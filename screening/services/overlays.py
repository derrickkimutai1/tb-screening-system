"""
Drawing a heatmap over a radiograph.

Every explanation method in this package produces the same thing: a small
two-dimensional map, normalised so its peak is 1. What happens afterwards -
re-reading the original, bounding its size, colouring the map, blending the
two and writing the file - does not depend on how the map was computed. It
lives here so that adding a method does not mean copying it again.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

OVERLAY_STRENGTH = 0.4
COLOUR_MAP = cv2.COLORMAP_JET

# The source radiographs reach 4892 pixels, but the map behind the overlay is
# at most a few dozen cells across. Writing the overlay at full size would
# produce a file of several megabytes carrying no extra information, and would
# slow the result page. The original upload is kept untouched at its own
# resolution.
MAX_OVERLAY_EDGE = 1024


class ExplanationUnavailable(RuntimeError):
    """Raised when a heatmap cannot be produced for an image."""


@dataclass(frozen=True)
class Explanation:
    path: Path
    coverage: float  # share of the image above half the peak activation


def render(source, heat, destination):
    """Blend a normalised heatmap over the original radiograph and write it."""
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

    # Bilinear, so a coarse map does not reach the radiograph as visible
    # squares. The underlying resolution is unchanged by the interpolation.
    enlarged = cv2.resize(
        heat, (original.shape[1], original.shape[0]), interpolation=cv2.INTER_LINEAR
    )
    coloured = cv2.applyColorMap(np.uint8(255 * enlarged), COLOUR_MAP)
    background = cv2.cvtColor(original, cv2.COLOR_GRAY2BGR)
    blended = cv2.addWeighted(coloured, OVERLAY_STRENGTH, background, 1 - OVERLAY_STRENGTH, 0)

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(destination), blended):
        raise ExplanationUnavailable(f"The overlay could not be written to {destination}")

    return Explanation(
        path=destination,
        coverage=round(float(np.mean(enlarged >= 0.5)), 4),
    )
