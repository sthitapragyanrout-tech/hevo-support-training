"""The learner's side of a mentor-rated simulation: `/api/v1/rated-sims/`.

Everything is keyed to the signed-in user (another learner's submission is a 404). Rating,
claiming and the trainer's actions are in `console.py`.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.http import Http404, QueryDict
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.media_pipeline.views import LimitedUploadHandler
from apps.progress.views import ProgressView

from . import access, files, payloads, services
from .errors import SimError, TooLarge
from .models import SubmissionFile

# Room for the text fields and multipart framing on top of the files themselves.
_OVERHEAD = 64 * 1024


class SubmitThrottle(UserRateThrottle):
    scope = "manual_sim_submit"


class RatedSimView(ProgressView):
    """Learner progress rules (locked lesson → 409, unpublished → 404) plus this app's own
    plain refusals."""

    def handle_exception(self, exc):
        if isinstance(exc, SimError):
            return Response({"detail": exc.message}, status=exc.status_code)
        return super().handle_exception(exc)

    def view_of(self, request: Request, activity_id: int) -> dict:
        activity = services._activity(activity_id)
        return payloads.learner_view(request.user, activity, services._now())


class ActivityView(RatedSimView):
    def get(self, request: Request, pk: int) -> Response:
        return Response(self.view_of(request, pk))


class OpenView(RatedSimView):
    """Opening the activity starts the learner's deadline (once)."""

    def post(self, request: Request, pk: int) -> Response:
        services.open_case(request.user, pk)
        return Response(self.view_of(request, pk))


class SubmitView(RatedSimView):
    throttle_classes = [SubmitThrottle]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def initial(self, request, *args, **kwargs):
        # Must be in place before anything reads the body: it stops reading a body the moment
        # it passes the limit, so an over-long upload is never written to disk.
        self.limiter = LimitedUploadHandler(request._request, files.max_request_bytes())
        request._request.upload_handlers = [self.limiter]
        super().initial(request, *args, **kwargs)

    def post(self, request: Request, pk: int) -> Response:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
        room = files.max_request_bytes() + settings.MANUAL_SIM_MAX_ANSWER_CHARS * 4 + _OVERHEAD
        if declared > room:
            raise _too_large()
        answer: object = None
        links: object = None
        uploads: list = []
        try:
            data = request.data
            uploads = request.FILES.getlist("files") if request.FILES else []
            if isinstance(data, QueryDict):  # a multipart form
                answer, links = data.get("answer"), data.getlist("links")
            elif isinstance(data, dict):  # JSON
                answer, links = data.get("answer"), data.get("links")
        except Exception:
            pass
        if self.limiter.exceeded:
            raise _too_large()
        services.submit(request.user, pk, answer, links, uploads)
        return Response(self.view_of(request, pk), status=status.HTTP_201_CREATED)


def _too_large() -> TooLarge:
    return TooLarge(f"The files are larger than {settings.MANUAL_SIM_MAX_TOTAL_MB:g} MB together.")


class WithdrawView(RatedSimView):
    def post(self, request: Request, pk: int) -> Response:
        sub = services.withdraw(request.user, pk)
        return Response(self.view_of(request, sub.case.activity_id))


class FileView(RatedSimView):
    """An attachment, authorised on every request: its author, the people who may rate the
    work, and trainers/admins/result viewers. Anyone else gets the same 404 as a missing file."""

    def get(self, request: Request, file_id: uuid.UUID):
        file = (
            SubmissionFile.objects.select_related("submission__case__user")
            .filter(uuid=file_id)
            .first()
        )
        if file is None or not access.can_see(request.user, file.submission):
            raise Http404()
        return files.respond(file)
