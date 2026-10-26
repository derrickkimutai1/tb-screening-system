"""
Score-CAM explanation.

Grad-CAM weights each feature map by the average gradient flowing into it.
Gradients at an internal layer are noisy and can saturate, which is one reason
its maps on this model land no better than chance against the lung masks.
Score-CAM throws the gradients away. It takes each feature map, enlarges it to
the size of the input, uses it as a mask over the radiograph, and asks the
model what it scores with only that region visible. The map's weight is the
score it earns.

That makes it causal, like occlusion, but the regions it tests are shaped by
features the network actually learned rather than by a square sliding across
the image. A lesion-shaped activation is tested as a lesion-shaped mask, where
occlusion can only ever cover a box.

The cost is one forward pass per feature map tested. `block_13_expand_relu`
has 576 of them, which would be far too slow, so only the strongest are
tried: a feature map that barely activates on this image cannot carry much of
its score, and testing it spends a forward pass to learn nothing. CHANNELS is
the number kept, and it is the setting that trades accuracy against time.

This is not what the application ships
--------------------------------------
Measured against the Montgomery lung masks on the 58 TB images, this scores a
lift of 0.26, well below chance and well below both Grad-CAM at 1.16 and
occlusion at 1.47. The maps land on the image borders rather than on the lungs.
It is kept so the comparison that settled the choice can be rerun rather than
taken on trust:

    python ml/scripts/evaluate_explanations.py --split all --method scorecam

Nothing in the application imports this module. See `ml/artifacts/
scorecam_evaluation.json` for the recorded figures and `explanation_methods.md`
for the comparison.
"""

from pathlib import Path

import numpy as np

from .gradcam import (
    EXPLANATION_LAYER,
    ExplanationUnavailable,
    GradCAMGenerator,
)
from .overlays import render

# How many feature maps are scored. 32 of 576 keeps the map within a second or
# two on a CPU. The maps are chosen by peak activation on this image, so the
# ones left out are those with little presence in it to begin with.
CHANNELS = 32

# Feature maps flatter than this carry no usable region: enlarged and
# normalised they would become an even wash over the whole radiograph, which
# masks nothing and only adds its score to every pixel equally.
MIN_RANGE = 1e-6


class ScoreCAMGenerator:
    """Produces a heatmap by masking with feature maps and re-scoring."""

    channels = CHANNELS

    def heatmap(self, model, prepared_image, layer_name=None):
        """Compute the Score-CAM map for one prepared image."""
        probe, head, _ = GradCAMGenerator._probe_model(model, layer_name or EXPLANATION_LAYER)

        batch = prepared_image[np.newaxis, ...]
        maps = np.asarray(probe(batch, training=False)[0])[0]
        height, width, count = maps.shape

        # The strongest feature maps on this image, which are the only ones
        # worth spending a forward pass on.
        order = np.argsort(maps.reshape(-1, count).max(axis=0))[::-1]
        chosen = [index for index in order[: self.channels]]

        import cv2

        masked = []
        kept = []
        for index in chosen:
            plane = maps[:, :, index]
            low, high = float(plane.min()), float(plane.max())
            if high - low < MIN_RANGE:
                continue
            mask = cv2.resize(
                (plane - low) / (high - low),
                (prepared_image.shape[1], prepared_image.shape[0]),
                interpolation=cv2.INTER_LINEAR,
            )
            # The input is scaled to -1..1, so multiplying by the mask fades
            # the hidden parts towards mid-grey rather than towards black.
            masked.append(prepared_image * mask[..., np.newaxis])
            kept.append(index)

        if not masked:
            raise ExplanationUnavailable("No feature map carried a usable region.")

        scores = model.predict(np.stack(masked), verbose=0)[:, 0]

        # The score each mask earns is the weight, used directly.
        #
        # The published method softmaxes these first, which assumes a
        # multi-class network whose logits span a wide range. This model ends
        # in a single sigmoid, so the scores already sit inside 0..1 and a
        # softmax over them comes out almost uniform: every weight lands near
        # 1/n, the sum becomes an unweighted average of the strongest feature
        # maps, and the result is dominated by whichever maps are broadest
        # rather than by whichever regions carry the score. Measured, that
        # version scored a lift of 0.04 against the lung masks, far below
        # chance, which is what a map of the image borders looks like.
        weights = np.clip(scores - scores.min(), 0, None)
        if weights.sum() <= 0:
            raise ExplanationUnavailable("No mask changed the score for this image.")

        # Each map is normalised before it is weighted, so a feature map with
        # large raw values cannot outvote a more relevant one purely on scale.
        combined = np.zeros((height, width), dtype=np.float32)
        for weight, index in zip(weights, kept, strict=True):
            plane = maps[:, :, index]
            low, high = float(plane.min()), float(plane.max())
            combined += weight * (plane - low) / (high - low)

        combined = np.maximum(combined, 0)
        peak = combined.max()
        if peak <= 0:
            raise ExplanationUnavailable("No region supported the score for this image.")
        return (combined / peak).astype(np.float32)

    def overlay(self, source, model, prepared_image, destination):
        """Write a Score-CAM map overlaid on the original radiograph."""
        return render(Path(source), self.heatmap(model, prepared_image), Path(destination))
