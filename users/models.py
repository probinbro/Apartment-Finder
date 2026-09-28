"""
Application user profiles.

Credentials live exclusively in Supabase Auth (`auth.users`). This table holds
app-specific profile data and the role used for authorization, linked to the
Supabase user by `auth_user_id`. The inherited `password` column is always set
to an unusable value — no password is ever stored here.
"""

import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models


def avatar_upload_path(instance, filename):
    return f"users/{instance.pk or 'new'}/avatar-{uuid.uuid4().hex[:12]}.jpg"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, auth_user_id=None, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email).lower(), auth_user_id=auth_user_id, **extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, auth_user_id=None, **extra_fields):
        extra_fields["role"] = User.Role.ADMIN
        return self.create_user(email, auth_user_id=auth_user_id, **extra_fields)


class User(AbstractBaseUser):
    class Role(models.TextChoices):
        USER = "user", "User"
        ADMIN = "admin", "Admin"

    auth_user_id = models.UUIDField(
        unique=True, null=True, blank=True, editable=False, help_text="Supabase auth.users.id"
    )
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    avatar = models.ImageField(upload_to=avatar_upload_path, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.USER, db_index=True)
    is_active = models.BooleanField(default=True, help_text="Inactive users cannot log in.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "profiles"
        ordering = ["-created_at"]

    def __str__(self):
        return self.email

    @property
    def is_admin(self):
        return self.is_active and self.role == self.Role.ADMIN

    # Compatibility with code that expects Django's staff/permission API.
    @property
    def is_staff(self):
        return self.is_admin

    @property
    def is_superuser(self):
        return self.is_admin

    def has_perm(self, perm, obj=None):
        return self.is_admin

    def has_module_perms(self, app_label):
        return self.is_admin

    @property
    def display_name(self):
        return self.full_name or self.email.split("@")[0]

    @property
    def initials(self):
        parts = [p for p in self.display_name.replace(".", " ").split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"
