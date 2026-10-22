"""
Shared plumbing for the Admin Console API (`/api/v1/admin/...`).

Every view authorises through `can()` (the same helper the rest of the API and
Django Admin use), shapes plain-language errors, and pages its lists the same
way so the SPA's `DataTable` works on all of them.
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.admin_services import AdminError
from apps.accounts.permissions import CanPermission
from apps.accounts.rbac import can

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


class ConsoleError(Exception):
    """A refusal the admin can act on: shown as-is in the console."""

    status_code = 400

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class CanAnyPermission(BasePermission):
    """For views several roles of administrator may open: set `required_any`."""

    def has_permission(self, request, view) -> bool:
        return any(can(request.user, action) for action in view.required_any)


class ConsoleView(APIView):
    """Authenticated + `required_action` (checked with `can()`), or, for a
    screen shared by several kinds of administrator, any of `required_any`."""

    permission_classes = [IsAuthenticated, CanPermission]
    required_action: str = ""
    required_any: tuple[str, ...] = ()

    def get_permissions(self):
        if self.required_any:
            return [IsAuthenticated(), CanAnyPermission()]
        return super().get_permissions()

    def handle_exception(self, exc):
        if isinstance(exc, ConsoleError | AdminError):
            return Response({"detail": exc.message}, status=exc.status_code)
        return super().handle_exception(exc)


def _int(value: str | None, default: int, low: int, high: int) -> int:
    try:
        number = int(value) if value is not None else default
    except ValueError:
        return default
    return max(low, min(number, high))


def optional_int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def paginate(request: Request, items) -> tuple[list[Any], dict[str, int]]:
    """Slice a queryset or list by `?page=` / `?page_size=`; returns the page
    and the meta the `DataTable` needs."""
    size = _int(request.query_params.get("page_size"), DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE)
    total = items.count() if hasattr(items, "count") and not isinstance(items, list) else len(items)
    pages = max(1, -(-total // size))
    page = _int(request.query_params.get("page"), 1, 1, pages)
    start = (page - 1) * size
    return list(items[start : start + size]), {
        "count": total,
        "page": page,
        "page_size": size,
        "pages": pages,
    }
