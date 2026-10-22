from __future__ import annotations

import re
from typing import Any

from .models import AuditLog

_SECRET_KEY = re.compile(r"password|secret|token|key", re.IGNORECASE)
# Names that merely *mention* a secret (a yes/no flag), not hold one.
_NOT_SECRET = {"must_change_password"}


def _scrub(value: Any) -> Any:
    """Never write a secret into the log, however it got into `changes`."""
    if isinstance(value, dict):
        return {
            k: "[hidden]" if k not in _NOT_SECRET and _SECRET_KEY.search(str(k)) else _scrub(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _client_ip(request) -> str | None:
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def record(
    request,
    action: str,
    *,
    target_type: str = "",
    target_id: object = "",
    target_label: str = "",
    changes: dict | None = None,
    actor=None,
) -> AuditLog:
    """Append one entry. Pass the DRF/Django `request` (the actor and IP come
    from it) or an explicit `actor` for non-request callers."""
    who = actor or getattr(request, "user", None)
    if who is not None and not getattr(who, "is_authenticated", False):
        who = None
    return AuditLog.objects.create(
        actor=who,
        actor_label=(who.email or who.username) if who is not None else "system",
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        target_label=target_label[:255],
        changes=_scrub(changes or {}),
        ip_address=_client_ip(request),
    )
