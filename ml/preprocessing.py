"""
Image preparation shared by model training and the web application.

This module is imported by both the training scripts and the Django prediction
service. Keeping one implementation is deliberate: if training and inference
prepared images differently the model would still return confident-looking
scores, but they would be meaningless, and nothing would raise an error. There
is therefore exactly one definition of what "prepared" means, and it lives here.

The module depends only on Pillow and NumPy. It does not import TensorFlow or
Django, so it can be imported cheaply and tested on its own.

Decisions encoded here, and why:

Colour mode
    The source images are not uniformly encoded. Montgomery is 8-bit greyscale,
    while Shenzhen mixes palette and RGB. Every image is therefore converted to
    single-channel intensity first, which normalises all three cases, and only
    then repeated across three channels for MobileNetV2, which expects three.
    Converting palette images straight to RGB would pass their palette through
    instead of their intensity.

Size
    Images are resized directly to 224 x 224, as stated in proposal section
    3.2.2. Source dimensions vary from 1130 x 948 up to 4892 x 4892 and aspect
    ratios differ, so this does distort the image slightly. Padding to a square
    first was rejected because the resulting borders are a constant artefact
    that a convolutional network can learn from.

Scaling
    Pixel values are mapped from 0-255 to the range -1 to 1. This matches the
    preprocessing MobileNetV2's ImageNet weights were trained with, so the
    pretrained features behave as intended. It is implemented directly rather
    than imported from Keras so that this module stays free of TensorFlow; the
    test suite asserts the two produce identical output.
"""

from pathlib import Path

import numpy as np
from PIL import Image

# Raise Pillow's guard against decompression-bomb images. The Montgomery
# radiographs are legitimately large, up to 4892 x 4892.
Image.MAX_IMAGE_PIXELS = None

INPUT_SIZE = (224, 224)
INPUT_CHANNELS = 3
SCALING = "mobilenet_v2"
RESAMPLING = Image.Resampling.BILINEAR

# Recorded alongside the model so the application can confirm at load time that
# it prepares images the same way the model was trained with.
PREPROCESSING_VERSION = "1"


def load_intensity(source):
    """Open an image and return it as single-channel intensity.

    Accepts a path or an open file object, so the training scripts can pass
    filenames and Django can pass an uploaded file directly.
    """
    with Image.open(source) as image:
        return image.convert("L")


def resize(image):
    """Resize to the model's input size."""
    return image.resize(INPUT_SIZE, RESAMPLING)


def to_array(image):
    """Repeat intensity across three channels and scale to the range -1 to 1."""
    intensity = np.asarray(image, dtype=np.float32)
    stacked = np.repeat(intensity[..., np.newaxis], INPUT_CHANNELS, axis=-1)
    return stacked / 127.5 - 1.0


def prepare(source):
    """Full preparation for one image, from a path or file object.

    Returns a float32 array of shape (224, 224, 3) scaled to -1 to 1.
    """
    return to_array(resize(load_intensity(source)))


def prepare_batch(sources):
    """Prepare several images into one batch of shape (n, 224, 224, 3)."""
    return np.stack([prepare(source) for source in sources])


def as_model_input(source):
    """Prepare one image as a batch of one, ready to pass to the model."""
    return prepare(source)[np.newaxis, ...]


def describe():
    """The preprocessing settings, for recording beside a trained model."""
    return {
        "preprocessing_version": PREPROCESSING_VERSION,
        "input_size": list(INPUT_SIZE),
        "channels": INPUT_CHANNELS,
        "colour_mode": "intensity repeated to three channels",
        "scaling": SCALING,
        "scaling_range": [-1.0, 1.0],
        "resampling": "bilinear",
    }


def label_from_filename(path):
    """Read the class from a dataset filename.

    Both reference datasets encode the label in the last character of the stem:
    `MCUCXR_0001_0.png` is normal and `CHNCXR_0002_1.png` is TB-positive.
    Returns 1 for TB and 0 for normal, matching the model's positive class.
    """
    stem = Path(path).stem
    suffix = stem.rsplit("_", 1)[-1]
    if suffix not in {"0", "1"}:
        raise ValueError(f"No class suffix in filename: {path}")
    return int(suffix)
