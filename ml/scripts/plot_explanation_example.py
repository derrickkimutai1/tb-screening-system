"""
The worked example: one radiograph, both explanations, and what each scored.

The figure this writes is the one that gets put on a slide and asked about, so
every number printed on it is computed here from the model and the hand-drawn
lung masks rather than typed in. An earlier version of this figure was drawn by
hand and carried two lifts, 1.11 and 1.63, that were neither this film's values
nor the current dataset means: they were dataset means from a run that had since
been superseded, printed beside a single image as though they described it. Both
faults come from the same cause, which is a figure that no script owns. This
script owns it.

Two different quantities appear on the figure and they are labelled apart,
because conflating them is the mistake that was there before:

    lift on this film    measured on the radiograph shown, from its own mask
    mean lift            the average over all 58 Montgomery TB films

Lift is the share of the highlighted area that falls inside the drawn lung
outline, divided by the share of the frame the lungs occupy. A lift of 1.00 is
what scattering the same amount of highlight at random would give, so it is the
number the method has to beat before it has shown anything at all. The outline
is drawn on both heatmap panels so the figure explains its own arithmetic.

The maps come from the application's own generators and are drawn by the
application's own renderer, so what the figure shows is what the system
produces, not a reimplementation of it that could quietly diverge.

Usage:
    .venv/Scripts/python.exe ml/scripts/plot_explanation_example.py
    .venv/Scripts/python.exe ml/scripts/plot_explanation_example.py --film MCUCXR_0141_1.png
"""

import argparse
import csv
import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import matplotlib

matplotlib.use("Agg")
import cv2  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
sys.path.insert(0, str(ROOT))

import preprocessing  # noqa: E402

MANIFEST = ROOT / "ml" / "artifacts" / "splits.csv"
ARTIFACTS = ROOT / "ml" / "artifacts"
MODELS = ROOT / "ml" / "models"
MASKS = ROOT / "data/raw/montgomery/MontgomerySet/ManualMask"
FIGURE = ARTIFACTS / "explanation_side_by_side.png"

MODEL_VERSION = "tb_mobilenetv2_v1"

# The film the figure has always used: Montgomery, confirmed TB, and in the
# test split, so it is one the model never saw. Changing it is a flag rather
# than a default, because picking the film that flatters the method after
# seeing the results is how a figure stops being evidence.
DEFAULT_FILM = "MCUCXR_0104_1.png"

# A pixel counts as highlighted at or above this share of the map's peak. The
# same value the evaluation script uses; the two numbers have to be comparable.
ACTIVATION = 0.5

INK = "#141414"
MUTED = "#5a5a5a"
RULE = "#c9c9c9"
PAPER = "#fbfbf9"


def lung_mask(filename):
    """The two hand-drawn masks combined into one lung region."""
    left = np.array(Image.open(MASKS / "leftMask" / filename).convert("L"))
    right = np.array(Image.open(MASKS / "rightMask" / filename).convert("L"))
    return (left > 127) | (right > 127)


def lift_of(cam, lungs):
    """How much more of the highlight lands on the lungs than chance would put there.

    Computed exactly as evaluate_explanations.py computes it, so the figure and
    the tables cannot disagree.
    """
    enlarged = np.array(
        Image.fromarray(cam).resize((lungs.shape[1], lungs.shape[0]), Image.BILINEAR)
    )
    hot = enlarged >= ACTIVATION
    if not hot.any():
        return None, None
    share = float((hot & lungs).sum() / hot.sum())
    area = float(lungs.mean())
    return (share / area if area else None), share


def stored_lift(artefact, filename):
    """The lift recorded for this film by the evaluation run, if there is one."""
    path = ARTIFACTS / artefact
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data.get("per_image", []):
        if row["filename"] == filename:
            return row["lift"]
    return None


def read_json(name):
    path = ARTIFACTS / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def wrap(text, width=180):
    """Break a footer line where the words allow rather than where the edge is."""
    return textwrap.fill(text, width)


def panel(axis, image, title, subtitle=None, cmap=None):
    axis.imshow(image, cmap=cmap)
    axis.set_xticks([])
    axis.set_yticks([])
    for side in axis.spines.values():
        side.set_edgecolor(RULE)
        side.set_linewidth(0.8)
    axis.set_title(title, fontsize=11, color=INK, pad=8, loc="left")
    if subtitle:
        axis.set_xlabel(subtitle, fontsize=9.5, color=MUTED, labelpad=7)


def outline(axis, lungs, shape):
    """Trace the drawn lung boundary over a panel."""
    small = cv2.resize(
        lungs.astype(np.uint8), (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST
    )
    axis.contour(small, levels=[0.5], colors="white", linewidths=0.9, alpha=0.85)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--film",
        default=DEFAULT_FILM,
        help=f"Montgomery filename to illustrate (default {DEFAULT_FILM})",
    )
    parser.add_argument("--out", default=str(FIGURE), help="where to write the figure")
    args = parser.parse_args()

    if not MASKS.is_dir():
        raise SystemExit(f"No lung masks at {MASKS}. Extract the Montgomery archive first.")

    with open(MANIFEST, encoding="utf-8") as handle:
        row = next((r for r in csv.DictReader(handle) if r["filename"] == args.film), None)
    if row is None:
        raise SystemExit(f"{args.film} is not in {MANIFEST.name}")
    if row["source"] != "montgomery":
        raise SystemExit(f"{args.film} has no lung mask; only Montgomery films do")

    source = ROOT / row["filepath"]
    if not source.exists():
        raise SystemExit(f"{source} is missing")

    import keras

    from screening.services.gradcam import EXPLANATION_LAYER, GradCAMGenerator
    from screening.services.occlusion import PATCH, STRIDE, OcclusionGenerator
    from screening.services.overlays import render

    print(f"film   {args.film}  ({row['split']} split, label {row['label']})")
    model = keras.models.load_model(MODELS / f"{MODEL_VERSION}.keras")
    prepared = preprocessing.prepare(source)
    score = float(model.predict(prepared[np.newaxis, ...], verbose=0)[0, 0])

    metrics = read_json("metrics.json") or {}
    low = metrics.get("decision_threshold")
    high = metrics.get("high_suspicion_threshold")
    if high and score >= high:
        band = "high suspicion"
    elif low and score >= low:
        band = "suspicious"
    else:
        band = "not flagged"
    print(f"score  {score:.4f}  ({band})")

    lungs = lung_mask(args.film)
    maps, lifts, overlays = {}, {}, {}
    with tempfile.TemporaryDirectory() as scratch:
        for key, generator in (
            ("gradcam", GradCAMGenerator()),
            ("occlusion", OcclusionGenerator()),
        ):
            print(f"  computing {key}...")
            cam = generator.heatmap(model, prepared)
            maps[key] = cam
            lifts[key], _ = lift_of(cam, lungs)
            written = Path(scratch) / f"{key}.png"
            render(source, cam, written)
            overlays[key] = cv2.cvtColor(cv2.imread(str(written)), cv2.COLOR_BGR2RGB)

    # The lift measured here should be the lift the evaluation run recorded for
    # the same film. If it is not, one of the two is stale and the figure must
    # not be published until that is resolved.
    checks = {
        "gradcam": f"gradcam-{EXPLANATION_LAYER}-all-tb_evaluation.json",
        "occlusion": f"occlusion-p{PATCH}s{STRIDE}-all-tb_evaluation.json",
    }
    for key, artefact in checks.items():
        recorded = stored_lift(artefact, args.film)
        if recorded is None:
            print(f"  warning: {artefact} records no lift for this film")
        elif abs(recorded - lifts[key]) > 0.01:
            raise SystemExit(
                f"{key} lift here is {lifts[key]:.4f} but {artefact} records "
                f"{recorded:.4f}. One of them is out of date; re-run "
                f"evaluate_explanations.py before drawing the figure."
            )

    original = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
    tall = max(original.shape)
    if tall > 1024:
        scale = 1024 / tall
        original = cv2.resize(
            original,
            (int(original.shape[1] * scale), int(original.shape[0] * scale)),
            interpolation=cv2.INTER_AREA,
        )

    comparison = read_json("explanation_comparison-all.json")
    held_out = read_json("explanation_comparison-test.json")

    figure, axes = plt.subplots(1, 3, figsize=(12.6, 6.4))
    figure.patch.set_facecolor(PAPER)

    panel(axes[0], original, "Radiograph as uploaded", "no map applied", cmap="gray")

    panel(
        axes[1],
        overlays["gradcam"],
        "Grad-CAM",
        f"lift on this film  {lifts['gradcam']:.2f}",
    )
    outline(axes[1], lungs, overlays["gradcam"].shape)

    panel(
        axes[2],
        overlays["occlusion"],
        f"Occlusion, patch {PATCH} stride {STRIDE}",
        f"lift on this film  {lifts['occlusion']:.2f}",
    )
    outline(axes[2], lungs, overlays["occlusion"].shape)

    identity = (
        f"{Path(args.film).stem}  ·  Montgomery  ·  {row['split']} split  ·  "
        f"{'confirmed TB' if row['label'] == '1' else 'normal'}  ·  "
        f"model score {score:.4f} ({band})"
    )
    reading = (
        "White line is the hand-drawn lung boundary. Lift is the share of the "
        "highlighted area falling inside it, divided by the share of the frame "
        "the lungs occupy: 1.00 is what scattering the same highlight at random "
        "would give."
    )
    if comparison:
        across = (
            f"Across all {comparison['images']} Montgomery TB films, mean lift is "
            f"{comparison['baseline_lift_mean']:.2f} for Grad-CAM and "
            f"{comparison['candidate_lift_mean']:.2f} for occlusion. Paired "
            f"difference +{comparison['mean_difference']:.2f} "
            f"[{comparison['difference_ci_95'][0]:.2f}, "
            f"{comparison['difference_ci_95'][1]:.2f}], occlusion higher on "
            f"{comparison['candidate_higher_on']} of {comparison['images']}."
        )
        if held_out:
            across += (
                f" On the {held_out['images']} held-out films alone the interval is "
                f"[{held_out['difference_ci_95'][0]:.2f}, "
                f"{held_out['difference_ci_95'][1]:.2f}] and includes zero."
            )
    else:
        across = "No dataset comparison artefact found; run compare_explanations.py."

    # The footer carries the whole defence of the figure, so it is given real
    # room rather than squeezed under the panels. Wrapped here at a fixed width
    # instead of by matplotlib, which breaks only at the figure edge and leaves
    # a line holding two words.
    figure.tight_layout(rect=(0.014, 0.225, 0.986, 0.985))
    figure.add_artist(plt.Line2D([0.014, 0.986], [0.205, 0.205], color=RULE, linewidth=0.8))
    figure.text(0.014, 0.172, identity, fontsize=9.5, color=INK, va="top")
    figure.text(
        0.986,
        0.172,
        f"model {MODEL_VERSION}",
        fontsize=8.6,
        color=MUTED,
        ha="right",
        va="top",
    )
    figure.text(
        0.014, 0.122, wrap(reading), fontsize=8.6, color=MUTED, va="top", linespacing=1.5
    )
    figure.text(
        0.014, 0.062, wrap(across), fontsize=8.6, color=MUTED, va="top", linespacing=1.5
    )

    destination = Path(args.out)
    figure.savefig(destination, dpi=150, facecolor=PAPER)
    plt.close(figure)

    print()
    print(f"  Grad-CAM lift on this film   {lifts['gradcam']:.2f}")
    print(f"  occlusion lift on this film  {lifts['occlusion']:.2f}")
    if comparison:
        print(
            f"  dataset means                {comparison['baseline_lift_mean']:.2f} "
            f"and {comparison['candidate_lift_mean']:.2f} over "
            f"{comparison['images']} films"
        )
    print(f"\n-> {destination}")


if __name__ == "__main__":
    main()
