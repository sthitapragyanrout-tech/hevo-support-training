"""Importing past customer queries as practice scenarios.

The pieces, in the order a question travels:

1. `zendesk.ZendeskReader` finds closed tickets and keeps only genuine customer messages
   (read-only; see that module).
2. The text is scrubbed and the model decides whether it is usable and rewrites it
   (`simbot_engine.ticket`). The raw message exists only in memory during this run; what is
   stored is the rewrite and the ticket's id.
3. Strict checks decide: approve automatically, save as a draft for a trainer, or drop.
4. Near-duplicates of anything already in the bank are not saved.

Nothing runs until the data-protection sign-off is recorded (`blocked_reason`). The web
process never calls Zendesk or the model: this runs on the practice worker.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

from simbot_engine.llm import LLMError
from simbot_engine.scenario import TOPIC_POOL, Sample
from simbot_engine.ticket import Assessment, assess, first_duplicate, rewrite_ticket

from . import gate, llm, zendesk
from .errors import BadReply, Conflict, SimError
from .models import PracticeSettings, Scenario, ScenarioImport

log = logging.getLogger(__name__)

MAX_PER_IMPORT = 50
STALE_AFTER = timedelta(minutes=30)
S = ScenarioImport.State


# ------------------------------------------------------------------ the gate


def blocked_reason() -> str | None:
    """Why an import may not run right now (None = it may). Checked when one is requested
    and again when it starts. The sign-off is the one thing code cannot grant: it can only
    insist that somebody recorded it."""
    if not settings.SIMBOT_ENABLED:
        return "Practice tickets are switched off on this server."
    if not settings.SIMBOT_ZENDESK_IMPORT_ENABLED:
        return (
            "Importing from Zendesk is switched off until the data-protection sign-off "
            "is recorded (SIMBOT_ZENDESK_IMPORT_ENABLED)."
        )
    if not settings.SIMBOT_ZENDESK_SIGNOFF.strip():
        return (
            "The data-protection sign-off hasn’t been recorded yet "
            "(SIMBOT_ZENDESK_SIGNOFF: who approved it, when, and the reference)."
        )
    if not zendesk.configured():
        return "Zendesk isn’t connected (ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN)."
    if not llm.configured():
        return llm.NOT_CONFIGURED
    if PracticeSettings.load().zendesk_audited_at is None:
        return "Run the Zendesk sample audit first (manage.py audit_zendesk_sample)."
    return None


def auto_approve_effective() -> bool:
    """Is automatic approval on? The environment switch is the master: when it is off, no
    Console setting can turn it back on."""
    return bool(settings.SIMBOT_AUTO_APPROVE and PracticeSettings.load().auto_approve_enabled)


def status() -> dict[str, Any]:
    """What the Console shows about the connection."""
    row = PracticeSettings.load()
    return {
        "configured": zendesk.configured(),
        "import_enabled": bool(settings.SIMBOT_ZENDESK_IMPORT_ENABLED),
        "signoff_recorded": bool(settings.SIMBOT_ZENDESK_SIGNOFF.strip()),
        "audited_at": row.zendesk_audited_at.isoformat() if row.zendesk_audited_at else None,
        "audit": {k: v for k, v in (row.zendesk_audit or {}).items() if k != "ids"},
        "blocked_reason": blocked_reason(),
        "auto_approve": {
            "on": auto_approve_effective(),
            "setting": row.auto_approve_enabled,
            "master": bool(settings.SIMBOT_AUTO_APPROVE),
        },
    }


# ------------------------------------------------------------- the question bank


def bank_status() -> dict[str, Any]:
    """How many questions learners can get, against how many we want. `empty` means nobody
    can start practice; `low` is under the target."""
    counts = {
        row["status"]: row["n"] for row in Scenario.objects.values("status").annotate(n=Count("pk"))
    }
    approved = counts.get(Scenario.Status.APPROVED, 0)
    target = settings.SIMBOT_BANK_TARGET
    state = "empty" if approved == 0 else "low" if approved < target else "ok"
    return {
        "approved": approved,
        "drafts": counts.get(Scenario.Status.DRAFT, 0),
        "target": target,
        "state": state,
    }


# ------------------------------------------------------------ nightly top-up


def topup_effective() -> bool:
    """Is the nightly top-up on? The environment value is the master: when it is off, no
    Console setting can turn it back on."""
    return bool(settings.SIMBOT_TOPUP_ENABLED and PracticeSettings.load().topup_enabled)


def topup_paused() -> bool:
    """Has the top-up found nothing for several nights in a row (the source is used up, or
    something is wrong)? It then stops asking until a person runs an import by hand or
    switches it off and on again."""
    row = PracticeSettings.load()
    since = row.topup_resumed_at
    last_manual = (
        ScenarioImport.objects.filter(trigger=ScenarioImport.Trigger.MANUAL)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    if last_manual and (since is None or last_manual > since):
        since = last_manual
    runs = ScenarioImport.objects.filter(
        trigger=ScenarioImport.Trigger.SCHEDULED, state__in=(S.DONE, S.FAILED)
    )
    if since is not None:
        runs = runs.filter(created_at__gt=since)
    recent = list(runs.order_by("-created_at", "-id")[: settings.SIMBOT_TOPUP_PAUSE_AFTER])
    return len(recent) == settings.SIMBOT_TOPUP_PAUSE_AFTER and all(
        r.approved + r.drafted == 0 for r in recent
    )


def next_topup_at(now=None):
    now = now or timezone.now()
    due = now.replace(
        hour=settings.SIMBOT_TOPUP_HOUR,
        minute=settings.SIMBOT_TOPUP_MINUTE,
        second=0,
        microsecond=0,
    )
    return due if due > now else due + timedelta(days=1)


def topup_status() -> dict[str, Any]:
    """What the Console shows about the nightly top-up."""
    row = PracticeSettings.load()
    return {
        "on": topup_effective(),
        "setting": row.topup_enabled,
        "master": bool(settings.SIMBOT_TOPUP_ENABLED),
        "count": min(settings.SIMBOT_TOPUP_COUNT, MAX_PER_IMPORT),
        "next_run_at": next_topup_at().isoformat(),
        "last_check": row.topup_last_check or None,
        "paused": topup_paused(),
    }


def _checked(outcome: str, reason: str, now) -> str:
    row = PracticeSettings.load()
    row.topup_last_check = {"at": now.isoformat(), "outcome": outcome, "reason": reason[:200]}
    row.save(update_fields=["topup_last_check", "updated_at"])
    return outcome


def top_up(*, now=None) -> str:
    """The nightly job: queue one ordinary import when the bank is short. Returns "off",
    "queued" or "skipped" (the reason is kept for the Console). It uses the same gate and the
    same run as a manual import, so every safeguard applies unchanged."""
    now = now or timezone.now()
    if not topup_effective():
        return "off"
    reason = blocked_reason()
    if reason:
        return _checked("skipped", reason, now)
    bank = bank_status()
    if bank["approved"] >= bank["target"]:
        return _checked("skipped", f"Enough approved questions ({bank['approved']}).", now)
    if bank["drafts"] >= settings.SIMBOT_TOPUP_MAX_DRAFTS:
        return _checked(
            "skipped", f"{bank['drafts']} questions are waiting for a trainer to review.", now
        )
    if topup_paused():
        return _checked(
            "skipped",
            f"Paused: the last {settings.SIMBOT_TOPUP_PAUSE_AFTER} nights found nothing new. "
            "Run an import yourself, or switch the top-up off and on, to resume.",
            now,
        )
    try:
        run = create_run(
            None,
            min(settings.SIMBOT_TOPUP_COUNT, MAX_PER_IMPORT),
            trigger=ScenarioImport.Trigger.SCHEDULED,
        )
    except SimError as exc:  # e.g. an import is already running
        return _checked("skipped", exc.message, now)
    enqueue(run.pk)
    return _checked("queued", f"Import #{run.pk} queued.", now)


# --------------------------------------------------------------------- audit


def run_audit(count: int, *, reader: zendesk.ZendeskReader | None = None) -> zendesk.AuditSummary:
    """Look at a sample of past tickets and say how many are genuine customer messages, and
    why the rest are not. Reads Zendesk only: nothing goes to the model, no text is kept —
    just counts and ticket ids, so a person can check a few in Zendesk itself."""
    reader = reader or zendesk.ZendeskReader(zendesk.ZendeskConfig.from_settings())
    summary = zendesk.AuditSummary.of(reader.sample(count))
    row = PracticeSettings.load()
    row.zendesk_audited_at = timezone.now()
    row.zendesk_audit = {
        "examined": summary.examined,
        "accepted": summary.accepted,
        "reasons": dict(summary.reasons),
        "ids": {"accepted": summary.accepted_ids, "rejected": summary.rejected_ids},
    }
    row.save(update_fields=["zendesk_audited_at", "zendesk_audit", "updated_at"])
    return summary


# ------------------------------------------------------------------- request


def create_run(
    user,
    count: Any,
    topic: str | None = None,
    *,
    trigger: str = ScenarioImport.Trigger.MANUAL,
) -> ScenarioImport:
    """Check the gate and the request, and record a queued run. Raises a `SimError` with a
    sentence. (Does not queue it: see `start_import`.) A nightly top-up has no `user`."""
    reason = blocked_reason()
    if reason:
        raise Conflict(reason)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_PER_IMPORT:
        raise BadReply(f"Choose between 1 and {MAX_PER_IMPORT} questions to import.")
    if topic is not None and topic not in TOPIC_POOL:
        raise BadReply("Choose one of the listed topics.")
    now = timezone.now()
    with transaction.atomic():
        busy = ScenarioImport.objects.select_for_update().filter(
            state__in=(S.QUEUED, S.RUNNING), created_at__gte=now - STALE_AFTER
        )
        if busy.exists():
            raise Conflict("An import is already running. Wait for it to finish.")
        return ScenarioImport.objects.create(
            started_by=user,
            trigger=trigger,
            requested=count,
            topic=topic or "",
            auto_approve=auto_approve_effective(),
        )


def start_import(user, count: Any, topic: str | None = None) -> ScenarioImport:
    """Queue an import for the practice worker."""
    run = create_run(user, count, topic)
    transaction.on_commit(lambda: enqueue(run.pk))
    return run


def enqueue(run_id: int) -> bool:
    from .tasks import import_scenarios

    try:
        import_scenarios.delay(run_id)
        return True
    except Exception:  # the broker is down: the sweeper picks it up
        log.warning("Could not queue import %s; the sweeper will retry", run_id, exc_info=True)
        return False


# ----------------------------------------------------------------------- run


def _fail(run: ScenarioImport, message: str) -> str:
    run.state, run.error, run.finished_at = S.FAILED, message[:200], timezone.now()
    run.save()
    return "failed"


def run_import(
    run_id: int,
    *,
    reader: zendesk.ZendeskReader | None = None,
    inner: Any = None,
) -> str:
    """Do one queued import. Safe to deliver twice: only the first claims it, and a ticket
    already imported can never be imported again (unique ticket id)."""
    claimed = ScenarioImport.objects.filter(pk=run_id, state=S.QUEUED).update(state=S.RUNNING)
    if not claimed:
        return "skipped"
    run = ScenarioImport.objects.get(pk=run_id)
    reason = blocked_reason()
    if reason:
        return _fail(run, reason)

    try:
        reader = reader or zendesk.ZendeskReader(zendesk.ZendeskConfig.from_settings())
        known_ids = {
            int(t)
            for t in Scenario.objects.filter(source_ticket_id__isnull=False).values_list(
                "source_ticket_id", flat=True
            )
            if t and t.isdigit()
        }
        verdicts = reader.sample(run.requested, exclude_ids=known_ids)
    except zendesk.ZendeskError as exc:
        return _fail(run, str(exc))

    client = llm.GatedLLM(inner)
    config = llm.engine_config()
    bank = [
        f"{summary} {opening}"
        for summary, opening in Scenario.objects.values_list("issue_summary", "opening_message")
    ]
    reasons: Counter[str] = Counter()
    stopped = ""
    for verdict in verdicts:
        run.examined += 1
        if not verdict.accepted:
            reasons[f"zendesk:{verdict.reason}"] += 1
        else:
            try:
                outcome = _import_one(run, verdict, client, config, bank, reasons)
            except gate.GateWait:
                stopped = "The model is busy right now. Try again in a few minutes."
            except gate.Paused as exc:
                stopped = str(exc)
            except LLMError as exc:
                run.failed += 1
                log.warning("Rewrite failed for an imported ticket: %s", exc)
            else:
                if outcome == "approved":
                    run.approved += 1
                elif outcome == "drafted":
                    run.drafted += 1
                elif outcome == "duplicate":
                    run.duplicates += 1
        run.rejected = dict(reasons)
        run.save()
        if stopped:
            break

    run.state = S.FAILED if stopped else S.DONE
    run.error = stopped[:200]
    run.finished_at = timezone.now()
    run.save()
    return "failed" if stopped else "done"


def _import_one(
    run: ScenarioImport,
    verdict: zendesk.Verdict,
    client: Any,
    config: Any,
    bank: list[str],
    reasons: Counter[str],
) -> str:
    """One genuine customer message → at most one scenario. Returns "approved", "drafted",
    "duplicate" or "dropped". The raw message goes no further than the model call."""
    rewrite = rewrite_ticket(client, config, Sample(verdict.subject, verdict.message))
    if rewrite.usable and rewrite.scenario and run.topic and rewrite.scenario.topic != run.topic:
        reasons["rewrite:other_topic"] += 1
        return "dropped"
    assessment = assess(rewrite, config)
    if assessment.decision == "drop":
        for problem in assessment.problems:
            reasons[f"rewrite:{problem}"] += 1
        return "dropped"
    scenario = rewrite.scenario
    assert scenario is not None
    text = f"{scenario.issue_summary} {scenario.opening_message}"
    if first_duplicate(text, bank) is not None:
        return "duplicate"

    approve = assessment.decision == "approve" and run.auto_approve
    now = timezone.now()
    try:
        with transaction.atomic():
            Scenario.objects.create(
                topic=scenario.topic,
                persona_type=scenario.persona_type,
                issue_summary=scenario.issue_summary,
                opening_message=scenario.opening_message,
                personality_notes=scenario.personality_notes,
                doc_hints=list(scenario.doc_hints),
                status=Scenario.Status.APPROVED if approve else Scenario.Status.DRAFT,
                source=Scenario.Source.ZENDESK,
                source_ticket_id=str(verdict.ticket_id),
                auto_approved=approve,
                approved_at=now if approve else None,
                review_note="" if approve else _note(assessment),
                import_run=run,
                created_by=run.started_by,
            )
    except IntegrityError:
        return "duplicate"  # this ticket was imported meanwhile
    bank.append(text)
    return "approved" if approve else "drafted"


def _note(assessment: Assessment) -> str:
    if assessment.decision == "approve":
        return "Automatic approval is off."
    words = {"unsure": "the model was not sure", "several_questions": "it asks several things"}
    return "Needs a look: " + ", ".join(words.get(p, p) for p in assessment.problems) + "."


# ---------------------------------------------------------------------- undo


@transaction.atomic
def revert_import(run: ScenarioImport) -> int:
    """Send everything this run approved automatically back to draft (a bad batch). What a
    person approved themselves is left alone. Returns how many went back."""
    back = Scenario.objects.filter(
        import_run=run, status=Scenario.Status.APPROVED, auto_approved=True
    ).update(
        status=Scenario.Status.DRAFT,
        auto_approved=False,
        approved_by=None,
        approved_at=None,
        review_note=f"Sent back with import #{run.pk}.",
        updated_at=timezone.now(),
    )
    return back


# ------------------------------------------------------------------- sweeper


def recover(*, now=None) -> int:
    """Imports a crash left behind: a stale running one is marked stopped (re-running is
    safe — tickets already imported are skipped); a queued one is queued again."""
    now = now or timezone.now()
    stopped = ScenarioImport.objects.filter(
        state=S.RUNNING, created_at__lt=now - STALE_AFTER
    ).update(state=S.FAILED, error="Stopped unexpectedly. You can start it again.", finished_at=now)
    for run_id in ScenarioImport.objects.filter(
        state=S.QUEUED, created_at__lt=now - timedelta(minutes=2)
    ).values_list("pk", flat=True):
        enqueue(run_id)
    return stopped
