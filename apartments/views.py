from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .filters import ApartmentSearchForm, apply_filters
from .models import Apartment, SavedApartment

PAGE_SIZE = 12


def apartment_list_view(request):
    """Browse and search published listings. Also serves as the search results page."""
    form = ApartmentSearchForm(request.GET or None)
    queryset = Apartment.objects.published().with_cover()

    is_search = bool(request.GET)
    if form.is_bound:
        form.is_valid()  # populate cleaned_data; invalid fields are simply ignored
        queryset = apply_filters(queryset, form.cleaned_data)
    else:
        queryset = apply_filters(queryset, {})

    page = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))
    context = {
        "form": form,
        "page_obj": page,
        "apartments": page.object_list,
        "is_search": is_search,
        "cities": Apartment.objects.published().order_by("city").values_list("city", flat=True).distinct(),
    }
    return render(request, "apartments/list.html", context)


def apartment_detail_view(request, slug):
    apartment = get_object_or_404(
        Apartment.objects.select_related("property_type", "owner").prefetch_related("images", "amenities"), slug=slug
    )
    # Unpublished listings are visible only to admins and to their owner (as a preview).
    if not apartment.can_be_viewed_by(request.user):
        raise Http404("Apartment not found")

    similar = (
        Apartment.objects.published().with_cover()
        .filter(city__iexact=apartment.city).exclude(pk=apartment.pk)[:3]
    )
    images = list(apartment.images.all())
    my_booking = None
    if request.user.is_authenticated:
        from bookings.models import Booking

        my_booking = Booking.objects.filter(apartment=apartment, tenant=request.user).order_by("-created_at").first()
    is_owner = request.user.is_authenticated and apartment.owner_id == request.user.pk
    # Phone/email are only revealed once the landlord has accepted the renter's booking.
    show_contact = is_owner or (request.user.is_authenticated and request.user.is_admin) or (
        my_booking is not None and my_booking.status == my_booking.Status.ACCEPTED
    )
    context = {
        "apartment": apartment,
        "my_booking": my_booking,
        "is_owner": is_owner,
        "show_contact": show_contact,
        "images": images,
        "gallery_data": [{"url": image.image.url, "caption": image.caption} for image in images],
        "similar": similar,
    }
    return render(request, "apartments/detail.html", context)


@login_required
@require_POST
def toggle_save_view(request, slug):
    apartment = get_object_or_404(Apartment.objects.published(), slug=slug)
    saved, created = SavedApartment.objects.get_or_create(user=request.user, apartment=apartment)
    if not created:
        saved.delete()
    is_saved = created
    if request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"saved": is_saved})
    target = request.POST.get("next")
    if target and url_has_allowed_host_and_scheme(target, {request.get_host()}, request.is_secure()):
        return redirect(target)
    return redirect(apartment.get_absolute_url())
