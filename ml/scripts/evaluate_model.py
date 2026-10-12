"""
Final evaluation on the held-out test split.

This runs once, after the model and thresholds have been settled on validation.
The test images have not been seen in training, in model selection or in
threshold selection, so the figures here are an honest estimate of performance
on unseen data.

Because the test split is only 120 images, every headline figure is reported
with a 95% confidence interval from bootstrap resampling. A single number from a
set this small would overstate how precisely it is known.

Produces, in ml/artifacts:
    metrics.json              every figure, with confidence intervals
    confusion_matrix.png
    roc_curve.png
    test_predictions.csv      per-image scores, for error analysis

Usage:
    python ml/scripts/evaluate_model.py
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
from sklearn.metrics import (  # noqa: E402
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))

import preprocessing  # noqa: E402
import provenance  # noqa: E402

MANIFEST = ROOT / "ml" / "artifacts" / "splits.csv"
MODELS = ROOT / "ml" / "models"
ARTIFACTS = ROOT / "ml" / "artifacts"
MODEL_VERSION = "tb_mobilenetv2_v1"

BOOTSTRAP_SAMPLES = 2000
SEED = 42


def load_test():
    with open(MANIFEST, encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if r["split"] == "test"]
    images = np.stack([preprocessing.prepare(ROOT / r["filepath"]) for r in rows])
    labels = np.array([int(r["label"]) for r in rows])
    return rows, images, labels


def specificity_score(labels, predicted):
    tn, fp = confusion_matrix(labels, predicted, labels=[0, 1])[0]
    return tn / (tn + fp) if tn + fp else 0.0


def confidence_intervals(labels, scores, threshold):
    """Resample the test set with replacement to show how precise each figure is."""
    rng = np.random.default_rng(SEED)
    collected = {k: [] for k in ("accuracy", "precision", "recall", "specificity", "f1", "auc")}

    for _ in range(BOOTSTRAP_SAMPLES):
        idx = rng.integers(0, len(labels), len(labels))
        y, s = labels[idx], scores[idx]
        if len(np.unique(y)) < 2:
            continue
        p = (s >= threshold).astype(int)
        collected["accuracy"].append(accuracy_score(y, p))
        collected["precision"].append(precision_score(y, p, zero_division=0))
        collected["recall"].append(recall_score(y, p, zero_division=0))
        collected["specificity"].append(specificity_score(y, p))
        collected["f1"].append(f1_score(y, p, zero_division=0))
        collected["auc"].append(roc_auc_score(y, s))

    return {
        name: [
            round(float(np.percentile(values, 2.5)), 4),
            round(float(np.percentile(values, 97.5)), 4),
        ]
        for name, values in collected.items()
    }


def main():
    model_path = MODELS / f"{MODEL_VERSION}.keras"
    metadata = json.loads((MODELS / "metadata.json").read_text(encoding="utf-8"))
    threshold = float(metadata["thresholds"]["decision"])
    high = float(metadata["thresholds"]["triage_medium_high"])

    import keras

    print(f"model      {MODEL_VERSION}")
    print(f"threshold  {threshold:.3f}  (chosen on validation)")
    print("\nloading the test split, unseen until now")
    rows, images, labels = load_test()
    print(f"  {len(rows)} images ({int(labels.sum())} TB, {int((labels == 0).sum())} normal)")

    model = keras.models.load_model(model_path)
    scores = model.predict(images, verbose=0).ravel()
    predicted = (scores >= threshold).astype(int)

    matrix = confusion_matrix(labels, predicted, labels=[0, 1])
    tn, fp, fn, tp = matrix.ravel()

    point = {
        "accuracy": float(accuracy_score(labels, predicted)),
        "precision": float(precision_score(labels, predicted, zero_division=0)),
        "recall": float(recall_score(labels, predicted, zero_division=0)),
        "specificity": float(specificity_score(labels, predicted)),
        "f1": float(f1_score(labels, predicted, zero_division=0)),
        "auc": float(roc_auc_score(labels, scores)),
    }
    print("\ncomputing confidence intervals")
    intervals = confidence_intervals(labels, scores, threshold)

    print("\ntest set results")
    for name in ("accuracy", "precision", "recall", "specificity", "f1", "auc"):
        low, hi = intervals[name]
        print(f"  {name:<12} {point[name]:.4f}   95% CI [{low:.3f}, {hi:.3f}]")

    print("\nconfusion matrix")
    print(f"  true negative  {tn:>3}     false positive {fp:>3}")
    print(f"  false negative {fn:>3}     true positive  {tp:>3}")
    print(f"\n  {fn} TB case{'s' if fn != 1 else ''} missed out of {tp + fn}")

    # Confusion matrix figure
    fig, ax = plt.subplots(figsize=(4.6, 4.2))
    ax.imshow(matrix, cmap="Blues")
    ax.set_xticks([0, 1], ["Unlikely TB", "Likely TB"])
    ax.set_yticks([0, 1], ["Normal", "TB"])
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title("Confusion matrix, test split")
    for i in range(2):
        for j in range(2):
            ax.text(
                j,
                i,
                matrix[i, j],
                ha="center",
                va="center",
                color="white" if matrix[i, j] > matrix.max() / 2 else "black",
                fontsize=15,
            )
    plt.tight_layout()
    plt.savefig(ARTIFACTS / "confusion_matrix.png", dpi=150)
    plt.close()

    # ROC curve
    fpr, tpr, _ = roc_curve(labels, scores)
    plt.figure(figsize=(5, 4.6))
    plt.plot(fpr, tpr, label=f"AUC = {point['auc']:.3f}")
    plt.plot([0, 1], [0, 1], linestyle=":", linewidth=1, label="Chance")
    plt.xlabel("False positive rate")
    plt.ylabel("True positive rate")
    plt.title("ROC curve, test split")
    plt.legend()
    plt.tight_layout()
    plt.savefig(ARTIFACTS / "roc_curve.png", dpi=150)
    plt.close()

    # Per-image predictions, for error analysis in the next phase.
    with open(ARTIFACTS / "test_predictions.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "source", "actual", "score", "predicted", "correct"])
        for row, score, pred in zip(rows, scores, predicted, strict=True):
            writer.writerow(
                [
                    row["filename"],
                    row["source"],
                    int(row["label"]),
                    round(float(score), 4),
                    int(pred),
                    int(int(row["label"]) == pred),
                ]
            )

    results = {
        "model_version": MODEL_VERSION,
        "run_tag": metadata.get("run_tag"),
        "provenance": provenance.describe(MANIFEST),
        "evaluated_on": "test split, held out from training and model selection",
        "test_images": len(rows),
        "test_tb": int(labels.sum()),
        "decision_threshold": threshold,
        "high_suspicion_threshold": high,
        "metrics": {k: round(v, 4) for k, v in point.items()},
        "confidence_intervals_95": intervals,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "confusion_matrix": {
            "true_negative": int(tn),
            "false_positive": int(fp),
            "false_negative": int(fn),
            "true_positive": int(tp),
        },
    }
    (ARTIFACTS / "metrics.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    print(f"\nmetrics     -> {(ARTIFACTS / 'metrics.json').relative_to(ROOT)}")
    print("figures     -> confusion_matrix.png, roc_curve.png")
    print(f"predictions -> {(ARTIFACTS / 'test_predictions.csv').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
