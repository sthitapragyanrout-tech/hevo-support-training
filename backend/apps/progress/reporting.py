"""
Read models for the Admin Console's results screens: who has done what, with
which scores. Pure queries — no writes, no permission checks (the console
views authorise first).

The attempt rows are the source of truth for scores; `ActivityProgress` holds
each learner's current state per activity.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q
from django.db.models.functions import Lower

from apps.activities import video
from apps.activities.registry import ACTIVITY_TYPES, is_completable
from apps.catalog.models import Activity, ContentNode, CourseVersion

from . import watching
from .models import ActivityAttempt, ActivityProgress, LessonCompletion, VideoWatch

User = get_user_model()

SCORED_TYPES = [key for key, d in ACTIVITY_TYPES.items() if d.score is not None]

LEARNER_ORDERING = {
    "name": "sort_name",
    "-name": "-sort_name",
    "lessons": "lessons_completed",
    "-lessons": "-lessons_completed",
    "attempts": "quiz_attempts",
    "-attempts": "-quiz_attempts",
}


def display_name(user) -> str:
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.email or user.username


def course_options() -> list[dict[str, Any]]:
    """Courses that have a published version (the ones with results to see)."""
    versions = (
        CourseVersion.objects.filter(state=CourseVersion.State.PUBLISHED)
        .select_related("root_node", "course")
        .order_by("course_id", "-version")
    )
    seen: set[int] = set()
    options = []
    for v in versions:
        if v.course_id in seen:
            continue
        seen.add(v.course_id)
        options.append(
            {"id": v.course_id, "title": v.root_node.title if v.root_node else v.course.slug}
        )
    return sorted(options, key=lambda o: o["title"].lower())


def learners_queryset(search: str = "", course_id: int | None = None, ordering: str = "name"):
    """Learners = people holding the learner role, plus anyone who has done
    something (so a trainer who tried a quiz still shows up)."""
    active = (
        Q(role_assignments__role__name="learner")
        | Q(activity_progress__isnull=False)
        | Q(lesson_completions__isnull=False)
        | Q(activity_attempts__isnull=False)
    )
    ids = User.objects.filter(active).values("pk")
    qs = User.objects.filter(pk__in=ids)
    if search:
        qs = qs.filter(
            Q(username__icontains=search)
            | Q(email__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(employee_id__icontains=search)
        )
    if course_id is not None:
        started = Q(
            pk__in=ActivityProgress.objects.filter(
                activity__content_node__course_version__course_id=course_id
            ).values("user")
        ) | Q(
            pk__in=LessonCompletion.objects.filter(
                node__course_version__course_id=course_id
            ).values("user")
        )
        qs = qs.filter(started)
    qs = qs.annotate(
        lessons_completed=Count(
            "lesson_completions",
            filter=Q(lesson_completions__provisional=False)
            & (
                Q(lesson_completions__node__course_version__course_id=course_id)
                if course_id is not None
                else Q()
            ),
            distinct=True,
        ),
        # Quizzes only: a practice ticket is not a quiz, and has its own rows.
        quiz_attempts=Count(
            "activity_attempts",
            filter=Q(activity_attempts__activity__activity_type="mcq")
            & (
                Q(activity_attempts__activity__content_node__course_version__course_id=course_id)
                if course_id is not None
                else Q()
            ),
            distinct=True,
        ),
    )
    qs = qs.annotate(sort_name=Lower("email"))
    return qs.order_by(LEARNER_ORDERING.get(ordering, "sort_name"), "pk")


def learner_row(user, last_activity) -> dict[str, Any]:
    return {
        "id": user.pk,
        "name": display_name(user),
        "email": user.email,
        "employee_id": user.employee_id,
        "lessons_completed": user.lessons_completed,
        "quiz_attempts": user.quiz_attempts,
        "last_activity": last_activity.isoformat() if last_activity else None,
    }


def last_activity_for(user_ids: list[int]) -> dict[int, Any]:
    """Most recent thing each learner did, across attempts, lessons, activities."""
    latest: dict[int, Any] = {}

    def fold(rows):
        for uid, when in rows:
            if when and (uid not in latest or when > latest[uid]):
                latest[uid] = when

    fold(
        ActivityAttempt.objects.filter(user_id__in=user_ids)
        .values("user_id")
        .annotate(t=Max("submitted_at"))
        .values_list("user_id", "t")
    )
    fold(
        LessonCompletion.objects.filter(user_id__in=user_ids)
        .values("user_id")
        .annotate(t=Max("completed_at"))
        .values_list("user_id", "t")
    )
    fold(
        ActivityProgress.objects.filter(user_id__in=user_ids)
        .values("user_id")
        .annotate(t=Max("started_at"))
        .values_list("user_id", "t")
    )
    return latest


def _lesson_title(activity: Activity) -> str:
    node = activity.content_node
    if node.kind == ContentNode.Kind.SUBTOPIC and node.parent is not None:
        return node.parent.title
    return node.title


def _course_title(version: CourseVersion) -> str:
    return version.root_node.title if version.root_node else version.course.slug


def attempt_rows(user, activity: Activity) -> list[dict[str, Any]]:
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


def sim_rows(user) -> dict[int, dict[str, Any]]:
    """A learner's practice tickets by activity: each session with its score, so a
    trainer can see how it went and open the transcript."""
    from apps.bot_sim.models import SimSession

    out: dict[int, dict[str, Any]] = {}
    for s in SimSession.objects.filter(user=user, preview=False).order_by("started_at", "id"):
        entry = out.setdefault(s.activity_id, {"sessions": [], "best_raw": None})
        result = s.result or {}
        raw = (result.get("score") or {}).get("raw")
        entry["sessions"].append(
            {
                "id": s.id,
                "state": s.state,
                "started_at": s.started_at.isoformat(),
                "raw": raw,
                "passed": result.get("passed"),
                "needs_review": bool(result.get("needs_review")),
                "reasons": result.get("review_reasons", []),
                "repeated": s.repeated,
                "abandon_reason": s.abandon_reason,
                "skip_reason": s.skip_reason,
            }
        )
        if raw is not None and (entry["best_raw"] is None or raw > entry["best_raw"]):
            entry["best_raw"] = raw
    for entry in out.values():
        scored = [t["raw"] for t in entry["sessions"] if t["state"] == "finished" and t["raw"]]
        entry["finished"] = len(scored)
        entry["average_raw"] = round(sum(scored) / len(scored), 2) if scored else None
        entry["skips"] = sum(1 for t in entry["sessions"] if t["abandon_reason"] == "skipped")
    return out


def rated_rows(user) -> dict[int, dict[str, Any]]:
    """A learner's mentor-rated simulations by activity (trainer's view)."""
    from apps.manual_sim import reporting as manual

    return manual.for_trainer(user)


def _sim_for(sims: dict[int, dict[str, Any]], activity: Activity) -> dict[str, Any] | None:
    """The practice tickets of a learner for one activity, with the quota they are working to."""
    if activity.activity_type != "bot_sim":
        return None
    from apps.activities import bot_sim as cfg

    mine = sims.get(activity.id) or {
        "sessions": [], "best_raw": None, "finished": 0, "average_raw": None, "skips": 0,
    }  # fmt: skip
    return {**mine, "required": cfg.required_tickets(activity.config)}


def watch_row(watch: VideoWatch | None, activity: Activity) -> dict[str, Any] | None:
    """How much of a video was watched, and anything a trainer should look at.
    `None` for every other kind of activity."""
    if activity.activity_type != "video":
        return None
    if video.is_self_reported(activity.config):
        # Nothing to measure: the learner said so (the activity's state tells whether).
        return {
            "watched_fraction": None,
            "needs_review": False,
            "reasons": [],
            "fidelity": "self_reported",
        }
    if watch is None:
        return {"watched_fraction": 0.0, "needs_review": False, "reasons": [], "fidelity": None}
    return {
        "watched_fraction": (
            round(min(watch.credited_seconds / watch.duration, 1.0), 4) if watch.duration else 0.0
        ),
        "needs_review": watch.needs_review,
        "reasons": watching.review_text(watch.review_reasons),
        "fidelity": watch.fidelity,
    }


def learner_detail(user) -> dict[str, Any]:
    """One learner: for each course they've touched, lessons done and every
    completable activity with its state and (for quizzes) every attempt."""
    progress_by_activity = {
        p.activity_id: p
        for p in ActivityProgress.objects.filter(user=user).select_related("activity")
    }
    version_ids = set(
        ActivityProgress.objects.filter(user=user).values_list(
            "activity__content_node__course_version_id", flat=True
        )
    ) | set(
        LessonCompletion.objects.filter(user=user).values_list("node__course_version_id", flat=True)
    )
    versions = CourseVersion.objects.filter(pk__in=version_ids).select_related(
        "root_node", "course"
    )
    # A lesson awaiting a mentor's rating is not counted as done.
    done_lessons = set(
        LessonCompletion.objects.filter(user=user, provisional=False).values_list(
            "node_id", flat=True
        )
    )
    watches = {w.activity_id: w for w in VideoWatch.objects.filter(user=user)}
    sims = sim_rows(user)
    rated = rated_rows(user)
    courses = []
    for version in versions.order_by("course_id", "-version"):
        lessons_total = ContentNode.objects.filter(
            course_version=version, kind=ContentNode.Kind.TOPIC
        ).count()
        lessons_done = ContentNode.objects.filter(
            course_version=version, kind=ContentNode.Kind.TOPIC, pk__in=done_lessons
        ).count()
        activities = []
        for activity in (
            Activity.objects.filter(content_node__course_version=version)
            .select_related("content_node__parent")
            .order_by("content_node__order", "order", "id")
        ):
            if not is_completable(activity.activity_type, activity.config):
                continue
            row = progress_by_activity.get(activity.id)
            scored = activity.activity_type in SCORED_TYPES
            attempts = attempt_rows(user, activity) if scored else []
            activities.append(
                {
                    "id": activity.id,
                    "title": activity.title,
                    "type": activity.activity_type,
                    "lesson": _lesson_title(activity),
                    "required": activity.is_required,
                    "state": row.state if row else "not_started",
                    "scored": scored,
                    "best_score": max((a["score"] for a in attempts), default=None),
                    "attempts": attempts,
                    "max_attempts": activity.max_attempts,
                    "watch": watch_row(watches.get(activity.id), activity),
                    "sim": _sim_for(sims, activity),
                    "rated": rated.get(activity.id)
                    if activity.activity_type == "manual_sim"
                    else None,
                }
            )
        courses.append(
            {
                "course_id": version.course_id,
                "title": _course_title(version),
                "version": version.version,
                "state": version.state,
                "lessons_total": lessons_total,
                "lessons_completed": lessons_done,
                "activities": activities,
            }
        )
    return {
        "id": user.pk,
        "name": display_name(user),
        "email": user.email,
        "employee_id": user.employee_id,
        "courses": courses,
    }


def quiz_rows(course_id: int | None = None) -> list[dict[str, Any]]:
    """Every scored activity in a published version, with how learners did."""
    activities = (
        Activity.objects.filter(
            activity_type__in=SCORED_TYPES,
            content_node__course_version__state=CourseVersion.State.PUBLISHED,
        )
        .select_related(
            "content_node__parent",
            "content_node__course_version__root_node",
            "content_node__course_version__course",
        )
        .order_by("content_node__course_version__course_id", "id")
    )
    if course_id is not None:
        activities = activities.filter(content_node__course_version__course_id=course_id)
    found = list(activities)
    ids = [a.id for a in found]
    best: dict[int, dict[int, float]] = defaultdict(dict)
    for activity_id, user_id, score in ActivityAttempt.objects.filter(
        activity_id__in=ids
    ).values_list("activity_id", "user_id", "score"):
        best[activity_id][user_id] = max(score, best[activity_id].get(user_id, 0.0))
    states: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for activity_id, state in ActivityProgress.objects.filter(activity_id__in=ids).values_list(
        "activity_id", "state"
    ):
        states[activity_id][state] += 1
    rows = []
    for a in found:
        scores = list(best[a.id].values())
        version = a.content_node.course_version
        rows.append(
            {
                "id": a.id,
                "title": a.title,
                "course": _course_title(version),
                "course_id": version.course_id,
                "version": version.version,
                "lesson": _lesson_title(a),
                "required": a.is_required,
                "learners": len(scores),
                "passed": states[a.id]["completed"],
                "not_passed": states[a.id]["exhausted"],
                "in_progress": states[a.id]["started"],
                "average_best_score": sum(scores) / len(scores) if scores else None,
            }
        )
    return rows


def quiz_detail(activity: Activity) -> dict[str, Any]:
    rows = []
    progress = {
        p.user_id: p
        for p in ActivityProgress.objects.filter(activity=activity).select_related("user")
    }
    attempts_by_user: dict[int, list[ActivityAttempt]] = defaultdict(list)
    for a in (
        ActivityAttempt.objects.filter(activity=activity).select_related("user").order_by("number")
    ):
        attempts_by_user[a.user_id].append(a)
    users = {a[0].user_id: a[0].user for a in attempts_by_user.values()}
    users.update({uid: p.user for uid, p in progress.items()})
    for uid, user in users.items():
        tries = attempts_by_user.get(uid, [])
        rows.append(
            {
                "user_id": uid,
                "name": display_name(user),
                "email": user.email,
                "state": progress[uid].state if uid in progress else "not_started",
                "attempts": len(tries),
                "best_score": max((t.score for t in tries), default=None),
                "last_score": tries[-1].score if tries else None,
                "last_attempt_at": tries[-1].submitted_at.isoformat() if tries else None,
            }
        )
    rows.sort(key=lambda r: (str(r["name"]).lower(), r["user_id"]))
    version = activity.content_node.course_version
    return {
        "id": activity.id,
        "title": activity.title,
        "course": _course_title(version),
        "version": version.version,
        "lesson": _lesson_title(activity),
        "max_attempts": activity.max_attempts,
        "learners": rows,
    }


def export_rows(course_id: int | None = None):
    """One row per attempt (quizzes, practice tickets, mentor ratings): the spreadsheet a manager
    asks for."""
    attempts = ActivityAttempt.objects.select_related(
        "user",
        "activity__content_node__course_version__root_node",
        "activity__content_node__course_version__course",
    ).order_by(
        "activity__content_node__course_version__course_id", "activity_id", "user_id", "number"
    )
    if course_id is not None:
        attempts = attempts.filter(activity__content_node__course_version__course_id=course_id)
    for a in attempts.iterator():
        version = a.activity.content_node.course_version
        kind = a.activity.activity_type
        scored_out_of_five = kind in ("bot_sim", "manual_sim")
        yield [
            a.user.email,
            display_name(a.user),
            a.user.employee_id or "",
            _course_title(version),
            version.version,
            a.activity.title,
            a.number,
            # Practice tickets and mentor ratings are scored out of 5, never as a percent.
            "" if scored_out_of_five else round(a.score * 100),
            "Passed" if a.passed else "Not passed",
            a.submitted_at.isoformat(),
            {"bot_sim": "Practice ticket", "manual_sim": "Mentor-rated"}.get(kind, "Quiz"),
            round(a.score * 5, 2) if scored_out_of_five else "",
        ]
