"""Practice tickets: start, reply, evaluate, answer, finish — each step safe to repeat.

The shape of the guarantees (tested with fault injection and a killed worker):

  * **A reply is accepted once.** `UNIQUE(session, client_id)` and
    `UNIQUE(session, seq)`; a repeated POST returns the turn that already exists.
  * **A customer message exists once.** The reply to intern turn *n* is the row
    with `seq = n + 1`; a second writer hits the unique key and its work is
    thrown away. The same goes for a nudge or a closing message.
  * **An evaluation is written once.** `UPDATE … WHERE scores IS NULL`.
  * **A turn's work is claimed, not assumed.** A worker takes a *lease* with one
    conditional UPDATE; a killed worker's lease simply expires. Steps are
    independent, so a retry after "evaluated, not yet answered" only answers.
  * **A result exists once.** Finalising is one transaction: the attempt, the
    progress row and the session state commit together (`OneToOne(attempt)`,
    state compare-and-set); the numbers are a pure function of the stored scores.
  * A model call that succeeded but whose result was lost is simply made again
    (bounded, and logged in `LLMCall`) — it can cost money, never duplicate output.
"""

from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.db.models.functions import Greatest
from django.utils import timezone

from apps.activities import bot_sim as cfg
from apps.catalog.models import Activity
from apps.progress import services as progress
from apps.progress.models import ActivityAttempt
from simbot_engine import outcome
from simbot_engine import session as engine
from simbot_engine.customer import customer_reply
from simbot_engine.evaluator import TurnScores, score_turn
from simbot_engine.llm import LLMClient, LLMError
from simbot_engine.narrative import write_narrative
from simbot_engine.scenario import Scenario as EngineScenario

from . import gate, llm
from .errors import BadReply, Conflict, NoScenarios, NotFound, TooMany, Unavailable
from .models import Scenario, SimSession, SimTurn

log = logging.getLogger(__name__)

CLOSING_MESSAGE = (
    "We've been waiting a while — closing this ticket now. Thanks for your time on this one."
)
STATES_LIVE = (SimSession.State.OPEN, SimSession.State.FINISHING)
SKIPPED = "skipped"
SKIP_REASONS = {
    "duplicate": "a question I've already had",
    "unclear": "unclear",
    "not_relevant": "not relevant to the job",
}
# This many different learners skipping a question for the same reason sends it back to a trainer.
FLAG_AFTER = 3
FLAG_NOTES = {
    "duplicate": "Reported as a duplicate by {n} learners.",
    "unclear": "Skipped as unclear by {n} learners.",
    "not_relevant": "Skipped as not relevant by {n} learners.",
}
MAX_PREVIEW_AGE = timedelta(hours=1)


# ------------------------------------------------------------------ helpers


def _now():
    return timezone.now()


def _engine_turns(turns) -> list[engine.Turn]:
    out = []
    for t in turns:
        item = engine.Turn(seq=t.seq, role=t.role, text=t.text, at=t.at, action=t.action or None)
        if t.scores:
            item.scores = TurnScores.from_dict(t.scores)
        out.append(item)
    return out


def _engine_config(session: SimSession):
    snap = session.config_snapshot or {}
    return llm.engine_config(max_exchanges=snap.get("max_exchanges"))


def _scenario(session: SimSession) -> EngineScenario:
    return EngineScenario.from_snapshot(session.scenario_snapshot)


def _owned(user, session_id: int, *, lock: bool = False) -> SimSession:
    qs = SimSession.objects.select_related("activity")
    if lock:
        qs = qs.select_for_update(of=("self",))
    session = qs.filter(pk=session_id, user=user).first()
    if session is None:
        raise NotFound("That practice ticket doesn’t exist.")
    return session


def count_matching(config: Any) -> int:
    return cfg.matching_scenarios(config).count()


# ------------------------------------------------------------------- start


def _pick_scenario(user, activity: Activity, *, preview: bool) -> tuple[Scenario, bool]:
    """A fresh approved scenario for this learner: one they haven't had on this activity
    (preferring a topic they haven't just had), never one they skipped. Only when the bank
    holds fewer questions than they need does it fall back to the one they saw longest ago
    (marked `repeated`). Previews may use any status."""
    qs = cfg.matching_scenarios(activity.config)
    if preview:
        qs = Scenario.objects.exclude(status=Scenario.Status.RETIRED)
        if cfg.persona(activity.config) != "random":
            qs = qs.filter(persona_type=cfg.persona(activity.config))
        if cfg.topics(activity.config):
            qs = qs.filter(topic__in=cfg.topics(activity.config))
    options = list(qs.order_by("id"))
    if not options:
        raise NoScenarios(
            "Practice isn’t available yet — your trainer needs to approve practice scenarios."
        )
    history = list(
        SimSession.objects.filter(user=user, activity=activity, preview=False)
        .order_by("started_at", "id")
        .values_list("scenario_id", "started_at", "abandon_reason", "scenario__topic")
    )
    skipped = {sid for sid, _, reason, _ in history if reason == SKIPPED}
    options = [o for o in options if o.pk not in skipped]
    if not options:
        raise NoScenarios(
            "There are no more new questions for you right now — ask your trainer to add more."
        )
    seen = {sid: at for sid, at, _, _ in history}
    recent_topics = {topic for _, _, _, topic in history[-2:]}
    unseen = [s for s in options if s.pk not in seen]
    rng = random.Random(f"{user.pk}-{activity.pk}-{len(seen)}")
    if unseen:
        varied = [s for s in unseen if s.topic not in recent_topics]
        return rng.choice(varied or unseen), False
    return min(options, key=lambda s: seen[s.pk]), True


def _live_session(user, activity: Activity) -> SimSession | None:
    return SimSession.objects.filter(
        user=user, activity=activity, preview=False, state__in=STATES_LIVE
    ).first()


def start(user, activity_id: int, *, now=None) -> SimSession:
    """Begin (or resume) the learner's practice ticket for this activity."""
    now = now or _now()
    activity = progress._activity(activity_id)  # published, exists, completable
    if activity.activity_type != "bot_sim":
        raise Conflict("This activity isn’t a practice ticket.")
    progress._assert_lesson_open(user, progress._lesson_of(activity))

    existing = _live_session(user, activity)
    if existing is not None:
        return existing
    gate.assert_available(now)

    try:
        with transaction.atomic():
            existing = _live_session(user, activity)
            if existing is not None:
                return existing
            progress.lock_attempts(user, activity)  # passed / out of tries → 409
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            started_today = (
                SimSession.objects.filter(user=user, preview=False, started_at__gte=today)
                .exclude(abandon_reason=SKIPPED)  # a skip costs nothing
                .count()
            )
            if started_today >= settings.SIMBOT_DAILY_SESSIONS_PER_USER:
                raise TooMany(
                    "You’ve reached today’s limit for practice tickets. Try again tomorrow."
                )
            scenario, repeated = _pick_scenario(user, activity, preview=False)
            return _create_session(user, activity, scenario, repeated, preview=False, now=now)
    except IntegrityError:
        # Two starts raced; the other one won. Hand back its session.
        existing = _live_session(user, activity)
        if existing is None:
            raise
        return existing


def start_preview(user, activity_id: int, *, now=None) -> SimSession:
    """An author trying a practice ticket in Studio: any non-retired scenario,
    nothing recorded, no attempt, no limits on their learner record."""
    now = now or _now()
    activity = (
        Activity.objects.select_related("content_node__course_version__course")
        .filter(pk=activity_id, activity_type="bot_sim")
        .first()
    )
    if activity is None:
        raise NotFound("That activity doesn’t exist.")
    if not llm.configured() or not settings.SIMBOT_ENABLED:
        raise Unavailable(llm.NOT_CONFIGURED)
    gate.assert_available(now)
    with transaction.atomic():
        scenario, _ = _pick_scenario(user, activity, preview=True)
        return _create_session(user, activity, scenario, False, preview=True, now=now)


def _create_session(user, activity, scenario: Scenario, repeated: bool, *, preview: bool, now):
    snapshot = scenario.snapshot()
    session = SimSession.objects.create(
        user=user,
        activity=activity,
        scenario=scenario,
        scenario_snapshot=snapshot,
        repeated=repeated,
        preview=preview,
        config_snapshot={
            "max_exchanges": cfg.max_exchanges(activity.config),
            "pass_threshold": cfg.pass_threshold(activity.config),
            "customer_model": settings.SIMBOT_MODEL,
            "eval_model": settings.SIMBOT_EVAL_MODEL,
            "engine": "simbot_engine/1",
        },
        started_at=now,
        last_activity_at=now,
    )
    SimTurn.objects.create(
        session=session,
        seq=1,
        role=SimTurn.Role.CUSTOMER,
        text=scenario.opening_message,
        at=now,
        action="open",
        job_state=SimTurn.Job.DONE,
    )
    return session


# ------------------------------------------------------------------- reply


def submit_reply(user, session_id: int, text: str, client_id, *, now=None) -> tuple[SimTurn, bool]:
    """Accept the learner's reply. Returns (turn, created); a repeat of the same
    `client_id` returns the original and changes nothing."""
    now = now or _now()
    clean = (text or "").strip()
    if not clean:
        raise BadReply("Write a reply before sending.")
    if len(clean) > settings.SIMBOT_MAX_REPLY_CHARS:
        raise BadReply(
            f"That reply is too long (the limit is {settings.SIMBOT_MAX_REPLY_CHARS} characters)."
        )

    with transaction.atomic():
        session = _owned(user, session_id, lock=True)
        repeat = session.turns.filter(client_id=client_id).first()
        if repeat is not None:
            return repeat, False
        if session.state != SimSession.State.OPEN:
            raise Conflict("This practice ticket has ended.")
        _apply_idle(session, now)
        if session.state != SimSession.State.OPEN:
            raise Conflict("This practice ticket has ended.")
        last = session.turns.order_by("-seq").first()
        assert last is not None
        if last.role != SimTurn.Role.CUSTOMER:
            raise Conflict("The customer hasn’t replied to your last message yet.")
        turns = _engine_turns(session.turns.order_by("seq"))
        turn = SimTurn.objects.create(
            session=session,
            seq=last.seq + 1,
            role=SimTurn.Role.INTERN,
            text=clean,
            at=now,
            client_id=client_id,
            tat_seconds=engine.tat_seconds(turns, now),
            job_enqueued_at=now,
        )
        SimSession.objects.filter(pk=session.pk).update(last_activity_at=now)
        turn_id = turn.pk
        transaction.on_commit(lambda: enqueue_turn(turn_id))
    return turn, True


def retry_turn(user, session_id: int) -> SimTurn:
    """The learner pressed "Try again" after the customer's reply failed."""
    with transaction.atomic():
        session = _owned(user, session_id, lock=True)
        turn = (
            session.turns.filter(role=SimTurn.Role.INTERN, job_state=SimTurn.Job.FAILED)
            .order_by("-seq")
            .first()
        )
        if turn is None:
            raise Conflict("There’s nothing to retry.")
        SimTurn.objects.filter(pk=turn.pk).update(
            job_state=SimTurn.Job.PENDING,
            job_attempts=0,
            job_error="",
            job_lease_expires_at=None,
            job_enqueued_at=_now(),
        )
        turn_id = turn.pk
        transaction.on_commit(lambda: enqueue_turn(turn_id))
    turn.refresh_from_db()
    return turn


def enqueue_turn(turn_id: int, *, countdown: float = 0) -> bool:
    from .tasks import process_turn

    SimTurn.objects.filter(pk=turn_id).update(job_enqueued_at=_now())
    try:
        process_turn.apply_async((turn_id,), countdown=countdown)
    except Exception:
        if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            raise
        log.warning("Could not queue turn %s; the sweeper will retry", turn_id, exc_info=True)
        return False
    return True


def enqueue_finalize(session_id: int, *, countdown: float = 0) -> bool:
    from .tasks import finalize_session

    SimSession.objects.filter(pk=session_id).update(finalize_enqueued_at=_now())
    try:
        finalize_session.apply_async((session_id,), countdown=countdown)
    except Exception:
        if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            raise
        log.warning(
            "Could not queue finalize %s; the sweeper will retry", session_id, exc_info=True
        )
        return False
    return True


# -------------------------------------------------------------- turn worker


def _client(session: SimSession, turn: SimTurn | None, inner: LLMClient | None) -> llm.GatedLLM:
    return llm.GatedLLM(inner, session=session, turn=turn)


def _fail_message(exc: Exception) -> str:
    if isinstance(exc, gate.Paused):
        return exc.message
    return "The customer couldn’t reply just now. Try again in a moment."


def run_turn(turn_id: int, *, inner: LLMClient | None = None, now=None) -> str:
    """Do the work that follows one intern reply: evaluate it, then answer it.
    Returns "skipped" | "busy" | "done" | "retry" | "failed" | "waiting"."""
    now = now or _now()
    turn = SimTurn.objects.select_related("session").filter(pk=turn_id).first()
    if turn is None or turn.role != SimTurn.Role.INTERN:
        return "skipped"
    session = turn.session
    if session.state == SimSession.State.ABANDONED or turn.job_state != SimTurn.Job.PENDING:
        return "skipped"
    if turn.job_attempts >= settings.SIMBOT_MAX_JOB_ATTEMPTS:
        # Taken this many times and never finished or failed on its own: its worker keeps
        # dying. Say so to the learner instead of running it again.
        log.warning(
            "Practice turn %s was taken %s times without finishing", turn.pk, turn.job_attempts
        )
        _give_up(session, turn, RuntimeError("worker stopped"))
        return "failed"

    claimed = (
        SimTurn.objects.filter(pk=turn.pk, job_state=SimTurn.Job.PENDING)
        .filter(Q(job_lease_expires_at__isnull=True) | Q(job_lease_expires_at__lt=now))
        .update(
            job_lease_expires_at=now + timedelta(seconds=settings.SIMBOT_LEASE_SECONDS),
            job_attempts=F("job_attempts") + 1,
        )
    )
    if not claimed:
        return "busy"
    turn.refresh_from_db()

    try:
        client = _client(session, turn, inner)
        _evaluate(session, turn, client)
        _answer(session, turn, client)
    except gate.GateWait as wait:
        log.info("Practice turn %s deferred %.1fs by the rate gate", turn.pk, wait.seconds)
        _release(turn, refund=True)
        enqueue_turn(turn.pk, countdown=wait.seconds)
        return "waiting"
    except gate.Paused as exc:
        _give_up(session, turn, exc)
        return "failed"
    except LLMError as exc:
        if exc.retryable and turn.job_attempts < settings.SIMBOT_MAX_JOB_ATTEMPTS:
            _release(turn)
            enqueue_turn(turn.pk, countdown=_backoff(turn.job_attempts))
            return "retry"
        _give_up(session, turn, exc)
        return "failed"

    SimTurn.objects.filter(pk=turn.pk).update(
        job_state=SimTurn.Job.DONE, job_lease_expires_at=None, job_error=""
    )
    _maybe_finalize(session.pk)
    return "done"


def _backoff(attempt: int) -> float:
    return settings.SIMBOT_RETRY_BACKOFF_SECONDS * (2 ** max(attempt - 1, 0))


def _release(turn: SimTurn, *, refund: bool = False) -> None:
    """Let go of a claim. `refund` gives the attempt back (waiting for the rate gate is not a
    try), so only real tries, and workers that died holding it, count towards the cap."""
    changes: dict = {"job_lease_expires_at": None}
    if refund:
        changes["job_attempts"] = Greatest(F("job_attempts") - 1, 0)
    SimTurn.objects.filter(pk=turn.pk).update(**changes)


def _give_up(session: SimSession, turn: SimTurn, exc: Exception) -> None:
    log.warning("Practice turn %s failed after %s attempts: %s", turn.pk, turn.job_attempts, exc)
    SimTurn.objects.filter(pk=turn.pk).update(
        job_state=SimTurn.Job.FAILED,
        job_lease_expires_at=None,
        job_error=_fail_message(exc)[:200],
    )
    if isinstance(exc, gate.Paused) and "length limit" in exc.message:
        abandon(session.pk, "token_budget")


def _evaluate(session: SimSession, turn: SimTurn, client: LLMClient) -> None:
    """Step 1 — score the reply. Skipped if it already has scores; the write is
    conditional, so the first writer wins and a late one changes nothing."""
    turn.refresh_from_db(fields=["scores"])
    if turn.scores is not None:
        return
    history = _engine_turns(session.turns.filter(seq__lt=turn.seq).order_by("seq"))
    scores = score_turn(
        client,
        _engine_config(session),
        _scenario(session),
        history,
        turn.text,
        turn.tat_seconds or 0,
    )
    SimTurn.objects.filter(pk=turn.pk, scores__isnull=True).update(scores=scores.to_dict())


def _answer(session: SimSession, turn: SimTurn, client: LLMClient) -> None:
    """Step 2 — the customer's reply is the row with seq = n + 1. Skipped if it
    exists (a retry, a duplicate delivery, a closing message) or the session has
    moved on; inserted at most once because of the unique key."""
    session.refresh_from_db(fields=["state"])
    if session.state != SimSession.State.OPEN:
        return
    if session.turns.filter(seq=turn.seq + 1).exists():
        return
    config = _engine_config(session)
    turns = _engine_turns(session.turns.filter(seq__lte=turn.seq).order_by("seq"))
    step = customer_reply(client, config, _scenario(session), turns)
    delivered = _now()
    try:
        with transaction.atomic():
            SimTurn.objects.create(
                session=session,
                seq=turn.seq + 1,
                role=SimTurn.Role.CUSTOMER,
                text=step.message,
                at=delivered,
                action=step.action,
                job_state=SimTurn.Job.DONE,
            )
            SimSession.objects.filter(pk=session.pk).update(last_activity_at=delivered)
    except IntegrityError:
        return  # someone else answered first; our (paid-for) answer is discarded
    if engine.should_close(step.action, turns, config):
        _begin_finish(session.pk)


# ----------------------------------------------------------------- finishing


def _begin_finish(session_id: int) -> bool:
    """open → finishing, once; then ask for the result."""
    moved = SimSession.objects.filter(pk=session_id, state=SimSession.State.OPEN).update(
        state=SimSession.State.FINISHING
    )
    if moved:
        transaction.on_commit(lambda: enqueue_finalize(session_id))
    return bool(moved)


def finish(user, session_id: int, *, now=None) -> SimSession:
    """The learner ends the ticket early. With no reply sent it is just abandoned."""
    now = now or _now()
    with transaction.atomic():
        session = _owned(user, session_id, lock=True)
        if session.state != SimSession.State.OPEN:
            return session
        if not session.turns.filter(role=SimTurn.Role.INTERN).exists():
            _abandon_locked(session, "no_replies", now)
        else:
            _begin_finish(session.pk)
    session.refresh_from_db()
    return session


def skips_used(user, activity) -> int:
    return SimSession.objects.filter(
        user=user, activity=activity, preview=False, abandon_reason=SKIPPED
    ).count()


def skip(user, session_id: int, reason: str, *, now=None) -> SimSession:
    """The learner passes on a question (a duplicate, an unclear one) before replying to it.
    It is not a ticket: no attempt, no score, no quota; they never get it again, and only a
    few skips are allowed. Repeating the call for the same session changes nothing."""
    now = now or _now()
    if reason not in SKIP_REASONS:
        raise BadReply("Say why you’re skipping this question.")
    with transaction.atomic():
        session = _owned(user, session_id, lock=True)
        if session.preview:
            raise Conflict("A preview can’t be skipped — just close it.")
        if session.state == SimSession.State.ABANDONED and session.abandon_reason == SKIPPED:
            return session
        if session.state != SimSession.State.OPEN:
            raise Conflict("This ticket has already ended.")
        if session.turns.filter(role=SimTurn.Role.INTERN).exists():
            raise Conflict("You can only skip a question before you reply to it.")
        allowed = cfg.skips_allowed()
        if skips_used(user, session.activity) >= allowed:
            raise Conflict(
                f"You’ve used all {allowed} skips. Please answer this one — "
                "or tell your trainer it needs changing."
            )
        _abandon_locked(session, SKIPPED, now)
        SimSession.objects.filter(pk=session.pk).update(skip_reason=reason)
    _flag_if_widely_skipped(session.scenario_id, reason)
    session.refresh_from_db()
    return session


def _flag_if_widely_skipped(scenario_id: int, reason: str) -> None:
    """Several different learners skipping a question the same way means it isn't working:
    send it back to a trainer, with the reason, rather than keep serving it."""
    with transaction.atomic():
        scenario = Scenario.objects.select_for_update().filter(pk=scenario_id).first()
        if scenario is None or scenario.status != Scenario.Status.APPROVED:
            return
        n = (
            SimSession.objects.filter(
                scenario_id=scenario_id, abandon_reason=SKIPPED, skip_reason=reason, preview=False
            )
            .values("user_id")
            .distinct()
            .count()
        )
        if n >= FLAG_AFTER:
            scenario.status = Scenario.Status.DRAFT
            scenario.approved_by = None
            scenario.approved_at = None
            scenario.auto_approved = False
            scenario.review_note = FLAG_NOTES[reason].format(n=n)
            scenario.save(
                update_fields=[
                    "status",
                    "approved_by",
                    "approved_at",
                    "auto_approved",
                    "review_note",
                    "updated_at",
                ]
            )


def abandon(session_id: int, reason: str, *, now=None) -> None:
    with transaction.atomic():
        session = SimSession.objects.select_for_update(of=("self",)).filter(pk=session_id).first()
        if session is not None and session.state in STATES_LIVE:
            _abandon_locked(session, reason, now or _now())


def _abandon_locked(session: SimSession, reason: str, now) -> None:
    SimSession.objects.filter(pk=session.pk, state__in=STATES_LIVE).update(
        state=SimSession.State.ABANDONED, abandon_reason=reason[:80], finished_at=now
    )


def _maybe_finalize(session_id: int) -> None:
    session = SimSession.objects.filter(pk=session_id).first()
    if session is not None and session.state == SimSession.State.FINISHING:
        enqueue_finalize(session_id)


def _apply_idle(session: SimSession, now) -> None:
    """Nudge once after enough silence, or close once the session has run too long.
    Called with the session row locked; safe to call repeatedly."""
    if session.state != SimSession.State.OPEN:
        return
    turns = _engine_turns(session.turns.order_by("seq"))
    config = _engine_config(session)
    decision = engine.idle_decision(turns, session.started_at, now, config)
    last = turns[-1]
    if decision == "nudge":
        _add_customer_turn(session, last.seq + 1, engine.NUDGE_MESSAGE, engine.NUDGE, now)
    elif decision == "close":
        if not any(t.role == engine.INTERN for t in turns):
            _abandon_locked(session, "timed_out", now)
            session.state = SimSession.State.ABANDONED
            return
        _add_customer_turn(session, last.seq + 1, CLOSING_MESSAGE, "close", now)
        _begin_finish(session.pk)
        session.state = SimSession.State.FINISHING


def _add_customer_turn(session: SimSession, seq: int, text: str, action: str, now) -> None:
    try:
        with transaction.atomic():
            SimTurn.objects.create(
                session=session,
                seq=seq,
                role=SimTurn.Role.CUSTOMER,
                text=text,
                at=now,
                action=action,
                job_state=SimTurn.Job.DONE,
            )
    except IntegrityError:
        pass  # another process added the next message first


def tick(user, session_id: int, *, now=None) -> SimSession:
    """Apply the idle rules for a session being looked at."""
    now = now or _now()
    with transaction.atomic():
        session = _owned(user, session_id, lock=True)
        _apply_idle(session, now)
    session.refresh_from_db()
    return session


# ---------------------------------------------------------------- finalising


def finalize(session_id: int, *, inner: LLMClient | None = None, now=None) -> str:
    """Turn a finished conversation into its result, exactly once. Returns
    "skipped" | "busy" | "waiting" | "retry" | "abandoned" | "finished"."""
    now = now or _now()
    session = SimSession.objects.select_related("activity", "user").filter(pk=session_id).first()
    if session is None or session.state != SimSession.State.FINISHING:
        return "skipped"
    if session.finalize_claims >= settings.SIMBOT_MAX_FINALIZE_CLAIMS:
        # Taken again and again without ever finishing (its worker keeps dying, or the model
        # never answers): close it, uncounted, so the learner can start another.
        log.warning("Practice ticket %s never finished; closing it", session_id)
        abandon(session_id, "feedback_failed", now=now)
        return "abandoned"
    claimed = (
        SimSession.objects.filter(pk=session_id, state=SimSession.State.FINISHING)
        .filter(Q(finalize_lease_expires_at__isnull=True) | Q(finalize_lease_expires_at__lt=now))
        .update(
            finalize_lease_expires_at=now + timedelta(seconds=settings.SIMBOT_LEASE_SECONDS),
            finalize_claims=F("finalize_claims") + 1,
        )
    )
    if not claimed:
        return "busy"
    outcome_ = _finalize_claimed(session, inner, now)
    if outcome_ in ("waiting", "retry"):
        SimSession.objects.filter(pk=session_id).update(finalize_lease_expires_at=None)
    return outcome_


def _finalize_claimed(session: SimSession, inner: LLMClient | None, now) -> str:
    turns = list(session.turns.order_by("seq"))
    interns = [t for t in turns if t.role == SimTurn.Role.INTERN]
    if any(t.scores is None for t in interns):
        # Replies still being scored: make sure each has work queued, then wait.
        for t in interns:
            if t.scores is None and t.job_state == SimTurn.Job.PENDING:
                enqueue_turn(t.pk)
        return "waiting"

    config = _engine_config(session)
    if len(interns) < config.min_scored_exchanges:
        abandon(session.pk, "too_short", now=now)
        return "abandoned"

    scenario = _scenario(session)
    engine_turns = _engine_turns(turns)
    narrative = session.narrative
    if narrative is None:
        try:
            narrative = write_narrative(
                _client(session, None, inner), config, scenario, engine_turns
            )
        except gate.GateWait as wait:
            enqueue_finalize(session.pk, countdown=wait.seconds)
            return "retry"
        except LLMError:
            tries = session.narrative_attempts + 1
            SimSession.objects.filter(pk=session.pk).update(narrative_attempts=tries)
            if tries < settings.SIMBOT_MAX_JOB_ATTEMPTS:
                enqueue_finalize(session.pk, countdown=_backoff(tries))
                return "retry"
            narrative = {}  # the written feedback is optional; the scores are not affected
        SimSession.objects.filter(pk=session.pk, narrative__isnull=True).update(narrative=narrative)
        session.refresh_from_db(fields=["narrative"])
        narrative = session.narrative or {}

    result = outcome.build(
        engine_turns,
        config=config,
        scenario=scenario,
        pass_threshold=session.config_snapshot.get("pass_threshold", cfg.DEFAULT_THRESHOLD),
        narrative=narrative or None,
    )
    return _commit_result(session, result, now)


def _commit_result(session: SimSession, result: dict, now) -> str:
    try:
        with transaction.atomic():
            locked = SimSession.objects.select_for_update(of=("self",)).get(pk=session.pk)
            if locked.state != SimSession.State.FINISHING:
                return "skipped"
            if locked.preview:
                locked.result = {**result, "preview": True}
                locked.state = SimSession.State.FINISHED
                locked.finished_at = now
                locked.save(update_fields=["result", "state", "finished_at"])
                return "finished"
            activity = locked.activity
            row, taken, limit = progress.lock_attempts(locked.user, activity)
            earlier = list(
                ActivityAttempt.objects.filter(user=locked.user, activity=activity)
                .order_by("number")
                .values_list("score", flat=True)
            )
            completes = cfg.completes(activity.config, [*earlier, result["score"]["scaled"]])
            left = progress.record_attempt(
                locked.user,
                activity,
                row,
                taken=taken,
                limit=limit,
                answers=[],
                details=[],
                score=result["score"]["scaled"],
                passed=result["passed"],
                now=now,
                completes=completes,
            )
            attempt = ActivityAttempt.objects.get(
                user=locked.user, activity=activity, number=taken + 1
            )
            locked.attempt = attempt
            locked.result = {
                **result,
                "attempts_left": left,
                "state": row.state,
                "attempt": taken + 1,
                "quota": {"done": taken + 1, "required": cfg.required_tickets(activity.config)},
            }
            locked.state = SimSession.State.FINISHED
            locked.finished_at = now
            locked.save(update_fields=["attempt", "result", "state", "finished_at"])
            return "finished"
    except progress.AttemptNotAllowed:
        # The tries were used up or the activity passed while this was running
        # (a reset, say). Nothing is recorded; a trainer can see why.
        abandon(session.pk, "attempts_unavailable", now=now)
        return "abandoned"


# ------------------------------------------------------------------ sweeper


def recover(*, now=None) -> dict[str, int]:
    """Put right whatever a crash, a lost message or a provider outage left:
    stuck turns, sessions waiting to finalise, silent sessions, stale previews.
    Safe to run any time, from any number of places."""
    now = now or _now()
    stale = now - timedelta(seconds=max(settings.SIMBOT_LEASE_SECONDS, 30))
    counts = {
        "turns": 0,
        "finalize": 0,
        "nudged": 0,
        "closed": 0,
        "previews": 0,
        "retried": 0,
        "imports": 0,
    }

    # Work nobody is doing. A claim that ran out means its worker died: do it again at
    # once (steps are idempotent). An unclaimed turn is only re-queued once its message
    # has had time to arrive, so a healthy queue isn't doubled up.
    live_turns = SimTurn.objects.filter(
        role=SimTurn.Role.INTERN,
        job_state=SimTurn.Job.PENDING,
        session__state__in=STATES_LIVE,
    )
    abandoned_claims = live_turns.filter(job_lease_expires_at__lt=now)
    unclaimed = live_turns.filter(job_lease_expires_at__isnull=True).filter(
        Q(job_enqueued_at__isnull=True) | Q(job_enqueued_at__lt=stale)
    )
    for turn in [*abandoned_claims, *unclaimed]:
        if enqueue_turn(turn.pk):
            counts["turns"] += 1

    # Failed evaluations of finishing sessions: try again after a pause (provider outage).
    for turn in SimTurn.objects.filter(
        role=SimTurn.Role.INTERN,
        job_state=SimTurn.Job.FAILED,
        scores__isnull=True,
        session__state=SimSession.State.FINISHING,
        session__last_activity_at__gte=now - timedelta(hours=24),
        job_enqueued_at__lt=now - timedelta(minutes=10),
    ):
        SimTurn.objects.filter(pk=turn.pk).update(
            job_state=SimTurn.Job.PENDING, job_attempts=0, job_lease_expires_at=None
        )
        if enqueue_turn(turn.pk):
            counts["retried"] += 1

    # Sessions waiting to be finalised: a worker died holding it (claim expired: do it
    # again at once), or nothing is in flight for it.
    finishing = SimSession.objects.filter(state=SimSession.State.FINISHING)
    for session in [
        *finishing.filter(finalize_lease_expires_at__lt=now),
        *finishing.filter(finalize_lease_expires_at__isnull=True).filter(
            Q(finalize_enqueued_at__isnull=True) | Q(finalize_enqueued_at__lt=stale)
        ),
    ]:
        if enqueue_finalize(session.pk):
            counts["finalize"] += 1

    # Silent sessions: nudge or close (a learner who has left still gets this).
    for pk in SimSession.objects.filter(state=SimSession.State.OPEN, preview=False).values_list(
        "pk", flat=True
    ):
        with transaction.atomic():
            session = SimSession.objects.select_for_update(of=("self",)).get(pk=pk)
            before = session.state, session.turns.count()
            _apply_idle(session, now)
            after = session.state, session.turns.count()
        if after != before:
            counts["closed" if after[0] != SimSession.State.OPEN else "nudged"] += 1

    counts["previews"] = SimSession.objects.filter(
        preview=True, state__in=STATES_LIVE, started_at__lt=now - MAX_PREVIEW_AGE
    ).update(state=SimSession.State.ABANDONED, abandon_reason="preview_expired", finished_at=now)

    from . import importing

    counts["imports"] = importing.recover(now=now)
    return counts
