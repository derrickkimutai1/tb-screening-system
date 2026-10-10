"""
Grad-CAM explanation.

Gradient-weighted Class Activation Mapping shows which regions of an image most
influenced the model's output. It takes the gradient of the score with respect
to the activations of the last convolutional layer, averages those gradients
over each feature map to get an importance weight, and sums the maps by weight.
The result is a coarse map, 7 by 7 for MobileNetV2, which is then enlarged and
laid over the original radiograph.

The map shows where the model looked. It is not a claim that disease is present
at those locations, and the result page says so.

The network is split at `out_relu`, MobileNetV2's final convolutional layer.
This is possible because training built the classifier head as its own model
rather than as loose layers, so the two halves can be recombined around the
point where the gradients are needed.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

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

    _split = None

    @classmethod
    def _split_model(cls, model):
        """Split the network at the last convolutional layer.

        Cached, because rebuilding the two halves on every request is wasteful
        and they never change for a given loaded model.
        """
        if cls._split is not None:
            return cls._split

        import keras

        base = next(
            (layer for layer in model.layers if "mobilenet" in layer.name.lower()), None
        )
        head = next(
            (layer for layer in model.layers if layer.name == "classification_head"), None
        )
        if base is None or head is None:
            raise ExplanationUnavailable(
                "The model does not have the expected base and head layers."
            )

        features = keras.Model(base.input, base.get_layer(LAST_CONV_LAYER).output)
        cls._split = (features, head)
        return cls._split

    def heatmap(self, model, prepared_image):
        """Compute the raw Grad-CAM map for one prepared image."""
        import tensorflow as tf

        features, head = self._split_model(model)
        batch = prepared_image[np.newaxis, ...]

        with tf.GradientTape() as tape:
            maps = features(batch, training=False)
            tape.watch(maps)
            score = head(maps, training=False)[:, 0]

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
        enlarged = cv2.resize(cam, (original.shape[1], original.shape[0]))
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
