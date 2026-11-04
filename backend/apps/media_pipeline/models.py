"""An uploaded video and where it is in becoming something a browser can play.

The database row is the source of truth for processing: a worker *claims* an
asset with a compare-and-set, and a sweeper (`services.recover_stuck_assets`)
re-queues whatever a lost message or a killed worker left behind. Nothing here
depends on the message broker being reliable.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class MediaAsset(models.Model):
    class Kind(models.TextChoices):
        VIDEO = "video", "Video"

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Waiting to be processed"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    # Names files on disk, so a stored path never contains anything the uploader typed.
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="media_assets",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.VIDEO)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UPLOADED)

    original_name = models.CharField(max_length=255)
    size_bytes = models.BigIntegerField()
    duration_seconds = models.FloatField(null=True, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)

    # Paths relative to MEDIA_ROOT. Empty once a file no longer exists.
    original_path = models.CharField(max_length=512, blank=True)
    video_path = models.CharField(max_length=512, blank=True)
    poster_path = models.CharField(max_length=512, blank=True)
    output_size_bytes = models.BigIntegerField(null=True, blank=True)
    output_sha256 = models.CharField(max_length=64, blank=True)
    original_purged = models.BooleanField(default=False)

    # A sentence an author can read; ffmpeg's own output only ever goes to logs.
    error = models.CharField(max_length=255, blank=True)
    retryable = models.BooleanField(default=False)

    attempts = models.PositiveSmallIntegerField(default=0)
    enqueued_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    ready_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "created_at"], name="media_status_created")]

    def __str__(self) -> str:
        return f"{self.original_name} ({self.status})"
