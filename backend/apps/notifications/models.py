"""A message for one person: something changed, or something is waiting for them.

Each row is a plain-text snapshot written for its recipient. `dedupe_key` (when given) makes a
message idempotent per person: a job that runs again, or an event that fires twice, never repeats
it. The keys are written by the code that raises the notice (see `services`), for example
`due-soon:<case>:<due_at>`, so a *changed* deadline is a different key and notifies again.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    # What it is about (`enrolled`, `quiz_marked`, ...): lets a channel or a filter treat kinds
    # differently later. Free text on purpose, so a new kind never needs a migration.
    kind = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    # Where it takes you: an in-app path ("/courses/1"), never an external address.
    link = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)
    dedupe_key = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "dedupe_key"],
                condition=~Q(dedupe_key=""),
                name="uniq_notification_key",
            )
        ]
        indexes = [models.Index(fields=["user", "read_at", "-created_at"], name="notif_user_read")]

    def __str__(self) -> str:
        return f"{self.user}: {self.title}"

    @property
    def is_read(self) -> bool:
        return self.read_at is not None
