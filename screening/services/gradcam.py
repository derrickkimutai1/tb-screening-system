"""
Grad-CAM explanation.

Gradient-weighted Class Activation Mapping shows which regions of an image most
influenced the model's output. It takes the gradient of the score with respect
to the activations of the last convolutional layer, averages those gradients
over each feature map to get an importance weight, and sums the maps by weight.
The result is a coarse map which is then enlarged and laid over the original
radiograph.

The map shows where the model looked. It is not a claim that disease is present
at those locations, and the result page says so.

Which layer the map comes from
------------------------------
The usual choice is the final convolutional layer, `out_relu`, but in
MobileNetV2 that layer is only 7 by 7. Stretched over a radiograph of a few
thousand pixels, one cell covers a region far larger than a lesion, and
measurement against Montgomery's manual lung masks bore that out: lift over
chance was 1.11, barely better than a random map.

`block_13_expand_relu` is the deepest layer still at 14 by 14, immediately
before the final downsample. It gives four times the spatial resolution at the
cost of slightly less abstract features. `evaluate_explanations.py` measures
both, so the choice is settled by the lung-mask lift rather than by argument.

Gradients are taken through a probe model that returns the chosen activation
and the prediction from one forward pass. Taking them through two separately
built halves would only work at the final layer, because MobileNetV2's residual
connections cannot be cut at an arbitrary depth and reassembled.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

# The layer the heatmap is read from, and the fallback if a model does not have
# it. EXPLANATION_LAYER must be a convolutional activation inside the base.
EXPLANATION_LAYER = "block_13_expand_relu"
LAST_CONV_LAYER = "out_relu"
OVERLAY_STRENGTH = 0.4
COLOUR_MAP = cv2.COLORMAP_JET

# The source radiographs reach 4892 pixels, but the activation map behind the
# overlay is only 7 by 7. Writing the overlay at full size would produce a file
# of several megabytes carrying no extra information, and would slow the result
# page. The original upload is kept untouched at its own resolution.
MAX_OVERLAY_EDGE = 1024


class ExplanationUnavailable(RuntimeError):
    """Raised when a heatmap cannot be produced for an image."""


@dataclass(frozen=True)
class Explanation:
    path: Path
    coverage: float  # share of the image above half the peak activation


class GradCAMGenerator:
    """Produces a heatmap overlay showing what influenced a prediction."""

    _probe = None
    _layer_used = None

    @classmethod
    def _probe_model(cls, model, layer_name=None):
        """Build a model returning the chosen activation and the final features.

        Cached, because rebuilding it on every request is wasteful and it never
        changes for a given loaded model. Both outputs come from one forward
        pass, which is what lets the tape connect the score back to an
        activation partway down the network.
        """
        wanted = layer_name or EXPLANATION_LAYER
        if cls._probe is not None and cls._layer_used == wanted:
            return (*cls._probe, cls._layer_used)

        import keras

        head = next(
            (layer for layer in model.layers if layer.name == "classification_head"), None
        )
        if head is None:
            raise ExplanationUnavailable("The model has no classification head.")

        # Find the pretrained base by looking for the layer that actually
        # contains the activation we want. Picking the first nested model
        # instead would find the augmentation pipeline, which is a Sequential
        # and therefore also a Model.
        base = chosen = None
        for candidate in model.layers:
            if not isinstance(candidate, keras.Model) or candidate is head:
                continue
            names = {layer.name for layer in candidate.layers}
            for option in (wanted, LAST_CONV_LAYER):
                if option in names:
                    base, chosen = candidate, option
                    break
            if base is not None:
                break

        if base is None:
            raise ExplanationUnavailable(
                f"No layer of the model contains '{wanted}' or '{LAST_CONV_LAYER}'."
            )

        probe = keras.Model(
            base.input, [base.get_layer(chosen).output, base.output], name="gradcam_probe"
        )
        cls._probe = (probe, head)
        cls._layer_used = chosen
        return probe, head, chosen

    @classmethod
    def layer_used(cls):
        """The base layer the last heatmap was read from, or None."""
        return cls._layer_used

    def heatmap(self, model, prepared_image, layer_name=None):
        """Compute the raw Grad-CAM map for one prepared image."""
        import tensorflow as tf

        probe, head, _ = self._probe_model(model, layer_name)
        batch = prepared_image[np.newaxis, ...]

        with tf.GradientTape() as tape:
            maps, pooled = probe(batch, training=False)
            tape.watch(maps)
            score = head(pooled, training=False)[:, 0]

        gradients = tape.gradient(score, maps)
        if gradients is None:
            raise ExplanationUnavailable("No gradients were produced for this image.")

        weights = tf.reduce_mean(gradients, axis=(1, 2))
        weighted = tf.einsum("bhwc,bc->bhw", maps, weights)
        # Only positive contributions matter: these are the regions pushing the
        # score up, which is what the explanation is about.
        cam = tf.nn.relu(weighted)[0].numpy()

        peak = cam.max()
        if peak <= 0:
            raise ExplanationUnavailable("No region influenced the score positively.")
        return cam / peak

    def overlay(self, source, model, prepared_image, destination):
        """Write a heatmap overlaid on the original radiograph."""
        original = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
        if original is None:
            raise ExplanationUnavailable("The original image could not be re-read.")

        height, width = original.shape
        scale = min(1.0, MAX_OVERLAY_EDGE / max(height, width))
        if scale < 1.0:
            original = cv2.resize(
                original,
                (int(width * scale), int(height * scale)),
                interpolation=cv2.INTER_AREA,
            )

        cam = self.heatmap(model, prepared_image)
        # Bilinear, so a 14 by 14 map does not reach the radiograph as visible
        # squares. The underlying resolution is unchanged by the interpolation.
        enlarged = cv2.resize(
            cam, (original.shape[1], original.shape[0]), interpolation=cv2.INTER_LINEAR
        )
        coloured = cv2.applyColorMap(np.uint8(255 * enlarged), COLOUR_MAP)
        background = cv2.cvtColor(original, cv2.COLOR_GRAY2BGR)
        blended = cv2.addWeighted(
            coloured, OVERLAY_STRENGTH, background, 1 - OVERLAY_STRENGTH, 0
        )

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(destination), blended):
            raise ExplanationUnavailable(f"The overlay could not be written to {destination}")

        return Explanation(
            path=destination,
            coverage=round(float(np.mean(enlarged >= 0.5)), 4),
        )
