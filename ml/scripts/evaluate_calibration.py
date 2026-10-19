"""
Measure whether the model's score behaves like a probability.

The interface calls the model's output a "model score" and not a confidence,
because a sigmoid output is not automatically a calibrated probability. That is
the correct label, but it has so far been a precaution rather than a finding.
This measures the thing the precaution is about.

A score is calibrated if, among the images scoring about 0.7, about 70 per cent
really are TB. The usual way to see this is a reliability curve: sort the scores
into bins, and plot the mean score in each bin against the fraction of those
images that are actually positive. A calibrated model follows the diagonal. A
model above the diagonal is underconfident, one below it is overconfident.

Three numbers summarise it:

    Brier score     mean squared error between score and outcome. Lower is
                    better. It mixes calibration and discrimination, so it is
                    reported alongside the reference value a model that always
                    predicts the base rate would achieve.
    ECE             expected calibration error: the average gap between score
                    and outcome frequency, weighted by how many images fall in
                    each bin. 0 is perfect.
    MCE             the largest such gap in any populated bin. It catches a
                    single badly wrong region that ECE would average away.

Measured on the validation split. The test split is deliberately not used: it
has been consulted three times already, and calibration is a property worth
knowing before deciding whether to show a percentage to a clinician, not a
final result to report.

Usage:
    python ml/scripts/evaluate_calibration.py
    python ml/scripts/evaluate_calibration.py --split validation --bins 10
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))

import preprocessing  # noqa: E402

MANIFEST = ROOT / "ml" / "artifacts" / "splits.csv"
MODELS = ROOT / "ml" / "models"
ARTIFACTS = ROOT / "ml" / "artifacts"
MODEL_VERSION = "tb_mobilenetv2_v1"

INK = "#1b1e17"
ACCENT = "#6b7f1f"
MUTED = "#9ba491"


def load_split(split):
    with open(MANIFEST, encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if r["split"] == split]
    images = np.stack([preprocessing.prepare(ROOT / r["filepath"]) for r in rows])
    labels = np.array([int(r["label"]) for r in rows])
    return images, labels


def bin_scores(labels, scores, bins):
    """Group the scores into equal-width bins and summarise each one.

    Equal width rather than equal count, because the question is about
    particular score ranges: "is 0.7 trustworthy" is a question about the bin
    near 0.7, and equal-count bins would move its boundaries with the data.
    """
    edges = np.linspace(0.0, 1.0, bins + 1)
    # The last bin includes 1.0, which digitize would otherwise place beyond
    # the final bin.
    index = np.clip(np.digitize(scores, edges[1:-1], right=False), 0, bins - 1)

    summary = []
    for b in range(bins):
        selected = index == b
        count = int(selected.sum())
        if not count:
            summary.append(
                {
                    "bin": b,
                    "lower": round(float(edges[b]), 3),
                    "upper": round(float(edges[b + 1]), 3),
                    "count": 0,
                    "mean_score": None,
                    "observed_rate": None,
                    "gap": None,
                }
            )
            continue

        mean_score = float(scores[selected].mean())
        observed = float(labels[selected].mean())
        summary.append(
            {
                "bin": b,
                "lower": round(float(edges[b]), 3),
                "upper": round(float(edges[b + 1]), 3),
                "count": count,
                "mean_score": round(mean_score, 4),
                "observed_rate": round(observed, 4),
                "gap": round(observed - mean_score, 4),
            }
        )
    return summary


def calibration_errors(summary, total):
    """Expected and maximum calibration error over the populated bins."""
    populated = [b for b in summary if b["count"]]
    if not populated:
        return None, None
    ece = sum(b["count"] / total * abs(b["gap"]) for b in populated)
    mce = max(abs(b["gap"]) for b in populated)
    return round(float(ece), 4), round(float(mce), 4)


def draw(summary, labels, scores, brier, baseline_brier, ece, destination, split):
    figure, (left, right) = plt.subplots(1, 2, figsize=(11.0, 4.8))

    populated = [b for b in summary if b["count"]]
    xs = [b["mean_score"] for b in populated]
    ys = [b["observed_rate"] for b in populated]
    sizes = [max(18, b["count"] * 6) for b in populated]

    left.plot(
        [0, 1], [0, 1], linestyle="--", linewidth=1, color=MUTED, label="Perfectly calibrated"
    )
    left.plot(xs, ys, color=ACCENT, linewidth=1.4, zorder=2)
    left.scatter(
        xs, ys, s=sizes, color=ACCENT, zorder=3, label="Observed, sized by images in bin"
    )
    left.set_xlabel("Mean model score in bin")
    left.set_ylabel("Fraction actually TB")
    left.set_title(
        f"Reliability curve, {split} split\nabove the line is underconfident",
        fontsize=10.5,
        loc="left",
        color=INK,
    )
    left.set_xlim(0, 1)
    left.set_ylim(0, 1)
    left.legend(fontsize=8, loc="upper left")
    left.spines[["top", "right"]].set_visible(False)

    # Where the scores actually fall. A reliability curve is easy to misread
    # without knowing that most images sit at one end.
    right.hist(
        scores[labels == 0],
        bins=20,
        range=(0, 1),
        alpha=0.75,
        color=MUTED,
        label="Actually normal",
    )
    right.hist(
        scores[labels == 1],
        bins=20,
        range=(0, 1),
        alpha=0.75,
        color=ACCENT,
        label="Actually TB",
    )
    right.set_xlabel("Model score")
    right.set_ylabel("Images")
    right.set_title(
        f"Where the scores fall\nBrier {brier:.4f}, against "
        f"{baseline_brier:.4f} for the base rate alone",
        fontsize=10.5,
        loc="left",
        color=INK,
    )
    right.legend(fontsize=8)
    right.spines[["top", "right"]].set_visible(False)

    figure.tight_layout()
    figure.savefig(destination, dpi=150)
    plt.close(figure)


def verdict(ece, mce, brier, baseline_brier):
    """Say plainly whether a percentage could honestly be shown to a clinician."""
    if brier >= baseline_brier:
        return (
            "The score carries no more information about the outcome than the base "
            "rate does. It must not be presented as a probability."
        )
    if ece <= 0.05 and mce <= 0.15:
        return (
            f"Calibration error is small: ECE {ece:.4f}, worst bin {mce:.4f}. The "
            "score tracks the observed rate closely enough that showing it as an "
            "approximate probability could be defended, though the validation split "
            "is small and this should be confirmed on held-out data first."
        )
    return (
        f"The score is not calibrated: ECE {ece:.4f} and a worst bin off by "
        f"{mce:.4f}. Displaying it as a percentage would assert an accuracy it does "
        "not have, which is why the interface labels it a model score and reports "
        "AUC instead. Calibrating it, by Platt scaling or isotonic regression fitted "
        "on validation, is recorded as future work."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--split", default="validation", choices=["train", "validation", "test"]
    )
    parser.add_argument("--bins", type=int, default=10)
    args = parser.parse_args()

    model_path = MODELS / f"{MODEL_VERSION}.keras"
    if not model_path.exists():
        raise SystemExit(f"No trained model at {model_path}.")

    import keras

    print(f"model  {MODEL_VERSION}")
    print(f"split  {args.split}")
    images, labels = load_split(args.split)
    scores = keras.models.load_model(model_path).predict(images, verbose=0).ravel()

    brier = float(np.mean((scores - labels) ** 2))
    base_rate = float(labels.mean())
    # What a model that ignored the image and always predicted the base rate
    # would score. Without it a Brier score is a number with no scale.
    baseline_brier = float(np.mean((base_rate - labels) ** 2))

    summary = bin_scores(labels, scores, args.bins)
    ece, mce = calibration_errors(summary, len(labels))
    statement = verdict(ece, mce, brier, baseline_brier)

    print(f"\n  images                       {len(labels)}")
    print(f"  base rate                    {base_rate:.4f}")
    print(f"  Brier score                  {brier:.4f}")
    print(f"  Brier, base rate only        {baseline_brier:.4f}")
    print(f"  expected calibration error   {ece:.4f}")
    print(f"  worst populated bin          {mce:.4f}")
    print(f"\n  {statement}")

    print("\n  bin          images   mean score   actually TB      gap")
    for b in summary:
        if not b["count"]:
            continue
        print(
            f"  {b['lower']:.1f} - {b['upper']:.1f}   {b['count']:>6}"
            f"   {b['mean_score']:>10.4f}   {b['observed_rate']:>11.4f}"
            f"   {b['gap']:>+7.4f}"
        )

    figure = ARTIFACTS / "calibration.png"
    draw(summary, labels, scores, brier, baseline_brier, ece, figure, args.split)

    payload = {
        "model_version": MODEL_VERSION,
        "split": args.split,
        "images": int(len(labels)),
        "bins": args.bins,
        "base_rate": round(base_rate, 4),
        "brier_score": round(brier, 4),
        "brier_score_base_rate_only": round(baseline_brier, 4),
        "expected_calibration_error": ece,
        "maximum_calibration_error": mce,
        "interpretation": statement,
        "note": (
            "Measured on the validation split. The test split was deliberately not "
            "used: it has been consulted three times already, and calibration is "
            "something to know before deciding whether to show a percentage to a "
            "clinician rather than a final result to report."
        ),
        "bins_detail": summary,
    }
    destination = ARTIFACTS / "calibration.json"
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\n  summary -> {destination.relative_to(ROOT)}")
    print(f"  figure  -> {figure.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
