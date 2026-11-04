"""
The one seam every authorization decision — Django admin and, from M2 on,
the DRF API — funnels through. See docs/architecture.md §11.

Permissions are read directly from `Role.permissions` for every role the
user holds (via `RoleAssignment`) — not from `user.has_perm()`/Django
Groups. `has_perm()` has exactly one caller in this codebase (this file);
everything else (admin, DRF) calls `can()` directly, so there's no need for
a custom authentication backend just to make `has_perm()` itself resolve
role permissions — this is simpler and touches nothing else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.models import Permission

from .models import Role

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser
    from django.db import models

    from .models import User

# The §11 seed role matrix, translated into Django permission codenames
# ("<app_label>.<codename>"). Only the M1-relevant permissions are mapped —
# rating/reporting/escalation permissions get added here as their owning
# apps (assessment, enrollment, ...) land in later milestones.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.Name.LEARNER: [],
    Role.Name.TRAINER: [
        "catalog.author_content",
        "progress.view_results",
        "progress.manage_attempts",
        "manual_sim.rate_submissions",
        "manual_sim.manage_reviews",
    ],
    Role.Name.MENTOR: ["manual_sim.rate_submissions"],
    Role.Name.ADMIN: [
        "catalog.author_content",
        "catalog.publish_courseversion",
        "accounts.manage_users",
        "accounts.manage_roles",
        "progress.view_results",
        "progress.manage_attempts",
        "audit.view_audit",
        "manual_sim.rate_submissions",
        "manual_sim.manage_reviews",
    ],
}


# Every action the SPA may need to know about, so the session can tell the UI
# what the signed-in user is allowed to do (the server remains the authority:
# each endpoint still calls `can()` itself).
KNOWN_ACTIONS: tuple[str, ...] = (
    "catalog.author_content",
    "catalog.publish_courseversion",
    "accounts.manage_users",
    "accounts.manage_roles",
    "progress.view_results",
    "progress.manage_attempts",
    "audit.view_audit",
    "manual_sim.rate_submissions",
    "manual_sim.manage_reviews",
)


# What each action means, in plain words, for the role matrix in the console.
ACTION_LABELS: dict[str, tuple[str, str]] = {
    "catalog.author_content": ("Author courses", "Create and edit courses in Studio."),
    "catalog.publish_courseversion": (
        "Publish courses",
        "Publish a submitted course so learners can see it.",
    ),
    "accounts.manage_users": (
        "Manage users",
        "Create, edit and deactivate users; reset passwords; unlock accounts.",
    ),
    "accounts.manage_roles": (
        "Manage roles",
        "Assign roles to users and change what each role may do.",
    ),
    "progress.view_results": ("View learner results", "See learners' progress and quiz scores."),
    "progress.manage_attempts": (
        "Reset quiz attempts",
        "Let a learner retake a quiz by clearing their attempts.",
    ),
    "audit.view_audit": ("View the audit log", "See who changed what in the console."),
    "manual_sim.rate_submissions": (
        "Rate simulations",
        "Rate the mentor-rated simulations of learners assigned to you and the shared review pool.",
    ),
    "manual_sim.manage_reviews": (
        "Manage simulation reviews",
        "Reassign reviews, extend deadlines, waive or close cases, and rate any submission.",
    ),
}

# Actions an Admin must always keep, or nobody could fix a mistake.
ADMIN_LOCKED_ACTIONS: tuple[str, ...] = (
    "accounts.manage_users",
    "accounts.manage_roles",
    "manual_sim.manage_reviews",
)


def _effective_permissions(user: User) -> set[str]:
    """Union of `Role.permissions` (as "<app_label>.<codename>" strings)
    across every role `user` holds via `RoleAssignment`.
    """
    pairs = Permission.objects.filter(role__assignments__user=user).values_list(
        "content_type__app_label", "codename"
    )
    return {f"{app_label}.{codename}" for app_label, codename in pairs}


def can(user: User | AnonymousUser, action: str, obj: models.Model | None = None) -> bool:
    """Return whether `user` may perform `action` (a Django permission
    codename, e.g. "catalog.author_content"), optionally scoped to `obj`.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if action not in _effective_permissions(user):
        return False
    if obj is None:
        return True
    return _scope_check(user, action, obj)


def _scope_check(user: User, action: str, obj: models.Model) -> bool:
    """Object-level scoping on top of the global permission check.

    M1 has nothing to scope against yet. There are two independent axes
    this will eventually cover, neither built out: (a) Group-based
    org-unit isolation — once some model carries a `group` FK, check
    `obj.group is None or obj.group == user.group`; (b) relational
    assignment scoping (e.g. a Mentor rating only their assigned
    trainees) — once `MentorAssignment` exists (M2), check a matching row
    exists. Until then this always returns True once the caller already
    holds the global permission. Intentionally a real function (not
    inlined into `can()`) so those follow-ups are one-function changes,
    not new call sites everywhere. See
    tests/test_rbac.py::test_can_scope_check_is_currently_a_noop.
    """
    return True


def capabilities_for(user: User) -> list[str]:
    """The known actions `user` may perform — for the SPA to show/hide UI."""
    return [action for action in KNOWN_ACTIONS if can(user, action)]
