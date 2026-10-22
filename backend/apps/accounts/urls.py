from django.urls import path

from . import views

app_name = "accounts_api"

urlpatterns = [
    path("session/", views.SessionView.as_view(), name="session"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("password/", views.ChangePasswordView.as_view(), name="password"),
]
