"""The learner's side of a practice ticket: `/api/v1/sim/`.

Everything is keyed to the signed-in user (another learner's session is a 404);
the web process only reads and writes rows — every model call happens on the
simulation worker.
"""

from __future__ import annotations

import uuid

from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.accounts.rbac import can
from apps.activities import bot_sim as cfg
from apps.progress.views import ProgressView

from . import payloads, services
from .errors import BadReply, SimError
from .models import SimSession


class StartThrottle(UserRateThrottle):
    scope = "sim_start"


class ReplyThrottle(UserRateThrottle):
    scope = "sim_reply"


class PollThrottle(UserRateThrottle):
    scope = "sim_poll"


class SimView(ProgressView):
    """Learner progress rules (locked lesson → 409, unpublished → 404, tries used up
    → 409) plus this app's own plain refusals."""

    def handle_exception(self, exc):
        if isinstance(exc, SimError):
            return Response({"detail": exc.message}, status=exc.status_code)
        return super().handle_exception(exc)


class StartView(SimView):
    throttle_classes = [StartThrottle]

    def post(self, request: Request, pk: int) -> Response:
        mine = SimSession.objects.filter(user=request.user, activity_id=pk)  # type: ignore[misc]
        known = set(mine.values_list("pk", flat=True))
        session = services.start(request.user, pk)
        return Response(
            payloads.session_payload(session),
            status=status.HTTP_200_OK if session.pk in known else status.HTTP_201_CREATED,
        )


class PreviewView(SimView):
    """An author trying it in Studio: needs the authoring permission, records nothing."""

    throttle_classes = [StartThrottle]

    def post(self, request: Request, pk: int) -> Response:
        if not can(request.user, "catalog.author_content"):
            raise PermissionDenied()
        session = services.start_preview(request.user, pk)
        return Response(payloads.session_payload(session), status=status.HTTP_201_CREATED)


class SessionView(SimView):
    throttle_classes = [PollThrottle]

    def get(self, request: Request, pk: int) -> Response:
        return Response(payloads.session_payload(services.tick(request.user, pk)))


class MessageView(SimView):
    throttle_classes = [ReplyThrottle]

    def post(self, request: Request, pk: int) -> Response:
        body = request.data if isinstance(request.data, dict) else {}
        text = body.get("text")
        if not isinstance(text, str):
            raise BadReply("Write a reply before sending.")
        try:
            client_id = uuid.UUID(str(body.get("client_id")))
        except ValueError as exc:
            raise BadReply("That message couldn’t be sent. Please try again.") from exc
        _, created = services.submit_reply(request.user, pk, text, client_id)
        session = services.tick(request.user, pk)
        return Response(
            payloads.session_payload(session),
            status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK,
        )


class RetryView(SimView):
    throttle_classes = [ReplyThrottle]

    def post(self, request: Request, pk: int) -> Response:
        services.retry_turn(request.user, pk)
        return Response(payloads.session_payload(services.tick(request.user, pk)))


class SkipView(SimView):
    throttle_classes = [ReplyThrottle]

    def post(self, request: Request, pk: int) -> Response:
        body = request.data if isinstance(request.data, dict) else {}
        reason = body.get("reason")
        session = services.skip(request.user, pk, reason if isinstance(reason, str) else "")
        return Response(payloads.session_payload(session))


class FinishView(SimView):
    throttle_classes = [ReplyThrottle]

    def post(self, request: Request, pk: int) -> Response:
        return Response(
            payloads.session_payload(services.finish(request.user, pk)),
            status=status.HTTP_202_ACCEPTED,
        )


class ResultView(SimView):
    throttle_classes = [PollThrottle]

    def get(self, request: Request, pk: int) -> Response:
        session = services.tick(request.user, pk)
        if session.state != SimSession.State.FINISHED:
            return Response(
                {"detail": "Your feedback isn’t ready yet.", "state": session.state},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(payloads.session_payload(session))


class ScenarioCountView(SimView):
    """For the Studio editor: how many approved scenarios match these settings."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        if not can(request.user, "catalog.author_content"):
            raise PermissionDenied()
        config = {
            "persona": request.query_params.get("persona", "random"),
            "topics": [t for t in request.query_params.get("topics", "").split(",") if t],
        }
        return Response(
            {
                "count": services.count_matching(config),
                "persona": cfg.persona(config),
                "topics": cfg.topics(config),
            }
        )
