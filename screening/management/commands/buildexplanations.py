"""
Build the visual explanation for records that are still waiting for one.

A batch upload defers its maps. An occlusion map is several hundred forward
passes, and building twenty of them while someone waits on the upload page
would spend minutes on images nobody has opened yet, so a batch stores the
predictions and leaves each map to be built when its case is first opened.

That is the right trade for throughput and the wrong state to be in when the
worklist is about to be shown to somebody. A case that has never been opened
displays "building the explanation" instead of a heatmap, and NFR-08 asks for
every result to be shown with the picture that produced it. Opening
seventeen cases by hand to warm them up is not a procedure.

    python manage.py buildexplanations            # build every pending map
    python manage.py buildexplanations --dry-run  # list what is waiting
    python manage.py buildexplanations --retry    # include ones that failed

Failed records are left alone unless asked for, because a map that failed once
usually fails the same way again and the run should not be spent on it. The
reason is on the record either way.
"""

import time

from django.core.management.base import BaseCommand

from screening.models import PredictionRecord


class Command(BaseCommand):
    help = "Build the explanation for screenings that are still waiting for one."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the records that are waiting without building anything.",
        )
        parser.add_argument(
            "--retry",
            action="store_true",
            help="Also rebuild records whose explanation previously failed.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Stop after this many records.",
        )

    def handle(self, *args, **options):
        # Imported here rather than at module level: building an explanation
        # loads TensorFlow, and `manage.py help` should not.
        from screening.views import build_explanation

        wanted = [PredictionRecord.ExplanationStatus.PENDING]
        if options["retry"]:
            wanted.append(PredictionRecord.ExplanationStatus.FAILED)

        waiting = PredictionRecord.objects.filter(explanation_status__in=wanted).order_by(
            "created_at"
        )
        if options["limit"]:
            waiting = waiting[: options["limit"]]
        waiting = list(waiting)

        if not waiting:
            self.stdout.write(self.style.SUCCESS("\n  Every record already has its map.\n"))
            return

        self.stdout.write(f"\n  {len(waiting)} record(s) waiting for an explanation\n")
        if options["dry_run"]:
            for record in waiting:
                self.stdout.write(
                    f"    {record.patient_reference:16} {record.created_at:%Y-%m-%d %H:%M}  "
                    f"{record.explanation_status}"
                )
            self.stdout.write("\n  Nothing was built. Run again without --dry-run.\n")
            return

        built = failed = 0
        started = time.perf_counter()
        for position, record in enumerate(waiting, start=1):
            at = time.perf_counter()
            build_explanation(record)
            record.refresh_from_db()
            took = time.perf_counter() - at
            if record.explanation_status == PredictionRecord.ExplanationStatus.GENERATED:
                built += 1
                mark, note = self.style.SUCCESS("built "), f"{took:5.1f}s"
            else:
                failed += 1
                mark = self.style.ERROR("failed")
                note = "see the log for the reason"
            self.stdout.write(
                f"    {position:>3}/{len(waiting)}  {mark}  "
                f"{record.patient_reference:16} {note}"
            )

        total = time.perf_counter() - started
        self.stdout.write(f"\n  {built} built, {failed} failed, {total:.1f}s in total\n")
