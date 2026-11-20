"""The admin Dashboard: one row per active enrollment — who, which course, which group, how far
they are, how their quizzes went, their course score and certificate — sortable and filterable.

Every number comes from the same per-enrollment summary the learner's own My progress page uses
(`summary.course_summary`), so the two can never disagree. That costs a fixed ~20 queries per row
regardless of course size; at cohort scale (a few hundred enrollments) this is fine, and the list
refuses to build more than `MAX_ROWS` at once rather than slowing to a crawl.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from apps.enrollment import access
from apps.enrollment.models import Enrollment

from . import reporting, summary

MAX_ROWS = 1000

ORDERINGS = {
    "name": lambda r: (r["name"].lower(), r["course"]["title"].lower()),
    "emp": lambda r: ((r["employee_id"] or "~").lower(), r["name"].lower()),
    "course": lambda r: (r["course"]["title"].lower(), r["name"].lower()),
    "group": lambda r: ((r["group"]["name"] if r["group"] else "~").lower(), r["name"].lower()),
    "progress": lambda r: (r["progress"], r["name"].lower()),
    "quiz": lambda r: (r["quiz_score"], r["name"].lower()),
    "score": lambda r: (r["course_score"], r["name"].lower()),
    "last": lambda r: (r["last_activity"] or "", r["name"].lower()),
}
# Columns whose value may be missing: rows without one always sort last, either direction.
NULLABLE = {"quiz": "quiz_score", "score": "course_score", "last": "last_activity"}


class TooMany(Exception):
    pass


def enrollments(
    *,
    search: str = "",
    course_id: int | None = None,
    group_id: int | None = None,
    no_group: bool = False,
):
    qs = Enrollment.objects.filter(
        state=Enrollment.State.ACTIVE,
        course__archived_at__isnull=True,
        version__state__in=access.RELEASED,
        user__is_active=True,
    ).select_related("user", "course", "program", "version__root_node")
    if search:
        qs = qs.filter(
            Q(user__email__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(user__username__icontains=search)
            | Q(user__employee_id__icontains=search)
        )
    if course_id is not None:
        qs = qs.filter(course_id=course_id)
    if no_group:
        qs = qs.filter(program__isnull=True)
    elif group_id is not None:
        qs = qs.filter(program_id=group_id)
    return qs.order_by("id")


def _name(user) -> str:
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.username or user.email


def quiz_score(course: dict[str, Any]) -> float | None:
    """Average of each quiz's best score, over the quizzes that have one (0–1)."""
    best = [q["best"] for q in course["quizzes"] if q["best"] is not None]
    return round(sum(best) / len(best), 4) if best else None


def row(enrollment: Enrollment, course: dict[str, Any], last_activity) -> dict[str, Any]:
    user = enrollment.user
    st = course["certification"]
    total, done = course["lessons_total"], course["lessons_done"]
    return {
        "enrollment_id": enrollment.pk,
        "user_id": user.pk,
        "name": _name(user),
        "email": user.email,
        "employee_id": user.employee_id,
        "course": {"id": enrollment.course_id, "title": course["title"]},
        "group": (
            {"id": enrollment.program.pk, "name": enrollment.program.name}
            if enrollment.program
            else None
        ),
        "lessons_done": done,
        "lessons_total": total,
        "progress": round(done / total, 4) if total else 0.0,
        "quiz_score": quiz_score(course),
        "course_score": st.get("score") if st["enabled"] else None,
        "certificate_on": st["enabled"],
        "threshold": st.get("threshold"),
        "certificate": st["certificate"],
        "last_activity": last_activity.isoformat() if last_activity else None,
    }


def rows(
    *,
    search: str = "",
    course_id: int | None = None,
    group_id: int | None = None,
    no_group: bool = False,
    certified: str = "",
    ordering: str = "name",
) -> list[dict[str, Any]]:
    qs = enrollments(search=search, course_id=course_id, group_id=group_id, no_group=no_group)
    found = list(qs[: MAX_ROWS + 1])
    if len(found) > MAX_ROWS:
        raise TooMany()
    latest = reporting.last_activity_for(list({e.user_id for e in found}))
    out = [row(e, summary.course_summary(e.user, e), latest.get(e.user_id)) for e in found]
    if certified == "yes":
        out = [r for r in out if r["certificate"]]
    elif certified == "no":
        out = [r for r in out if not r["certificate"]]
    return order(out, ordering)


def order(out: list[dict[str, Any]], ordering: str) -> list[dict[str, Any]]:
    key = ordering.lstrip("-")
    if key not in ORDERINGS:
        key, ordering = "name", "name"
    descending = ordering.startswith("-")
    nullable = NULLABLE.get(key)
    present = [r for r in out if not nullable or r[nullable] is not None]
    absent = [r for r in out if nullable and r[nullable] is None]
    present.sort(key=ORDERINGS[key], reverse=descending)
    absent.sort(key=lambda r: r["name"].lower())
    return present + absent


def totals(out: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "learners": len({r["user_id"] for r in out}),
        "enrollments": len(out),
        "certificates": sum(1 for r in out if r["certificate"]),
        "courses": len({r["course"]["id"] for r in out}),
    }
