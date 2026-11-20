from django.urls import path

from . import views

app_name = "certificates_api"

urlpatterns = [
    path("<str:code>/", views.CertificateView.as_view(), name="certificate"),
]
