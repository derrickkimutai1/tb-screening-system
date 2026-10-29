"""
Remove radiographs and overlays that no record points at.

Deleting a PredictionRecord removes the row and leaves its files behind:
Django has not deleted the file behind a FileField since 1.3, because a
rollback would otherwise destroy data that is still referenced. The result is
that a clinic which has removed a case keeps its chest X-ray on disk
indefinitely, under a name nothing can look up. That is a retention problem
before it is a tidiness one - the image is still a patient's radiograph when
the record describing it has gone.

    python manage.py prunemedia            # list what is unreferenced
    python manage.py prunemedia --delete   # remove it

Listing is the default because this destroys files that cannot be recovered.

Files written in the last hour are left alone whatever is asked. An upload
writes the image before the row describing it is committed, so a file with no
record may be a case that is halfway through being screened rather than one
that has been removed.
"""

from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from screening.models import PredictionRecord

SETTLING_PERIOD = timedelta(hours=1)


class Command(BaseCommand):
    help = "List, or remove, media files that no screening record refers to."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Remove the files. Without this the command only lists them.",
        )

    def handle(self, *args, **options):
        root = Path(settings.MEDIA_ROOT)
        if not root.exists():
            self.stdout.write("There is no media directory. Nothing to do.")
            return

        referenced = set()
        fields = ("xray_image", "explanation_image", "comparison_image")
        for stored in PredictionRecord.objects.values_list(*fields):
            for name in stored:
                if name:
                    referenced.add((root / name).resolve())

        cutoff = timezone.now() - SETTLING_PERIOD
        unreferenced, recent = [], 0
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.resolve() in referenced:
                continue
            written = timezone.datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.get_current_timezone()
            )
            if written > cutoff:
                recent += 1
                continue
            unreferenced.append(path)

        if not unreferenced:
            self.stdout.write(
                self.style.SUCCESS("\n  Every stored file belongs to a record.\n")
            )
            return

        total = sum(path.stat().st_size for path in unreferenced)
        for path in unreferenced:
            self.stdout.write(f"    {path.relative_to(root)}")

        summary = f"{len(unreferenced)} files, {total / 1048576:.1f} MB, no record"
        if recent:
            summary += f"; {recent} more written within the hour and left alone"

        if not options["delete"]:
            self.stdout.write(
                f"\n  {summary}.\n\n"
                "  Nothing was removed. Run again with --delete to remove them.\n"
            )
            return

        removed, failed = 0, []
        for path in unreferenced:
            try:
                path.unlink()
                removed += 1
            except OSError as problem:
                failed.append(f"{path.relative_to(root)}: {problem}")

        for directory in sorted(root.rglob("*"), reverse=True):
            # Dated folders are created by the upload path and are of no use
            # once empty. rmdir refuses a directory that still holds anything.
            if directory.is_dir():
                try:
                    directory.rmdir()
                except OSError:
                    pass

        if failed:
            self.stdout.write(self.style.ERROR(f"\n  {len(failed)} could not be removed:"))
            for problem in failed:
                self.stdout.write(f"    {problem}")

        self.stdout.write(
            self.style.SUCCESS(f"\n  Removed {removed} files, {total / 1048576:.1f} MB.\n")
        )
