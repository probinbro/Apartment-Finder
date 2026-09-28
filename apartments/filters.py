"""
Apartment search/filtering.

`ApartmentSearchForm` validates the query string; `apply_filters` maps each
cleaned field to a queryset operation via the FILTERS registry. To add a new
filter: add a form field, then register one function in FILTERS.
"""

from django import forms
from django.db.models import Q

from .models import Amenity, Apartment, PropertyType

ANY = [("", "Any")]
BEDROOM_CHOICES = ANY + [("0", "Studio+"), ("1", "1+"), ("2", "2+"), ("3", "3+"), ("4", "4+")]
BATHROOM_CHOICES = ANY + [("1", "1+"), ("2", "2+"), ("3", "3+")]

SORT_OPTIONS = {
    "newest": ("Newest first", ["-published_at", "-created_at"]),
    "rent_asc": ("Rent: low to high", ["rent", "-created_at"]),
    "rent_desc": ("Rent: high to low", ["-rent", "-created_at"]),
    "size_desc": ("Largest first", ["-size_sqft", "-created_at"]),
}


def is_empty(value):
    if hasattr(value, "exists"):  # ModelMultipleChoiceField returns a queryset
        return not value.exists()
    return value is None or value == "" or value == [] or value == ()


class ApartmentSearchForm(forms.Form):
    q = forms.CharField(
        required=False, max_length=100, label="Location or keyword",
        widget=forms.TextInput(attrs={"placeholder": "Gulshan, Dhanmondi, Uttara..."}),
    )
    city = forms.CharField(required=False, max_length=100)
    area = forms.CharField(required=False, max_length=100, label="Area / neighborhood")
    min_rent = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2, label="Min rent",
                                  widget=forms.NumberInput(attrs={"placeholder": "Min", "step": "1000"}))
    max_rent = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2, label="Max rent",
                                  widget=forms.NumberInput(attrs={"placeholder": "Max", "step": "1000"}))
    bedrooms = forms.TypedChoiceField(required=False, choices=BEDROOM_CHOICES, coerce=int, empty_value=None)
    bathrooms = forms.TypedChoiceField(required=False, choices=BATHROOM_CHOICES, coerce=int, empty_value=None)
    property_type = forms.ModelChoiceField(
        required=False, queryset=PropertyType.objects.all(), to_field_name="slug", empty_label="Any type"
    )
    availability = forms.ChoiceField(required=False, choices=ANY + list(Apartment.Availability.choices))
    furnishing = forms.ChoiceField(required=False, choices=ANY + list(Apartment.Furnishing.choices))
    tenant_preference = forms.ChoiceField(
        required=False, label="Suitable for",
        choices=ANY + [("family", "Family"), ("bachelor", "Bachelor"), ("female", "Female")],
    )
    min_size = forms.IntegerField(required=False, min_value=0, label="Min size (sq ft)")
    amenities = forms.ModelMultipleChoiceField(
        required=False, queryset=Amenity.objects.all(), to_field_name="slug", widget=forms.CheckboxSelectMultiple
    )
    sort = forms.ChoiceField(required=False, choices=[(k, v[0]) for k, v in SORT_OPTIONS.items()])

    # Fields shown in the collapsible "More filters" panel.
    advanced_fields = ("area", "bathrooms", "availability", "tenant_preference", "furnishing", "min_size", "amenities")

    def clean(self):
        cleaned = super().clean()
        low, high = cleaned.get("min_rent"), cleaned.get("max_rent")
        if low is not None and high is not None and low > high:
            self.add_error("max_rent", "Max rent must be greater than min rent.")
        return cleaned

    def active_filter_count(self):
        if not hasattr(self, "cleaned_data"):
            return 0
        return sum(1 for name, value in self.cleaned_data.items() if name != "sort" and not is_empty(value))

    def advanced_active(self):
        data = getattr(self, "cleaned_data", {})
        return any(not is_empty(data.get(name)) for name in self.advanced_fields)


def _keyword(qs, value):
    for term in value.split()[:5]:
        qs = qs.filter(
            Q(title__icontains=term) | Q(city__icontains=term) | Q(area__icontains=term)
            | Q(address__icontains=term) | Q(description__icontains=term)
        )
    return qs


def _amenities(qs, amenities):
    for amenity in amenities:  # listing must have *all* selected amenities
        qs = qs.filter(amenities=amenity)
    return qs


FILTERS = {
    "q": _keyword,
    "city": lambda qs, v: qs.filter(city__iexact=v.strip()),
    "area": lambda qs, v: qs.filter(area__icontains=v.strip()),
    "min_rent": lambda qs, v: qs.filter(rent__gte=v),
    "max_rent": lambda qs, v: qs.filter(rent__lte=v),
    "bedrooms": lambda qs, v: qs.filter(bedrooms__gte=v),
    "bathrooms": lambda qs, v: qs.filter(bathrooms__gte=v),
    "property_type": lambda qs, v: qs.filter(property_type=v),
    "availability": lambda qs, v: qs.filter(availability=v),
    "furnishing": lambda qs, v: qs.filter(furnishing=v),
    # "Anyone" listings suit every household type.
    "tenant_preference": lambda qs, v: qs.filter(tenant_preference__in=[v, Apartment.TenantPreference.ANY]),
    "min_size": lambda qs, v: qs.filter(size_sqft__gte=v),
    "amenities": _amenities,
}


def apply_filters(queryset, cleaned_data):
    for name, filter_func in FILTERS.items():
        value = cleaned_data.get(name)
        if is_empty(value):
            continue
        queryset = filter_func(queryset, value)
    sort_key = cleaned_data.get("sort") or "newest"
    return queryset.order_by(*SORT_OPTIONS.get(sort_key, SORT_OPTIONS["newest"])[1])
