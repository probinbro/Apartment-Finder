"""
Load realistic demo listings with real, openly licensed photos.

Listing data and photo sources live in apartments/demo/listings.json. Photos
come from Wikimedia Commons (CC0 / CC BY / CC BY-SA); each image caption
credits the photographer and licence. If a photo can't be downloaded (e.g.
offline), a generated placeholder illustration is used instead.

    python manage.py seed_demo           # add demo listings (skips existing titles)
    python manage.py seed_demo --reset   # delete previous demo listings first
"""

import io
import json
import random
from decimal import Decimal
from pathlib import Path

import requests
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand
from PIL import Image, ImageDraw

from apartments.models import Amenity, Apartment, PropertyType
from apartments.services import add_images

DEMO_MARKER = "demo"  # stored in extra_attributes to identify seeded rows
DATA_FILE = Path(__file__).resolve().parents[2] / "demo" / "listings.json"
USER_AGENT = "ApartmentFinderDemoSeeder/1.0 (Django demo data loader)"
CONTACTS = [
    ("Mizanur Rahman", "+880 1711-234567"), ("Farzana Akter", "+880 1819-456123"),
    ("Tanvir Hasan", "+880 1552-789012"), ("Nusrat Jahan", "+880 1911-345678"),
]


def download_photo(session, url, name):
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return SimpleUploadedFile(name, response.content, content_type="image/jpeg")


def placeholder_photo(seed, width=1280, height=900):
    """Simple interior illustration used when a real photo can't be fetched."""
    rng = random.Random(seed)
    wall = rng.choice([(236, 229, 216), (226, 232, 240), (240, 234, 226)])
    accent = rng.choice([(15, 118, 110), (249, 115, 82), (59, 130, 246)])
    image = Image.new("RGB", (width, height), wall)
    draw = ImageDraw.Draw(image)
    horizon = int(height * 0.68)
    draw.rectangle([0, horizon, width, height], fill=(160, 130, 100))
    draw.rectangle([150, 90, 560, 420], fill=(170, 215, 240), outline=(250, 250, 250), width=14)
    draw.rounded_rectangle([580, horizon - 150, 1100, horizon + 40], radius=34, fill=accent)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return SimpleUploadedFile(f"placeholder-{seed}.jpg", buffer.getvalue(), content_type="image/jpeg")


class Command(BaseCommand):
    help = "Create realistic demo apartment listings with real photos."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing demo listings first.")
        parser.add_argument("--no-images", action="store_true", help="Skip photos entirely.")

    def handle(self, *args, reset=False, no_images=False, **options):
        if reset:
            demo = Apartment.objects.filter(extra_attributes__source=DEMO_MARKER)
            count = demo.count()
            for apartment in demo:  # per-object delete so image files are removed too
                apartment.delete()
            self.stdout.write(f"Removed {count} demo listings.")

        types = {pt.slug: pt for pt in PropertyType.objects.all()}
        amenities = {a.slug: a for a in Amenity.objects.all()}
        if not types:
            self.stderr.write("No property types found — run `python manage.py migrate` first.")
            return

        listings = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
        created = 0

        for index, item in enumerate(listings):
            if Apartment.objects.filter(title=item["title"]).exists():
                continue
            contact_name, contact_phone = CONTACTS[index % len(CONTACTS)]
            apartment = Apartment.objects.create(
                title=item["title"],
                description=item["desc"],
                property_type=types.get(item["type"]) or next(iter(types.values())),
                address=item["address"],
                city=item["city"],
                area=item["area"],
                rent=Decimal(item["rent"]),
                bedrooms=item["beds"],
                bathrooms=item["baths"],
                size_sqft=item["size"],
                furnishing=item["furnishing"],
                availability=Apartment.Availability.AVAILABLE if index % 5 else Apartment.Availability.COMING_SOON,
                advance_months=item.get("advance", 2),
                service_charge=Decimal(item.get("service", "0")),
                tenant_preference=item.get("tenant", Apartment.TenantPreference.ANY),
                floor_number=item.get("floor"),
                total_floors=item.get("floors"),
                contact_name=contact_name,
                contact_phone=contact_phone,
                contact_email="",  # booking emails go to admins for demo listings
                status=item.get("status", Apartment.Status.PUBLISHED),
                is_featured=item["featured"],
                extra_attributes={"source": DEMO_MARKER},
            )
            apartment.amenities.set([amenities[slug] for slug in item["amen"] if slug in amenities])
            if not no_images:
                self._attach_photos(session, apartment, item["photos"], index)
            created += 1
            self.stdout.write(f"  + {apartment.title}")

        self.stdout.write(self.style.SUCCESS(f"Created {created} demo listings."))

    def _attach_photos(self, session, apartment, photos, index):
        for number, photo in enumerate(photos):
            name = f"demo-{index}-{number}.jpg"
            try:
                upload = download_photo(session, photo["url"], name)
            except requests.RequestException as exc:
                self.stderr.write(f"    ! could not download photo ({exc.__class__.__name__}); using placeholder")
                upload = placeholder_photo(index * 10 + number)
                caption = photo["room"]
            else:
                caption = f"{photo['room']} · Photo: {photo['credit']}"
            add_images(apartment, [upload], caption=caption[:150])
