"""URL configuration."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from . import admin_site  # noqa: F401 — restricts Django Admin and orders its sidebar

urlpatterns = [
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/catalog/", include("apps.catalog.urls")),
    path("api/v1/authoring/", include("apps.catalog.authoring_urls")),
    path("api/v1/progress/", include("apps.progress.urls")),
    path("api/v1/admin/", include("apps.console.urls")),
]

if settings.ENABLE_DJANGO_ADMIN:
    # Emergency access, superusers only. The SPA owns /admin.
    urlpatterns.append(path("django-admin/", admin.site.urls))
