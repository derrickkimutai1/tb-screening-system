"""
Fill the system with screenings to demonstrate it against.

A demonstration of a worklist needs a worklist. Sixteen cases, all awaiting
review and nearly all high suspicion, show neither the triage spread nor the
review workflow, and a dashboard built on them looks like a dashboard of
nothing.

Every record this makes is a real screening. The images are real radiographs
from the project's own datasets, they go through the upload view like any
other, and the score, the label and the triage level are the model's own
output. Nothing here writes a prediction by hand, because demonstration data
that was typed rather than computed would misrepresent the system in the one
place somebody is looking at it.

The case references are non-identifying, as the system requires, and the
images are from public research archives rather than from patients.

Usage:
    python scripts/seed_demo_cases.py
    python scripts/seed_demo_cases.py --count 24 --clinic "Kenyatta National Hospital"
    python scripts/seed_demo_cases.py --remove        # take them away again
"""

import argparse
import csv
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Everything this script creates carries it, so --remove knows what is its own
# and cannot take away a real screening somebody made.
PREFIX = "KNH-26"
SEED = 42


def balanced(rows, count):
    """An even spread across both archives and both labels, chosen the same way
    every run so a rerun produces the same demonstration."""
    groups = {}
    for row in rows:
        groups.setdefault((row["source"], row["label"]), []).append(row)

    rng = random.Random(SEED)
    for items in groups.values():
        rng.shuffle(items)

    chosen, index = [], 0
    keys = sorted(groups)
    while len(chosen) < count:
        taken_any = False
        for key in keys:
            if index < len(groups[key]) and len(chosen) < count:
                chosen.append(groups[key][index])
                taken_any = True
        if not taken_any:
            break
        index += 1
    return chosen


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--clinic", default="Kenyatta National Hospital")
    parser.add_argument(
        "--screener",
        default="derrick.kim46@gmail.com",
        help="the account the screenings are attributed to",
    )
    parser.add_argument(
        "--remove",
        action="store_true",
        help=f"delete every case this script made, by its {PREFIX} reference",
    )
    args = parser.parse_args()

    import django

    django.setup()

    from django.conf import settings

    if "testserver" not in settings.ALLOWED_HOSTS:
        settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]

    from django.contrib.auth import get_user_model
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test import Client
    from django.urls import reverse

    from screening.models import Facility, PredictionRecord, profile_for

    existing = PredictionRecord.objects.filter(patient_reference__startswith=PREFIX)

    if args.remove:
        count = existing.count()
        for record in existing:
            for field in (record.xray_image, record.explanation_image):
                if field:
                    (Path(settings.MEDIA_ROOT) / field.name).unlink(missing_ok=True)
        existing.delete()
        print(f"removed {count} seeded cases")
        return 0

    if existing.exists():
        print(f"{existing.count()} seeded cases already present.")
        print("Run with --remove first to replace them.")
        return 0

    try:
        screener = get_user_model().objects.get(email=args.screener)
    except get_user_model().DoesNotExist:
        raise SystemExit(f"No account for {args.screener}.") from None

    clinic, _ = Facility.objects.get_or_create(name=args.clinic)
    profile = profile_for(screener)
    if profile.facility != clinic:
        raise SystemExit(
            f"{args.screener} is at {profile.facility}, not {clinic}. "
            "Screenings land at the screener's clinic, so pick one who works there."
        )

    with open(ROOT / "ml" / "artifacts" / "splits.csv", encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if (ROOT / r["filepath"]).is_file()]

    chosen = balanced(rows, args.count)
    if len(chosen) < args.count:
        print(f"only {len(chosen)} readable images available")

    client = Client()
    client.force_login(screener)

    print(f"screening {len(chosen)} radiographs into {clinic}\n", flush=True)
    made = []
    for index, row in enumerate(chosen, start=1):
        path = ROOT / row["filepath"]
        reference = f"{PREFIX}-{index:04d}"
        upload = SimpleUploadedFile(path.name, path.read_bytes(), "image/png")
        response = client.post(
            reverse("screening:upload"),
            {"patient_reference": reference, "xray_image": upload},
        )
        if response.status_code != 302:
            print(f"  {reference}  refused ({response.status_code})")
            continue
        record = PredictionRecord.objects.get(patient_reference=reference)
        made.append(record)
        print(
            f"  {reference}  {record.get_triage_level_display():17s} "
            f"{record.tb_probability:.4f}  ({row['source']})",
            flush=True,
        )

    # A worklist where nothing has ever been decided does not show the review
    # workflow. Roughly a third are reviewed, oldest first, as a clinic would
    # work through a queue rather than at random.
    reviewers = [
        u
        for u in get_user_model().objects.all()
        if profile_for(u).may_review and profile_for(u).facility == clinic
    ]
    if reviewers:
        from screening.models import ReviewNote

        decided = made[: max(1, len(made) // 3)]
        for record in decided:
            reviewer = reviewers[0]
            follow_up = record.triage_level == PredictionRecord.TriageLevel.HIGH
            status = (
                PredictionRecord.ReviewStatus.FOLLOW_UP
                if follow_up
                else PredictionRecord.ReviewStatus.REVIEWED
            )
            ReviewNote.objects.create(
                record=record,
                reviewer=reviewer,
                reviewer_name=profile_for(reviewer).display_name,
                note=(
                    "Referred for confirmatory testing."
                    if follow_up
                    else "Reviewed; no follow-up indicated on this film."
                ),
                status_set=status,
            )
            record.review_status = status
            record.save(update_fields=["review_status", "updated_at"])
        print(f"\nreviewed {len(decided)} of them, so the queue is not all pending")

    total = PredictionRecord.objects.count()
    print(f"\n{len(made)} cases added; {total} in the system")
    print(f"remove them again with: python {Path(__file__).name} --remove")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
