"""
Does the dataset size limit this model, and would more radiographs help?

The dataset is 800 images, 559 of them training. That is small for a medical
imaging model and it is the first thing anyone reading the results will say.
"Small" on its own is not a finding, though: what matters is whether
performance is still climbing with each image added, or whether it has
flattened and the limit lies somewhere else.

This measures it. The model is retrained on 25, 50, 75 and 100 per cent of the
training split, three times each from a different random draw, and scored on
the same fixed validation split every time. The resulting curve answers the
question directly:

    still climbing at 559   the dataset is the binding constraint, and the
                            curve says roughly how many more images are needed
                            for a given gain

    flattened before 559    more of the same data would not help, and the
                            remedy is a different architecture, better labels,
                            or a different population

Nothing here presupposes which. The verdict is written from the measurement.

What is held constant, so that a difference is attributable to dataset size:
everything the deployed model was trained with. The settings below are copied
from `reg-both`, the run that was promoted, and the 100 per cent points
therefore retrain the deployed recipe exactly.

Two things vary on purpose. The subsample draw varies, because one unlucky
draw of 140 images is not evidence about 140 images. The training seed varies
with it, so the spread at each point includes the run-to-run noise of this
training procedure rather than pretending it away; the spread at 100 per cent,
where every run sees the identical images, is that noise on its own and is the
yardstick a gap between points has to beat.

**The test split is never loaded by this script.** Every number here is on
validation, so the test set stays untouched.

Runs are recorded as they finish and an interrupted run is resumed rather than
repeated. One pass is about twelve retrainings and takes roughly ninety minutes
on a CPU.

Usage:
    python ml/scripts/learning_curve.py
    python ml/scripts/learning_curve.py --quick
    python ml/scripts/learning_curve.py --fresh
"""

import argparse
import csv
import gc
import json
import math
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
sys.path.insert(0, str(ROOT / "ml" / "scripts"))

import preprocessing  # noqa: E402
import provenance  # noqa: E402
import train_model as trainer  # noqa: E402

ARTIFACTS = ROOT / "ml" / "artifacts"
MANIFEST = ARTIFACTS / "splits.csv"

MEASUREMENTS = ARTIFACTS / "learning_curve.json"
FIGURE = ARTIFACTS / "learning_curve.png"
REPORT = ARTIFACTS / "learning_curve.md"

# The promoted model's settings, from ml/models/metadata.json. Changing one of
# these makes the curve describe a model the application does not run.
SETTINGS = {
    "architecture": "mobilenetv2",
    "augmentation": "light",
    "dropout": 0.5,
    "weight_decay": 1e-4,
    "batch_size": 32,
    "head_epochs": 30,
    "head_learning_rate": 1e-3,
    "fine_tune_epochs": 15,
    "fine_tune_lr": 1e-4,
    "unfreeze": 60,
}

FRACTIONS = (0.25, 0.50, 0.75, 1.00)
SEEDS = (42, 1337, 2026)

# AUC values a reader is likely to ask about. The first is roughly where this
# model is now; the others are targets the curve is asked to price.
TARGETS = (0.93, 0.95, 0.97)

INK = "#1b1e17"
ACCENT = "#6b7f1f"
MUTED = "#9ba491"
FAINT = "#d8dccf"


def load_split(split):
    """One split, prepared exactly as the application prepares an upload."""
    with open(MANIFEST, encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if r["split"] == split]

    images = np.stack([preprocessing.prepare(ROOT / r["filepath"]) for r in rows])
    labels = np.array([int(r["label"]) for r in rows], dtype=np.float32)
    print(f"  {split:<11} {len(rows):>4} images  ({int(labels.sum())} TB)")
    return images, labels


def subsample(labels, fraction, seed):
    """Indices for a stratified draw, keeping the TB share of the full split.

    Drawn per class rather than from the whole set. A random draw of a quarter
    of 559 images could easily shift the class balance by several points, and
    that shift would show up in the curve as an effect of dataset size when it
    is nothing of the kind.
    """
    rng = np.random.default_rng(seed)
    chosen = []
    for value in (0.0, 1.0):
        pool = np.flatnonzero(labels == value)
        take = max(1, int(round(len(pool) * fraction)))
        chosen.append(rng.choice(pool, size=take, replace=False))
    index = np.concatenate(chosen)
    rng.shuffle(index)
    return index


def stopping_callbacks():
    """Early stopping and a learning-rate reduction, but no checkpoint file.

    `train_model.py` checkpoints because it keeps the model afterwards. Here
    only the numbers are kept, and twelve discarded checkpoints would be a few
    hundred megabytes written for nothing. `restore_best_weights` leaves the
    best epoch's weights in memory, which is what gets evaluated.
    """
    import keras

    return [
        keras.callbacks.EarlyStopping(
            monitor="val_auc", mode="max", patience=8, restore_best_weights=True, verbose=0
        ),
        keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=4, min_lr=1e-7, verbose=0
        ),
    ]


def evaluate(model, images, labels):
    scores = model.evaluate(images, labels, verbose=0, return_dict=True)
    return {key: round(float(value), 4) for key, value in scores.items()}


def train_once(train_x, train_y, val_x, val_y, seed):
    """Train the deployed recipe on the images given, and return what it scores.

    Both stages run, and the better of the two is reported, which is the rule
    `train_model.py` applies when it promotes a run. Reporting stage 2
    unconditionally would charge the smaller subsets for a fine-tuning step
    that had too little data to help.
    """
    import keras
    from keras.layers import BatchNormalization

    keras.utils.set_random_seed(seed)
    started = time.monotonic()

    model, base = trainer.build_model(
        SETTINGS["augmentation"],
        dropout=SETTINGS["dropout"],
        architecture=SETTINGS["architecture"],
    )

    trainer.compile_model(
        model,
        learning_rate=SETTINGS["head_learning_rate"],
        weight_decay=SETTINGS["weight_decay"],
    )
    model.fit(
        train_x,
        train_y,
        validation_data=(val_x, val_y),
        epochs=SETTINGS["head_epochs"],
        batch_size=SETTINGS["batch_size"],
        callbacks=stopping_callbacks(),
        verbose=0,
    )
    best = evaluate(model, val_x, val_y)
    stage_kept = "head"

    cut = max(0, len(base.layers) - SETTINGS["unfreeze"])
    base.trainable = True
    for layer in base.layers[:cut]:
        layer.trainable = False
    # Batch-normalisation statistics stay frozen; updating them on a subset
    # this small destabilises fine-tuning, and the subsets here are smaller
    # still than the one that rule was adopted for.
    for layer in base.layers:
        if isinstance(layer, BatchNormalization):
            layer.trainable = False

    trainer.compile_model(
        model,
        learning_rate=SETTINGS["fine_tune_lr"],
        weight_decay=SETTINGS["weight_decay"],
    )
    model.fit(
        train_x,
        train_y,
        validation_data=(val_x, val_y),
        epochs=SETTINGS["fine_tune_epochs"],
        batch_size=SETTINGS["batch_size"],
        callbacks=stopping_callbacks(),
        verbose=0,
    )
    tuned = evaluate(model, val_x, val_y)
    if tuned["auc"] > best["auc"]:
        best = tuned
        stage_kept = "fine_tune"

    minutes = round((time.monotonic() - started) / 60, 2)

    del model, base
    keras.backend.clear_session()
    gc.collect()

    return {
        "val_auc": best["auc"],
        "val_accuracy": best["accuracy"],
        "val_precision": best["precision"],
        "val_recall": best["recall"],
        "val_loss": best["loss"],
        "stage_kept": stage_kept,
        "minutes": minutes,
    }


def summarise(runs):
    """Collapse the runs at each dataset size into one point with a spread."""
    points = []
    for fraction in sorted({r["fraction"] for r in runs}):
        at = [r for r in runs if r["fraction"] == fraction]
        aucs = np.array([r["val_auc"] for r in at])
        points.append(
            {
                "fraction": fraction,
                "images": at[0]["images"],
                "runs": len(at),
                "mean_auc": round(float(aucs.mean()), 4),
                "min_auc": round(float(aucs.min()), 4),
                "max_auc": round(float(aucs.max()), 4),
                "spread": round(float(aucs.max() - aucs.min()), 4),
                "sd_auc": round(float(aucs.std(ddof=1)) if len(at) > 1 else 0.0, 4),
                "sem_auc": round(
                    float(aucs.std(ddof=1) / np.sqrt(len(at))) if len(at) > 1 else 0.0, 4
                ),
                "mean_recall": round(float(np.mean([r["val_recall"] for r in at])), 4),
            }
        )
    return points


def fit_power_law(runs):
    """Fit the error against dataset size, and say how well the fit holds.

    Learning curves are conventionally modelled as a power law in the error
    rather than in the score: error falls as a fixed proportion for each
    doubling of the data. A straight line through log(error) against
    log(images) is therefore two parameters rather than three, which is as much
    as twelve noisy points can carry.

    The fit is reported with its R-squared so that a bad fit discredits its own
    projection instead of being quoted as a prediction.
    """
    images = np.array([r["images"] for r in runs], dtype=float)
    error = 1.0 - np.array([r["val_auc"] for r in runs], dtype=float)
    if len(runs) < 3 or np.any(error <= 0):
        return None

    x = np.log(images)
    y = np.log(error)
    # Fitted about the mean rather than about zero. The log sizes here sit
    # between 4.9 and 6.3, far from the origin, and fitting a line through a
    # cluster that far out is poorly conditioned: numpy says so. Centring is
    # algebraically the same line, recovered below.
    centre = float(x.mean())
    slope, shifted = np.polyfit(x - centre, y, 1)
    intercept = shifted - slope * centre

    predicted = slope * x + intercept
    residual = float(np.sum((y - predicted) ** 2))
    total = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1.0 - residual / total if total > 0 else 0.0

    def auc_at(n):
        return 1.0 - float(np.exp(intercept) * n**slope)

    def images_for(auc):
        # Inverting error(n) = exp(intercept) * n ** slope.
        if slope >= 0 or auc >= 1.0:
            return None
        wanted = 1.0 - auc
        return float(np.exp((np.log(wanted) - intercept) / slope))

    projection = {}
    for n in (1000, 1600, 3200):
        projection[str(n)] = round(auc_at(n), 4)

    needed = {}
    for target in TARGETS:
        n = images_for(target)
        needed[f"{target:.2f}"] = int(round(n)) if n and n < 1e7 else None

    return {
        "exponent": round(float(slope), 4),
        "coefficient": round(float(np.exp(intercept)), 4),
        "r_squared": round(float(r_squared), 4),
        "halving_gain": round(float(1.0 - 2.0**slope), 4),
        "projected_auc": projection,
        "images_for_auc": needed,
        "fitted_on": len(runs),
        "observed_up_to": int(images.max()),
    }


def read_measurements():
    if not MEASUREMENTS.exists():
        return []
    try:
        stored = json.loads(MEASUREMENTS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return stored.get("runs", [])


def write_measurements(runs, available, validation_images):
    runs = sorted(runs, key=lambda r: (r["fraction"], r["seed"]))
    MEASUREMENTS.write_text(
        json.dumps(
            {
                "produced": datetime.now(UTC).isoformat(timespec="seconds"),
                "provenance": provenance.describe(MANIFEST),
                "settings": SETTINGS,
                "train_images_available": available,
                "validation_images": validation_images,
                "seeds": list(SEEDS),
                "runs": runs,
                "points": summarise(runs),
                "fit": fit_power_law(runs),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="",
    )


def draw(points, runs, fit, available):
    figure, axes = plt.subplots(1, 2, figsize=(11.4, 4.8))
    left, right = axes

    xs = [p["images"] for p in points]
    means = [p["mean_auc"] for p in points]
    lows = [p["min_auc"] for p in points]
    highs = [p["max_auc"] for p in points]

    left.fill_between(xs, lows, highs, color=FAINT, zorder=1)
    left.plot(xs, means, color=ACCENT, linewidth=1.8, zorder=3)
    left.scatter(
        [r["images"] for r in runs],
        [r["val_auc"] for r in runs],
        s=22,
        color=INK,
        alpha=0.55,
        zorder=4,
    )
    left.scatter(xs, means, s=46, color=ACCENT, zorder=5, edgecolor="white", linewidth=1.2)

    for point in points:
        left.annotate(
            f"{point['mean_auc']:.4f}",
            (point["images"], point["max_auc"]),
            textcoords="offset points",
            xytext=(0, 9),
            ha="center",
            fontsize=8.5,
            color=INK,
        )

    left.set_title(
        "Validation AUC against training images used",
        fontsize=10.5,
        loc="left",
        color=INK,
        pad=10,
    )
    left.set_xlabel("training images", fontsize=9, color=MUTED)
    left.set_ylabel("validation AUC", fontsize=9, color=MUTED)
    left.spines[["top", "right"]].set_visible(False)
    left.tick_params(labelsize=8.5)
    left.set_xticks(xs)
    # Room for the leftmost annotation, which otherwise sits on the axis.
    margin = (max(xs) - min(xs)) * 0.09
    left.set_xlim(min(xs) - margin, max(xs) + margin)
    left.grid(axis="y", color=FAINT, linewidth=0.7, zorder=0)
    span = max(highs) - min(lows)
    left.set_ylim(min(lows) - span * 0.35, max(highs) + span * 0.35)

    if fit is not None:
        grid = np.linspace(min(xs) * 0.9, 3400, 200)
        errors = fit["coefficient"] * grid ** fit["exponent"]
        observed = grid <= available
        right.plot(
            grid[observed],
            errors[observed],
            color=ACCENT,
            linewidth=1.8,
            zorder=3,
            label="fitted on the measured range",
        )
        right.plot(
            grid[~observed],
            errors[~observed],
            color=ACCENT,
            linewidth=1.4,
            linestyle=(0, (4, 3)),
            zorder=3,
            label="projection beyond the data held",
        )
        right.scatter(
            [r["images"] for r in runs],
            [1.0 - r["val_auc"] for r in runs],
            s=22,
            color=INK,
            alpha=0.55,
            zorder=4,
        )
        right.set_xscale("log")
        right.set_yscale("log")
        # Label the sizes actually measured and the ones projected to, rather
        # than the decade marks a log axis defaults to.
        ticks = sorted({*xs, 1000, 3200})
        right.set_xticks(ticks)
        right.set_xticklabels([f"{t:,}" for t in ticks], fontsize=8)
        right.minorticks_off()
        right.set_title(
            f"Error against dataset size, log scales (R-squared {fit['r_squared']:.2f})",
            fontsize=10.5,
            loc="left",
            color=INK,
            pad=10,
        )
        right.set_xlabel("training images", fontsize=9, color=MUTED)
        right.set_ylabel("1 minus validation AUC", fontsize=9, color=MUTED)
        right.spines[["top", "right"]].set_visible(False)
        right.tick_params(labelsize=8.5)
        right.grid(color=FAINT, linewidth=0.7, which="both", zorder=0)
        right.legend(fontsize=8, frameon=False, loc="lower left")
    else:
        right.set_visible(False)

    figure.suptitle(
        "What dataset size buys: the deployed recipe retrained on subsets of its "
        "own training split",
        fontsize=12,
        color=INK,
        x=0.012,
        y=0.985,
        ha="left",
    )
    figure.text(
        0.012,
        0.922,
        f"{len(SEEDS)} draws per size, scored on the same fixed validation split. Shaded "
        "band is the range across draws. The test split was not used.",
        fontsize=9,
        color=MUTED,
        ha="left",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.9))
    figure.savefig(FIGURE, dpi=150)
    plt.close(figure)


def resolution(one, other, multiplier=2.0):
    """The smallest difference between two points this measurement can claim.

    Two standard errors of the difference between the means. The raw spread of
    individual runs is the wrong comparison: a point is a mean of several draws
    and is known more precisely than any single draw.
    """

    def standard_error(point):
        if point["runs"] < 2:
            return 0.0
        return point["sd_auc"] / math.sqrt(point["runs"])

    combined = math.sqrt(standard_error(one) ** 2 + standard_error(other) ** 2)
    return round(multiplier * combined, 4)


def verdict(points, fit, available):
    """State what the curve supports, whichever way it came out."""
    if len(points) < 2:
        return "Too few sizes measured to say anything about the trend."

    first, previous, last = points[0], points[-2], points[-1]

    # Whether a gap is real is a question about the means, not about the raw
    # spread of individual runs, so it is judged against the standard error of
    # the difference between two means. Two standard errors is the usual
    # two-sided bar. With three draws per size that bar is high, which is a
    # property of the measurement and is stated rather than worked around.
    overall = last["mean_auc"] - first["mean_auc"]
    resolvable = resolution(first, last)

    if overall <= resolvable:
        shape = (
            f"Across the whole range, going from {first['images']} to {last['images']} "
            f"training images moved validation AUC by {overall:+.4f}, which does not clear "
            f"the {resolvable:.4f} this measurement can resolve. Dataset size has no "
            f"demonstrable effect on this architecture over the range available, so the "
            f"complaint that 800 images is too few is not what limits the result here."
        )
    else:
        shape = (
            f"Dataset size matters, and measurably: {first['images']} training images give "
            f"{first['mean_auc']:.4f} validation AUC and {last['images']} give "
            f"{last['mean_auc']:.4f}, a rise of {overall:.4f} against the {resolvable:.4f} "
            f"this measurement can resolve."
        )

    # The separate question, and the one the criticism is really about: has it
    # stopped rising by the time the data runs out?
    edge = last["mean_auc"] - previous["mean_auc"]
    edge_resolvable = resolution(previous, last)
    added = last["images"] - previous["images"]

    if edge <= 0:
        shape += (
            f" The curve has nonetheless stopped climbing before the data runs out: the "
            f"last {added} images moved it by {edge:+.4f}. More radiographs of this kind "
            f"would not be the remedy."
        )
    elif edge <= edge_resolvable:
        shape += (
            f" At the right-hand end it is still rising, by {edge:.4f} over the last "
            f"{added} images, but that is inside the {edge_resolvable:.4f} that "
            f"{last['runs']} draws can resolve, so the curve cannot be said to have either "
            f"flattened or kept climbing at {last['images']} images. Resolving that one "
            f"segment would "
            f"take more repeats, not more data."
        )
    else:
        shape += (
            f" It is still rising where the data stops, by {edge:.4f} over the last "
            f"{added} images, clear of the {edge_resolvable:.4f} resolution. The dataset "
            f"is a binding constraint rather than a cosmetic complaint: this model has not "
            f"finished learning from images it does not have."
        )

    if overall <= resolvable:
        return (
            f"{shape} With no measurable trend to extend, no projection of what a larger "
            f"dataset would deliver is made."
        )

    if fit is None or fit["r_squared"] < 0.5:
        quality = (
            "The power-law fit does not describe these points well enough to project "
            "from, so no claim is made about what a larger dataset would deliver."
        )
        return f"{shape} {quality}"

    halving = fit["halving_gain"]
    reach = fit["images_for_auc"]
    # The first target the fit can actually price, if any.
    target, priced = next(
        ((t, reach[f"{t:.2f}"]) for t in TARGETS if reach.get(f"{t:.2f}")), (None, None)
    )

    projection = (
        f"Fitted as a power law, error falls {halving * 100:.0f} per cent for each "
        f"doubling of the training set (R-squared {fit['r_squared']:.2f})."
    )
    if priced and priced > available:
        projection += (
            f" Extended, that puts AUC {target:.2f} at about {priced:,} training images, "
            f"roughly {priced / available:.1f} times what is held. That is an "
            f"extrapolation beyond {available} images and is a projection, not a result: "
            f"it assumes more images of the same kind, labelled the same way, and real "
            f"curves bend where a fit does not."
        )
    elif priced:
        projection += (
            f" The fit already reaches AUC {target:.2f} inside the measured range, which "
            f"means the point estimates scatter around the line rather than following it "
            f"cleanly, and the projection should not be quoted."
        )

    return f"{shape} {projection}"


def write_report(points, runs, fit, available, validation_images):
    statement = verdict(points, fit, available)
    total = round(sum(r["minutes"] for r in runs), 1)
    percentages = [str(int(p["fraction"] * 100)) for p in points]
    shares = (
        " and ".join([", ".join(percentages[:-1]), percentages[-1]])
        if len(percentages) > 1
        else percentages[0]
    )

    lines = [
        "# Does the dataset size limit this model?",
        "",
        "Produced by `ml/scripts/learning_curve.py`. Regenerate rather than edit.",
        "",
        "## The question",
        "",
        "The dataset is 800 images, 559 of them training. Any reader will notice, and",
        '"small" is the easiest criticism to make of a medical imaging result. It is also',
        "not a finding on its own. What matters is whether performance is still improving",
        "with each image added, or whether it stopped improving before the data ran out.",
        "",
        "Those two situations call for opposite conclusions. A curve still climbing says",
        "the dataset is the binding constraint and more radiographs are the remedy. A",
        "curve already flat says more of the same images would change nothing, and the",
        "limit is the architecture, the labels, or the population the images came from.",
        "",
        "## How it was measured",
        "",
        f"The deployed recipe was retrained on {shares}",
        f"per cent of the training split, {len(SEEDS)} times at each size from a different",
        "stratified draw, and scored each time on the same fixed validation split of",
        f"{validation_images} images. The test split was not loaded.",
        "",
        "Every setting is the one the promoted model was trained with, so the 100 per cent",
        "points retrain the deployed model exactly:",
        "",
        "| Setting | Value |",
        "|---|---|",
        "| Architecture | MobileNetV2, ImageNet weights |",
        f"| Augmentation | {SETTINGS['augmentation']} |",
        f"| Dropout | {SETTINGS['dropout']} |",
        f"| Weight decay | {SETTINGS['weight_decay']} |",
        f"| Batch size | {SETTINGS['batch_size']} |",
        f"| Head epochs | {SETTINGS['head_epochs']}, early stopping on validation AUC |",
        f"| Fine-tuning | last {SETTINGS['unfreeze']} base layers "
        f"at {SETTINGS['fine_tune_lr']} |",
        "",
        "Draws are stratified by class. A plain random draw of a quarter of the images",
        "could shift the TB share by several points, and that shift would appear in the",
        "curve as an effect of dataset size when it is nothing of the kind.",
        "",
        "The training seed changes with the draw, so the spread at each size includes the",
        "run-to-run noise of this training procedure rather than hiding it. At 100 per",
        "cent every run sees identical images, so the spread there is that noise alone,",
        "and it is the bar a gap between sizes has to clear to count as a gap.",
        "",
        "## What it shows",
        "",
        "| Training images | Share | Mean AUC | Range across draws | Standard error |",
        "|---|---|---|---|---|",
    ]

    for point in points:
        lines.append(
            f"| {point['images']} | {int(point['fraction'] * 100)}% | "
            f"{point['mean_auc']:.4f} | {point['min_auc']:.4f} to {point['max_auc']:.4f} | "
            f"{point['sem_auc']:.4f} |"
        )

    lines += [
        "",
        "![Learning curve](learning_curve.png)",
        "",
        statement,
        "",
        "AUC is the measure here because it does not depend on a threshold. Sensitivity",
        "at a fixed 0.5 cut-off is recorded per run in `learning_curve.json` but is not",
        "reported above, and should not be: each run calibrates differently, so at an",
        "untuned threshold sensitivity swings with the run rather than with the dataset.",
        "The deployed model's threshold is chosen on validation after training, at 0.102,",
        "and doing that for twelve throwaway models would measure the threshold search",
        "rather than the dataset.",
        "",
    ]

    if fit is not None:
        lines += [
            "## The projection, and what it is worth",
            "",
            "Learning curves are conventionally modelled as a power law in the error rather",
            "than in the score: the error falls by a fixed proportion for each doubling of",
            "the data. Fitting a straight line through log(error) against log(images) is two",
            f"parameters rather than three, which is as much as {fit['fitted_on']} "
            f"noisy points can carry. Every run is fitted, not the four means.",
            "",
            f"The fit has R-squared {fit['r_squared']:.2f} and an exponent of "
            f"{fit['exponent']:.3f}.",
            "",
            "| Training images | Projected AUC |",
            "|---|---|",
        ]
        for images, value in fit["projected_auc"].items():
            marker = "" if int(images) <= available else " (extrapolated)"
            lines.append(f"| {int(images):,}{marker} | {value:.4f} |")

        lines += [
            "",
            "Read these as a projection and nothing stronger. They assume more images of",
            "the same kind, labelled to the same standard, from the same two source",
            "collections, and they assume the curve keeps the shape it had over a range",
            f"of {points[0]['images']} to {available} images. Real learning curves bend "
            f"where a two-parameter fit does not.",
            "",
        ]

    lines += [
        "## What this does not say",
        "",
        f"The yardstick is itself small. Every AUC here is measured on {validation_images}",
        "validation images, so each point carries a sampling error of its own that has",
        "nothing to do with how many images the model trained on. The curve measures the",
        "effect of training size against a fixed and noisy ruler; it does not make the",
        "ruler longer.",
        "",
        "Nor does it speak to the population. Montgomery County and Shenzhen are not",
        "Kenya, and a curve showing that more images of the same kind would help says",
        "nothing about whether images of the same kind are the ones that should be",
        "collected. `ml/artifacts/cross_dataset.json` is where that question is measured.",
        "",
        f"Total training time for this measurement: {total:.0f} minutes across "
        f"{len(runs)} runs on a CPU.",
        "",
    ]

    # newline="" keeps the line endings written here, rather than translating
    # them to the platform's. These artefacts are committed, and a file that
    # changes its endings on every regeneration is a diff that says nothing.
    REPORT.write_text("\n".join(lines), encoding="utf-8", newline="")


def main():
    parser = argparse.ArgumentParser(
        description="Measure validation performance against training dataset size."
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="one draw per size instead of three, for a rough shape in a quarter of the time",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="discard recorded runs and measure again from the start",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="redraw the figure and report from the runs already recorded",
    )
    arguments = parser.parse_args()

    seeds = SEEDS[:1] if arguments.quick else SEEDS
    done = [] if arguments.fresh else read_measurements()

    print("loading images")
    train_x, train_y = load_split("train")
    val_x, val_y = load_split("validation")
    available = len(train_y)

    if arguments.report_only:
        if not done:
            raise SystemExit("Nothing recorded yet, so there is no report to write.")
        runs = done
    else:
        recorded = {(r["fraction"], r["seed"]) for r in done}
        wanted = [(f, s) for f in FRACTIONS for s in seeds]
        outstanding = [pair for pair in wanted if pair not in recorded]

        if done and outstanding:
            print(f"\nresuming: {len(done)} runs recorded, {len(outstanding)} to go")
        print(f"\n{len(outstanding)} runs to train, roughly 10 minutes each at full size")

        runs = list(done)
        for position, (fraction, seed) in enumerate(outstanding, start=1):
            index = subsample(train_y, fraction, seed)
            subset_x, subset_y = train_x[index], train_y[index]
            positives = int(subset_y.sum())
            print(
                f"\n[{position}/{len(outstanding)}] {int(fraction * 100)}% "
                f"({len(index)} images, {positives} TB), seed {seed}"
            )

            result = train_once(subset_x, subset_y, val_x, val_y, seed)
            result.update(
                {
                    "fraction": fraction,
                    "images": len(index),
                    "positives": positives,
                    "seed": seed,
                }
            )
            runs.append(result)
            print(
                f"  AUC {result['val_auc']:.4f}  recall {result['val_recall']:.4f}  "
                f"kept {result['stage_kept']}  {result['minutes']:.1f} min"
            )

            # Written after every run. Ninety minutes of training should not be
            # lost to an interrupted shell.
            write_measurements(runs, available, len(val_y))

    points = summarise(runs)
    fit = fit_power_law(runs)
    write_measurements(runs, available, len(val_y))
    draw(points, runs, fit, available)
    write_report(points, runs, fit, available, len(val_y))

    print()
    print(verdict(points, fit, available))
    print()
    for path in (MEASUREMENTS, FIGURE, REPORT):
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
