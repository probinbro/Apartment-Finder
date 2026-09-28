from django.urls import path

from . import views

app_name = "admin_panel"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("requests/", views.request_list_view, name="requests"),
    path("requests/<int:pk>/", views.request_review_view, name="request_review"),
    path("apartments/", views.apartment_list_view, name="apartments"),
    path("apartments/new/", views.apartment_create_view, name="apartment_create"),
    path("apartments/<int:pk>/edit/", views.apartment_edit_view, name="apartment_edit"),
    path("apartments/<int:pk>/delete/", views.apartment_delete_view, name="apartment_delete"),
    path("apartments/<int:pk>/status/", views.apartment_set_status_view, name="apartment_status"),
    path("apartments/<int:pk>/images/", views.apartment_images_view, name="apartment_images"),
    path("images/<int:pk>/primary/", views.image_set_primary_view, name="image_primary"),
    path("images/<int:pk>/delete/", views.image_delete_view, name="image_delete"),
    path("images/<int:pk>/replace/", views.image_replace_view, name="image_replace"),
    path("images/<int:pk>/caption/", views.image_caption_view, name="image_caption"),
    path("media/", views.media_view, name="media"),
    path("users/", views.user_list_view, name="users"),
    path("users/<int:pk>/", views.user_edit_view, name="user_edit"),
    path("taxonomy/", views.taxonomy_view, name="taxonomy"),
    path("taxonomy/<str:kind>/<int:pk>/delete/", views.taxonomy_delete_view, name="taxonomy_delete"),
    path("messages/", views.message_list_view, name="messages"),
    path("messages/<int:pk>/", views.message_action_view, name="message_action"),
]
