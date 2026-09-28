import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apartments.models import Apartment
from core.supabase.client import SupabaseError, full_name_from_user, generate_pkce_pair

from . import services
from .forms import LoginForm, ProfileForm, RegisterForm

logger = logging.getLogger(__name__)


def _safe_next_url(request, fallback="users:dashboard"):
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(candidate, {request.get_host()}, request.is_secure()):
        return candidate
    return reverse(fallback)


def login_view(request):
    if request.user.is_authenticated:
        return redirect("users:dashboard")

    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            auth_session = services.get_auth_client().sign_in_with_password(
                form.cleaned_data["email"], form.cleaned_data["password"]
            )
            user = services.start_session(request, auth_session)
        except SupabaseError as exc:
            form.add_error(None, exc.user_message)
        else:
            messages.success(request, f"Welcome back, {user.display_name}!")
            return redirect(_safe_next_url(request))

    return render(request, "users/login.html", {"form": form, "next": request.GET.get("next", "")})


def register_view(request):
    if request.user.is_authenticated:
        return redirect("users:dashboard")

    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            result = services.get_auth_client().sign_up(
                data["email"],
                data["password"],
                full_name=data["full_name"],
                redirect_to=settings.SITE_URL + reverse("users:auth_callback"),
            )
            if result.requires_confirmation:
                return render(request, "users/check_email.html", {"email": data["email"]})
            user = services.start_session(request, result.session, full_name=data["full_name"])
        except SupabaseError as exc:
            form.add_error(None, exc.user_message)
        else:
            messages.success(request, f"Welcome to {settings.SITE_NAME}, {user.display_name}!")
            return redirect("users:dashboard")

    return render(request, "users/register.html", {"form": form})


@require_POST
def logout_view(request):
    services.end_session(request)
    messages.info(request, "You have been logged out.")
    return redirect(settings.LOGOUT_REDIRECT_URL)


OAUTH_SESSION_KEY = "supabase_oauth"


def oauth_start_view(request, provider):
    """Begin social login (e.g. Google) via Supabase using PKCE."""
    if provider not in settings.SUPABASE_OAUTH_PROVIDERS:
        raise Http404("Unknown sign-in provider")
    verifier, challenge = generate_pkce_pair()
    # The verifier stays server-side, so an intercepted `code` is useless on its own.
    request.session[OAUTH_SESSION_KEY] = {"verifier": verifier, "next": _safe_next_url(request)}
    try:
        url = services.get_auth_client().oauth_authorize_url(
            provider, settings.SITE_URL + reverse("users:auth_callback"), challenge
        )
    except SupabaseError as exc:
        messages.error(request, exc.user_message)
        return redirect("users:login")
    return redirect(url)


def auth_callback_view(request):
    """
    Where Supabase sends users back to.

    * Social login (PKCE): `?code=...` — exchanged for a session server-side.
    * Email confirmation links: tokens arrive in the URL fragment, which only
      the browser can read, so the template's script posts them back to us.
    """
    if request.GET.get("error"):
        messages.error(request, "Sign-in was cancelled or failed. Please try again.")
        return redirect("users:login")

    code = request.GET.get("code")
    if not code:
        return render(request, "users/auth_callback.html")

    oauth_state = request.session.pop(OAUTH_SESSION_KEY, None)
    if not oauth_state:
        messages.error(request, "Your sign-in session expired. Please try again.")
        return redirect("users:login")
    try:
        auth_session, auth_user = services.get_auth_client().exchange_code_for_session(code, oauth_state["verifier"])
        user = services.start_session(request, auth_session, full_name=full_name_from_user(auth_user))
    except SupabaseError as exc:
        messages.error(request, exc.user_message)
        return redirect("users:login")

    messages.success(request, f"Welcome, {user.display_name}!")
    next_url = oauth_state.get("next") or reverse("users:dashboard")
    return redirect(next_url if url_has_allowed_host_and_scheme(next_url, {request.get_host()}) else "users:dashboard")


@require_POST
def auth_session_view(request):
    """Exchange browser-held Supabase tokens (from the callback) for a Django session."""
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "Invalid request."}, status=400)

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        return JsonResponse({"error": "Missing access token."}, status=400)

    try:
        auth_session, full_name = services.session_from_access_token(
            access_token, payload.get("refresh_token"), payload.get("expires_at")
        )
        services.start_session(request, auth_session, full_name=full_name)
    except SupabaseError as exc:
        return JsonResponse({"error": exc.user_message}, status=401)

    messages.success(request, "Your email is confirmed and you are now logged in.")
    return JsonResponse({"redirect": reverse("users:dashboard")})


@login_required
def dashboard_view(request):
    from bookings.models import Booking

    context = {
        "open_booking_count": Booking.objects.filter(tenant=request.user).open().count(),
        "recent_apartments": Apartment.objects.published().with_cover()[:3],
        "published_count": Apartment.objects.published().count(),
    }
    return render(request, "users/dashboard.html", context)


@login_required
def profile_view(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST":
        if form.is_valid():
            try:
                form.save()
            except SupabaseError as exc:
                messages.error(request, exc.user_message)
            except Exception:
                logger.exception("Failed to save profile for user %s", request.user.pk)
                messages.error(request, "We couldn't save your profile right now. Please try again.")
            else:
                messages.success(request, "Your profile has been updated.")
                return redirect("users:profile")
        else:
            messages.error(request, "Please correct the errors below.")
    return render(request, "users/profile.html", {"form": form})


@login_required
def saved_apartments_view(request):
    apartments = Apartment.objects.published().with_cover().filter(saved_by__user=request.user).order_by("-saved_by__created_at")
    return render(request, "users/saved.html", {"apartments": apartments})
