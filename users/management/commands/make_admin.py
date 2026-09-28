from django.core.management.base import BaseCommand, CommandError

from users.models import User


class Command(BaseCommand):
    help = "Grant (or with --revoke, remove) the admin role for a registered user."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--revoke", action="store_true", help="Demote the user back to a normal user.")

    def handle(self, email, revoke=False, **options):
        user = User.objects.filter(email__iexact=email.strip()).first()
        if user is None:
            raise CommandError(f"No profile for {email}. Register and log in once through the website first.")
        user.role = User.Role.USER if revoke else User.Role.ADMIN
        user.save(update_fields=["role", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"{user.email} is now {'a regular user' if revoke else 'an admin'}."))
