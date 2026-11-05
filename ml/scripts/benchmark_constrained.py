"""Time a screening on one processor core.

NFR-01 was measured on the development machine, which has twelve cores and
eleven gigabytes of memory. A clinic buying a computer does not have that, and
"it is fast on my laptop" answers no question a panel would ask.

This pins the process to a single core and screens the same way the
application does - upload, quality check, model, then the explanation built on
first open - so the figure covers a complete result rather than the forward
pass alone.

Memory is reported rather than capped. Capping it on Windows needs a job
object, and a run that is killed partway reports nothing; the peak is measured
instead, which answers the same question: how much does it need.

    .venv/Scripts/python.exe ml/scripts/benchmark_constrained.py
"""

import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

SCREENINGS = int(os.environ.get("SCREENINGS", "20"))


def pin_to_one_core():
    """Restrict this process to a single core, and say which."""
    try:
        import psutil

        process = psutil.Process()
        process.cpu_affinity([0])
        return len(process.cpu_affinity())
    except Exception as error:  # pragma: no cover - reported, not raised
        print(f"  could not pin: {error}")
        return None


def peak_memory_mb():
    try:
        import psutil

        return round(psutil.Process().memory_info().peak_wset / (1024 * 1024), 1)
    except Exception:
        return None


def main():
    cores = pin_to_one_core()
    print(f"cores available to this process: {cores}")

    import django

    django.setup()

    from django.contrib.auth import get_user_model
    from django.test import Client
    from django.test.utils import setup_test_environment

    from screening.models import Facility, PredictionRecord, Profile

    setup_test_environment()

    films = sorted((ROOT / "data/raw/montgomery/MontgomerySet/CXR_png").glob("*.png"))
    if not films:
        sys.exit("no radiographs to screen")

    User = get_user_model()
    user = User.objects.filter(profile__role=Profile.Role.RADIOGRAPHER).first()
    if user is None:
        sys.exit("no radiographer account to screen as")
    print(f"screening as {user.email}, {Facility.objects.count()} facilities")

    client = Client()
    client.force_login(user)

    timings = []
    created = []
    for index in range(SCREENINGS):
        film = films[index % len(films)]
        reference = f"BENCH-{index:03d}"
        started = time.perf_counter()
        with film.open("rb") as handle:
            response = client.post(
                "/", {"patient_reference": reference, "xray_image": handle}, follow=True
            )
        record = PredictionRecord.objects.filter(patient_reference=reference).first()
        if record is not None:
            # The explanation is built when a case is first opened, and the
            # requirement covers a complete result, so it is inside the timing.
            client.post(f"/cases/{record.case_id}/explanation/", {})
            created.append(record)
        elapsed = time.perf_counter() - started
        timings.append(round(elapsed, 3))
        print(f"  {index + 1:3d}/{SCREENINGS}  {elapsed:6.2f}s  HTTP {response.status_code}")

    # The benchmark must not leave a hundred records in the caseload it was
    # run against.
    for record in created:
        for name in (record.xray_image, record.explanation_image, record.comparison_image):
            if name:
                path = Path(name.path)
                if path.exists():
                    path.unlink()
        record.delete()
    print(f"removed {len(created)} benchmark records")

    timings.sort()
    result = {
        "measures": "one complete screening: upload, quality check, model and explanation",
        "screenings": len(timings),
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cores_on_machine": os.cpu_count(),
            "cores_available_to_process": cores,
            "peak_memory_mb": peak_memory_mb(),
            "gpu": "none; TensorFlow has no GPU support on native Windows",
        },
        "median_seconds": round(statistics.median(timings), 3),
        "p90_seconds": round(timings[int(len(timings) * 0.9) - 1], 3),
        "slowest_seconds": timings[-1],
        "fastest_seconds": timings[0],
        "within_ten_seconds": sum(1 for t in timings if t <= 10),
        "model_file_mb": round(
            (ROOT / "ml/models/tb_mobilenetv2_v1.keras").stat().st_size / (1024 * 1024), 1
        )
        if (ROOT / "ml/models/tb_mobilenetv2_v1.keras").exists()
        else None,
        "note": (
            "Pinned to a single core so the figure describes a machine a clinic "
            "could actually buy, rather than the twelve-core development laptop "
            "NFR-01 was measured on. Memory is the measured peak of this process, "
            "not a cap."
        ),
    }

    out = ROOT / "ml/artifacts/constrained_benchmark.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8", newline="")
    print(
        f"\nmedian {result['median_seconds']}s  p90 {result['p90_seconds']}s  "
        f"peak {result['machine']['peak_memory_mb']} MB"
    )
    print(f"-> {out}")


if __name__ == "__main__":
    main()
