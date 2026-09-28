"""
Booking notification emails.

Emails are sent after the database transaction commits, and a failed email
never breaks the booking itself — it is logged instead.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from users.models import User

logger = logging.getLogger(__name__)


def _absolute(path):
    return f"{settings.SITE_URL}{path}"


def landlord_recipients(booking):
    """Owner's account email and listing contact email; admins for listings without an owner."""
    apartment = booking.apartment
    emails = []
    if apartment.owner and apartment.owner.is_active:
        emails.append(apartment.owner.email)
    if apartment.contact_email:
        emails.append(apartment.contact_email)
    if not apartment.owner:
        emails += settings.ADMIN_NOTIFICATION_EMAILS or list(
            User.objects.filter(role=User.Role.ADMIN, is_active=True).values_list("email", flat=True)
        )
    return sorted({e.lower() for e in emails if e})


def _send(template, subject, recipients, context, reply_to=None):
    if not recipients:
        logger.warning("No recipients for email %s", template)
        return
    context = {"SITE_NAME": settings.SITE_NAME, "CURRENCY_SYMBOL": settings.CURRENCY_SYMBOL, **context}
    text_body = render_to_string(f"bookings/emails/{template}.txt", context)
    html_body = render_to_string(f"bookings/emails/{template}.html", context)
    message = EmailMultiAlternatives(
        subject=f"{subject} · {settings.SITE_NAME}", body=text_body, to=recipients, reply_to=reply_to or None
    )
    message.attach_alternative(html_body, "text/html")
    try:
        message.send()
    except Exception:
        logger.exception("Failed to send '%s' email to %s", template, recipients)


def _context(booking):
    return {
        "booking": booking,
        "apartment": booking.apartment,
        "apartment_url": _absolute(booking.apartment.get_absolute_url()),
        "landlord_url": _absolute(reverse("bookings:landlord_requests")),
        "tenant_url": _absolute(reverse("bookings:my_bookings")),
    }


def send_new_booking_notifications(booking):
    context = _context(booking)
    _send(
        "landlord_new_booking", f"New booking request for “{booking.apartment.title}”",
        landlord_recipients(booking), context, reply_to=[booking.email],
    )
    _send("tenant_booking_received", "We sent your booking request", [booking.email], context)


def send_booking_decision(booking):
    accepted = booking.status == booking.Status.ACCEPTED
    subject = "Your booking was accepted 🎉" if accepted else "Update on your booking request"
    _send("tenant_booking_decision", subject, [booking.email], _context(booking))


def send_booking_cancelled(booking, notify_landlord=True, was_accepted=False):
    context = {**_context(booking), "was_accepted": was_accepted}
    if notify_landlord:
        _send("landlord_booking_cancelled", f"Booking cancelled for “{booking.apartment.title}”", landlord_recipients(booking), context)


def send_booking_expired(booking):
    _send("tenant_booking_expired", "Your booking request expired", [booking.email], _context(booking))
