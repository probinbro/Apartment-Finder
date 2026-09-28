from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apartments.models import Amenity, Apartment, PropertyType

from .helpers import apartment_form_data, image_upload, make_admin, make_apartment, make_user


class GuestBrowsingTests(TestCase):
    def test_public_pages_are_open_to_guests(self):
        make_apartment()
        for name in ["core:home", "core:about", "core:contact", "apartments:list", "users:login", "users:register"]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_home_shows_published_listings_and_locations(self):
        make_apartment(title="Visible flat", is_featured=True)
        make_apartment(title="Hidden flat", status=Apartment.Status.DRAFT)
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "Visible flat")
        self.assertNotContains(response, "Hidden flat")
        self.assertContains(response, "Browse by location")

    def test_guests_cannot_reach_admin_or_owner_actions(self):
        apartment = make_apartment()
        for url in [reverse("admin_panel:dashboard"), reverse("admin_panel:apartment_create"),
                    reverse("admin_panel:apartment_edit", args=[apartment.pk])]:
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), f"{reverse('users:login')}?next={url}")
        response = self.client.post(reverse("admin_panel:apartment_delete", args=[apartment.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Apartment.objects.filter(pk=apartment.pk).exists())


class ApartmentDetailTests(TestCase):
    def test_published_detail_page(self):
        apartment = make_apartment(title="Sunny loft", description="Great light.")
        response = self.client.get(apartment.get_absolute_url())
        self.assertContains(response, "Sunny loft")
        self.assertContains(response, "Great light.")
        self.assertContains(response, "$1,500")

    def test_missing_apartment_is_friendly_404(self):
        response = self.client.get(reverse("apartments:detail", args=["does-not-exist"]))
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "couldn't find that page", status_code=404)

    def test_unpublished_listing_hidden_from_public_but_previewable(self):
        owner = make_user("owner@example.com")
        apartment = make_apartment(status=Apartment.Status.PENDING, owner=owner)
        self.assertEqual(self.client.get(apartment.get_absolute_url()).status_code, 404)

        self.client.force_login(make_user("other@example.com"))
        self.assertEqual(self.client.get(apartment.get_absolute_url()).status_code, 404)

        self.client.force_login(owner)
        self.assertContains(self.client.get(apartment.get_absolute_url()), "Preview")

        self.client.force_login(make_admin())
        self.assertContains(self.client.get(apartment.get_absolute_url()), "Review request")

    def test_reserved_slugs_are_not_used(self):
        apartment = make_apartment(title="List your home")
        self.assertNotEqual(apartment.slug, "list-your-home")


class SearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        condo = PropertyType.objects.get_or_create(slug="condo", defaults={"name": "Condo"})[0]
        cls.parking = Amenity.objects.get_or_create(slug="parking", defaults={"name": "Parking"})[0]
        cls.cheap = make_apartment(title="Cheap studio", city="Austin", area="Campus", rent=Decimal("900"), bedrooms=0)
        cls.mid = make_apartment(title="Family home", city="Denver", area="Highlands", rent=Decimal("2200"), bedrooms=3, bathrooms=2)
        cls.condo = make_apartment(title="City condo", city="Denver", area="LoDo", rent=Decimal("3000"), bedrooms=1, property_type=condo)
        cls.condo.amenities.add(cls.parking)
        make_apartment(title="Draft place", city="Denver", status=Apartment.Status.DRAFT)

    def search(self, **params):
        response = self.client.get(reverse("apartments:list"), params)
        return {a.title for a in response.context["apartments"]}

    def test_lists_only_published(self):
        self.assertEqual(self.search(), {"Cheap studio", "Family home", "City condo"})

    def test_keyword_matches_city_area_and_title(self):
        self.assertEqual(self.search(q="denver"), {"Family home", "City condo"})
        self.assertEqual(self.search(q="highlands"), {"Family home"})

    def test_filters(self):
        self.assertEqual(self.search(city="Austin"), {"Cheap studio"})
        self.assertEqual(self.search(min_rent=1000, max_rent=2500), {"Family home"})
        self.assertEqual(self.search(bedrooms=2), {"Family home"})
        self.assertEqual(self.search(bathrooms=2), {"Family home"})
        self.assertEqual(self.search(property_type="condo"), {"City condo"})
        self.assertEqual(self.search(amenities="parking"), {"City condo"})

    def test_sorting(self):
        response = self.client.get(reverse("apartments:list"), {"sort": "rent_asc"})
        self.assertEqual([a.title for a in response.context["apartments"]], ["Cheap studio", "Family home", "City condo"])

    def test_invalid_input_is_ignored_gracefully(self):
        response = self.client.get(reverse("apartments:list"), {"bedrooms": "lots", "min_rent": "-5", "page": "999"})
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("apartments:list"), {"min_rent": 5000, "max_rent": 100})
        self.assertContains(response, "Max rent must be greater than min rent")

    def test_empty_results_state(self):
        self.assertContains(self.client.get(reverse("apartments:list"), {"q": "atlantis"}), "No apartments match your search")


class ListYourHomeTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com", full_name="Olive Owner")
        self.client.force_login(self.owner)

    def submission_data(self, **overrides):
        data = apartment_form_data(**overrides)
        data.pop("status")
        data["photos"] = [image_upload("front.jpg"), image_upload("kitchen.png", "PNG")]
        return data

    def test_form_is_prefilled_with_owner_contact(self):
        response = self.client.get(reverse("apartments:submit"))
        self.assertContains(response, "Olive Owner")

    def test_submission_creates_pending_listing_with_photos(self):
        response = self.client.post(reverse("apartments:submit"), self.submission_data())
        self.assertRedirects(response, reverse("apartments:my_listings"))
        apartment = Apartment.objects.get(title="Bright flat")
        self.assertEqual(apartment.status, Apartment.Status.PENDING)
        self.assertEqual(apartment.owner, self.owner)
        self.assertTrue(apartment.submitted_by_user)
        self.assertEqual(apartment.images.count(), 2)
        self.assertEqual(apartment.images.filter(is_primary=True).count(), 1)
        # not public until approved
        self.assertNotIn(apartment, Apartment.objects.published())

    def test_owner_cannot_publish_or_feature_by_tampering(self):
        self.client.post(reverse("apartments:submit"), self.submission_data(status="published", is_featured="on", owner=999))
        apartment = Apartment.objects.get(title="Bright flat")
        self.assertEqual(apartment.status, Apartment.Status.PENDING)
        self.assertFalse(apartment.is_featured)
        self.assertEqual(apartment.owner, self.owner)

    def test_photo_required_and_validated(self):
        data = self.submission_data()
        data["photos"] = []
        self.assertContains(self.client.post(reverse("apartments:submit"), data), "Choose at least one image")
        from django.core.files.uploadedfile import SimpleUploadedFile
        data["photos"] = [SimpleUploadedFile("virus.jpg", b"not an image", content_type="image/jpeg")]
        self.assertContains(self.client.post(reverse("apartments:submit"), data), "not a valid image")
        self.assertFalse(Apartment.objects.exists())

    def test_invalid_listing_data_rejected(self):
        response = self.client.post(reverse("apartments:submit"), self.submission_data(rent="-10", bedrooms="-1", title="  "))
        self.assertContains(response, "Please correct the errors below")
        self.assertFalse(Apartment.objects.exists())

    def test_pending_limit(self):
        for i in range(5):
            make_apartment(title=f"Pending {i}", status=Apartment.Status.PENDING, owner=self.owner)
        response = self.client.post(reverse("apartments:submit"), self.submission_data())
        self.assertContains(response, "several listings waiting for review")
        self.assertFalse(Apartment.objects.filter(title="Bright flat").exists())

    def test_my_listings_shows_status_and_rejection_note(self):
        make_apartment(title="Needs work", status=Apartment.Status.REJECTED, owner=self.owner, review_note="Add real photos")
        make_apartment(title="Someone else's", owner=make_user("x@example.com"))
        response = self.client.get(reverse("apartments:my_listings"))
        self.assertContains(response, "Needs work")
        self.assertContains(response, "Add real photos")
        self.assertNotContains(response, "Someone else")

    def test_editing_rejected_listing_resubmits_it(self):
        apartment = make_apartment(status=Apartment.Status.REJECTED, owner=self.owner, review_note="Fix title")
        data = self.submission_data(title="Fixed title")
        data["photos"] = []
        response = self.client.post(reverse("apartments:edit_listing", args=[apartment.pk]), data)
        self.assertRedirects(response, reverse("apartments:my_listings"))
        apartment.refresh_from_db()
        self.assertEqual((apartment.title, apartment.status), ("Fixed title", Apartment.Status.PENDING))

    def test_published_listing_cannot_be_edited_by_owner(self):
        apartment = make_apartment(owner=self.owner)
        response = self.client.post(reverse("apartments:edit_listing", args=[apartment.pk]), self.submission_data(title="Sneaky"))
        self.assertRedirects(response, reverse("apartments:my_listings"))
        apartment.refresh_from_db()
        self.assertNotEqual(apartment.title, "Sneaky")

    def test_users_cannot_touch_other_peoples_listings(self):
        other = make_apartment(status=Apartment.Status.PENDING, owner=make_user("x@example.com"))
        self.assertEqual(self.client.get(reverse("apartments:edit_listing", args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("apartments:delete_listing", args=[other.pk])).status_code, 404)
        self.assertTrue(Apartment.objects.filter(pk=other.pk).exists())

    def test_owner_can_remove_listing(self):
        apartment = make_apartment(owner=self.owner, status=Apartment.Status.PENDING)
        self.client.post(reverse("apartments:delete_listing", args=[apartment.pk]))
        self.assertFalse(Apartment.objects.filter(pk=apartment.pk).exists())
