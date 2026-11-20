"""Certificate endpoints.

GET  /api/v1/certificates/<code>/                    the certificate page (its owner, or staff)
GET  /api/v1/authoring/courses/<pk>/certificate/     the course's policy (course authors)
PUT  /api/v1/authoring/courses/<pk>/certificate/     change it (audited)
POST /api/v1/admin/certificates/<pk>/revoke/         revoke with a reason (audited)
POST /api/v1/admin/certificates/<pk>/restore/        undo a revocation (audited)
"""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.rbac import can
from apps.audit import services as audit
from apps.catalog.authoring_views import AuthoringView
from apps.catalog.models import Course
from apps.console.base import ConsoleView

from . import services
from .models import Certificate

VIEW_RESULTS = "progress.view_results"
MANAGE = "enrollment.manage_enrollments"


def _errors(view_cls):
    """Map certificate errors to their HTTP status with a plain `detail`."""

    def handle_exception(self, exc):
        if isinstance(exc, services.CertificateError):
            return Response({"detail": exc.message}, status=exc.status_code)
        return super(view_cls, self).handle_exception(exc)

    view_cls.handle_exception = handle_exception
    return view_cls


class CertificateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, code: str) -> Response:
        cert = (
            Certificate.objects.select_related("user", "version").filter(code=code.upper()).first()
        )
        staff = can(request.user, VIEW_RESULTS)
        # Someone else's certificate is simply not found (no hint that the code exists).
        if cert is None or (cert.user_id != request.user.pk and not staff):
            raise Http404
        if cert.revoked_at is not None and not staff:
            raise Http404
        return Response(services.page_payload(cert, staff=staff))


@_errors
class PolicyView(AuthoringView):
    def get(self, request: Request, pk: int) -> Response:
        course = get_object_or_404(Course, pk=pk)
        self.authorize(request, course)
        return Response(services.policy_payload(services.policy_of(course)))

    def put(self, request: Request, pk: int) -> Response:
        course = get_object_or_404(Course, pk=pk)
        self.authorize(request, course)
        data = request.data if isinstance(request.data, dict) else {}
        policy, changes = services.set_policy(course, data, by=request.user)
        if changes:
            audit.record(
                request,
                "certificates.policy",
                target_type="course",
                target_id=course.pk,
                target_label=course.slug,
                changes=changes,
            )
        return Response(services.policy_payload(policy))


@_errors
class RevokeView(ConsoleView):
    required_action = MANAGE

    def post(self, request: Request, pk: int) -> Response:
        cert = get_object_or_404(Certificate.objects.select_related("user", "version"), pk=pk)
        data = request.data if isinstance(request.data, dict) else {}
        cert = services.revoke(cert, str(data.get("reason") or ""), by=request.user)
        audit.record(
            request,
            "certificates.revoke",
            target_type="certificate",
            target_id=cert.pk,
            target_label=f"{cert.code} · {services.name_of(cert.user)} · {cert.course_title}",
            changes={"reason": cert.revoked_reason},
        )
        return Response(services.page_payload(cert, staff=True))


@_errors
class RestoreView(ConsoleView):
    required_action = MANAGE

    def post(self, request: Request, pk: int) -> Response:
        cert = get_object_or_404(Certificate.objects.select_related("user", "version"), pk=pk)
        cert = services.restore(cert)
        audit.record(
            request,
            "certificates.restore",
            target_type="certificate",
            target_id=cert.pk,
            target_label=f"{cert.code} · {services.name_of(cert.user)} · {cert.course_title}",
        )
        return Response(services.page_payload(cert, staff=True))
