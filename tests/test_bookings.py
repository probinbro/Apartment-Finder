from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apartments.models import Apartment, SavedApartment
from bookings import services
from bookings.models import Booking
from core.templatetags.ui import format_money

from .helpers import make_admin, make_apartment, make_user


def booking_data(**overrides):
    data = {
        "full_name": "Rahim Uddin",
        "phone": "01712345678",
        "email": "rahim@example.com",
        "household": "family",
        "occupants": "4",
        "move_in_date": (timezone.localdate() + timedelta(days=20)).isoformat(),
        "visit_date": (timezone.localdate() + timedelta(days=3)).isoformat(),
        "message": "We are a family of four.",
        "agree": "on",
    }
    data.update(overrides)
    return data


@override_settings(ADMIN_NOTIFICATION_EMAILS=[])
class BookingFlowTests(TestCase):
    def setUp(self):
        self.landlord = make_user("landlord@example.com", full_name="Karim Landlord")
        self.tenant = make_user("tenant@example.com", full_name="Rahim Uddin")
        self.apartment = make_apartment(
            title="Dhanmondi flat", owner=self.landlord, contact_phone="01811111111",
            contact_email="karim.contact@example.com", rent=Decimal("45000"),
        )
        self.book_url = reverse("bookings:book", args=[self.apartment.slug])

    def book(self, **overrides):
        self.client.force_login(self.tenant)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.book_url, booking_data(**overrides))

    def test_booking_requires_login(self):
        response = self.client.get(self.book_url)
        self.assertRedirects(response, f"{reverse('users:login')}?next={self.book_url}")

    def test_detail_page_shows_book_button_and_hides_phone(self):
        response = self.client.get(self.apartment.get_absolute_url())
        self.assertContains(response, "Book this apartment")
        self.assertNotContains(response, "01811111111")

    def test_booking_marks_apartment_booked_and_emails_landlord(self):
        response = self.book()
        self.assertRedirects(response, reverse("bookings:my_bookings"))
        booking = Booking.objects.get()
        self.assertEqual((booking.status, booking.tenant, booking.occupants), (Booking.Status.PENDING, self.tenant, 4))
        self.apartment.refresh_from_db()
        self.assertEqual(self.apartment.availability, Apartment.Availability.BOOKED)

        landlord_mail = next(m for m in mail.outbox if "landlord@example.com" in m.to)
        self.assertIn("karim.contact@example.com", landlord_mail.to)  # listing contact email too
        self.assertIn("New booking request", landlord_mail.subject)
        self.assertIn("01712345678", landlord_mail.body)
        self.assertEqual(landlord_mail.reply_to, ["rahim@example.com"])
        self.assertTrue(any(m.to == ["rahim@example.com"] for m in mail.outbox))  # confirmation to renter

    def test_booked_apartment_shows_badge_and_cannot_be_booked_again(self):
        self.book()
        other = make_user("other@example.com")
        self.client.force_login(other)
        page = self.client.get(self.apartment.get_absolute_url())
        self.assertContains(page, "Currently booked")
        response = self.client.post(self.book_url, booking_data(), follow=True)
        self.assertContains(response, "already booked")
        self.assertEqual(Booking.objects.count(), 1)
        self.assertContains(self.client.get(reverse("apartments:list")), "Booked")

    def test_database_prevents_two_open_bookings(self):
        self.book()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Booking.objects.create(
                apartment=self.apartment, tenant=make_user("x@example.com"), full_name="X", phone="0171", email="x@x.com",
                move_in_date=timezone.localdate(),
            )

    def test_landlord_sees_request_and_accepts(self):
        self.book()
        booking = Booking.objects.get()
        self.client.force_login(self.landlord)
        dashboard = self.client.get(reverse("bookings:landlord_requests"))
        self.assertContains(dashboard, "Rahim Uddin")
        self.assertContains(dashboard, "01712345678")
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("bookings:respond", args=[booking.pk]), {"action": "accept", "note": "Come Friday 5pm"})
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.ACCEPTED)
        self.assertEqual(mail.outbox[0].to, ["rahim@example.com"])
        self.assertIn("accepted", mail.outbox[0].subject)
        self.assertIn("01811111111", mail.outbox[0].body)  # landlord number revealed

        self.client.force_login(self.tenant)
        self.assertContains(self.client.get(self.apartment.get_absolute_url()), "01811111111")

    def test_decline_releases_apartment(self):
        self.book()
        booking = Booking.objects.get()
        self.client.force_login(self.landlord)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("bookings:respond", args=[booking.pk]), {"action": "decline"})
        self.apartment.refresh_from_db()
        self.assertEqual(self.apartment.availability, Apartment.Availability.AVAILABLE)
        self.assertEqual(Booking.objects.get().status, Booking.Status.DECLINED)

    def test_tenant_can_cancel_and_landlord_is_notified(self):
        self.book()
        booking = Booking.objects.get()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("bookings:cancel", args=[booking.pk]))
        self.apartment.refresh_from_db()
        self.assertEqual(self.apartment.availability, Apartment.Availability.AVAILABLE)
        self.assertIn("landlord@example.com", mail.outbox[0].to)

    def test_other_users_cannot_respond_or_cancel(self):
        self.book()
        booking = Booking.objects.get()
        stranger = make_user("stranger@example.com")
        self.client.force_login(stranger)
        self.assertEqual(self.client.post(reverse("bookings:respond", args=[booking.pk]), {"action": "accept"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("bookings:cancel", args=[booking.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("bookings:landlord_requests")), "Rahim Uddin")
        self.assertEqual(Booking.objects.get().status, Booking.Status.PENDING)

    def test_tenant_cannot_accept_own_booking(self):
        self.book()
        booking = Booking.objects.get()
        self.assertEqual(self.client.post(reverse("bookings:respond", args=[booking.pk]), {"action": "accept"}).status_code, 403)

    def test_landlord_cannot_book_own_listing(self):
        self.client.force_login(self.landlord)
        response = self.client.post(self.book_url, booking_data(), follow=True)
        self.assertContains(response, "your own listing")
        self.assertFalse(Booking.objects.exists())

    def test_invalid_booking_input(self):
        self.client.force_login(self.tenant)
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        response = self.client.post(self.book_url, booking_data(move_in_date=yesterday, phone="abc", occupants="0", agree=""))
        self.assertContains(response, "can&#x27;t be in the past")
        self.assertContains(response, "valid phone number")
        self.assertFalse(Booking.objects.exists())

    @override_settings(MAX_ACTIVE_BOOKINGS_PER_USER=1)
    def test_limit_on_open_bookings(self):
        self.book()
        second = make_apartment(title="Second flat", owner=self.landlord)
        response = self.client.post(reverse("bookings:book", args=[second.slug]), booking_data(), follow=True)
        self.assertContains(response, "already have 1 open booking")

    def test_stale_requests_expire_and_free_the_apartment(self):
        self.book()
        Booking.objects.update(created_at=timezone.now() - timedelta(days=10))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(services.expire_stale_bookings(), 1)
        self.apartment.refresh_from_db()
        self.assertEqual(self.apartment.availability, Apartment.Availability.AVAILABLE)
        self.assertEqual(Booking.objects.get().status, Booking.Status.EXPIRED)

    def test_complete_tenancy(self):
        self.book()
        booking = Booking.objects.get()
        services.accept_booking(booking, self.landlord)
        self.client.force_login(self.landlord)
        self.client.post(reverse("bookings:complete", args=[booking.pk]), {"relist": "0"})
        self.apartment.refresh_from_db()
        self.assertEqual(self.apartment.availability, Apartment.Availability.RENTED)


class AdminBookingTests(TestCase):
    def test_admins_handle_bookings_for_listings_without_landlord(self):
        admin = make_admin("boss@example.com")
        apartment = make_apartment(contact_email="")
        tenant = make_user("t@example.com")
        with self.captureOnCommitCallbacks(execute=True):
            booking = services.create_booking(apartment, tenant, {
                "full_name": "T", "phone": "01700000000", "email": "t@example.com", "move_in_date": timezone.localdate(),
            })
        self.assertTrue(any("boss@example.com" in m.to for m in mail.outbox))
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse("admin_panel:bookings")), "you manage this booking")
        self.client.post(reverse("bookings:respond", args=[booking.pk]), {"action": "accept"})
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.ACCEPTED)


class SavedApartmentTests(TestCase):
    def test_toggle_save(self):
        user = make_user()
        apartment = make_apartment()
        self.client.force_login(user)
        url = reverse("apartments:toggle_save", args=[apartment.slug])
        self.assertEqual(self.client.post(url, HTTP_X_REQUESTED_WITH="fetch").json(), {"saved": True})
        self.assertContains(self.client.get(reverse("users:saved")), apartment.title)
        self.assertEqual(self.client.post(url, HTTP_X_REQUESTED_WITH="fetch").json(), {"saved": False})
        self.assertFalse(SavedApartment.objects.exists())

    def test_guest_cannot_save(self):
        apartment = make_apartment()
        self.assertEqual(self.client.post(reverse("apartments:toggle_save", args=[apartment.slug])).status_code, 302)


class TakaFormattingTests(TestCase):
    def test_lakh_grouping(self):
        self.assertEqual(format_money(Decimal("150000")), "৳1,50,000")
        self.assertEqual(format_money(Decimal("2500000.50")), "৳25,00,000.50")
        self.assertEqual(format_money(Decimal("750")), "৳750")
        self.assertEqual(format_money(Decimal("12000")), "৳12,000")
        self.assertEqual(format_money("not a number"), "")
