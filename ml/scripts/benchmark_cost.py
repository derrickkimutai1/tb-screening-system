"""What it costs to run this for a clinic, in the units the platform bills in.

Derived rather than measured: it reads the timing artefacts and converts them
into the resource-seconds the hosting platform charges for. Nothing here needs
a price, which is deliberate. Published per-second rates change and are quoted
differently by region, so the answer is given as a fraction of the free
monthly grant, which is documented by the platform itself and is the figure
that actually decides whether a facility pays anything at all.

The grant, per subscription per calendar month: 180,000 vCPU-seconds, 360,000
GiB-seconds and 2 million requests. The application runs on one virtual
processor and 2 GiB, and scales to zero when idle, so it consumes nothing
between screenings.

    .venv/Scripts/python.exe ml/scripts/benchmark_cost.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "ml" / "artifacts"

VCPU = 1
GIB = 2
GRANT_VCPU_SECONDS = 180_000
GRANT_GIB_SECONDS = 360_000
GRANT_REQUESTS = 2_000_000

# A screening is not one request. The result page, its stylesheet on a cold
# cache, the radiograph, the heatmap and the occlusion map are all fetched.
REQUESTS_PER_SCREENING = 8

# Scale to zero is what makes this cheap, and it is also why the first request
# after a quiet period pays for the container to start. Measured on the
# deployed instance.
COLD_START_SECONDS = 19.3
COLD_STARTS_PER_DAY = 4

VOLUMES = (20, 50, 100)
DAYS = 30


def read(name):
    path = ARTIFACTS / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main():
    timing = read("response_times.json")
    if timing is None:
        raise SystemExit("no response_times.json; run the timing harness first")
    seconds = timing["median_seconds"]

    rows = []
    for per_day in VOLUMES:
        active = per_day * seconds * DAYS
        starts = COLD_STARTS_PER_DAY * COLD_START_SECONDS * DAYS
        total = active + starts
        vcpu_s = total * VCPU
        gib_s = total * GIB
        requests = per_day * REQUESTS_PER_SCREENING * DAYS
        rows.append(
            {
                "screenings_per_day": per_day,
                "screenings_per_month": per_day * DAYS,
                "active_seconds_per_month": round(total),
                "active_hours_per_month": round(total / 3600, 1),
                "vcpu_seconds": round(vcpu_s),
                "gib_seconds": round(gib_s),
                "requests": requests,
                "share_of_vcpu_grant": round(vcpu_s / GRANT_VCPU_SECONDS, 4),
                "share_of_gib_grant": round(gib_s / GRANT_GIB_SECONDS, 4),
                "share_of_request_grant": round(requests / GRANT_REQUESTS, 5),
                "within_free_grant": (
                    vcpu_s <= GRANT_VCPU_SECONDS
                    and gib_s <= GRANT_GIB_SECONDS
                    and requests <= GRANT_REQUESTS
                ),
            }
        )

    # The binding constraint is memory-seconds, because the app holds 2 GiB.
    ceiling_seconds = min(GRANT_VCPU_SECONDS / VCPU, GRANT_GIB_SECONDS / GIB)
    overhead = COLD_STARTS_PER_DAY * COLD_START_SECONDS * DAYS
    screenings_in_grant = int((ceiling_seconds - overhead) / seconds)

    result = {
        "measures": ("hosting cost as a share of the platform's published free monthly grant"),
        "derived_from": {
            "median_screening_seconds": seconds,
            "source": "ml/artifacts/response_times.json",
            "cold_start_seconds": COLD_START_SECONDS,
            "cold_starts_assumed_per_day": COLD_STARTS_PER_DAY,
            "requests_assumed_per_screening": REQUESTS_PER_SCREENING,
        },
        "instance": {"vcpu": VCPU, "memory_gib": GIB, "scales_to_zero": True},
        "free_grant_per_subscription_per_month": {
            "vcpu_seconds": GRANT_VCPU_SECONDS,
            "gib_seconds": GRANT_GIB_SECONDS,
            "requests": GRANT_REQUESTS,
        },
        "binding_constraint": (
            "GiB-seconds, because the instance holds 2 GiB and memory bills at "
            "twice the processor"
        ),
        "screenings_per_month_within_grant": screenings_in_grant,
        "volumes": rows,
        "always_on_comparison": {
            "seconds_per_month": 30 * 24 * 3600,
            "vcpu_seconds": 30 * 24 * 3600 * VCPU,
            "gib_seconds": 30 * 24 * 3600 * GIB,
            "times_over_gib_grant": round((30 * 24 * 3600 * GIB) / GRANT_GIB_SECONDS, 1),
            "note": (
                "Keeping one replica running permanently, which is what scaling to zero avoids."
            ),
        },
        "note": (
            "No currency figure is given. Published per-second rates differ by "
            "region and change, and the question a facility actually asks is "
            "whether the service costs anything, which the free grant settles. "
            "The grant figures are the platform's own published allowance. "
            "Cold starts are included because scaling to zero trades a charge "
            "for a wait, and leaving them out would understate the usage of a "
            "clinic that screens in short bursts through the day."
        ),
    }

    out = ARTIFACTS / "cost_benchmark.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8", newline="")

    print(f"median screening {seconds}s on 1 vCPU / {GIB} GiB, scaling to zero\n")
    print(f"{'per day':>8}  {'active h/mo':>11}  {'GiB-s':>9}  {'of grant':>9}  within grant")
    for r in rows:
        print(
            f"{r['screenings_per_day']:>8}  {r['active_hours_per_month']:>11}  "
            f"{r['gib_seconds']:>9}  {r['share_of_gib_grant'] * 100:>8.1f}%  "
            f"{'yes' if r['within_free_grant'] else 'NO'}"
        )
    print(f"\nfree grant covers about {screenings_in_grant:,} screenings a month")
    over = result["always_on_comparison"]["times_over_gib_grant"]
    print(f"always-on would be {over}x the grant")
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
