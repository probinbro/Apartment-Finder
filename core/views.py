from django.contrib import messages
from django.db.models import Count
from django.shortcuts import redirect, render

from apartments.filters import ApartmentSearchForm
from apartments.models import Apartment

from .forms import ContactForm


def home_view(request):
    published = Apartment.objects.published()
    featured = list(published.filter(is_featured=True).with_cover()[:6])
    if len(featured) < 3:
        featured = list(published.with_cover().order_by("-published_at", "-created_at")[:6])

    context = {
        "search_form": ApartmentSearchForm(),
        "featured": featured,
        "locations": published.values("city").annotate(count=Count("id")).order_by("-count", "city")[:8],
        "listing_count": published.count(),
    }
    return render(request, "core/home.html", context)


def about_view(request):
    return render(request, "core/about.html")


def contact_view(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not form.is_spam():
            form.save()
        messages.success(request, "Thanks for reaching out! We'll get back to you soon.")
        return redirect("core:contact")
    return render(request, "core/contact.html", {"form": form})


def error_403_view(request, exception=None):
    return render(request, "errors/403.html", status=403)


def error_404_view(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_500_view(request):
    return render(request, "errors/500.html", status=500)


def csrf_failure_view(request, reason=""):
    return render(request, "errors/403.html", {"csrf_failure": True}, status=403)
