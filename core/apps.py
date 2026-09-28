from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _apply_rls_after_migrate(sender, using, **kwargs):
    from django.db import connections

    from .rls import apply_rls

    apply_rls(connections[using])


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from . import checks  # noqa: F401 — registers configuration system checks

        # Re-applied after every migrate so tables added later are covered too.
        post_migrate.connect(_apply_rls_after_migrate, sender=self, dispatch_uid="core.apply_rls")
