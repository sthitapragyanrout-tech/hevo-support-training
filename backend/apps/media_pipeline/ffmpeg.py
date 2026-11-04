"""Thin, bounded wrappers around ffprobe and ffmpeg.

Every call has a timeout and runs in its own process group, so a hung or
runaway child is killed with everything it spawned. Their stderr goes to the
log only — callers raise errors with their own plain sentences.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from .errors import NotAVideo, PermanentError, TransientError

log = logging.getLogger(__name__)

_STDERR_TAIL = 2000
# Encoded output is a *fresh* file in a temp directory, so a hostile source can
# only make it big, never wrong; `-fs` below caps the size regardless.
VIDEO_FILTER = "scale='trunc(min(1280,iw)/2)*2':-2"


@dataclass(frozen=True)
class VideoInfo:
    duration: float
    width: int
    height: int
    codec: str
    has_audio: bool


def _niced(cmd: list[str]) -> list[str]:
    """Run ffmpeg at a lower CPU priority, so a conversion can never starve the web
    server or the practice worker on the same machine (`MEDIA_FFMPEG_NICE`, 0 = off)."""
    niceness = getattr(settings, "MEDIA_FFMPEG_NICE", 0)
    if niceness and shutil.which("nice"):
        return ["nice", "-n", str(int(niceness)), *cmd]
    return cmd


def _run(cmd: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """Run to completion or kill the whole process group at `timeout`."""
    process = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(process)
        process.communicate()
        raise
    return subprocess.CompletedProcess(cmd, process.returncode, out, err)


def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # already gone
        process.kill()


def probe(path: Path) -> VideoInfo:
    """What `path` really is, judged by ffprobe — never by its name. Raises
    `NotAVideo` for anything that is not a readable video with a length."""
    cmd = [
        settings.FFPROBE_BIN,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        done = _run(_niced(cmd), timeout=settings.MEDIA_PROBE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        log.warning("ffprobe timed out on %s", path.name)
        raise NotAVideo("We couldn’t read that file. Try exporting it again.") from exc
    except OSError as exc:
        log.exception("ffprobe could not run")
        raise TransientError("Video processing isn’t available right now.") from exc
    if done.returncode != 0:
        log.info("ffprobe rejected %s: %s", path.name, done.stderr[-_STDERR_TAIL:])
        raise NotAVideo("That file doesn’t look like a video we can read.")
    try:
        data = json.loads(done.stdout or "{}")
    except ValueError as exc:
        raise NotAVideo("That file doesn’t look like a video we can read.") from exc

    streams = data.get("streams") or []
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")  # cover art, not video
        ),
        None,
    )
    if video is None:
        raise NotAVideo("That file doesn’t contain a video.")
    try:
        width, height = int(video["width"]), int(video["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NotAVideo("We couldn’t read the size of that video.") from exc
    raw = (data.get("format") or {}).get("duration") or video.get("duration")
    try:
        duration = float(raw)
    except (TypeError, ValueError) as exc:
        raise NotAVideo("We couldn’t work out how long that video is.") from exc
    if not duration > 0 or duration != duration or duration == float("inf"):
        raise NotAVideo("We couldn’t work out how long that video is.")
    if width <= 0 or height <= 0:
        raise NotAVideo("We couldn’t read the size of that video.")
    return VideoInfo(
        duration=duration,
        width=width,
        height=height,
        codec=str(video.get("codec_name") or ""),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def transcode(src: Path, dest: Path, *, timeout: float, max_output_bytes: int) -> None:
    """Re-encode `src` as a web-safe MP4 (H.264/AAC, ≤1280px wide, `faststart`).
    Only the first video stream and first audio stream are kept."""
    cmd = [
        settings.FFMPEG_BIN,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-sn",
        "-dn",
        "-vf",
        VIDEO_FILTER,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-threads",
        "2",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "-fs",
        str(max_output_bytes),
        str(dest),
    ]
    _run_encoder(_niced(cmd), timeout, "transcode")


def poster(src: Path, dest: Path, *, at_seconds: float) -> None:
    """One still frame, for the player's poster."""
    cmd = [
        settings.FFMPEG_BIN,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-ss",
        f"{max(at_seconds, 0):.2f}",
        "-i",
        str(src),
        "-frames:v",
        "1",
        "-vf",
        "scale='min(640,iw)':-2",
        "-q:v",
        "4",
        str(dest),
    ]
    _run_encoder(_niced(cmd), 120, "poster")


def check_decodes(path: Path, *, timeout: float) -> None:
    """Decode the whole file and throw the result away. Anything ffmpeg
    complains about (a cut-off file, corrupt packets) is a failure."""
    cmd = [
        settings.FFMPEG_BIN,
        "-hide_banner",
        "-v",
        "error",
        "-xerror",
        "-nostdin",
        "-threads",  # as an input option: bounds the decoder, which otherwise takes every core
        "2",
        "-i",
        str(path),
        "-f",
        "null",
        "-",
    ]
    try:
        done = _run(_niced(cmd), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise TransientError("Processing took too long and was stopped.") from exc
    except OSError as exc:
        raise TransientError(_os_message(exc)) from exc
    if done.returncode != 0 or done.stderr.strip():
        log.warning("Converted file failed the decode check: %s", done.stderr[-_STDERR_TAIL:])
        raise TransientError("We couldn’t process this video. Try uploading it again.")


def _run_encoder(cmd: list[str], timeout: float, what: str) -> None:
    try:
        done = _run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        log.warning("ffmpeg %s timed out after %ss", what, timeout)
        raise TransientError("Processing took too long and was stopped.") from exc
    except OSError as exc:
        # Binary missing, or the disk refused a write (ENOSPC, EIO, EACCES).
        log.exception("ffmpeg %s could not run", what)
        raise TransientError(_os_message(exc)) from exc
    if done.returncode != 0:
        tail = done.stderr[-_STDERR_TAIL:]
        log.warning("ffmpeg %s failed (%s): %s", what, done.returncode, tail)
        if "No space left" in tail:
            raise TransientError(_os_message(OSError(28, "No space left on device")))
        raise PermanentError("We couldn’t convert that video. Try exporting it again as MP4.")


def _os_message(exc: OSError) -> str:
    if getattr(exc, "errno", None) == 28:
        return "The server ran out of storage space. Try again once space is freed up."
    return "The server hit a problem while processing this video. It will try again."
