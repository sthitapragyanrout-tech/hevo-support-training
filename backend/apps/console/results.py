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
from apps.certification import services as cert_services
from apps.certification.models import Certificate
from apps.enrollment.models import Program
from apps.progress import dashboard, reporting, services, summary

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
        detail = reporting.learner_detail(user)
        # The courses they are on now, each at the version they are pinned to, with the same
        # summary as their own My progress page (plus what only staff see: mentor scores and the
        # breakdown of the course score).
        enrolled = []
        for e in dashboard.enrollments().filter(user=user).order_by("-enrolled_at", "-id"):
            course = summary.course_summary(user, e)
            course["group"] = {"id": e.program.pk, "name": e.program.name} if e.program else None
            course["version"] = e.version.version
            course["quiz_score"] = dashboard.quiz_score(course)
            enrolled.append(course)
        detail["enrolled"] = enrolled
        # Every certificate they have held, revoked ones included (so one can be restored).
        detail["certificates"] = [
            cert_services.page_payload(c, staff=True)
            for c in Certificate.objects.filter(user=user).select_related("user", "version")
        ]
        return Response(detail)


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


class DashboardView(ConsoleView):
    """One row per active enrollment, sortable by progress, quiz score, course score, ...
    `?export=csv` downloads the same rows (logged, like every export)."""

    required_action = VIEW_RESULTS

    CSV_HEADER = [
        "Name",
        "Email",
        "Employee id",
        "Course",
        "Group",
        "Lessons done",
        "Lessons total",
        "Progress %",
        "Quiz score %",
        "Course score %",
        "Pass mark %",
        "Certificate",
        "Certificate issued",
        "Last activity",
    ]

    def get(self, request: Request):
        params = request.query_params
        group = params.get("group", "")
        try:
            found = dashboard.rows(
                search=params.get("search", "").strip(),
                course_id=optional_int(params.get("course")),
                group_id=optional_int(group) if group != "none" else None,
                no_group=group == "none",
                certified=params.get("certified", ""),
                ordering=params.get("ordering", "name"),
            )
        except dashboard.TooMany:
            raise ConsoleError(
                f"More than {dashboard.MAX_ROWS} enrollments match. Choose a course or a group."
            ) from None
        if params.get("export") == "csv":
            return self._csv(request, found)
        page, meta = paginate(request, found)
        return Response(
            {
                "results": page,
                **meta,
                "totals": dashboard.totals(found),
                # The group filter's options (anyone who may see results may see these names).
                "groups": [
                    {"id": pk, "name": name}
                    for pk, name in Program.objects.filter(archived_at__isnull=True)
                    .order_by("name")
                    .values_list("pk", "name")
                ],
            }
        )

    def _csv(self, request: Request, found) -> StreamingHttpResponse:
        audit.record(
            request,
            "results.dashboard_export",
            target_type="dashboard",
            target_label="Dashboard",
            changes={"rows": len(found)},
        )

        def pct(value):
            return "" if value is None else round(value * 100, 1)

        lines = [
            [
                r["name"],
                r["email"],
                r["employee_id"] or "",
                r["course"]["title"],
                r["group"]["name"] if r["group"] else "",
                r["lessons_done"],
                r["lessons_total"],
                pct(r["progress"]),
                pct(r["quiz_score"]),
                pct(r["course_score"]),
                r["threshold"] if r["certificate_on"] else "",
                r["certificate"]["code"] if r["certificate"] else "",
                r["certificate"]["issued_at"] if r["certificate"] else "",
                r["last_activity"] or "",
            ]
            for r in found
        ]
        writer = csv.writer(_Echo())
        stream = (writer.writerow(line) for line in [self.CSV_HEADER, *lines])
        response = StreamingHttpResponse(stream, content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="dashboard.csv"'
        return response


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
    """Every attempt (quizzes and practice tickets) as a CSV. An export is a sensitive
    read, so it is logged."""

    required_action = VIEW_RESULTS

    HEADER = [
        "Learner email",
        "Learner name",
        "Employee id",
        "Course",
        "Version",
        "Activity",
        "Attempt",
        "Score %",  # quizzes only; the other two are scored out of 5 (last column)
        "Result",
        "Submitted at",
        "Type",
        "Score out of 5",
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
        response["Content-Disposition"] = 'attachment; filename="results.csv"'
        return response
