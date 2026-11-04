"""Recording that a learner watched (part of) a video — and deciding, on the
server, whether that adds up to having watched it.

The browser sends a *heartbeat* every few seconds: which stretches it played,
where it is now, how fast. `record_watch` believes only as much of that as real
server-side time allows (the bucket in `watch.py`), never twice, never for
skipped sections, and it — not the browser — marks the activity complete.

What this does and does not do (stated plainly, because it matters):
  * It makes bypassing hard: scrubbing to the end, forged or replayed requests,
    several tabs at once all earn no more than genuine playback would.
  * Finishing a video costs real time: at least about its length divided by the
    credited speed.
  * It cannot tell whether a person was paying attention.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.activities import video
from apps.activities.registry import get_type
from apps.catalog.models import Activity

from . import services, watch
from .models import ActivityProgress, VideoWatch

SESSION_OVERLAP_SECONDS = 30
# An honest player reports ~15 s per heartbeat. Far more than this in one go is
# what a forged "whole video" request looks like.
BURST_SECONDS = 40.0
MAX_SEQ = 10**9
MAX_YOUTUBE_SECONDS = 6 * 3600.0

# What `needs_review` can say. Shown to trainers in plain words by the console.
REASONS = {
    "best_effort": "Watched in an embedded player (less precise)",
    "over_budget": "Reported more watching than real time allows",
    "multiple_sessions": "Played in several tabs or devices at once",
    "mostly_hidden": "Mostly watched with the tab in the background",
    "too_fast": "Played faster than the credited speed",
    "burst": "Reported a long stretch of watching all at once",
    "duration_changed": "The video's length changed during playback",
}


class BadWatch(services.ProgressError):
    status_code = 400


def _now():
    return timezone.now()


def _video_activity(activity_id: int) -> Activity:
    activity = services._activity(activity_id)  # published, exists, completable
    descriptor = get_type(activity.activity_type)
    if descriptor is None or descriptor.completion != "tracked":
        raise services.NotCompletable("This activity isn’t a video.")
    if video.is_self_reported(activity.config):
        raise services.NotCompletable("This video can’t be tracked; it’s confirmed by the learner.")
    return activity


def _duration(activity: Activity, claimed: float | None, current: float) -> float:
    """The length the server believes in: an upload's is known; a YouTube
    video's is whatever the player reports, held fixed once set."""
    if video.source_of(activity.config) == video.UPLOAD:
        asset = video._ready_asset(activity.config)
        return float(asset.duration_seconds or 0) if asset else 0.0
    if current > 0:
        return current
    return claimed or 0.0


def _state(
    user, row: VideoWatch | None, activity: Activity, *, accepted: float = 0.0
) -> dict[str, Any]:
    needed = video.threshold(activity.config)
    duration = row.duration if row else 0.0
    if duration <= 0 and video.source_of(activity.config) == video.UPLOAD:
        asset = video._ready_asset(activity.config)
        duration = float(asset.duration_seconds or 0) if asset else 0.0
    credited = row.credited_seconds if row else 0.0
    progress = ActivityProgress.objects.filter(user=user, activity=activity).first()
    return {
        "state": progress.state if progress else None,
        "completed": bool(row and row.completed_at),
        "watched_fraction": round(min(credited / duration, 1.0), 4) if duration else 0.0,
        "needed_fraction": needed,
        "position": round(row.last_position, 2) if row else 0.0,
        "duration": duration or None,
        "accepted_seconds": round(accepted, 2),
    }


def watch_state(user, activity_id: int) -> dict[str, Any]:
    """Where the learner is in this video (for resuming and the progress line)."""
    activity = _video_activity(activity_id)
    services._assert_lesson_open(user, services._lesson_of(activity))
    row = VideoWatch.objects.filter(user=user, activity=activity).first()
    return _state(user, row, activity)


def _parse(raw: Any, activity: Activity) -> dict[str, Any]:
    """The heartbeat, validated. Anything off → `BadWatch`, and nothing changes."""
    if not isinstance(raw, dict):
        raise BadWatch("That update wasn’t understood.")
    try:
        session = uuid.UUID(str(raw.get("session_id")))
        seq = raw.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq <= MAX_SEQ:
            raise watch.BadClaim("seq")
        parsed: dict[str, Any] = {
            "session": session,
            "seq": seq,
            "rate": watch.number(raw.get("rate", 1), low=0.05, high=16),
            "hidden": watch.number(raw.get("hidden_seconds", 0), low=0, high=3600),
            "position": watch.number(raw.get("position", 0), low=0, high=10**6),
            "raw_ranges": raw.get("ranges", []),
            "claimed_duration": None,
        }
        if video.source_of(activity.config) == video.YOUTUBE:
            parsed["claimed_duration"] = watch.number(
                raw.get("duration"), low=1, high=MAX_YOUTUBE_SECONDS
            )
    except (ValueError, watch.BadClaim) as exc:
        raise BadWatch("That update wasn’t understood.") from exc
    return parsed


@transaction.atomic
def record_watch(user, activity_id: int, raw: Any) -> dict[str, Any]:
    activity = _video_activity(activity_id)
    services._assert_lesson_open(user, services._lesson_of(activity))
    beat = _parse(raw, activity)

    now = _now()
    row, _ = VideoWatch.objects.select_for_update().get_or_create(
        user=user,
        activity=activity,
        defaults={"fidelity": _fidelity(activity)},
    )

    # Done is done: nothing a later request says can change it.
    if row.completed_at is not None:
        return _state(user, row, activity)

    # --- replay and ordering -------------------------------------------------
    if beat["session"] == row.session_id:
        if beat["seq"] == row.last_seq and row.last_reply:
            return row.last_reply  # a network retry: same answer, no effect
        if beat["seq"] < row.last_seq:
            return _state(user, row, activity)  # late or replayed: ignore
    elif (
        row.last_heartbeat_at is not None
        and (now - row.last_heartbeat_at).total_seconds() < SESSION_OVERLAP_SECONDS
    ):
        row.session_overlaps += 1  # another tab/device was playing a moment ago

    duration = _duration(activity, beat["claimed_duration"], row.duration)
    if duration < 1:
        raise BadWatch("That update wasn’t understood.")
    if row.duration and abs(row.duration - duration) > 1.0:
        _flag(row, "duration_changed")
    try:
        claimed = watch.clean_ranges(beat["raw_ranges"], duration)
    except watch.BadClaim as exc:
        raise BadWatch("That update wasn’t understood.") from exc

    # --- the bucket: credit only what real time allows ----------------------
    cap = video.credited_rate(activity.config)
    if row.budget_at is None:
        level = watch.INITIAL_BUDGET
        elapsed = 0.0
        row.first_heartbeat_at = now
    else:
        level = row.budget
        elapsed = (now - row.budget_at).total_seconds()
    level = watch.refill(level, elapsed, cap)

    accepted: list[watch.Interval] = []
    refused = 0.0
    too_fast = beat["rate"] > cap + watch.RATE_SLACK
    credited_before = watch.from_lists(row.ranges)
    new = watch.subtract(claimed, credited_before)
    if too_fast:
        refused = watch.measure(new)
        row.fast_heartbeats += 1
    else:
        accepted, refused = watch.trim_to_budget(new, level)
    got = watch.measure(accepted)

    row.ranges = watch.as_lists(watch.merge([*credited_before, *accepted]))
    row.credited_seconds = watch.measure(watch.from_lists(row.ranges))
    row.budget = level - got
    row.budget_at = now
    row.rejected_seconds += refused
    row.longest_credit = max(row.longest_credit, got)
    row.duration = duration
    row.last_position = min(beat["position"], duration)
    gap = (now - row.last_heartbeat_at).total_seconds() if row.last_heartbeat_at else 0.0
    row.hidden_seconds += min(beat["hidden"], gap + 1.0)
    row.heartbeats += 1
    row.last_heartbeat_at = now
    row.session_id = beat["session"]
    row.last_seq = beat["seq"]

    _review(row)

    # --- the server decides ---------------------------------------------------
    if row.credited_seconds >= video.threshold(activity.config) * duration:
        _complete(row, activity, now)

    reply = _state(user, row, activity, accepted=got)
    row.last_reply = reply
    row.save()
    return reply


def _fidelity(activity: Activity) -> str:
    return "verified" if video.source_of(activity.config) == video.UPLOAD else "best_effort"


def _flag(row: VideoWatch, reason: str) -> None:
    row.needs_review = True
    if reason not in row.review_reasons:
        row.review_reasons = [*row.review_reasons, reason]


def _review(row: VideoWatch) -> None:
    """Mark anything unusual for a trainer's eye. Never blocks the learner."""
    if row.rejected_seconds > max(10.0, 0.25 * row.credited_seconds):
        _flag(row, "over_budget")
    if row.session_overlaps >= 2:
        _flag(row, "multiple_sessions")
    if row.credited_seconds > 30 and row.hidden_seconds > 0.5 * row.credited_seconds:
        _flag(row, "mostly_hidden")
    if row.fast_heartbeats >= 3:
        _flag(row, "too_fast")
    if row.longest_credit > BURST_SECONDS:
        _flag(row, "burst")


def _complete(row: VideoWatch, activity: Activity, now) -> None:
    row.completed_at = now
    if row.fidelity == "best_effort":
        _flag(row, "best_effort")
    progress, _ = ActivityProgress.objects.get_or_create(
        user=row.user, activity=activity, defaults={"started_at": now}
    )
    if progress.state != ActivityProgress.State.COMPLETED:
        progress.state = ActivityProgress.State.COMPLETED
        progress.completed_at = now
        progress.save(update_fields=["state", "completed_at"])


def review_text(reasons: list[str]) -> list[str]:
    return [REASONS.get(r, r) for r in reasons]
