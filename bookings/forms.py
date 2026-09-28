from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from users.forms import validate_phone

from .models import Booking


class BookingForm(forms.ModelForm):
    agree = forms.BooleanField(
        label="I understand this is a booking request. The landlord will confirm, and no payment is taken online.",
    )

    class Meta:
        model = Booking
        fields = ["full_name", "phone", "email", "household", "occupants", "move_in_date", "visit_date", "message"]
        widgets = {
            "move_in_date": forms.DateInput(attrs={"type": "date"}),
            "visit_date": forms.DateInput(attrs={"type": "date"}),
            "occupants": forms.NumberInput(attrs={"min": 1, "max": 30}),
            "phone": forms.TextInput(attrs={"placeholder": "01XXXXXXXXX", "autocomplete": "tel"}),
            "message": forms.Textarea(attrs={"rows": 4, "placeholder": "Introduce yourself — e.g. who will live here, your profession, any questions."}),
        }
        labels = {"full_name": "Your full name", "email": "Your email"}

    def __init__(self, *args, apartment=None, **kwargs):
        self.apartment = apartment
        super().__init__(*args, **kwargs)
        today = timezone.localdate().isoformat()
        self.fields["move_in_date"].widget.attrs["min"] = today
        self.fields["visit_date"].widget.attrs["min"] = today

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        validate_phone(phone)
        digits = "".join(ch for ch in phone if ch.isdigit())
        if len(digits) < 10:
            raise ValidationError("Enter a valid phone number, e.g. 01712345678.")
        return phone

    def clean_move_in_date(self):
        value = self.cleaned_data["move_in_date"]
        today = timezone.localdate()
        if value < today:
            raise ValidationError("Move-in date can't be in the past.")
        if value > today + timedelta(days=365):
            raise ValidationError("Move-in date must be within the next 12 months.")
        return value

    def clean_visit_date(self):
        value = self.cleaned_data.get("visit_date")
        if value and value < timezone.localdate():
            raise ValidationError("Viewing date can't be in the past.")
        return value

    def clean_occupants(self):
        value = self.cleaned_data["occupants"]
        if not 1 <= value <= 30:
            raise ValidationError("Enter between 1 and 30 people.")
        return value


class LandlordResponseForm(forms.Form):
    action = forms.ChoiceField(choices=[("accept", "Accept"), ("decline", "Decline")])
    note = forms.CharField(
        required=False, max_length=2000, widget=forms.Textarea(attrs={"rows": 2}),
        label="Message to the renter (optional)",
    )
