"""
Thin server-side client for the Supabase REST APIs (Auth + Storage).

We talk to Supabase over HTTPS with `requests` rather than pulling in the full
SDK: the surface we need is small, and keeping it explicit makes it easy to
mock in tests and to see exactly which key each call uses.

Key usage rules:
  * The anon key is used for end-user auth calls (sign up / sign in / refresh).
  * The service-role key is only used server-side for Storage and admin tasks.
    It is never rendered into templates or sent to the browser.
"""

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class SupabaseError(Exception):
    """Base error. `user_message` is always safe to show to end users."""

    default_message = "Something went wrong while contacting the authentication service."

    def __init__(self, user_message=None, *, code=None, status=None):
        self.user_message = user_message or self.default_message
        self.code = code
        self.status = status
        super().__init__(f"{self.user_message} (code={code}, status={status})")


class SupabaseConfigError(SupabaseError):
    default_message = "Authentication is not configured on this server. Please contact the site administrator."


class SupabaseAuthError(SupabaseError):
    default_message = "Authentication failed. Please try again."


class SupabaseServiceError(SupabaseError):
    default_message = "The authentication service is temporarily unavailable. Please try again shortly."


# Maps Supabase (GoTrue) error codes to friendly, non-leaky messages.
AUTH_ERROR_MESSAGES = {
    "invalid_credentials": "Invalid email or password.",
    "invalid_grant": "Invalid email or password.",
    "email_not_confirmed": "Please confirm your email address before logging in. Check your inbox for the link.",
    "user_already_exists": "An account with this email already exists. Try logging in instead.",
    "email_exists": "An account with this email already exists. Try logging in instead.",
    "weak_password": "That password is too weak. Use at least 8 characters with a mix of letters and numbers.",
    "signup_disabled": "New registrations are currently disabled.",
    "email_address_invalid": "Please enter a valid email address.",
    "validation_failed": "Please check the details you entered and try again.",
    "over_request_rate_limit": "Too many attempts. Please wait a minute and try again.",
    "over_email_send_rate_limit": "Too many emails sent. Please wait a few minutes and try again.",
    "refresh_token_not_found": "Your session has expired. Please log in again.",
    "refresh_token_already_used": "Your session has expired. Please log in again.",
    "session_not_found": "Your session has expired. Please log in again.",
    "bad_jwt": "Your session has expired. Please log in again.",
    "user_banned": "This account has been disabled. Please contact support.",
    "flow_state_not_found": "Your sign-in link expired. Please try again.",
    "flow_state_expired": "Your sign-in link expired. Please try again.",
    "bad_code_verifier": "Sign-in could not be verified. Please try again.",
    "provider_disabled": "That sign-in method is not enabled. Please use email and password.",
    "validation_failed_provider": "That sign-in method is not enabled. Please use email and password.",
}


def full_name_from_user(user):
    """Best-effort display name from Supabase user metadata (email signup or OAuth)."""
    metadata = (user or {}).get("user_metadata") or {}
    return (metadata.get("full_name") or metadata.get("name") or "").strip()


def generate_pkce_pair():
    """Return (code_verifier, code_challenge) for the OAuth PKCE flow (RFC 7636, S256)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


@dataclass(frozen=True)
class AuthSession:
    access_token: str
    refresh_token: str
    expires_at: int
    user_id: str
    email: str
    email_confirmed: bool = True

    @property
    def is_expired(self):
        return time.time() >= self.expires_at

    @classmethod
    def from_payload(cls, payload):
        user = payload.get("user") or {}
        expires_at = payload.get("expires_at") or int(time.time()) + int(payload.get("expires_in", 3600))
        return cls(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token", ""),
            expires_at=int(expires_at),
            user_id=user.get("id", ""),
            email=(user.get("email") or "").lower(),
            email_confirmed=bool(user.get("email_confirmed_at") or user.get("confirmed_at")),
        )


@dataclass(frozen=True)
class SignUpResult:
    user_id: str
    email: str
    session: AuthSession | None  # None when email confirmation is required

    @property
    def requires_confirmation(self):
        return self.session is None


class _BaseClient:
    def __init__(self, url=None, timeout=None):
        self.url = (url if url is not None else settings.SUPABASE_URL).rstrip("/")
        self.timeout = timeout or settings.SUPABASE_TIMEOUT_SECONDS

    def _request(self, method, path, *, key, bearer=None, error_cls=SupabaseAuthError, **kwargs):
        if not self.url or not key:
            raise SupabaseConfigError(code="missing_config")
        headers = {"apikey": key}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        elif not key.startswith("sb_"):
            # Legacy JWT-style keys must also be sent as a bearer token. New
            # sb_publishable_/sb_secret_ keys are sent in the apikey header only.
            headers["Authorization"] = f"Bearer {key}"
        headers.update(kwargs.pop("headers", {}))
        try:
            response = requests.request(method, f"{self.url}{path}", headers=headers, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            logger.warning("Supabase request %s %s failed: %s", method, path, exc)
            raise SupabaseServiceError(code="network_error") from exc

        if response.status_code >= 500:
            logger.error("Supabase %s %s returned %s", method, path, response.status_code)
            raise SupabaseServiceError(status=response.status_code)
        if response.status_code >= 400:
            raise self._error_from_response(response, error_cls)
        return response

    @staticmethod
    def _error_from_response(response, error_cls):
        try:
            body = response.json()
        except ValueError:
            body = {}
        code = body.get("error_code") or body.get("code") or body.get("error")
        if response.status_code == 429:
            code = code or "over_request_rate_limit"
        message = AUTH_ERROR_MESSAGES.get(str(code)) if code else None
        logger.debug("Supabase error status=%s code=%s", response.status_code, code)
        return error_cls(message, code=code, status=response.status_code)


class SupabaseAuthClient(_BaseClient):
    """End-user authentication using the public anon key."""

    def __init__(self, url=None, anon_key=None, timeout=None):
        super().__init__(url, timeout)
        self.anon_key = anon_key if anon_key is not None else settings.SUPABASE_ANON_KEY

    def _auth(self, method, path, **kwargs):
        return self._request(method, f"/auth/v1{path}", key=self.anon_key, **kwargs)

    def sign_up(self, email, password, *, full_name="", redirect_to=None):
        params = {"redirect_to": redirect_to} if redirect_to else None
        payload = {"email": email, "password": password, "data": {"full_name": full_name}}
        body = self._auth("POST", "/signup", json=payload, params=params).json()

        # With email confirmation on, Supabase returns the user without a session.
        if body.get("access_token"):
            session = AuthSession.from_payload(body)
            return SignUpResult(user_id=session.user_id, email=session.email, session=session)
        user = body.get("user") or body
        return SignUpResult(user_id=user.get("id", ""), email=(user.get("email") or email).lower(), session=None)

    def sign_in_with_password(self, email, password):
        body = self._auth("POST", "/token", params={"grant_type": "password"}, json={"email": email, "password": password}).json()
        return AuthSession.from_payload(body)

    def refresh_session(self, refresh_token):
        body = self._auth("POST", "/token", params={"grant_type": "refresh_token"}, json={"refresh_token": refresh_token}).json()
        return AuthSession.from_payload(body)

    def oauth_authorize_url(self, provider, redirect_to, code_challenge):
        """URL that starts a social login; Supabase redirects back to `redirect_to?code=...`."""
        if not self.url or not self.anon_key:
            raise SupabaseConfigError(code="missing_config")
        query = urlencode({
            "provider": provider,
            "redirect_to": redirect_to,
            "code_challenge": code_challenge,
            "code_challenge_method": "s256",
        })
        return f"{self.url}/auth/v1/authorize?{query}"

    def exchange_code_for_session(self, auth_code, code_verifier):
        """Complete the PKCE flow server-side. Returns (AuthSession, raw user payload)."""
        body = self._auth(
            "POST", "/token", params={"grant_type": "pkce"},
            json={"auth_code": auth_code, "code_verifier": code_verifier},
        ).json()
        return AuthSession.from_payload(body), body.get("user") or {}

    def get_user(self, access_token):
        """Validate an access token with Supabase and return the auth user payload."""
        return self._auth("GET", "/user", bearer=access_token).json()

    def sign_out(self, access_token):
        """Revoke the refresh token server-side. Best effort: failures are logged only."""
        try:
            self._auth("POST", "/logout", bearer=access_token)
        except SupabaseError as exc:
            logger.info("Supabase sign-out failed (ignored): %s", exc)


class SupabaseAdminClient(_BaseClient):
    """Privileged server-side operations. Uses the service-role key."""

    def __init__(self, url=None, service_key=None, timeout=None):
        super().__init__(url, timeout)
        self.service_key = service_key if service_key is not None else settings.SUPABASE_SERVICE_ROLE_KEY

    def request(self, method, path, **kwargs):
        kwargs.setdefault("error_cls", SupabaseServiceError)
        return self._request(method, path, key=self.service_key, **kwargs)

    def set_user_banned(self, auth_user_id, banned):
        """Ban/unban a user in Supabase Auth so they cannot obtain new tokens."""
        duration = "876000h" if banned else "none"
        self.request("PUT", f"/auth/v1/admin/users/{auth_user_id}", json={"ban_duration": duration})


def is_auth_configured():
    return bool(settings.SUPABASE_URL and settings.SUPABASE_ANON_KEY)


def is_admin_configured():
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)
