"""Who can rate a mentor-rated simulation. One place, used by routing, the queue, the mentor
picker and the publish check.

"Can rate" means active and holding `manual_sim.rate_submissions` through a role. Superusers
pass `can()` everywhere, so they count as able to rate, but they are not offered as people to
route work to (nobody holds that as a job).
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Q, QuerySet

RATE = "manual_sim.rate_submissions"
MANAGE = "manual_sim.manage_reviews"


def _by_role(action: str) -> Q:
    app_label, codename = action.split(".", 1)
    return Q(
        role_assignments__role__permissions__content_type__app_label=app_label,
        role_assignments__role__permissions__codename=codename,
    )


def raters() -> QuerySet:
    """Active people holding the rating permission through a role (the mentor picker)."""
    user = get_user_model()
    return user.objects.filter(is_active=True).filter(_by_role(RATE)).distinct()


def someone_can_rate() -> bool:
    user = get_user_model()
    return (
        user.objects.filter(is_active=True).filter(Q(is_superuser=True) | _by_role(RATE)).exists()
    )


def is_rater(user) -> bool:
    """May this person rate at all (the permission, ignoring whose work it is)?"""
    if user is None or not getattr(user, "is_active", False):
        return False
    return raters().filter(pk=user.pk).exists() or bool(user.is_superuser)
