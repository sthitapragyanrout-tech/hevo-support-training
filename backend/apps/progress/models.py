"""
What a learner has done — deliberately small: one row per (learner, activity)
and one per (learner, lesson). Module and course progress are *derived* from
lesson completion, never stored, so they can't drift.

Rows point at nodes/activities of a specific published version. Until
enrollments pin learners to a version, a newly published version therefore
starts fresh. (An xAPI-shaped statement store can be back-filled from these
timestamps later.)
"""

from django.conf import settings
from django.db import models


class ActivityProgress(models.Model):
    class State(models.TextChoices):
        STARTED = "started", "Started"
        COMPLETED = "completed", "Completed"
        # A scored activity whose attempts are all used without a pass: it
        # no longer blocks the lesson, and every score stays on record.
        EXHAUSTED = "exhausted", "Finished, not passed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="activity_progress"
    )
    activity = models.ForeignKey(
        "catalog.Activity", on_delete=models.CASCADE, related_name="progress"
    )
    state = models.CharField(max_length=16, choices=State.choices, default=State.STARTED)
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "activity"], name="uniq_activity_progress")
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.activity} · {self.state}"


class ActivityAttempt(models.Model):
    """One scored try at an activity (a quiz submission). Generic on purpose:
    any scored type records the same shape, and an xAPI statement store can be
    back-filled from these rows. `details` holds the per-item verdicts only —
    never an answer key."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="activity_attempts"
    )
    activity = models.ForeignKey(
        "catalog.Activity", on_delete=models.CASCADE, related_name="attempts"
    )
    number = models.PositiveIntegerField()
    answers = models.JSONField(default=list)
    details = models.JSONField(default=list)
    score = models.FloatField()
    passed = models.BooleanField()
    submitted_at = models.DateTimeField()

    class Meta:
        ordering = ["activity_id", "number"]
        permissions = [
            ("view_results", "Can view learners' results"),
            ("manage_attempts", "Can reset a learner's quiz attempts"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "activity", "number"], name="uniq_activity_attempt_number"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.activity} · attempt {self.number}"


class LessonCompletion(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_completions"
    )
    node = models.ForeignKey(
        "catalog.ContentNode", on_delete=models.CASCADE, related_name="completions"
    )
    completed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "node"], name="uniq_lesson_completion")
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.node}"
