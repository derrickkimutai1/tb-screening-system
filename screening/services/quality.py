"""
Image quality checking, as required by proposal Objective 4.

A radiograph that is badly blurred or poorly exposed is harder for the model to
read, and the clinician should know that before trusting the result. This check
runs before prediction and usually produces a warning rather than a rejection:
a usable but poor image still gets a prediction, shown alongside a caution.
Three things are refused outright - a file that cannot be decoded at all, one
smaller than the model's own input, which could only be screened by enlarging
it first, and one with no range between its lightest and darkest point, which
carries nothing to read however sharp or bright the rest of the check finds
it.

The thresholds were measured rather than guessed. Blur and brightness were
computed across all 559 training radiographs, which are diagnostically usable
images, and the limits sit just below the 2.5th percentile of that distribution:

    blur (variance of Laplacian)   min 80.6, p2.5 103.5, median 182.4, max 787.0
    brightness (mean intensity)    min 39.3, p2.5  87.2, median 152.0, max 198.5

So an image is flagged only when it falls outside the range of images already
accepted as readable.
"""

from dataclasses import dataclass

import cv2
import numpy as np

# Measured from the training split. See the module docstring.
MINIMUM_SHARPNESS = 100.0
MINIMUM_BRIGHTNESS = 85.0
MAXIMUM_BRIGHTNESS = 200.0

# Measured at a fixed size so the figures do not depend on the source
# resolution, which varies from 1130 to 4892 pixels across the datasets.
ASSESSMENT_SIZE = (512, 512)

# An image with no range at all carries nothing to read.
#
# A uniform rectangle is not a degraded radiograph, it is not a radiograph.
# This was found when half the project's own dataset arrived as a black
# rectangle through a decoding fault: the checks below called it blurred and
# dark, the screening went ahead, and the model returned "Unlikely TB" on an
# image containing no information. A caution is the wrong answer to that; a
# refusal is the right one. A real chest film spans most of the scale, so this
# limit is far below anything diagnostic and will not refuse a flat-looking
# but genuine image.
MINIMUM_RANGE = 16

# The model's input size, and the smallest image worth screening.
#
# Anything smaller has to be enlarged to reach the network, which invents no
# detail: it stretches what little is there and produces a confident-looking
# score from an image a radiologist could not read either. A thumbnail or an
# icon dropped into the upload field is the realistic case, and it should be
# refused with a reason rather than screened.
MINIMUM_EDGE = 224


@dataclass(frozen=True)
class QualityReport:
    status: str  # ACCEPTABLE, DEGRADED or INVALID
    message: str
    blur_score: float | None
    brightness_mean: float | None

    @property
    def is_usable(self):
        return self.status != "INVALID"


class ImageQualityChecker:
    """Assesses whether a radiograph is readable enough to trust the result."""

    def check(self, source):
        """Assess one image from a path.

        Returns a report; it never raises for a bad image, because an unusable
        upload is an expected outcome rather than an error.
        """
        image = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
        if image is None or image.size == 0:
            return QualityReport(
                status="INVALID",
                message="This file could not be read as an image. Upload a PNG or JPEG.",
                blur_score=None,
                brightness_mean=None,
            )

        height, width = image.shape[:2]
        if min(height, width) < MINIMUM_EDGE:
            return QualityReport(
                status="INVALID",
                message=(
                    f"This image is {width} by {height} pixels. A radiograph must "
                    f"be at least {MINIMUM_EDGE} by {MINIMUM_EDGE} so it does not "
                    "have to be enlarged before screening."
                ),
                blur_score=None,
                brightness_mean=None,
            )

        spread = int(image.max()) - int(image.min())
        if spread < MINIMUM_RANGE:
            return QualityReport(
                status="INVALID",
                message=(
                    "This image is blank or very nearly so, with almost no "
                    "difference between its lightest and darkest point. It "
                    "carries nothing to screen. Check that it exported "
                    "correctly and upload it again."
                ),
                blur_score=None,
                brightness_mean=round(float(np.mean(image)), 2),
            )

        resized = cv2.resize(image, ASSESSMENT_SIZE, interpolation=cv2.INTER_AREA)
        sharpness = float(cv2.Laplacian(resized, cv2.CV_64F).var())
        brightness = float(np.mean(resized))

        concerns = []
        if sharpness < MINIMUM_SHARPNESS:
            concerns.append("appears blurred or low in detail")
        if brightness < MINIMUM_BRIGHTNESS:
            concerns.append("is darker than expected")
        elif brightness > MAXIMUM_BRIGHTNESS:
            concerns.append("is brighter than expected")

        if concerns:
            return QualityReport(
                status="DEGRADED",
                message=(
                    f"The image {' and '.join(concerns)}. The result may be less "
                    "reliable than usual and should be read with that in mind."
                ),
                blur_score=round(sharpness, 2),
                brightness_mean=round(brightness, 2),
            )

        return QualityReport(
            status="ACCEPTABLE",
            message="",
            blur_score=round(sharpness, 2),
            brightness_mean=round(brightness, 2),
        )
