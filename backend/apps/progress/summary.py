"""The learner's own progress report: every course they are enrolled on, at a glance.

Facts only. There is no overall score, no pass/fail for a course and no ranking, because how
results combine is not decided (see `docs/scoring-open-questions.md`). What it shows is what the
platform already records about *this* learner: lessons done, what is next, how each quiz went,
practice tickets, and mentor-rated work with the mentor's feedback.

It is built on `course_progress`, so it can never disagree with the course page, and it only ever
reads the caller's own rows (nothing about anyone else, no answer keys, no reference answers, no
rater-only notes). Courses are the ones the learner is **actively enrolled** on, at the version they
are pinned to, and modules a trainer switched off for them are left out, as everywhere else.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from apps.activities.registry import is_completable
from apps.catalog.models import Activity, ContentNode
from apps.enrollment import access
from apps.enrollment.models import Enrollment
from apps.manual_sim.models import SimSubmission

from . import services
from .models import ActivityAttempt


def learner_summary(user) -> dict[str, Any]:
    enrollments = list(
        Enrollment.objects.filter(
            user=user,
            state=Enrollment.State.ACTIVE,
            course__archived_at__isnull=True,
            version__state__in=access.RELEASED,
        )
        .select_related("course", "version__root_node")
        .order_by("-enrolled_at", "-id")
    )
    return {"courses": [public(_course(user, e)) for e in enrollments]}


# Internal keys a learner never receives: the mentor's score is used to work out the course score
# but is not shown on My progress.
_INTERNAL_RATED = ("last_score",)


def public(course: dict[str, Any]) -> dict[str, Any]:
    """The learner's copy of a course summary: without the mentor scores, and without the
    per-kind breakdown of the course score (one of its parts is the mentor's average)."""
    return {
        **course,
        "rated": [
            {k: v for k, v in r.items() if k not in _INTERNAL_RATED} for r in course["rated"]
        ],
        "certification": {k: v for k, v in course["certification"].items() if k != "parts"},
    }


def course_summary(user, enrollment: Enrollment) -> dict[str, Any]:
    """The full internal summary of one enrollment (mentor scores included): for staff views and
    for working out certificates. Never send this to the learner; use `public`."""
    return _course(user, enrollment)


def _quiz_status(state: str | None, pending: bool, count: int) -> str:
    if pending:
        return "awaiting_review"
    if state == "completed":
        return "passed"
    if state == "exhausted":
        return "not_passed"
    return "in_progress" if count or state == "started" else "not_started"


def _course(user, enrollment: Enrollment) -> dict[str, Any]:
    version = enrollment.version
    payload = services.course_progress(user, version.pk)
    disabled = access.disabled_module_ids(user, version)
    ordered = services._lessons_in_order(version, disabled)
    position = {lesson.id: i for i, lesson in enumerate(ordered)}
    titles = {lesson.id: lesson.title for lesson in ordered}
    completed = set(payload["completed_lessons"])
    next_id = payload["next_lesson_id"]

    activities = [
        a
        for a in Activity.objects.filter(content_node__course_version=version).select_related(
            "content_node__parent"
        )
        if is_completable(a.activity_type, a.config)
    ]
    placed: list[tuple[Activity, Any]] = []
    for activity in activities:
        lesson = services._lesson_of(activity)
        if lesson is not None and lesson.pk in position:  # in a module they have
            placed.append((activity, lesson))
    placed.sort(key=lambda pair: (position[pair[1].pk], pair[0].order, pair[0].pk))

    quizzes, practice, rated = [], [], []
    ticket_ids = [a.pk for a, _ in placed if a.activity_type == "bot_sim"]
    tries = _tickets(user, ticket_ids)
    notes = _feedback(user, [a.pk for a, _ in placed if a.activity_type == "manual_sim"])

    for activity, lesson in placed:
        where = {
            "activity_id": activity.pk,
            "lesson_id": lesson.pk,
            "lesson_title": lesson.title,
            "title": activity.title,
        }
        if activity.activity_type == "mcq":
            s = payload["attempts"].get(activity.pk)
            count = s["count"] if s else 0
            pending = bool(s and s.get("pending"))
            state = payload["activities"].get(activity.pk)
            quizzes.append(
                {
                    **where,
                    "status": _quiz_status(state, pending, count),
                    "attempts_used": count + (1 if pending else 0),
                    "max_attempts": activity.max_attempts,
                    "best": s["best_score"] if s and count else None,
                    "latest": s["last_score"] if s and count else None,
                    "required": activity.is_required,
                }
            )
        elif activity.activity_type == "bot_sim":
            sim = payload["sim"].get(activity.pk) or {}
            done = tries.get(activity.pk, [])
            practice.append(
                {
                    **where,
                    "finished": len(done),
                    # Out of 5, like everywhere practice tickets are scored; never a percentage.
                    "average": round(sim["average"] * 5, 2)
                    if sim.get("average") is not None
                    else None,
                    "recent": [
                        {"at": at.isoformat(), "score": round(score * 5, 2)}
                        for at, score in done[-3:][::-1]
                    ],
                    "in_progress": bool(sim.get("live")),
                    "required": activity.is_required,
                }
            )
        elif activity.activity_type == "manual_sim":
            r = payload["rated"].get(activity.pk) or {}
            note = notes.get(activity.pk)
            rated.append(
                {
                    **where,
                    "status": r.get("status", "not_submitted"),
                    "revisions": r.get("revisions", 0),
                    # Internal only (see `public`): learners see the status and the mentor's words.
                    "last_score": r.get("last_score"),
                    "due_at": r.get("due_at"),  # already an ISO string
                    "overdue": bool(r.get("overdue")),
                    "feedback": note["comment"] if note else None,
                    "rated_at": note["at"] if note else None,
                    "required": activity.is_required,
                }
            )

    required_left = sum(1 for lesson in ordered if lesson.required and lesson.id not in completed)
    course = {
        "course_id": version.course_id,
        "enrollment_id": enrollment.pk,
        "version_id": version.pk,
        "title": version.root_node.title if version.root_node else version.course.slug,
        "lessons_total": len(ordered),
        "lessons_done": len(completed),
        "lessons_awaiting_review": len(payload["awaiting_review_lessons"]),
        "next_lesson": {"id": next_id, "title": titles[next_id]} if next_id in titles else None,
        "modules": _modules(
            version, disabled, completed, set(payload["awaiting_review_lessons"]), next_id, titles
        ),
        "required_lessons_left": required_left,
        "quizzes": quizzes,
        "practice": practice,
        "rated": rated,
    }
    from apps.certification import services as certification

    course["certification"] = certification.standing(user, enrollment, course)
    return course


def _modules(
    version, disabled, completed: set[int], awaiting: set[int], next_id, titles
) -> list[dict[str, Any]]:
    """The course's modules in order, each with how many of its lessons are done and every lesson
    with its state. A lesson waiting for marks is not done (as on the course page); switched-off
    modules are left out."""
    lessons_by_module: dict[int, list[int]] = defaultdict(list)
    info: dict[int, tuple[str, bool]] = {}
    for module_id, lesson_id, title, required in (
        ContentNode.objects.filter(course_version=version, kind=ContentNode.Kind.TOPIC)
        .order_by("order", "id")
        .values_list("parent_id", "id", "title", "is_required")
    ):
        lessons_by_module[module_id].append(lesson_id)
        info[lesson_id] = (title, required)
    out = []
    for module in ContentNode.objects.filter(
        course_version=version, kind=ContentNode.Kind.SEGMENT
    ).order_by("order", "id"):
        if module.pk in disabled:
            continue
        lessons = lessons_by_module.get(module.pk, [])
        if not lessons:  # an empty module has nothing to finish; leave it out of the index
            continue
        done = sum(1 for lesson_id in lessons if lesson_id in completed)
        started = done or any(lesson_id in awaiting for lesson_id in lessons)
        state = "done" if done == len(lessons) else "in_progress" if started else "not_started"
        nxt = next_id if next_id in lessons else None
        out.append(
            {
                "id": module.pk,
                "title": module.title,
                "lessons_total": len(lessons),
                "lessons_done": done,
                "lessons_awaiting_review": sum(1 for i in lessons if i in awaiting),
                "state": state,
                "next_lesson": {"id": nxt, "title": titles[nxt]} if nxt in titles else None,
                "lessons": [
                    {
                        "id": i,
                        "title": info[i][0],
                        "required": info[i][1],
                        "state": _lesson_state(i, completed, awaiting, next_id),
                    }
                    for i in lessons
                ],
            }
        )
    return out


def _lesson_state(lesson_id: int, completed: set[int], awaiting: set[int], next_id) -> str:
    if lesson_id in completed:
        return "done"
    if lesson_id in awaiting:
        return "awaiting_review"
    return "next" if lesson_id == next_id else "not_started"


def _tickets(user, activity_ids: list[int]) -> dict[int, list[tuple[Any, float]]]:
    """{activity id: [(when, scaled score)] oldest first} for finished practice tickets."""
    out: dict[int, list[tuple[Any, float]]] = defaultdict(list)
    if not activity_ids:
        return out
    for activity_id, at, score in (
        ActivityAttempt.objects.filter(user=user, activity_id__in=activity_ids)
        .order_by("submitted_at", "id")
        .values_list("activity_id", "submitted_at", "score")
    ):
        out[activity_id].append((at, score))
    return out


def _feedback(user, activity_ids: list[int]) -> dict[int, dict[str, Any]]:
    """The latest mentor comment on each simulation: only the comment and when it was given."""
    out: dict[int, dict[str, Any]] = {}
    if not activity_ids:
        return out
    for activity_id, comment, at in (
        SimSubmission.objects.filter(
            case__user=user, case__activity_id__in=activity_ids, state=SimSubmission.State.RATED
        )
        .order_by("case__activity_id", "revision")
        .values_list("case__activity_id", "overall_comment", "rated_at")
    ):
        out[activity_id] = {"comment": comment or None, "at": at.isoformat() if at else None}
    return out
