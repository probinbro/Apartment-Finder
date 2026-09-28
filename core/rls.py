"""
Supabase Row Level Security.

Django connects to Postgres as the table owner, which bypasses RLS, so these
policies do not affect the app itself. They protect the data from direct
access through Supabase's auto-generated REST API (PostgREST) with the public
anon key:

  * RLS is enabled on EVERY table in the `public` schema — including Django's
    internal tables such as `django_session`, which must never be readable.
  * Only public-safe data gets read policies: published apartments, their
    images and the lookup tables. Users may read their own profile row.
  * No insert/update/delete policies exist, so all writes go through Django.

Applied automatically after `migrate` on PostgreSQL (see core.apps), and
available manually via `python manage.py apply_rls`.
"""

import logging

logger = logging.getLogger(__name__)

# Only touches tables that don't have RLS yet: ALTER TABLE takes an exclusive
# lock, so re-running it on every deploy would block live traffic.
ENABLE_RLS_ON_ALL_TABLES = """
DO $$
DECLARE t record;
BEGIN
    FOR t IN
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.relname);
    END LOOP;
END $$;
"""

PUBLIC_READ_POLICIES = {
    "apartments": "status = 'published'",
    "apartment_images": (
        "EXISTS (SELECT 1 FROM public.apartments a WHERE a.id = apartment_id AND a.status = 'published')"
    ),
    "property_types": "true",
    "amenities": "true",
    "apartments_amenities": "true",
}

OWN_PROFILE_POLICY = "auth_user_id = auth.uid()"


def _supabase_roles_exist(cursor):
    cursor.execute("SELECT count(*) FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
    has_roles = cursor.fetchone()[0] == 2
    cursor.execute("SELECT to_regprocedure('auth.uid()') IS NOT NULL")
    return has_roles and cursor.fetchone()[0]


def _table_exists(cursor, table):
    cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [f"public.{table}"])
    return cursor.fetchone()[0]


def _policy_exists(cursor, table, name):
    cursor.execute("SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = %s AND policyname = %s", [table, name])
    return cursor.fetchone() is not None


def _ensure_policy(cursor, table, name, sql, replace):
    if not _table_exists(cursor, table):
        return
    if _policy_exists(cursor, table, name):
        if not replace:
            return
        cursor.execute(f'DROP POLICY "{name}" ON public.{table}')
    cursor.execute(sql)


def apply_rls(connection, replace_policies=False):
    """Idempotent: creates only what is missing unless `replace_policies` is set."""
    if connection.vendor != "postgresql":
        return False
    with connection.cursor() as cursor:
        cursor.execute(ENABLE_RLS_ON_ALL_TABLES)
        if not _supabase_roles_exist(cursor):
            logger.info("RLS enabled; Supabase roles not found, so no policies were created.")
            return True

        for table, condition in PUBLIC_READ_POLICIES.items():
            _ensure_policy(
                cursor, table, "public_read",
                f'CREATE POLICY "public_read" ON public.{table} FOR SELECT TO anon, authenticated USING ({condition})',
                replace_policies,
            )
        _ensure_policy(
            cursor, "profiles", "own_profile_read",
            f'CREATE POLICY "own_profile_read" ON public.profiles FOR SELECT TO authenticated USING ({OWN_PROFILE_POLICY})',
            replace_policies,
        )
    logger.info("Supabase RLS checked.")
    return True
