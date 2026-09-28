from django.core.management.base import BaseCommand
from django.db import connection

from core.rls import apply_rls


class Command(BaseCommand):
    help = "Enable Row Level Security on all public tables and (re)create the Supabase read policies."

    def handle(self, *args, **options):
        if apply_rls(connection):
            self.stdout.write(self.style.SUCCESS("Row Level Security applied."))
        else:
            self.stdout.write(self.style.WARNING("Skipped: RLS is only available on PostgreSQL (Supabase)."))
