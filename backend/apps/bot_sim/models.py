"""Practice tickets: the scenarios trainers approve, the sessions learners play,
and the bookkeeping that keeps the model calls bounded.

Idempotency lives in the database, not in the queue: every step that must happen
exactly once is guarded by a unique key or a compare-and-set, so a retry, a
duplicate message or a killed worker can only ever repeat *work*, never a
*result* (see `services.py`).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q


class Scenario(models.Model):
    """One customer question a learner may be given. Only `approved` scenarios are
    ever used in a scored session."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"
        RETIRED = "retired", "Retired"

    class Source(models.TextChoices):
        GENERATED = "generated", "Generated"
        MANUAL = "manual", "Written by hand"
        SEED = "seed", "Sample"
        ZENDESK = "zendesk", "From a past customer query"

    topic = models.CharField(max_length=40)
    persona_type = models.CharField(max_length=20)
    issue_summary = models.CharField(max_length=300)
    opening_message = models.TextField()
    personality_notes = models.TextField()
    # Keywords a correct documentation page would contain (for judging link relevance).
    doc_hints = models.JSONField(default=list, blank=True)
    # Future grounding: what a correct reply should convey, and where it is documented.
    reference_answer = models.TextField(blank=True)
    doc_url = models.CharField(max_length=300, blank=True)

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.MANUAL)
    # Imported from a past Zendesk ticket: only its id is kept (never the customer's own text).
    # Unique, so importing the same ticket twice can never create two scenarios.
    source_ticket_id = models.CharField(max_length=40, null=True, blank=True, unique=True)
    # Approved by the strict automatic checks rather than by a person.
    auto_approved = models.BooleanField(default=False)
    # Why a trainer should look again (e.g. several learners skipped it as unclear).
    review_note = models.CharField(max_length=200, blank=True)
    import_run = models.ForeignKey(
        "ScenarioImport",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="scenarios",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "topic", "persona_type"], name="scenario_pick")]

    def __str__(self) -> str:
        return f"{self.issue_summary} ({self.status})"

    def snapshot(self) -> dict:
        from simbot_engine.scenario import Scenario as EngineScenario

        return EngineScenario(
            topic=self.topic,
            persona_type=self.persona_type,
            issue_summary=self.issue_summary,
            opening_message=self.opening_message,
            personality_notes=self.personality_notes,
            doc_hints=tuple(self.doc_hints or []),
            reference_answer=self.reference_answer,
            doc_url=self.doc_url,
        ).snapshot()


class SimSession(models.Model):
    """One learner's go at one practice ticket (or an author's unrecorded preview)."""

    class State(models.TextChoices):
        OPEN = "open", "In progress"
        FINISHING = "finishing", "Preparing feedback"
        FINISHED = "finished", "Finished"
        ABANDONED = "abandoned", "Abandoned"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sim_sessions"
    )
    activity = models.ForeignKey(
        "catalog.Activity", on_delete=models.CASCADE, related_name="sim_sessions"
    )
    scenario = models.ForeignKey(Scenario, on_delete=models.PROTECT, related_name="sessions")
    # The scenario as it was when the session began: later edits never change a transcript.
    scenario_snapshot = models.JSONField(default=dict)
    repeated = models.BooleanField(default=False)
    preview = models.BooleanField(default=False)  # an author trying it: nothing recorded
    state = models.CharField(max_length=12, choices=State.choices, default=State.OPEN)
    abandon_reason = models.CharField(max_length=80, blank=True)
    # When the learner skipped the question instead of answering it (see `services.skip`).
    skip_reason = models.CharField(max_length=16, blank=True)

    # Settings frozen at the start, so editing the activity can't change a session mid-way.
    config_snapshot = models.JSONField(default=dict)

    started_at = models.DateTimeField()
    last_activity_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    narrative = models.JSONField(null=True, blank=True)
    narrative_attempts = models.PositiveSmallIntegerField(default=0)
    result = models.JSONField(null=True, blank=True)
    attempt = models.OneToOneField(
        "progress.ActivityAttempt",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sim_session",
    )
    finalize_enqueued_at = models.DateTimeField(null=True, blank=True)
    # A worker's claim on building the result; a killed worker's claim simply expires.
    finalize_lease_expires_at = models.DateTimeField(null=True, blank=True)
    # How many times a worker has taken the result job; a worker that is killed never says it
    # failed, so this is what stops a ticket being retried for ever (`finalize`).
    finalize_claims = models.PositiveSmallIntegerField(default=0)
    tokens_used = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at", "-id"]
        constraints = [
            # One live practice ticket per learner per activity.
            models.UniqueConstraint(
                fields=["user", "activity"],
                condition=Q(state__in=["open", "finishing"], preview=False),
                name="one_live_sim_session",
            )
        ]
        indexes = [models.Index(fields=["state", "last_activity_at"], name="sim_session_idle")]

    def __str__(self) -> str:
        return f"{self.user} · {self.activity} · {self.state}"


class SimTurn(models.Model):
    """One message in the thread. A customer reply is *the row with seq = n+1*; the
    unique `(session, seq)` is what makes a duplicate reply impossible."""

    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        INTERN = "intern", "Intern"

    class Job(models.TextChoices):
        PENDING = "pending", "Pending"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    session = models.ForeignKey(SimSession, on_delete=models.CASCADE, related_name="turns")
    seq = models.PositiveIntegerField()
    role = models.CharField(max_length=10, choices=Role.choices)
    text = models.TextField()
    # Customer: when it became visible. Intern: when the API accepted it (server times).
    at = models.DateTimeField()
    action = models.CharField(max_length=12, blank=True)  # customer: follow_up|close|…|nudge
    client_id = models.UUIDField(null=True, blank=True)  # the browser's id for a sent reply

    # --- intern turns only: the work that follows a reply -----------------
    tat_seconds = models.PositiveIntegerField(null=True, blank=True)
    scores = models.JSONField(null=True, blank=True)  # written once; None = not yet evaluated
    job_state = models.CharField(max_length=8, choices=Job.choices, default=Job.PENDING)
    job_attempts = models.PositiveSmallIntegerField(default=0)
    job_enqueued_at = models.DateTimeField(null=True, blank=True)
    job_lease_expires_at = models.DateTimeField(null=True, blank=True)
    job_error = models.CharField(max_length=200, blank=True)  # a sentence a learner can read

    class Meta:
        ordering = ["session_id", "seq"]
        constraints = [
            models.UniqueConstraint(fields=["session", "seq"], name="uniq_sim_turn_seq"),
            models.UniqueConstraint(
                fields=["session", "client_id"],
                condition=Q(client_id__isnull=False),
                name="uniq_sim_turn_client",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.session_id}#{self.seq} {self.role}"


class LLMCall(models.Model):
    """Every call to the language model: for cost, latency and audit."""

    session = models.ForeignKey(
        SimSession, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    turn = models.ForeignKey(
        SimTurn, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    task = models.CharField(max_length=12)
    model = models.CharField(max_length=60)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=14
    )  # ok | rate_limited | timeout | error | refused | bad_output
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["created_at"], name="llmcall_when")]


class LLMBudget(models.Model):
    """One row shared by every process: the rate window, the day's token total and
    the circuit breaker. Locked with `select_for_update` for each decision."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    window_start = models.DateTimeField(null=True, blank=True)
    requests_in_window = models.PositiveIntegerField(default=0)
    tokens_in_window = models.PositiveIntegerField(default=0)
    day = models.DateField(null=True, blank=True)
    tokens_today = models.BigIntegerField(default=0)
    consecutive_failures = models.PositiveSmallIntegerField(default=0)
    breaker_open_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class ScenarioImport(models.Model):
    """One run of importing past customer queries — what was asked for and what came of
    it, so the Console can show real results (and undo a bad batch)."""

    class State(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        DONE = "done", "Finished"
        FAILED = "failed", "Stopped early"

    class Trigger(models.TextChoices):
        MANUAL = "manual", "Started by an administrator"
        SCHEDULED = "scheduled", "Nightly top-up"

    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    trigger = models.CharField(max_length=10, choices=Trigger.choices, default=Trigger.MANUAL)
    requested = models.PositiveSmallIntegerField()
    topic = models.CharField(max_length=40, blank=True)  # only keep questions on this topic
    state = models.CharField(max_length=10, choices=State.choices, default=State.QUEUED)
    auto_approve = models.BooleanField(default=False)  # whether approval was on for this run
    examined = models.PositiveIntegerField(default=0)
    approved = models.PositiveIntegerField(default=0)
    drafted = models.PositiveIntegerField(default=0)
    duplicates = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    rejected = models.JSONField(default=dict)  # {reason: count}; no text, no ticket content
    error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Import #{self.pk} ({self.state})"


class PracticeSettings(models.Model):
    """One row of switches an administrator can flip in the Console."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    # Approving imported scenarios automatically (the env `SIMBOT_AUTO_APPROVE` overrides to off).
    auto_approve_enabled = models.BooleanField(default=True)
    # The last read-only audit of a Zendesk sample: nothing is imported before one has run.
    zendesk_audited_at = models.DateTimeField(null=True, blank=True)
    zendesk_audit = models.JSONField(default=dict, blank=True)  # counts by reason, ticket ids
    # Nightly top-up of the question bank (the env `SIMBOT_TOPUP_ENABLED` overrides to off).
    # Off until an administrator switches it on: it reads Zendesk and spends model calls unattended.
    topup_enabled = models.BooleanField(default=False)
    topup_resumed_at = models.DateTimeField(null=True, blank=True)  # last switched on
    topup_last_check = models.JSONField(default=dict, blank=True)  # {at, outcome, reason}
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls) -> PracticeSettings:
        row, _ = cls.objects.get_or_create(id=1)
        return row
