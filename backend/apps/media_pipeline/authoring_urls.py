from django.urls import path

from . import views

app_name = "media_authoring_api"

urlpatterns = [
    path("", views.MediaUploadView.as_view(), name="upload"),
    path("limits/", views.MediaLimitsView.as_view(), name="limits"),
    path("<int:pk>/", views.MediaDetailView.as_view(), name="detail"),
    path("<int:pk>/retry/", views.MediaRetryView.as_view(), name="retry"),
]
