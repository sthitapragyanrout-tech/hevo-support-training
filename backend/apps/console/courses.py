"""Courses back-office: every course in every state, its version history, and
archive/restore. Authoring itself stays in Studio — these screens are for
overseeing what exists, not for editing it."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.rbac import can
from apps.audit import services as audit
from apps.catalog import services
from apps.catalog.models import Activity, ContentNode, Course, CourseVersion
from apps.progress.models import ActivityProgress, LessonCompletion

from .base import ConsoleView, paginate

AUTHOR = "catalog.author_content"
PUBLISH = "catalog.publish_courseversion"

STATUS_FILTERS = {"draft", "in_review", "published", "published_with_draft", "archived"}


def _queryset():
    return Course.objects.select_related("created_by").prefetch_related(
        Prefetch(
            "versions",
            queryset=CourseVersion.objects.select_related(
                "root_node", "published_by", "submitted_by"
            ),
        )
    )


def _title(course: Course) -> str:
    versions = list(course.versions.all())
    newest = max(versions, key=lambda v: v.version, default=None)
    return newest.root_node.title if newest and newest.root_node else course.slug


def _status(course: Course) -> dict[str, str]:
    if course.archived_at is not None:
        return {"key": "archived", "label": "Archived"}
    result = services.course_status(course)
    return {"key": result.key, "label": result.label}


def _who(user) -> str | None:
    return (user.email or user.username) if user else None


def course_row(course: Course) -> dict[str, Any]:
    versions = list(course.versions.all())
    published = [v for v in versions if v.state == CourseVersion.State.PUBLISHED]
    return {
        "id": course.pk,
        "title": _title(course),
        "slug": course.slug,
        "status": _status(course),
        "created_by": _who(course.created_by),
        "created_at": course.created_at.isoformat(),
        "archived_at": course.archived_at.isoformat() if course.archived_at else None,
        "versions": len(versions),
        "published_version": max((v.version for v in published), default=None),
    }


class CourseListView(ConsoleView):
    required_any = (AUTHOR, PUBLISH)

    def get(self, request: Request) -> Response:
        params = request.query_params
        courses = list(_queryset().order_by("-created_at", "-pk"))
        search = params.get("search", "").strip().lower()
        wanted = params.get("status", "")
        rows = []
        for course in courses:
            row = course_row(course)
            if search and search not in row["title"].lower() and search not in course.slug:
                continue
            if wanted in STATUS_FILTERS and row["status"]["key"] != wanted:
                continue
            rows.append(row)
        page, meta = paginate(request, rows)
        return Response({"results": page, **meta})


def _version_rows(course: Course) -> list[dict[str, Any]]:
    versions = sorted(course.versions.all(), key=lambda v: -v.version)
    ids = [v.pk for v in versions]
    lessons = dict(
        ContentNode.objects.filter(course_version_id__in=ids, kind=ContentNode.Kind.TOPIC)
        .values_list("course_version_id")
        .annotate(n=Count("pk"))
    )
    activities = dict(
        Activity.objects.filter(content_node__course_version_id__in=ids)
        .values_list("content_node__course_version_id")
        .annotate(n=Count("pk"))
    )
    learners: dict[int, set[int]] = defaultdict(set)
    for version_id, user_id in ActivityProgress.objects.filter(
        activity__content_node__course_version_id__in=ids
    ).values_list("activity__content_node__course_version_id", "user_id"):
        learners[version_id].add(user_id)
    for version_id, user_id in LessonCompletion.objects.filter(
        node__course_version_id__in=ids
    ).values_list("node__course_version_id", "user_id"):
        learners[version_id].add(user_id)
    return [
        {
            "id": v.pk,
            "number": v.version,
            "state": v.state,
            "state_label": v.get_state_display(),
            "title": v.root_node.title if v.root_node else None,
            "lessons": lessons.get(v.pk, 0),
            "activities": activities.get(v.pk, 0),
            "learners": len(learners[v.pk]),
            "submitted_at": v.submitted_at.isoformat() if v.submitted_at else None,
            "submitted_by": _who(v.submitted_by),
            "published_at": v.published_at.isoformat() if v.published_at else None,
            "published_by": _who(v.published_by),
        }
        for v in versions
    ]


class CourseDetailView(ConsoleView):
    required_any = (AUTHOR, PUBLISH)

    def get(self, request: Request, course_id: int) -> Response:
        course = get_object_or_404(_queryset(), pk=course_id)
        return Response(
            {
                **course_row(course),
                "versions_history": _version_rows(course),
                "can_archive": request.user.is_superuser or bool(self._can(request, PUBLISH)),
            }
        )

    @staticmethod
    def _can(request: Request, action: str) -> bool:

        return can(request.user, action)


class _ArchiveBase(ConsoleView):
    required_action = PUBLISH
    archive = True

    def post(self, request: Request, course_id: int) -> Response:
        course = get_object_or_404(_queryset(), pk=course_id)
        changed = (
            services.archive_course(course) if self.archive else services.restore_course(course)
        )
        if changed:
            audit.record(
                request,
                "courses.archive" if self.archive else "courses.restore",
                target_type="course",
                target_id=course.pk,
                target_label=_title(course),
            )
        course = _queryset().get(pk=course_id)
        return Response(course_row(course), status=status.HTTP_200_OK)


class CourseArchiveView(_ArchiveBase):
    archive = True


class CourseRestoreView(_ArchiveBase):
    archive = False
