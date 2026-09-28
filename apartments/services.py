"""Image management operations for apartment listings."""

from django.db import transaction
from django.db.models import Max
from django.db.models.signals import post_delete
from django.dispatch import receiver

from core.images import delete_file_quietly, process_image

from .models import ApartmentImage


@transaction.atomic
def add_images(apartment, uploads, *, uploaded_by=None, caption=""):
    """Process and attach uploaded images. The first image of a listing becomes primary."""
    has_primary = apartment.images.filter(is_primary=True).exists()
    next_order = (apartment.images.aggregate(m=Max("sort_order"))["m"] or 0) + 1
    created = []
    try:
        for offset, upload in enumerate(uploads):
            processed, _ = process_image(upload)
            image = ApartmentImage(
                apartment=apartment,
                caption=caption,
                is_primary=not has_primary and offset == 0,
                sort_order=next_order + offset,
                file_size=processed.size,
                uploaded_by=uploaded_by,
            )
            image.image.save(processed.name, processed, save=False)
            image.save()
            created.append(image)
    except Exception:
        # The DB rows roll back with the transaction; remove already-stored files too.
        for image in created:
            delete_file_quietly(image.image.storage, image.image.name)
        raise
    return created


@transaction.atomic
def set_primary_image(image):
    ApartmentImage.objects.filter(apartment_id=image.apartment_id, is_primary=True).exclude(pk=image.pk).update(is_primary=False)
    if not image.is_primary:
        image.is_primary = True
        image.save(update_fields=["is_primary"])


@transaction.atomic
def delete_image(image):
    """Delete an image (file removal happens via signal) and promote a new primary if needed."""
    apartment_id, was_primary = image.apartment_id, image.is_primary
    image.delete()
    if was_primary:
        replacement = ApartmentImage.objects.filter(apartment_id=apartment_id).order_by("sort_order", "id").first()
        if replacement:
            set_primary_image(replacement)


def replace_image(image, upload):
    """Swap the file behind an existing image record, keeping caption/order/primary flag."""
    processed, _ = process_image(upload)
    old_name = image.image.name
    image.image.save(processed.name, processed, save=False)
    image.file_size = processed.size
    image.save()
    delete_file_quietly(image.image.storage, old_name)
    return image


@receiver(post_delete, sender=ApartmentImage)
def _remove_image_file(sender, instance, **kwargs):
    # Runs for single deletes and for cascades when an apartment is deleted.
    name, storage = instance.image.name, instance.image.storage
    transaction.on_commit(lambda: delete_file_quietly(storage, name))
