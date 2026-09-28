from django.conf import settings


def site(request):
    """Values available in every template. Only non-secret settings belong here."""
    return {
        "SITE_NAME": settings.SITE_NAME,
        "CURRENCY_SYMBOL": settings.CURRENCY_SYMBOL,
        "OAUTH_PROVIDERS": settings.SUPABASE_OAUTH_PROVIDERS,
    }


def admin_badges(request):
    """Counts shown in the admin sidebar. Only queried for admins."""
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated and user.is_admin):
        return {}
    from apartments.models import Apartment

    return {"pending_request_count": Apartment.objects.filter(status=Apartment.Status.PENDING).count()}
