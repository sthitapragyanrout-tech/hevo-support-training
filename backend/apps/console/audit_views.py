from __future__ import annotations

from django.db.models import Q
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.models import AuditLog

from .base import ConsoleView, paginate


def _row(entry: AuditLog) -> dict:
    return {
        "id": entry.pk,
        "created_at": entry.created_at.isoformat(),
        "actor": entry.actor_label,
        "action": entry.action,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "target": entry.target_label,
        "changes": entry.changes,
        "ip_address": entry.ip_address,
    }


class AuditListView(ConsoleView):
    required_action = "audit.view_audit"

    def get(self, request: Request) -> Response:
        params = request.query_params
        qs = AuditLog.objects.all()
        if search := params.get("search", "").strip():
            qs = qs.filter(
                Q(actor_label__icontains=search)
                | Q(target_label__icontains=search)
                | Q(action__icontains=search)
            )
        if action := params.get("action"):
            qs = qs.filter(action=action)
        page, meta = paginate(request, qs)
        return Response({"results": [_row(e) for e in page], **meta})


class AuditActionsView(ConsoleView):
    """Distinct actions seen so far — the filter dropdown."""

    required_action = "audit.view_audit"

    def get(self, request: Request) -> Response:
        actions = AuditLog.objects.order_by().values_list("action", flat=True).distinct()
        return Response({"results": sorted(actions)})
