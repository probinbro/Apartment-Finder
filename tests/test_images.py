import io

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from PIL import Image

from core.images import process_image, validate_image_file

from .helpers import image_bytes, image_upload


class ImageValidationTests(SimpleTestCase):
    def test_accepts_jpeg_png_and_webp(self):
        for fmt, name in [("JPEG", "a.jpg"), ("PNG", "a.png"), ("WEBP", "a.webp")]:
            with self.subTest(fmt=fmt):
                self.assertEqual(validate_image_file(image_upload(name, fmt)), fmt)

    def test_rejects_disallowed_extension(self):
        upload = SimpleUploadedFile("script.php", image_bytes(), content_type="image/jpeg")
        with self.assertRaises(ValidationError):
            validate_image_file(upload)

    def test_rejects_non_image_content_with_image_extension(self):
        upload = SimpleUploadedFile("evil.jpg", b"<?php system($_GET['c']); ?>", content_type="image/jpeg")
        with self.assertRaisesMessage(ValidationError, "not a valid image"):
            validate_image_file(upload)

    def test_rejects_unsupported_format_even_if_renamed(self):
        upload = SimpleUploadedFile("anim.png", image_bytes("GIF"), content_type="image/png")
        with self.assertRaises(ValidationError):
            validate_image_file(upload)

    @override_settings(IMAGE_MAX_UPLOAD_BYTES=100)
    def test_rejects_oversized_file(self):
        with self.assertRaisesMessage(ValidationError, "too large"):
            validate_image_file(image_upload(size=(400, 400)))


class ImageProcessingTests(SimpleTestCase):
    def test_reencodes_to_jpeg_with_random_name(self):
        processed, (width, height) = process_image(image_upload("house.png", "PNG", mode="RGBA", color=(0, 0, 0, 0)))
        self.assertTrue(processed.name.endswith(".jpg"))
        self.assertNotIn("house", processed.name)
        self.assertEqual(Image.open(processed).format, "JPEG")
        self.assertEqual((width, height), (64, 48))

    @override_settings(IMAGE_MAX_DIMENSION=100)
    def test_downscales_large_images(self):
        _, (width, height) = process_image(image_upload(size=(400, 200)))
        self.assertEqual((width, height), (100, 50))

    def test_strips_exif_metadata(self):
        source = Image.new("RGB", (32, 32))
        exif = Image.Exif()
        exif[0x010F] = "SecretCameraMaker"
        buffer = io.BytesIO()
        source.save(buffer, format="JPEG", exif=exif)
        upload = SimpleUploadedFile("gps.jpg", buffer.getvalue(), content_type="image/jpeg")

        processed, _ = process_image(upload)
        self.assertNotIn(b"SecretCameraMaker", processed.read())
