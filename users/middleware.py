import logging

from django.contrib import messages
from django.contrib.auth import logout

from core.supabase.client import SupabaseAuthError, SupabaseConfigError, SupabaseServiceError

from . import services

logger = logging.getLogger(__name__)


class SupabaseSessionMiddleware:
    """
    Keeps the Django session in step with the user's Supabase session.

    When the Supabase access token expires we refresh it with the stored
    refresh token. If Supabase rejects the refresh (revoked, expired, user
    banned) the user is logged out with a friendly message. Temporary outages
    do not log anyone out; the refresh is retried on the next request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            self._ensure_fresh_session(request)
        return self.get_response(request)

    def _ensure_fresh_session(self, request):
        auth_session = services.get_stored_session(request)
        if auth_session is None or not services.token_needs_refresh(auth_session):
            return
        try:
            refreshed = services.get_auth_client().refresh_session(auth_session.refresh_token)
        except (SupabaseServiceError, SupabaseConfigError) as exc:
            logger.warning("Could not refresh Supabase session: %s", exc)
            return
        except SupabaseAuthError:
            self._expire(request)
            return

        if str(refreshed.user_id) != str(request.user.auth_user_id):
            logger.warning("Refreshed Supabase session belongs to a different user; logging out.")
            self._expire(request)
            return
        services.store_tokens(request, refreshed)

    @staticmethod
    def _expire(request):
        logout(request)
        messages.warning(request, "Your session has expired. Please log in again.")
