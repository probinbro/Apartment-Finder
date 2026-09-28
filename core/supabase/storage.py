"""
Django storage backend for Supabase Storage.

Used as the default file storage when SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
are configured, so `ImageField`s transparently upload to the bucket and
`.url` returns the public object URL.

Uploads/deletes use the service-role key (server-side only). The bucket is
public-read so images can be served directly from Supabase's CDN.
"""

from urllib.parse import quote

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

from .client import SupabaseAdminClient, SupabaseError


@deconstructible
class SupabaseStorage(Storage):
    def __init__(self, bucket=None, client=None):
        self.bucket = bucket or settings.SUPABASE_STORAGE_BUCKET
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = SupabaseAdminClient()
        return self._client

    def _object_path(self, name):
        return f"/storage/v1/object/{self.bucket}/{quote(name)}"

    def _save(self, name, content):
        content.seek(0)
        content_type = getattr(content, "content_type", None) or "application/octet-stream"
        self.client.request(
            "POST",
            self._object_path(name),
            data=content.read(),
            headers={"Content-Type": content_type, "x-upsert": "false", "cache-control": "max-age=31536000"},
        )
        return name

    def _open(self, name, mode="rb"):
        response = self.client.request("GET", self._object_path(name))
        return ContentFile(response.content, name=name)

    def delete(self, name):
        if not name:
            return
        try:
            self.client.request("DELETE", self._object_path(name))
        except SupabaseError as exc:
            # A missing object is fine: the goal state (object gone) is reached.
            if exc.status not in (400, 404):
                raise

    def exists(self, name):
        try:
            self.client.request("HEAD", self._object_path(name))
            return True
        except SupabaseError as exc:
            if exc.status in (400, 404):
                return False
            raise

    def url(self, name):
        return f"{settings.SUPABASE_URL}/storage/v1/object/public/{self.bucket}/{quote(name)}"

    def size(self, name):
        response = self.client.request("HEAD", self._object_path(name))
        return int(response.headers.get("Content-Length", 0))
