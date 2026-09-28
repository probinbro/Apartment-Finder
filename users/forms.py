import re

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from core.images import delete_file_quietly, process_image

from .models import User

PHONE_PATTERN = re.compile(r"^\+?[0-9 ()\-]{6,20}$")


def validate_phone(value):
    if value and not PHONE_PATTERN.match(value):
        raise ValidationError("Enter a valid phone number (digits, spaces, +, - and brackets only).")


class LoginForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}))
    password = forms.CharField(strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    def clean_email(self):
        return self.cleaned_data["email"].lower()


class RegisterForm(forms.Form):
    full_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password = forms.CharField(strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password_confirm = forms.CharField(
        label="Confirm password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )

    def clean_email(self):
        return self.cleaned_data["email"].lower()

    def clean_password(self):
        password = self.cleaned_data["password"]
        min_length = settings.SUPABASE_MIN_PASSWORD_LENGTH
        if len(password) < min_length:
            raise ValidationError(f"Password must be at least {min_length} characters long.")
        if password.isdigit() or password.isalpha():
            raise ValidationError("Password must contain both letters and numbers.")
        return password

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") and cleaned.get("password") != cleaned.get("password_confirm"):
            self.add_error("password_confirm", "Passwords do not match.")
        return cleaned


class ProfileForm(forms.ModelForm):
    """Users may edit their own name, phone and avatar — never email or role."""

    remove_avatar = forms.BooleanField(required=False, label="Remove current photo")

    class Meta:
        model = User
        fields = ["full_name", "phone", "avatar"]
        widgets = {"avatar": forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp", "data-preview": "avatar"})}
        labels = {"avatar": "Profile photo"}

    def clean_phone(self):
        phone = self.cleaned_data.get("phone", "").strip()
        validate_phone(phone)
        return phone

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar and avatar != self.initial.get("avatar"):
            processed, _ = process_image(avatar, max_dimension=512)
            return processed
        return avatar

    def save(self, commit=True):
        user = super().save(commit=False)
        previous = User.objects.filter(pk=user.pk).values_list("avatar", flat=True).first()
        if self.cleaned_data.get("remove_avatar") and "avatar" not in self.changed_data:
            user.avatar = ""
        if commit:
            user.save()
            if previous and previous != user.avatar.name:
                delete_file_quietly(user.avatar.storage, previous)
        return user
