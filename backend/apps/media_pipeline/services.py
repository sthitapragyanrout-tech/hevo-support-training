"""Uploading a video, turning it into something every browser plays, and
recovering when a worker or a message goes missing.

The pipeline, in order:

  upload    validate (size, type, ffprobe, limits, free space) → store the
            original under `originals/` → row `uploaded` → queue the task
  process   claim (compare-and-set) → transcode into a private temp dir →
            verify the *output* → atomically move into `videos/` + `posters/`
            → commit `ready` → only then delete the original
  recover   re-queue lost work, release dead leases, fail what keeps failing,
            clear debris, finish deferred deletions

Everything a person reads (`MediaAsset.error`, `MediaError.message`) is a plain
sentence; ffmpeg's own output goes to the log and nowhere else.
"""

from __future__ import annotations

import errno
import hashlib
import logging
import os
import shutil
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from . import ffmpeg
from .errors import (
    LimitExceeded,
    MediaError,
    NoSpace,
    NotAVideo,
    PermanentError,
    TooLarge,
    TooManyUnfinished,
    TransientError,
)
from .models import MediaAsset

log = logging.getLogger(__name__)

MB = 1024 * 1024
ORIGINALS, VIDEOS, POSTERS, TMP = "originals", "videos", "posters", "tmp"
GIVE_UP = "We couldn’t process this video. Try uploading it again, or export it as MP4 first."


# ----------------------------------------------------------------- storage


def media_root() -> Path:
    root = Path(settings.MEDIA_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve(relative: str, *, under: str | None = None) -> Path:
    """The absolute path for a stored relative path, refusing anything that
    would land outside `MEDIA_ROOT` (or outside `under`, a top-level folder)."""
    root = media_root().resolve()
    path = (root / relative).resolve()
    base = (root / under).resolve() if under else root
    if base not in path.parents:
        raise ValueError("path escapes the media folder")
    return path


def max_upload_bytes() -> int:
    return int(settings.MEDIA_MAX_UPLOAD_MB * MB)


def limits() -> dict[str, Any]:
    """The limits an uploader is told about (so the Studio can check up front)."""
    return {
        "max_upload_mb": settings.MEDIA_MAX_UPLOAD_MB,
        "max_duration_minutes": settings.MEDIA_MAX_DURATION_SECONDS // 60,
        "allowed_extensions": list(settings.MEDIA_ALLOWED_EXTENSIONS),
    }


def _free_bytes() -> int:
    return shutil.disk_usage(media_root()).free


def _assert_free_space(needed_bytes: int) -> None:
    reserve = int(settings.MEDIA_MIN_FREE_MB * MB)
    if _free_bytes() < needed_bytes + reserve:
        raise NoSpace("There isn’t enough storage space right now. Please try again later.")


def _hours(seconds: int) -> str:
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours}-hour" if hours != 1 else "1-hour"
    return f"{seconds // 60}-minute"


def _check_limits(info: ffmpeg.VideoInfo) -> None:
    if info.duration < 1:
        raise LimitExceeded("That video is too short to use (under a second).")
    if info.duration > settings.MEDIA_MAX_DURATION_SECONDS:
        raise LimitExceeded(
            f"This video is longer than the {_hours(settings.MEDIA_MAX_DURATION_SECONDS)} limit."
        )
    if info.width * info.height > settings.MEDIA_MAX_PIXELS:
        raise LimitExceeded("This video’s picture size is larger than we can handle (4K maximum).")


# ------------------------------------------------------------------ upload


def _extension(name: str) -> str:
    ext = Path(name or "").suffix.lower().lstrip(".")
    if ext not in settings.MEDIA_ALLOWED_EXTENSIONS:
        allowed = ", ".join(e.upper() for e in settings.MEDIA_ALLOWED_EXTENSIONS)
        raise NotAVideo(f"We can’t use that kind of file. Upload one of: {allowed}.")
    return ext


def _display_name(name: str) -> str:
    cleaned = "".join(ch for ch in os.path.basename(name or "video") if ch.isprintable())
    return cleaned.strip()[:255] or "video"


def _assert_unfinished_cap(user) -> None:
    unfinished = MediaAsset.objects.filter(
        uploaded_by=user,
        status__in=[MediaAsset.Status.UPLOADED, MediaAsset.Status.PROCESSING],
    ).count()
    if unfinished >= settings.MEDIA_MAX_UNFINISHED_PER_USER:
        raise TooManyUnfinished(
            "You have several videos still processing. Wait for one to finish, then try again."
        )


def create_asset(upload, user) -> MediaAsset:
    """Store an uploaded video and queue its processing. Raises `MediaError`
    (with a plain message and an HTTP status) for anything we won't accept; a
    rejected upload leaves nothing on disk."""
    ext = _extension(upload.name)
    limit = max_upload_bytes()
    if upload.size is not None and upload.size > limit:
        raise TooLarge(f"That file is larger than the {settings.MEDIA_MAX_UPLOAD_MB:g} MB limit.")
    _assert_unfinished_cap(user)
    _assert_free_space(int((upload.size or 0) * 2))

    uid = uuid.uuid4()
    relative = f"{ORIGINALS}/{uid}.{ext}"
    dest = resolve(relative)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    written = 0
    try:
        with open(part, "wb") as handle:
            for chunk in upload.chunks():
                written += len(chunk)
                if written > limit:
                    raise TooLarge(
                        f"That file is larger than the {settings.MEDIA_MAX_UPLOAD_MB:g} MB limit."
                    )
                handle.write(chunk)
        info = ffmpeg.probe(part)
        _check_limits(info)
        os.replace(part, dest)
    except OSError as exc:
        _discard(part, dest)
        if exc.errno == errno.ENOSPC:
            raise NoSpace("There isn’t enough storage space right now.") from exc
        log.exception("Could not store an upload")
        raise MediaError("We couldn’t save that file. Please try again.", status_code=500) from exc
    except BaseException:
        _discard(part, dest)
        raise

    asset = MediaAsset.objects.create(
        uuid=uid,
        uploaded_by=user,
        original_name=_display_name(upload.name),
        size_bytes=written,
        duration_seconds=info.duration,
        width=info.width,
        height=info.height,
        original_path=relative,
    )
    transaction.on_commit(lambda: enqueue(asset.pk))
    return asset


def _discard(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.warning("Could not remove %s", path.name)


# ------------------------------------------------------------------- queue


def enqueue(asset_id: int, *, countdown: int = 0) -> bool:
    """Ask a worker to process the asset. The database, not the broker, is the
    record of what is waiting: if the broker is down the asset simply stays
    `uploaded` and the sweeper queues it again. Returns whether it was sent."""
    from .tasks import transcode_asset

    MediaAsset.objects.filter(pk=asset_id).update(enqueued_at=timezone.now())
    try:
        transcode_asset.apply_async((asset_id,), countdown=countdown)
    except Exception:
        # Whatever the broker throws (kombu's filesystem transport raises an
        # UnboundLocalError on an unwritable folder, for one) must not lose the
        # upload. Run inline (tests, eager mode) the task's own errors surface.
        if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            raise
        log.warning(
            "Could not queue media asset %s; the sweeper will retry", asset_id, exc_info=True
        )
        return False
    return True


def _transcode_timeout(duration: float | None) -> int:
    wanted = max(120, int((duration or 0) * 4))
    return min(wanted, settings.MEDIA_TRANSCODE_TIMEOUT_SECONDS)


# ----------------------------------------------------------------- process


def claim(asset_id: int) -> MediaAsset | None:
    """Take the asset for processing, or `None` if it is not waiting (already
    claimed, ready, failed, or gone). A single conditional UPDATE, so two
    workers holding the same message cannot both proceed."""
    asset = MediaAsset.objects.filter(pk=asset_id).first()
    if asset is None or asset.status != MediaAsset.Status.UPLOADED:
        return None
    now = timezone.now()
    lease = now + timedelta(
        seconds=_transcode_timeout(asset.duration_seconds) + settings.MEDIA_LEASE_SLACK_SECONDS
    )
    taken = MediaAsset.objects.filter(pk=asset_id, status=MediaAsset.Status.UPLOADED).update(
        status=MediaAsset.Status.PROCESSING,
        attempts=F("attempts") + 1,
        claimed_at=now,
        lease_expires_at=lease,
        error="",
    )
    return MediaAsset.objects.get(pk=asset_id) if taken == 1 else None


def process_asset(asset_id: int) -> str:
    """Run one claimed transcode to its end. Returns what happened:
    "skipped", "ready", "retry", "failed" or "lost" (the claim expired and
    someone else owns the asset now)."""
    asset = claim(asset_id)
    if asset is None:
        return "skipped"
    attempt = asset.attempts
    work = media_root() / TMP / f"{asset.pk}-{attempt}"
    try:
        _assert_free_space(asset.size_bytes)
        work.mkdir(parents=True, exist_ok=True)
        outcome = _transcode_and_publish(asset, attempt, work)
    except TransientError as exc:
        return _release(asset, attempt, exc.message)
    except NoSpace as exc:  # may pass once space is freed
        return _release(asset, attempt, exc.message)
    except (PermanentError, MediaError) as exc:
        return _fail(asset, attempt, exc.message, retryable=False)
    except MemoryError:
        return _release(asset, attempt, "The server ran low on memory while processing this video.")
    except OSError as exc:
        log.exception("Disk or system error while processing asset %s", asset.pk)
        return _release(asset, attempt, ffmpeg._os_message(exc))
    except Exception:
        log.exception("Unexpected error while processing asset %s", asset.pk)
        return _release(asset, attempt, GIVE_UP)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if outcome == "ready":
        purge_original(asset.pk)
    return outcome


def _transcode_and_publish(asset: MediaAsset, attempt: int, work: Path) -> str:
    if not asset.original_path:
        raise PermanentError("The original upload is no longer available. Please upload it again.")
    try:
        source = resolve(asset.original_path, under=ORIGINALS)
    except ValueError as exc:
        raise PermanentError(GIVE_UP) from exc
    if not source.is_file():
        raise PermanentError("The original upload is no longer available. Please upload it again.")

    # Trust nothing from the upload step: look at the file again.
    source_info = ffmpeg.probe(source)
    _check_limits(source_info)

    timeout = _transcode_timeout(source_info.duration)
    cap = int(settings.MEDIA_MAX_OUTPUT_MB * MB)
    encoded = work / "out.mp4"
    still = work / "poster.jpg"
    ffmpeg.transcode(source, encoded, timeout=timeout, max_output_bytes=cap)
    output_info = _verify_output(encoded, source_info, cap)
    ffmpeg.poster(encoded, still, at_seconds=output_info.duration * 0.1)
    if not still.is_file() or still.stat().st_size == 0:
        raise TransientError(GIVE_UP)
    digest = _sha256(encoded)
    size = encoded.stat().st_size

    video_rel = f"{VIDEOS}/{asset.uuid}.mp4"
    poster_rel = f"{POSTERS}/{asset.uuid}.jpg"
    video_dest, poster_dest = resolve(video_rel), resolve(poster_rel)
    video_dest.parent.mkdir(parents=True, exist_ok=True)
    poster_dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(encoded, video_dest)  # atomic: a reader never sees half a file
        os.replace(still, poster_dest)
        with transaction.atomic():
            updated = MediaAsset.objects.filter(
                pk=asset.pk, status=MediaAsset.Status.PROCESSING, attempts=attempt
            ).update(
                status=MediaAsset.Status.READY,
                video_path=video_rel,
                poster_path=poster_rel,
                output_size_bytes=size,
                output_sha256=digest,
                duration_seconds=output_info.duration,
                width=output_info.width,
                height=output_info.height,
                ready_at=timezone.now(),
                error="",
                retryable=False,
                claimed_at=None,
                lease_expires_at=None,
            )
    except BaseException:
        # Not published: leave no orphaned file in a folder the player reads from.
        _discard(video_dest, poster_dest)
        raise
    return "ready" if updated else "lost"


def _verify_output(path: Path, source: ffmpeg.VideoInfo, cap: int) -> ffmpeg.VideoInfo:
    """The converted file must really be a playable, complete video before the
    original is allowed to go."""
    if not path.is_file() or path.stat().st_size == 0:
        raise TransientError(GIVE_UP)
    if path.stat().st_size > cap:
        raise PermanentError("The converted video came out larger than we allow.")
    try:
        info = ffmpeg.probe(path)
    except NotAVideo as exc:
        raise TransientError(GIVE_UP) from exc
    if info.codec != "h264" or info.width > 1280:
        raise TransientError(GIVE_UP)
    if abs(info.duration - source.duration) > max(1.0, source.duration * 0.02):
        # A truncated encode (full disk, killed process) is the usual cause.
        raise TransientError(GIVE_UP)
    # The index can be intact while the data behind it is cut short, so the
    # whole file is decoded once: any error means it must not replace the original.
    ffmpeg.check_decodes(path, timeout=_transcode_timeout(source.duration))
    return info


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _release(asset: MediaAsset, attempt: int, message: str) -> str:
    """A problem that may pass: queue it again, until the attempts run out."""
    if attempt >= settings.MEDIA_MAX_ATTEMPTS:
        return _fail(asset, attempt, message, retryable=True)
    changed = MediaAsset.objects.filter(
        pk=asset.pk, status=MediaAsset.Status.PROCESSING, attempts=attempt
    ).update(
        status=MediaAsset.Status.UPLOADED,
        claimed_at=None,
        lease_expires_at=None,
        error="",
    )
    if not changed:
        return "lost"
    enqueue(asset.pk, countdown=settings.MEDIA_RETRY_BACKOFF_SECONDS * attempt)
    return "retry"


def _fail(
    asset: MediaAsset,
    attempt: int,
    message: str,
    *,
    retryable: bool,
    from_status: str = MediaAsset.Status.PROCESSING,
) -> str:
    changed = MediaAsset.objects.filter(pk=asset.pk, status=from_status, attempts=attempt).update(
        status=MediaAsset.Status.FAILED,
        error=message[:255],
        retryable=retryable,
        claimed_at=None,
        lease_expires_at=None,
    )
    return "failed" if changed else "lost"


def purge_original(asset_id: int) -> bool:
    """Delete the uploaded original of a `ready` asset. Safe by construction:
    only a ready asset, only inside `originals/`, never when originals are kept.
    A failure leaves `original_purged=False` for the sweeper to retry."""
    if settings.MEDIA_KEEP_ORIGINALS:
        return False
    asset = MediaAsset.objects.filter(pk=asset_id, status=MediaAsset.Status.READY).first()
    if asset is None or asset.original_purged:
        return False
    if asset.original_path:
        try:
            path = resolve(asset.original_path, under=ORIGINALS)
            path.unlink(missing_ok=True)
        except (OSError, ValueError):
            log.warning("Could not delete the original of asset %s; will retry", asset.pk)
            return False
    MediaAsset.objects.filter(pk=asset.pk).update(original_purged=True, original_path="")
    return True


# ---------------------------------------------------------------- recovery


def recover_stuck_assets() -> dict[str, int]:
    """Put right whatever a crash, a lost message or a full disk left behind.
    Safe to run any time, from any number of places."""
    now = timezone.now()
    stale = now - timedelta(seconds=settings.MEDIA_REQUEUE_AFTER_SECONDS)
    counts = {"requeued": 0, "released": 0, "failed": 0, "debris": 0, "purged": 0}

    # A worker died holding the asset: its lease ran out.
    for asset in MediaAsset.objects.filter(
        status=MediaAsset.Status.PROCESSING, lease_expires_at__lt=now
    ):
        if asset.attempts >= settings.MEDIA_MAX_ATTEMPTS:
            if _fail(asset, asset.attempts, GIVE_UP, retryable=True) == "failed":
                counts["failed"] += 1
        elif MediaAsset.objects.filter(
            pk=asset.pk, status=MediaAsset.Status.PROCESSING, lease_expires_at__lt=now
        ).update(
            status=MediaAsset.Status.UPLOADED,
            claimed_at=None,
            lease_expires_at=None,
            enqueued_at=None,
        ):
            counts["released"] += 1

    # Waiting with no message in flight (never sent, lost, or the broker was down).
    for asset in MediaAsset.objects.filter(status=MediaAsset.Status.UPLOADED).filter(
        Q(enqueued_at__isnull=True) | Q(enqueued_at__lt=stale)
    ):
        if asset.attempts >= settings.MEDIA_MAX_ATTEMPTS:
            failed = _fail(
                asset,
                asset.attempts,
                GIVE_UP,
                retryable=True,
                from_status=MediaAsset.Status.UPLOADED,
            )
            if failed == "failed":
                counts["failed"] += 1
        elif enqueue(asset.pk):
            counts["requeued"] += 1

    counts["debris"] = _clear_debris(now)
    for asset_id in MediaAsset.objects.filter(
        status=MediaAsset.Status.READY, original_purged=False
    ).values_list("pk", flat=True):
        if purge_original(asset_id):
            counts["purged"] += 1
    return counts


def _clear_debris(now) -> int:
    """Remove temp folders no live worker owns, and half-written uploads."""
    cleared = 0
    age = settings.MEDIA_DEBRIS_MIN_AGE_SECONDS
    tmp = media_root() / TMP
    if tmp.is_dir():
        for folder in tmp.iterdir():
            asset_id = folder.name.split("-", 1)[0]
            live = (
                asset_id.isdigit()
                and MediaAsset.objects.filter(
                    pk=int(asset_id),
                    status=MediaAsset.Status.PROCESSING,
                    lease_expires_at__gt=now,
                ).exists()
            )
            if not live and now.timestamp() - folder.stat().st_mtime >= age:
                shutil.rmtree(folder, ignore_errors=True)
                cleared += 1
    originals = media_root() / ORIGINALS
    if originals.is_dir():
        for part in originals.glob("*.part"):
            if now.timestamp() - part.stat().st_mtime > 3600:
                _discard(part)
                cleared += 1
    return cleared


def retry_asset(asset: MediaAsset) -> MediaAsset:
    """Queue a failed asset again (the author pressed Retry)."""
    original_exists = False
    if asset.original_path:
        try:
            original_exists = resolve(asset.original_path, under=ORIGINALS).is_file()
        except ValueError:
            original_exists = False
    if asset.status != MediaAsset.Status.FAILED or not asset.retryable or not original_exists:
        raise MediaError("This video can’t be retried. Please upload it again.", status_code=409)
    MediaAsset.objects.filter(pk=asset.pk, status=MediaAsset.Status.FAILED).update(
        status=MediaAsset.Status.UPLOADED, attempts=0, error="", retryable=False, enqueued_at=None
    )
    transaction.on_commit(lambda: enqueue(asset.pk))
    asset.refresh_from_db()
    return asset
