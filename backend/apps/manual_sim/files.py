"""Attachments on a submission: deciding what a file *is*, storing it safely, serving it back.

Trust nothing the uploader says: the type is decided from the file's own bytes (never its
extension or the browser's `Content-Type`); only PNG, JPEG, WebP and PDF are accepted;
images are also opened by Pillow (header, pixel count, integrity) so a disguised or
decompression-bomb file is refused. We never re-encode, so the bytes are exactly what was sent.
A stored file is named by a UUID plus the extension of the type *we* detected, so nothing the
uploader typed reaches the file system, and it lives outside any static path: it is served only
by an endpoint that checks who is asking, on every request.

Not done: antivirus scanning, and EXIF metadata is not stripped from images.
"""

from __future__ import annotations

import errno
import logging
import os
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.http.response import HttpResponseBase
from django.utils.http import content_disposition_header
from PIL import Image, UnidentifiedImageError

from apps.media_pipeline import services as media
from apps.media_pipeline.errors import MediaError

from .errors import BadInput, SimError, TooLarge
from .models import SubmissionFile

log = logging.getLogger(__name__)

MB = 1024 * 1024
FOLDER = "attachments"
ALLOWED_TEXT = "PNG, JPEG, WebP or PDF"

# What we say a file is → (extension, serve inline?). PDFs are always downloaded, never rendered
# in our origin.
KINDS = {
    "image/png": ("png", True),
    "image/jpeg": ("jpg", True),
    "image/webp": ("webp", True),
    "application/pdf": ("pdf", False),
}
_PIL_FORMAT = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


@dataclass(frozen=True)
class Detected:
    content_type: str
    extension: str
    size: int


def limits() -> dict[str, float | int | list[str]]:
    """What a learner is told they may attach (so the screen can check up front)."""
    return {
        "max_files": settings.MANUAL_SIM_MAX_FILES,
        "max_file_mb": settings.MANUAL_SIM_MAX_FILE_MB,
        "max_total_mb": settings.MANUAL_SIM_MAX_TOTAL_MB,
        "types": ["png", "jpg", "webp", "pdf"],
    }


def max_request_bytes() -> int:
    return int(settings.MANUAL_SIM_MAX_TOTAL_MB * MB)


def _sniff(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def detect(upload) -> Detected:
    """Decide what `upload` is, or refuse it with a sentence."""
    size = getattr(upload, "size", None)
    per_file = int(settings.MANUAL_SIM_MAX_FILE_MB * MB)
    if size is None or size <= 0:
        raise BadInput("One of the files is empty.")
    if size > per_file:
        raise TooLarge(f"A file is larger than the {settings.MANUAL_SIM_MAX_FILE_MB:g} MB limit.")
    upload.seek(0)
    head = upload.read(16)
    kind = _sniff(head)
    if kind is None:
        raise BadInput(f"We can’t use that kind of file. Attach {ALLOWED_TEXT}.")
    upload.seek(0)
    if kind == "application/pdf":
        upload.seek(max(size - 2048, 0))
        if b"%%EOF" not in upload.read(2048):
            raise BadInput("That PDF looks incomplete or damaged.")
    else:
        _check_image(upload, kind)
    upload.seek(0)
    return Detected(kind, KINDS[kind][0], size)


def _check_image(upload, kind: str) -> None:
    upload.seek(0)
    try:
        with Image.open(upload) as image:
            if image.format != _PIL_FORMAT[kind]:
                raise BadInput(f"We can’t use that kind of file. Attach {ALLOWED_TEXT}.")
            width, height = image.size
            if width < 1 or height < 1 or width * height > settings.MANUAL_SIM_MAX_PIXELS:
                raise BadInput("That image is too large. Use a smaller screenshot.")
            image.verify()
    except BadInput:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise BadInput("That image looks damaged. Try saving it again.") from None


def check_batch(uploads: Sequence, *, allowed: bool) -> list[Detected]:
    """Validate every attachment before anything is written."""
    if not uploads:
        return []
    if not allowed:
        raise BadInput("This activity doesn’t take attachments.")
    if len(uploads) > settings.MANUAL_SIM_MAX_FILES:
        raise BadInput(f"Attach at most {settings.MANUAL_SIM_MAX_FILES} files.")
    detected = [detect(u) for u in uploads]
    if sum(d.size for d in detected) > max_request_bytes():
        raise TooLarge(
            f"The files are larger than {settings.MANUAL_SIM_MAX_TOTAL_MB:g} MB together."
        )
    return detected


# ----------------------------------------------------------------------- storing


def display_name(name: str) -> str:
    """What we show as the file's name: no path, no control characters, bounded."""
    base = os.path.basename((name or "").replace("\\", "/"))
    cleaned = "".join(ch for ch in base if ch.isprintable())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:120] or "attachment"


def path_of(file: SubmissionFile) -> Path:
    return media.resolve(file.relative_path, under=FOLDER)


def write(upload, detected: Detected) -> uuid.UUID:
    """Store one validated upload; returns its id. Raises a `SimError` on any failure and
    leaves nothing behind."""
    uid = uuid.uuid4()
    relative = f"{FOLDER}/{uid}.{detected.extension}"
    dest = media.resolve(relative, under=FOLDER)
    part = dest.with_name(dest.name + ".part")
    try:
        media._assert_free_space(detected.size * 2)
        dest.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with open(part, "wb") as handle:
            upload.seek(0)
            for chunk in upload.chunks():
                written += len(chunk)
                if written > detected.size:  # it grew while we read it: refuse
                    raise BadInput("That file changed while it was being uploaded.")
                handle.write(chunk)
        if written != detected.size:
            raise BadInput("That file didn’t upload completely. Please try again.")
        os.replace(part, dest)
    except MediaError as exc:
        discard_paths(part, dest)
        raise SimError(exc.message, exc.status_code) from exc
    except OSError as exc:
        discard_paths(part, dest)
        if exc.errno == errno.ENOSPC:
            raise SimError("There isn’t enough storage space right now.", 503) from exc
        log.exception("Could not store an attachment")
        raise SimError("We couldn’t save that file. Please try again.", 500) from exc
    except BaseException:
        discard_paths(part, dest)
        raise
    return uid


def discard_paths(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.warning("Could not remove %s", path.name)


def remove_after_delete(sender, instance: SubmissionFile, **kwargs) -> None:
    """Signal handler: delete the stored file when its row is deleted (including when a whole
    submission or user is deleted)."""
    try:
        discard_paths(path_of(instance))
    except ValueError:
        log.error("Attachment %s has a stored path outside its folder", instance.pk)


def discard(files: Sequence[SubmissionFile]) -> None:
    for file in files:
        try:
            discard_paths(path_of(file))
        except ValueError:
            log.error("Attachment %s has a stored path outside its folder", file.pk)


# ------------------------------------------------------------------------ serving


def respond(file: SubmissionFile) -> HttpResponseBase:
    """The bytes of an attachment, with headers that stop a browser treating it as a page.
    The caller has already checked that this person may see it."""
    try:
        path = path_of(file)
    except ValueError:
        log.error("Attachment %s has a stored path outside its folder", file.pk)
        raise SimError("That file isn’t available.", 404) from None
    if not path.is_file():
        log.error("Attachment %s is missing from disk", file.pk)
        raise SimError("That file isn’t available.", 404)
    kind = file.content_type if file.content_type in KINDS else "application/octet-stream"
    inline = KINDS.get(kind, ("", False))[1]
    disposition = content_disposition_header(not inline, display_name(file.original_name)) or ""
    response: HttpResponseBase
    if settings.MEDIA_ACCEL_REDIRECT:
        response = HttpResponse()
        response["X-Accel-Redirect"] = (
            f"{settings.MEDIA_ACCEL_REDIRECT.rstrip('/')}/{file.relative_path}"
        )
    else:
        response = FileResponse(open(path, "rb"), content_type=kind)
    response["Content-Type"] = kind
    response["Content-Disposition"] = disposition
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-cache"
    response["Vary"] = "Cookie"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    return response
