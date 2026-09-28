"""
Django settings for the Apartment Finder platform.

All secrets and environment-specific values are read from environment
variables (loaded from a local `.env` file in development). See `.env.example`.
"""

import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


RUNNING_TESTS = len(sys.argv) > 1 and sys.argv[1] == "test"

# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------

DEBUG = env_bool("DEBUG", False)

SECRET_KEY = env("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG or RUNNING_TESTS:
        SECRET_KEY = "insecure-dev-only-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured("SECRET_KEY must be set when DEBUG is off.")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")

# Render (render.com) tells the app its public hostname; trust it automatically.
RENDER_EXTERNAL_HOSTNAME = env("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

SITE_NAME = env("SITE_NAME", "Apartment Finder")

# Public base URL of the site; used for Supabase auth redirects (email links, Google login).
SITE_URL = (
    env("SITE_URL")
    or (f"https://{RENDER_EXTERNAL_HOSTNAME}" if RENDER_EXTERNAL_HOSTNAME else "http://127.0.0.1:8000")
).rstrip("/")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "users",
    "apartments",
    "bookings",
    "admin_panel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "users.middleware.SupabaseSessionMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site",
                "core.context_processors.admin_badges",
                "core.context_processors.user_badges",
            ],
            "builtins": ["core.templatetags.ui"],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --------------------------------------------------------------------------
# Database — Supabase PostgreSQL
# --------------------------------------------------------------------------


def database_from_url(url):
    """Build a Django DATABASES entry from a postgres:// connection URL."""
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("DATABASE_URL must be a PostgreSQL URL (postgresql://...).")
    options = dict(parse_qsl(parsed.query))
    options.setdefault("sslmode", "require")
    port = parsed.port or 5432
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")) or "postgres",
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(port),
        "OPTIONS": options,
        # Supabase's pooler limits client connections, so by default we don't
        # hold connections open between requests.
        "CONN_MAX_AGE": int(env("DB_CONN_MAX_AGE", "0")),
        "CONN_HEALTH_CHECKS": True,
        # Port 6543 is Supabase's *transaction* pooler, which cannot keep
        # server-side cursors alive across statements.
        "DISABLE_SERVER_SIDE_CURSORS": port == 6543,
    }


DATABASE_URL = env("DATABASE_URL")
USE_POSTGRES_FOR_TESTS = env_bool("TEST_USE_POSTGRES", False)

if DATABASE_URL and not (RUNNING_TESTS and not USE_POSTGRES_FOR_TESTS):
    DATABASES = {"default": database_from_url(DATABASE_URL)}
elif DEBUG or RUNNING_TESTS:
    # Local fallback so tests and quick UI work run without network access.
    # Supabase PostgreSQL is the real database; see README "Database setup".
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured("DATABASE_URL (Supabase PostgreSQL) must be set when DEBUG is off.")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Authentication — Supabase Auth, mapped onto a local profile model
# --------------------------------------------------------------------------

AUTH_USER_MODEL = "users.User"
AUTHENTICATION_BACKENDS = ["users.backends.SupabaseAuthBackend"]
LOGIN_URL = "users:login"
LOGIN_REDIRECT_URL = "users:dashboard"
LOGOUT_REDIRECT_URL = "core:home"

# Passwords are handled entirely by Supabase; these validators only guard the
# registration form before the request is forwarded.
AUTH_PASSWORD_VALIDATORS = []
SUPABASE_MIN_PASSWORD_LENGTH = int(env("SUPABASE_MIN_PASSWORD_LENGTH", "8"))

SUPABASE_URL = (env("SUPABASE_URL") or "").rstrip("/")
SUPABASE_ANON_KEY = env("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = env("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_STORAGE_BUCKET = env("SUPABASE_STORAGE_BUCKET", "apartment-media")
SUPABASE_TIMEOUT_SECONDS = float(env("SUPABASE_TIMEOUT_SECONDS", "10"))
# Social login providers enabled in Supabase (Authentication → Providers), e.g. "google".
SUPABASE_OAUTH_PROVIDERS = [p.lower() for p in env_list("SUPABASE_OAUTH_PROVIDERS", "")]

# --------------------------------------------------------------------------
# Sessions & security
# --------------------------------------------------------------------------

SESSION_COOKIE_AGE = int(env("SESSION_COOKIE_AGE", str(60 * 60 * 24 * 7)))
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
CSRF_FAILURE_VIEW = "core.views.csrf_failure_view"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "3600"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# --------------------------------------------------------------------------
# Internationalization
# --------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "Asia/Dhaka")
USE_I18N = True
USE_TZ = True

# Rents are in Bangladeshi Taka, shown with South-Asian (lakh) digit grouping: ৳1,50,000.
CURRENCY_SYMBOL = env("CURRENCY_SYMBOL", "৳")
USE_LAKH_GROUPING = env_bool("USE_LAKH_GROUPING", True)

# --------------------------------------------------------------------------
# Bookings
# --------------------------------------------------------------------------

# An unanswered booking request holds the apartment for this many days, then expires.
BOOKING_HOLD_DAYS = int(env("BOOKING_HOLD_DAYS", "3"))
# Anti-abuse: how many open (pending/accepted) bookings one user may hold at once.
MAX_ACTIVE_BOOKINGS_PER_USER = int(env("MAX_ACTIVE_BOOKINGS_PER_USER", "3"))

# --------------------------------------------------------------------------
# Email — booking notifications
# --------------------------------------------------------------------------
# Priority: Brevo HTTP API (works on hosts that block SMTP, e.g. Render free) →
# SMTP (e.g. Gmail with an app password) → console output (development).

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", f"{SITE_NAME} <no-reply@example.com>")
BREVO_API_KEY = env("BREVO_API_KEY", "")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_TIMEOUT = 10
if BREVO_API_KEY:
    EMAIL_BACKEND = "core.email_backends.BrevoEmailBackend"
elif EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = int(env("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
# Fallback recipients for bookings on listings that have no landlord account.
ADMIN_NOTIFICATION_EMAILS = env_list("ADMIN_NOTIFICATION_EMAILS", "")

# --------------------------------------------------------------------------
# Static & media files
# --------------------------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Images go to Supabase Storage when it is configured; otherwise to MEDIA_ROOT.
USE_SUPABASE_STORAGE = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY) and not RUNNING_TESTS

STORAGES = {
    "default": {
        "BACKEND": (
            "core.supabase.storage.SupabaseStorage"
            if USE_SUPABASE_STORAGE
            else "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG or RUNNING_TESTS
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}

# Image upload rules (enforced in core/images.py).
IMAGE_MAX_UPLOAD_BYTES = int(env("IMAGE_MAX_UPLOAD_MB", "5")) * 1024 * 1024
IMAGE_ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
IMAGE_MAX_DIMENSION = 1920
IMAGE_MAX_FILES_PER_UPLOAD = 10
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# --------------------------------------------------------------------------
# Logging — errors are logged server-side, never shown to users.
# --------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "[{levelname}] {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "core": {"level": "INFO"},
        "users": {"level": "INFO"},
        "apartments": {"level": "INFO"},
        "admin_panel": {"level": "INFO"},
    },
}

if RUNNING_TESTS:
    LOGGING["root"]["level"] = "CRITICAL"
    for _logger in LOGGING["loggers"].values():
        _logger["level"] = "CRITICAL"

if RUNNING_TESTS:
    # Tests never talk to the real Supabase project or write files to disk.
    SUPABASE_URL = "https://test-project.supabase.co"
    SUPABASE_ANON_KEY = "test-anon-key"
    SUPABASE_SERVICE_ROLE_KEY = ""
    SUPABASE_OAUTH_PROVIDERS = ["google"]
    STORAGES["default"] = {"BACKEND": "django.core.files.storage.InMemoryStorage"}
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
