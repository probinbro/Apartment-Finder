from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("auth/callback/", views.auth_callback_view, name="auth_callback"),
    path("auth/<str:provider>/start/", views.oauth_start_view, name="oauth_start"),
    path("auth/session/", views.auth_session_view, name="auth_session"),
    path("account/", views.dashboard_view, name="dashboard"),
    path("account/profile/", views.profile_view, name="profile"),
    path("account/saved/", views.saved_apartments_view, name="saved"),
]
