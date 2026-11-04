"""Who a learner's mentor is for a course, and where a submission goes.

This module is the **only** code that writes `MentorAssignment` rows or decides routing, so
the rules stay in one place. The enrolment workflow (not built yet) is meant to be its only
caller: it assigns a mentor when a learner is enrolled on a course and unassigns when they
leave. Until it exists nothing calls these, so every submission goes to the shared pool —
deliberately: there is no platform-wide mentor and no temporary assignment screen.

Rules: a mentor is *per learner per course* (different courses may have different mentors);
they must be active, hold the rating permission, and not be the learner. A mentor who stops
being eligible later (deactivated, role removed) is simply ignored when routing, so the work
falls to the pool instead of being stranded.
"""

from __future__ import annotations

from django.db import transaction

from apps.accounts.models import User
from apps.catalog.models import Activity, Course

from . import eligibility
from .errors import BadInput
from .models import MentorAssignment, SimSubmission


def is_eligible_mentor(mentor, learner) -> bool:
    """May `mentor` be this learner's mentor? Active, holds the rating permission through a
    role, and is not the learner."""
    if mentor is None or learner is None or mentor.pk == learner.pk:
        return False
    return eligibility.raters().filter(pk=mentor.pk).exists()


def course_of(activity: Activity) -> Course:
    return activity.content_node.course_version.course


def mentor_for(learner, course: Course):
    """The learner's mentor for this course, or None (no assignment, or no longer eligible)."""
    row = (
        MentorAssignment.objects.filter(learner=learner, course=course)
        .select_related("mentor")
        .first()
    )
    if row is not None and is_eligible_mentor(row.mentor, learner):
        return row.mentor
    return None


def route_for(learner, activity: Activity) -> tuple[User | None, str]:
    """Where a new submission goes: (the mentor, "assignment"), or (None, "pool")."""
    return route_for_course(learner, course_of(activity))


@transaction.atomic
def assign_mentor(learner, course: Course, mentor, *, by=None, source: str = "enrollment"):
    """Make `mentor` this learner's mentor for `course` (replacing any earlier one) and
    re-route their unrated work in that course. Raises `BadInput` for an ineligible mentor."""
    if not is_eligible_mentor(mentor, learner):
        raise BadInput(
            "That person can’t be this learner’s mentor. A mentor must be active, "
            "be allowed to rate simulations, and not be the learner."
        )
    row, _ = MentorAssignment.objects.update_or_create(
        learner=learner,
        course=course,
        defaults={"mentor": mentor, "assigned_by": by, "source": source},
    )
    reroute_open(learner, course)
    return row


@transaction.atomic
def unassign_mentor(learner, course: Course, *, by=None) -> bool:
    """Remove the learner's mentor for `course`; their unrated work there returns to the pool.
    Returns whether there was an assignment."""
    removed, _ = MentorAssignment.objects.filter(learner=learner, course=course).delete()
    if removed:
        reroute_open(learner, course)
    return bool(removed)


def reroute_open(learner, course: Course) -> int:
    """Re-route the learner's *unrated* submissions in this course that were routed by the
    assignment rules (not ones a trainer or admin routed by hand). A claim is cleared when the
    reviewer changes; a saved draft stays attached. Rated work is never touched. Returns how
    many moved."""
    mentor, routing = route_for_course(learner, course)
    moved = 0
    pending = (
        SimSubmission.objects.select_for_update()
        .filter(
            case__user=learner,
            case__activity__content_node__course_version__course=course,
            state=SimSubmission.State.SUBMITTED,
        )
        .exclude(routing=SimSubmission.Routing.ADMIN)
    )
    for sub in pending:
        new_id = mentor.pk if mentor is not None else None
        if sub.assigned_mentor_id == new_id and sub.routing == routing:
            continue
        sub.assigned_mentor = mentor
        sub.routing = routing
        sub.claimed_by = None
        sub.claimed_at = None
        sub.save(update_fields=["assigned_mentor", "routing", "claimed_by", "claimed_at"])
        moved += 1
    return moved


def route_for_course(learner, course: Course) -> tuple[User | None, str]:
    mentor = mentor_for(learner, course)
    if mentor is not None:
        return mentor, SimSubmission.Routing.ASSIGNMENT
    return None, SimSubmission.Routing.POOL
