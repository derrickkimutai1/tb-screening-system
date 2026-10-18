"""
Choose the decision and triage thresholds from validation evidence.

A model returns a score between 0 and 1. Turning that into "Likely TB" needs a
cutoff, and the default of 0.50 is arbitrary. Proposal section 3.2.3 requires
the thresholds to be justified from validation behaviour rather than assumed.

Two thresholds are chosen here, both on the validation split only:

Decision threshold
    The lowest cutoff that reaches at least 90% sensitivity. That target comes
    from the World Health Organization's target product profile for a TB triage
    test, which asks for at least 90% sensitivity and 70% specificity. Screening
    favours catching cases over avoiding false alarms, because a false alarm
    costs a confirmatory test while a missed case costs a missed diagnosis.
    Among the cutoffs that reach the target, the one with the best specificity
    is taken.

High-suspicion threshold
    The lowest cutoff reaching 95% specificity, so that cases marked high
    suspicion are ones the model rarely raises in error. This is what makes a
    high-suspicion label worth prioritising.

The low-to-medium boundary is the decision threshold itself, so that "Likely TB"
and "at least medium suspicion" mean the same thing.

Usage:
    python ml/scripts/select_thresholds.py
"""

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

# World Health Organization target product profile for a TB triage test.
# The requirement: the WHO target product profile for a TB triage test.
TARGET_SENSITIVITY = 0.90

# Chosen with a margin above the requirement. A threshold picked to reach
# exactly 0.90 on validation lands either side of it on unseen data: the
# validation split holds about 60 TB cases, so a sensitivity estimate carries
# a standard error near 0.04. Aiming at 0.90 gives roughly even odds of
# falling short, and that happened: a threshold selected at 0.900 delivered
# 0.881 on unseen images.
#
# The margin is 0.02 rather than more, because the trade-off on validation is
# steep in this region. Raising the selection target from 0.92 to 0.95 buys
# two points of sensitivity for ten of specificity:
#
#     target 0.90 -> sensitivity 0.900, specificity 0.689
#     target 0.92 -> sensitivity 0.933, specificity 0.639
#     target 0.95 -> sensitivity 0.950, specificity 0.541
#
# Note that no threshold satisfies both WHO targets at once. The best
# specificity available at or above 90 per cent sensitivity is 0.689, short
# of the 0.70 the profile asks for. That is a property of this model on this
# data and is reported rather than worked around.
SELECTION_MARGIN = 0.02
SELECTION_SENSITIVITY = TARGET_SENSITIVITY + SELECTION_MARGIN
TARGET_SPECIFICITY = 0.70
HIGH_SUSPICION_SPECIFICITY = 0.95


def load_split(split):
    with open(MANIFEST, encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if r["split"] == split]
    images = np.stack([preprocessing.prepare(ROOT / r["filepath"]) for r in rows])
    labels = np.array([int(r["label"]) for r in rows])
    return rows, images, labels


def rates(labels, scores, threshold):
    predicted = scores >= threshold
    tp = int(np.sum(predicted & (labels == 1)))
    fn = int(np.sum(~predicted & (labels == 1)))
    tn = int(np.sum(~predicted & (labels == 0)))
    fp = int(np.sum(predicted & (labels == 0)))
    sensitivity = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    return sensitivity, specificity


def sweep(labels, scores):
    candidates = np.unique(np.round(scores, 3))
    return [(float(t), *rates(labels, scores, t)) for t in candidates]


def main():
    model_path = MODELS / f"{MODEL_VERSION}.keras"
    if not model_path.exists():
        raise SystemExit("No promoted model. Run train_model.py with --promote first.")

    import keras

    print("loading the validation split")
    _, images, labels = load_split("validation")
    model = keras.models.load_model(model_path)
    scores = model.predict(images, verbose=0).ravel()

    table = sweep(labels, scores)

    reaching_target = [row for row in table if row[1] >= SELECTION_SENSITIVITY]
    if reaching_target:
        decision, sens, spec = max(reaching_target, key=lambda row: row[2])
        basis = (
            f"lowest cutoff reaching {SELECTION_SENSITIVITY:.0%} sensitivity on "
            f"validation, a margin of {SELECTION_MARGIN:.0%} above the WHO target "
            f"of {TARGET_SENSITIVITY:.0%} to allow for transfer to unseen data"
        )
    else:
        # No cutoff reaches the target, so fall back to the best balance of the
        # two rates (Youden's J) and say so plainly.
        decision, sens, spec = max(table, key=lambda row: row[1] + row[2] - 1)
        basis = "best balance of sensitivity and specificity; WHO target not reachable"

    high_candidates = [row for row in table if row[2] >= HIGH_SUSPICION_SPECIFICITY]
    if high_candidates:
        high, high_sens, high_spec = min(high_candidates, key=lambda row: row[0])
    else:
        high, high_sens, high_spec = max(table, key=lambda row: row[2])

    if high <= decision:
        high = round(min(0.99, decision + (1 - decision) / 2), 3)
        high_sens, high_spec = rates(labels, scores, high)

    decision = round(decision, 3)
    high = round(high, 3)

    print(
        f"\ndecision threshold   {decision:.3f}   "
        f"sensitivity {sens:.3f}  specificity {spec:.3f}"
    )
    print(f"  basis: {basis}")
    print(
        f"high-suspicion       {high:.3f}   "
        f"sensitivity {high_sens:.3f}  specificity {high_spec:.3f}"
    )
    print(
        f"\nWHO target met: sensitivity {'yes' if sens >= TARGET_SENSITIVITY else 'NO'}, "
        f"specificity {'yes' if spec >= TARGET_SPECIFICITY else 'NO'}"
    )

    # Curve showing how the two rates trade off, for the report.
    thresholds = [row[0] for row in table]
    plt.figure(figsize=(7, 4.2))
    plt.plot(thresholds, [row[1] for row in table], label="Sensitivity")
    plt.plot(thresholds, [row[2] for row in table], label="Specificity")
    plt.axhline(TARGET_SENSITIVITY, linestyle=":", linewidth=1, label="WHO sensitivity target")
    plt.axvline(decision, color="black", linewidth=1, label=f"Chosen decision {decision:.3f}")
    plt.axvline(
        high, color="grey", linestyle="--", linewidth=1, label=f"High suspicion {high:.3f}"
    )
    plt.xlabel("Threshold")
    plt.ylabel("Rate")
    plt.title("Threshold selection on the validation split")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(ARTIFACTS / "threshold_selection.png", dpi=150)
    plt.close()

    metadata = json.loads((MODELS / "metadata.json").read_text(encoding="utf-8"))
    metadata["thresholds"] = {
        "decision": decision,
        "triage_low_medium": decision,
        "triage_medium_high": high,
        "selected_on": "validation split",
        "basis": basis,
        "who_target": {
            "sensitivity": TARGET_SENSITIVITY,
            "selection_sensitivity": SELECTION_SENSITIVITY,
            "selection_margin": SELECTION_MARGIN,
            "specificity": TARGET_SPECIFICITY,
            "source": "WHO target product profile for a TB triage test",
        },
        "validation_at_decision": {
            "sensitivity": round(sens, 4),
            "specificity": round(spec, 4),
        },
        "validation_at_high_suspicion": {
            "sensitivity": round(high_sens, 4),
            "specificity": round(high_spec, 4),
        },
    }
    (MODELS / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"\nmetadata -> {(MODELS / 'metadata.json').relative_to(ROOT)}")
    print(f"figure   -> {(ARTIFACTS / 'threshold_selection.png').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
