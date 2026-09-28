from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.supabase.client import SupabaseAdminClient, SupabaseError, is_admin_configured

ALLOWED_MIME_TYPES = ["image/jpeg", "image/png", "image/webp"]


class Command(BaseCommand):
    help = "Create (or update) the public Supabase Storage bucket used for apartment images."

    def handle(self, *args, **options):
        if not is_admin_configured():
            raise CommandError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env first.")

        bucket = settings.SUPABASE_STORAGE_BUCKET
        config = {
            "id": bucket,
            "name": bucket,
            "public": True,
            "file_size_limit": settings.IMAGE_MAX_UPLOAD_BYTES,
            "allowed_mime_types": ALLOWED_MIME_TYPES,
        }
        client = SupabaseAdminClient()
        try:
            client.request("POST", "/storage/v1/bucket", json=config)
            self.stdout.write(self.style.SUCCESS(f"Created public bucket '{bucket}'."))
        except SupabaseError as exc:
            if exc.status not in (400, 409):
                raise CommandError(f"Could not create bucket: {exc}") from exc
            # Already exists: make sure its settings are correct.
            client.request("PUT", f"/storage/v1/bucket/{bucket}", json=config)
            self.stdout.write(self.style.SUCCESS(f"Bucket '{bucket}' already exists; settings updated."))
