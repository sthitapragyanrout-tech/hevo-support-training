from django.urls import path

from . import stream

app_name = "media_api"

urlpatterns = [
    path("<int:pk>/video/", stream.MediaStreamView.as_view(), name="video"),
    path("<int:pk>/poster/", stream.MediaPosterView.as_view(), name="poster"),
]
