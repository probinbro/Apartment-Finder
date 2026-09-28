from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [
    path("", include("core.urls")),
    path("", include("users.urls")),
    path("apartments/", include("apartments.urls")),
    path("bookings/", include("bookings.urls")),
    path("manage/", include("admin_panel.urls")),
]

if settings.DEBUG:
    # Serves locally stored uploads when Supabase Storage is not configured.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "core.views.error_403_view"
handler404 = "core.views.error_404_view"
handler500 = "core.views.error_500_view"
