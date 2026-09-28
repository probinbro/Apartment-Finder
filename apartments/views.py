from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .filters import ApartmentSearchForm, apply_filters
from .models import Apartment

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
    context = {
        "apartment": apartment,
        "images": images,
        "gallery_data": [{"url": image.image.url, "caption": image.caption} for image in images],
        "similar": similar,
    }
    return render(request, "apartments/detail.html", context)
