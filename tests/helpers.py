"""Shared factories and fakes for the test suite. Supabase is always mocked."""

import io
import time
import uuid
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apartments.models import Apartment, PropertyType
from core.supabase.client import AuthSession
from users.models import User


def make_user(email="user@example.com", role=User.Role.USER, **extra):
    return User.objects.create_user(email=email, auth_user_id=uuid.uuid4(), role=role, **extra)


def make_admin(email="admin@example.com", **extra):
    return make_user(email=email, role=User.Role.ADMIN, **extra)


def make_apartment(**overrides):
    data = {
        "title": "Test apartment",
        "description": "A lovely place.",
        "property_type": PropertyType.objects.get_or_create(slug="apartment", defaults={"name": "Apartment"})[0],
        "address": "1 Main Street",
        "city": "Austin",
        "area": "Downtown",
        "rent": Decimal("1500"),
        "bedrooms": 2,
        "bathrooms": 1,
        "size_sqft": 800,
        "contact_name": "Owner",
        "contact_email": "owner@example.com",
        "status": Apartment.Status.PUBLISHED,
    }
    data.update(overrides)
    return Apartment.objects.create(**data)


def image_bytes(fmt="JPEG", size=(64, 48), color=(200, 120, 80), mode="RGB"):
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def image_upload(name="photo.jpg", fmt="JPEG", **kwargs):
    content_type = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(fmt, "application/octet-stream")
    return SimpleUploadedFile(name, image_bytes(fmt, **kwargs), content_type=content_type)


def fake_session(user_id=None, email="user@example.com", expires_in=3600):
    return AuthSession(
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=int(time.time()) + expires_in,
        user_id=str(user_id or uuid.uuid4()),
        email=email,
    )


def mock_auth_client():
    """Patch the Supabase auth client used by views/middleware; returns the patcher."""
    return mock.patch("users.services.get_auth_client")


def apartment_form_data(**overrides):
    property_type = PropertyType.objects.get_or_create(slug="apartment", defaults={"name": "Apartment"})[0]
    data = {
        "title": "Bright flat",
        "description": "Sunny and quiet.",
        "property_type": property_type.pk,
        "status": Apartment.Status.PUBLISHED,
        "address": "10 Oak Street",
        "city": "denver",
        "area": "highlands",
        "rent": "1800",
        "bedrooms": "2",
        "bathrooms": "1",
        "size_sqft": "900",
        "furnishing": Apartment.Furnishing.FURNISHED,
        "availability": Apartment.Availability.AVAILABLE,
        "contact_name": "Jane Owner",
        "contact_phone": "+1 555 123 4567",
        "contact_email": "jane@example.com",
    }
    data.update(overrides)
    return data
