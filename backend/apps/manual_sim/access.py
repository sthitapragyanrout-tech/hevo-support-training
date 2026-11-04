"""Who may act on a submission, and the two clocks.

`can_rate`-style decisions live here, in one place, because the generic `rbac.can(user, action,
obj)` scope check is deliberately a no-op: every Console endpoint that touches a submission
must go through `rating_access` (or `can_see`). A missed call would show a mentor someone else's
learner, so the authorisation tests walk every endpoint.

The clocks are computed from timestamps when read — nothing here is stored as a flag:

* the learner's: `SimCase.due_at` (overdue = nothing waiting or passed, and now is past it);
* the mentor's: `SimSubmission.review_due_at` (overdue = still waiting past it), plus a grace
  after which any eligible rater may take the work ("escalated").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.rbac import can

from . import eligibility
from .models import SimSubmission

RATE = eligibility.RATE
MANAGE = eligibility.MANAGE


def is_manager(user) -> bool:
    return can(user, MANAGE)


def is_rater(user) -> bool:
    return can(user, RATE)


# --------------------------------------------------------------------------- clocks


def lease(sub: SimSubmission, now) -> User | None:
    """Who currently holds the claim (None if nobody, or the lease ran out)."""
    if sub.claimed_by_id is None or sub.claimed_at is None:
        return None
    if now >= sub.claimed_at + timedelta(minutes=settings.MANUAL_SIM_CLAIM_MINUTES):
        return None
    return sub.claimed_by


def review_overdue(sub: SimSubmission, now) -> bool:
    return sub.state == SimSubmission.State.SUBMITTED and now > sub.review_due_at


def escalated(sub: SimSubmission, now) -> bool:
    """Overdue by more than the grace: open to any eligible rater, whoever it was routed to."""
    grace = timedelta(hours=settings.MANUAL_SIM_ESCALATION_GRACE_HOURS)
    return sub.state == SimSubmission.State.SUBMITTED and now > sub.review_due_at + grace


def in_pool(sub: SimSubmission, now, rater_ids: set[int] | None = None) -> bool:
    """Open to any eligible rater: routed to the pool, escalated, or routed to someone who is
    no longer able to rate."""
    if sub.assigned_mentor_id is None or escalated(sub, now):
        return True
    ids = (
        rater_ids
        if rater_ids is not None
        else set(eligibility.raters().values_list("pk", flat=True))
    )
    return sub.assigned_mentor_id not in ids


# ----------------------------------------------------------------------- who may act


@dataclass(frozen=True)
class Access:
    allowed: bool
    via: str = ""  # "manager" | "assigned" | "pool" | "claim"
    reason: str = ""
    held_by: User | None = None  # someone else's live claim, if that is what blocks you


def rating_access(user, sub: SimSubmission, now=None, rater_ids: set[int] | None = None) -> Access:
    """May `user` claim, draft and rate this submission right now?"""
    now = now or timezone.now()
    if not is_rater(user):
        return Access(False, reason="You can’t rate simulations.")
    if sub.case.user_id == user.pk:
        return Access(False, reason="You can’t rate your own work.")
    if sub.state != SimSubmission.State.SUBMITTED:
        return Access(False, reason="This submission isn’t waiting for a rating.")
    holder = lease(sub, now)
    if is_manager(user):
        return Access(
            True, via="manager", held_by=holder if holder and holder.pk != user.pk else None
        )
    if sub.assigned_mentor_id == user.pk and not escalated(sub, now):
        return Access(True, via="assigned")
    if in_pool(sub, now, rater_ids):
        if holder is not None and holder.pk != user.pk:
            return Access(False, reason="Another mentor is rating this one.", held_by=holder)
        return Access(True, via="pool")
    return Access(False, reason="This submission is with another mentor.")


def can_see(user, sub: SimSubmission, now=None) -> bool:
    """May `user` read this submission and its thread? The learner who made it; managers; anyone
    who may rate it now; and the people who see learners' results."""
    now = now or timezone.now()
    if sub.case.user_id == user.pk:
        return True
    if is_manager(user) or can(user, "progress.view_results"):
        return True
    if not is_rater(user):
        return False
    if sub.assigned_mentor_id == user.pk or sub.rated_by_id == user.pk:
        return True
    # Work open to every rater is visible to every rater, including while someone else holds
    # it (they are told who); work with another mentor is not.
    return sub.state == SimSubmission.State.SUBMITTED and in_pool(sub, now)
