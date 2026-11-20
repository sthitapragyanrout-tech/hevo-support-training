"""Admin Console API for enrollment: who is on which course, programs, mentors.

Everything here needs `enrollment.manage_enrollments`. The services own the rules; these views
parse input, call them, write the audit trail and shape the response.
"""

from __future__ import annotations

import datetime
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, F, OuterRef, Q, Subquery
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit import services as audit
from apps.catalog.models import ContentNode, Course, CourseVersion
from apps.console.base import ConsoleError, ConsoleView, optional_int, paginate
from apps.manual_sim import assignments, eligibility
from apps.manual_sim.errors import SimError
from apps.manual_sim.models import MentorAssignment

from . import migration, services
from . import modules as modules_
from .errors import Conflict, EnrollmentError
from .models import Enrollment, Program

User = get_user_model()

MANAGE = "enrollment.manage_enrollments"
MAX_PEOPLE = 200


# ------------------------------------------------------------------------- shaping


def _name(user) -> str:
    return services._name(user)


def _who(user) -> dict[str, Any] | None:
    return None if user is None else {"id": user.pk, "name": _name(user), "email": user.email}


def _title(version: CourseVersion) -> str:
    return version.root_node.title if version.root_node else version.course.slug


def _latest_published(course_ids) -> dict[int, int]:
    """{course id: number of its newest published version}."""
    out: dict[int, int] = {}
    for course_id, number in (
        CourseVersion.objects.filter(course_id__in=course_ids, state=CourseVersion.State.PUBLISHED)
        .order_by("course_id", "version")
        .values_list("course_id", "version")
    ):
        out[course_id] = number  # ascending, so the last one wins
    return out


def _mentors(rows) -> dict[tuple[int, int], Any]:
    pairs = {(e.user_id, e.course_id) for e in rows}
    if not pairs:
        return {}
    found = MentorAssignment.objects.filter(
        learner_id__in={p[0] for p in pairs}, course_id__in={p[1] for p in pairs}
    ).select_related("mentor")
    return {
        (a.learner_id, a.course_id): a.mentor
        for a in found
        if assignments.is_eligible_mentor(a.mentor, a.learner)
    }


def _module_counts(rows: list[Enrollment]) -> dict[int, tuple[int, int]]:
    """{enrollment id: (modules on, modules in the course)}: two queries for the whole page."""
    totals = dict(
        ContentNode.objects.filter(
            course_version_id__in={e.version_id for e in rows}, kind=ContentNode.Kind.SEGMENT
        )
        .values_list("course_version_id")
        .annotate(n=Count("id"))
    )
    off = dict(
        Enrollment.objects.filter(pk__in=[e.pk for e in rows])
        .values_list("pk")
        .annotate(n=Count("excluded_modules"))
    )
    return {
        e.pk: (totals.get(e.version_id, 0) - off.get(e.pk, 0), totals.get(e.version_id, 0))
        for e in rows
    }


def enrollment_rows(rows: list[Enrollment]) -> list[dict[str, Any]]:
    latest = _latest_published({e.course_id for e in rows})
    mentors = _mentors(rows)
    counts = _module_counts(rows)
    return [
        {
            "id": e.pk,
            "user": _who(e.user),
            "course": {
                "id": e.course_id,
                "title": _title(e.version),
                "archived": e.course.archived_at is not None,
            },
            "version": {
                "id": e.version_id,
                "number": e.version.version,
                "latest_number": latest.get(e.course_id),
                "older": e.course_id in latest and latest[e.course_id] != e.version.version,
            },
            "program": {"id": e.program.pk, "name": e.program.name} if e.program else None,
            "mentor": _who(mentors.get((e.user_id, e.course_id))),
            "modules": {"enabled": counts[e.pk][0], "total": counts[e.pk][1]},
            "state": e.state,
            "source": e.source,
            "enrolled_at": e.enrolled_at.isoformat(),
            "withdrawn_at": e.withdrawn_at.isoformat() if e.withdrawn_at else None,
            "withdrawn_reason": e.withdrawn_reason,
        }
        for e in rows
    ]


def _one(pk: int) -> dict[str, Any]:
    row = _queryset().get(pk=pk)
    return enrollment_rows([row])[0]


def _queryset():
    return Enrollment.objects.select_related(
        "user", "course", "version__root_node", "version__course", "program"
    )


def _label(e: Enrollment) -> str:
    return f"{e.user.email} → {_title(e.version)}"


# ------------------------------------------------------------------------- base view


class _View(ConsoleView):
    required_action = MANAGE

    def handle_exception(self, exc):
        if isinstance(exc, EnrollmentError | SimError):
            return Response({"detail": exc.message}, status=exc.status_code)
        return super().handle_exception(exc)


def _body(request: Request) -> dict[str, Any]:
    return request.data if isinstance(request.data, dict) else {}


def _int(body: dict[str, Any], key: str, *, required: bool = True) -> int | None:
    value = body.get(key)
    if value is None:
        if required:
            raise ConsoleError(f"{key.replace('_', ' ').capitalize()} is required.")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConsoleError(f"{key.replace('_', ' ').capitalize()} must be a number.")
    return value


def _target(body: dict[str, Any]) -> tuple[Course | None, Program | None]:
    course_id = _int(body, "course_id", required=False)
    program_id = _int(body, "program_id", required=False)
    if (course_id is None) == (program_id is None):
        raise ConsoleError("Choose a course or a group to enroll them on.")
    if course_id is not None:
        return get_object_or_404(Course, pk=course_id), None
    return None, get_object_or_404(Program, pk=program_id)


def _module_ids(body: dict[str, Any]) -> list[int] | None:
    """The modules to give (the ticked ones). Absent = every module."""
    raw = body.get("module_ids")
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(
        isinstance(i, int) and not isinstance(i, bool) for i in raw
    ):
        raise ConsoleError("Module choices must be a list of module ids.")
    return raw


def _mentor(body: dict[str, Any]):
    mentor_id = _int(body, "mentor_id", required=False)
    return None if mentor_id is None else get_object_or_404(User, pk=mentor_id)


# --------------------------------------------------------------------------- lists


class OptionsView(_View):
    """What the Enroll dialogs offer: courses that can be enrolled on, programs, mentors."""

    def get(self, request: Request) -> Response:
        latest = _latest_published(Course.objects.values("pk"))
        courses = []
        for course in Course.objects.filter(archived_at__isnull=True, pk__in=list(latest)):
            version = (
                course.versions.filter(state=CourseVersion.State.PUBLISHED)
                .select_related("root_node")
                .order_by("-version")
                .first()
            )
            if version is not None and version.root_node is not None:
                courses.append(
                    {
                        "id": course.pk,
                        "title": version.root_node.title,
                        "modules": [
                            {"id": m.pk, "title": m.title} for m in modules_.modules_of(version)
                        ],
                    }
                )
        courses.sort(key=lambda c: str(c["title"]).lower())
        programs = [
            {
                "id": p.pk,
                "name": p.name,
                "course_ids": [i.course_id for i in p.items.all()],
            }
            for p in Program.objects.filter(archived_at__isnull=True).prefetch_related("items")
        ]
        mentors = [
            {"id": u.pk, "name": _name(u), "email": u.email}
            for u in eligibility.raters().order_by(Lower("email"))
        ]
        return Response({"courses": courses, "programs": programs, "mentors": mentors})


class PeopleView(_View):
    """The learner picker: `?search=` over name, email and employee id; `?course=` marks who is
    already on that course."""

    def get(self, request: Request) -> Response:
        search = request.query_params.get("search", "").strip()
        qs = User.objects.filter(is_active=True)
        if search:
            qs = qs.filter(
                Q(email__icontains=search)
                | Q(username__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(employee_id__icontains=search)
            )
        course_id = optional_int(request.query_params.get("course"))
        if course_id is not None:
            qs = qs.annotate(
                on_course=Exists(
                    Enrollment.objects.filter(
                        user=OuterRef("pk"), course_id=course_id, state=Enrollment.State.ACTIVE
                    )
                )
            )
        qs = qs.filter(role_assignments__role__name="learner").distinct().order_by(Lower("email"))
        people = list(qs[:20])
        return Response(
            {
                "results": [
                    {**_who(u), "on_course": bool(getattr(u, "on_course", False))}  # type: ignore[dict-item]
                    for u in people
                ]
            }
        )


class EnrollmentListView(_View):
    def get(self, request: Request) -> Response:
        params = request.query_params
        qs = _queryset()
        state = params.get("state", "active")
        if state in (Enrollment.State.ACTIVE, Enrollment.State.WITHDRAWN):
            qs = qs.filter(state=state)
        course_id = optional_int(params.get("course"))
        if course_id is not None:
            qs = qs.filter(course_id=course_id)
        program_id = optional_int(params.get("program"))
        if program_id is not None:
            qs = qs.filter(program_id=program_id)
        search = params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(user__email__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(user__employee_id__icontains=search)
            )
        if params.get("older") in ("1", "true"):
            newest = CourseVersion.objects.filter(
                course=OuterRef("course"), state=CourseVersion.State.PUBLISHED
            ).order_by("-version")
            qs = (
                qs.annotate(newest_id=Subquery(newest.values("pk")[:1]))
                .filter(newest_id__isnull=False)
                .exclude(version_id=F("newest_id"))
            )
        mentor_id = optional_int(params.get("mentor"))
        if mentor_id is not None:
            qs = qs.filter(
                Exists(
                    MentorAssignment.objects.filter(
                        learner=OuterRef("user"), course=OuterRef("course"), mentor_id=mentor_id
                    )
                )
            )
        qs = qs.order_by(Lower("user__email"), "course_id")
        page, meta = paginate(self.request, qs)
        return Response({"results": enrollment_rows(page), **meta})

    def post(self, request: Request) -> Response:
        """Enroll chosen people on a course, or on every course of a program."""
        body = _body(request)
        course, program = _target(body)
        ids = body.get("user_ids")
        if (
            not isinstance(ids, list)
            or not ids
            or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)
        ):
            raise ConsoleError("Choose at least one person to enroll.")
        if len(ids) > MAX_PEOPLE:
            raise ConsoleError(
                f"Choose at most {MAX_PEOPLE} people at a time. Use a list for more."
            )
        mentor = _mentor(body)
        module_ids = _module_ids(body)
        if module_ids is not None and program is not None:
            raise ConsoleError(
                "Choosing modules works for one course at a time. Enroll the group with "
                "every module, then trim individual learners."
            )
        if module_ids is not None and course is not None:
            try:  # a bad choice is the request's fault, not each person's: refuse it whole
                modules_.excluded_ids(services.enrollable_version(course), module_ids)
            except Conflict:
                pass  # nothing published to enroll on: each person is told so below
        people = {u.pk: u for u in User.objects.filter(pk__in=ids)}
        if set(people) != set(ids):
            raise ConsoleError("One of those people doesn’t exist.", 404)
        results = []
        for uid in dict.fromkeys(ids):
            user = people[uid]
            if program is not None:
                steps = services.enroll_program(user, program, mentor=mentor, by=request.user)
                results.append(_program_result(request, user, program, steps))
            else:
                assert course is not None
                try:
                    row, outcome = services.enroll(
                        user, course, mentor=mentor, modules=module_ids, by=request.user
                    )
                except (EnrollmentError, SimError) as exc:
                    results.append({"user": _who(user), "outcome": "failed", "detail": exc.message})
                    continue
                _audit_enroll(request, row, outcome)
                results.append({"user": _who(user), "outcome": outcome, "enrollment": _one(row.pk)})
        return Response({"results": results}, status=status.HTTP_200_OK)


def _titles(node_ids) -> list[str]:
    """Module titles in course order, for the audit trail."""
    return list(
        ContentNode.objects.filter(pk__in=list(node_ids))
        .order_by("order", "id")
        .values_list("title", flat=True)
    )


def _audit_enroll(request, row: Enrollment, outcome: str, **extra) -> None:
    if outcome == services.ALREADY:
        return
    off = _titles(modules_.excluded_of(row))
    if off:
        extra = {**extra, "modules_off": off}
    audit.record(
        request,
        "enrollments.enroll" if outcome == services.ENROLLED else "enrollments.reenroll",
        target_type="enrollment",
        target_id=row.pk,
        target_label=_label(row),
        changes={
            "version": row.version.version,
            "source": row.source,
            "program": row.program.name if row.program else None,
            **extra,
        },
    )


def _program_result(request, user, program, steps) -> dict[str, Any]:
    out = []
    for step in steps:
        if step.outcome != "skipped":
            row = Enrollment.objects.select_related("version", "user", "program").get(
                user=user, course=step.course
            )
            _audit_enroll(request, row, step.outcome)
        out.append({"course_id": step.course.pk, "outcome": step.outcome, "detail": step.detail})
    return {"user": _who(user), "outcome": "program", "courses": out}


# --------------------------------------------------------------------------- bulk


class BulkView(_View):
    """Paste a list: `apply` false → preview only; true → do exactly what the preview lists."""

    def post(self, request: Request) -> Response:
        body = _body(request)
        course, program = _target(body)
        apply = body.get("apply") is True
        text = body.get("text")
        if not isinstance(text, str):
            raise ConsoleError("Paste a list of email addresses, one per line.")
        rows = services.bulk(
            text,
            course=course,
            program=program,
            default_mentor=_mentor(body),
            modules=_module_ids(body),
            by=request.user,
            apply=apply,
        )
        if apply:
            for row in rows:
                for step in row.courses:
                    if step["state"] != "done":
                        continue
                    enrollment = Enrollment.objects.select_related(
                        "version", "user", "program"
                    ).get(user=row.user, course_id=step["id"])
                    _audit_enroll(request, enrollment, step["outcome"], via="list")
        return Response(
            {
                "applied": apply,
                "summary": services.summarise(rows),
                "rows": [
                    {
                        "line": r.line,
                        "email": r.email,
                        "mentor_email": r.mentor_email,
                        "status": r.status,
                        "label": services.STATUSES.get(r.status, r.status),
                        "detail": r.detail,
                        "user": _who(r.user),
                        "courses": r.courses,
                    }
                    for r in rows
                ],
            }
        )


# ---------------------------------------------------------------------- one row


def _enrollment(pk: int) -> Enrollment:
    return get_object_or_404(_queryset(), pk=pk)


class WithdrawView(_View):
    def post(self, request: Request, pk: int) -> Response:
        row = services.withdraw(
            _enrollment(pk), str(_body(request).get("reason") or ""), by=request.user
        )
        row = _enrollment(row.pk)
        audit.record(
            request,
            "enrollments.withdraw",
            target_type="enrollment",
            target_id=row.pk,
            target_label=_label(row),
            changes={"reason": row.withdrawn_reason},
        )
        return Response(_one(row.pk))


class ReenrollView(_View):
    def post(self, request: Request, pk: int) -> Response:
        old = _enrollment(pk)
        row, outcome = services.enroll(old.user, old.course, by=request.user)
        _audit_enroll(request, _enrollment(row.pk), outcome)
        return Response(_one(row.pk))


class MentorView(_View):
    def post(self, request: Request, pk: int) -> Response:
        row = _enrollment(pk)
        mentor = _mentor(_body(request))
        before = services.mentor_of(row)
        services.change_mentor(row, mentor, by=request.user)
        audit.record(
            request,
            "enrollments.mentor",
            target_type="enrollment",
            target_id=row.pk,
            target_label=_label(row),
            changes={
                "from": _name(before) if before else "shared pool",
                "to": _name(mentor) if mentor else "shared pool",
            },
        )
        return Response(_one(row.pk))


class GroupView(_View):
    """Set or clear the group (program) an enrollment counts under: `{"program_id": id|null}`."""

    def post(self, request: Request, pk: int) -> Response:
        row = _enrollment(pk)
        program_id = _int(_body(request), "program_id", required=False)
        program = None if program_id is None else get_object_or_404(Program, pk=program_id)
        before = row.program.name if row.program else None
        services.set_group(row, program)
        audit.record(
            request,
            "enrollments.group",
            target_type="enrollment",
            target_id=row.pk,
            target_label=_label(row),
            changes={"from": before or "no group", "to": program.name if program else "no group"},
        )
        return Response(_one(row.pk))


class ModulesView(_View):
    """Which modules this learner gets: GET the course's modules with what is on; POST the ticked
    ones (`module_ids`)."""

    def get(self, request: Request, pk: int) -> Response:
        row = _enrollment(pk)
        off = modules_.excluded_of(row)
        return Response(
            {
                "active": row.state == Enrollment.State.ACTIVE,
                "modules": [
                    {"id": m.pk, "title": m.title, "enabled": m.pk not in off}
                    for m in modules_.modules_of(row.version)
                ],
            }
        )

    def post(self, request: Request, pk: int) -> Response:
        row = _enrollment(pk)
        ids = _module_ids(_body(request))
        if ids is None:
            raise ConsoleError("Choose the modules to give them.")
        change = modules_.set_modules(row, ids)
        if change.before_off != change.after_off:
            audit.record(
                request,
                "enrollments.modules",
                target_type="enrollment",
                target_id=row.pk,
                target_label=_label(row),
                changes={
                    "off_before": _titles(change.before_off),
                    "off_after": _titles(change.after_off),
                },
            )
        return Response(_one(row.pk))


def _carry(body: dict[str, Any]) -> set[int]:
    raw = body.get("carry", [])
    if not isinstance(raw, list) or not all(
        isinstance(i, int) and not isinstance(i, bool) for i in raw
    ):
        raise ConsoleError("Carry-over choices must be a list of activity ids.")
    return set(raw)


def _new_modules_off(body: dict[str, Any]) -> set[int]:
    raw = body.get("new_modules_off", [])
    if not isinstance(raw, list) or not all(
        isinstance(i, int) and not isinstance(i, bool) for i in raw
    ):
        raise ConsoleError("Module choices must be a list of module ids.")
    return set(raw)


class MigrationPreviewView(_View):
    """What moving this learner to the newest published version would do. Changes nothing."""

    def post(self, request: Request, pk: int) -> Response:
        body = _body(request)
        return Response(migration.preview(_enrollment(pk), _carry(body), _new_modules_off(body)))


class MigrateView(_View):
    """Move the learner to the newest published version (`to_version_id` is the one the preview
    showed; if a newer one has appeared, nothing happens)."""

    def post(self, request: Request, pk: int) -> Response:
        row = _enrollment(pk)
        body = _body(request)
        result = migration.apply(
            row,
            to_version_id=_int(body, "to_version_id"),
            carry=_carry(body),
            new_off=_new_modules_off(body),
            by=request.user,
        )
        audit.record(
            request,
            "enrollments.migrate",
            target_type="enrollment",
            target_id=row.pk,
            target_label=_label(row),
            changes={
                "from": result["from"]["number"],
                "to": result["to"]["number"],
                **result["counts"],
            },
        )
        return Response({"result": result, "enrollment": _one(row.pk)})


# ------------------------------------------------------------------------ programs


def _program(program: Program) -> dict[str, Any]:
    items = list(program.items.select_related("course").order_by("order", "id"))
    versions = {
        c.pk: c
        for c in CourseVersion.objects.filter(
            course_id__in=[i.course_id for i in items], state=CourseVersion.State.PUBLISHED
        )
        .select_related("root_node")
        .order_by("version")
    }
    by_course = {}
    for v in versions.values():
        by_course[v.course_id] = v
    members = (
        Enrollment.objects.filter(program=program, state=Enrollment.State.ACTIVE)
        .values("user")
        .distinct()
        .count()
    )
    return {
        "id": program.pk,
        "name": program.name,
        "description": program.description,
        "starts_on": program.starts_on.isoformat() if program.starts_on else None,
        "ends_on": program.ends_on.isoformat() if program.ends_on else None,
        "archived": program.archived_at is not None,
        "members": members,
        "courses": [
            {
                "course_id": i.course_id,
                "title": _title(by_course[i.course_id])
                if i.course_id in by_course
                else i.course.slug,
                "required": i.is_required,
                "published": i.course_id in by_course and i.course.archived_at is None,
                "archived": i.course.archived_at is not None,
            }
            for i in items
        ],
    }


def _date(body: dict[str, Any], key: str) -> datetime.date | None:
    raw = body.get(key)
    if raw in (None, ""):
        return None
    try:
        return datetime.date.fromisoformat(str(raw))
    except ValueError as exc:
        raise ConsoleError("Dates must look like 2026-03-31.") from exc


def _course_list(body: dict[str, Any]) -> list[tuple[int, bool]] | None:
    raw = body.get("courses")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ConsoleError("Courses must be a list.")
    out = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("course_id"), int):
            raise ConsoleError("Each course needs a course_id.")
        out.append((item["course_id"], item.get("required", True) is not False))
    return out


class ProgramListView(_View):
    def get(self, request: Request) -> Response:
        archived = request.query_params.get("archived") in ("1", "true")
        qs = Program.objects.filter(archived_at__isnull=not archived).order_by(Lower("name"))
        return Response({"results": [_program(p) for p in qs]})

    def post(self, request: Request) -> Response:
        body = _body(request)
        program = services.save_program(
            None,
            name=body.get("name"),
            description=body.get("description", ""),
            starts_on=_date(body, "starts_on"),
            ends_on=_date(body, "ends_on"),
            courses=_course_list(body) or [],
            by=request.user,
        )
        audit.record(
            request,
            "programs.create",
            target_type="program",
            target_id=program.pk,
            target_label=program.name,
            changes={"courses": len(_course_list(body) or [])},
        )
        return Response(_program(program), status=status.HTTP_201_CREATED)


class ProgramDetailView(_View):
    def get(self, request: Request, pk: int) -> Response:
        return Response(_program(get_object_or_404(Program, pk=pk)))

    def put(self, request: Request, pk: int) -> Response:
        program = get_object_or_404(Program, pk=pk)
        before = _program(program)
        body = _body(request)
        services.save_program(
            program,
            name=body.get("name"),
            description=body.get("description", ""),
            starts_on=_date(body, "starts_on"),
            ends_on=_date(body, "ends_on"),
            courses=_course_list(body),
            by=request.user,
        )
        after = _program(program)
        audit.record(
            request,
            "programs.update",
            target_type="program",
            target_id=program.pk,
            target_label=program.name,
            changes={
                "before": [c["title"] for c in before["courses"]],
                "after": [c["title"] for c in after["courses"]],
            },
        )
        return Response(after)


class ProgramArchiveView(_View):
    def post(self, request: Request, pk: int) -> Response:
        program = services.archive_program(get_object_or_404(Program, pk=pk))
        audit.record(
            request,
            "programs.archive",
            target_type="program",
            target_id=program.pk,
            target_label=program.name,
        )
        return Response(_program(program))


class ProgramRestoreView(_View):
    def post(self, request: Request, pk: int) -> Response:
        program = services.restore_program(get_object_or_404(Program, pk=pk))
        audit.record(
            request,
            "programs.restore",
            target_type="program",
            target_id=program.pk,
            target_label=program.name,
        )
        return Response(_program(program))


class ProgramCatchUpView(_View):
    """Enroll the program's existing members on any course added to it since."""

    def post(self, request: Request, pk: int) -> Response:
        program = get_object_or_404(Program, pk=pk)
        counts = services.enroll_missing(program, by=request.user)
        audit.record(
            request,
            "programs.enroll_missing",
            target_type="program",
            target_id=program.pk,
            target_label=program.name,
            changes=counts,
        )
        return Response({**counts, "program": _program(program)})
