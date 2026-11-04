from django.urls import path

from . import views

app_name = "rated_sim_api"

urlpatterns = [
    path("activities/<int:pk>/", views.ActivityView.as_view(), name="activity"),
    path("activities/<int:pk>/open/", views.OpenView.as_view(), name="open"),
    path("activities/<int:pk>/submissions/", views.SubmitView.as_view(), name="submit"),
    path("submissions/<int:pk>/withdraw/", views.WithdrawView.as_view(), name="withdraw"),
    path("files/<uuid:file_id>/", views.FileView.as_view(), name="file"),
]
