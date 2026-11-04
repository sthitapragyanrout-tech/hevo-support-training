"""Mentor-rated simulations: what a learner handed in, who rates it, and how it went.

A learner works on one activity as a `SimCase` (their deadline and how it ended). Each time
they hand something in it is a new, immutable `SimSubmission` (a *revision*); a mentor's
rating of it is a set of `RubricScore` rows. Nothing is ever edited after it is submitted or
rated, so the history of a case is simply its rows. Deadlines and overdue-ness are computed
from timestamps when read, never stored as flags.

Who rates what: `MentorAssignment` (a learner's mentor for one course) is written only by
`assignments.assign_mentor`; until the enrolment workflow exists nothing calls it, so every
submission goes to the shared pool.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class MentorAssignment(models.Model):
    """A learner's mentor for one course. Written only through `assignments`."""

    learner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mentor_assignments"
    )
    course = models.ForeignKey(
        "catalog.Course", on_delete=models.CASCADE, related_name="mentor_assignments"
    )
    mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mentees"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    assigned_at = models.DateTimeField(auto_now=True)
    # Where the assignment came from; the enrolment workflow will write "enrollment".
    source = models.CharField(max_length=24, default="enrollment")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["learner", "course"], name="uniq_mentor_assignment_learner_course"
            )
        ]

    def __str__(self) -> str:
        return f"{self.learner} → {self.mentor} ({self.course})"


class SimCase(models.Model):
    """One learner's work on one activity: the deadline they are working to, and how it ended
    if a trainer or admin closed it. Created the first time they open the activity."""

    class DueBasis(models.TextChoices):
        INITIAL = "initial", "From first opening"
        REVISION = "revision", "To revise after feedback"
        EXTENDED = "extended", "Extended"

    class Closed(models.TextChoices):
        WAIVED = "waived", "Waived"
        NOT_PASSED = "not_passed", "Closed, not passed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sim_cases"
    )
    activity = models.ForeignKey(
        "catalog.Activity", on_delete=models.CASCADE, related_name="sim_cases"
    )
    opened_at = models.DateTimeField()
    due_at = models.DateTimeField(null=True, blank=True)
    due_basis = models.CharField(max_length=10, choices=DueBasis.choices, default=DueBasis.INITIAL)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    closed_reason = models.CharField(max_length=12, choices=Closed.choices, blank=True)
    close_note = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "activity"], name="uniq_sim_case_user_activity")
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.activity}"

    @property
    def is_closed(self) -> bool:
        return self.closed_at is not None


class SimSubmission(models.Model):
    """One revision handed in. Immutable once submitted; rating only fills the outcome."""

    class State(models.TextChoices):
        SUBMITTED = "submitted", "Waiting for a mentor"
        RATED = "rated", "Rated"
        WITHDRAWN = "withdrawn", "Withdrawn"

    class Routing(models.TextChoices):
        POOL = "pool", "Shared pool"
        ASSIGNMENT = "assignment", "The learner's mentor for the course"
        ADMIN = "admin", "Routed by a trainer or admin"

    case = models.ForeignKey(SimCase, on_delete=models.CASCADE, related_name="submissions")
    revision = models.PositiveIntegerField()
    previous = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="next_revisions"
    )
    answer = models.TextField()
    links = models.JSONField(default=list, blank=True)
    submitted_at = models.DateTimeField()
    # The deadline in force when it was handed in, and whether it was after it.
    due_snapshot = models.DateTimeField(null=True, blank=True)
    late = models.BooleanField(default=False)
    # The mentor's clock: independent of the learner's deadline and of lateness.
    review_due_at = models.DateTimeField()

    state = models.CharField(max_length=10, choices=State.choices, default=State.SUBMITTED)
    withdrawn_by = models.CharField(max_length=12, blank=True)  # learner | trainer | closed

    assigned_mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    routing = models.CharField(max_length=10, choices=Routing.choices, default=Routing.POOL)
    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    # The rater's unsaved scores and comment; `draft_by` is whose they are.
    draft = models.JSONField(default=dict, blank=True)
    draft_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    # The outcome, filled once by the rating.
    rated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    rated_at = models.DateTimeField(null=True, blank=True)
    overall_comment = models.TextField(blank=True)
    raw_score = models.FloatField(null=True, blank=True)  # the overall on the 1–5 scale
    scaled = models.FloatField(null=True, blank=True)  # raw / 5; never shown as a percentage
    passed = models.BooleanField(null=True, blank=True)
    attempt = models.ForeignKey(
        "progress.ActivityAttempt",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["case_id", "revision"]
        constraints = [
            models.UniqueConstraint(fields=["case", "revision"], name="uniq_sim_revision"),
            # A learner may have only one piece of work waiting at a time.
            models.UniqueConstraint(
                fields=["case"],
                condition=Q(state="submitted"),
                name="uniq_open_sim_submission",
            ),
        ]
        indexes = [
            models.Index(fields=["state", "submitted_at"], name="sim_sub_state_when"),
            models.Index(fields=["assigned_mentor", "state"], name="sim_sub_mentor_state"),
        ]
        permissions = [
            ("rate_submissions", "Can rate mentor-rated simulations"),
            ("manage_reviews", "Can manage simulation reviews"),
        ]

    def __str__(self) -> str:
        return f"{self.case} · revision {self.revision} ({self.state})"


class RubricScore(models.Model):
    """One criterion's score on one rated submission (the criterion's label is copied, so the
    record reads the same whatever happens to the activity later)."""

    submission = models.ForeignKey(SimSubmission, on_delete=models.CASCADE, related_name="scores")
    criterion_key = models.CharField(max_length=64)
    label = models.CharField(max_length=200)
    max_score = models.PositiveSmallIntegerField(default=5)
    score = models.PositiveSmallIntegerField()
    feedback = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["submission_id", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "criterion_key"], name="uniq_rubric_score_criterion"
            )
        ]

    def __str__(self) -> str:
        return f"{self.label}: {self.score}/{self.max_score}"


class SubmissionFile(models.Model):
    """An attachment, stored on disk under a name we chose (`uuid` + the extension of the
    type *we* detected), never anything the uploader typed."""

    submission = models.ForeignKey(SimSubmission, on_delete=models.CASCADE, related_name="files")
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=64)
    extension = models.CharField(max_length=8)
    size_bytes = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["submission_id", "id"]

    @property
    def relative_path(self) -> str:
        return f"attachments/{self.uuid}.{self.extension}"

    def __str__(self) -> str:
        return self.original_name
