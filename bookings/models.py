"""
Booking requests from renters to landlords.

Flow: a renter books a published, available apartment → the apartment is
marked Booked while the landlord decides → accepted (stays booked), or
declined / cancelled / expired (apartment becomes available again).
A partial unique constraint guarantees at most one open booking per apartment,
even if two renters click "Book" at the same moment.
"""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

OPEN_STATUSES = ("pending", "accepted")


class BookingQuerySet(models.QuerySet):
    def open(self):
        return self.filter(status__in=OPEN_STATUSES)

    def for_landlord(self, user):
        """Bookings a user may manage: on listings they own (admins: everything)."""
        if user.is_admin:
            return self
        return self.filter(apartment__owner=user)

    def stale(self):
        cutoff = timezone.now() - timedelta(days=settings.BOOKING_HOLD_DAYS)
        return self.filter(status=Booking.Status.PENDING, created_at__lt=cutoff)


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for landlord"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"
        COMPLETED = "completed", "Tenancy ended"

    class Household(models.TextChoices):
        FAMILY = "family", "Family"
        BACHELOR = "bachelor", "Bachelor"
        FEMALE = "female", "Female"
        OTHER = "other", "Other"

    apartment = models.ForeignKey("apartments.Apartment", on_delete=models.CASCADE, related_name="bookings")
    tenant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)

    # Details supplied by the renter
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30)
    email = models.EmailField()
    household = models.CharField("Household type", max_length=20, choices=Household.choices, default=Household.FAMILY)
    occupants = models.PositiveSmallIntegerField("Number of people", default=1)
    move_in_date = models.DateField("Preferred move-in date")
    visit_date = models.DateField("Preferred viewing date", null=True, blank=True)
    message = models.TextField("Message to landlord", blank=True, max_length=2000)

    # Landlord's response
    landlord_note = models.TextField(blank=True, max_length=2000)
    responded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    responded_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BookingQuerySet.as_manager()

    class Meta:
        db_table = "bookings"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["apartment"], condition=Q(status__in=OPEN_STATUSES), name="one_open_booking_per_apartment"
            ),
            models.CheckConstraint(condition=Q(occupants__gte=1) & Q(occupants__lte=30), name="booking_occupants_range"),
        ]
        indexes = [models.Index(fields=["tenant", "status"])]

    def __str__(self):
        return f"Booking #{self.pk} · {self.apartment} · {self.get_status_display()}"

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES

    @property
    def expires_at(self):
        return self.created_at + timedelta(days=settings.BOOKING_HOLD_DAYS)

    @property
    def landlord(self):
        return self.apartment.owner

    def can_be_managed_by(self, user):
        return user.is_authenticated and (user.is_admin or self.apartment.owner_id == user.pk)
