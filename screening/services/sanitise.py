"""
Strip metadata from an upload before it is stored.

A photographed or exported radiograph can carry EXIF metadata: the camera, the
date, and on a phone the GPS coordinates of where the picture was taken. None of
it is needed to screen the image, and a clinical system holding the location a
patient was photographed at is holding more than it was given permission for.
The course guidance asks for unnecessary location and EXIF metadata to be
removed, so it is removed here rather than being carried into storage.

Orientation is the one tag that matters, because a JPEG can be stored rotated
with a tag saying which way up it belongs. That rotation is applied to the
pixels first, so stripping the tag cannot turn an upright chest film sideways.

The image is re-encoded rather than edited, which also means a file that only
looks like an image does not survive: whatever is written out is what Pillow
could decode, not the bytes that arrived.

Re-encoding is the most expensive thing an upload does, because a radiograph
is around twenty megapixels, so how it is done decides whether the system
meets its response-time requirement. See the notes beside the two lines that
matter.
"""

import io
from pathlib import Path

from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image, ImageOps

# Re-encoding a JPEG loses a little information. 95 is high enough that the
# loss is far below the detail the model reads at 224 by 224, and keeps the
# stored file a reasonable size.
JPEG_QUALITY = 95


def strip_metadata(uploaded):
    """Return the upload re-encoded without metadata, orientation applied.

    Returns the original unchanged if it cannot be decoded. The form has
    already established that it is an image, and the quality checker will
    reject what this cannot read, so failing here would replace a specific
    message to the user with a generic error.
    """
    try:
        uploaded.seek(0)
        with Image.open(uploaded) as image:
            # Applies the orientation tag to the pixels, then discards it.
            upright = ImageOps.exif_transpose(image)
            fmt = (image.format or "PNG").upper()

            # A new image with nothing in its info dictionary, so no metadata
            # can survive into the copy. paste moves the pixels inside Pillow;
            # the earlier putdata(list(getdata())) built a Python list of every
            # pixel first, which on a 4892 by 4020 radiograph means nineteen
            # million objects and most of a second on its own.
            clean = Image.new(upright.mode, upright.size)
            clean.paste(upright)

            buffer = io.BytesIO()
            if fmt in {"JPEG", "JPG"}:
                clean.save(buffer, format="JPEG", quality=JPEG_QUALITY)
            else:
                # Default compression rather than optimize=True. Optimising a
                # radiograph of this size took nine seconds and saved seven per
                # cent of the file, which is the wrong way round: NFR-01 gives
                # the whole screening ten seconds, and this one step spent them
                # all. PNG is lossless at every level, so nothing is given up
                # but disc space.
                clean.save(buffer, format="PNG")
    except (OSError, ValueError):
        uploaded.seek(0)
        return uploaded

    buffer.seek(0)
    return InMemoryUploadedFile(
        buffer,
        field_name=getattr(uploaded, "field_name", "xray_image"),
        name=Path(uploaded.name).name,
        content_type="image/jpeg" if fmt in {"JPEG", "JPG"} else "image/png",
        size=buffer.getbuffer().nbytes,
        charset=None,
    )
