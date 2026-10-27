"""
Measure how long a screening takes, end to end, as NFR-01 asks.

    "At least 90 percent of single-image screenings shall return a complete
    result, including heatmap generation, within 10 seconds on a CPU-only
    machine with 8 GB RAM, measured over 50 consecutive uploads."

Two things that requirement implies are easy to get wrong, so they are stated
here rather than left to the reader.

The clock covers both halves. The explanation is no longer built during the
upload: the record is stored first and the map is built when somebody opens
the case. A timing that measured only the upload would look excellent and
would not be what the requirement asks about, so each screening here is timed
as upload plus explanation, which is what a clinician waits for in total.

The requests go through the application, not around it. Django's test client
runs the real middleware, views, forms, model and database, so everything the
requirement covers is included. What it leaves out is the network hop between
a browser and the server, which on a facility machine serving itself is
loopback and negligible, and the browser's own rendering.

The records this creates are deleted afterwards, along with their images, so
measuring does not leave fifty screenings in the caseload.

Usage:
    python scripts/measure_screening_time.py
    python scripts/measure_screening_time.py --uploads 50
"""

import argparse
import csv
import json
import os
import platform
import sys
import time
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REQUIREMENT_SECONDS = 10.0
REQUIREMENT_SHARE = 0.90
ARTIFACTS = ROOT / "ml" / "artifacts"


def machine():
    """What the figures below describe, since the requirement names hardware."""
    total_ram_gb = None
    try:
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = Status()
        status.dwLength = ctypes.sizeof(Status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        total_ram_gb = round(status.ullTotalPhys / (1024**3), 1)
    except Exception:
        pass

    return {
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "python": platform.python_version(),
        "total_ram_gb": total_ram_gb,
        "gpu": "none; TensorFlow has no GPU support on native Windows",
    }


def radiographs(count):
    """Real images from the dataset, in manifest order so a rerun matches."""
    manifest = ARTIFACTS / "splits.csv"
    with open(manifest, encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle)]
    chosen = [ROOT / r["filepath"] for r in rows]
    chosen = [p for p in chosen if p.is_file()][:count]
    if len(chosen) < count:
        raise SystemExit(f"Only {len(chosen)} readable images; {count} were asked for.")
    return chosen


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--uploads", type=int, default=50)
    args = parser.parse_args()

    import django

    django.setup()

    from django.conf import settings

    # Django's test client sends Host: testserver. The test runner allows that
    # automatically; this script is not the test runner, so the request is
    # rejected before it reaches a view. Allowing it here affects only this
    # process, and nothing is listening on a socket for anyone else to reach.
    if "testserver" not in settings.ALLOWED_HOSTS:
        settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]

    from django.contrib.auth import get_user_model
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test import Client
    from django.urls import reverse

    from screening.models import PredictionRecord, Profile, profile_for
    from screening.services.predict import PredictionEngine

    operator, created = get_user_model().objects.get_or_create(
        username="timing-operator", defaults={"email": "timing@example.invalid"}
    )
    profile = profile_for(operator)
    profile.role = Profile.Role.CLINICIAN
    profile.save()

    client = Client()
    client.force_login(operator)

    images = radiographs(args.uploads)

    # Load the model before the clock starts. NFR-03 requires it to be loaded
    # once at startup and reused, so including that one-off cost in the first
    # screening would measure something the requirement already excludes.
    print("loading the model...", flush=True)
    PredictionEngine().model()

    print(f"screening {len(images)} radiographs, one at a time\n", flush=True)
    created_ids = []
    results = []

    try:
        for index, path in enumerate(images, start=1):
            payload = SimpleUploadedFile(path.name, path.read_bytes(), "image/png")

            started = time.perf_counter()
            response = client.post(
                reverse("screening:upload"),
                {"patient_reference": f"TIMING-{index:03d}", "xray_image": payload},
            )
            upload_seconds = time.perf_counter() - started
            if response.status_code != 302:
                print(f"  {index:3d}  refused ({response.status_code}), skipped")
                continue

            case_id = response["Location"].rstrip("/").rsplit("/", 1)[-1]
            created_ids.append(case_id)

            started_map = time.perf_counter()
            client.post(reverse("screening:case_explanation", args=[case_id]))
            explanation_seconds = time.perf_counter() - started_map

            total = upload_seconds + explanation_seconds
            results.append(
                {
                    "image": path.name,
                    "upload_seconds": round(upload_seconds, 3),
                    "explanation_seconds": round(explanation_seconds, 3),
                    "total_seconds": round(total, 3),
                }
            )
            flag = " " if total <= REQUIREMENT_SECONDS else " OVER"
            print(
                f"  {index:3d}  upload {upload_seconds:5.2f}s  "
                f"explanation {explanation_seconds:5.2f}s  "
                f"total {total:5.2f}s{flag}",
                flush=True,
            )
    finally:
        # Measuring must not leave fifty screenings in the caseload.
        removed = PredictionRecord.objects.filter(case_id__in=created_ids)
        for record in removed:
            for field in (record.xray_image, record.explanation_image):
                if field:
                    target = Path(settings.MEDIA_ROOT) / field.name
                    target.unlink(missing_ok=True)
        count = removed.count()
        removed.delete()
        if created:
            # Deactivated, not deleted. Every screening above wrote an audit
            # row naming this account, and the actor column is SET_NULL, so
            # deleting it rewrites those rows after they were sealed. That is
            # what broke a hundred of them the first time this script ran.
            operator.is_active = False
            operator.save(update_fields=["is_active"])
        print(f"\ncleaned up {count} records")

    if not results:
        raise SystemExit("No screenings completed; nothing to report.")

    totals = sorted(r["total_seconds"] for r in results)
    within = sum(1 for t in totals if t <= REQUIREMENT_SECONDS)
    share = within / len(totals)
    median = totals[len(totals) // 2]
    p90 = totals[max(0, int(len(totals) * 0.90) - 1)]
    met = share >= REQUIREMENT_SHARE

    print()
    print(f"  screenings            {len(totals)}")
    print(f"  median                {median:.2f}s")
    print(f"  90th percentile       {p90:.2f}s")
    print(f"  slowest               {totals[-1]:.2f}s")
    print(
        f"  within {REQUIREMENT_SECONDS:.0f}s            "
        f"{within} of {len(totals)} ({share:.1%})"
    )
    print()
    print(f"  NFR-01 {'met' if met else 'NOT met'}")

    summary = {
        "requirement": (
            "NFR-01: at least 90% of single-image screenings return a complete "
            "result, including heatmap generation, within 10 seconds"
        ),
        "machine": machine(),
        "screenings": len(totals),
        "median_seconds": median,
        "p90_seconds": p90,
        "slowest_seconds": totals[-1],
        "within_requirement": within,
        "share_within_requirement": round(share, 4),
        "requirement_met": met,
        "note": (
            "Timed as upload plus explanation, because the explanation is built "
            "when a case is first opened rather than during the upload, and the "
            "requirement covers a complete result including heatmap generation. "
            "Measured through Django's test client, which runs the real "
            "middleware, views, model and database but not the network hop or "
            "browser rendering."
        ),
        "per_screening": results,
    }
    destination = ARTIFACTS / "response_times.json"
    destination.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n  summary -> {destination.relative_to(ROOT)}")

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.figure(figsize=(7, 4.2))
        plt.hist(totals, bins=15, edgecolor="white")
        plt.axvline(
            REQUIREMENT_SECONDS,
            color="tab:red",
            linestyle="--",
            linewidth=1.5,
            label=f"NFR-01 limit ({REQUIREMENT_SECONDS:.0f}s)",
        )
        plt.axvline(median, color="black", linewidth=1.2, label=f"Median = {median:.2f}s")
        plt.xlabel("Seconds from upload to a complete result with heatmap")
        plt.ylabel("Screenings")
        plt.title(f"Screening response time over {len(totals)} consecutive uploads")
        plt.legend(fontsize=8)
        plt.tight_layout()
        figure = ARTIFACTS / "response_times.png"
        plt.savefig(figure, dpi=150)
        plt.close()
        print(f"  figure  -> {figure.relative_to(ROOT)}")
    except ImportError:
        pass

    return 0 if met else 1


if __name__ == "__main__":
    raise SystemExit(main())
