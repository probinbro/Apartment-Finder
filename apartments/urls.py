from django.urls import path

from . import owner_views, views

app_name = "apartments"

urlpatterns = [
    path("", views.apartment_list_view, name="list"),
    path("list-your-home/", owner_views.submit_listing_view, name="submit"),
    path("my-listings/", owner_views.my_listings_view, name="my_listings"),
    path("my-listings/<int:pk>/edit/", owner_views.edit_listing_view, name="edit_listing"),
    path("my-listings/<int:pk>/delete/", owner_views.delete_listing_view, name="delete_listing"),
    path("my-listings/<int:pk>/photos/<int:image_pk>/delete/", owner_views.delete_listing_photo_view, name="delete_listing_photo"),
    path("<slug:slug>/save/", views.toggle_save_view, name="toggle_save"),
    path("<slug:slug>/", views.apartment_detail_view, name="detail"),
]
