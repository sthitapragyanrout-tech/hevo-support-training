from django.urls import path

from . import authoring_views as v

app_name = "authoring_api"

urlpatterns = [
    path("activity-types/", v.ActivityTypeListView.as_view(), name="activity-types"),
    path("courses/", v.CourseListCreateView.as_view(), name="courses"),
    path("courses/<int:pk>/", v.CourseDetailView.as_view(), name="course"),
    path("courses/<int:pk>/draft/", v.StartDraftView.as_view(), name="start-draft"),
    path("courses/<int:pk>/preview/", v.CoursePreviewView.as_view(), name="preview"),
    path("courses/<int:pk>/nodes/", v.NodeCreateView.as_view(), name="node-create"),
    path("courses/<int:pk>/publish-checklist/", v.PublishChecklistView.as_view(), name="checklist"),
    path("courses/<int:pk>/submit/", v.SubmitView.as_view(), name="submit"),
    path("courses/<int:pk>/publish/", v.PublishView.as_view(), name="publish"),
    path("courses/<int:pk>/return-to-draft/", v.ReturnToDraftView.as_view(), name="return"),
    path("courses/<int:pk>/import/preview/", v.ImportPreviewView.as_view(), name="import-preview"),
    path("courses/<int:pk>/import/commit/", v.ImportCommitView.as_view(), name="import-commit"),
    path("nodes/<int:pk>/", v.NodeDetailView.as_view(), name="node"),
    path("nodes/<int:pk>/impact/", v.NodeImpactView.as_view(), name="node-impact"),
    path("nodes/<int:pk>/order/", v.NodeOrderView.as_view(), name="node-order"),
    path("nodes/<int:pk>/activities/", v.NodeActivitiesView.as_view(), name="node-activities"),
    path(
        "nodes/<int:pk>/activities/order/",
        v.NodeActivitiesOrderView.as_view(),
        name="node-activities-order",
    ),
    path("activities/<int:pk>/", v.ActivityDetailView.as_view(), name="activity"),
]
