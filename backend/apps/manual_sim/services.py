"""The life of a mentor-rated simulation.

A learner *opens* the activity (which starts their deadline), *submits* work (a new immutable
revision), a rater *rates* it, and the learner revises and resubmits until it passes. Trainers
and admins can reassign, extend, waive, close and reopen. Every write takes a row lock first
and is safe to repeat: a double click makes one submission, a rating can be given once.

Two clocks, never mixed:
  * the learner's deadline lives on the case (`due_at`) — first from when they opened it, then
    from when changes were requested; late work is accepted and marked late;
  * the mentor's review target lives on each submission (`review_due_at`).
Nothing here ever completes, fails or unblocks an activity by itself because a date passed:
overdue is only ever *shown*. The ways out are a pass, or a trainer/admin extending, waiving
or closing — each audited by its caller.

Services take `now=` (tests inject it), and never import views.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.activities import manual_sim as cfg
from apps.catalog.models import Activity
from apps.progress import services as progress
from apps.progress.models import ActivityAttempt, ActivityProgress

from . import access, assignments, files
from .errors import BadInput, Conflict, Forbidden, NotFound
from .models import RubricScore, SimCase, SimSubmission, SubmissionFile

log = logging.getLogger(__name__)

S = SimSubmission.State
MAX_COMMENT = 4000
MAX_FEEDBACK = 2000
MAX_REASON = 500
MAX_LINK = 500


def _now():
    return timezone.now()


# ------------------------------------------------------------------------ lookups


def _activity(activity_id: int) -> Activity:
    activity = progress._activity(activity_id)  # published, exists, completable
    if activity.activity_type != "manual_sim":
        raise Conflict("This activity isn’t a mentor-rated simulation.")
    return activity


def _lock_case(user, activity: Activity, now) -> SimCase:
    """The learner's case, created if needed, locked for the rest of the transaction."""
    case, _ = SimCase.objects.get_or_create(
        user=user,
        activity=activity,
        defaults={
            "opened_at": now,
            "due_at": _deadline(now, cfg.due_days(activity.config)),
            "due_basis": SimCase.DueBasis.INITIAL,
        },
    )
    return SimCase.objects.select_for_update().get(pk=case.pk)


def _deadline(start, days: int):
    return start + timedelta(days=days) if days else None


def _submission(submission_id: int, *, lock: bool = False) -> SimSubmission:
    qs = SimSubmission.objects.select_related(
        "case__user", "case__activity__content_node__course_version__course", "claimed_by"
    )
    if lock:
        qs = qs.select_for_update(of=("self",))
    try:
        return qs.get(pk=submission_id)
    except SimSubmission.DoesNotExist as exc:
        raise NotFound("That submission doesn’t exist.") from exc


def _progress_state(user, activity: Activity) -> str | None:
    return (
        ActivityProgress.objects.filter(user=user, activity=activity)
        .values_list("state", flat=True)
        .first()
    )


# --------------------------------------------------------------- the case at a glance


def case_summary(case: SimCase, *, now=None, state: str | None = None) -> dict[str, Any]:
    """Where a learner's work on this activity stands, computed from the rows and the clock.
    `state` is the learner's `ActivityProgress.state` if the caller already has it."""
    now = now or _now()
    subs = list(case.submissions.all())
    live = [s for s in subs if s.state != S.WITHDRAWN]
    waiting = next((s for s in subs if s.state == S.SUBMITTED), None)
    rated = [s for s in live if s.state == S.RATED]
    if state is None:
        state = _progress_state(case.user, case.activity)
    if case.is_closed:
        status = case.closed_reason  # "waived" | "not_passed"
    elif state == ActivityProgress.State.COMPLETED:
        status = "passed"
    elif waiting is not None:
        status = "waiting"
    elif live and live[-1].state == S.RATED and live[-1].passed is False:
        status = "changes_requested"
    else:
        status = "not_submitted"
    unsuccessful = sum(1 for s in rated if s.passed is False)
    finished = status in ("passed", "waived", "not_passed")
    return {
        "status": status,
        "revisions": len(live),
        "unsuccessful": unsuccessful,
        "due_at": case.due_at,
        "due_basis": case.due_basis,
        "overdue": (
            not finished and waiting is None and case.due_at is not None and now > case.due_at
        ),
        "needs_attention": (not finished) and unsuccessful >= settings.MANUAL_SIM_ATTENTION_AFTER,
        "last_score": rated[-1].raw_score if rated else None,
        "waiting": waiting,
    }


# ------------------------------------------------------------------------- opening


def open_case(user, activity_id: int, *, now=None) -> SimCase:
    """The learner opens the activity: their deadline starts (once). Safe to repeat."""
    now = now or _now()
    activity = _activity(activity_id)
    progress._assert_lesson_open(user, progress._lesson_of(activity))
    with transaction.atomic():
        ActivityProgress.objects.get_or_create(
            user=user, activity=activity, defaults={"started_at": now}
        )
        return _lock_case(user, activity, now)


# ------------------------------------------------------------------------ submitting


def _clean_links(raw: Any) -> list[str]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise BadInput("Links must be a list.")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise BadInput("A link wasn’t text.")
        link = item.strip()
        if not link:
            continue
        parts = urlsplit(link)
        if (
            len(link) > MAX_LINK
            or parts.scheme not in ("http", "https")
            or not parts.netloc
            or any(ch.isspace() or not ch.isprintable() for ch in link)
        ):
            raise BadInput("Links must start with http:// or https:// and have no spaces.")
        out.append(link)
    if len(out) > settings.MANUAL_SIM_MAX_LINKS:
        raise BadInput(f"Add at most {settings.MANUAL_SIM_MAX_LINKS} links.")
    return out


def submit(user, activity_id: int, answer: Any, links: Any = None, uploads=(), *, now=None):
    """Hand in work: the first submission, or a revision after changes were requested."""
    try:
        return _submit(user, activity_id, answer, links, list(uploads), now or _now())
    except IntegrityError as exc:
        # Two requests raced past the checks; the database kept only one open submission.
        raise Conflict(
            "You already have work waiting for a mentor. Wait for the rating, or withdraw it first."
        ) from exc


def _submit(user, activity_id, answer, links, uploads, now) -> SimSubmission:
    activity = _activity(activity_id)
    progress._assert_lesson_open(user, progress._lesson_of(activity))
    config = activity.config
    if not isinstance(answer, str) or not answer.strip():
        raise BadInput("Write your answer before handing it in.")
    if len(answer) > settings.MANUAL_SIM_MAX_ANSWER_CHARS:
        raise BadInput(
            f"Your answer is longer than {settings.MANUAL_SIM_MAX_ANSWER_CHARS:,} characters."
        )
    clean_links = _clean_links(links)
    detected = files.check_batch(uploads, allowed=cfg.allow_files(config))  # nothing written yet

    written: list[SubmissionFile] = []
    try:
        with transaction.atomic():
            ActivityProgress.objects.get_or_create(
                user=user, activity=activity, defaults={"started_at": now}
            )
            case = _lock_case(user, activity, now)
            if case.is_closed:
                raise Conflict(
                    "This activity has been closed. Ask your trainer if you need to continue."
                )
            if _progress_state(user, activity) == ActivityProgress.State.COMPLETED:
                raise Conflict("You’ve already passed this one.")
            subs = list(case.submissions.order_by("revision"))
            if any(s.state == S.SUBMITTED for s in subs):
                raise Conflict(
                    "You already have work waiting for a mentor. "
                    "Wait for the rating, or withdraw it first."
                )
            live = [s for s in subs if s.state != S.WITHDRAWN]
            if live and not (live[-1].state == S.RATED and live[-1].passed is False):
                raise Conflict("There’s nothing to revise yet.")
            mentor, routing = assignments.route_for(user, activity)
            sub = SimSubmission.objects.create(
                case=case,
                revision=(subs[-1].revision + 1) if subs else 1,
                previous=live[-1] if live else None,
                answer=answer.strip(),
                links=clean_links,
                submitted_at=now,
                due_snapshot=case.due_at,
                late=case.due_at is not None and now > case.due_at,
                review_due_at=now + timedelta(hours=cfg.review_hours(config)),
                assigned_mentor=mentor,
                routing=routing,
            )
            for upload, kind in zip(uploads, detected, strict=True):
                uid = files.write(upload, kind)
                written.append(
                    SubmissionFile.objects.create(
                        submission=sub,
                        uuid=uid,
                        original_name=files.display_name(getattr(upload, "name", "")),
                        content_type=kind.content_type,
                        extension=kind.extension,
                        size_bytes=kind.size,
                    )
                )
            return sub
    except BaseException:
        files.discard(written)  # the rows roll back with the transaction; so do the files
        raise


# ----------------------------------------------------------------------- withdrawing


@transaction.atomic
def withdraw(user, submission_id: int, *, now=None) -> SimSubmission:
    """The learner takes back work nobody has started reviewing. It costs them nothing and
    does not move their deadline."""
    now = now or _now()
    sub = _submission(submission_id, lock=True)
    if sub.case.user_id != user.pk:
        raise NotFound("That submission doesn’t exist.")
    if sub.state != S.SUBMITTED:
        raise Conflict("That one is no longer waiting, so it can’t be withdrawn.")
    if access.lease(sub, now) is not None or sub.draft:
        raise Conflict("A mentor has started reviewing it, so it can’t be withdrawn now.")
    _withdraw(sub, "learner")
    _settle(sub.case.user, sub.case.activity)
    return sub


def _settle(user, activity: Activity, *, reopen: bool = False) -> None:
    """The lesson may have been completed on the strength of this activity being handed in;
    keep it provisional until nothing in it awaits a pass."""
    progress.settle_lesson(user, progress._lesson_of(activity), reopen=reopen)


def _withdraw(sub: SimSubmission, by: str) -> None:
    sub.state = S.WITHDRAWN
    sub.withdrawn_by = by
    sub.claimed_by = None
    sub.claimed_at = None
    sub.draft = {}
    sub.draft_by = None
    sub.save(
        update_fields=[
            "state",
            "withdrawn_by",
            "claimed_by",
            "claimed_at",
            "draft",
            "draft_by",
        ]
    )


# ------------------------------------------------------ claiming, routing, drafting


def _require_access(user, sub: SimSubmission, now):
    decision = access.rating_access(user, sub, now)
    if decision.allowed:
        return decision
    if sub.state != S.SUBMITTED:
        raise Conflict(decision.reason)
    if sub.case.user_id == user.pk or not access.is_rater(user):
        raise Forbidden(decision.reason)
    if decision.held_by is not None:
        raise Conflict(decision.reason)
    raise Forbidden(decision.reason)


@transaction.atomic
def claim(user, submission_id: int, *, now=None) -> SimSubmission:
    """Start rating: take the submission so nobody else works on it at the same time (a
    two-hour lease; a trainer or admin may take it over)."""
    now = now or _now()
    sub = _submission(submission_id, lock=True)
    _require_access(user, sub, now)
    _take(sub, user, now)
    return sub


def _take(sub: SimSubmission, user, now) -> None:
    sub.claimed_by = user
    sub.claimed_at = now
    sub.save(update_fields=["claimed_by", "claimed_at"])


@transaction.atomic
def release(user, submission_id: int, *, now=None) -> SimSubmission:
    """Give a claim back (your own; a trainer or admin may release anyone's). A saved draft
    stays with the submission."""
    now = now or _now()
    sub = _submission(submission_id, lock=True)
    if sub.state != S.SUBMITTED:
        raise Conflict("This submission isn’t waiting for a rating.")
    holder = access.lease(sub, now)
    if holder is None:
        return sub
    if holder.pk != user.pk and not access.is_manager(user):
        raise Forbidden("Another mentor is rating this one.")
    sub.claimed_by = None
    sub.claimed_at = None
    sub.save(update_fields=["claimed_by", "claimed_at"])
    return sub


@transaction.atomic
def reassign(actor, submission_id: int, mentor=None, *, now=None) -> SimSubmission:
    """A trainer or admin sends one submission to a named mentor (or back to the pool).
    It then stays where they put it, whatever happens to the learner's assignments."""
    if not access.is_manager(actor):
        raise Forbidden("Only a trainer or an admin can reassign a review.")
    sub = _submission(submission_id, lock=True)
    if sub.state != S.SUBMITTED:
        raise Conflict("This submission isn’t waiting for a rating.")
    if mentor is not None and not assignments.is_eligible_mentor(mentor, sub.case.user):
        raise BadInput("That person can’t rate this learner’s work.")
    sub.assigned_mentor = mentor
    sub.routing = SimSubmission.Routing.ADMIN
    sub.claimed_by = None
    sub.claimed_at = None
    sub.save(update_fields=["assigned_mentor", "routing", "claimed_by", "claimed_at"])
    return sub


def _read_scores(config: Any, raw: Any, *, complete: bool) -> dict[str, int | None]:
    wanted = [c["key"] for c in cfg.criteria(config)]
    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or set(raw) - set(wanted):
        raise BadInput("Those scores don’t match this activity’s criteria.")
    out: dict[str, int | None] = {}
    for key in wanted:
        value = raw.get(key)
        if value is None:
            if complete:
                raise BadInput("Score every criterion before submitting.")
            out[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= cfg.MAX_SCORE:
            raise BadInput("Each score must be a whole number from 1 to 5.")
        out[key] = value
    return out


def _read_feedback(config: Any, raw: Any) -> dict[str, str]:
    wanted = {c["key"] for c in cfg.criteria(config)}
    if raw is None:
        return {}
    if not isinstance(raw, dict) or set(raw) - wanted:
        raise BadInput("That feedback doesn’t match this activity’s criteria.")
    out: dict[str, str] = {}
    for key, text in raw.items():
        if text is None or text == "":
            continue
        if not isinstance(text, str) or len(text) > MAX_FEEDBACK:
            raise BadInput(f"Feedback can be up to {MAX_FEEDBACK:,} characters per criterion.")
        out[key] = text.strip()
    return out


@transaction.atomic
def save_draft(user, submission_id: int, scores=None, feedback=None, comment=None, *, now=None):
    """Keep a rating in progress. Anything may be missing; nothing is final."""
    now = now or _now()
    sub = _submission(submission_id, lock=True)
    decision = _require_access(user, sub, now)
    config = sub.case.activity.config
    if comment is not None and (not isinstance(comment, str) or len(comment) > MAX_COMMENT):
        raise BadInput(f"The overall comment can be up to {MAX_COMMENT:,} characters.")
    sub.draft = {
        "scores": _read_scores(config, scores, complete=False),
        "feedback": _read_feedback(config, feedback),
        "comment": (comment or "").strip(),
    }
    sub.draft_by = user
    if decision.via != "assigned":  # a claim only matters where others could also take it
        sub.claimed_by = user
        sub.claimed_at = now
    sub.save(update_fields=["draft", "draft_by", "claimed_by", "claimed_at"])
    return sub


# ---------------------------------------------------------------------------- rating


@transaction.atomic
def rate(rater, submission_id: int, scores, feedback=None, comment=None, *, now=None):
    """Give the rating. Final: it is written once and never edited. Returns the submission."""
    now = now or _now()
    # Same lock order as submitting and closing: the case first, then the submission.
    case = SimCase.objects.select_for_update().get(pk=_submission(submission_id).case_id)
    sub = _submission(submission_id, lock=True)
    _require_access(rater, sub, now)
    learner, activity = sub.case.user, sub.case.activity
    if case.is_closed:
        raise Conflict("This case was closed, so it can’t be rated.")
    config = activity.config
    marks = _read_scores(config, scores, complete=True)
    notes = _read_feedback(config, feedback)
    if not isinstance(comment, str) or not comment.strip():
        raise BadInput("Add an overall comment for the learner.")
    if len(comment) > MAX_COMMENT:
        raise BadInput(f"The overall comment can be up to {MAX_COMMENT:,} characters.")
    result = cfg.rate(config, {k: int(v) for k, v in marks.items() if v is not None})

    criteria = cfg.criteria(config)
    for order, c in enumerate(criteria):
        RubricScore.objects.create(
            submission=sub,
            criterion_key=c["key"],
            label=c["label"],
            max_score=cfg.MAX_SCORE,
            score=int(marks[c["key"]] or 0),
            feedback=notes.get(c["key"], ""),
            order=order,
        )

    row, _ = ActivityProgress.objects.select_for_update().get_or_create(
        user=learner, activity=activity, defaults={"started_at": now}
    )
    taken = ActivityAttempt.objects.filter(user=learner, activity=activity).count()
    progress.record_attempt(
        learner,
        activity,
        row,
        taken=taken,
        limit=0,  # deadlines, not a count of tries, bound this work
        answers={"submission": sub.pk, "revision": sub.revision},
        details=[
            {"key": c["key"], "label": c["label"], "score": marks[c["key"]], "max": cfg.MAX_SCORE}
            for c in criteria
        ],
        score=result.scaled,
        passed=result.passed,
        now=now,
        completes=result.passed,
    )
    sub.attempt = ActivityAttempt.objects.get(user=learner, activity=activity, number=taken + 1)
    sub.state = S.RATED
    sub.rated_by = rater
    sub.rated_at = now
    sub.overall_comment = comment.strip()
    sub.raw_score = result.raw
    sub.scaled = result.scaled
    sub.passed = result.passed
    sub.claimed_by = None
    sub.claimed_at = None
    sub.draft = {}
    sub.draft_by = None
    sub.save()
    if not result.passed:
        # Changes were requested: the learner's revision window starts now.
        case.due_at = _deadline(now, cfg.revision_days(config))
        case.due_basis = SimCase.DueBasis.REVISION
        case.save(update_fields=["due_at", "due_basis"])
    else:
        _settle(learner, activity)
    return sub


# ------------------------------------------- trainer / admin: extend, waive, close, reopen


def _reason(text: Any) -> str:
    if not isinstance(text, str) or not text.strip():
        raise BadInput("Give a reason. It is kept in the audit log.")
    if len(text.strip()) > MAX_REASON:
        raise BadInput(f"The reason can be up to {MAX_REASON} characters.")
    return text.strip()


def _manager(actor) -> None:
    if not access.is_manager(actor):
        raise Forbidden("Only a trainer or an admin can do that.")


def _case(case_id: int) -> SimCase:
    try:
        return (
            SimCase.objects.select_for_update().select_related("user", "activity").get(pk=case_id)
        )
    except SimCase.DoesNotExist as exc:
        raise NotFound("That case doesn’t exist.") from exc


@transaction.atomic
def extend(actor, case_id: int, days: Any, reason: Any, *, now=None) -> SimCase:
    """Give the learner more time (counted from now, or from the current deadline if that is
    later)."""
    now = now or _now()
    _manager(actor)
    case = _case(case_id)
    note = _reason(reason)
    limit = settings.MANUAL_SIM_EXTEND_MAX_DAYS
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= limit:
        raise BadInput(f"Extend by 1 to {limit} days.")
    if case.is_closed:
        raise Conflict("This case is closed. Reopen it first.")
    if _progress_state(case.user, case.activity) == ActivityProgress.State.COMPLETED:
        raise Conflict("They’ve already passed this one.")
    start = max(case.due_at or now, now)
    case.due_at = start + timedelta(days=days)
    case.due_basis = SimCase.DueBasis.EXTENDED
    case.save(update_fields=["due_at", "due_basis"])
    log.info("Case %s extended by %s days (%s)", case.pk, days, note[:40])
    return case


def _finish(actor, case_id: int, reason: Any, closed: str, now) -> SimCase:
    _manager(actor)
    case = _case(case_id)
    note = _reason(reason)
    if case.is_closed:
        raise Conflict("This case is already closed.")
    if _progress_state(case.user, case.activity) == ActivityProgress.State.COMPLETED:
        raise Conflict("They’ve already passed this one.")
    for waiting in case.submissions.select_for_update().filter(state=S.SUBMITTED):
        _withdraw(waiting, "closed")  # a rating can't arrive after the case is closed
    case.closed_at = now
    case.closed_by = actor
    case.closed_reason = closed
    case.close_note = note
    case.save(update_fields=["closed_at", "closed_by", "closed_reason", "close_note"])
    row, _ = ActivityProgress.objects.select_for_update().get_or_create(
        user=case.user, activity=case.activity, defaults={"started_at": now}
    )
    # "Finished, not passed": stops holding the lesson up, and the case says which kind.
    row.state = ActivityProgress.State.EXHAUSTED
    row.save(update_fields=["state"])
    _settle(case.user, case.activity)
    return case


@transaction.atomic
def waive(actor, case_id: int, reason: Any, *, now=None) -> SimCase:
    """Excuse the learner from this activity. It stops holding their lesson up, is recorded as
    waived, and never counts as passed."""
    return _finish(actor, case_id, reason, SimCase.Closed.WAIVED, now or _now())


@transaction.atomic
def close(actor, case_id: int, reason: Any, *, now=None) -> SimCase:
    """End the case as not passed (final). It stops holding the lesson up; it never counts as
    passed."""
    return _finish(actor, case_id, reason, SimCase.Closed.NOT_PASSED, now or _now())


@transaction.atomic
def reopen(actor, case_id: int, reason: Any, *, now=None) -> SimCase:
    """Undo a waive or close: the learner can hand work in again, with a fresh deadline."""
    now = now or _now()
    _manager(actor)
    case = _case(case_id)
    _reason(reason)
    if not case.is_closed:
        raise Conflict("This case isn’t closed.")
    case.closed_at = None
    case.closed_by = None
    case.closed_reason = ""
    case.close_note = ""
    revising = case.submissions.exclude(state=S.WITHDRAWN).exists()
    days = (
        cfg.revision_days(case.activity.config) if revising else cfg.due_days(case.activity.config)
    )
    case.due_at = _deadline(now, days)
    case.due_basis = SimCase.DueBasis.EXTENDED
    case.save()
    row = (
        ActivityProgress.objects.select_for_update()
        .filter(user=case.user, activity=case.activity)
        .first()
    )
    if row is not None and row.state == ActivityProgress.State.EXHAUSTED:
        row.state = ActivityProgress.State.STARTED
        row.completed_at = None
        row.save(update_fields=["state", "completed_at"])
    if case.activity.is_required:
        # The lesson was finished with this activity out of the way; unless work is already
        # handed in (then it simply awaits a rating again), that is no longer true.
        _settle(case.user, case.activity, reopen=True)
    return case
