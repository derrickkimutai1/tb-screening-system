"""
Train on one hospital, test on the other.

The main evaluation splits a pool of images from two sources and reports on a
held-out slice of that same pool. That measures performance on unseen images,
but not on an unseen *hospital*. Since the system is intended for Kenyan
clinics, whose machines appear in neither dataset, the harder and more honest
question is how much performance survives a change of source.

This script answers it directly. It trains only on Shenzhen images and tests on
every Montgomery image, none of which the model has seen. The drop between the
two is the cost of changing hospital, and it is the closest estimate available
of what deployment elsewhere would cost.

It also repeats the lungs-against-surroundings test on all 138 Montgomery
images rather than the 21 available in the ordinary test split, so the finding
rests on a reasonable sample.

Usage:
    python ml/scripts/cross_dataset.py
"""

import csv
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
sys.path.insert(0, str(ROOT))

import preprocessing  # noqa: E402
import provenance  # noqa: E402

MANIFEST = ROOT / "ml" / "artifacts" / "splits.csv"
MODELS = ROOT / "ml" / "models"
STAGING = MODELS / "checkpoints"
ARTIFACTS = ROOT / "ml" / "artifacts"
MASKS = ROOT / "data/raw/montgomery/MontgomerySet/ManualMask"

SEED = 42
BLANK = -1.0
TARGET_SENSITIVITY = 0.90


def rows_for(source, splits=None):
    with open(MANIFEST, encoding="utf-8") as handle:
        return [
            r
            for r in csv.DictReader(handle)
            if r["source"] == source and (splits is None or r["split"] in splits)
        ]


def load(rows):
    images = np.stack([preprocessing.prepare(ROOT / r["filepath"]) for r in rows])
    labels = np.array([int(r["label"]) for r in rows], dtype=np.float32)
    return images, labels


def build():
    import keras
    from keras.applications import MobileNetV2

    keras.utils.set_random_seed(SEED)
    base = MobileNetV2(weights="imagenet", include_top=False, input_shape=(224, 224, 3))
    base.trainable = False

    head = keras.Sequential(
        [
            keras.layers.GlobalAveragePooling2D(),
            keras.layers.BatchNormalization(),
            keras.layers.Dropout(0.3),
            keras.layers.Dense(128, activation="relu"),
            keras.layers.Dropout(0.2),
            keras.layers.Dense(64, activation="relu"),
            keras.layers.Dense(1, activation="sigmoid"),
        ],
        name="classification_head",
    )
    augmentation = keras.Sequential(
        [
            keras.layers.RandomRotation(0.02, fill_mode="constant", fill_value=-1.0),
            keras.layers.RandomZoom(0.05, fill_mode="constant", fill_value=-1.0),
            keras.layers.RandomBrightness(0.05, value_range=(-1.0, 1.0)),
        ],
        name="augmentation",
    )

    inputs = keras.Input(shape=(224, 224, 3))
    outputs = head(base(augmentation(inputs), training=False))
    return keras.Model(inputs, outputs), base


def compile_for(model, learning_rate):
    import keras

    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate),
        loss="binary_crossentropy",
        metrics=[keras.metrics.AUC(name="auc")],
    )


def specificity_at(labels, scores, target):
    """Best specificity available while holding sensitivity at or above target."""
    best = (0.0, None)
    for threshold in np.unique(np.round(scores, 3)):
        predicted = scores >= threshold
        tp = np.sum(predicted & (labels == 1))
        fn = np.sum(~predicted & (labels == 1))
        tn = np.sum(~predicted & (labels == 0))
        fp = np.sum(predicted & (labels == 0))
        sensitivity = tp / (tp + fn) if tp + fn else 0
        specificity = tn / (tn + fp) if tn + fp else 0
        if sensitivity >= target and specificity > best[0]:
            best = (float(specificity), float(threshold))
    return best


def lung_regions(rows, images):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    lungs_only = images.copy()
    surroundings_only = images.copy()
    for index, row in enumerate(rows):
        left = np.array(Image.open(MASKS / "leftMask" / row["filename"]).convert("L"))
        right = np.array(Image.open(MASKS / "rightMask" / row["filename"]).convert("L"))
        mask = Image.fromarray(((left > 127) | (right > 127)).astype(np.uint8) * 255)
        small = np.array(mask.resize(preprocessing.INPUT_SIZE, Image.NEAREST)) > 127
        lungs_only[index][~small] = BLANK
        surroundings_only[index][small] = BLANK
    return lungs_only, surroundings_only


def main():
    import keras
    from sklearn.metrics import roc_auc_score

    print("training on Shenzhen only, testing on every Montgomery image\n")

    train_rows = rows_for("shenzhen", {"train"})
    val_rows = rows_for("shenzhen", {"validation"})
    test_rows = rows_for("montgomery")

    print(f"  train      {len(train_rows):>4} Shenzhen images")
    print(f"  validation {len(val_rows):>4} Shenzhen images")
    print(f"  test       {len(test_rows):>4} Montgomery images, none seen in training")

    train_x, train_y = load(train_rows)
    val_x, val_y = load(val_rows)
    test_x, test_y = load(test_rows)

    model, base = build()
    STAGING.mkdir(parents=True, exist_ok=True)
    checkpoint = STAGING / "cross_dataset.keras"
    callbacks = [
        keras.callbacks.ModelCheckpoint(
            checkpoint, monitor="val_auc", mode="max", save_best_only=True
        ),
        keras.callbacks.EarlyStopping(
            monitor="val_auc", mode="max", patience=8, restore_best_weights=True
        ),
    ]

    print("\n  stage 1: head")
    compile_for(model, 1e-3)
    model.fit(
        train_x,
        train_y,
        validation_data=(val_x, val_y),
        epochs=30,
        batch_size=32,
        callbacks=callbacks,
        verbose=2,
    )

    print("\n  stage 2: fine-tuning")
    from keras.layers import BatchNormalization

    base.trainable = True
    for layer in base.layers[: len(base.layers) - 60]:
        layer.trainable = False
    for layer in base.layers:
        if isinstance(layer, BatchNormalization):
            layer.trainable = False
    compile_for(model, 1e-4)
    model.fit(
        train_x,
        train_y,
        validation_data=(val_x, val_y),
        epochs=15,
        batch_size=32,
        callbacks=callbacks,
        verbose=2,
    )

    model = keras.models.load_model(checkpoint)

    within = float(roc_auc_score(val_y, model.predict(val_x, verbose=0).ravel()))
    scores = model.predict(test_x, verbose=0).ravel()
    across = float(roc_auc_score(test_y, scores))
    specificity, threshold = specificity_at(test_y, scores, TARGET_SENSITIVITY)

    print("\n  results")
    print(f"    within Shenzhen, validation AUC   {within:.4f}")
    print(f"    across to Montgomery, test AUC    {across:.4f}")
    print(f"    cost of changing hospital         {within - across:+.4f}")
    print(f"    specificity at {TARGET_SENSITIVITY:.0%} sensitivity   {specificity:.4f}")

    print("\n  lungs against surroundings, all 138 Montgomery images")
    lungs_only, surroundings_only = lung_regions(test_rows, test_x)
    regions = {"intact": round(across, 4)}
    for name, batch in (("lungs_only", lungs_only), ("surroundings_only", surroundings_only)):
        value = float(roc_auc_score(test_y, model.predict(batch, verbose=0).ravel()))
        regions[name] = round(value, 4)
        print(f"    {name:<20} AUC {value:.4f}")

    summary = {
        "provenance": provenance.describe(),
        "trained_on": {"source": "shenzhen", "images": len(train_rows)},
        "validated_on": {"source": "shenzhen", "images": len(val_rows)},
        "tested_on": {"source": "montgomery", "images": len(test_rows)},
        "auc_within_source": round(within, 4),
        "auc_across_source": round(across, 4),
        "generalisation_cost": round(within - across, 4),
        "specificity_at_target_sensitivity": {
            "target_sensitivity": TARGET_SENSITIVITY,
            "specificity": round(specificity, 4),
            "threshold": threshold,
        },
        "regions": regions,
        "note": (
            "Every Montgomery image is unseen, so this is a genuine external test. "
            "The region test now uses all 138 images rather than the 21 in the "
            "ordinary test split."
        ),
    }
    (ARTIFACTS / "cross_dataset.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"\n  summary -> {(ARTIFACTS / 'cross_dataset.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
