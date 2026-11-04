"""Upload and manage videos (the Studio's side). Playing them is in `stream.py`."""

from __future__ import annotations

from django.conf import settings
from django.core.files.uploadhandler import StopUpload, TemporaryFileUploadHandler
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import CanPermission

from . import access, services
from .errors import MediaError, TooLarge
from .models import MediaAsset

_MULTIPART_OVERHEAD = 64 * 1024


class LimitedUploadHandler(TemporaryFileUploadHandler):
    """Stops reading an upload the moment it passes the size limit, so an
    over-long body is never written to disk (and a lying Content-Length can't
    sneak past the up-front check)."""

    def __init__(self, request, max_bytes: int):
        super().__init__(request)
        self.max_bytes = max_bytes
        self.total = 0
        self.exceeded = False

    def receive_data_chunk(self, raw_data, start):
        self.total += len(raw_data)
        if self.total > self.max_bytes:
            self.exceeded = True
            raise StopUpload(connection_reset=False)
        return super().receive_data_chunk(raw_data, start)


def payload(asset: MediaAsset) -> dict:
    """What the Studio is told about an asset — never a file path."""
    ready = asset.status == MediaAsset.Status.READY
    return {
        "id": asset.pk,
        "status": asset.status,
        "status_label": asset.get_status_display(),
        "original_name": asset.original_name,
        "size_bytes": asset.size_bytes,
        "duration_seconds": asset.duration_seconds,
        "width": asset.width,
        "height": asset.height,
        "error": asset.error,
        "retryable": asset.retryable and asset.status == MediaAsset.Status.FAILED,
        "video_url": f"/api/v1/media/{asset.pk}/video/" if ready else None,
        "poster_url": f"/api/v1/media/{asset.pk}/poster/" if ready else None,
    }


class MediaAuthoringView(APIView):
    permission_classes = [IsAuthenticated, CanPermission]
    required_action = access.AUTHOR

    def handle_exception(self, exc):
        if isinstance(exc, MediaError):
            return Response({"detail": exc.message}, status=exc.status_code)
        return super().handle_exception(exc)

    def _asset(self, request: Request, pk: int) -> MediaAsset:
        asset = get_object_or_404(MediaAsset, pk=pk)
        if not access.can_manage(request.user, asset):
            # Same answer as "doesn't exist": no one learns which ids are taken.
            raise Http404()
        return asset


class MediaLimitsView(MediaAuthoringView):
    def get(self, request: Request) -> Response:
        return Response(services.limits())


class MediaUploadView(MediaAuthoringView):
    parser_classes = [MultiPartParser]

    def initial(self, request, *args, **kwargs):
        # Must be in place before anything reads the body (authentication does).
        request._request.upload_handlers = [
            self._handler(request._request),
        ]
        super().initial(request, *args, **kwargs)

    def _handler(self, django_request) -> LimitedUploadHandler:
        self.limiter = LimitedUploadHandler(django_request, services.max_upload_bytes())
        return self.limiter

    def post(self, request: Request) -> Response:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
        if declared > services.max_upload_bytes() + _MULTIPART_OVERHEAD:
            raise _too_large()
        try:
            upload = request.FILES.get("file")
        except Exception:
            upload = None
        if self.limiter.exceeded:
            raise _too_large()
        if upload is None:
            raise MediaError("Choose a video file to upload.")
        asset = services.create_asset(upload, request.user)
        return Response(payload(asset), status=status.HTTP_201_CREATED)


def _too_large() -> TooLarge:
    return TooLarge(f"That file is larger than the {settings.MEDIA_MAX_UPLOAD_MB:g} MB limit.")


class MediaDetailView(MediaAuthoringView):
    def get(self, request: Request, pk: int) -> Response:
        return Response(payload(self._asset(request, pk)))


class MediaRetryView(MediaAuthoringView):
    def post(self, request: Request, pk: int) -> Response:
        asset = services.retry_asset(self._asset(request, pk))
        return Response(payload(asset))
