from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from . import services
from .models import Notification

PAGE_SIZE = 20
MAX_PAGE_SIZE = 50


class NotificationsThrottle(UserRateThrottle):
    scope = "notifications"


class _View(APIView):
    """Anyone signed in, and only ever their *own* notifications: every query is filtered by the
    caller, so another person's id is simply not found."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [NotificationsThrottle]


def _me(request: Request) -> int:
    pk = request.user.pk
    assert pk is not None  # IsAuthenticated guarantees a real user
    return pk


def _item(n: Notification) -> dict:
    return {
        "id": n.pk,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "link": n.link,
        "created_at": n.created_at.isoformat(),
        "read": n.read_at is not None,
    }


def _int(raw, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(raw)))
    except (TypeError, ValueError):
        return default


class ListView(_View):
    """GET /api/v1/notifications/?unread=1&page=&page_size= — newest first."""

    def get(self, request: Request) -> Response:
        rows = Notification.objects.filter(user_id=_me(request))
        if request.query_params.get("unread") in ("1", "true"):
            rows = rows.filter(read_at__isnull=True)
        size = _int(request.query_params.get("page_size"), PAGE_SIZE, 1, MAX_PAGE_SIZE)
        total = rows.count()
        pages = max(1, -(-total // size))
        page = _int(request.query_params.get("page"), 1, 1, pages)
        start = (page - 1) * size
        return Response(
            {
                "results": [_item(n) for n in rows[start : start + size]],
                "count": total,
                "page": page,
                "pages": pages,
                "unread_count": services.unread_count(request.user),
            }
        )


class UnreadCountView(_View):
    """GET /api/v1/notifications/unread-count/ — the light call the header bell polls."""

    def get(self, request: Request) -> Response:
        return Response({"unread_count": services.unread_count(request.user)})


class ReadView(_View):
    def post(self, request: Request, pk: int) -> Response:
        get_object_or_404(Notification, pk=pk, user_id=_me(request))
        found = services.mark_read(request.user, pk)
        assert found is not None
        return Response({**_item(found), "unread_count": services.unread_count(request.user)})


class ReadAllView(_View):
    def post(self, request: Request) -> Response:
        services.mark_all_read(request.user)
        return Response({"unread_count": 0})
