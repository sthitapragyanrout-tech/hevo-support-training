"""The reminders: things that become true with the passing of time, found by looking at the
database every few minutes. Each is de-duplicated by key, so running this twice (or from two
places) never repeats a message, and a *changed* deadline is a different key and notifies again.

* A learner is told once when a simulation deadline is within a day, and once when it has passed.
* A mentor is told when a review they were given is overdue; trainers and admins are told when it
  is overdue by the escalation grace (anyone may take it by then), and get one **daily digest**
  of learners past a deadline rather than a message per learner.

Nothing here changes any work: overdue is only ever shown, as everywhere else in the platform.
Time is injected with `now=` for tests.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.enrollment import access as enrollment_access
from apps.enrollment.models import Enrollment
from apps.manual_sim import access as review_access
from apps.manual_sim.models import QuizReview, SimCase, SimSubmission
from apps.progress.models import ActivityProgress

from . import events, services

SOON = timedelta(hours=24)
# A deadline that passed long ago is not news: only the last two weeks get an "overdue" message,
# so switching reminders on never floods anyone with ancient history.
RECENT = timedelta(days=14)


def sweep(*, now=None) -> dict[str, int]:
    """Raise every reminder that is due. Returns how many of each kind were newly raised."""
    now = now or timezone.now()
    learner_told, overdue = _learner_deadlines(now)
    mentors_told, escalated_told = _reviews(now)
    return {
        "learner": learner_told,
        "mentors": mentors_told,
        "escalated": escalated_told,
        "digest": _digest(overdue, now),
    }


# ------------------------------------------------------------------------- learners


def _open_cases(now):
    """Cases a learner could still act on: not closed, not passed, nothing handed in and waiting,
    on a course they are actively enrolled on, in a module they have."""
    cases = (
        SimCase.objects.filter(closed_at__isnull=True, due_at__isnull=False)
        .select_related(
            "user",
            "activity__content_node__course_version__root_node",
            "activity__content_node__course_version__course",
            "activity__content_node__parent__parent",
        )
        .order_by("due_at")
    )
    waiting = set(
        SimSubmission.objects.filter(state=SimSubmission.State.SUBMITTED).values_list(
            "case_id", flat=True
        )
    )
    passed = set(
        ActivityProgress.objects.filter(state=ActivityProgress.State.COMPLETED).values_list(
            "user_id", "activity_id"
        )
    )
    enrolled = set(
        Enrollment.objects.filter(state=Enrollment.State.ACTIVE).values_list(
            "user_id", "version_id"
        )
    )
    off: dict[tuple[int, int], frozenset[int]] = {}
    for case in cases:
        version = case.activity.content_node.course_version
        if (
            case.pk in waiting
            or (case.user_id, case.activity_id) in passed
            or (case.user_id, version.pk) not in enrolled
            or not case.user.is_active
        ):
            continue
        key = (case.user_id, version.pk)
        if key not in off:
            off[key] = enrollment_access.disabled_module_ids(case.user, version)
        if enrollment_access.module_id_of(case.activity.content_node) in off[key]:
            continue
        yield case


def _learner_deadlines(now) -> tuple[int, list[SimCase]]:
    sent = 0
    overdue: list[SimCase] = []
    for case in _open_cases(now):
        due = case.due_at
        activity = case.activity
        link = events._lesson_link(activity)
        if now < due <= now + SOON:
            made = services.notify(
                case.user,
                events.DUE_SOON,
                f"“{activity.title}” is due {events.when(due)}",
                f"Hand it in by {events.when(due)} to stay on track.",
                link,
                f"due-soon:{case.pk}:{due.isoformat()}",
            )
            sent += made is not None
        elif due <= now:
            overdue.append(case)
            if now - due <= RECENT:
                made = services.notify(
                    case.user,
                    events.OVERDUE,
                    f"“{activity.title}” is past its deadline",
                    "You can still hand it in. Late work is accepted and marked as late.",
                    link,
                    f"overdue:{case.pk}:{due.isoformat()}",
                )
                sent += made is not None
    return sent, overdue


# ------------------------------------------------------------------------- reviewers


def _reviews(now) -> tuple[int, int]:
    """(told mentors about overdue reviews, told managers about escalated ones)."""
    mentors = escalated = 0
    waiting: list[tuple[str, Any]] = [
        *(("sim", s) for s in _waiting_sims()),
        *(("quiz", r) for r in _waiting_quizzes()),
    ]
    managers = list(events.managers())
    for kind, item in waiting:
        if not review_access.review_overdue(item, now):
            continue
        learner = item.case.user if kind == "sim" else item.user
        title = item.case.activity.title if kind == "sim" else item.activity.title
        link = f"/admin/ratings/{item.pk}" if kind == "sim" else f"/admin/ratings/quiz/{item.pk}"
        stamp = item.review_due_at.isoformat()
        due = events.when(item.review_due_at)
        text = f"{events.person(learner)}’s work on {title} was due for review {due}."
        if item.assigned_mentor is not None:
            mentors += len(
                services.notify_many(
                    [item.assigned_mentor],
                    events.REVIEW_OVERDUE,
                    f"A review is overdue: {title}",
                    text,
                    link,
                    f"review-overdue:{kind}:{item.pk}:{stamp}",
                )
            )
        if review_access.escalated(item, now) or item.assigned_mentor is None:
            # In the pool nobody owns it, so trainers hear as soon as it is overdue; with an owner
            # they hear once it has gone past the grace and anyone may take it.
            pool = [m for m in managers if m.pk != learner.pk]
            escalated += len(
                services.notify_many(
                    pool,
                    events.REVIEW_ESCALATED,
                    f"A review is overdue and open to anyone: {title}"
                    if item.assigned_mentor is not None
                    else f"A review in the pool is overdue: {title}",
                    text,
                    link,
                    f"review-escalated:{kind}:{item.pk}:{stamp}",
                )
            )
    return mentors, escalated


def _waiting_sims():
    return SimSubmission.objects.filter(state=SimSubmission.State.SUBMITTED).select_related(
        "case__user", "case__activity", "assigned_mentor"
    )


def _waiting_quizzes():
    return QuizReview.objects.filter(state=QuizReview.State.SUBMITTED).select_related(
        "user", "activity", "assigned_mentor"
    )


# ------------------------------------------------------------------------- digest


def _digest(overdue: list[SimCase], now) -> int:
    """One message per manager per day: how many learners are past a deadline."""
    learners = {c.user_id for c in overdue}
    if not learners:
        return 0
    n = len(learners)
    made = services.notify_many(
        events.managers(),
        events.OVERDUE_DIGEST,
        f"{n} learner{'s are' if n != 1 else ' is'} past a deadline",
        "Open the review queue to see who needs a nudge, an extension or a decision.",
        "/admin/ratings",
        f"overdue-digest:{timezone.localdate(now) if settings.USE_TZ else now.date()}",
    )
    return len(made)
