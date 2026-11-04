"""Playing an uploaded video: authorised on every request, byte-range capable."""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import Iterator
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.http.response import HttpResponseBase
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.progress.services import LessonLocked

from . import access, byterange, services
from .models import MediaAsset

log = logging.getLogger(__name__)

CHUNK = 256 * 1024


def _iterate(path: Path, start: int, length: int) -> Iterator[bytes]:
    with open(path, "rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            block = handle.read(min(CHUNK, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


def _protect(response: HttpResponseBase, content_type: str) -> HttpResponseBase:
    response["Content-Type"] = content_type
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, no-cache"
    response["Vary"] = "Cookie"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = "inline"
    return response


class MediaStreamView(APIView):
    """`GET /api/v1/media/<id>/video/` (and `/poster/`)."""

    permission_classes = [IsAuthenticated]
    variant = "video"

    def handle_exception(self, exc):
        if isinstance(exc, LessonLocked):
            return Response(
                {"detail": exc.message, "blocked_by": exc.blocked_by}, status=exc.status_code
            )
        return super().handle_exception(exc)

    def get(self, request: Request, pk: int):
        asset = MediaAsset.objects.filter(pk=pk).first()
        if asset is None:
            raise Http404()
        verdict = access.can_view(request.user, asset)
        if verdict.locked is not None:
            raise verdict.locked
        if not verdict.allowed:
            raise Http404()

        relative, folder, fallback = (
            (asset.video_path, services.VIDEOS, "video/mp4")
            if self.variant == "video"
            else (asset.poster_path, services.POSTERS, "image/jpeg")
        )
        if asset.status != MediaAsset.Status.READY or not relative:
            raise Http404()  # an author asking before processing is done
        try:
            path = services.resolve(relative, under=folder)
        except ValueError:
            log.error("Media asset %s has a stored path outside its folder", asset.pk)
            raise Http404() from None
        if not path.is_file():
            log.error("Media asset %s is marked ready but its file is missing", asset.pk)
            raise Http404()
        content_type = mimetypes.guess_type(path.name)[0] or fallback

        if settings.MEDIA_ACCEL_REDIRECT:
            # nginx sends the bytes (and handles ranges); we only did the authorising.
            handoff = HttpResponse()
            handoff["X-Accel-Redirect"] = f"{settings.MEDIA_ACCEL_REDIRECT.rstrip('/')}/{relative}"
            return _protect(handoff, content_type)

        size = path.stat().st_size
        try:
            wanted = byterange.parse(request.headers.get("Range"), size)
        except byterange.Unsatisfiable:
            refused = HttpResponse(status=416)
            refused["Content-Range"] = f"bytes */{size}"
            return _protect(refused, content_type)

        response: HttpResponseBase
        if wanted is None:
            response = StreamingHttpResponse(_iterate(path, 0, size), status=200)
            response["Content-Length"] = str(size)
        else:
            response = StreamingHttpResponse(
                _iterate(path, wanted.start, wanted.length), status=206
            )
            response["Content-Length"] = str(wanted.length)
            response["Content-Range"] = f"bytes {wanted.start}-{wanted.end}/{size}"
        return _protect(response, content_type)


class MediaPosterView(MediaStreamView):
    variant = "poster"
