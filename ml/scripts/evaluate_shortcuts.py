"""
Test whether the classifier is reading pathology or reading shortcuts.

A model can score well by learning something that correlates with the label but
is not the disease. Here the risk is concrete: the two source datasets have
different TB rates, Montgomery 42 per cent against Shenzhen 51 per cent, and
their images differ in exposure, framing and the acquisition markers printed in
the corners. A model that learned "this looks like a Shenzhen image" would score
well on this data and fail completely on a Kenyan X-ray machine.

Three tests, run against the held-out test split:

1.  Source separability. Train a classifier to predict which dataset an image
    came from, ignoring TB entirely. A high score means the shortcut is
    available to be learned. It does not prove the TB model used it.

2.  Corner occlusion. Blank the top band of each test image, where the
    acquisition markers sit, and score again. A drop means the model was relying
    on that region. The bottom band is blanked as a control: losing the same
    number of pixels from a region with no markers should not matter as much.

3.  Lungs against surroundings. Using Montgomery's hand-drawn masks, score each
    image twice: once with everything outside the lungs blanked, once with the
    lungs themselves blanked. If the surroundings alone still carry the signal,
    the model is not reading the lungs.

Blanking sets pixels to -1, which is black on the scale the model is given.

Usage:
    python ml/scripts/evaluate_shortcuts.py
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
from PIL import Image  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
sys.path.insert(0, str(ROOT))

import preprocessing  # noqa: E402
import provenance  # noqa: E402

MANIFEST = ROOT / "ml" / "artifacts" / "splits.csv"
MODELS = ROOT / "ml" / "models"
ARTIFACTS = ROOT / "ml" / "artifacts"
MASKS = ROOT / "data/raw/montgomery/MontgomerySet/ManualMask"

MODEL_VERSION = "tb_mobilenetv2_v1"
BLANK = -1.0
BAND = 0.15
SEED = 42

Image.MAX_IMAGE_PIXELS = None


def load(split=None, source=None):
    with open(MANIFEST, encoding="utf-8") as handle:
        rows = [
            r
            for r in csv.DictReader(handle)
            if (split is None or r["split"] == split)
            and (source is None or r["source"] == source)
        ]
    images = np.stack([preprocessing.prepare(ROOT / r["filepath"]) for r in rows])
    return rows, images


def source_separability():
    """Can a model tell the two datasets apart, ignoring TB entirely?"""
    import keras

    keras.utils.set_random_seed(SEED)
    from keras.applications import MobileNetV2

    print("  loading images")
    train_rows, train_x = load("train")
    test_rows, test_x = load("test")
    train_y = np.array([r["source"] == "shenzhen" for r in train_rows], dtype=np.float32)
    test_y = np.array([r["source"] == "shenzhen" for r in test_rows], dtype=np.float32)

    base = MobileNetV2(weights="imagenet", include_top=False, input_shape=(224, 224, 3))
    base.trainable = False
    model = keras.Sequential(
        [
            base,
            keras.layers.GlobalAveragePooling2D(),
            keras.layers.Dropout(0.2),
            keras.layers.Dense(1, activation="sigmoid"),
        ]
    )
    model.compile(
        optimizer=keras.optimizers.Adam(1e-3),
        loss="binary_crossentropy",
        metrics=[keras.metrics.AUC(name="auc")],
    )
    print("  training a dataset-source classifier")
    model.fit(train_x, train_y, epochs=6, batch_size=32, verbose=0)

    scores = model.predict(test_x, verbose=0).ravel()
    auc = float(roc_auc_score(test_y, scores))
    accuracy = float(np.mean((scores >= 0.5) == test_y))
    print(f"  source AUC {auc:.4f}   accuracy {accuracy:.4f}")
    return {"auc": round(auc, 4), "accuracy": round(accuracy, 4), "test_images": len(test_rows)}


def blank_band(images, where):
    """Blank a horizontal band of each image."""
    copy = images.copy()
    height = copy.shape[1]
    edge = int(height * BAND)
    if where == "top":
        copy[:, :edge, :, :] = BLANK
    else:
        copy[:, -edge:, :, :] = BLANK
    return copy


def occlusion(model, rows, images):
    """Does blanking the marker region change the result?"""
    labels = np.array([int(r["label"]) for r in rows])

    results = {}
    for name, batch in (
        ("intact", images),
        ("top_blanked", blank_band(images, "top")),
        ("bottom_blanked", blank_band(images, "bottom")),
    ):
        scores = model.predict(batch, verbose=0).ravel()
        auc = float(roc_auc_score(labels, scores))
        results[name] = round(auc, 4)
        print(f"  {name:<16} AUC {auc:.4f}")

    results["drop_from_top"] = round(results["intact"] - results["top_blanked"], 4)
    results["drop_from_bottom"] = round(results["intact"] - results["bottom_blanked"], 4)
    return results


def lungs_against_surroundings(model):
    """Where does the signal live: inside the lungs, or outside them?"""
    rows, images = load("test", "montgomery")
    labels = np.array([int(r["label"]) for r in rows])
    print(f"  {len(rows)} Montgomery test images have masks")

    lungs_only = images.copy()
    surroundings_only = images.copy()
    for index, row in enumerate(rows):
        left = np.array(Image.open(MASKS / "leftMask" / row["filename"]).convert("L"))
        right = np.array(Image.open(MASKS / "rightMask" / row["filename"]).convert("L"))
        mask = Image.fromarray(((left > 127) | (right > 127)).astype(np.uint8) * 255)
        small = np.array(mask.resize(preprocessing.INPUT_SIZE, Image.NEAREST)) > 127
        lungs_only[index][~small] = BLANK
        surroundings_only[index][small] = BLANK

    results = {"test_images": len(rows)}
    for name, batch in (
        ("intact", images),
        ("lungs_only", lungs_only),
        ("surroundings_only", surroundings_only),
    ):
        scores = model.predict(batch, verbose=0).ravel()
        auc = float(roc_auc_score(labels, scores))
        results[name] = round(auc, 4)
        print(f"  {name:<20} AUC {auc:.4f}")
    return results


def draw(occluded, regions):
    labels = ["Intact", "Top blanked\n(markers)", "Bottom blanked\n(control)"]
    values = [occluded["intact"], occluded["top_blanked"], occluded["bottom_blanked"]]

    figure, (left, right) = plt.subplots(1, 2, figsize=(11, 4.2))
    left.bar(labels, values, color=["tab:blue", "tab:red", "tab:grey"])
    left.axhline(0.5, linestyle=":", color="black", linewidth=1, label="Chance")
    left.set_ylabel("AUC on the test split")
    left.set_title("Blanking the acquisition markers")
    left.set_ylim(0.4, 1.0)
    left.legend(fontsize=8)

    names = ["Intact", "Lungs only", "Surroundings\nonly"]
    scores = [regions["intact"], regions["lungs_only"], regions["surroundings_only"]]
    right.bar(names, scores, color=["tab:blue", "tab:green", "tab:orange"])
    right.axhline(0.5, linestyle=":", color="black", linewidth=1, label="Chance")
    right.set_ylabel("AUC, Montgomery test images")
    right.set_title("Where does the signal live?")
    right.set_ylim(0.0, 1.0)
    right.legend(fontsize=8)

    plt.tight_layout()
    plt.savefig(ARTIFACTS / "shortcut_tests.png", dpi=150)
    plt.close()


def main():
    import keras

    print(f"model {MODEL_VERSION}\n")
    model = keras.models.load_model(MODELS / f"{MODEL_VERSION}.keras")

    print("1. can a model tell the two datasets apart?")
    separability = source_separability()

    print("\n2. does blanking the marker region change the result?")
    rows, images = load("test")
    occluded = occlusion(model, rows, images)

    print("\n3. lungs against surroundings")
    regions = lungs_against_surroundings(model)

    draw(occluded, regions)

    summary = {
        "model_version": MODEL_VERSION,
        "provenance": provenance.describe(),
        "source_separability": separability,
        "occlusion": occluded,
        "regions": regions,
        "notes": {
            "source_separability": (
                "A high score means the shortcut exists and could be learned. It does "
                "not by itself prove the TB classifier used it."
            ),
            "occlusion": (
                "The bottom band is a control: it removes the same number of pixels "
                "from a region carrying no acquisition markers."
            ),
            "regions": (
                "Montgomery only, because only it has masks. The sample is small, so "
                "these figures are indicative rather than precise."
            ),
        },
    }
    (ARTIFACTS / "shortcut_tests.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print(f"\nsummary -> {(ARTIFACTS / 'shortcut_tests.json').relative_to(ROOT)}")
    print(f"figure  -> {(ARTIFACTS / 'shortcut_tests.png').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
