"""
Compare two explanation methods on the same images, pair by pair.

Comparing two mean lifts says very little here. Montgomery carries only 58 TB
radiographs with hand-drawn lung masks, and lift varies far more between
images than between methods: one film where both methods score 3 moves either
mean more than a real difference between them would. Two separate means also
throw away the fact that both methods were measured on the same films.

Pairing keeps it. For each image the difference between the two lifts is taken,
and the question becomes whether those differences sit above zero. A bootstrap
over the images gives an interval for the mean difference, and the sign test
counts how often one method simply wins, which does not care how extreme the
outliers are.

An interval that includes zero means this data cannot tell the two apart. That
is a result, not a failure, and it is the honest thing to report when it
happens.

Usage:
    python ml/scripts/compare_explanations.py \\
        ml/artifacts/gradcam-...json ml/artifacts/occlusion-...json
"""

import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_SAMPLES = 10000
SEED = 42


def lifts_by_image(path):
    """The per-image lifts from one evaluation, keyed by filename."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    label = data.get("layer") or data.get("method")
    rows = {
        row["filename"]: row["lift"] for row in data["per_image"] if row["lift"] is not None
    }
    return label, rows, data


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("baseline", help="evaluation JSON for the method being replaced")
    parser.add_argument("candidate", help="evaluation JSON for the proposed method")
    args = parser.parse_args()

    baseline_name, baseline, baseline_data = lifts_by_image(args.baseline)
    candidate_name, candidate, _ = lifts_by_image(args.candidate)

    shared = sorted(set(baseline) & set(candidate))
    if not shared:
        raise SystemExit("The two evaluations share no images.")

    first = np.array([baseline[name] for name in shared])
    second = np.array([candidate[name] for name in shared])
    difference = second - first

    rng = np.random.default_rng(SEED)
    indices = rng.integers(0, len(shared), size=(BOOTSTRAP_SAMPLES, len(shared)))
    means = difference[indices].mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])

    wins = int((difference > 0).sum())
    ties = int((difference == 0).sum())

    print(f"images     {len(shared)} measured by both")
    print(f"baseline   {baseline_name}: lift {first.mean():.2f}")
    print(f"candidate  {candidate_name}: lift {second.mean():.2f}")
    print()
    print(f"  mean difference   {difference.mean():+.3f}  95% CI [{low:+.3f}, {high:+.3f}]")
    print(f"  candidate higher  {wins} of {len(shared)} images ({ties} tied)")
    print()

    if low > 0:
        verdict = "the candidate is better on this data"
    elif high < 0:
        verdict = "the candidate is worse on this data"
    else:
        verdict = (
            "this data cannot separate the two: the interval includes zero, so "
            "any difference claimed from the means alone would be noise"
        )
    print(f"  {verdict}")

    summary = {
        "baseline": {"source": str(args.baseline), "name": baseline_name},
        "candidate": {"source": str(args.candidate), "name": candidate_name},
        "images": len(shared),
        "split": baseline_data.get("split"),
        "baseline_lift_mean": round(float(first.mean()), 4),
        "candidate_lift_mean": round(float(second.mean()), 4),
        "mean_difference": round(float(difference.mean()), 4),
        "difference_ci_95": [round(float(low), 4), round(float(high), 4)],
        "candidate_higher_on": wins,
        "tied": ties,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "interpretation": verdict,
    }
    # Named for the split it covers, so a comparison on nine held-out images
    # cannot quietly replace one made over fifty-eight.
    destination = (
        ROOT
        / "ml"
        / "artifacts"
        / f"explanation_comparison-{baseline_data.get('split', 'unknown')}.json"
    )
    destination.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n  summary -> {destination.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
