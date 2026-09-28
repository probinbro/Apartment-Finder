"""Booking state changes. Every transition keeps the apartment's availability in sync."""

import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apartments.models import Apartment

from . import emails
from .models import Booking

logger = logging.getLogger(__name__)


class BookingError(Exception):
    """Raised with a user-safe message when a booking action isn't allowed."""


def _set_availability(apartment_id, availability):
    Apartment.objects.filter(pk=apartment_id).update(availability=availability, updated_at=timezone.now())


def expire_stale_bookings():
    """Free apartments whose booking requests went unanswered. Cheap; called on booking pages."""
    expired = 0
    for booking in Booking.objects.stale().select_related("apartment"):
        with transaction.atomic():
            updated = Booking.objects.filter(pk=booking.pk, status=Booking.Status.PENDING).update(
                status=Booking.Status.EXPIRED, updated_at=timezone.now()
            )
            if updated:
                _set_availability(booking.apartment_id, Apartment.Availability.AVAILABLE)
                expired += 1
                transaction.on_commit(lambda b=booking: emails.send_booking_expired(b))
    return expired


def create_booking(apartment, tenant, data):
    """Create a booking and mark the apartment as booked, atomically."""
    if apartment.owner_id == tenant.pk:
        raise BookingError("You can't book your own listing.")
    open_count = Booking.objects.filter(tenant=tenant).open().count()
    if open_count >= settings.MAX_ACTIVE_BOOKINGS_PER_USER:
        raise BookingError(
            f"You already have {open_count} open bookings. Cancel one before booking another apartment."
        )

    try:
        with transaction.atomic():
            # Lock the row so two renters can't book the same apartment concurrently.
            locked = Apartment.objects.select_for_update().get(pk=apartment.pk)
            if not locked.is_bookable:
                raise BookingError("Sorry, this apartment has just been booked by someone else.")
            booking = Booking.objects.create(apartment=locked, tenant=tenant, **data)
            locked.availability = Apartment.Availability.BOOKED
            locked.save(update_fields=["availability", "updated_at"])
    except IntegrityError as exc:  # unique open-booking constraint (race on databases without row locks)
        raise BookingError("Sorry, this apartment has just been booked by someone else.") from exc

    transaction.on_commit(lambda: emails.send_new_booking_notifications(booking))
    return booking


def _respond(booking, actor, status, note, availability):
    with transaction.atomic():
        booking.status = status
        booking.landlord_note = note
        booking.responded_by = actor
        booking.responded_at = timezone.now()
        booking.save(update_fields=["status", "landlord_note", "responded_by", "responded_at", "updated_at"])
        _set_availability(booking.apartment_id, availability)


def accept_booking(booking, actor, note=""):
    if booking.status != Booking.Status.PENDING:
        raise BookingError("Only pending requests can be accepted.")
    _respond(booking, actor, Booking.Status.ACCEPTED, note, Apartment.Availability.BOOKED)
    transaction.on_commit(lambda: emails.send_booking_decision(booking))


def decline_booking(booking, actor, note=""):
    if booking.status != Booking.Status.PENDING:
        raise BookingError("Only pending requests can be declined.")
    _respond(booking, actor, Booking.Status.DECLINED, note, Apartment.Availability.AVAILABLE)
    transaction.on_commit(lambda: emails.send_booking_decision(booking))


def cancel_booking(booking, actor):
    """Tenant withdraws a pending or accepted booking; the apartment is released."""
    if not booking.is_open:
        raise BookingError("This booking is no longer active.")
    was_accepted = booking.status == Booking.Status.ACCEPTED
    with transaction.atomic():
        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=["status", "updated_at"])
        _set_availability(booking.apartment_id, Apartment.Availability.AVAILABLE)
    transaction.on_commit(lambda: emails.send_booking_cancelled(booking, notify_landlord=True, was_accepted=was_accepted))


def complete_booking(booking, actor, relist=True):
    """Landlord marks an accepted tenancy as ended/rented out."""
    if booking.status != Booking.Status.ACCEPTED:
        raise BookingError("Only accepted bookings can be closed.")
    with transaction.atomic():
        booking.status = Booking.Status.COMPLETED
        booking.save(update_fields=["status", "updated_at"])
        _set_availability(
            booking.apartment_id,
            Apartment.Availability.AVAILABLE if relist else Apartment.Availability.RENTED,
        )
