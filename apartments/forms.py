from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from core.images import validate_image_file
from users.forms import validate_phone

from .models import Apartment, ApartmentImage


class ApartmentForm(forms.ModelForm):
    class Meta:
        model = Apartment
        fields = [
            "title", "description", "property_type", "status", "is_featured",
            "address", "city", "area", "postal_code", "latitude", "longitude",
            "rent", "bedrooms", "bathrooms", "size_sqft",
            "furnishing", "availability", "available_from", "amenities",
            "advance_months", "service_charge", "tenant_preference", "floor_number", "total_floors",
            "contact_name", "contact_phone", "contact_email", "owner",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
            "available_from": forms.DateInput(attrs={"type": "date"}),
            "amenities": forms.CheckboxSelectMultiple,
            "rent": forms.NumberInput(attrs={"min": "1", "step": "0.01"}),
            "bedrooms": forms.NumberInput(attrs={"min": "0", "max": "50"}),
            "bathrooms": forms.NumberInput(attrs={"min": "0", "max": "50"}),
            "size_sqft": forms.NumberInput(attrs={"min": "1"}),
            "service_charge": forms.NumberInput(attrs={"min": "0", "step": "100"}),
            "advance_months": forms.NumberInput(attrs={"min": "0", "max": "24"}),
        }
        help_texts = {"is_featured": "Show this listing in the homepage “Featured” section."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "owner" in self.fields:
            self.fields["owner"].queryset = self.fields["owner"].queryset.filter(is_active=True).order_by("email")
            self.fields["owner"].required = False
        self.fields["property_type"].empty_label = "Select a type"

    def _clean_text(self, name):
        value = (self.cleaned_data.get(name) or "").strip()
        if not value:
            raise ValidationError("This field cannot be blank.")
        return value

    def clean_title(self):
        return self._clean_text("title")

    def clean_description(self):
        return self._clean_text("description")

    def clean_city(self):
        return self._clean_text("city").title()

    def clean_area(self):
        return self._clean_text("area").title()

    def clean_address(self):
        return self._clean_text("address")

    def clean_rent(self):
        rent = self.cleaned_data.get("rent")
        if rent is not None and rent <= 0:
            raise ValidationError("Rent must be a positive amount.")
        return rent

    def clean_size_sqft(self):
        size = self.cleaned_data.get("size_sqft")
        if size is not None and size <= 0:
            raise ValidationError("Size must be greater than zero.")
        return size

    def clean_bedrooms(self):
        return self._clean_room_count("bedrooms")

    def clean_bathrooms(self):
        return self._clean_room_count("bathrooms")

    def _clean_room_count(self, name):
        value = self.cleaned_data.get(name)
        if value is not None and not 0 <= value <= 50:
            raise ValidationError("Enter a number between 0 and 50.")
        return value

    def clean_latitude(self):
        lat = self.cleaned_data.get("latitude")
        if lat is not None and not -90 <= lat <= 90:
            raise ValidationError("Latitude must be between -90 and 90.")
        return lat

    def clean_longitude(self):
        lng = self.cleaned_data.get("longitude")
        if lng is not None and not -180 <= lng <= 180:
            raise ValidationError("Longitude must be between -180 and 180.")
        return lng

    def clean_advance_months(self):
        value = self.cleaned_data.get("advance_months")
        if value is not None and value > 24:
            raise ValidationError("Advance can be at most 24 months.")
        return value

    def clean_service_charge(self):
        value = self.cleaned_data.get("service_charge")
        if value is not None and value < 0:
            raise ValidationError("Service charge cannot be negative.")
        return value

    def clean_contact_phone(self):
        phone = (self.cleaned_data.get("contact_phone") or "").strip()
        validate_phone(phone)
        return phone

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("contact_phone") and not cleaned.get("contact_email"):
            self.add_error("contact_email", "Provide at least a contact phone number or email.")
        floor, total = cleaned.get("floor_number"), cleaned.get("total_floors")
        if floor is not None and total and floor > total:
            self.add_error("floor_number", "Floor can't be higher than the building's total floors.")
        if (cleaned.get("latitude") is None) != (cleaned.get("longitude") is None):
            self.add_error("longitude", "Provide both latitude and longitude, or neither.")
        return cleaned


OWNER_EDITABLE_FIELDS = [
    "title", "description", "property_type",
    "address", "city", "area", "postal_code",
    "rent", "bedrooms", "bathrooms", "size_sqft",
    "furnishing", "availability", "available_from", "amenities",
    "advance_months", "service_charge", "tenant_preference", "floor_number", "total_floors",
    "contact_name", "contact_phone", "contact_email",
]


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else ([data] if data else [])
        if not files:
            if self.required:
                raise ValidationError("Choose at least one image to upload.")
            return []
        if len(files) > settings.IMAGE_MAX_FILES_PER_UPLOAD:
            raise ValidationError(f"You can upload up to {settings.IMAGE_MAX_FILES_PER_UPLOAD} images at a time.")
        errors = []
        for upload in files:
            try:
                validate_image_file(upload)
            except ValidationError as exc:
                errors.extend(exc.messages)
        if errors:
            raise ValidationError(errors)
        return files


IMAGE_ACCEPT = "image/jpeg,image/png,image/webp"


class ImageUploadForm(forms.Form):
    images = MultipleImageField(widget=MultipleFileInput(attrs={"accept": IMAGE_ACCEPT, "data-preview": "multi"}))
    caption = forms.CharField(max_length=150, required=False, help_text="Optional; applied to every image in this upload.")


class ImageReplaceForm(forms.Form):
    image = forms.FileField(widget=forms.FileInput(attrs={"accept": IMAGE_ACCEPT}))

    def clean_image(self):
        upload = self.cleaned_data["image"]
        validate_image_file(upload)
        return upload


class ImageCaptionForm(forms.ModelForm):
    class Meta:
        model = ApartmentImage
        fields = ["caption"]


class ListingSubmissionForm(ApartmentForm):
    """
    Form for users listing their own home. Moderation fields (status, featured,
    owner) are deliberately excluded — they are set by the view and by admins,
    never taken from the request.
    """

    photos = MultipleImageField(
        required=False,
        widget=MultipleFileInput(attrs={"accept": IMAGE_ACCEPT, "data-preview": "multi"}),
        help_text="JPG, PNG or WEBP · max 5 MB each · up to 10 photos.",
    )

    class Meta(ApartmentForm.Meta):
        fields = OWNER_EDITABLE_FIELDS

    def __init__(self, *args, require_photos=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["photos"].required = require_photos
        # Owners can't set "Booked"/"Rented" themselves; that is driven by bookings.
        self.fields["availability"].choices = [
            (value, label) for value, label in self.fields["availability"].choices
            if value in Apartment.BOOKABLE_AVAILABILITIES
        ]
