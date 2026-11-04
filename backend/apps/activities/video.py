"""The video activity: where its picture comes from, what a learner may see of
its configuration, and when it counts as something a learner can finish.

Three sources, all played inside the lesson:

  upload   a file the author uploaded (a `MediaAsset`), transcoded by the worker
           and streamed by this server — the one source whose watching the
           server can verify closely
  youtube  an embedded YouTube player, tracked on a best-effort basis
  drive    a Google Drive file's embedded preview. Google exposes no playback
           position for it, so watching can't be measured: the learner confirms
           they watched it (like a reading) and trainers see it as self-reported

`config` keys (all validated by the registry's schema; `check_complete` adds
the rules a schema can't express):

  source                "upload" | "youtube" | "drive"
  media_asset           the MediaAsset id (upload)
  youtube_url           a YouTube link (youtube)
  drive_url             a Google Drive share link (drive)
  completion_threshold  fraction of the video that must be watched (default 0.9)
  max_credited_rate     fastest playback speed that still earns credit (default 1)
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

UPLOAD = "upload"
YOUTUBE = "youtube"
DRIVE = "drive"
SOURCES = (UPLOAD, YOUTUBE, DRIVE)

DEFAULT_THRESHOLD = 0.9
MIN_THRESHOLD = 0.5
DEFAULT_RATE = 1.0
MAX_RATE = 2.0

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
    "youtu.be",
}
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_id(url: Any) -> str | None:
    """The 11-character video id in a YouTube link, or None if it isn't one.
    Only YouTube's own hosts are accepted, so a config can never make the
    learner's browser frame some other site."""
    if not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host not in _YOUTUBE_HOSTS:
        return None
    candidate: str | None = None
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif parsed.path == "/watch":
        values = parse_qs(parsed.query).get("v")
        candidate = values[0] if values else None
    else:
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in ("embed", "shorts", "live", "v"):
            candidate = parts[1]
    return candidate if candidate and _YOUTUBE_ID.match(candidate) else None


_DRIVE_ID = re.compile(r"^[A-Za-z0-9_-]{10,128}$")


def drive_id(url: Any) -> str | None:
    """The file id in a Google Drive share link, or None. Only drive.google.com
    is accepted, so a config can never make a learner's browser frame another site.
    Handles /file/d/<id>/view, /file/d/<id>/preview, /open?id=<id>, /uc?id=<id>."""
    if not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if (
        parsed.scheme not in ("http", "https")
        or (parsed.hostname or "").lower() != "drive.google.com"
    ):
        return None
    candidate: str | None = None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 3 and parts[0] == "file" and parts[1] == "d":
        candidate = parts[2]
    elif parts and parts[0] in ("open", "uc"):
        values = parse_qs(parsed.query).get("id")
        candidate = values[0] if values else None
    return candidate if candidate and _DRIVE_ID.match(candidate) else None


def is_self_reported(config: Any) -> bool:
    """Is this video finished by the learner saying so (nothing to measure)?"""
    return source_of(config) == DRIVE


def source_of(config: Any) -> str | None:
    value = config.get("source") if isinstance(config, dict) else None
    return value if value in SOURCES else None


def asset_id(config: Any) -> int | None:
    value = config.get("media_asset") if isinstance(config, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def threshold(config: Any) -> float:
    value = config.get("completion_threshold") if isinstance(config, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return min(max(float(value), MIN_THRESHOLD), 1.0)
    return DEFAULT_THRESHOLD


def credited_rate(config: Any) -> float:
    """The fastest playback speed that still earns watch credit."""
    value = config.get("max_credited_rate") if isinstance(config, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return min(max(float(value), 0.25), MAX_RATE)
    return DEFAULT_RATE


def _ready_asset(config: Any):
    from apps.media_pipeline.models import MediaAsset

    pk = asset_id(config)
    if pk is None:
        return None
    return MediaAsset.objects.filter(pk=pk, status=MediaAsset.Status.READY).first()


def is_playable(config: Any) -> bool:
    """Is there really a video behind this config? Only then can it be watched
    — and so only then can it hold a lesson up."""
    source = source_of(config)
    if source == UPLOAD:
        return _ready_asset(config) is not None
    if source == YOUTUBE:
        return youtube_id(config.get("youtube_url")) is not None
    if source == DRIVE:
        return drive_id(config.get("drive_url")) is not None
    return False


def check_complete(config: Any) -> list[str]:
    """What stops this video being published (empty = it is ready)."""
    source = source_of(config)
    if source is None:
        return ["Choose a video: upload one, or paste a YouTube or Google Drive link."]
    if source == DRIVE:
        if drive_id(config.get("drive_url")) is None:
            return ["Paste a valid Google Drive link (drive.google.com)."]
        return []
    if source == YOUTUBE:
        if youtube_id(config.get("youtube_url")) is None:
            return ["Paste a valid YouTube link (youtube.com or youtu.be)."]
        return []
    from apps.media_pipeline.models import MediaAsset

    pk = asset_id(config)
    if pk is None:
        return ["Upload a video."]
    asset = MediaAsset.objects.filter(pk=pk).first()
    if asset is None:
        return ["The uploaded video can’t be found. Upload it again."]
    if asset.status == MediaAsset.Status.FAILED:
        return ["The video couldn’t be processed. Retry it or upload it again."]
    if asset.status != MediaAsset.Status.READY:
        return ["The video is still processing. Publish once it shows as ready."]
    return []


def learner_view(config: Any) -> dict[str, Any]:
    """What a learner may see: how to play it and how it is tracked. Never a
    file path, an original file name or who uploaded it."""
    source = source_of(config)
    view: dict[str, Any] = {
        "source": source,
        "completion_threshold": threshold(config),
        "max_credited_rate": credited_rate(config),
    }
    if source == YOUTUBE:
        view["youtube_id"] = youtube_id(config.get("youtube_url"))
    elif source == DRIVE:
        view["drive_id"] = drive_id(config.get("drive_url"))
    elif source == UPLOAD:
        asset = _ready_asset(config)
        if asset is not None:
            view.update(
                media_asset=asset.pk,
                media_url=f"/api/v1/media/{asset.pk}/video/",
                poster_url=f"/api/v1/media/{asset.pk}/poster/",
                duration=asset.duration_seconds,
            )
    return view


def authorize_config(config: Any, actor) -> list[str]:
    """Rules about *who* may point a video activity at an uploaded asset: only
    one they uploaded themselves (an administrator may use any)."""
    pk = asset_id(config)
    if pk is None or source_of(config) != UPLOAD:
        return []
    from apps.media_pipeline import access
    from apps.media_pipeline.models import MediaAsset

    asset = MediaAsset.objects.filter(pk=pk).first()
    if asset is None or not access.can_manage(actor, asset):
        return ["That video isn’t available to you. Upload it again."]
    return []
