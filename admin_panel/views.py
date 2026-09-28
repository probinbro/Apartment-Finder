"""
Administration dashboard. Every view is wrapped in `admin_required`, which
checks the role stored in the database — never anything sent by the client.
"""

import logging

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, ProtectedError, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apartments import services as image_services
from apartments.forms import ApartmentForm, ImageCaptionForm, ImageReplaceForm, ImageUploadForm
from apartments.models import Amenity, Apartment, ApartmentImage, PropertyType
from core.models import ContactMessage
from core.supabase.client import SupabaseAdminClient, SupabaseError, is_admin_configured
from users.models import User
from users.permissions import admin_required

from .forms import AmenityForm, PropertyTypeForm, ReviewForm, UserAdminForm

logger = logging.getLogger(__name__)

ADMIN_PAGE_SIZE = 20
UPLOAD_ERROR = "We couldn't store the image right now. Please try again."


def _redirect_back(request, fallback):
    target = request.POST.get("next")
    if target and url_has_allowed_host_and_scheme(target, {request.get_host()}, request.is_secure()):
        return redirect(target)
    return redirect(fallback)


def _paginate(request, queryset):
    return Paginator(queryset, ADMIN_PAGE_SIZE).get_page(request.GET.get("page"))


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


@admin_required
def dashboard_view(request):
    status_counts = dict(Apartment.objects.values_list("status").annotate(n=Count("id")))
    context = {
        "stats": {
            "total": sum(status_counts.values()),
            "published": status_counts.get(Apartment.Status.PUBLISHED, 0),
            "unpublished": status_counts.get(Apartment.Status.DRAFT, 0),
            "archived": status_counts.get(Apartment.Status.ARCHIVED, 0),
            "users": User.objects.count(),
            "admins": User.objects.filter(role=User.Role.ADMIN).count(),
            "images": ApartmentImage.objects.count(),
            "unread_messages": ContactMessage.objects.filter(is_read=False).count(),
            "pending": status_counts.get(Apartment.Status.PENDING, 0),
            "rejected": status_counts.get(Apartment.Status.REJECTED, 0),
        },
        "pending_requests": Apartment.objects.filter(status=Apartment.Status.PENDING)
        .select_related("owner").with_cover().order_by("created_at")[:5],
        "recent_apartments": Apartment.objects.with_cover().order_by("-created_at")[:6],
        "recent_users": User.objects.order_by("-created_at")[:5],
    }
    stats = context["stats"]
    stats["inactive"] = stats["total"] - stats["published"]
    return render(request, "admin_panel/dashboard.html", context)


# --------------------------------------------------------------------------
# Apartments
# --------------------------------------------------------------------------


@admin_required
def apartment_list_view(request):
    queryset = Apartment.objects.with_cover().order_by("-created_at")
    status = request.GET.get("status", "")
    query = request.GET.get("q", "").strip()
    if status in Apartment.Status.values:
        queryset = queryset.filter(status=status)
    if query:
        queryset = queryset.filter(Q(title__icontains=query) | Q(city__icontains=query) | Q(area__icontains=query))
    context = {
        "page_obj": _paginate(request, queryset),
        "status": status,
        "query": query,
        "status_choices": Apartment.Status.choices,
    }
    return render(request, "admin_panel/apartments/list.html", context)


@admin_required
def apartment_create_view(request):
    form = ApartmentForm(request.POST or None, initial={"owner": request.user})
    if request.method == "POST":
        if form.is_valid():
            apartment = form.save()
            messages.success(request, f"“{apartment.title}” was created. Now add some photos.")
            return redirect("admin_panel:apartment_images", pk=apartment.pk)
        messages.error(request, "Please correct the errors below.")
    return render(request, "admin_panel/apartments/form.html", {"form": form, "is_create": True})


@admin_required
def apartment_edit_view(request, pk):
    apartment = get_object_or_404(Apartment, pk=pk)
    form = ApartmentForm(request.POST or None, instance=apartment)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, f"“{apartment.title}” was updated.")
            return redirect("admin_panel:apartments")
        messages.error(request, "Please correct the errors below.")
    return render(request, "admin_panel/apartments/form.html", {"form": form, "apartment": apartment, "is_create": False})


@admin_required
def apartment_delete_view(request, pk):
    apartment = get_object_or_404(Apartment, pk=pk)
    if request.method == "POST":
        title = apartment.title
        apartment.delete()  # images and their files are removed via cascade + signal
        messages.success(request, f"“{title}” was deleted.")
        return redirect("admin_panel:apartments")
    return render(request, "admin_panel/apartments/confirm_delete.html", {"apartment": apartment})


@admin_required
@require_POST
def apartment_set_status_view(request, pk):
    apartment = get_object_or_404(Apartment, pk=pk)
    new_status = request.POST.get("status")
    if new_status not in Apartment.Status.values:
        messages.error(request, "Invalid status.")
    else:
        apartment.status = new_status
        apartment.save(update_fields=["status", "published_at", "updated_at"])
        messages.success(request, f"“{apartment.title}” is now {apartment.get_status_display().lower()}.")
    return _redirect_back(request, "admin_panel:apartments")


# --------------------------------------------------------------------------
# Listing requests (homes submitted by users)
# --------------------------------------------------------------------------


@admin_required
def request_list_view(request):
    queryset = (
        Apartment.objects.filter(status=Apartment.Status.PENDING)
        .select_related("owner", "property_type").with_cover().order_by("created_at")
    )
    recently_reviewed = (
        Apartment.objects.filter(submitted_by_user=True, reviewed_at__isnull=False)
        .select_related("owner", "reviewed_by").order_by("-reviewed_at")[:10]
    )
    context = {"page_obj": _paginate(request, queryset), "recently_reviewed": recently_reviewed}
    return render(request, "admin_panel/requests/list.html", context)


@admin_required
def request_review_view(request, pk):
    apartment = get_object_or_404(
        Apartment.objects.select_related("owner", "property_type").prefetch_related("images", "amenities"), pk=pk
    )
    form = ReviewForm(request.POST or None, initial={"note": apartment.review_note})
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["action"] == "approve":
            apartment.approve(request.user)
            messages.success(request, f"“{apartment.title}” was approved and is now live.")
        else:
            apartment.reject(request.user, form.cleaned_data["note"].strip())
            messages.info(request, f"“{apartment.title}” was rejected. The owner will see your note.")
        return redirect("admin_panel:requests")
    return render(request, "admin_panel/requests/review.html", {"apartment": apartment, "form": form})


# --------------------------------------------------------------------------
# Apartment images
# --------------------------------------------------------------------------


@admin_required
def apartment_images_view(request, pk):
    apartment = get_object_or_404(Apartment, pk=pk)
    form = ImageUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if form.is_valid():
            try:
                created = image_services.add_images(
                    apartment, form.cleaned_data["images"], uploaded_by=request.user, caption=form.cleaned_data["caption"]
                )
            except ValidationError as exc:
                form.add_error("images", exc)
            except SupabaseError:
                logger.exception("Image upload failed for apartment %s", apartment.pk)
                messages.error(request, UPLOAD_ERROR)
            else:
                messages.success(request, f"Uploaded {len(created)} image{'s' if len(created) != 1 else ''}.")
                return redirect("admin_panel:apartment_images", pk=apartment.pk)
        if form.errors:
            messages.error(request, "Some files could not be uploaded. See the details below.")
    context = {"apartment": apartment, "images": apartment.images.all(), "form": form, "replace_form": ImageReplaceForm()}
    return render(request, "admin_panel/apartments/images.html", context)


def _image_or_404(pk):
    return get_object_or_404(ApartmentImage.objects.select_related("apartment"), pk=pk)


@admin_required
@require_POST
def image_set_primary_view(request, pk):
    image = _image_or_404(pk)
    image_services.set_primary_image(image)
    messages.success(request, "Primary image updated.")
    return _redirect_back(request, reverse("admin_panel:apartment_images", args=[image.apartment_id]))


@admin_required
@require_POST
def image_delete_view(request, pk):
    image = _image_or_404(pk)
    apartment_id = image.apartment_id
    image_services.delete_image(image)
    messages.success(request, "Image deleted.")
    return _redirect_back(request, reverse("admin_panel:apartment_images", args=[apartment_id]))


@admin_required
@require_POST
def image_replace_view(request, pk):
    image = _image_or_404(pk)
    form = ImageReplaceForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            image_services.replace_image(image, form.cleaned_data["image"])
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        except SupabaseError:
            logger.exception("Image replace failed for image %s", image.pk)
            messages.error(request, UPLOAD_ERROR)
        else:
            messages.success(request, "Image replaced.")
    else:
        messages.error(request, " ".join(form.errors.get("image", ["Invalid image."])))
    return _redirect_back(request, reverse("admin_panel:apartment_images", args=[image.apartment_id]))


@admin_required
@require_POST
def image_caption_view(request, pk):
    image = _image_or_404(pk)
    form = ImageCaptionForm(request.POST, instance=image)
    if form.is_valid():
        form.save()
        messages.success(request, "Caption saved.")
    else:
        messages.error(request, "Caption is too long (150 characters max).")
    return _redirect_back(request, reverse("admin_panel:apartment_images", args=[image.apartment_id]))


# --------------------------------------------------------------------------
# Media library
# --------------------------------------------------------------------------


@admin_required
def media_view(request):
    queryset = ApartmentImage.objects.select_related("apartment", "uploaded_by").order_by("-created_at")
    totals = queryset.aggregate(count=Count("id"), bytes=Sum("file_size"))
    context = {"page_obj": _paginate(request, queryset), "totals": totals}
    return render(request, "admin_panel/media.html", context)


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------


@admin_required
def user_list_view(request):
    queryset = User.objects.annotate(listing_count=Count("apartments")).order_by("-created_at")
    query = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    if query:
        queryset = queryset.filter(Q(email__icontains=query) | Q(full_name__icontains=query))
    if role in User.Role.values:
        queryset = queryset.filter(role=role)
    context = {"page_obj": _paginate(request, queryset), "query": query, "role": role, "role_choices": User.Role.choices}
    return render(request, "admin_panel/users/list.html", context)


@admin_required
def user_edit_view(request, pk):
    managed_user = get_object_or_404(User, pk=pk)
    is_self = managed_user.pk == request.user.pk
    was_active = managed_user.is_active
    form = UserAdminForm(request.POST or None, instance=managed_user)
    if is_self:
        # Admins cannot demote or disable themselves (prevents lock-out).
        form.fields["role"].disabled = True
        form.fields["is_active"].disabled = True

    if request.method == "POST":
        if form.is_valid():
            user = form.save()
            if user.is_active != was_active:
                _sync_supabase_ban(request, user)
            messages.success(request, f"{user.email} was updated.")
            return redirect("admin_panel:users")
        messages.error(request, "Please correct the errors below.")

    return render(request, "admin_panel/users/edit.html", {"form": form, "managed_user": managed_user, "is_self": is_self})


def _sync_supabase_ban(request, user):
    """Mirror account disabling into Supabase Auth when the service key is available."""
    if not (user.auth_user_id and is_admin_configured()):
        return
    try:
        SupabaseAdminClient().set_user_banned(user.auth_user_id, banned=not user.is_active)
    except SupabaseError:
        logger.exception("Failed to sync ban state for user %s", user.pk)
        messages.warning(request, "Saved locally, but the change could not be synced to Supabase Auth.")


# --------------------------------------------------------------------------
# Taxonomy: property types & amenities
# --------------------------------------------------------------------------


@admin_required
def taxonomy_view(request):
    type_form = PropertyTypeForm(request.POST if request.POST.get("kind") == "type" else None, prefix="type")
    amenity_form = AmenityForm(request.POST if request.POST.get("kind") == "amenity" else None, prefix="amenity")
    if request.method == "POST":
        form = type_form if request.POST.get("kind") == "type" else amenity_form
        if form.is_bound and form.is_valid():
            item = form.save()
            messages.success(request, f"“{item.name}” was added.")
            return redirect("admin_panel:taxonomy")
        messages.error(request, "Please correct the errors below.")
    context = {
        "property_types": PropertyType.objects.annotate(n=Count("apartments")),
        "amenities": Amenity.objects.annotate(n=Count("apartments")),
        "type_form": type_form,
        "amenity_form": amenity_form,
    }
    return render(request, "admin_panel/taxonomy.html", context)


@admin_required
@require_POST
def taxonomy_delete_view(request, kind, pk):
    model = {"type": PropertyType, "amenity": Amenity}.get(kind)
    if model is None:
        return redirect("admin_panel:taxonomy")
    item = get_object_or_404(model, pk=pk)
    try:
        item.delete()
    except ProtectedError:
        messages.error(request, f"“{item.name}” is used by existing listings and cannot be deleted.")
    else:
        messages.success(request, f"“{item.name}” was deleted.")
    return redirect("admin_panel:taxonomy")


# --------------------------------------------------------------------------
# Contact messages
# --------------------------------------------------------------------------


@admin_required
def message_list_view(request):
    return render(request, "admin_panel/messages.html", {"page_obj": _paginate(request, ContactMessage.objects.all())})


@admin_required
@require_POST
def message_action_view(request, pk):
    message = get_object_or_404(ContactMessage, pk=pk)
    action = request.POST.get("action")
    if action == "delete":
        message.delete()
        messages.success(request, "Message deleted.")
    elif action in ("read", "unread"):
        message.is_read = action == "read"
        message.save(update_fields=["is_read"])
    return _redirect_back(request, "admin_panel:messages")
