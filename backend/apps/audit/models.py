"""
Who did what, to what, and when — written by every Admin Console mutation
(and by sensitive reads such as an export). Django Admin keeps its own
`LogEntry` for changes made there; this is the log for the console.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # A snapshot, so the entry still reads correctly if the account is later
    # renamed or removed.
    actor_label = models.CharField(max_length=255)
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    target_label = models.CharField(max_length=255, blank=True)
    # A small summary or before/after pair. Never secrets (see services.record).
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        permissions = [("view_audit", "Can view the audit log")]

    def __str__(self) -> str:
        return f"{self.actor_label} · {self.action} · {self.target_label or self.target_type}"
