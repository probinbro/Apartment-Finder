from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apartments import services
from apartments.models import Apartment, ApartmentImage
from core.models import ContactMessage
from users.models import User

from .helpers import apartment_form_data, image_upload, make_admin, make_apartment, make_user


class AdminAuthorizationTests(TestCase):
    def test_regular_user_gets_403_everywhere(self):
        apartment = make_apartment()
        self.client.force_login(make_user())
        urls = [
            reverse("admin_panel:dashboard"), reverse("admin_panel:requests"), reverse("admin_panel:apartments"),
            reverse("admin_panel:apartment_create"), reverse("admin_panel:apartment_edit", args=[apartment.pk]),
            reverse("admin_panel:users"), reverse("admin_panel:media"), reverse("admin_panel:taxonomy"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin_panel:apartment_delete", args=[apartment.pk])).status_code, 403)
        self.assertTrue(Apartment.objects.filter(pk=apartment.pk).exists())

    def test_admin_can_open_every_page(self):
        apartment = make_apartment()
        self.client.force_login(make_admin())
        for url in [reverse("admin_panel:dashboard"), reverse("admin_panel:requests"), reverse("admin_panel:apartments"),
                    reverse("admin_panel:apartment_images", args=[apartment.pk]), reverse("admin_panel:users"),
                    reverse("admin_panel:media"), reverse("admin_panel:taxonomy"), reverse("admin_panel:messages")]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_inactive_admin_has_no_access(self):
        admin = make_admin(is_active=False)
        self.assertFalse(admin.is_admin)


class ApartmentCrudTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)

    def test_create_apartment(self):
        response = self.client.post(reverse("admin_panel:apartment_create"), apartment_form_data())
        apartment = Apartment.objects.get(title="Bright flat")
        self.assertRedirects(response, reverse("admin_panel:apartment_images", args=[apartment.pk]))
        self.assertEqual(apartment.city, "Denver")  # normalised
        self.assertIsNotNone(apartment.published_at)

    def test_invalid_apartment_data(self):
        cases = {
            "rent": ("0", "Rent must be a positive amount"),
            "bedrooms": ("-1", "greater than or equal to 0"),
            "size_sqft": ("0", "Size must be greater than zero"),
            "title": ("   ", "This field"),
            "latitude": ("123", "Latitude must be between"),
        }
        for field, (value, message) in cases.items():
            with self.subTest(field=field):
                response = self.client.post(reverse("admin_panel:apartment_create"), apartment_form_data(**{field: value}))
                self.assertContains(response, message)
        response = self.client.post(reverse("admin_panel:apartment_create"), apartment_form_data(contact_phone="", contact_email=""))
        self.assertContains(response, "at least a contact phone number or email")
        self.assertFalse(Apartment.objects.exists())

    def test_edit_apartment(self):
        apartment = make_apartment()
        response = self.client.post(reverse("admin_panel:apartment_edit", args=[apartment.pk]), apartment_form_data(title="Renamed", rent="2500"))
        self.assertRedirects(response, reverse("admin_panel:apartments"))
        apartment.refresh_from_db()
        self.assertEqual((apartment.title, str(apartment.rent)), ("Renamed", "2500.00"))

    def test_delete_apartment_removes_images(self):
        apartment = make_apartment()
        image = services.add_images(apartment, [image_upload()])[0]
        storage, name = image.image.storage, image.image.name
        self.assertTrue(storage.exists(name))
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("admin_panel:apartment_delete", args=[apartment.pk]))
        self.assertRedirects(response, reverse("admin_panel:apartments"))
        self.assertFalse(Apartment.objects.filter(pk=apartment.pk).exists())
        self.assertFalse(storage.exists(name))

    def test_publish_and_unpublish(self):
        apartment = make_apartment(status=Apartment.Status.DRAFT)
        self.client.post(reverse("admin_panel:apartment_status", args=[apartment.pk]), {"status": "published"})
        apartment.refresh_from_db()
        self.assertTrue(apartment.is_published)
        self.client.post(reverse("admin_panel:apartment_status", args=[apartment.pk]), {"status": "bogus"})
        apartment.refresh_from_db()
        self.assertTrue(apartment.is_published)


class ImageManagementTests(TestCase):
    def setUp(self):
        self.client.force_login(make_admin())
        self.apartment = make_apartment()
        self.url = reverse("admin_panel:apartment_images", args=[self.apartment.pk])

    def test_upload_multiple_first_becomes_primary(self):
        response = self.client.post(self.url, {"images": [image_upload("a.jpg"), image_upload("b.webp", "WEBP")], "caption": "Nice"})
        self.assertRedirects(response, self.url)
        images = list(self.apartment.images.order_by("sort_order"))
        self.assertEqual(len(images), 2)
        self.assertTrue(images[0].is_primary)
        self.assertTrue(images[0].image.name.startswith(f"apartments/{self.apartment.pk}/"))
        self.assertEqual(images[1].caption, "Nice")

    def test_invalid_upload_rejected(self):
        bad = SimpleUploadedFile("shell.jpg", b"#!/bin/sh\nrm -rf /", content_type="image/jpeg")
        response = self.client.post(self.url, {"images": [bad]})
        self.assertContains(response, "not a valid image")
        self.assertFalse(ApartmentImage.objects.exists())

    def test_set_primary_replace_and_delete(self):
        first, second = services.add_images(self.apartment, [image_upload(), image_upload()])
        self.client.post(reverse("admin_panel:image_primary", args=[second.pk]))
        first.refresh_from_db(), second.refresh_from_db()
        self.assertTrue(second.is_primary)
        self.assertFalse(first.is_primary)

        old_name = second.image.name
        self.client.post(reverse("admin_panel:image_replace", args=[second.pk]), {"image": image_upload("new.png", "PNG")})
        second.refresh_from_db()
        self.assertNotEqual(second.image.name, old_name)
        self.assertTrue(second.is_primary)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("admin_panel:image_delete", args=[second.pk]))
        first.refresh_from_db()
        self.assertTrue(first.is_primary)  # promoted automatically


class ListingRequestReviewTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)
        self.pending = make_apartment(title="Owner flat", status=Apartment.Status.PENDING, owner=make_user("o@example.com"), submitted_by_user=True)

    def test_requests_queue_and_dashboard_badge(self):
        self.assertContains(self.client.get(reverse("admin_panel:requests")), "Owner flat")
        response = self.client.get(reverse("admin_panel:dashboard"))
        self.assertContains(response, "1 listing request waiting for review")

    def test_approve_publishes_listing(self):
        response = self.client.post(reverse("admin_panel:request_review", args=[self.pending.pk]), {"action": "approve"})
        self.assertRedirects(response, reverse("admin_panel:requests"))
        self.pending.refresh_from_db()
        self.assertTrue(self.pending.is_published)
        self.assertEqual(self.pending.reviewed_by, self.admin)
        self.assertIsNotNone(self.pending.published_at)
        self.assertEqual(self.client.get(self.pending.get_absolute_url()).status_code, 200)

    def test_reject_requires_note(self):
        url = reverse("admin_panel:request_review", args=[self.pending.pk])
        self.assertContains(self.client.post(url, {"action": "reject", "note": " "}), "tell the owner why")
        self.client.post(url, {"action": "reject", "note": "Photos are blurry"})
        self.pending.refresh_from_db()
        self.assertEqual((self.pending.status, self.pending.review_note), (Apartment.Status.REJECTED, "Photos are blurry"))


class UserManagementTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)

    def test_promote_and_disable_user(self):
        user = make_user()
        self.client.post(reverse("admin_panel:user_edit", args=[user.pk]), {"full_name": "U", "phone": "", "role": "admin", "is_active": ""})
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.ADMIN)
        self.assertFalse(user.is_active)

    def test_admin_cannot_demote_or_disable_self(self):
        self.client.post(reverse("admin_panel:user_edit", args=[self.admin.pk]), {"full_name": "Me", "role": "user", "is_active": ""})
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, User.Role.ADMIN)
        self.assertTrue(self.admin.is_active)

    def test_user_list_does_not_expose_credentials(self):
        response = self.client.get(reverse("admin_panel:users"))
        self.assertNotContains(response, "password")


class ContactFormTests(TestCase):
    def test_contact_message_saved_and_honeypot_blocks_bots(self):
        data = {"name": "Ann", "email": "ann@example.com", "subject": "Hi", "message": "Hello"}
        self.client.post(reverse("core:contact"), data)
        self.client.post(reverse("core:contact"), {**data, "website": "spam.example"})
        self.assertEqual(ContactMessage.objects.count(), 1)
