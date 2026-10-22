"""
Recording what a learner has done. Every rule lives here; the views only
translate to HTTP.

  * Only *published* content can be recorded against (drafts are the author's
    workspace; archived versions belong to no new learner).
  * Only activity types the platform can complete today are recordable
    (`registry.is_completable`); others render as "coming later" and never
    block a lesson.
  * Scored types (a quiz) are completed by *passing*: `submit_attempt` judges
    the answers on the server, records the attempt, and completes the
    activity on a pass. Self-attested completion is refused for them.
  * A lesson can be completed once every *required, completable* activity in
    it — its own and its sections' — is finished: passed, or (for a scored
    activity) out of attempts. A learner is never trapped by a failed quiz;
    every attempt and score stays on record.
  * Everything is idempotent and undoable.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.activities.registry import get_type, is_completable
from apps.catalog.models import Activity, ContentNode, CourseVersion

from .models import ActivityAttempt, ActivityProgress, LessonCompletion


class ProgressError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(ProgressError):
    status_code = 404


class NotCompletable(ProgressError):
    status_code = 400


class BadAnswers(ProgressError):
    status_code = 400


class AttemptNotAllowed(ProgressError):
    """Already passed, or out of attempts."""

    status_code = 409


class ResetNotAllowed(ProgressError):
    status_code = 403


class LessonBlocked(ProgressError):
    """The lesson still has required activities to finish."""

    status_code = 409

    def __init__(self, pending: list[int]):
        n = len(pending)
        noun = "activity" if n == 1 else "activities"
        super().__init__(f"Finish the {n} required {noun} in this lesson first.")
        self.pending = pending


def _published(version: CourseVersion) -> bool:
    # Archiving a course retires it: nothing more can be recorded against it.
    return version.state == CourseVersion.State.PUBLISHED and version.course.archived_at is None


def _activity(activity_id: int) -> Activity:
    try:
        activity = Activity.objects.select_related("content_node__course_version__course").get(
            pk=activity_id
        )
    except Activity.DoesNotExist as exc:
        raise NotFound("That activity doesn’t exist.") from exc
    if not _published(activity.content_node.course_version):
        raise NotFound("That activity isn’t available.")
    if not is_completable(activity.activity_type):
        raise NotCompletable("This kind of activity can’t be completed yet.")
    return activity


def _is_scored(activity: Activity) -> bool:
    descriptor = get_type(activity.activity_type)
    return descriptor is not None and descriptor.score is not None


def _self_attested(activity_id: int) -> Activity:
    activity = _activity(activity_id)
    if _is_scored(activity):
        raise NotCompletable("This activity is completed by passing it.")
    return activity


def _lesson_of(activity: Activity) -> ContentNode | None:
    node = activity.content_node
    if node.kind == ContentNode.Kind.TOPIC:
        return node
    if node.kind == ContentNode.Kind.SUBTOPIC:
        return node.parent
    return None


# ------------------------------------------------------------------ activities


def start_activity(user, activity_id: int) -> str:
    activity = _activity(activity_id)
    row, _ = ActivityProgress.objects.get_or_create(
        user=user, activity=activity, defaults={"started_at": timezone.now()}
    )
    return row.state


@transaction.atomic
def complete_activity(user, activity_id: int) -> str:
    activity = _self_attested(activity_id)
    now = timezone.now()
    row, _ = ActivityProgress.objects.get_or_create(
        user=user, activity=activity, defaults={"started_at": now}
    )
    if row.state != ActivityProgress.State.COMPLETED:
        row.state = ActivityProgress.State.COMPLETED
        row.completed_at = now
        row.save(update_fields=["state", "completed_at"])
    return row.state


@transaction.atomic
def uncomplete_activity(user, activity_id: int) -> str | None:
    """Back to "started". If that activity was needed for an already
    completed lesson, the lesson is reopened too (it is no longer true)."""
    activity = _self_attested(activity_id)
    row = ActivityProgress.objects.filter(user=user, activity=activity).first()
    if row is None:
        return None
    if row.state == ActivityProgress.State.COMPLETED:
        row.state = ActivityProgress.State.STARTED
        row.completed_at = None
        row.save(update_fields=["state", "completed_at"])
        lesson = _lesson_of(activity)
        if lesson is not None and activity.is_required:
            LessonCompletion.objects.filter(user=user, node=lesson).delete()
    return row.state


# -------------------------------------------------------------------- attempts


@transaction.atomic
def submit_attempt(user, activity_id: int, raw_answers) -> dict:
    """Judge and record one try at a scored activity. The progress row is
    locked first, so two quick submits can't both take the last attempt or
    skip a number. A pass completes the activity (permanently)."""
    activity = _activity(activity_id)
    descriptor = get_type(activity.activity_type)
    if descriptor is None or descriptor.score is None or descriptor.review is None:
        raise NotCompletable("This activity isn’t scored.")

    now = timezone.now()
    row, _ = ActivityProgress.objects.select_for_update().get_or_create(
        user=user, activity=activity, defaults={"started_at": now}
    )
    if row.state == ActivityProgress.State.COMPLETED:
        raise AttemptNotAllowed("You’ve already passed this one.")
    taken = ActivityAttempt.objects.filter(user=user, activity=activity).count()
    limit = activity.max_attempts  # 0 = unlimited
    if limit and taken >= limit:
        raise AttemptNotAllowed("You’ve used all your attempts. Ask your trainer for another try.")

    try:
        result, answers = descriptor.score(activity.config, raw_answers)
    except ValueError as exc:
        raise BadAnswers(str(exc)) from exc

    number = taken + 1
    ActivityAttempt.objects.create(
        user=user,
        activity=activity,
        number=number,
        answers=answers,
        details=result.results,
        score=result.score,
        passed=result.passed,
        submitted_at=now,
    )
    attempts_left = max(limit - number, 0) if limit else None
    if result.passed:
        row.state = ActivityProgress.State.COMPLETED
        row.completed_at = now
        row.save(update_fields=["state", "completed_at"])
    elif attempts_left == 0:
        row.state = ActivityProgress.State.EXHAUSTED
        row.save(update_fields=["state"])

    # The answer key is revealed only when trying again can no longer be gamed
    # by it: once passed, or once the last attempt is spent.
    reveal = result.passed or attempts_left == 0
    return {
        "state": row.state,
        "passed": result.passed,
        "score": result.score,
        "correct": result.correct,
        "total": result.total,
        "needed": result.needed,
        "attempts_left": attempts_left,
        "picks": answers,
        "review": descriptor.review(activity.config, result, reveal=reveal),
        "history": _history(user, activity),
    }


def _history(user, activity: Activity) -> list[dict]:
    """Every try, oldest first — what a learner sees as "Your attempts"."""
    return [
        {
            "number": a.number,
            "score": a.score,
            "correct": sum(a.details),
            "total": len(a.details),
            "passed": a.passed,
            "submitted_at": a.submitted_at.isoformat(),
        }
        for a in ActivityAttempt.objects.filter(user=user, activity=activity).order_by("number")
    ]


def attempts_report(user, activity_id: int) -> dict:
    """The learner's own attempt history and their latest try, reviewed. The
    answer key appears only under the same rule as when they submitted."""
    activity = _activity(activity_id)
    descriptor = get_type(activity.activity_type)
    if descriptor is None or descriptor.review is None:
        raise NotCompletable("This activity isn’t scored.")
    history = _history(user, activity)
    last = ActivityAttempt.objects.filter(user=user, activity=activity).order_by("-number").first()
    if last is None:
        return {"history": [], "latest": None}
    row = ActivityProgress.objects.filter(user=user, activity=activity).first()
    state = row.state if row else ActivityProgress.State.STARTED
    finished = state in (ActivityProgress.State.COMPLETED, ActivityProgress.State.EXHAUSTED)
    limit = activity.max_attempts
    return {
        "history": history,
        "latest": {
            "state": state,
            "passed": last.passed,
            "score": last.score,
            "correct": sum(last.details),
            "total": len(last.details),
            "needed": None,
            "attempts_left": max(limit - last.number, 0) if limit else None,
            "picks": last.answers,
            "review": descriptor.review(
                activity.config, SimpleNamespace(results=last.details), reveal=finished
            ),
            "history": history,
        },
    }


@transaction.atomic
def reset_attempts(user, activity_id: int) -> None:
    """Forget the learner's own tries at a scored activity so it can be taken
    again (for testing). It defeats the attempt limit, so it exists only where
    `ALLOW_ATTEMPT_RESET` is on; trainers get a proper screen later."""
    if not settings.ALLOW_ATTEMPT_RESET:
        raise ResetNotAllowed("Resetting attempts isn’t available here.")
    activity = _activity(activity_id)
    if not _is_scored(activity):
        raise NotCompletable("This activity has no attempts to reset.")
    _wipe_attempts(user, activity)


def _wipe_attempts(user, activity: Activity) -> dict:
    """Delete one learner's tries at one activity, and everything that rested
    on them. Returns what was removed (for the audit trail)."""
    previous = ActivityProgress.objects.filter(user=user, activity=activity).first()
    removed, _ = ActivityAttempt.objects.filter(user=user, activity=activity).delete()
    ActivityProgress.objects.filter(user=user, activity=activity).delete()
    lesson = _lesson_of(activity)
    if lesson is not None and activity.is_required:
        # The lesson was finished with this activity behind it; no longer true.
        LessonCompletion.objects.filter(user=user, node=lesson).delete()
    return {"attempts_deleted": removed, "previous_state": previous.state if previous else None}


@transaction.atomic
def reset_attempts_for(learner, activity_id: int) -> dict:
    """The trainer/admin reset: any learner's attempts at any scored activity.
    Authorised by the caller (`progress.manage_attempts`); not behind the
    learner-facing `ALLOW_ATTEMPT_RESET` switch."""
    try:
        activity = Activity.objects.select_related("content_node__course_version__course").get(
            pk=activity_id
        )
    except Activity.DoesNotExist as exc:
        raise NotFound("That activity doesn’t exist.") from exc
    if not _is_scored(activity):
        raise NotCompletable("This activity has no attempts to reset.")
    return _wipe_attempts(learner, activity)


# --------------------------------------------------------------------- lessons


def _lesson(node_id: int) -> ContentNode:
    try:
        node = ContentNode.objects.select_related("course_version__course").get(pk=node_id)
    except ContentNode.DoesNotExist as exc:
        raise NotFound("That lesson doesn’t exist.") from exc
    if node.kind != ContentNode.Kind.TOPIC or not _published(node.course_version):
        raise NotFound("That lesson isn’t available.")
    return node


def pending_activities(user, lesson: ContentNode) -> list[int]:
    """Required, completable activities in the lesson the learner hasn't finished."""
    required = [
        a
        for a in Activity.objects.filter(
            content_node__in=[lesson, *lesson.children.all()], is_required=True
        )
        if is_completable(a.activity_type)
    ]
    done = set(
        ActivityProgress.objects.filter(
            user=user,
            activity__in=required,
            state__in=[ActivityProgress.State.COMPLETED, ActivityProgress.State.EXHAUSTED],
        ).values_list("activity_id", flat=True)
    )
    return [a.id for a in required if a.id not in done]


@transaction.atomic
def complete_lesson(user, node_id: int) -> None:
    lesson = _lesson(node_id)
    pending = pending_activities(user, lesson)
    if pending:
        raise LessonBlocked(pending)
    LessonCompletion.objects.get_or_create(
        user=user, node=lesson, defaults={"completed_at": timezone.now()}
    )


def uncomplete_lesson(user, node_id: int) -> None:
    lesson = _lesson(node_id)
    LessonCompletion.objects.filter(user=user, node=lesson).delete()


# ------------------------------------------------------------------- read side


def course_progress(user, version_id: int) -> dict:
    """{"completed_lessons": [node ids], "activities": {activity id: state}}."""
    try:
        version = CourseVersion.objects.select_related("course").get(pk=version_id)
    except CourseVersion.DoesNotExist as exc:
        raise NotFound("That course doesn’t exist.") from exc
    if not _published(version):
        raise NotFound("That course isn’t available.")
    lessons = list(
        LessonCompletion.objects.filter(user=user, node__course_version=version).values_list(
            "node_id", flat=True
        )
    )
    activities = dict(
        ActivityProgress.objects.filter(
            user=user, activity__content_node__course_version=version
        ).values_list("activity_id", "state")
    )
    return {
        "completed_lessons": lessons,
        "activities": activities,
        "attempts": _attempt_summaries(user, version),
        "can_reset_attempts": bool(settings.ALLOW_ATTEMPT_RESET),
    }


def _attempt_summaries(user, version: CourseVersion) -> dict[int, dict]:
    """{activity id: {count, best_score, last_score, attempts_left}} — one query."""
    rows = ActivityAttempt.objects.filter(
        user=user, activity__content_node__course_version=version
    ).values_list("activity_id", "score", "activity__max_attempts")
    summaries: dict[int, dict] = {}
    for activity_id, score, limit in rows.order_by("activity_id", "number"):
        entry = summaries.setdefault(
            activity_id,
            {"count": 0, "best_score": 0.0, "last_score": 0.0, "limit": limit},
        )
        entry["count"] += 1
        entry["best_score"] = max(entry["best_score"], score)
        entry["last_score"] = score
    return {
        activity_id: {
            "count": e["count"],
            "best_score": e["best_score"],
            "last_score": e["last_score"],
            "attempts_left": max(e["limit"] - e["count"], 0) if e["limit"] else None,
        }
        for activity_id, e in summaries.items()
    }
