"""Sign-in activity: who signed in, who failed to, and who got locked out —
what django-axes records, read-only, for investigating a locked or suspicious
account."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from axes.models import AccessFailureLog, AccessLog
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts import admin_services as svc

from .base import ConsoleView, paginate

User = get_user_model()


def _day(value: str | None, *, end: bool) -> datetime | None:
    """`2026-10-23` → the start (or end) of that day, in the server's time zone."""
    try:
        parsed = date.fromisoformat(value) if value else None
    except ValueError:
        return None
    if parsed is None:
        return None
    moment = datetime.combine(parsed, time.max if end else time.min)
    return timezone.make_aware(moment)


class SignInListView(ConsoleView):
    required_action = "accounts.manage_users"

    def get(self, request: Request) -> Response:
        params = request.query_params
        failed = params.get("kind") == "failed"
        qs = (AccessFailureLog if failed else AccessLog).objects.all()
        if search := params.get("search", "").strip():
            qs = qs.filter(
                Q(username__icontains=search)
                | Q(ip_address__icontains=search)
                | Q(user_agent__icontains=search)
            )
        if start := _day(params.get("from"), end=False):
            qs = qs.filter(attempt_time__gte=start)
        if end := _day(params.get("to"), end=True):
            qs = qs.filter(attempt_time__lte=end)
        if failed and params.get("locked") == "true":
            qs = qs.filter(locked_out=True)
        qs = qs.order_by("-attempt_time", "-pk")
        page, meta = paginate(request, qs)

        known = {
            u.username: u
            for u in User.objects.filter(username__in={e.username for e in page if e.username})
        }
        rows: list[dict[str, Any]] = []
        for entry in page:
            user = known.get(entry.username)
            row: dict[str, Any] = {
                "id": entry.pk,
                "when": entry.attempt_time.isoformat(),
                "username": entry.username,
                "user_id": user.pk if user else None,
                "name": svc.display_name(user) if user else None,
                "ip_address": entry.ip_address,
                "user_agent": entry.user_agent,
            }
            if failed:
                row["locked_out"] = entry.locked_out
            else:
                row["signed_out_at"] = entry.logout_time.isoformat() if entry.logout_time else None
            rows.append(row)
        return Response({"results": rows, "kind": "failed" if failed else "success", **meta})
