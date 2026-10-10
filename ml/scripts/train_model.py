"""
Train the TB classifier: MobileNetV2 transfer learning.

Follows proposal section 3.2.3. Training runs in two stages:

1.  The pretrained base is frozen and only the new classification head is
    trained. The head is the one described in the proposal: global average
    pooling, batch normalisation, dropout, dense layers of 128 and 64 units with
    ReLU, and a single sigmoid output.
2.  The last layers of the base are then unfrozen and trained at a much lower
    learning rate. This stage is discarded if it does not improve validation
    performance.

Images come from the manifest written by `prepare_data.py`, and are prepared by
`ml/preprocessing.py`, the same module the web application uses. Augmentation is
applied to the training split only; validation images are never altered.

**The test split is never loaded by this script.** Model choices are made on the
validation split alone, so the test set stays untouched until final evaluation.

Each run is tagged, writes its own model and metadata under `ml/models/checkpoints`,
and appends a row to `ml/artifacts/experiments.csv`. Nothing is promoted to the
final model path automatically; `--promote` does that once a variant is chosen.

Usage:
    python ml/scripts/train_model.py --tag baseline
    python ml/scripts/train_model.py --tag light-aug --augmentation light
    python ml/scripts/train_model.py --tag no-aug --augmentation none
    python ml/scripts/train_model.py --tag deep-tune --unfreeze 60 --fine-tune-lr 1e-4
    python ml/scripts/train_model.py --tag light-aug --promote
"""

import argparse
import csv
import json
import os
import random
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))

import preprocessing  # noqa: E402

MANIFEST = ROOT / "ml" / "artifacts" / "splits.csv"
MODELS = ROOT / "ml" / "models"
STAGING = MODELS / "checkpoints"
ARTIFACTS = ROOT / "ml" / "artifacts"
EXPERIMENTS = ARTIFACTS / "experiments.csv"

MODEL_VERSION = "tb_mobilenetv2_v1"
SEED = 42

# Provisional. `select_thresholds.py` replaces these with values justified from
# the validation results; every stored prediction records the ones it used.
DECISION_THRESHOLD = 0.50
TRIAGE_LOW_MEDIUM = 0.50
TRIAGE_MEDIUM_HIGH = 0.80

AUGMENTATION_LEVELS = {
    "standard": dict(rotation=0.05, zoom=0.10, translation=0.05, brightness=0.10),
    "light": dict(rotation=0.02, zoom=0.05, translation=0.0, brightness=0.05),
    "none": None,
}


def set_seeds():
    random.seed(SEED)
    np.random.seed(SEED)
    import keras

    keras.utils.set_random_seed(SEED)


def load_split(split):
    """Load one split into memory, prepared exactly as the application prepares it."""
    with open(MANIFEST, encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if r["split"] == split]

    images = np.stack([preprocessing.prepare(ROOT / r["filepath"]) for r in rows])
    labels = np.array([int(r["label"]) for r in rows], dtype=np.float32)
    print(f"  {split:<11} {len(rows):>4} images  ({int(labels.sum())} TB)")
    return images, labels


def build_augmentation(level):
    """Geometric and brightness changes only, and deliberately mild.

    Chest radiographs are anatomically consistent, so heavy augmentation would
    distort medically meaningful structure. There is no horizontal flip: the
    heart lies on one side, and mirroring would teach the model otherwise.
    Edges exposed by rotation are filled with -1, which is black on this scale.
    """
    import keras

    settings = AUGMENTATION_LEVELS[level]
    if settings is None:
        return None

    layers = [
        keras.layers.RandomRotation(
            settings["rotation"], fill_mode="constant", fill_value=-1.0
        ),
        keras.layers.RandomZoom(settings["zoom"], fill_mode="constant", fill_value=-1.0),
    ]
    if settings["translation"]:
        layers.append(
            keras.layers.RandomTranslation(
                settings["translation"],
                settings["translation"],
                fill_mode="constant",
                fill_value=-1.0,
            )
        )
    layers.append(
        keras.layers.RandomBrightness(settings["brightness"], value_range=(-1.0, 1.0))
    )
    return keras.Sequential(layers, name="augmentation")


def build_model(augmentation_level):
    """MobileNetV2 with the classification head from proposal section 3.2.3.

    The head is a separate model rather than loose layers so that Grad-CAM can
    later split the network cleanly at the final convolutional layer.
    """
    import keras
    from keras.applications import MobileNetV2

    base = MobileNetV2(
        weights="imagenet",
        include_top=False,
        input_shape=(*preprocessing.INPUT_SIZE, preprocessing.INPUT_CHANNELS),
    )
    base.trainable = False

    head = keras.Sequential(
        [
            keras.layers.GlobalAveragePooling2D(),
            keras.layers.BatchNormalization(),
            keras.layers.Dropout(0.3),
            keras.layers.Dense(128, activation="relu"),
            keras.layers.Dropout(0.2),
            keras.layers.Dense(64, activation="relu"),
            keras.layers.Dense(1, activation="sigmoid", name="tb_probability"),
        ],
        name="classification_head",
    )

    inputs = keras.Input(shape=(*preprocessing.INPUT_SIZE, preprocessing.INPUT_CHANNELS))
    augmentation = build_augmentation(augmentation_level)
    x = augmentation(inputs) if augmentation else inputs
    # training=False keeps the pretrained batch-normalisation statistics fixed,
    # which is the documented way to fine-tune these models.
    features = base(x, training=False)
    outputs = head(features)

    return keras.Model(inputs, outputs, name=MODEL_VERSION), base


def compile_model(model, learning_rate):
    import keras

    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
        loss="binary_crossentropy",
        metrics=[
            keras.metrics.BinaryAccuracy(name="accuracy"),
            keras.metrics.Precision(name="precision"),
            keras.metrics.Recall(name="recall"),
            keras.metrics.AUC(name="auc"),
        ],
    )


def callbacks_for(checkpoint):
    import keras

    return [
        keras.callbacks.ModelCheckpoint(
            checkpoint, monitor="val_auc", mode="max", save_best_only=True, verbose=0
        ),
        keras.callbacks.EarlyStopping(
            monitor="val_auc", mode="max", patience=8, restore_best_weights=True, verbose=1
        ),
        keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=4, min_lr=1e-7, verbose=1
        ),
    ]


def history_as_lists(history):
    return {key: [float(v) for v in values] for key, values in history.history.items()}


def record_experiment(row):
    """Append one run to the experiment record, creating it if needed."""
    columns = [
        "tag",
        "run_at",
        "augmentation",
        "head_epochs",
        "unfreeze",
        "fine_tune_lr",
        "stage_kept",
        "val_accuracy",
        "val_precision",
        "val_recall",
        "val_auc",
        "val_loss",
    ]
    new = not EXPERIMENTS.exists()
    with open(EXPERIMENTS, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        if new:
            writer.writeheader()
        writer.writerow(row)


def promote(tag):
    """Copy a tagged run to the final model path used by the application."""
    source = STAGING / f"{tag}_selected.keras"
    meta = STAGING / f"{tag}_metadata.json"
    if not source.exists():
        raise SystemExit(f"No trained model tagged '{tag}'. Train it first.")
    shutil.copy2(source, MODELS / f"{MODEL_VERSION}.keras")
    shutil.copy2(meta, MODELS / "metadata.json")
    print(f"promoted '{tag}' to {MODEL_VERSION}.keras")


def main():
    parser = argparse.ArgumentParser(description="Train the TB classifier.")
    parser.add_argument("--tag", default="baseline", help="name for this run")
    parser.add_argument("--augmentation", choices=list(AUGMENTATION_LEVELS), default="standard")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--fine-tune-epochs", type=int, default=15)
    parser.add_argument("--unfreeze", type=int, default=30, help="base layers to unfreeze")
    parser.add_argument("--fine-tune-lr", type=float, default=1e-5)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--no-fine-tune", action="store_true")
    parser.add_argument("--promote", action="store_true", help="promote this tag and exit")
    args = parser.parse_args()

    STAGING.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    if args.promote:
        promote(args.tag)
        return 0

    set_seeds()
    print(f"run: {args.tag}  (augmentation: {args.augmentation})")
    print("loading images")
    train_x, train_y = load_split("train")
    val_x, val_y = load_split("validation")

    model, base = build_model(args.augmentation)
    trainable = sum(int(np.prod(w.shape)) for w in model.trainable_weights)
    print(f"\ntrainable parameters, stage 1: {trainable:,}")

    # Each stage checkpoints separately. A shared file would let a weaker
    # fine-tuned model overwrite a stronger head-only one, because the callback
    # starts comparing from scratch in the second stage.
    head_checkpoint = STAGING / f"{args.tag}_stage1.keras"
    tuned_checkpoint = STAGING / f"{args.tag}_stage2.keras"
    selected = STAGING / f"{args.tag}_selected.keras"

    print("\nstage 1: training the classification head")
    compile_model(model, learning_rate=1e-3)
    first = model.fit(
        train_x,
        train_y,
        validation_data=(val_x, val_y),
        epochs=args.epochs,
        batch_size=args.batch_size,
        callbacks=callbacks_for(head_checkpoint),
        verbose=2,
    )
    history = {"head": history_as_lists(first)}
    best_auc = max(history["head"]["val_auc"])
    print(f"\nbest validation AUC after stage 1: {best_auc:.4f}")

    stage_kept = "head"
    fine_tuned_from = None
    if not args.no_fine_tune:
        print(f"\nstage 2: fine-tuning the last {args.unfreeze} layers of the base")
        from keras.layers import BatchNormalization

        fine_tuned_from = max(0, len(base.layers) - args.unfreeze)
        base.trainable = True
        for layer in base.layers[:fine_tuned_from]:
            layer.trainable = False
        # Batch-normalisation layers stay frozen; updating their statistics on a
        # small dataset destabilises fine-tuning.
        for layer in base.layers:
            if isinstance(layer, BatchNormalization):
                layer.trainable = False

        trainable = sum(int(np.prod(w.shape)) for w in model.trainable_weights)
        print(f"trainable parameters, stage 2: {trainable:,}")

        compile_model(model, learning_rate=args.fine_tune_lr)
        second = model.fit(
            train_x,
            train_y,
            validation_data=(val_x, val_y),
            epochs=args.fine_tune_epochs,
            batch_size=args.batch_size,
            callbacks=callbacks_for(tuned_checkpoint),
            verbose=2,
        )
        history["fine_tune"] = history_as_lists(second)
        improved = max(history["fine_tune"]["val_auc"])
        print(f"\nbest validation AUC after stage 2: {improved:.4f}")
        if improved > best_auc:
            best_auc = improved
            stage_kept = "fine_tune"
        else:
            print("fine-tuning did not improve validation AUC; the head-only model is kept")
            fine_tuned_from = None

    shutil.copy2(tuned_checkpoint if stage_kept == "fine_tune" else head_checkpoint, selected)
    print(f"\nkept the {stage_kept} model")

    import keras
    import tensorflow as tf

    model = keras.models.load_model(selected)
    final = model.evaluate(val_x, val_y, verbose=0, return_dict=True)
    print("\nvalidation performance of the selected model")
    for key, value in final.items():
        print(f"  {key:<10} {value:.4f}")

    metadata = {
        "model_version": MODEL_VERSION,
        "run_tag": args.tag,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "architecture": "MobileNetV2, ImageNet weights, custom classification head",
        "framework": {"tensorflow": tf.__version__, "keras": keras.__version__},
        "seed": SEED,
        "classes": {"0": "Unlikely TB", "1": "Likely TB"},
        "positive_class": 1,
        "preprocessing": preprocessing.describe(),
        "training": {
            "train_images": int(len(train_y)),
            "validation_images": int(len(val_y)),
            "batch_size": args.batch_size,
            "augmentation": args.augmentation,
            "augmentation_settings": AUGMENTATION_LEVELS[args.augmentation],
            "head_learning_rate": 1e-3,
            "fine_tune_learning_rate": args.fine_tune_lr,
            "fine_tuned_from_layer": fine_tuned_from,
            "stage_kept": stage_kept,
        },
        "validation_metrics": {k: round(float(v), 4) for k, v in final.items()},
        "thresholds": {
            "decision": DECISION_THRESHOLD,
            "triage_low_medium": TRIAGE_LOW_MEDIUM,
            "triage_medium_high": TRIAGE_MEDIUM_HIGH,
            "note": "Provisional. To be justified from validation evidence.",
        },
    }
    (STAGING / f"{args.tag}_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    (ARTIFACTS / f"training_history_{args.tag}.json").write_text(
        json.dumps(history, indent=2), encoding="utf-8"
    )

    record_experiment(
        {
            "tag": args.tag,
            "run_at": metadata["created"],
            "augmentation": args.augmentation,
            "head_epochs": len(history["head"]["val_auc"]),
            "unfreeze": args.unfreeze if not args.no_fine_tune else 0,
            "fine_tune_lr": args.fine_tune_lr,
            "stage_kept": stage_kept,
            "val_accuracy": round(float(final["accuracy"]), 4),
            "val_precision": round(float(final["precision"]), 4),
            "val_recall": round(float(final["recall"]), 4),
            "val_auc": round(float(final["auc"]), 4),
            "val_loss": round(float(final["loss"]), 4),
        }
    )

    print(f"\nmodel    -> {selected.relative_to(ROOT)}")
    print(f"record   -> {EXPERIMENTS.relative_to(ROOT)}")
    print("promote the chosen run with: --tag <name> --promote")
    return 0


if __name__ == "__main__":
    sys.exit(main())
