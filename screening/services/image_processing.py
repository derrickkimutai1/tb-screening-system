"""
Image preparation for the web application.

This is a thin wrapper over `ml/preprocessing.py`, the module the training
scripts use. It exists so the application has a class matching the design in
proposal section 3.5.4, while the actual preparation stays in one place shared
with training. If this file did the work itself, the two could drift apart and
every prediction would be quietly wrong.
"""

import sys

from django.conf import settings

sys.path.insert(0, str(settings.ML_DIR))

import preprocessing  # noqa: E402


class ImageProcessor:
    """Prepares an uploaded radiograph for the model."""

    input_size = preprocessing.INPUT_SIZE

    def prepare(self, source):
        """Return one prepared image, shaped (224, 224, 3)."""
        return preprocessing.prepare(source)

    def as_model_input(self, source):
        """Return the image as a batch of one, ready for the model."""
        return preprocessing.as_model_input(source)

    def describe(self):
        """The preprocessing settings, for recording against a prediction."""
        return preprocessing.describe()
