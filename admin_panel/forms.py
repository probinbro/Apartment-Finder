from django import forms

from apartments.models import Amenity, PropertyType
from users.models import User


class UserAdminForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "phone", "role", "is_active"]
        labels = {"is_active": "Account active (can log in)"}


class PropertyTypeForm(forms.ModelForm):
    class Meta:
        model = PropertyType
        fields = ["name", "sort_order"]


class AmenityForm(forms.ModelForm):
    class Meta:
        model = Amenity
        fields = ["name", "icon", "sort_order"]


class ReviewForm(forms.Form):
    action = forms.ChoiceField(choices=[("approve", "Approve"), ("reject", "Reject")])
    note = forms.CharField(
        required=False, max_length=1000, widget=forms.Textarea(attrs={"rows": 3}),
        label="Message to the owner", help_text="Required when rejecting — explain what needs to change.",
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("action") == "reject" and not (cleaned.get("note") or "").strip():
            self.add_error("note", "Please tell the owner why the listing was rejected.")
        return cleaned
