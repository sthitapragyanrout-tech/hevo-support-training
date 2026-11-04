from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from . import services, watching


class ProgressView(APIView):
    """Anyone signed in may record *their own* progress; there is no
    cross-user access here, so no `can()` check is needed."""

    permission_classes = [IsAuthenticated]

    def handle_exception(self, exc):
        if isinstance(exc, services.LessonLocked):
            return Response(
                {"detail": exc.message, "blocked_by": exc.blocked_by}, status=exc.status_code
            )
        if isinstance(exc, services.LessonBlocked):
            return Response({"detail": exc.message, "pending": exc.pending}, status=exc.status_code)
        if isinstance(exc, services.ProgressError):
            return Response({"detail": exc.message}, status=exc.status_code)
        return super().handle_exception(exc)


class CourseProgressView(ProgressView):
    def get(self, request: Request, version_id: int) -> Response:
        return Response(services.course_progress(request.user, version_id))


class ActivityStartView(ProgressView):
    def post(self, request: Request, pk: int) -> Response:
        return Response({"state": services.start_activity(request.user, pk)})


class ActivityCompleteView(ProgressView):
    def post(self, request: Request, pk: int) -> Response:
        return Response({"state": services.complete_activity(request.user, pk)})

    def delete(self, request: Request, pk: int) -> Response:
        return Response({"state": services.uncomplete_activity(request.user, pk)})


class ActivityAttemptView(ProgressView):
    def post(self, request: Request, pk: int) -> Response:
        body = request.data if isinstance(request.data, dict) else {}
        outcome = services.submit_attempt(request.user, pk, body.get("answers"))
        return Response(outcome, status=status.HTTP_201_CREATED)

    def get(self, request: Request, pk: int) -> Response:
        return Response(services.attempts_report(request.user, pk))

    def delete(self, request: Request, pk: int) -> Response:
        services.reset_attempts(request.user, pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class WatchThrottle(UserRateThrottle):
    scope = "video_watch"


class ActivityWatchView(ProgressView):
    """A learner's own watch state (GET) and heartbeats (POST). The browser
    sends what it played; the server decides what counts and whether the video
    is finished — there is no "mark watched" here."""

    throttle_classes = [WatchThrottle]

    def get(self, request: Request, pk: int) -> Response:
        return Response(watching.watch_state(request.user, pk))

    def post(self, request: Request, pk: int) -> Response:
        return Response(watching.record_watch(request.user, pk, request.data))


class LessonCompleteView(ProgressView):
    def post(self, request: Request, pk: int) -> Response:
        services.complete_lesson(request.user, pk)
        return Response({"completed": True}, status=status.HTTP_200_OK)

    def delete(self, request: Request, pk: int) -> Response:
        services.uncomplete_lesson(request.user, pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
