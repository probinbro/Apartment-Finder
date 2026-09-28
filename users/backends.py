from django.contrib.auth.backends import BaseBackend

from .models import User


def sync_user_from_supabase(auth_user_id, email, full_name=""):
    """
    Get or create the local profile for a verified Supabase user.

    Only identity fields come from Supabase. The role is never read from the
    auth payload (user_metadata is user-editable), so it cannot be escalated
    from the client side.
    """
    email = (email or "").lower()
    user = User.objects.filter(auth_user_id=auth_user_id).first()
    if user is None and email:
        # Link a profile pre-created by email (e.g. by an admin), or one whose
        # Supabase account was deleted and re-created. Supabase guarantees email
        # uniqueness, so the old auth user no longer exists in that case.
        user = User.objects.filter(email=email).first()
        if user is not None:
            user.auth_user_id = auth_user_id
            user.save(update_fields=["auth_user_id", "updated_at"])
    if user is None:
        return User.objects.create_user(email=email, auth_user_id=auth_user_id, full_name=full_name[:150])

    if email and user.email != email:
        user.email = email
        user.save(update_fields=["email", "updated_at"])
    return user


class SupabaseAuthBackend(BaseBackend):
    """
    Authenticates a request from an AuthSession that has already been issued
    or verified by Supabase (see users.services). Never checks passwords itself.
    """

    def authenticate(self, request, auth_session=None, full_name="", **kwargs):
        if auth_session is None or not auth_session.user_id:
            return None
        user = sync_user_from_supabase(auth_session.user_id, auth_session.email, full_name)
        return user if user.is_active else None

    def get_user(self, user_id):
        # Returning None for inactive users logs them out on their next request.
        return User.objects.filter(pk=user_id, is_active=True).first()
