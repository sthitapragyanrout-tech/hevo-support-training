"""Learner results: who has done what, with which scores — and the reset."""

from __future__ import annotations

import csv

from django.contrib.auth import get_user_model
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit import services as audit
from apps.catalog.models import Activity
from apps.progress import reporting, services

from .base import ConsoleError, ConsoleView, optional_int, paginate

User = get_user_model()

VIEW_RESULTS = "progress.view_results"
MANAGE_ATTEMPTS = "progress.manage_attempts"


class ResultCoursesView(ConsoleView):
    """Courses that have a published version — the filter dropdown."""

    required_action = VIEW_RESULTS

    def get(self, request: Request) -> Response:
        return Response({"results": reporting.course_options()})


class LearnerListView(ConsoleView):
    required_action = VIEW_RESULTS

    def get(self, request: Request) -> Response:
        params = request.query_params
        qs = reporting.learners_queryset(
            search=params.get("search", "").strip(),
            course_id=optional_int(params.get("course")),
            ordering=params.get("ordering", "name"),
        )
        page, meta = paginate(request, qs)
        latest = reporting.last_activity_for([u.pk for u in page])
        return Response(
            {"results": [reporting.learner_row(u, latest.get(u.pk)) for u in page], **meta}
        )


class LearnerDetailView(ConsoleView):
    required_action = VIEW_RESULTS

    def get(self, request: Request, user_id: int) -> Response:
        user = get_object_or_404(User, pk=user_id)
        return Response(reporting.learner_detail(user))


class ResetAttemptsView(ConsoleView):
    """Wipe one learner's tries at one quiz so they can take it again."""

    required_action = MANAGE_ATTEMPTS

    def delete(self, request: Request, user_id: int, activity_id: int) -> Response:
        learner = get_object_or_404(User, pk=user_id)
        try:
            removed = services.reset_attempts_for(learner, activity_id)
        except services.ProgressError as exc:
            raise ConsoleError(exc.message, exc.status_code) from exc
        activity = Activity.objects.get(pk=activity_id)
        audit.record(
            request,
            "results.reset_attempts",
            target_type="activity",
            target_id=activity_id,
            target_label=f"{learner.email} · {activity.title}",
            changes={"learner": learner.email, **removed},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class QuizListView(ConsoleView):
    required_action = VIEW_RESULTS

    def get(self, request: Request) -> Response:
        rows = reporting.quiz_rows(optional_int(request.query_params.get("course")))
        page, meta = paginate(request, rows)
        return Response({"results": page, **meta})


class QuizDetailView(ConsoleView):
    required_action = VIEW_RESULTS

    def get(self, request: Request, activity_id: int) -> Response:
        activity = get_object_or_404(
            Activity.objects.select_related("content_node__parent__course_version"),
            pk=activity_id,
            activity_type__in=reporting.SCORED_TYPES,
        )
        return Response(reporting.quiz_detail(activity))


class _Echo:
    def write(self, value):
        return value


class ResultsExportView(ConsoleView):
    """Every attempt as a CSV. An export is a sensitive read, so it is logged."""

    required_action = VIEW_RESULTS

    HEADER = [
        "Learner email",
        "Learner name",
        "Employee id",
        "Course",
        "Version",
        "Quiz",
        "Attempt",
        "Score %",
        "Result",
        "Submitted at",
    ]

    def get(self, request: Request) -> StreamingHttpResponse:
        course_id = optional_int(request.query_params.get("course"))
        rows = list(reporting.export_rows(course_id))
        audit.record(
            request,
            "results.export",
            target_type="course",
            target_id=course_id or "all",
            target_label="All courses" if course_id is None else f"Course {course_id}",
            changes={"rows": len(rows)},
        )
        writer = csv.writer(_Echo())
        stream = (writer.writerow(r) for r in [self.HEADER, *rows])
        response = StreamingHttpResponse(stream, content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="quiz-results.csv"'
        return response
