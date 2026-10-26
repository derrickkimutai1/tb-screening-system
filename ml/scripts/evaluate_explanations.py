"""
Measure whether the Grad-CAM explanations actually look at the lungs.

Showing a heatmap is not the same as showing a useful one. A model can reach a
good score by reading something other than pathology, such as acquisition
markers, image borders, or differences between the two source datasets, and
Grad-CAM will faithfully highlight whatever it used.

Montgomery ships a hand-drawn left and right lung mask for each of its 138
images, so this can be measured rather than judged by eye. For each image the
script computes:

    share    the fraction of strongly activated pixels that fall inside the lungs
    area     the fraction of the whole image the lungs occupy
    lift     share divided by area

Lift is the figure that matters. A lift of 1.0 means the activation is spread as
though it had been placed at random, carrying no preference for the lungs at all.
A model reading lung pathology should score well above 1.

Only Montgomery images are measured, because only they have masks. Shenzhen has
none, so its explanations cannot be checked this way.

Usage:
    python ml/scripts/evaluate_explanations.py
    python ml/scripts/evaluate_explanations.py --split test --activation 0.5
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
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
sys.path.insert(0, str(ROOT))

import preprocessing  # noqa: E402

from screening.services.occlusion import PATCH, STRIDE  # noqa: E402

MANIFEST = ROOT / "ml" / "artifacts" / "splits.csv"
MODELS = ROOT / "ml" / "models"
ARTIFACTS = ROOT / "ml" / "artifacts"
MASKS = ROOT / "data/raw/montgomery/MontgomerySet/ManualMask"

MODEL_VERSION = "tb_mobilenetv2_v1"
METHOD_NAMES = {
    "gradcam": "Grad-CAM",
    "occlusion": "Occlusion",
    "scorecam": "Score-CAM",
}
Image.MAX_IMAGE_PIXELS = None


def lung_mask(filename):
    """Combine the left and right hand-drawn masks into one lung region."""
    left = np.array(Image.open(MASKS / "leftMask" / filename).convert("L"))
    right = np.array(Image.open(MASKS / "rightMask" / filename).convert("L"))
    return (left > 127) | (right > 127)


def measure(rows, model, generator, activation, layer=None):
    from screening.services.gradcam import ExplanationUnavailable

    results = []
    for row in rows:
        try:
            cam = generator.heatmap(
                model, preprocessing.prepare(ROOT / row["filepath"]), layer_name=layer
            )
        except ExplanationUnavailable:
            continue

        lungs = lung_mask(row["filename"])
        enlarged = np.array(
            Image.fromarray(cam).resize((lungs.shape[1], lungs.shape[0]), Image.BILINEAR)
        )
        hot = enlarged >= activation
        if not hot.any():
            continue

        share = float((hot & lungs).sum() / hot.sum())
        area = float(lungs.mean())
        results.append(
            {
                "filename": row["filename"],
                "label": int(row["label"]),
                "share_in_lungs": round(share, 4),
                "lung_area": round(area, 4),
                "lift": round(share / area, 4) if area else None,
            }
        )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--split",
        default="test",
        choices=["train", "validation", "development", "test", "all"],
        help=(
            "development is train plus validation: the images to choose a "
            "setting on, so that the reported figure is not measured on the "
            "same data the setting was tuned against."
        ),
    )
    parser.add_argument(
        "--activation",
        type=float,
        default=0.5,
        help="a pixel counts as activated at or above this share of the peak",
    )
    parser.add_argument(
        "--layer",
        default=None,
        help=(
            "base layer to read the map from; defaults to the one the application "
            "uses. Pass out_relu to measure the 7 by 7 map for comparison. "
            "Grad-CAM only."
        ),
    )
    parser.add_argument(
        "--method",
        default="gradcam",
        choices=["gradcam", "occlusion", "scorecam"],
        help=(
            "which explanation to measure. Both are scored by the same lung-mask "
            "lift, which is the only way the choice between them can be settled."
        ),
    )
    parser.add_argument(
        "--patch", type=int, default=None, help="occluding patch size in pixels"
    )
    parser.add_argument(
        "--stride", type=int, default=None, help="how far the patch moves each step"
    )
    parser.add_argument(
        "--labels",
        default="all",
        choices=["all", "tb", "normal"],
        help=(
            "which images to measure. On a normal radiograph there is no lesion to "
            "find, so the lung-mask question has no right answer there and the "
            "combined figure mixes two different questions."
        ),
    )
    args = parser.parse_args()

    if not MASKS.is_dir():
        raise SystemExit(f"No lung masks at {MASKS}. Extract the Montgomery archive first.")

    with open(MANIFEST, encoding="utf-8") as handle:
        rows = [
            r
            for r in csv.DictReader(handle)
            if r["source"] == "montgomery"
            and (
                args.split == "all"
                or r["split"] == args.split
                or (args.split == "development" and r["split"] in {"train", "validation"})
            )
        ]
    if args.labels != "all":
        wanted = "1" if args.labels == "tb" else "0"
        rows = [r for r in rows if r["label"] == wanted]
    if not rows:
        raise SystemExit(f"No Montgomery images in the {args.split} split.")

    import keras

    from screening.services.gradcam import EXPLANATION_LAYER, GradCAMGenerator

    print(f"model  {MODEL_VERSION}")
    print(f"images {len(rows)} Montgomery radiographs from the {args.split} split")

    model = keras.models.load_model(MODELS / f"{MODEL_VERSION}.keras")

    if args.method == "scorecam":
        from screening.services.scorecam import CHANNELS, ScoreCAMGenerator

        generator = ScoreCAMGenerator()
        layer_used = f"scorecam top {CHANNELS} of {EXPLANATION_LAYER}"
        print(f"method {layer_used}")
    elif args.method == "occlusion":
        from screening.services.occlusion import OcclusionGenerator

        generator = OcclusionGenerator()
        if args.patch:
            generator.patch = args.patch
        if args.stride:
            generator.stride = args.stride
        layer_used = f"occlusion patch {args.patch or PATCH} stride {args.stride or STRIDE}"
        print(f"method {layer_used}")
    else:
        generator = GradCAMGenerator()

    results = measure(rows, model, generator, args.activation, layer=args.layer)

    if args.method == "gradcam":
        # Report the layer actually used, which may be the fallback rather than
        # the one asked for.
        layer_used = generator.layer_used() or "unknown"
        print(f"layer  {layer_used}")
    if not results:
        raise SystemExit("No explanations could be produced.")

    settings = f"-{args.split}-{args.labels}"
    if args.method == "occlusion":
        settings = f"-p{args.patch or PATCH}s{args.stride or STRIDE}{settings}"

    shares = np.array([r["share_in_lungs"] for r in results])
    areas = np.array([r["lung_area"] for r in results])
    lifts = np.array([r["lift"] for r in results])

    print()
    print(
        f"  activation inside the lungs  mean {shares.mean():.1%}  "
        f"median {np.median(shares):.1%}"
    )
    print(f"  lungs as a share of image    mean {areas.mean():.1%}")
    print(
        f"  lift                         mean {lifts.mean():.2f}  median {np.median(lifts):.2f}"
    )

    tb = lifts[[r["label"] == 1 for r in results]]
    normal = lifts[[r["label"] == 0 for r in results]]
    if len(tb):
        print(f"  lift on TB cases             mean {tb.mean():.2f}  ({len(tb)} images)")
    if len(normal):
        print(
            f"  lift on normal cases         mean {normal.mean():.2f}  ({len(normal)} images)"
        )

    verdict = (
        "the explanations are no more concentrated on the lungs than chance"
        if lifts.mean() < 1.25
        else "the explanations favour the lungs"
    )
    print(f"\n  {verdict}")

    plt.figure(figsize=(7, 4.2))
    plt.hist(lifts, bins=12, edgecolor="white")
    plt.axvline(1.0, color="black", linestyle="--", linewidth=1, label="Chance (lift = 1)")
    plt.axvline(
        lifts.mean(), color="tab:red", linewidth=1.5, label=f"Mean = {lifts.mean():.2f}"
    )
    plt.xlabel("Lift: activation in lungs relative to lung area")
    plt.ylabel("Images")
    plt.title(
        f"{METHOD_NAMES[args.method]} lung concentration "
        f"from {layer_used}, Montgomery {args.split} split"
    )
    plt.legend(fontsize=8)
    plt.tight_layout()
    # Named after the layer when one was asked for, so a comparison between
    # two layers leaves two figures rather than overwriting the first.
    if args.method != "gradcam":
        figure = ARTIFACTS / f"{args.method}{settings}_lung_concentration.png"
    else:
        figure = ARTIFACTS / f"gradcam-{layer_used}{settings}_lung_concentration.png"
    plt.savefig(figure, dpi=150)
    plt.close()

    summary = {
        "model_version": MODEL_VERSION,
        "split": args.split,
        "images": len(results),
        "activation_threshold": args.activation,
        "method": args.method,
        "layer": layer_used,
        "share_in_lungs_mean": round(float(shares.mean()), 4),
        "lung_area_mean": round(float(areas.mean()), 4),
        "lift_mean": round(float(lifts.mean()), 4),
        "lift_median": round(float(np.median(lifts)), 4),
        "lift_tb_mean": round(float(tb.mean()), 4) if len(tb) else None,
        "lift_normal_mean": round(float(normal.mean()), 4) if len(normal) else None,
        "interpretation": verdict,
        "note": (
            "Only Montgomery images carry hand-drawn lung masks, so only they can be "
            "checked. A lift near 1 means the activation is distributed as though placed "
            "at random with respect to the lungs."
        ),
        "per_image": results,
    }
    if args.method != "gradcam":
        destination = ARTIFACTS / f"{args.method}{settings}_evaluation.json"
    else:
        destination = ARTIFACTS / f"gradcam-{layer_used}{settings}_evaluation.json"
    destination.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n  summary -> {destination.relative_to(ROOT)}")
    print(f"  figure  -> {figure.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
