from django.db import migrations
from django.utils.text import slugify

# Property types commonly used in Bangladeshi rental listings ("To-Let").
PROPERTY_TYPES = [("Flat", 0), ("Sublet", 7), ("Bachelor seat", 8), ("Office space", 9)]

AMENITIES = [
    ("Gas line", "zap"), ("CCTV", "eye"), ("Intercom", "phone"), ("Rooftop access", "sun"),
    ("24h water supply", "waves"), ("IPS / power backup", "zap"), ("Prayer space", "home"), ("Car parking", "car"),
]
RENAMES = {"elevator": "Lift", "power-backup": "Generator"}
REMOVE_DUPLICATES = ["parking"]  # superseded by "Car parking"


def forwards(apps, schema_editor):
    PropertyType = apps.get_model("apartments", "PropertyType")
    Amenity = apps.get_model("apartments", "Amenity")
    for name, order in PROPERTY_TYPES:
        PropertyType.objects.get_or_create(slug=slugify(name), defaults={"name": name, "sort_order": order})

    for slug, name in RENAMES.items():
        Amenity.objects.filter(slug=slug).update(name=name)
    start = Amenity.objects.count()
    for offset, (name, icon) in enumerate(AMENITIES):
        Amenity.objects.get_or_create(slug=slugify(name), defaults={"name": name, "icon": icon, "sort_order": start + offset})

    car_parking = Amenity.objects.get(slug="car-parking")
    for old in Amenity.objects.filter(slug__in=REMOVE_DUPLICATES):
        for apartment in old.apartments.all():
            apartment.amenities.add(car_parking)
        old.delete()


class Migration(migrations.Migration):
    dependencies = [("apartments", "0004_bangladesh_rental_terms")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
