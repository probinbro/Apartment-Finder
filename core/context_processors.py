from django.conf import settings


def site(request):
    """Values available in every template. Only non-secret settings belong here."""
    return {
        "SITE_NAME": settings.SITE_NAME,
        "CURRENCY_SYMBOL": settings.CURRENCY_SYMBOL,
        "OAUTH_PROVIDERS": settings.SUPABASE_OAUTH_PROVIDERS,
        "BOOKING_HOLD_DAYS": settings.BOOKING_HOLD_DAYS,
    }


def user_badges(request):
    """Per-user data for navigation badges and heart icons, evaluated lazily."""
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {}
    from django.utils.functional import SimpleLazyObject

    from apartments.models import SavedApartment
    from bookings.models import Booking

    return {
        "saved_ids": SimpleLazyObject(lambda: set(SavedApartment.objects.filter(user=user).values_list("apartment_id", flat=True))),
        "landlord_pending_count": SimpleLazyObject(
            lambda: Booking.objects.filter(apartment__owner=user, status=Booking.Status.PENDING).count()
        ),
    }


def admin_badges(request):
    """Counts shown in the admin sidebar. Only queried for admins."""
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated and user.is_admin):
        return {}
    from apartments.models import Apartment

    from bookings.models import Booking

    return {
        "pending_request_count": Apartment.objects.filter(status=Apartment.Status.PENDING).count(),
        "pending_booking_count": Booking.objects.filter(status=Booking.Status.PENDING).count(),
    }
