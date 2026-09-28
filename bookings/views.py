from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apartments.models import Apartment

from . import services
from .forms import BookingForm, LandlordResponseForm
from .models import Booking


def _back(request, fallback):
    target = request.POST.get("next")
    if target and url_has_allowed_host_and_scheme(target, {request.get_host()}, request.is_secure()):
        return redirect(target)
    return redirect(fallback)


@login_required
def book_view(request, slug):
    services.expire_stale_bookings()
    apartment = get_object_or_404(Apartment.objects.select_related("property_type", "owner"), slug=slug)
    if not apartment.is_published:
        return redirect(apartment.get_absolute_url())

    existing = Booking.objects.filter(apartment=apartment, tenant=request.user).open().first()
    if existing:
        messages.info(request, "You already have an active booking for this apartment.")
        return redirect("bookings:my_bookings")
    if apartment.owner_id == request.user.pk:
        messages.info(request, "This is your own listing.")
        return redirect(apartment.get_absolute_url())
    if not apartment.is_bookable:
        messages.warning(request, "Sorry, this apartment is already booked. Try a similar one below.")
        return redirect(apartment.get_absolute_url())

    user = request.user
    form = BookingForm(
        request.POST or None, apartment=apartment,
        initial={"full_name": user.full_name, "email": user.email, "phone": user.phone},
    )
    if request.method == "POST" and form.is_valid():
        try:
            details = {k: v for k, v in form.cleaned_data.items() if k != "agree"}
            services.create_booking(apartment, user, details)
        except services.BookingError as exc:
            messages.error(request, str(exc))
            return redirect(apartment.get_absolute_url())
        messages.success(request, "Booking request sent! The apartment is on hold for you while the landlord responds.")
        return redirect("bookings:my_bookings")

    cover = apartment.cover_image
    return render(request, "bookings/book.html", {"apartment": apartment, "form": form, "cover": cover})


@login_required
def my_bookings_view(request):
    services.expire_stale_bookings()
    bookings = (
        Booking.objects.filter(tenant=request.user)
        .select_related("apartment", "apartment__property_type", "apartment__owner")
        .prefetch_related("apartment__images")
    )
    return render(request, "bookings/my_bookings.html", {"bookings": bookings})


@login_required
@require_POST
def cancel_booking_view(request, pk):
    booking = get_object_or_404(Booking, pk=pk, tenant=request.user)
    try:
        services.cancel_booking(booking, request.user)
    except services.BookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Your booking was cancelled and the apartment is available again.")
    return redirect("bookings:my_bookings")


@login_required
def landlord_requests_view(request):
    """Booking requests for apartments the user owns."""
    services.expire_stale_bookings()
    queryset = (
        Booking.objects.filter(apartment__owner=request.user)
        .select_related("apartment", "tenant").prefetch_related("apartment__images")
    )
    status = request.GET.get("status", "")
    if status in Booking.Status.values:
        queryset = queryset.filter(status=status)
    counts = {s: Booking.objects.filter(apartment__owner=request.user, status=s).count() for s in ("pending", "accepted")}
    page = Paginator(queryset, 15).get_page(request.GET.get("page"))
    context = {
        "page_obj": page, "status": status, "counts": counts,
        "status_choices": Booking.Status.choices, "response_form": LandlordResponseForm(),
        "has_listings": Apartment.objects.filter(owner=request.user).exists(),
    }
    return render(request, "bookings/landlord_requests.html", context)


@login_required
@require_POST
def respond_view(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("apartment"), pk=pk)
    if not booking.can_be_managed_by(request.user):
        return render(request, "errors/403.html", status=403)
    form = LandlordResponseForm(request.POST)
    fallback = "bookings:landlord_requests"
    if not form.is_valid():
        messages.error(request, "Invalid action.")
        return _back(request, fallback)
    try:
        if form.cleaned_data["action"] == "accept":
            services.accept_booking(booking, request.user, form.cleaned_data["note"])
            messages.success(request, f"Booking accepted. {booking.full_name} can now see your contact details.")
        else:
            services.decline_booking(booking, request.user, form.cleaned_data["note"])
            messages.info(request, "Booking declined. The apartment is available for others again.")
    except services.BookingError as exc:
        messages.error(request, str(exc))
    return _back(request, fallback)


@login_required
@require_POST
def complete_view(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("apartment"), pk=pk)
    if not booking.can_be_managed_by(request.user):
        return render(request, "errors/403.html", status=403)
    relist = request.POST.get("relist") == "1"
    try:
        services.complete_booking(booking, request.user, relist=relist)
    except services.BookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Listing is available for booking again." if relist else "Marked as rented.")
    return _back(request, "bookings:landlord_requests")
