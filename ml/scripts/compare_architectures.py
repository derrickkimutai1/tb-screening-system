"""
Compare the candidate architectures and write the justification.

The proposal names MobileNetV2 and gives a deployment reason for it. A reason
is not evidence, so this compares it against two alternatives trained under
identical conditions and writes down what the comparison shows, whichever way
it comes out.

What is held constant, so that a difference is attributable to the architecture:

    the splits          the same stratified 70/15/15 manifest, seeded at 42
    the head            global average pooling, dropout, dense 128, dense 64, sigmoid
    the schedule        30 head epochs then 15 fine-tuning epochs, early stopping
    the fine-tuning     the last 60 base layers at 1e-4
    the regularisation  dropout 0.5, weight decay 1e-4
    the augmentation    light
    the batch size      32

What necessarily differs is how pixels arrive: each network was pretrained on
its own input convention. `ml/preprocessing.py` stays the single source of
truth for reading a file, and `train_model.py` converts its output per
architecture, so the images are identical and only the convention changes.

Selection is on validation only. The test split is not read here.

Usage:
    python ml/scripts/compare_architectures.py
"""

import csv
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))

import preprocessing  # noqa: E402

MANIFEST_SPLIT = "validation"
ARTIFACTS = ROOT / "ml" / "artifacts"
STAGING = ROOT / "ml" / "models" / "checkpoints"
EXPERIMENTS = ARTIFACTS / "experiments.csv"

FIGURE = ARTIFACTS / "architecture_comparison.png"
REPORT = ARTIFACTS / "architecture_comparison.md"

# The runs that form the comparison. Each is the best run of its architecture
# under the shared settings above.
COMPARED = {
    "arch-mobilenetv2": "MobileNetV2",
    "arch-resnet50": "ResNet50",
    "arch-efficientnetb0": "EfficientNetB0",
    "arch-scratch": "Small CNN, no pretraining",
}

# What each one is called on an axis, where the full name does not fit.
SHORT = {
    "MobileNetV2": "MobileNetV2",
    "ResNet50": "ResNet50",
    "EfficientNetB0": "EfficientNet\nB0",
    "Small CNN, no pretraining": "Small CNN\nfrom scratch",
}

# The architecture the proposal chose, and the one every comparison is drawn
# against.
REFERENCE = "MobileNetV2"

# Resamples for the confidence intervals. The validation split is 121 images,
# so a difference of a few thousandths of AUC may be nothing at all; the only
# way to say whether two architectures are distinguishable on a set this small
# is to measure the uncertainty rather than compare point estimates.
BOOTSTRAP_RESAMPLES = 2000

INK = "#1b1e17"
ACCENT = "#6b7f1f"
MUTED = "#9ba491"


def load_validation():
    """The validation images and labels, read once and shared by every model."""
    import numpy as np

    with open(ARTIFACTS / "splits.csv", encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if r["split"] == MANIFEST_SPLIT]

    images = np.stack([preprocessing.prepare(ROOT / r["filepath"]) for r in rows])
    labels = np.array([int(r["label"]) for r in rows])
    return images, labels


def scores_for(tag, images):
    """The model's score for every validation image, or None if it is missing."""
    import keras

    path = STAGING / f"{tag}_selected.keras"
    if not path.exists():
        return None
    return keras.models.load_model(path).predict(images, verbose=0).ravel()


def bootstrap(labels, scores_by_label, resamples=BOOTSTRAP_RESAMPLES, seed=42):
    """Confidence intervals for each AUC, and for each difference from the reference.

    The same resampled indices are used for every model on each draw. That
    pairing matters: two models are being compared on one set of patients, and
    resampling them independently would add variation that does not exist in
    the comparison being made.
    """
    import numpy as np
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(seed)
    names = list(scores_by_label)
    draws = {name: [] for name in names}
    gaps = {name: [] for name in names if name != REFERENCE}

    for _ in range(resamples):
        index = rng.integers(0, len(labels), len(labels))
        resampled = labels[index]
        # A resample that lost one class entirely has no AUC to report.
        if resampled.min() == resampled.max():
            continue

        aucs = {n: roc_auc_score(resampled, scores_by_label[n][index]) for n in names}
        for name, value in aucs.items():
            draws[name].append(value)
        if REFERENCE in aucs:
            for name in gaps:
                gaps[name].append(aucs[name] - aucs[REFERENCE])

    def interval(values):
        return [
            round(float(np.percentile(values, 2.5)), 4),
            round(float(np.percentile(values, 97.5)), 4),
        ]

    return (
        {n: interval(v) for n, v in draws.items() if v},
        {n: interval(v) for n, v in gaps.items() if v},
    )


def measure_latency(tag, repeats=20):
    """Median milliseconds to score one image on this CPU.

    The deployment target is a clinic without a GPU, so the cost that matters
    in service is the time to score one radiograph, not the time to train. The
    median is taken rather than the mean because an occasional scheduling
    hiccup on a laptop should not define the figure, and the first calls are
    discarded because they include graph construction.
    """
    import keras
    import numpy as np

    path = STAGING / f"{tag}_selected.keras"
    if not path.exists():
        return None

    model = keras.models.load_model(path)
    one = np.zeros((1, 224, 224, 3), dtype="float32")

    for _ in range(3):
        model.predict(one, verbose=0)

    timings = []
    for _ in range(repeats):
        start = time.perf_counter()
        model.predict(one, verbose=0)
        timings.append((time.perf_counter() - start) * 1000)

    return round(float(np.median(timings)), 1)


def load_runs(images=None):
    """Read the compared runs, pulling wall-clock time from each run's metadata."""
    with open(EXPERIMENTS, encoding="utf-8") as handle:
        rows = {r["tag"]: r for r in csv.DictReader(handle)}

    runs = []
    for tag, label in COMPARED.items():
        row = rows.get(tag)
        if row is None:
            print(f"  missing: {tag} has not been trained yet")
            continue

        meta_path = STAGING / f"{tag}_metadata.json"
        seconds = None
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            seconds = meta.get("training", {}).get("wall_clock_seconds")

        runs.append(
            {
                "tag": tag,
                "label": label,
                "auc": float(row["val_auc"]),
                "accuracy": float(row["val_accuracy"]),
                "recall": float(row["val_recall"]),
                "precision": float(row["val_precision"]),
                "loss": float(row["val_loss"]),
                "parameters": int(row["parameters"]),
                "minutes": round(seconds / 60, 1) if seconds else None,
                "latency_ms": measure_latency(tag),
                "scores": None if images is None else scores_for(tag, images),
                "stage_kept": row["stage_kept"],
            }
        )
    return runs


def bar(axis, runs, key, title, formatter, highlight, errors=None):
    labels = [SHORT.get(r["label"], r["label"]) for r in runs]
    values = [r[key] for r in runs]
    colours = [ACCENT if r["label"] == highlight else MUTED for r in runs]

    bars = axis.bar(labels, values, color=colours, width=0.62, zorder=2)
    axis.set_title(title, fontsize=10.5, loc="left", color=INK, pad=10)
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.tick_params(axis="x", labelsize=8.5, length=0)
    axis.tick_params(axis="y", labelsize=0, length=0)
    axis.set_yticklabels([])

    if errors is not None:
        axis.errorbar(
            labels,
            values,
            yerr=errors,
            fmt="none",
            ecolor=INK,
            elinewidth=1.1,
            capsize=4,
            zorder=3,
        )

    # Headroom for the label, and for an error bar where there is one.
    tops = [
        value + (errors[1][i] if errors is not None else 0) for i, value in enumerate(values)
    ]
    axis.set_ylim(0, max(tops) * 1.22)

    for index, (rect, value) in enumerate(zip(bars, values, strict=True)):
        axis.text(
            rect.get_x() + rect.get_width() / 2,
            tops[index] + max(tops) * 0.035,
            formatter(value),
            ha="center",
            va="bottom",
            fontsize=9,
            color=INK,
        )


def draw(runs):
    """What it scores, what it costs to store, to retrain, and to run."""
    runs = sorted(runs, key=lambda r: -r["auc"])
    timed = [r for r in runs if r["minutes"] is not None]
    latent = [r for r in runs if r["latency_ms"] is not None]

    figure, axes = plt.subplots(2, 2, figsize=(11.0, 8.4))
    flat = axes.ravel()

    intervals = [r.get("interval") for r in runs]
    errors = None
    if all(intervals):
        errors = [
            [r["auc"] - r["interval"][0] for r in runs],
            [r["interval"][1] - r["auc"] for r in runs],
        ]

    bar(
        flat[0],
        runs,
        "auc",
        "Validation AUC, with 95% interval\nhigher is better",
        lambda v: f"{v:.4f}",
        REFERENCE,
        errors=errors,
    )

    bar(
        flat[1],
        runs,
        "parameters",
        "Parameters\nlower is cheaper to store and to ship",
        lambda v: f"{v / 1e6:.1f}M",
        REFERENCE,
    )

    if timed:
        bar(
            flat[2],
            timed,
            "minutes",
            "Training time on CPU\nlower is cheaper to retrain",
            lambda v: f"{v:.0f} min",
            REFERENCE,
        )
    else:
        flat[2].set_visible(False)

    if latent:
        bar(
            flat[3],
            latent,
            "latency_ms",
            "Scoring one image on CPU\nthe cost paid in the clinic",
            lambda v: f"{v:.0f} ms",
            REFERENCE,
        )
    else:
        flat[3].set_visible(False)

    figure.suptitle(
        "Architecture comparison: identical splits, head, schedule and regularisation",
        fontsize=12,
        color=INK,
        x=0.015,
        y=0.985,
        ha="left",
    )
    figure.text(
        0.015,
        0.945,
        f"Validation split, 121 images. {REFERENCE} is the architecture the "
        "proposal chose and is highlighted.",
        fontsize=9,
        color=MUTED,
        ha="left",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.925))
    figure.savefig(FIGURE, dpi=150)
    plt.close(figure)


def verdict(runs):
    """State what the numbers support, whichever architecture they favour.

    The point estimate is not the whole answer. With 121 validation images a
    gap of a few hundredths of AUC may be noise, so where a confidence interval
    for the difference is available it decides whether a gap is claimed at all.
    """
    best = max(runs, key=lambda r: r["auc"])
    mobile = next((r for r in runs if r["label"] == REFERENCE), None)
    if mobile is None:
        return f"{REFERENCE} has not been trained, so no comparison can be drawn.", best

    if best["label"] == REFERENCE:
        others = ", ".join(r["label"] for r in runs if r is not mobile)
        return (
            f"{REFERENCE} scores highest on validation AUC at {mobile['auc']:.4f}, "
            f"ahead of {others}, while also being among the smallest compared. On this "
            "dataset it is the better choice on both counts, so no trade-off has to "
            "be argued.",
            best,
        )

    gap = best["auc"] - mobile["auc"]
    ratio = best["parameters"] / mobile["parameters"]
    interval = best.get("gap")

    if interval is not None and interval[0] <= 0 <= interval[1]:
        separable = (
            f"That gap carries a 95 per cent confidence interval of "
            f"[{interval[0]:+.4f}, {interval[1]:+.4f}], which includes zero. On a "
            f"validation split of this size the two architectures are therefore not "
            f"reliably distinguishable: the ordering could reverse on another sample. "
            f"What is not in doubt is the cost, and {best['label']} carries "
            f"{ratio:.1f} times the parameters for an advantage that cannot be "
            f"demonstrated."
        )
    elif interval is not None:
        separable = (
            f"That gap carries a 95 per cent confidence interval of "
            f"[{interval[0]:+.4f}, {interval[1]:+.4f}], which excludes zero, so the "
            f"advantage is real on this split and not an artefact of the sample. It "
            f"costs {ratio:.1f} times the parameters. Whether that is worth paying "
            f"depends on the deployment, and this project's deployment is a clinic "
            f"running inference on a CPU without a GPU. A model that scores better "
            f"but cannot run where the patients are has no sensitivity at all. The "
            f"proposal's choice stands on that basis rather than on accuracy, which "
            f"is a weaker claim than winning outright and is reported as such."
        )
    else:
        separable = (
            f"It costs {ratio:.1f} times the parameters. Whether that is worth paying "
            f"depends on the deployment, and this project's deployment is a clinic "
            f"running inference on a CPU without a GPU."
        )

    return (
        f"{best['label']} scores {best['auc']:.4f} against {REFERENCE}'s "
        f"{mobile['auc']:.4f}, an advantage of {gap:.4f} AUC. {separable}",
        best,
    )


def write_report(runs):
    statement, best = verdict(runs)
    mobile = next((r for r in runs if r["label"] == REFERENCE), None)
    reference_auc = mobile["auc"] if mobile else 0.0

    lines = [
        "# Which architecture, and why",
        "",
        "Produced by `ml/scripts/compare_architectures.py`. Regenerate rather than edit.",
        "",
        "## The question",
        "",
        "Proposal section 3.2.3 names MobileNetV2 and justifies it by deployment: a",
        "clinic in a resource-constrained setting runs this on a CPU, so the model has",
        "to be small and fast. That is a reason to prefer a compact network. It is not",
        "evidence that a compact network is good enough, and the two are different",
        "claims. This compares it against the alternatives to settle the second one.",
        "",
        "## What was held constant",
        "",
        "Every run below used the same stratified 70/15/15 manifest seeded at 42, the",
        "same classification head, the same two-stage schedule of 30 head epochs then",
        "15 fine-tuning epochs with early stopping, the same 60 unfrozen base layers at",
        "a fine-tuning rate of 1e-4, the same dropout of 0.5 and weight decay of 1e-4,",
        "light augmentation and a batch size of 32.",
        "",
        "The one thing that necessarily differs is the input convention each network",
        "was pretrained on. `ml/preprocessing.py` remains the single source of truth for",
        "reading an image off disk, and the conversion happens inside the model, so the",
        "pixels are identical and only the convention changes.",
        "",
        "All selection is on the validation split. The test split was not read.",
        "",
        "## Results",
        "",
        "| Architecture | Parameters | Validation AUC | 95% CI | vs "
        + REFERENCE
        + " | Training | One image |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for run in sorted(runs, key=lambda r: -r["auc"]):
        minutes = f"{run['minutes']:.0f} min" if run["minutes"] is not None else "-"
        latency = f"{run['latency_ms']:.0f} ms" if run["latency_ms"] is not None else "-"
        interval = run.get("interval")
        ci = f"[{interval[0]:.3f}, {interval[1]:.3f}]" if interval else "-"
        gap = run.get("gap")
        if run["label"] == REFERENCE:
            against = "reference"
        elif gap:
            overlaps = " (overlaps)" if gap[0] <= 0 <= gap[1] else ""
            against = f"{run['auc'] - reference_auc:+.4f}{overlaps}"
        else:
            against = "-"
        lines.append(
            f"| {run['label']} | {run['parameters']:,} | **{run['auc']:.4f}** | "
            f"{ci} | {against} | {minutes} | {latency} |"
        )

    lines += [
        "",
        "![Architecture comparison](architecture_comparison.png)",
        "",
        "## What it shows",
        "",
        statement,
        "",
    ]

    if mobile is not None and best["label"] != REFERENCE:
        lines += [
            "## The size argument, stated properly",
            "",
            f"The larger network carries roughly "
            f"{best['parameters'] / mobile['parameters']:.0f} times the parameters, "
            f"and its saved file is "
            f"{best['parameters'] * 4 / 1e6:.0f} MB against "
            f"{mobile['parameters'] * 4 / 1e6:.0f} MB. That cost is paid in three "
            "places: in every inference on a machine without a GPU, in every "
            "retraining, and in the Windows executable this project ships as its "
            "final deliverable, which has to carry the weights inside it.",
            "",
            f"On this machine the difference in scoring one image is "
            f"{best['latency_ms']:.0f} ms against {mobile['latency_ms']:.0f} ms. "
            "That is the weaker half of the argument and is stated rather than "
            "leaned on: at this scale both are fast enough for a clinic, and it is "
            "the file size and the retraining cost that carry the decision.",
            "",
        ]

    lines += [
        "## What this comparison does not establish",
        "",
        f"- {len(runs)} architectures, one run each. The confidence intervals above",
        "  describe sampling variation in the 121 validation images. They say nothing",
        "  about variation between training runs: the same architecture trained again",
        "  with a different seed would land somewhere slightly different, and that",
        "  source of uncertainty is not measured here. Repeated runs per architecture",
        "  would be needed to separate the two.",
        "- Each alternative was given the schedule tuned for MobileNetV2. A network",
        "  tuned for itself might do better, so a loss here is not proof of a worse",
        "  architecture, only of a worse architecture under these settings.",
        "- Validation only, on 121 images. The ordering could differ on the test split,",
        "  which was deliberately not consulted.",
        "",
    ]

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    print("loading the validation split")
    images, labels = load_validation()

    runs = load_runs(images)
    if len(runs) < 2:
        raise SystemExit("Fewer than two architectures have been trained; nothing to compare.")

    scored = {r["label"]: r["scores"] for r in runs if r["scores"] is not None}
    if len(scored) >= 2:
        print(f"bootstrapping {BOOTSTRAP_RESAMPLES} resamples of {len(labels)} images")
        intervals, gaps = bootstrap(labels, scored)
        for run in runs:
            run["interval"] = intervals.get(run["label"])
            run["gap"] = gaps.get(run["label"])
    else:
        for run in runs:
            run["interval"] = run["gap"] = None

    draw(runs)
    write_report(runs)

    print(f"{'architecture':<18}{'params':>13}{'val AUC':>10}{'min':>7}{'ms/image':>10}")
    for run in sorted(runs, key=lambda r: -r["auc"]):
        minutes = f"{run['minutes']:.0f}" if run["minutes"] is not None else "-"
        latency = f"{run['latency_ms']:.0f}" if run["latency_ms"] is not None else "-"
        print(
            f"{run['label']:<18}{run['parameters']:>13,}{run['auc']:>10.4f}"
            f"{minutes:>7}{latency:>10}"
        )

    print(f"\nfigure -> {FIGURE.relative_to(ROOT)}")
    print(f"report -> {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
