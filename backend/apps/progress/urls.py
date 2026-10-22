from django.urls import path

from . import views

app_name = "progress_api"

urlpatterns = [
    path("courses/<int:version_id>/", views.CourseProgressView.as_view(), name="course"),
    path("activities/<int:pk>/start/", views.ActivityStartView.as_view(), name="activity-start"),
    path(
        "activities/<int:pk>/complete/",
        views.ActivityCompleteView.as_view(),
        name="activity-complete",
    ),
    path(
        "activities/<int:pk>/attempts/",
        views.ActivityAttemptView.as_view(),
        name="activity-attempts",
    ),
    path("lessons/<int:pk>/complete/", views.LessonCompleteView.as_view(), name="lesson-complete"),
]
