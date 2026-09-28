"""
Image validation and normalisation with Pillow.

Every uploaded image is:
  1. size-checked before decoding,
  2. verified to be a real JPEG/PNG/WEBP (by content, not by extension),
  3. re-encoded as an optimised JPEG — which also strips EXIF/GPS metadata and
     any payload appended to the original file.
"""

import io
import logging
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

# Refuse "decompression bomb" images outright instead of just warning.
Image.MAX_IMAGE_PIXELS = 40_000_000

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
OUTPUT_FORMAT = "JPEG"
OUTPUT_EXTENSION = ".jpg"
OUTPUT_CONTENT_TYPE = "image/jpeg"


def validate_image_file(upload):
    """Raise ValidationError unless `upload` is an acceptable image. Returns the detected format."""
    max_bytes = settings.IMAGE_MAX_UPLOAD_BYTES
    if upload.size > max_bytes:
        raise ValidationError(
            f"“{upload.name}” is too large. Maximum size is {max_bytes // (1024 * 1024)} MB.", code="file_too_large"
        )

    extension = ("." + upload.name.rsplit(".", 1)[-1].lower()) if "." in upload.name else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError(f"“{upload.name}” is not a supported image type. Use JPG, PNG or WEBP.", code="bad_extension")

    try:
        upload.seek(0)
        with Image.open(upload) as probe:
            image_format = probe.format
            probe.verify()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise ValidationError(f"“{upload.name}” is not a valid image file.", code="invalid_image")
    finally:
        upload.seek(0)

    if image_format not in settings.IMAGE_ALLOWED_FORMATS:
        raise ValidationError(f"“{upload.name}” is not a supported image format. Use JPG, PNG or WEBP.", code="bad_format")
    return image_format


def process_image(upload, *, max_dimension=None, quality=85):
    """
    Validate and re-encode an uploaded image.

    Returns an InMemoryUploadedFile (JPEG) with a random name, ready to assign
    to an ImageField, plus the final (width, height).
    """
    validate_image_file(upload)
    max_dimension = max_dimension or settings.IMAGE_MAX_DIMENSION

    upload.seek(0)
    with Image.open(upload) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.getchannel("A"))
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        image.save(buffer, format=OUTPUT_FORMAT, quality=quality, optimize=True, progressive=True)
        width, height = image.size

    size = buffer.tell()
    buffer.seek(0)
    processed = InMemoryUploadedFile(
        file=buffer,
        field_name=None,
        name=f"{uuid.uuid4().hex}{OUTPUT_EXTENSION}",
        content_type=OUTPUT_CONTENT_TYPE,
        size=size,
        charset=None,
    )
    return processed, (width, height)


def delete_file_quietly(storage, name):
    """Delete a stored file; log instead of failing if the storage backend errors."""
    if not name:
        return
    try:
        storage.delete(name)
    except Exception:  # noqa: BLE001 — orphaned files must never break a user action
        logger.exception("Failed to delete stored file %s", name)
