"""
Apartment listing data model.

Lookup-style values that admins may want to extend (property types, amenities)
are tables rather than hard-coded choices. Attributes that don't warrant a
column yet (floor number, parking spaces, pet policy, ...) can be stored in
`Apartment.extra_attributes` until they are promoted to real fields.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Prefetch, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class PropertyType(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "property_types"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = self.slug or slugify(self.name)
        super().save(*args, **kwargs)


class Amenity(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)
    icon = models.CharField(max_length=30, blank=True, help_text="Icon key from core/templatetags/icons.py")
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "amenities"
        ordering = ["sort_order", "name"]
        verbose_name_plural = "amenities"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = self.slug or slugify(self.name)
        super().save(*args, **kwargs)


class ApartmentQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Apartment.Status.PUBLISHED)

    def with_cover(self):
        """Load what listing cards need in a fixed number of queries."""
        return self.select_related("property_type").prefetch_related(
            Prefetch("images", queryset=ApartmentImage.objects.order_by("-is_primary", "sort_order", "id"))
        )


class Apartment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        DRAFT = "draft", "Unpublished"
        PUBLISHED = "published", "Published"
        REJECTED = "rejected", "Rejected"
        ARCHIVED = "archived", "Archived"

    # Statuses in which the owner may still edit or withdraw a submission.
    OWNER_EDITABLE_STATUSES = (Status.PENDING, Status.REJECTED)

    class Availability(models.TextChoices):
        AVAILABLE = "available", "Available now"
        COMING_SOON = "coming_soon", "Available soon"
        BOOKED = "booked", "Booked"
        RENTED = "rented", "Rented"

    # Availabilities in which a published listing can receive a booking request.
    BOOKABLE_AVAILABILITIES = (Availability.AVAILABLE, Availability.COMING_SOON)

    class TenantPreference(models.TextChoices):
        ANY = "any", "Anyone"
        FAMILY = "family", "Family"
        BACHELOR = "bachelor", "Bachelor"
        FEMALE = "female", "Female only"

    class Furnishing(models.TextChoices):
        FURNISHED = "furnished", "Furnished"
        SEMI_FURNISHED = "semi_furnished", "Semi-furnished"
        UNFURNISHED = "unfurnished", "Unfurnished"

    # Basics
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, editable=False)
    description = models.TextField()
    property_type = models.ForeignKey(PropertyType, on_delete=models.PROTECT, related_name="apartments")

    # Location
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100, db_index=True)
    area = models.CharField("Area / neighborhood", max_length=100, db_index=True)
    postal_code = models.CharField(max_length=20, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Specs
    rent = models.DecimalField("Monthly rent", max_digits=10, decimal_places=2)
    bedrooms = models.PositiveSmallIntegerField(help_text="0 for a studio")
    bathrooms = models.PositiveSmallIntegerField()
    size_sqft = models.PositiveIntegerField("Size (sq ft)", null=True, blank=True)
    furnishing = models.CharField(max_length=20, choices=Furnishing.choices, default=Furnishing.UNFURNISHED)
    availability = models.CharField(max_length=20, choices=Availability.choices, default=Availability.AVAILABLE, db_index=True)
    available_from = models.DateField(null=True, blank=True)

    # Bangladeshi rental terms
    advance_months = models.PositiveSmallIntegerField(
        "Advance (months)", default=2, help_text="Months of rent paid in advance as security."
    )
    service_charge = models.DecimalField(
        "Service charge / month", max_digits=10, decimal_places=2, default=0,
        help_text="Building maintenance, guard, lift, generator etc.",
    )
    tenant_preference = models.CharField(max_length=20, choices=TenantPreference.choices, default=TenantPreference.ANY)
    floor_number = models.PositiveSmallIntegerField("Floor", null=True, blank=True, help_text="0 for ground floor")
    total_floors = models.PositiveSmallIntegerField("Total floors in building", null=True, blank=True)

    amenities = models.ManyToManyField(Amenity, blank=True, related_name="apartments")
    extra_attributes = models.JSONField(default=dict, blank=True)

    # Contact
    contact_name = models.CharField(max_length=120)
    contact_phone = models.CharField(max_length=30, blank=True)
    contact_email = models.EmailField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="apartments",
        help_text="Profile that owns or manages this listing.",
    )

    # Publishing
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    is_featured = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    # Moderation of listings submitted by users ("List your home").
    submitted_by_user = models.BooleanField(default=False, editable=False)
    review_note = models.TextField(blank=True, help_text="Shown to the owner when a submission is rejected.")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", editable=False
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ApartmentQuerySet.as_manager()

    class Meta:
        db_table = "apartments"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "city"]),
            models.Index(fields=["status", "rent"]),
            models.Index(fields=["status", "bedrooms"]),
            models.Index(fields=["status", "-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(rent__gt=0), name="apartment_rent_positive"),
            models.CheckConstraint(condition=Q(size_sqft__isnull=True) | Q(size_sqft__gt=0), name="apartment_size_positive"),
            models.CheckConstraint(condition=Q(bedrooms__lte=50) & Q(bathrooms__lte=50), name="apartment_rooms_reasonable"),
            models.CheckConstraint(condition=Q(service_charge__gte=0), name="apartment_service_charge_non_negative"),
            models.CheckConstraint(condition=Q(advance_months__lte=24), name="apartment_advance_reasonable"),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug()
        if self.status == self.Status.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    # Slugs that would collide with other URLs under /apartments/.
    RESERVED_SLUGS = {"list-your-home", "my-listings"}

    def _unique_slug(self):
        base = slugify(self.title)[:200] or "apartment"
        slug = base
        while slug in self.RESERVED_SLUGS or Apartment.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{uuid.uuid4().hex[:6]}"
        return slug

    def get_absolute_url(self):
        return reverse("apartments:detail", kwargs={"slug": self.slug})

    @property
    def is_published(self):
        return self.status == self.Status.PUBLISHED

    @property
    def is_bookable(self):
        return self.is_published and self.availability in self.BOOKABLE_AVAILABILITIES

    @property
    def advance_amount(self):
        return self.rent * self.advance_months

    @property
    def move_in_cost(self):
        """Advance plus the first month's rent and service charge — what a renter pays upfront."""
        return self.advance_amount + self.rent + self.service_charge

    @property
    def floor_display(self):
        if self.floor_number is None:
            return ""
        label = "Ground floor" if self.floor_number == 0 else f"Floor {self.floor_number}"
        return f"{label} of {self.total_floors}" if self.total_floors else label

    @property
    def owner_can_edit(self):
        return self.status in self.OWNER_EDITABLE_STATUSES

    def can_be_viewed_by(self, user):
        if self.is_published:
            return True
        return user.is_authenticated and (user.is_admin or self.owner_id == user.pk)

    def approve(self, reviewer):
        self.status = self.Status.PUBLISHED
        self.review_note = ""
        self._mark_reviewed(reviewer)

    def reject(self, reviewer, note):
        self.status = self.Status.REJECTED
        self.review_note = note
        self._mark_reviewed(reviewer)

    def _mark_reviewed(self, reviewer):
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.save()

    @property
    def location_display(self):
        return ", ".join(part for part in (self.area, self.city) if part)

    @property
    def bedrooms_display(self):
        if self.bedrooms == 0:
            return "Studio"
        return f"{self.bedrooms} bed{'s' if self.bedrooms != 1 else ''}"

    @property
    def cover_image(self):
        """Primary image, else the first image. Uses prefetched images when available."""
        images = list(self.images.all())
        primary = next((img for img in images if img.is_primary), None)
        return primary or (images[0] if images else None)


def apartment_image_path(instance, filename):
    # apartments/<apartment-id>/<random>.jpg — organised per listing.
    return f"apartments/{instance.apartment_id}/{filename}"


class ApartmentImage(models.Model):
    apartment = models.ForeignKey(Apartment, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=apartment_image_path, width_field="width", height_field="height", max_length=255)
    caption = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    width = models.PositiveIntegerField(null=True, blank=True, editable=False)
    height = models.PositiveIntegerField(null=True, blank=True, editable=False)
    file_size = models.PositiveIntegerField(null=True, blank=True, editable=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "apartment_images"
        ordering = ["-is_primary", "sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["apartment"], condition=Q(is_primary=True), name="one_primary_image_per_apartment"
            ),
        ]

    def __str__(self):
        return f"Image {self.pk} of {self.apartment_id}"


class SavedApartment(models.Model):
    """A user's favourite listing."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_apartments")
    apartment = models.ForeignKey(Apartment, on_delete=models.CASCADE, related_name="saved_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "saved_apartments"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "apartment"], name="unique_saved_apartment")]
