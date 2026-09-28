"""Startup checks that flag missing or unsafe configuration early (`manage.py check`)."""

from django.conf import settings
from django.core.checks import Warning, register


@register()
def supabase_configuration_check(app_configs, **kwargs):
    if settings.RUNNING_TESTS:
        return []
    issues = []
    if not (settings.SUPABASE_URL and settings.SUPABASE_ANON_KEY):
        issues.append(Warning(
            "Supabase Auth is not configured; login and registration will be unavailable.",
            hint="Set SUPABASE_URL and SUPABASE_ANON_KEY in your .env file.",
            id="core.W001",
        ))
    if not settings.USE_SUPABASE_STORAGE:
        issues.append(Warning(
            "Supabase Storage is not configured; uploads are saved to the local media/ folder.",
            hint="Set SUPABASE_SERVICE_ROLE_KEY (and SUPABASE_STORAGE_BUCKET) to use Supabase Storage.",
            id="core.W002",
        ))
    if settings.DATABASES["default"]["ENGINE"].endswith("sqlite3"):
        issues.append(Warning(
            "Using the local SQLite fallback database instead of Supabase PostgreSQL.",
            hint="Set DATABASE_URL to your Supabase connection string.",
            id="core.W003",
        ))
    return issues
