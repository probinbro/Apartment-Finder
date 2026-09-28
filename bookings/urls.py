from django.urls import path

from . import views

app_name = "bookings"

urlpatterns = [
    path("book/<slug:slug>/", views.book_view, name="book"),
    path("my-bookings/", views.my_bookings_view, name="my_bookings"),
    path("my-bookings/<int:pk>/cancel/", views.cancel_booking_view, name="cancel"),
    path("requests/", views.landlord_requests_view, name="landlord_requests"),
    path("requests/<int:pk>/respond/", views.respond_view, name="respond"),
    path("requests/<int:pk>/complete/", views.complete_view, name="complete"),
]
