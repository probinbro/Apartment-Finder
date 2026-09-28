from django.db import migrations
from django.utils.text import slugify

PROPERTY_TYPES = ["Apartment", "Studio", "Condo", "Penthouse", "Duplex", "Loft", "Shared room"]

AMENITIES = [
    ("Wi-Fi", "wifi"), ("Air conditioning", "snowflake"), ("Parking", "car"), ("Balcony", "sun"),
    ("Elevator", "elevator"), ("Gym", "dumbbell"), ("Swimming pool", "waves"), ("24/7 security", "shield"),
    ("Power backup", "zap"), ("Pet friendly", "paw"), ("Furnished kitchen", "home"), ("Laundry", "refresh"),
]


def seed(apps, schema_editor):
    PropertyType = apps.get_model("apartments", "PropertyType")
    Amenity = apps.get_model("apartments", "Amenity")
    for order, name in enumerate(PROPERTY_TYPES):
        PropertyType.objects.get_or_create(slug=slugify(name), defaults={"name": name, "sort_order": order})
    for order, (name, icon) in enumerate(AMENITIES):
        Amenity.objects.get_or_create(slug=slugify(name), defaults={"name": name, "icon": icon, "sort_order": order})


class Migration(migrations.Migration):
    dependencies = [("apartments", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
