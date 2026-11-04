"""Read-side summaries of a learner's mentor-rated work, for the learner's own course view and
for trainers looking at results. Everything is computed from the rows and the clock."""

from __future__ import annotations

from typing import Any

from django.db.models import prefetch_related_objects
from django.utils import timezone

from apps.activities import manual_sim as cfg
from apps.progress.models import ActivityProgress
from apps.progress.reporting import display_name

from . import access, services
from .models import SimCase, SimSubmission


def _cases(user, **filters) -> list[SimCase]:
    """The learner's cases with their submissions: one query when there are none (the
    common case on every course view), three otherwise, however many cases there are."""
    cases = list(SimCase.objects.filter(user=user, **filters).select_related("user", "activity"))
    if cases:
        prefetch_related_objects(cases, "submissions")
    return cases


def _states(user, cases: list[SimCase]) -> dict[int, str]:
    if not cases:
        return {}
    return dict(
        ActivityProgress.objects.filter(
            user=user, activity_id__in=[c.activity_id for c in cases]
        ).values_list("activity_id", "state")
    )


def course_summaries(user, version, now=None) -> dict[int, dict[str, Any]]:
    """For the learner's own course view: {activity id: how their work stands}. Deliberately
    small: no routing, no raters, no internal flags."""
    now = now or timezone.now()
    cases = _cases(user, activity__content_node__course_version=version)
    states = _states(user, cases)
    out: dict[int, dict[str, Any]] = {}
    for case in cases:
        summary = services.case_summary(case, now=now, state=states.get(case.activity_id))
        out[case.activity_id] = {
            "status": summary["status"],
            "revisions": summary["revisions"],
            "due_at": summary["due_at"].isoformat() if summary["due_at"] else None,
            "overdue": summary["overdue"],
            "last_score": summary["last_score"],
            # Does handing the work in open the next lesson (else only a pass does)?
            "holds_next": cfg.holds_next(case.activity.config),
        }
    return out


def for_trainer(user, now=None) -> dict[int, dict[str, Any]]:
    """For a trainer looking at one learner: {activity id: the full picture}, including what
    only trainers see (the internal flag, who has it, a closing note)."""
    now = now or timezone.now()
    cases = _cases(user)
    states = _states(user, cases)
    out: dict[int, dict[str, Any]] = {}
    for case in cases:
        summary = services.case_summary(case, now=now, state=states.get(case.activity_id))
        waiting: SimSubmission | None = summary["waiting"]
        out[case.activity_id] = {
            "case_id": case.pk,
            "status": summary["status"],
            "revisions": summary["revisions"],
            "unsuccessful": summary["unsuccessful"],
            "needs_attention": summary["needs_attention"],
            "due_at": summary["due_at"].isoformat() if summary["due_at"] else None,
            "due_basis": summary["due_basis"],
            "overdue": summary["overdue"],
            "last_score": summary["last_score"],
            "closed_reason": case.closed_reason,
            "close_note": case.close_note,
            "waiting": (
                {
                    "id": waiting.pk,
                    "review_due_at": waiting.review_due_at.isoformat(),
                    "review_overdue": access.review_overdue(waiting, now),
                    "escalated": access.escalated(waiting, now),
                    "assigned_mentor": (
                        display_name(waiting.assigned_mentor) if waiting.assigned_mentor else None
                    ),
                }
                if waiting
                else None
            ),
        }
    return out
