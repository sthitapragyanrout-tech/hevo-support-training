"""
The Studio's API. Every endpoint is keyed by *course* (and node/activity ids
within it) — a version is something the server resolves ("the course's open
draft"), never something the client picks. All writes go through
`catalog.services`; this module only authorises, validates input and shapes
responses.

Authorization: every view passes the `Course` into `can()` so the
object-scoping seam in `accounts.rbac` can later restrict trainers to their
own courses. Today any trainer may edit any course.
"""

from __future__ import annotations

import json
from typing import Any

from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import CanPermission
from apps.accounts.rbac import can
from apps.activities import registry

from . import importer, services
from .models import Activity, ContentNode, Course, CourseVersion
from .serializers import AuthoringActivitySerializer, build_course_tree

AUTHOR = "catalog.author_content"
PUBLISH = "catalog.publish_courseversion"
_OPEN_STATES = {s.value for s in CourseVersion.OPEN_STATES}


# ------------------------------------------------------------------- helpers


class AuthoringView(APIView):
    """Authenticated + `required_action` via `can()`; maps domain errors to
    HTTP responses with an author-safe `detail`."""

    permission_classes = [IsAuthenticated, CanPermission]
    required_action = AUTHOR

    def handle_exception(self, exc):
        if isinstance(exc, services.AuthoringError):
            return Response({"detail": exc.message}, status=exc.status_code)
        return super().handle_exception(exc)

    def authorize(self, request: Request, course: Course, action: str | None = None) -> None:
        if not can(request.user, action or self.required_action, course):
            raise PermissionDenied()


def _courses_qs():
    return Course.objects.prefetch_related(
        Prefetch("versions", queryset=CourseVersion.objects.select_related("root_node"))
    )


def _display_version(course: Course) -> CourseVersion | None:
    """The version an author is looking at: the open draft / review, else the
    newest published, else the newest of anything."""
    versions = list(course.versions.all())  # prefetched, newest first via Meta.ordering
    for state_group in (CourseVersion.OPEN_STATES, (CourseVersion.State.PUBLISHED,), None):
        for v in versions:
            if state_group is None or v.state in state_group:
                return v
    return None


def _status(course: Course) -> dict[str, Any]:
    result = services.course_status(course)
    return {"key": result.key, "label": result.label}


def _title(course: Course) -> str:
    version = _display_version(course)
    return version.root_node.title if version and version.root_node else course.slug


def _course_summary(course: Course) -> dict[str, Any]:
    return {
        "id": course.id,
        "slug": course.slug,
        "title": _title(course),
        "status": _status(course),
    }


def _version_payload(version: CourseVersion | None) -> dict[str, Any] | None:
    if version is None:
        return None
    return {
        "number": version.version,
        "state": version.state,
        "published_at": version.published_at,
        "submitted_at": version.submitted_at,
        "submitted_by": version.submitted_by.email if version.submitted_by else None,
    }


def _course_detail(course: Course, user) -> dict[str, Any]:
    course = _courses_qs().get(pk=course.pk)
    status_ = services.course_status(course)
    shown = _display_version(course)
    can_author = can(user, AUTHOR, course)
    can_publish = can(user, PUBLISH, course)
    editable = bool(shown and shown.is_editable)
    return {
        **_course_summary(course),
        "version": _version_payload(shown),
        "published_version": _version_payload(status_.published_version),
        "editable": editable and can_author,
        "actions": {
            "start_draft": can_author and status_.key == "published",
            "submit": can_author and editable,
            "publish": can_publish and shown is not None and shown.state in _OPEN_STATES,
            "return_to_draft": can_publish and shown is not None and shown.state == "in_review",
        },
        "tree": build_course_tree(shown, authoring=True) if shown else None,
    }


def _node_payload(node: ContentNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "kind": node.kind,
        "title": node.title,
        "slug": node.slug,
        "description": node.description,
        "estimated_minutes": node.estimated_minutes,
        "is_required": node.is_required,
        "order": node.order,
    }


def _course_of(node: ContentNode) -> Course:
    return node.course_version.course


# ------------------------------------------------------------ input shapes


class CourseCreateInput(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")


class OverviewInput(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)


class NodeCreateInput(serializers.Serializer):
    parent = serializers.IntegerField()  # type: ignore[assignment]  # API name; shadows Field.parent
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    estimated_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    is_required = serializers.BooleanField(required=False, default=True)


class NodeUpdateInput(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    estimated_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    is_required = serializers.BooleanField(required=False)


class OrderInput(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField())


class ActivityCreateInput(serializers.Serializer):
    activity_type = serializers.CharField()
    title = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    config = serializers.JSONField(required=False)
    is_required = serializers.BooleanField(required=False)
    points = serializers.IntegerField(required=False, min_value=0)
    max_attempts = serializers.IntegerField(required=False, min_value=0)
    mastery_threshold = serializers.FloatField(
        required=False, allow_null=True, min_value=0.0, max_value=1.0
    )


class ActivityUpdateInput(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    config = serializers.JSONField(required=False)
    is_required = serializers.BooleanField(required=False)
    points = serializers.IntegerField(required=False, min_value=0)
    max_attempts = serializers.IntegerField(required=False, min_value=0)
    mastery_threshold = serializers.FloatField(
        required=False, allow_null=True, min_value=0.0, max_value=1.0
    )


def _validated(serializer_class, request: Request, *, partial: bool = False) -> dict[str, Any]:
    serializer = serializer_class(data=request.data, partial=partial)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


# ------------------------------------------------------------------ courses


class ActivityTypeListView(AuthoringView):
    def get(self, request: Request) -> Response:
        return Response(registry.list_types())


def _structure_counts(courses: list[Course]) -> dict[int, dict[str, int]]:
    """{course_id: {"modules": n, "lessons": n}} for each course's displayed
    version, in one query (for the list screen)."""
    version_to_course = {}
    for course in courses:
        version = _display_version(course)
        if version is not None:
            version_to_course[version.id] = course.id
    rows = (
        ContentNode.objects.filter(
            course_version_id__in=version_to_course,
            kind__in=[ContentNode.Kind.SEGMENT, ContentNode.Kind.TOPIC],
        )
        .values("course_version_id", "kind")
        .annotate(n=Count("id"))
    )
    counts: dict[int, dict[str, int]] = {c.id: {"modules": 0, "lessons": 0} for c in courses}
    for row in rows:
        key = "modules" if row["kind"] == ContentNode.Kind.SEGMENT else "lessons"
        counts[version_to_course[row["course_version_id"]]][key] = row["n"]
    return counts


class CourseListCreateView(AuthoringView):
    def get(self, request: Request) -> Response:
        courses = list(_courses_qs().filter(archived_at__isnull=True).order_by("-created_at"))
        counts = _structure_counts(courses)
        return Response([{**_course_summary(c), **counts[c.id]} for c in courses])

    def post(self, request: Request) -> Response:
        data = _validated(CourseCreateInput, request)
        course = services.create_course(
            title=data["title"], description=data["description"], user=request.user
        )
        return Response(_course_detail(course, request.user), status=status.HTTP_201_CREATED)


class CourseDetailView(AuthoringView):
    def get(self, request: Request, pk: int) -> Response:
        course = get_object_or_404(Course, pk=pk)
        self.authorize(request, course)
        return Response(_course_detail(course, request.user))

    def patch(self, request: Request, pk: int) -> Response:
        course = get_object_or_404(Course, pk=pk)
        self.authorize(request, course)
        data = _validated(OverviewInput, request, partial=True)
        version = services.open_version(course)
        if version is None:
            raise services.NotEditable("Start a new draft to make changes.")
        services.update_overview(
            version, title=data.get("title"), description=data.get("description")
        )
        return Response(_course_detail(course, request.user))


class StartDraftView(AuthoringView):
    def post(self, request: Request, pk: int) -> Response:
        course = get_object_or_404(Course, pk=pk)
        self.authorize(request, course)
        services.get_or_create_draft(course)
        return Response(_course_detail(course, request.user), status=status.HTTP_201_CREATED)


class CoursePreviewView(AuthoringView):
    """The draft in the *learner* payload shape (activity config stripped),
    so the SPA can mount the real learner screens on it."""

    def get(self, request: Request, pk: int) -> Response:
        course = _courses_qs().get(pk=pk) if Course.objects.filter(pk=pk).exists() else None
        if course is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        self.authorize(request, course)
        version = _display_version(course)
        if version is None or version.root_node is None:
            return Response({"detail": "Nothing to preview yet."}, status=status.HTTP_404_NOT_FOUND)
        return Response(build_course_tree(version))


# ------------------------------------------------------------ review/publish


class PublishChecklistView(AuthoringView):
    def get(self, request: Request, pk: int) -> Response:
        course = get_object_or_404(Course, pk=pk)
        self.authorize(request, course)
        version = services.open_version(course)
        if version is None:
            return Response({"ok": True, "issues": []})
        issues = services.publish_checklist(version)
        return Response(
            {
                "ok": not any(i.level == "error" for i in issues),
                "issues": [
                    {"message": i.message, "node_id": i.node_id, "level": i.level} for i in issues
                ],
            }
        )


class SubmitView(AuthoringView):
    def post(self, request: Request, pk: int) -> Response:
        course = get_object_or_404(Course, pk=pk)
        self.authorize(request, course)
        version = services.open_version(course)
        if version is None:
            raise services.NotEditable("There is no draft to submit.")
        services.submit_for_publish(version, request.user)
        return Response(_course_detail(course, request.user))


class PublishView(AuthoringView):
    required_action = PUBLISH

    def post(self, request: Request, pk: int) -> Response:
        course = get_object_or_404(Course, pk=pk)
        self.authorize(request, course)
        version = services.open_version(course)
        if version is None:
            raise services.NotEditable("There is no draft to publish.")
        services.publish_version(version, request.user)
        return Response(_course_detail(course, request.user))


class ReturnToDraftView(AuthoringView):
    required_action = PUBLISH

    def post(self, request: Request, pk: int) -> Response:
        course = get_object_or_404(Course, pk=pk)
        self.authorize(request, course)
        version = services.open_version(course)
        if version is None:
            raise services.InvalidOperation("There is nothing to return.")
        services.return_to_draft(version)
        return Response(_course_detail(course, request.user))


# -------------------------------------------------------------------- nodes


class NodeCreateView(AuthoringView):
    def post(self, request: Request, pk: int) -> Response:
        course = get_object_or_404(Course, pk=pk)
        self.authorize(request, course)
        data = _validated(NodeCreateInput, request)
        parent = get_object_or_404(
            ContentNode.objects.select_related("course_version"),
            pk=data.pop("parent"),
            course_version__course=course,
        )
        node = services.add_node(parent, **data)
        return Response(_node_payload(node), status=status.HTTP_201_CREATED)


class NodeDetailView(AuthoringView):
    def _node(self, request: Request, pk: int) -> ContentNode:
        node = get_object_or_404(
            ContentNode.objects.select_related("course_version__course"), pk=pk
        )
        self.authorize(request, _course_of(node))
        return node

    def patch(self, request: Request, pk: int) -> Response:
        node = self._node(request, pk)
        changes = _validated(NodeUpdateInput, request, partial=True)
        return Response(_node_payload(services.update_node(node, **changes)))

    def delete(self, request: Request, pk: int) -> Response:
        services.delete_node(self._node(request, pk))
        return Response(status=status.HTTP_204_NO_CONTENT)


class NodeImpactView(AuthoringView):
    def get(self, request: Request, pk: int) -> Response:
        node = get_object_or_404(
            ContentNode.objects.select_related("course_version__course"), pk=pk
        )
        self.authorize(request, _course_of(node))
        return Response(services.node_impact(node))


class NodeOrderView(AuthoringView):
    def put(self, request: Request, pk: int) -> Response:
        parent = get_object_or_404(
            ContentNode.objects.select_related("course_version__course"), pk=pk
        )
        self.authorize(request, _course_of(parent))
        ids = _validated(OrderInput, request)["ids"]
        services.reorder_children(parent, ids)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------- activities


class NodeActivitiesView(AuthoringView):
    def post(self, request: Request, pk: int) -> Response:
        node = get_object_or_404(
            ContentNode.objects.select_related("course_version__course"), pk=pk
        )
        self.authorize(request, _course_of(node))
        data = _validated(ActivityCreateInput, request)
        activity = services.add_activity(node, **data)
        return Response(AuthoringActivitySerializer(activity).data, status=status.HTTP_201_CREATED)


class NodeActivitiesOrderView(AuthoringView):
    def put(self, request: Request, pk: int) -> Response:
        node = get_object_or_404(
            ContentNode.objects.select_related("course_version__course"), pk=pk
        )
        self.authorize(request, _course_of(node))
        services.reorder_activities(node, _validated(OrderInput, request)["ids"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ActivityDetailView(AuthoringView):
    def _activity(self, request: Request, pk: int) -> Activity:
        activity = get_object_or_404(
            Activity.objects.select_related("content_node__course_version__course"), pk=pk
        )
        self.authorize(request, _course_of(activity.content_node))
        return activity

    def patch(self, request: Request, pk: int) -> Response:
        activity = self._activity(request, pk)
        changes = _validated(ActivityUpdateInput, request, partial=True)
        updated = services.update_activity(activity, **changes)
        return Response(AuthoringActivitySerializer(updated).data)

    def delete(self, request: Request, pk: int) -> Response:
        services.delete_activity(self._activity(request, pk))
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------- import


def _read_upload(request: Request) -> tuple[list[str], list[list[str]], dict[str, str | None]]:
    upload = request.FILES.get("file")
    if upload is None:
        raise importer.ImportFileError("Choose a .csv or .xlsx file to upload.")
    headers, rows = importer.read_table(upload.name, upload.read())
    mapping = importer.suggest_mapping(headers)
    supplied = request.POST.get("mapping")
    if supplied:
        try:
            override = json.loads(supplied) if isinstance(supplied, str) else dict(supplied)
        except (ValueError, TypeError) as exc:
            raise importer.ImportFileError("The column mapping couldn't be read.") from exc
        for field_name in importer.FIELDS:
            if field_name in override:
                value = override[field_name]
                mapping[field_name] = value if value in headers else None
    return headers, rows, mapping


class ImportPreviewView(AuthoringView):
    """Parse + validate an upload and show what *would* be created. Writes nothing."""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request, pk: int) -> Response:
        course = get_object_or_404(Course, pk=pk)
        self.authorize(request, course)
        headers, rows, mapping = _read_upload(request)
        plan = importer.build_plan(headers, rows, mapping)
        return Response(
            {
                "headers": headers,
                "mapping": mapping,
                "counts": plan.counts,
                "outline": plan.outline(),
                "errors": [{"row": m.row, "message": m.message} for m in plan.errors],
                "warnings": [{"row": m.row, "message": m.message} for m in plan.warnings],
                "ok": not plan.errors,
            }
        )


class ImportCommitView(AuthoringView):
    """Re-validate the same upload + mapping and append it to the open draft,
    all-or-nothing."""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request, pk: int) -> Response:
        course = get_object_or_404(Course, pk=pk)
        self.authorize(request, course)
        version = services.open_version(course)
        if version is None:
            raise services.NotEditable("Start a new draft to import into.")
        headers, rows, mapping = _read_upload(request)
        plan = importer.build_plan(headers, rows, mapping)
        counts = importer.apply_plan(version, plan)
        return Response(
            {"counts": counts, "course": _course_detail(course, request.user)},
            status=status.HTTP_201_CREATED,
        )
