"""Raising, resolving and clearing notifications.

Two rules matter more than the rest:

* **A notification never breaks what raised it.** `notify` runs in its own savepoint and swallows
  (and logs) any failure, so a bug here can't stop a rating, an enrollment or a sweep.
* **It is written inside the caller's transaction.** If the event rolls back, so does the notice:
  nobody is told about something that didn't happen.

`deliver` is the seam for other channels. Email, when it is built, belongs there (send after the
transaction commits, respecting a per-person preference); nothing else needs to change.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import Notification

log = logging.getLogger(__name__)

MAX_TITLE = 200
MAX_BODY = 2000
READ_KEPT_DAYS = 90
ANY_KEPT_DAYS = 180


def _clean_link(link: str) -> str:
    """Only paths inside the app: a notification can't point anywhere else."""
    return link if link.startswith("/") and not link.startswith("//") else ""


def notify(
    user,
    kind: str,
    title: str,
    body: str = "",
    link: str = "",
    dedupe_key: str = "",
) -> Notification | None:
    """Tell `user` something. Returns the new notification, or None if there was nothing to do
    (no user, a deactivated user, already told under this key) or it could not be written."""
    if user is None or not getattr(user, "is_active", False):
        return None
    try:
        with transaction.atomic():
            fields: dict[str, Any] = {
                "kind": kind,
                "title": title[:MAX_TITLE],
                "body": body[:MAX_BODY],
                "link": _clean_link(link),
            }
            if dedupe_key:
                notification, created = Notification.objects.get_or_create(
                    user=user, dedupe_key=dedupe_key, defaults=fields
                )
                if not created:
                    return None
            else:
                notification = Notification.objects.create(user=user, **fields)
    except Exception:  # noqa: BLE001 - deliberately broad: see the module docstring
        log.exception(
            "Could not write a %r notification for user %s", kind, getattr(user, "pk", "?")
        )
        return None
    deliver(notification)
    return notification


def notify_many(
    users: Iterable,
    kind: str,
    title: str,
    body: str = "",
    link: str = "",
    dedupe_key: str = "",
) -> list[Notification]:
    """The same message to several people; each gets their own copy (and their own dedupe key)."""
    out: list[Notification] = []
    for user in users:
        key = f"{dedupe_key}:{user.pk}" if dedupe_key else ""
        made = notify(user, kind, title, body, link, key)
        if made is not None:
            out.append(made)
    return out


def deliver(notification: Notification) -> None:
    """Hand a new notification to the channels beyond the in-app list. Nothing yet; email will be
    sent from here after commit (`transaction.on_commit`), if the person wants it."""


def resolve(prefix: str, *, now=None) -> int:
    """Mark every unread notification whose key starts with `prefix` as read. Used when the thing
    a notice was about is over (work rated, withdrawn, reassigned), so it doesn't linger."""
    if not prefix:
        return 0
    return Notification.objects.filter(dedupe_key__startswith=prefix, read_at__isnull=True).update(
        read_at=now or timezone.now()
    )


def unread_count(user) -> int:
    return Notification.objects.filter(user=user, read_at__isnull=True).count()


def mark_read(user, notification_id: int, *, now=None) -> Notification | None:
    """Mark one of `user`'s own notifications read. None if it isn't theirs (or doesn't exist)."""
    found = Notification.objects.filter(pk=notification_id, user=user).first()
    if found is not None and found.read_at is None:
        found.read_at = now or timezone.now()
        found.save(update_fields=["read_at"])
    return found


def mark_all_read(user, *, now=None) -> int:
    return Notification.objects.filter(user=user, read_at__isnull=True).update(
        read_at=now or timezone.now()
    )


def prune(*, now=None) -> int:
    """Delete read notifications older than 90 days, and any older than 180. Returns how many."""
    now = now or timezone.now()
    old_read = Notification.objects.filter(
        read_at__isnull=False, created_at__lt=now - timedelta(days=READ_KEPT_DAYS)
    )
    very_old = Notification.objects.filter(created_at__lt=now - timedelta(days=ANY_KEPT_DAYS))
    deleted = old_read.delete()[0]
    return deleted + very_old.delete()[0]
