"""
User and role administration — the rules behind the Admin Console's Users and
Roles screens. Views authorise and audit; every rule lives here.

Three safeguards run through everything:
  * you cannot lock yourself out (no self-deactivation, no removing your own
    Admin role or superuser flag);
  * the system can never be left with nobody able to administer it;
  * the Admin role always keeps the permissions needed to undo a mistake.
"""

from __future__ import annotations

import re
import secrets
from typing import Any

from axes.helpers import get_cool_off
from axes.models import AccessAttempt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.text import slugify

from .models import Role, RoleAssignment
from .rbac import ACTION_LABELS, ADMIN_LOCKED_ACTIONS, KNOWN_ACTIONS

User = get_user_model()

USER_ORDERING = {
    "name": "sort_name",
    "-name": "-sort_name",
    "last_login": "last_login",
    "-last_login": "-last_login",
    "joined": "date_joined",
    "-joined": "-date_joined",
}

EDITABLE_FIELDS = (
    "first_name",
    "last_name",
    "email",
    "employee_id",
    "timezone",
    "must_change_password",
)
PRIVILEGE_FIELDS = ("is_staff", "is_superuser")


class AdminError(Exception):
    """A refusal an administrator can act on, in plain words."""

    status_code = 400

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


# --------------------------------------------------------------------- lockouts


def locked_usernames() -> set[str]:
    """Accounts django-axes is currently refusing: enough recent failures."""
    attempts = AccessAttempt.objects.filter(failures_since_start__gte=settings.AXES_FAILURE_LIMIT)
    cool_off = get_cool_off()
    if cool_off is not None:
        attempts = attempts.filter(attempt_time__gte=timezone.now() - cool_off)
    return set(attempts.values_list("username", flat=True))


def unlock(user) -> int:
    """Clear the failed-login records so the person can try again now."""
    removed, _ = AccessAttempt.objects.filter(username=user.username).delete()
    return removed


# ------------------------------------------------------------------------ reads


def list_users(
    *,
    search: str = "",
    role: str = "",
    active: str = "",
    locked: str = "",
    ordering: str = "name",
):
    qs = User.objects.prefetch_related("role_assignments__role").annotate(sort_name=Lower("email"))
    if search:
        qs = qs.filter(
            Q(username__icontains=search)
            | Q(email__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(employee_id__icontains=search)
        )
    if role:
        qs = qs.filter(role_assignments__role__name=role)
    if active in ("true", "false"):
        qs = qs.filter(is_active=active == "true")
    if locked == "true":
        qs = qs.filter(username__in=locked_usernames())
    return qs.order_by(USER_ORDERING.get(ordering, "sort_name"), "pk")


def display_name(user) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.email or user.username


def role_names(user) -> list[str]:
    return sorted(a.role.name for a in user.role_assignments.all())


# --------------------------------------------------------------------- safeguards


def _administrators():
    """Active people who can administer: holders of the Admin role, superusers."""
    return User.objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(role_assignments__role__name=Role.Name.ADMIN)
    )


def _would_strand(*, excluding: set[int]) -> bool:
    return not _administrators().exclude(pk__in=excluding).exists()


# ------------------------------------------------------------------------ writes


def _validated_password(password: str, user=None) -> str:
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise AdminError(" ".join(exc.messages)) from exc
    return password


def generate_password() -> str:
    return secrets.token_urlsafe(9)


@transaction.atomic
def create_user(
    *,
    email: str,
    username: str = "",
    first_name: str = "",
    last_name: str = "",
    employee_id: str | None = None,
    timezone_name: str | None = None,
    password: str = "",
    roles: list[str] | None = None,
) -> tuple[Any, str | None]:
    """Create a person. Without a password one is generated and returned once;
    either way they must change it at first sign-in."""
    email = email.strip()
    username = (username or email).strip()
    if User.objects.filter(email__iexact=email).exists():
        raise AdminError("Someone already has that email address.")
    if User.objects.filter(username__iexact=username).exists():
        raise AdminError("That username is taken.")
    if employee_id and User.objects.filter(employee_id=employee_id).exists():
        raise AdminError("That employee id belongs to someone else.")
    names = roles if roles is not None else [Role.Name.LEARNER]
    found = {r.name: r for r in Role.objects.filter(name__in=names)}
    missing = sorted(set(names) - set(found))
    if missing:
        raise AdminError(f"Unknown role: {', '.join(missing)}.")

    generated = None
    if not password:
        generated = password = generate_password()
    else:
        _validated_password(password)

    extra = {"timezone": timezone_name} if timezone_name else {}
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        employee_id=employee_id or None,
        must_change_password=True,
        **extra,
    )
    for name in names:
        RoleAssignment.objects.create(user=user, role=found[name])
    return user, generated


@transaction.atomic
def update_user(actor, user, changes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Apply profile/access changes; returns {field: {"before", "after"}} for
    what actually changed (the audit trail). Privilege flags are for
    superusers only."""
    allowed = set(EDITABLE_FIELDS) | {"is_active"} | set(PRIVILEGE_FIELDS)
    unknown = set(changes) - allowed
    if unknown:
        raise AdminError(f"Can't change: {', '.join(sorted(unknown))}.")

    privileged = set(changes) & set(PRIVILEGE_FIELDS)
    if privileged and not actor.is_superuser:
        raise AdminError("Only a superuser can change staff or superuser access.", 403)

    if "email" in changes:
        changes["email"] = changes["email"].strip()
        if User.objects.filter(email__iexact=changes["email"]).exclude(pk=user.pk).exists():
            raise AdminError("Someone already has that email address.")
    if "employee_id" in changes:
        changes["employee_id"] = changes["employee_id"] or None
        taken = (
            changes["employee_id"]
            and User.objects.filter(employee_id=changes["employee_id"]).exclude(pk=user.pk).exists()
        )
        if taken:
            raise AdminError("That employee id belongs to someone else.")

    if changes.get("is_active") is False and user.pk == actor.pk:
        raise AdminError("You can’t deactivate your own account.")
    if changes.get("is_superuser") is False and user.pk == actor.pk:
        raise AdminError("You can’t remove your own superuser access.")
    losing_admin = changes.get("is_active") is False or changes.get("is_superuser") is False
    if losing_admin and user.is_active and _is_administrator(user):
        if changes.get("is_active") is False or not _holds_admin_role(user):
            if _would_strand(excluding={user.pk}):
                raise AdminError("That would leave nobody able to administer the system.")

    diff: dict[str, dict[str, Any]] = {}
    for field, value in changes.items():
        before = getattr(user, field)
        if before != value:
            diff[field] = {"before": before, "after": value}
            setattr(user, field, value)
    if diff:
        user.save(update_fields=list(diff))
    return diff


def _holds_admin_role(user) -> bool:
    return user.role_assignments.filter(role__name=Role.Name.ADMIN).exists()


def _is_administrator(user) -> bool:
    return user.is_active and (user.is_superuser or _holds_admin_role(user))


def set_password(user, password: str = "") -> str | None:
    """Give someone a new password (typed, or generated and returned once).
    They must change it next sign-in, and any open sessions end because the
    session hash changes with the password."""
    generated = None
    if not password:
        generated = password = generate_password()
    else:
        _validated_password(password, user)
    user.set_password(password)
    user.must_change_password = True
    user.save(update_fields=["password", "must_change_password"])
    return generated


@transaction.atomic
def set_roles(actor, user, names: list[str]) -> dict[str, list[str]]:
    """Make the user hold exactly these roles. Returns before/after."""
    wanted = set(names)
    found = {r.name: r for r in Role.objects.filter(name__in=wanted)}
    missing = sorted(wanted - set(found))
    if missing:
        raise AdminError(f"Unknown role: {', '.join(missing)}.")
    before = set(role_names(user))
    if Role.Name.ADMIN in before and Role.Name.ADMIN not in wanted and user.pk == actor.pk:
        raise AdminError("You can’t remove your own Admin role.")
    if Role.Name.ADMIN in before and Role.Name.ADMIN not in wanted and user.is_active:
        if not user.is_superuser and _would_strand(excluding={user.pk}):
            raise AdminError("That would leave nobody able to administer the system.")
    RoleAssignment.objects.filter(user=user).exclude(role__name__in=wanted).delete()
    for name in wanted - before:
        RoleAssignment.objects.create(user=user, role=found[name])
    return {"before": sorted(before), "after": sorted(wanted)}


# ------------------------------------------------------------------------ roles


def role_matrix() -> dict[str, Any]:
    """Every role with what it may do, plus the catalogue of actions."""
    roles = []
    counts = {r["role__name"]: r["n"] for r in _member_counts()}
    prefetched = {r.pk: r for r in Role.objects.prefetch_related("permissions__content_type")}
    for role in (prefetched[r.pk] for r in _ordered_roles()):
        granted = sorted(
            f"{p.content_type.app_label}.{p.codename}"
            for p in role.permissions.all()
            if f"{p.content_type.app_label}.{p.codename}" in KNOWN_ACTIONS
        )
        roles.append(
            {
                "id": role.pk,
                "name": role.name,
                "label": role.display_label,
                "builtin": role.is_builtin,
                "permissions": granted,
                "members": counts.get(role.name, 0),
                "locked": list(ADMIN_LOCKED_ACTIONS) if role.name == Role.Name.ADMIN else [],
            }
        )
    actions = [
        {"key": key, "label": ACTION_LABELS[key][0], "description": ACTION_LABELS[key][1]}
        for key in KNOWN_ACTIONS
    ]
    return {"roles": roles, "actions": actions}


def _ordered_roles():
    """The four built-in roles in their natural order, then custom ones as added."""
    builtin = list(Role.Name.values)
    return sorted(
        Role.objects.all(),
        key=lambda r: (builtin.index(r.name) if r.name in builtin else len(builtin), r.pk),
    )


ROLE_KEY = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def _role_key(label: str) -> str:
    return slugify(label).replace("-", "_")


@transaction.atomic
def create_role(label: str, permissions: list[str] | None = None) -> Role:
    """A new role administrators can hand out. Its key comes from the label."""
    label = " ".join(label.split())
    if not label:
        raise AdminError("Give the role a name.")
    if len(label) > 64:
        raise AdminError("That name is too long (64 characters at most).")
    key = _role_key(label)
    if not ROLE_KEY.match(key):
        raise AdminError("Use letters and numbers in the role’s name.")
    if key in Role.Name.values:
        raise AdminError("That name is used by a built-in role. Choose another.")
    if Role.objects.filter(name=key).exists() or Role.objects.filter(label__iexact=label).exists():
        raise AdminError("There is already a role with that name.")
    role = Role.objects.create(name=key, label=label)
    if permissions:
        set_role_permissions(role, permissions)
    return role


def rename_role(role: Role, label: str) -> dict[str, str]:
    if role.is_builtin:
        raise AdminError("Built-in roles can’t be renamed.")
    label = " ".join(label.split())
    if not label or len(label) > 64:
        raise AdminError("Give the role a name of 64 characters or fewer.")
    if Role.objects.filter(label__iexact=label).exclude(pk=role.pk).exists():
        raise AdminError("There is already a role with that name.")
    before = role.display_label
    role.label = label
    role.save(update_fields=["label"])
    return {"before": before, "after": label}


@transaction.atomic
def delete_role(role: Role) -> dict[str, Any]:
    """Remove a role nobody holds. Built-ins are permanent."""
    if role.is_builtin:
        raise AdminError("Built-in roles can’t be deleted.")
    holders = role.assignments.count()
    if holders:
        who = "person holds" if holders == 1 else "people hold"
        raise AdminError(f"{holders} {who} this role. Move them to another role first.", 409)
    snapshot = {
        "name": role.name,
        "label": role.display_label,
        "permissions": sorted(
            f"{p.content_type.app_label}.{p.codename}"
            for p in role.permissions.select_related("content_type")
        ),
    }
    role.delete()
    return snapshot


def role_options() -> list[dict[str, Any]]:
    """Name and label of every role — enough to show or pick one."""
    return [
        {"name": r.name, "label": r.display_label, "builtin": r.is_builtin}
        for r in _ordered_roles()
    ]


def _member_counts():
    from django.db.models import Count

    return (
        RoleAssignment.objects.filter(user__is_active=True)
        .values("role__name")
        .annotate(n=Count("user", distinct=True))
    )


@transaction.atomic
def set_role_permissions(role: Role, keys: list[str]) -> dict[str, list[str]]:
    """Make the role grant exactly these actions (only ones we know about)."""
    wanted = set(keys)
    unknown = sorted(wanted - set(KNOWN_ACTIONS))
    if unknown:
        raise AdminError(f"Unknown permission: {', '.join(unknown)}.")
    if role.name == Role.Name.ADMIN:
        dropped = sorted(set(ADMIN_LOCKED_ACTIONS) - wanted)
        if dropped:
            raise AdminError(
                "Admins must keep “Manage users” and “Manage roles”, "
                "or nobody could undo a mistake."
            )
    perms = []
    for key in wanted:
        app_label, codename = key.split(".", 1)
        try:
            perms.append(
                Permission.objects.get(content_type__app_label=app_label, codename=codename)
            )
        except Permission.DoesNotExist as exc:
            raise AdminError(f"Permission {key} isn’t set up on this server.") from exc
    before = sorted(
        f"{p.content_type.app_label}.{p.codename}"
        for p in role.permissions.select_related("content_type")
        if f"{p.content_type.app_label}.{p.codename}" in KNOWN_ACTIONS
    )
    # Keep any permission outside the console's catalogue exactly as it was.
    outside = [
        p
        for p in role.permissions.select_related("content_type")
        if f"{p.content_type.app_label}.{p.codename}" not in KNOWN_ACTIONS
    ]
    role.permissions.set([*perms, *outside])
    return {"before": before, "after": sorted(wanted)}
