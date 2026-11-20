"""Certificates: what it takes to earn one on a course, and the ones that were earned.

`CertificatePolicy` is a per-course setting (not part of a version), so a trainer can change the
pass bar without publishing. A `Certificate` is a snapshot: the score, the threshold and the weights
at the moment it was issued, so it can always be explained later even if the policy changes. It is
never taken back automatically; only a person can revoke one, with a reason.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

DEFAULT_THRESHOLD = 70


class CertificatePolicy(models.Model):
    course = models.OneToOneField(
        "catalog.Course", on_delete=models.CASCADE, related_name="certificate_policy"
    )
    enabled = models.BooleanField(default=False)
    # Whole percent, 1–100: the course score needed.
    threshold = models.PositiveSmallIntegerField(
        default=DEFAULT_THRESHOLD, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    # Relative weights of each kind of scored work (0 leaves that kind out of the score).
    weight_quiz = models.PositiveSmallIntegerField(default=1)
    weight_practice = models.PositiveSmallIntegerField(default=1)
    weight_rated = models.PositiveSmallIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    def __str__(self) -> str:
        return f"Certificate policy for {self.course}"

    @property
    def weights(self) -> dict[str, int]:
        return {
            "quiz": self.weight_quiz,
            "practice": self.weight_practice,
            "rated": self.weight_rated,
        }


def new_code() -> str:
    """A short, unguessable id printed on the certificate."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I
    return "".join(secrets.choice(alphabet) for _ in range(10))


class Certificate(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="certificates"
    )
    course = models.ForeignKey(
        "catalog.Course", on_delete=models.PROTECT, related_name="certificates"
    )
    version = models.ForeignKey(
        "catalog.CourseVersion", on_delete=models.PROTECT, related_name="certificates"
    )
    enrollment = models.ForeignKey(
        "enrollment.Enrollment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="certificates",
    )
    code = models.CharField(max_length=16, unique=True, default=new_code)
    course_title = models.CharField(max_length=255)
    issued_at = models.DateTimeField()
    # The snapshot: score 0–1 (None when the course has no scored work, so completion alone
    # earned it), threshold in whole percent, weights and per-kind breakdown.
    score = models.FloatField(null=True, blank=True)
    threshold = models.PositiveSmallIntegerField()
    weights = models.JSONField(default=dict)
    breakdown = models.JSONField(default=dict)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    revoked_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-issued_at", "-id"]
        constraints = [
            # One standing certificate per person and course; a revoked one stays on record.
            models.UniqueConstraint(
                fields=["user", "course"],
                condition=Q(revoked_at__isnull=True),
                name="uniq_live_certificate",
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} · {self.user} · {self.course_title}"

    @property
    def is_live(self) -> bool:
        return self.revoked_at is None
