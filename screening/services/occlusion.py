"""
Occlusion explanation.

Grad-CAM answers "which activations correlated with the score", and on this
model its answer does not land on the lungs: measured against Montgomery's
hand-drawn lung masks the activation is spread as though placed at random, a
lift of 0.9963 over all 138 images and 1.11 over the TB cases among them.
Occlusion asks a different and blunter question.
It covers one patch of the radiograph at a time, runs the model again, and
records how far the score falls. A region whose removal costs the model its
confidence was carrying that confidence.

The difference matters. Grad-CAM is correlational and reads an internal layer
through a gradient; occlusion is causal and reads the model's own output. The
occlusion experiment in `ml/scripts/evaluate_shortcuts.py` already showed the
model's signal lives in the lungs - lungs only 0.7884 AUC against surroundings
only 0.5453 - so the method has already been shown to find what Grad-CAM
misses on this model.

The cost is that it is not free. One map is 169 forward passes instead of one
backward pass, which is why the patches are evaluated as a single batch, and
why the map is built the first time somebody opens a case rather than during
the upload: a batch of twenty would otherwise spend minutes producing maps for
images nobody looks at.

What the map is not
-------------------
It shows where the model's score came from, not where disease is. A region can
matter to the model and hold no pathology, which is exactly the failure the
shortcut investigation was looking for. The result page and the printed report
both say so.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .overlays import ExplanationUnavailable, render

# The occluding patch, in pixels of the 224 by 224 model input.
#
# Patch size sets how much is hidden at once; stride sets how finely the
# window moves. Both were chosen on the 49 Montgomery TB images in the train
# and validation splits, never on the test split, so the figure this method
# is finally reported at was not the figure it was tuned against.
#
#     Grad-CAM                      lift 1.11    median 0.84
#     patch 32, stride 8            lift 1.51    median 1.17    625 passes
#     patch 32, stride 16           lift 1.63    median 1.44    169 passes
#     patch 32, stride 24           lift 1.97    median 1.77     81 passes
#
# A 48 pixel patch was tried first and scored 1.12, barely above Grad-CAM: it
# covers about a fifth of the image, so hiding it moves the score without
# saying which part of that fifth mattered. 32 is small enough to separate one
# zone from another.
#
# Why stride 16 and not 24, when 24 scores higher
# -----------------------------------------------
# Because the metric rewards coarseness and the score is partly an artefact of
# it. Lift asks what share of the hot pixels fall inside the lungs. A map with
# few large cells marks the middle of the chest, which overlaps the lungs well
# and scores highly while telling a clinician nothing about where to look; in
# the limit a single hot cell covering everything still scores 1.0 rather than
# 0. A 7 by 7 map being too coarse to hold a lesion is exactly why Grad-CAM
# was moved off out_relu in the first place, and stride 24 gives a 9 by 9.
#
# So the setting is the finest one that clearly beats Grad-CAM rather than the
# one with the best number: a 13 by 13 map, 169 forward passes, lift 1.63
# against 1.11, and a median of 1.44 against 0.84.
#
# Change these and the recorded lift no longer describes what ships. Rerun
# `evaluate_explanations.py --method occlusion --patch N --stride M` if you do.
PATCH = 32
STRIDE = 16

# What goes in a record's explanation_method, so a stored image can always be
# traced to the method and settings that produced it.
METHOD_NAME = f"occlusion-p{PATCH}s{STRIDE}"

# Mid-grey in the model's input range, which preprocessing scales to -1..1. The
# patch has to be neutral: filling it with black or white would itself be a
# strong signal and the map would measure the fill rather than the region.
NEUTRAL = 0.0


class OcclusionGenerator:
    """Produces a heatmap by hiding parts of the image and re-scoring it."""

    patch = PATCH
    stride = STRIDE

    def _positions(self, size):
        """Top-left offsets of every patch, covering the full width.

        The last position is pinned to the edge rather than dropped, so the
        right and bottom margins are measured too. Without that a lesion in
        the lower zones could sit in a band the map never covers.
        """
        offsets = list(range(0, size - self.patch + 1, self.stride))
        if offsets[-1] != size - self.patch:
            offsets.append(size - self.patch)
        return offsets

    def heatmap(self, model, prepared_image, layer_name=None):  # noqa: ARG002
        """Compute the occlusion map for one prepared image.

        `layer_name` is accepted and ignored. It exists so this generator can
        stand in for GradCAMGenerator wherever one is passed, including in the
        evaluation script, which measures both through the same code path.
        """
        height, width = prepared_image.shape[:2]
        if min(height, width) < self.patch:
            raise ExplanationUnavailable("The image is smaller than the occluding patch.")

        rows = self._positions(height)
        columns = self._positions(width)

        # Every occluded copy in one array, scored in a single call. One call
        # per patch would spend most of its time in per-call overhead rather
        # than in the model.
        batch = np.repeat(prepared_image[np.newaxis, ...], len(rows) * len(columns), axis=0)
        for index, (top, left) in enumerate((top, left) for top in rows for left in columns):
            batch[index, top : top + self.patch, left : left + self.patch, :] = NEUTRAL

        baseline = float(model.predict(prepared_image[np.newaxis, ...], verbose=0)[0, 0])
        scores = model.predict(batch, verbose=0)[:, 0]

        # How much hiding each patch cost the score. Negative values are
        # regions whose removal made the model more confident, which is not
        # what the explanation is about, so they are clipped away.
        drop = np.clip(baseline - scores, 0, None).reshape(len(rows), len(columns))

        peak = drop.max()
        if peak <= 0:
            raise ExplanationUnavailable("No region supported the score for this image.")
        return (drop / peak).astype(np.float32)

    def overlay(self, source, model, prepared_image, destination):
        """Write an occlusion map overlaid on the original radiograph."""
        return render(Path(source), self.heatmap(model, prepared_image), Path(destination))


@dataclass(frozen=True)
class OcclusionSettings:
    """What the shipped map was produced at, for recording beside a result."""

    patch: int = PATCH
    stride: int = STRIDE
