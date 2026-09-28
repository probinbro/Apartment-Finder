import time
import uuid
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user
from django.test import TestCase
from django.urls import reverse

from core.supabase.client import SupabaseAuthError, SupabaseServiceError, SignUpResult
from users import services
from users.models import User

from .helpers import fake_session, make_user, mock_auth_client


class LoginTests(TestCase):
    url = reverse("users:login")

    def test_login_page_renders_with_google_button(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Continue with Google")

    def test_successful_login_creates_profile_and_session(self):
        with mock_auth_client() as get_client:
            get_client.return_value.sign_in_with_password.return_value = fake_session(email="new@example.com")
            response = self.client.post(self.url, {"email": "New@Example.com", "password": "secret123"})

        self.assertRedirects(response, reverse("users:dashboard"))
        user = User.objects.get(email="new@example.com")
        self.assertEqual(user.role, User.Role.USER)
        self.assertFalse(user.has_usable_password())  # no password stored locally
        self.assertIn(services.SESSION_TOKENS_KEY, self.client.session)

    def test_invalid_credentials_show_friendly_error(self):
        with mock_auth_client() as get_client:
            get_client.return_value.sign_in_with_password.side_effect = SupabaseAuthError(
                "Invalid email or password.", code="invalid_credentials", status=400
            )
            response = self.client.post(self.url, {"email": "a@example.com", "password": "wrong"})
        self.assertContains(response, "Invalid email or password.")
        self.assertFalse(get_user(self.client).is_authenticated)

    def test_service_outage_is_reported_without_details(self):
        with mock_auth_client() as get_client:
            get_client.return_value.sign_in_with_password.side_effect = SupabaseServiceError(status=503)
            response = self.client.post(self.url, {"email": "a@example.com", "password": "x"})
        self.assertContains(response, "temporarily unavailable")

    def test_disabled_account_cannot_log_in(self):
        user = make_user(is_active=False)
        with mock_auth_client() as get_client:
            get_client.return_value.sign_in_with_password.return_value = fake_session(user.auth_user_id, user.email)
            response = self.client.post(self.url, {"email": user.email, "password": "secret123"})
        self.assertContains(response, "disabled")
        self.assertFalse(get_user(self.client).is_authenticated)

    def test_next_parameter_is_respected_but_external_urls_are_not(self):
        with mock_auth_client() as get_client:
            get_client.return_value.sign_in_with_password.return_value = fake_session()
            response = self.client.post(self.url + "?next=/account/profile/", {"email": "a@example.com", "password": "x"})
            self.assertRedirects(response, reverse("users:profile"))
        self.client.logout()
        with mock_auth_client() as get_client:
            get_client.return_value.sign_in_with_password.return_value = fake_session()
            response = self.client.post(self.url + "?next=https://evil.example/", {"email": "b@example.com", "password": "x"})
            self.assertRedirects(response, reverse("users:dashboard"))

    def test_recreated_supabase_account_relinks_existing_profile(self):
        user = make_user("same@example.com", full_name="Keep Me")
        with mock_auth_client() as get_client:
            get_client.return_value.sign_in_with_password.return_value = fake_session(email="same@example.com")
            self.client.post(self.url, {"email": "same@example.com", "password": "x"})
        self.assertEqual(User.objects.filter(email="same@example.com").count(), 1)
        self.assertEqual(get_user(self.client).pk, user.pk)

    def test_role_is_never_taken_from_supabase_metadata(self):
        """A user who sets role=admin in their own Supabase metadata stays a normal user."""
        with mock_auth_client() as get_client:
            get_client.return_value.sign_in_with_password.return_value = fake_session(email="sneaky@example.com")
            self.client.post(self.url, {"email": "sneaky@example.com", "password": "x", "role": "admin"})
        self.assertEqual(User.objects.get(email="sneaky@example.com").role, User.Role.USER)


class RegisterTests(TestCase):
    url = reverse("users:register")
    data = {"full_name": "Ann Renter", "email": "ann@example.com", "password": "abc12345", "password_confirm": "abc12345"}

    def test_registration_requiring_email_confirmation(self):
        with mock_auth_client() as get_client:
            get_client.return_value.sign_up.return_value = SignUpResult("id", "ann@example.com", None)
            response = self.client.post(self.url, self.data)
        self.assertContains(response, "Check your inbox")
        self.assertFalse(get_user(self.client).is_authenticated)

    def test_registration_with_immediate_session_logs_in(self):
        with mock_auth_client() as get_client:
            session = fake_session(email="ann@example.com")
            get_client.return_value.sign_up.return_value = SignUpResult(session.user_id, session.email, session)
            response = self.client.post(self.url, self.data)
        self.assertRedirects(response, reverse("users:dashboard"))
        self.assertEqual(User.objects.get(email="ann@example.com").full_name, "Ann Renter")

    def test_password_rules_and_confirmation(self):
        for password, confirm, message in [("short1", "short1", "at least 8"), ("abcdefgh", "abcdefgh", "letters and numbers"), ("abc12345", "abc99999", "do not match")]:
            with self.subTest(password=password):
                response = self.client.post(self.url, {**self.data, "password": password, "password_confirm": confirm})
                self.assertContains(response, message)

    def test_supabase_error_shown(self):
        with mock_auth_client() as get_client:
            get_client.return_value.sign_up.side_effect = SupabaseAuthError("An account with this email already exists.")
            response = self.client.post(self.url, self.data)
        self.assertContains(response, "already exists")


class LogoutAndProtectedPagesTests(TestCase):
    def test_protected_pages_redirect_guests_to_login(self):
        for name in ["users:dashboard", "users:profile", "users:saved", "apartments:submit", "apartments:my_listings"]:
            with self.subTest(page=name):
                url = reverse(name)
                self.assertRedirects(self.client.get(url), f"{reverse('users:login')}?next={url}")

    def test_logged_in_user_sees_dashboard_and_profile(self):
        self.client.force_login(make_user(full_name="Sam"))
        self.assertContains(self.client.get(reverse("users:dashboard")), "Hi, Sam")
        self.assertEqual(self.client.get(reverse("users:profile")).status_code, 200)

    def test_logout_requires_post(self):
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(reverse("users:logout")).status_code, 405)
        with mock_auth_client():
            response = self.client.post(reverse("users:logout"))
        self.assertRedirects(response, reverse("core:home"))
        self.assertFalse(get_user(self.client).is_authenticated)

    def test_profile_update_cannot_change_email_or_role(self):
        user = make_user()
        self.client.force_login(user)
        self.client.post(reverse("users:profile"), {"full_name": "New Name", "phone": "+1 555 000 1111", "role": "admin", "email": "x@evil.com"})
        user.refresh_from_db()
        self.assertEqual((user.full_name, user.role, user.email), ("New Name", User.Role.USER, "user@example.com"))

    def test_profile_rejects_invalid_phone(self):
        self.client.force_login(make_user())
        response = self.client.post(reverse("users:profile"), {"full_name": "A", "phone": "call me maybe"})
        self.assertContains(response, "valid phone number")


class SessionRefreshMiddlewareTests(TestCase):
    def _login_with_expired_token(self):
        user = make_user()
        self.client.force_login(user)
        session = self.client.session
        session[services.SESSION_TOKENS_KEY] = {
            "access_token": "old", "refresh_token": "refresh", "expires_at": int(time.time()) - 10,
            "user_id": str(user.auth_user_id), "email": user.email, "email_confirmed": True,
        }
        session.save()
        return user

    def test_expired_token_is_refreshed(self):
        user = self._login_with_expired_token()
        with mock_auth_client() as get_client:
            get_client.return_value.refresh_session.return_value = fake_session(user.auth_user_id, user.email)
            response = self.client.get(reverse("users:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session[services.SESSION_TOKENS_KEY]["access_token"], "access-token")

    def test_revoked_session_logs_user_out(self):
        self._login_with_expired_token()
        with mock_auth_client() as get_client:
            get_client.return_value.refresh_session.side_effect = SupabaseAuthError(code="refresh_token_not_found")
            response = self.client.get(reverse("users:dashboard"), follow=True)
        self.assertContains(response, "Your session has expired")
        self.assertFalse(get_user(self.client).is_authenticated)

    def test_outage_keeps_user_logged_in(self):
        self._login_with_expired_token()
        with mock_auth_client() as get_client:
            get_client.return_value.refresh_session.side_effect = SupabaseServiceError(status=503)
            response = self.client.get(reverse("users:dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_deactivated_user_is_logged_out_on_next_request(self):
        user = make_user()
        self.client.force_login(user)
        User.objects.filter(pk=user.pk).update(is_active=False)
        self.assertEqual(self.client.get(reverse("users:dashboard")).status_code, 302)


class GoogleLoginTests(TestCase):
    def test_start_redirects_to_supabase_with_pkce_challenge(self):
        response = self.client.get(reverse("users:oauth_start", args=["google"]) + "?next=/account/profile/")
        self.assertEqual(response.status_code, 302)
        target = urlparse(response["Location"])
        params = parse_qs(target.query)
        self.assertEqual(target.path, "/auth/v1/authorize")
        self.assertEqual(params["provider"], ["google"])
        self.assertEqual(params["code_challenge_method"], ["s256"])
        self.assertTrue(params["redirect_to"][0].endswith(reverse("users:auth_callback")))
        state = self.client.session["supabase_oauth"]
        self.assertNotEqual(state["verifier"], params["code_challenge"][0])  # verifier never leaves the server
        self.assertEqual(state["next"], "/account/profile/")

    def test_unknown_provider_is_404(self):
        self.assertEqual(self.client.get(reverse("users:oauth_start", args=["myspace"])).status_code, 404)

    def test_callback_exchanges_code_and_logs_in(self):
        self.client.get(reverse("users:oauth_start", args=["google"]))
        verifier = self.client.session["supabase_oauth"]["verifier"]
        with mock_auth_client() as get_client:
            session = fake_session(email="gmail.user@gmail.com")
            get_client.return_value.exchange_code_for_session.return_value = (session, {"user_metadata": {"full_name": "Gee Mail"}})
            response = self.client.get(reverse("users:auth_callback") + "?code=abc123")
            get_client.return_value.exchange_code_for_session.assert_called_once_with("abc123", verifier)
        self.assertRedirects(response, reverse("users:dashboard"))
        self.assertEqual(User.objects.get(email="gmail.user@gmail.com").full_name, "Gee Mail")
        self.assertNotIn("supabase_oauth", self.client.session)

    def test_callback_without_started_flow_is_rejected(self):
        with mock_auth_client() as get_client:
            response = self.client.get(reverse("users:auth_callback") + "?code=stolen", follow=True)
            get_client.return_value.exchange_code_for_session.assert_not_called()
        self.assertContains(response, "sign-in session expired")

    def test_callback_error_from_provider(self):
        response = self.client.get(reverse("users:auth_callback") + "?error=access_denied", follow=True)
        self.assertContains(response, "cancelled or failed")

    def test_callback_without_code_renders_email_link_handler(self):
        self.assertContains(self.client.get(reverse("users:auth_callback")), "Signing you in")


class EmailLinkSessionTests(TestCase):
    def test_tokens_from_email_link_are_verified_with_supabase(self):
        user_id = str(uuid.uuid4())
        with mock_auth_client() as get_client:
            get_client.return_value.get_user.return_value = {"id": user_id, "email": "c@example.com", "user_metadata": {"full_name": "Cee"}}
            response = self.client.post(
                reverse("users:auth_session"), {"access_token": "tok", "refresh_token": "ref", "expires_at": 9999999999},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["redirect"], reverse("users:dashboard"))
        self.assertEqual(str(User.objects.get(email="c@example.com").auth_user_id), user_id)
        # client-supplied expiry is capped
        self.assertLessEqual(self.client.session[services.SESSION_TOKENS_KEY]["expires_at"], time.time() + 3601)

    def test_invalid_token_rejected(self):
        with mock_auth_client() as get_client:
            get_client.return_value.get_user.side_effect = SupabaseAuthError("Your session has expired.")
            response = self.client.post(reverse("users:auth_session"), {"access_token": "bad"}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_missing_token(self):
        response = self.client.post(reverse("users:auth_session"), {}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
