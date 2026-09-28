"""
Glue between Supabase auth sessions and Django's session framework.

After Supabase verifies a user we log them into a normal Django session. The
Supabase tokens are kept in the server-side session store (never in a readable
cookie) so the session can be refreshed or revoked later.
"""

import time
from dataclasses import asdict

from django.contrib.auth import authenticate, login, logout

from core.supabase.client import AuthSession, SupabaseAuthClient, SupabaseAuthError, full_name_from_user

SESSION_TOKENS_KEY = "supabase_auth"
# Refresh slightly before expiry to avoid racing the token's lifetime.
EXPIRY_LEEWAY_SECONDS = 60


class AccountDisabledError(SupabaseAuthError):
    default_message = "This account has been disabled. Please contact support."


def get_auth_client():
    return SupabaseAuthClient()


def store_tokens(request, auth_session):
    request.session[SESSION_TOKENS_KEY] = asdict(auth_session)


def get_stored_session(request):
    data = request.session.get(SESSION_TOKENS_KEY)
    if not data:
        return None
    try:
        return AuthSession(**data)
    except TypeError:
        return None


def token_needs_refresh(auth_session):
    return time.time() >= auth_session.expires_at - EXPIRY_LEEWAY_SECONDS


def start_session(request, auth_session, full_name=""):
    """Log the Supabase-verified user into Django. Raises AccountDisabledError."""
    user = authenticate(request, auth_session=auth_session, full_name=full_name)
    if user is None:
        raise AccountDisabledError(code="user_disabled")
    login(request, user)  # rotates the session key (session fixation protection)
    store_tokens(request, auth_session)
    return user


def session_from_access_token(access_token, refresh_token, expires_at=None, client=None):
    """Build an AuthSession from browser-supplied tokens after verifying them with Supabase."""
    client = client or get_auth_client()
    user = client.get_user(access_token)
    now = int(time.time())
    # Never trust a client-supplied expiry beyond Supabase's default 1h lifetime.
    try:
        expires_at = min(int(expires_at), now + 3600) if expires_at else now + 3600
    except (TypeError, ValueError):
        expires_at = now + 3600
    return AuthSession(
        access_token=access_token,
        refresh_token=refresh_token or "",
        expires_at=expires_at,
        user_id=user.get("id", ""),
        email=(user.get("email") or "").lower(),
        email_confirmed=bool(user.get("email_confirmed_at")),
    ), full_name_from_user(user)


def end_session(request):
    auth_session = get_stored_session(request)
    if auth_session:
        get_auth_client().sign_out(auth_session.access_token)
    logout(request)  # flushes the session, including stored tokens
