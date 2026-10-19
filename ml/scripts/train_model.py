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
import time
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))

import preprocessing  # noqa: E402
import provenance  # noqa: E402

MANIFEST = ROOT / "ml" / "artifacts" / "splits.csv"
MODELS = ROOT / "ml" / "models"
STAGING = MODELS / "checkpoints"
ARTIFACTS = ROOT / "ml" / "artifacts"
EXPERIMENTS = ARTIFACTS / "experiments.csv"

MODEL_VERSION = "tb_mobilenetv2_v1"
SEED = 42

# Candidate architectures.
#
# The proposal names MobileNetV2 and gives a deployment reason: a clinic in a
# resource-constrained setting runs this on a CPU. That is a reason to prefer a
# compact network, not evidence that a compact network suffices, so the
# alternatives here exist to test the claim rather than to replace it.
#
# Every one is a pretrained ImageNet feature extractor carrying the same
# classification head, trained on the same splits with the same schedule and
# seed, so a difference in validation AUC is attributable to the architecture.
#
# They disagree about how pixels should arrive. ml/preprocessing.py stays the
# single source of truth for turning a file into an array and always produces
# [-1, 1]; each entry says how to convert that into what its network expects,
# so preprocessing stays shared and the adaptation stays visible.
ARCHITECTURES = {
    "mobilenetv2": {
        "module": "keras.applications.mobilenet_v2",
        "callable": "MobileNetV2",
        # MobileNetV2 is itself trained on [-1, 1]; nothing to convert.
        "input_range": "signed_unit",
        "note": "Proposal section 3.2.3. Depthwise separable convolutions.",
    },
    "resnet50": {
        "module": "keras.applications.resnet50",
        "callable": "ResNet50",
        # Caffe-style: BGR channel order, zero-centred on the ImageNet mean,
        # expecting 0-255 rather than [-1, 1].
        "input_range": "caffe",
        "note": "Residual connections. The common heavyweight baseline.",
    },
    "efficientnetb0": {
        "module": "keras.applications.efficientnet",
        "callable": "EfficientNetB0",
        # Keras EfficientNet normalises inside the model and wants raw 0-255.
        "input_range": "raw255",
        "note": "Compound scaling. Compact like MobileNetV2 but deeper.",
    },
    "scratch": {
        # The simpler baseline the CS Project II checklist asks for. A plain
        # convolutional network with no pretrained weights, so the comparison
        # answers whether transfer learning was needed at all rather than
        # assuming it. 559 training images is far too few to fit a network of
        # this kind from nothing, and the point of the baseline is to show that
        # rather than to state it.
        "module": None,
        "callable": "SmallCNN",
        "input_range": "signed_unit",
        "pretrained": False,
        "note": "No pretrained weights. The control for transfer learning.",
    },
}
DEFAULT_ARCHITECTURE = "mobilenetv2"

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


def build_scratch_base(input_shape):
    """A plain convolutional network, trained from nothing.

    Deliberately conventional: a stride-2 stem, then four blocks of one
    convolution and a pooling step, each doubling the channels and halving the
    resolution, ending at 7 by 7 like MobileNetV2 does. Batch normalisation
    after each convolution keeps it trainable without pretrained statistics to
    inherit.

    The stem halves the resolution before any full-width convolution runs. The
    first layers of a network at 224 by 224 dominate its cost, and this is a
    baseline whose purpose is to be beaten, not to be competitive; a version
    that took hours to train would answer the same question and delay the
    comparison it belongs to.
    """
    import keras

    inputs = keras.Input(shape=input_shape)
    x = keras.layers.Conv2D(16, 3, strides=2, padding="same", use_bias=False)(inputs)
    x = keras.layers.BatchNormalization()(x)
    x = keras.layers.ReLU()(x)

    for filters in (32, 64, 128, 256):
        x = keras.layers.Conv2D(filters, 3, padding="same", use_bias=False)(x)
        x = keras.layers.BatchNormalization()(x)
        x = keras.layers.ReLU()(x)
        x = keras.layers.MaxPooling2D(2)(x)

    return keras.Model(inputs, x, name="small_cnn")


def build_input_adapter(input_range):
    """Convert the shared [-1, 1] arrays into what this network was trained on.

    Returns None when no conversion is needed, so the common case adds no layer.
    """
    import keras

    if input_range == "signed_unit":
        return None

    if input_range == "raw255":
        return keras.layers.Rescaling(127.5, offset=127.5, name="to_raw_255")

    if input_range == "caffe":
        # Built from stock layers rather than a Lambda wrapping
        # keras.applications.resnet50.preprocess_input: a Lambda holding a
        # plain function trains correctly but cannot be deserialised, so the
        # saved model would not load back. A one-epoch run caught that.
        #
        # Caffe preprocessing is two steps: put the channels in BGR order, then
        # subtract the per-channel ImageNet mean from values in 0-255. The
        # channel swap is omitted deliberately. ml/preprocessing.py replicates
        # one intensity channel three times, so the three channels are
        # identical and reversing them cannot change anything; subtracting the
        # BGR means in place therefore gives exactly the same array the swap
        # would have produced.
        return keras.Sequential(
            [
                keras.layers.Rescaling(127.5, offset=127.5),
                keras.layers.Normalization(
                    axis=-1,
                    mean=[103.939, 116.779, 123.68],
                    variance=[1.0, 1.0, 1.0],
                ),
            ],
            name="to_caffe",
        )

    raise ValueError(f"Unknown input range: {input_range}")


def build_model(augmentation_level, dropout=0.3, architecture=DEFAULT_ARCHITECTURE):
    """A pretrained base with the classification head from proposal section 3.2.3.

    The head is a separate model rather than loose layers so that Grad-CAM can
    later split the network cleanly at the final convolutional layer.
    """
    import importlib

    import keras

    spec = ARCHITECTURES[architecture]
    shape = (*preprocessing.INPUT_SIZE, preprocessing.INPUT_CHANNELS)
    pretrained = spec.get("pretrained", True)

    if pretrained:
        constructor = getattr(importlib.import_module(spec["module"]), spec["callable"])
        base = constructor(weights="imagenet", include_top=False, input_shape=shape)
    else:
        base = build_scratch_base(shape)

    # A pretrained base starts frozen so the random head cannot wreck it. A
    # base with nothing to protect trains from the first epoch; freezing it
    # would leave the head reading random features, which would measure
    # nothing.
    base.trainable = not pretrained

    head = keras.Sequential(
        [
            keras.layers.GlobalAveragePooling2D(),
            keras.layers.BatchNormalization(),
            keras.layers.Dropout(dropout),
            keras.layers.Dense(128, activation="relu"),
            keras.layers.Dropout(max(0.0, dropout - 0.1)),
            keras.layers.Dense(64, activation="relu"),
            keras.layers.Dense(1, activation="sigmoid", name="tb_probability"),
        ],
        name="classification_head",
    )

    inputs = keras.Input(shape=(*preprocessing.INPUT_SIZE, preprocessing.INPUT_CHANNELS))
    augmentation = build_augmentation(augmentation_level)
    x = augmentation(inputs) if augmentation else inputs
    # Augmentation runs in the shared [-1, 1] space, so its constant fill value
    # stays correct for every architecture; conversion happens afterwards.
    adapter = build_input_adapter(spec["input_range"])
    if adapter is not None:
        x = adapter(x)
    # training=False keeps the pretrained batch-normalisation statistics fixed,
    # which is the documented way to fine-tune these models.
    features = base(x, training=False)
    outputs = head(features)

    name = MODEL_VERSION if architecture == DEFAULT_ARCHITECTURE else f"tb_{architecture}"
    return keras.Model(inputs, outputs, name=name), base


def compile_model(model, learning_rate, weight_decay=0.0):
    import keras

    model.compile(
        optimizer=keras.optimizers.Adam(
            learning_rate=learning_rate, weight_decay=weight_decay or None
        ),
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
        "architecture",
        "parameters",
        "augmentation",
        "dropout",
        "weight_decay",
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
    parser.add_argument(
        "--architecture",
        choices=list(ARCHITECTURES),
        default=DEFAULT_ARCHITECTURE,
        help="pretrained base to build on",
    )
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--fine-tune-epochs", type=int, default=15)
    parser.add_argument("--unfreeze", type=int, default=30, help="base layers to unfreeze")
    parser.add_argument("--fine-tune-lr", type=float, default=1e-5)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--dropout", type=float, default=0.3)
    parser.add_argument("--weight-decay", type=float, default=0.0)
    parser.add_argument("--no-fine-tune", action="store_true")
    parser.add_argument("--promote", action="store_true", help="promote this tag and exit")
    args = parser.parse_args()

    STAGING.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    if args.promote:
        promote(args.tag)
        return 0

    set_seeds()
    print(f"run: {args.tag}  ({args.architecture}, augmentation: {args.augmentation})")
    print("loading images")
    train_x, train_y = load_split("train")
    val_x, val_y = load_split("validation")

    # Wall-clock cost is part of the comparison: a network that wins on AUC but
    # cannot be retrained or served on the target hardware has not won.
    started = time.monotonic()
    model, base = build_model(
        args.augmentation, dropout=args.dropout, architecture=args.architecture
    )
    total_parameters = model.count_params()
    print(f"total parameters: {total_parameters:,}")
    trainable = sum(int(np.prod(w.shape)) for w in model.trainable_weights)
    print(f"\ntrainable parameters, stage 1: {trainable:,}")

    # Each stage checkpoints separately. A shared file would let a weaker
    # fine-tuned model overwrite a stronger head-only one, because the callback
    # starts comparing from scratch in the second stage.
    head_checkpoint = STAGING / f"{args.tag}_stage1.keras"
    tuned_checkpoint = STAGING / f"{args.tag}_stage2.keras"
    selected = STAGING / f"{args.tag}_selected.keras"

    print("\nstage 1: training the classification head")
    compile_model(model, learning_rate=1e-3, weight_decay=args.weight_decay)
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
    pretrained = ARCHITECTURES[args.architecture].get("pretrained", True)
    if not pretrained:
        # Nothing is frozen, so there is nothing to unfreeze. Stage 1 already
        # trained the whole network.
        print()
        print("no pretrained weights: the whole network trained in stage 1")
    if pretrained and not args.no_fine_tune:
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

        compile_model(model, learning_rate=args.fine_tune_lr, weight_decay=args.weight_decay)
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
        "architecture": {
            "name": args.architecture,
            "base": ARCHITECTURES[args.architecture]["callable"],
            "weights": "imagenet",
            "input_range": ARCHITECTURES[args.architecture]["input_range"],
            "note": ARCHITECTURES[args.architecture]["note"],
            "total_parameters": int(total_parameters),
            "head": "custom classification head, proposal section 3.2.3",
        },
        "framework": {"tensorflow": tf.__version__, "keras": keras.__version__},
        "seed": SEED,
        "provenance": provenance.describe(MANIFEST),
        "classes": {"0": "Unlikely TB", "1": "Likely TB"},
        "positive_class": 1,
        "preprocessing": preprocessing.describe(),
        "training": {
            "train_images": int(len(train_y)),
            "validation_images": int(len(val_y)),
            "batch_size": args.batch_size,
            "dropout": args.dropout,
            "weight_decay": args.weight_decay,
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
            "architecture": ARCHITECTURES[args.architecture]["callable"],
            "parameters": int(total_parameters),
            "augmentation": args.augmentation,
            "dropout": args.dropout,
            "weight_decay": args.weight_decay,
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

    elapsed = time.monotonic() - started
    metadata["training"]["wall_clock_seconds"] = round(elapsed, 1)
    (STAGING / f"{args.tag}_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    print(f"\nwall clock: {elapsed / 60:.1f} min")
    print(f"model    -> {selected.relative_to(ROOT)}")
    print(f"record   -> {EXPERIMENTS.relative_to(ROOT)}")
    print("promote the chosen run with: --tag <name> --promote")
    return 0


if __name__ == "__main__":
    sys.exit(main())
