from django.urls import path

from . import views

app_name = "catalog_api"

urlpatterns = [
    path("courses/", views.CourseListView.as_view(), name="course-list"),
    path("courses/<int:pk>/", views.CourseTreeView.as_view(), name="course-tree"),
]
