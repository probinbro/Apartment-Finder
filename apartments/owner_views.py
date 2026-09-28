"""
"List your home": registered users submit their own property, which stays
hidden in `pending` status until an admin approves it in the admin panel.
Every query here is scoped to `owner=request.user`, so users can only ever see
or change their own submissions.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.supabase.client import SupabaseError

from . import services
from .forms import ListingSubmissionForm
from .models import Apartment

logger = logging.getLogger(__name__)

# Guards against spam: a user can't have more than this many listings awaiting review.
MAX_PENDING_PER_USER = 5


def _own_listing_or_404(request, pk):
    return get_object_or_404(Apartment, pk=pk, owner=request.user)


def _save_submission(request, form, apartment_is_new):
    """Save the listing as pending review, plus any uploaded photos, atomically."""
    with transaction.atomic():
        apartment = form.save(commit=False)
        apartment.owner = request.user
        apartment.status = Apartment.Status.PENDING
        apartment.submitted_by_user = True
        apartment.is_featured = False if apartment_is_new else apartment.is_featured
        apartment.save()
        form.save_m2m()
        photos = form.cleaned_data.get("photos") or []
        if photos:
            services.add_images(apartment, photos, uploaded_by=request.user)
    return apartment


@login_required
def submit_listing_view(request):
    pending = Apartment.objects.filter(owner=request.user, status=Apartment.Status.PENDING).count()
    limit_reached = pending >= MAX_PENDING_PER_USER

    initial = {"contact_name": request.user.full_name, "contact_email": request.user.email, "contact_phone": request.user.phone}
    form = ListingSubmissionForm(request.POST or None, request.FILES or None, initial=initial)

    if request.method == "POST" and not limit_reached:
        if form.is_valid():
            try:
                apartment = _save_submission(request, form, apartment_is_new=True)
            except ValidationError as exc:
                form.add_error("photos", exc)
            except SupabaseError:
                logger.exception("Photo upload failed for a listing submission")
                messages.error(request, "We couldn't upload your photos right now. Please try again.")
            else:
                messages.success(request, f"Thanks! “{apartment.title}” was submitted and is waiting for review.")
                return redirect("apartments:my_listings")
        if form.errors:
            messages.error(request, "Please correct the errors below.")

    return render(request, "apartments/submit.html", {"form": form, "limit_reached": limit_reached, "max_pending": MAX_PENDING_PER_USER})


@login_required
def my_listings_view(request):
    listings = Apartment.objects.filter(owner=request.user).with_cover().order_by("-created_at")
    return render(request, "apartments/my_listings.html", {"listings": listings})


@login_required
def edit_listing_view(request, pk):
    apartment = _own_listing_or_404(request, pk)
    if not apartment.owner_can_edit:
        messages.info(request, "Published listings can't be edited directly. Contact us if something needs changing.")
        return redirect("apartments:my_listings")

    form = ListingSubmissionForm(request.POST or None, request.FILES or None, instance=apartment, require_photos=False)
    if request.method == "POST":
        if form.is_valid():
            try:
                _save_submission(request, form, apartment_is_new=False)
            except ValidationError as exc:
                form.add_error("photos", exc)
            except SupabaseError:
                logger.exception("Photo upload failed for listing %s", apartment.pk)
                messages.error(request, "We couldn't upload your photos right now. Please try again.")
            else:
                messages.success(request, "Your changes were saved and the listing was sent for review again.")
                return redirect("apartments:my_listings")
        if form.errors:
            messages.error(request, "Please correct the errors below.")

    return render(request, "apartments/submit.html", {"form": form, "apartment": apartment, "images": apartment.images.all()})


@login_required
@require_POST
def delete_listing_view(request, pk):
    apartment = _own_listing_or_404(request, pk)
    title = apartment.title
    apartment.delete()
    messages.success(request, f"“{title}” was removed.")
    return redirect("apartments:my_listings")


@login_required
@require_POST
def delete_listing_photo_view(request, pk, image_pk):
    apartment = _own_listing_or_404(request, pk)
    if apartment.owner_can_edit:
        image = get_object_or_404(apartment.images, pk=image_pk)
        services.delete_image(image)
        messages.success(request, "Photo removed.")
    return redirect("apartments:edit_listing", pk=apartment.pk)
