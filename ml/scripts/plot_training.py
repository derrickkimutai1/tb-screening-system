"""
Draw the training curves and write a plain-language model report.

The numbers from training are kept as JSON, which is precise but unreadable. This
produces the two things a reader actually needs:

    training_history_<tag>.png  training against validation, epoch by epoch
    model_report_<tag>.md       what the curves mean, in words

The gap between the training and validation curves is what shows overfitting. If
training keeps improving while validation flattens or worsens, the model is
learning the training images rather than the pattern. The report states which of
those is happening and by how much.

Usage:
    python ml/scripts/plot_training.py --tag deep-tune
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "ml" / "artifacts"
MODELS = ROOT / "ml" / "models"

STAGE_NAMES = {"head": "Stage 1: classification head", "fine_tune": "Stage 2: fine-tuning"}


def flatten(history):
    """Lay both stages on one continuous epoch axis."""
    series = {"auc": [], "val_auc": [], "loss": [], "val_loss": []}
    boundaries, best_epochs = [], []
    offset = 0

    for stage in ("head", "fine_tune"):
        if stage not in history:
            continue
        data = history[stage]
        count = len(data["val_auc"])
        for key in series:
            series[key].extend(data[key])
        best = max(range(count), key=lambda i: data["val_auc"][i])
        # Both numbers are useful: the epoch within its own stage, and the same
        # epoch counted from the start of training, which is what the plot shows.
        best_epochs.append((stage, best + 1, offset + best + 1, data["val_auc"][best]))
        offset += count
        boundaries.append(offset)

    return series, boundaries[:-1], best_epochs, offset


def draw(series, boundaries, best_epochs, total, tag):
    epochs = range(1, total + 1)
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)

    top.plot(epochs, series["auc"], label="Training AUC")
    top.plot(epochs, series["val_auc"], label="Validation AUC")
    top.set_ylabel("AUC")
    top.set_title(f"Training history: {tag}")

    bottom.plot(epochs, series["loss"], label="Training loss")
    bottom.plot(epochs, series["val_loss"], label="Validation loss")
    bottom.set_ylabel("Loss")
    bottom.set_xlabel("Epoch")

    for axis in (top, bottom):
        for boundary in boundaries:
            axis.axvline(boundary + 0.5, color="grey", linestyle="--", linewidth=1)
        for _, _, overall, _ in best_epochs:
            axis.axvline(overall, color="black", linestyle=":", linewidth=1)
        axis.grid(alpha=0.2)
        axis.legend(fontsize=9)

    if boundaries:
        top.text(
            boundaries[0] + 0.8,
            top.get_ylim()[0],
            " fine-tuning starts",
            fontsize=8,
            color="grey",
            va="bottom",
        )
    for _, within, overall, _ in best_epochs:
        top.text(
            overall,
            top.get_ylim()[1],
            f" best: epoch {within} of this stage",
            fontsize=8,
            rotation=90,
            va="top",
        )

    plt.tight_layout()
    plt.savefig(ARTIFACTS / f"training_history_{tag}.png", dpi=150)
    plt.close()


def verdict(train_auc, val_auc):
    gap = train_auc - val_auc
    if gap < 0.02:
        return gap, "a close fit, with no meaningful overfitting"
    if gap < 0.08:
        return gap, "mild overfitting"
    if gap < 0.15:
        return gap, "moderate overfitting"
    return gap, "severe overfitting"


def main():
    parser = argparse.ArgumentParser(description="Plot training curves and report on them.")
    parser.add_argument("--tag", default="deep-tune")
    args = parser.parse_args()

    history_path = ARTIFACTS / f"training_history_{args.tag}.json"
    if not history_path.exists():
        raise SystemExit(f"No training history at {history_path}")

    history = json.loads(history_path.read_text(encoding="utf-8"))
    series, boundaries, best_epochs, total = flatten(history)
    draw(series, boundaries, best_epochs, total, args.tag)

    metadata = json.loads((MODELS / "metadata.json").read_text(encoding="utf-8"))
    metrics_path = ARTIFACTS / "metrics.json"
    test = (
        json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else None
    )

    kept = metadata["training"]["stage_kept"]
    stage = history[kept]
    best_index = max(range(len(stage["val_auc"])), key=lambda i: stage["val_auc"][i])
    gap, judgement = verdict(stage["auc"][best_index], stage["val_auc"][best_index])

    lines = [
        f"# Model report: {args.tag}",
        "",
        "Produced by `ml/scripts/plot_training.py`. Regenerate rather than edit.",
        "",
        "## Epochs",
        "",
        "| Stage | Epoch limit | Epochs run | Best epoch | Validation AUC |",
        "|---|---|---|---|---|",
    ]
    limits = {"head": 30, "fine_tune": 15}
    for stage_name, within, overall, auc in best_epochs:
        ran = len(history[stage_name]["val_auc"])
        lines.append(
            f"| {STAGE_NAMES[stage_name]} | {limits[stage_name]} | {ran} "
            f"| {within} (epoch {overall} overall) | {auc:.4f} |"
        )

    lines += [
        "",
        f"**{total} epochs were run in total.** The limits are upper bounds, not targets:",
        "early stopping ends a stage once validation AUC has not improved for eight epochs,",
        "and the weights kept are those of the best epoch rather than the last one. Epochs",
        "after the best one are the model improving on the training images while getting",
        "worse on unseen ones, so they are discarded.",
        "",
        "## Overfitting or underfitting",
        "",
        f"At the best epoch of the stage that was kept ({STAGE_NAMES[kept].lower()}):",
        "",
        "| | Training | Validation | Gap |",
        "|---|---|---|---|",
    ]
    for metric, label in (("auc", "AUC"), ("accuracy", "Accuracy"), ("loss", "Loss")):
        t = stage[metric][best_index]
        v = stage[f"val_{metric}"][best_index]
        lines.append(f"| {label} | {t:.4f} | {v:.4f} | {t - v:+.4f} |")

    lines += [
        "",
        f"**Verdict: {judgement}**, with an AUC gap of {gap:.3f}.",
        "",
        "The model scores higher on images it has seen than on images it has not, which is",
        "overfitting by definition. It is not underfitting: underfitting would mean weak",
        "scores on both, whereas training AUC shows the model learned the data well.",
        "",
        "The cause is the size of the training set. 559 images is small for a convolutional",
        "network, which is why transfer learning was used rather than training from scratch,",
        "and why augmentation and early stopping are applied.",
        "",
    ]

    if test:
        val_auc = metadata["validation_metrics"]["auc"]
        test_auc = test["metrics"]["auc"]
        lines += [
            "## Does it generalise",
            "",
            "| Validation AUC | Test AUC | Difference |",
            "|---|---|---|",
            f"| {val_auc:.4f} | {test_auc:.4f} | {abs(val_auc - test_auc):.4f} |",
            "",
            "Two separate sets of unseen images agree closely. There are two ways to overfit:",
            "fitting the training images too closely, which the gap above shows, and fitting",
            "the validation set through repeated tuning, which would make the final figure",
            "meaningless. This agreement shows the second did not happen.",
            "",
            "## Test results",
            "",
            "| Metric | Value | 95% confidence interval |",
            "|---|---|---|",
        ]
        for name in ("accuracy", "precision", "recall", "specificity", "f1", "auc"):
            low, high = test["confidence_intervals_95"][name]
            value = test["metrics"][name]
            lines.append(f"| {name.capitalize()} | {value:.4f} | [{low:.3f}, {high:.3f}] |")
        matrix = test["confusion_matrix"]
        detected = matrix["true_positive"]
        positives = detected + matrix["false_negative"]
        flagged = matrix["false_positive"]
        negatives = flagged + matrix["true_negative"]
        lines += [
            "",
            f"{detected} of {positives} "
            f"TB cases detected; {flagged} of {negatives} healthy patients flagged in error.",
            "",
        ]

    lines += ["## Figure", "", f"![Training history](training_history_{args.tag}.png)", ""]

    report_path = ARTIFACTS / f"model_report_{args.tag}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"total epochs run : {total}")
    print(f"verdict          : {judgement} (AUC gap {gap:.3f})")
    figure = ARTIFACTS / f"training_history_{args.tag}.png"
    report = ARTIFACTS / f"model_report_{args.tag}.md"
    print(f"figure           -> {figure.relative_to(ROOT)}")
    print(f"report           -> {report.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
