"""Marking the written answers of a quiz.

A quiz may mix choice questions (scored at once) with written ones (a person gives marks). When a
learner submits such a quiz, the choice part is scored, the written answers wait here as a
`QuizReview`, and **no attempt exists yet**: the `ActivityAttempt` is written when the review is
marked, with the score over all the points (choice questions are worth one each, a written one its
`max_marks`) and the quiz's normal pass mark. Until then the learner can't start another try and
the next lesson stays open (the lesson is "awaiting review", like a handed-in simulation).

The lifecycle is `SimSubmission`'s: routed to the learner's mentor or the shared pool, a two-hour
claim, a review target that is only ever shown (never acted on), reassigned by a trainer or admin.
`access` serves both kinds, so who may see and mark what is one set of rules.

Services take `now=` (tests inject it) and never import views. Every write locks the review row
first, then the learner's progress row (the order the version move uses).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.activities import manual_sim as cfg
from apps.activities import quiz
from apps.catalog.models import Activity
from apps.notifications import events
from apps.progress import services as progress
from apps.progress.models import ActivityAttempt, ActivityProgress

from . import access, assignments, services
from .errors import BadInput, Conflict, Forbidden, NotFound
from .models import QuizReview, QuizReviewMark, SimSubmission

S = QuizReview.State
MAX_COMMENT = 4000
MAX_QUESTION_COMMENT = 2000


def _now():
    return timezone.now()


def _review(review_id: int, *, lock: bool = False) -> QuizReview:
    qs = QuizReview.objects.select_related(
        "user",
        "activity__content_node__course_version__course",
        "activity__content_node__course_version__root_node",
        "assigned_mentor",
        "claimed_by",
    )
    if lock:
        qs = qs.select_for_update(of=("self",))
    try:
        return qs.get(pk=review_id)
    except QuizReview.DoesNotExist as exc:
        raise NotFound("That quiz attempt doesn’t exist.") from exc


def open_review_for(user, activity: Activity) -> QuizReview | None:
    return QuizReview.objects.filter(user=user, activity=activity, state=S.SUBMITTED).first()


# ----------------------------------------------------------------------- submitting


def submit(
    user,
    activity: Activity,
    *,
    attempt_no: int,
    answers: list[Any],
    auto_earned: int,
    auto_possible: int,
    choice_results: list[bool | None],
    now,
) -> QuizReview:
    """Park a quiz attempt for marking. Called from `progress.submit_attempt` inside its
    transaction, with the learner's progress row already locked, so two quick submits can't both
    get here."""
    mentor, routing = assignments.route_for(user, activity)
    review = QuizReview.objects.create(
        user=user,
        activity=activity,
        attempt_no=attempt_no,
        answers=answers,
        auto_earned=auto_earned,
        auto_possible=auto_possible,
        choice_results=choice_results,
        submitted_at=now,
        review_due_at=now + timedelta(hours=cfg.review_hours(activity.config)),
        assigned_mentor=mentor,
        routing=routing,
    )
    events.work_waiting_quiz(review)
    return review


# ------------------------------------------------------- claiming, routing


@transaction.atomic
def claim(user, review_id: int, *, now=None) -> QuizReview:
    """Start marking: take it so nobody else works on it at the same time (a two-hour lease; a
    trainer or admin may take it over)."""
    now = now or _now()
    review = _review(review_id, lock=True)
    services._require_access(user, review, now)
    review.claimed_by = user
    review.claimed_at = now
    review.save(update_fields=["claimed_by", "claimed_at"])
    return review


@transaction.atomic
def release(user, review_id: int, *, now=None) -> QuizReview:
    now = now or _now()
    review = _review(review_id, lock=True)
    if review.state != S.SUBMITTED:
        raise Conflict("This attempt isn’t waiting for marking.")
    holder = access.lease(review, now)
    if holder is None:
        return review
    if holder.pk != user.pk and not access.is_manager(user):
        raise Forbidden("Another mentor is marking this one.")
    review.claimed_by = None
    review.claimed_at = None
    review.save(update_fields=["claimed_by", "claimed_at"])
    return review


@transaction.atomic
def reassign(actor, review_id: int, mentor=None, *, now=None) -> QuizReview:
    """A trainer or admin sends one attempt to a named mentor (or back to the pool)."""
    if not access.is_manager(actor):
        raise Forbidden("Only a trainer or an admin can reassign a review.")
    review = _review(review_id, lock=True)
    if review.state != S.SUBMITTED:
        raise Conflict("This attempt isn’t waiting for marking.")
    if mentor is not None and not assignments.is_eligible_mentor(mentor, review.user):
        raise BadInput("That person can’t mark this learner’s work.")
    review.assigned_mentor = mentor
    review.routing = SimSubmission.Routing.ADMIN
    review.claimed_by = None
    review.claimed_at = None
    review.save(update_fields=["assigned_mentor", "routing", "claimed_by", "claimed_at"])
    events.work_reassigned("quiz", review)
    return review


# ------------------------------------------------------------------------ marking


def written_questions(config: Any) -> list[tuple[int, dict[str, Any]]]:
    """(question index, question) for every written question, in order."""
    return [(i, q) for i, q in enumerate(quiz.questions(config)) if quiz.is_written(q)]


def _read_marks(config: Any, raw: Any) -> dict[int, int]:
    wanted = {i: q for i, q in written_questions(config)}
    if not isinstance(raw, dict):
        raise BadInput("Give marks for every written question.")
    try:
        given = {int(k): v for k, v in raw.items()}
    except (TypeError, ValueError) as exc:
        raise BadInput("Those marks don’t match this quiz’s questions.") from exc
    if set(given) != set(wanted):
        raise BadInput("Give marks for every written question.")
    out: dict[int, int] = {}
    for index, value in given.items():
        top = quiz.max_marks(wanted[index])
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= top:
            raise BadInput(f"Question {index + 1}: marks must be a whole number from 0 to {top}.")
        out[index] = value
    return out


def _read_comments(config: Any, raw: Any) -> dict[int, str]:
    if raw is None:
        return {}
    wanted = {i for i, _ in written_questions(config)}
    if not isinstance(raw, dict):
        raise BadInput("Those comments don’t match this quiz’s questions.")
    out: dict[int, str] = {}
    for key, text in raw.items():
        try:
            index = int(key)
        except (TypeError, ValueError) as exc:
            raise BadInput("Those comments don’t match this quiz’s questions.") from exc
        if index not in wanted:
            raise BadInput("Those comments don’t match this quiz’s questions.")
        if text is None or text == "":
            continue
        if not isinstance(text, str) or len(text) > MAX_QUESTION_COMMENT:
            raise BadInput(f"A comment can be up to {MAX_QUESTION_COMMENT:,} characters.")
        out[index] = text.strip()
    return out


@transaction.atomic
def rate(rater, review_id: int, marks, comments=None, overall=None, *, now=None) -> QuizReview:
    """Give the marks. Final: written once, never edited. The score is over every point on
    offer, the pass mark is the quiz's own, and the attempt is recorded here."""
    now = now or _now()
    review = _review(review_id, lock=True)
    services._require_access(rater, review, now)
    learner, activity = review.user, review.activity
    config = activity.config
    given = _read_marks(config, marks)
    notes = _read_comments(config, comments)
    if overall is not None and (not isinstance(overall, str) or len(overall) > MAX_COMMENT):
        raise BadInput(f"The overall comment can be up to {MAX_COMMENT:,} characters.")

    details: list[Any] = []
    written_total = 0
    for index, question in enumerate(quiz.questions(config)):
        if quiz.is_written(question):
            top = quiz.max_marks(question)
            written_total += top
            details.append({"marks": given[index], "max": top, "comment": notes.get(index, "")})
        else:
            details.append(bool(review.choice_results[index]))
    earned = review.auto_earned + sum(given.values())
    possible = review.auto_possible + written_total
    needed = quiz.required_points(possible, quiz.pass_threshold(config))
    passed = possible > 0 and earned >= needed

    row, _ = ActivityProgress.objects.select_for_update().get_or_create(
        user=learner, activity=activity, defaults={"started_at": now}
    )
    taken = ActivityAttempt.objects.filter(user=learner, activity=activity).count()
    progress.record_attempt(
        learner,
        activity,
        row,
        taken=taken,
        limit=activity.max_attempts,
        answers=review.answers,
        details=details,
        score=earned / possible if possible else 0.0,
        passed=passed,
        now=now,
        completes=passed,
    )
    review.attempt = ActivityAttempt.objects.get(user=learner, activity=activity, number=taken + 1)
    for index, question in written_questions(config):
        QuizReviewMark.objects.create(
            review=review,
            question_index=index,
            max_marks=quiz.max_marks(question),
            marks=given[index],
            comment=notes.get(index, ""),
        )
    review.state = S.RATED
    review.rated_by = rater
    review.rated_at = now
    review.overall_comment = (overall or "").strip()
    review.claimed_by = None
    review.claimed_at = None
    review.save()
    # Passed or out of tries: the quiz is finished and the lesson settles. Failed with tries
    # left: it is something to do again, so a lesson that was complete "pending marks" reopens.
    progress.settle_lesson(learner, progress._lesson_of(activity), reopen=True)
    events.work_done("quiz", review.pk)
    events.quiz_marked(review, passed=passed, score=earned / possible if possible else 0.0)
    return review
