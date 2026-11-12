from django.urls import path

from . import views

app_name = "notifications_api"

urlpatterns = [
    path("", views.ListView.as_view(), name="list"),
    path("unread-count/", views.UnreadCountView.as_view(), name="unread-count"),
    path("read-all/", views.ReadAllView.as_view(), name="read-all"),
    path("<int:pk>/read/", views.ReadView.as_view(), name="read"),
]
