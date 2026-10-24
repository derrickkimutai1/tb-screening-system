"""
Check that the audit trail has not been altered.

Each row carries a hash of its own contents together with the hash of the row
before it, so changing a field or removing a row breaks that row's hash and
every hash after it. This walks the chain and says where it first fails.

    python manage.py verifyaudit

Exits non-zero when anything is wrong, so it can be run on a schedule and
noticed rather than read.
"""

from django.core.management.base import BaseCommand

from screening.models import AccessEvent


class Command(BaseCommand):
    help = "Verify the audit trail has not been altered."

    def add_arguments(self, parser):
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Say nothing unless something is wrong.",
        )

    def handle(self, *args, **options):
        checked, problems = AccessEvent.verify_chain()

        if not checked:
            if not options["quiet"]:
                self.stdout.write("The audit trail is empty. Nothing to verify.")
            return

        if problems:
            self.stdout.write(
                self.style.ERROR(f"\n  {len(problems)} problem(s) in {checked} audit rows:\n")
            )
            for problem in problems:
                self.stdout.write(f"    {problem}")
            self.stdout.write(
                "\n  A broken chain means a row was changed or deleted after it was\n"
                "  written. The first row listed is where the trail stops being\n"
                "  trustworthy; everything before it still verifies.\n"
            )
            raise SystemExit(1)

        if not options["quiet"]:
            self.stdout.write(
                self.style.SUCCESS(f"\n  {checked} audit rows verified. The chain is intact.\n")
            )
