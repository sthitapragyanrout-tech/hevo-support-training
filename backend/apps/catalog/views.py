from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CourseVersion
from .serializers import CourseSummarySerializer, build_course_tree


def _published_versions():
    # Learners only ever see published versions; drafts stay admin-side.
    # root_node is nullable until authoring finishes, so exclude half-built ones.
    # An archived course is retired: gone from learners' lists and unreachable.
    return CourseVersion.objects.filter(
        state=CourseVersion.State.PUBLISHED,
        root_node__isnull=False,
        course__archived_at__isnull=True,
    ).select_related("root_node")


class CourseListView(APIView):
    """GET /api/v1/catalog/courses/ — published courses, newest version first."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(CourseSummarySerializer(_published_versions(), many=True).data)


class CourseTreeView(APIView):
    """GET /api/v1/catalog/courses/<id>/ — the full nested tree for one version."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: int) -> Response:
        version = get_object_or_404(_published_versions(), pk=pk)
        return Response(build_course_tree(version))
