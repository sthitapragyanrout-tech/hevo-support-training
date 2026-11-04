"""Shared pieces for the media tests: real (tiny) clips made with ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe are not installed")


def make_clip(
    path: Path,
    *,
    seconds: float = 2,
    size: str = "320x240",
    audio: bool = True,
    codec: str = "libx264",
) -> Path:
    """A real, playable test video (colour bars + a tone)."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    cmd += ["-f", "lavfi", "-i", f"testsrc=duration={seconds}:size={size}:rate=15"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-c:v", codec, "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


# ---------------------------------------------------------------- fake assets
# Streaming and authorization don't care what the bytes are, so these tests use
# plain files and need no ffmpeg.

VIDEO_BYTES = bytes(range(256)) * 40  # 10,240 bytes, every value distinct per 256
POSTER_BYTES = b"\xff\xd8\xff" + b"p" * 997


def ready_asset(uploader, media_root, *, status=None):
    from apps.media_pipeline.models import MediaAsset

    asset = MediaAsset.objects.create(
        uploaded_by=uploader,
        original_name="Secret client demo.mov",
        size_bytes=len(VIDEO_BYTES),
        duration_seconds=120.0,
        width=1280,
        height=720,
        status=status or MediaAsset.Status.READY,
        original_path="originals/never-shown.mov",
    )
    if asset.status == MediaAsset.Status.READY:
        video = media_root / "videos" / f"{asset.uuid}.mp4"
        poster = media_root / "posters" / f"{asset.uuid}.jpg"
        video.parent.mkdir(parents=True, exist_ok=True)
        poster.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(VIDEO_BYTES)
        poster.write_bytes(POSTER_BYTES)
        asset.video_path = f"videos/{asset.uuid}.mp4"
        asset.poster_path = f"posters/{asset.uuid}.jpg"
        asset.save(update_fields=["video_path", "poster_path"])
    return asset


def video_course(make_role_user, asset, *, order="free", publish=True, title="Course"):
    """A course whose second lesson holds a video of `asset` (and whose first
    lesson is a required reading, so a sequential course locks the video)."""
    from apps.accounts.models import Role
    from apps.catalog import services as catalog
    from apps.catalog.models import Activity

    author = asset.uploaded_by
    admin = make_role_user(Role.Name.ADMIN, username=f"adm-{title}", email=f"adm-{title}@e.com")
    course = catalog.create_course(title=title, user=author)
    version = catalog.open_version(course)
    module = catalog.add_node(version.root_node, title="Module")
    first = catalog.add_node(module, title="First")
    Activity.objects.create(
        content_node=first,
        activity_type="reading",
        title="Read",
        config={"source_url": "https://x.io"},
    )
    second = catalog.add_node(module, title="Second")
    activity = Activity.objects.create(
        content_node=second,
        activity_type="video",
        title="Watch",
        config={"source": "upload", "media_asset": asset.pk},
    )
    catalog.set_learning_order(version, order)
    if publish:
        version.publish(admin)
    return course, version, first, second, activity
