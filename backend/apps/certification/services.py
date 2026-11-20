"""Earning, showing and revoking certificates.

`evaluate` is the only place a certificate is issued. It runs after anything that can change
the result (a lesson finished, a quiz scored or marked, a ticket scored, work rated, the policy
changed) and issues one when the learner is actively enrolled, has finished every required lesson,
has a result for each kind of scored work the course weighs, and reaches the threshold.

It never takes one back: a later policy change or a reset leaves an issued certificate alone, and
once a person has *any* certificate on a course (even a revoked one) nothing is issued again
automatically — a revoked certificate comes back only when someone restores it.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.enrollment import access
from apps.enrollment.models import Enrollment

from . import scoring
from .models import Certificate, CertificatePolicy

log = logging.getLogger(__name__)

CERTIFICATE_EARNED = "certificate_earned"
MAX_REASON = 300


class CertificateError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class Conflict(CertificateError):
    status_code = 409


# ----------------------------------------------------------------------------- policy


def policy_of(course) -> CertificatePolicy:
    """The course's policy (an unsaved, switched-off default when none has been set)."""
    return CertificatePolicy.objects.filter(course=course).first() or CertificatePolicy(
        course=course
    )


def policy_payload(policy: CertificatePolicy) -> dict[str, Any]:
    return {
        "enabled": policy.enabled,
        "threshold": policy.threshold,
        "weights": policy.weights,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
    }


def _whole(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CertificateError(f"{name} must be a whole number.")
    if not low <= value <= high:
        raise CertificateError(f"{name} must be between {low} and {high}.")
    return value


@transaction.atomic
def set_policy(course, data: dict[str, Any], *, by=None) -> tuple[CertificatePolicy, dict]:
    """Change the policy; returns (policy, {field: [before, after]} for what changed). Everyone on
    the course is checked again once this commits (someone may now qualify)."""
    policy = CertificatePolicy.objects.select_for_update().filter(course=course).first()
    if policy is None:
        policy = CertificatePolicy(course=course)
    before = {"enabled": policy.enabled, "threshold": policy.threshold, **policy.weights}
    if "enabled" in data:
        if not isinstance(data["enabled"], bool):
            raise CertificateError("Enabled must be true or false.")
        policy.enabled = data["enabled"]
    if "threshold" in data:
        policy.threshold = _whole(data["threshold"], "The passing threshold", 1, 100)
    weights = data.get("weights")
    if weights is not None:
        if not isinstance(weights, dict) or set(weights) - set(scoring.KINDS):
            raise CertificateError("Weights are given for quiz, practice and rated work.")
        for kind, value in weights.items():
            setattr(policy, f"weight_{kind}", _whole(value, "Each weight", 0, 100))
    if not any(policy.weights.values()):
        raise CertificateError("At least one kind of work needs a weight above 0.")
    policy.updated_by = by
    policy.save()
    after = {"enabled": policy.enabled, "threshold": policy.threshold, **policy.weights}
    changes = {k: [before[k], after[k]] for k in after if before[k] != after[k]}
    if policy.enabled:
        course_id = course.pk
        transaction.on_commit(lambda: evaluate_course(course_id))
    return policy, changes


# --------------------------------------------------------------------------- standing


def _live(user_id: int, course_id: int) -> Certificate | None:
    return Certificate.objects.filter(
        user_id=user_id, course_id=course_id, revoked_at__isnull=True
    ).first()


def certificate_info(cert: Certificate | None) -> dict[str, Any] | None:
    if cert is None:
        return None
    return {
        "id": cert.pk,
        "code": cert.code,
        "issued_at": cert.issued_at.isoformat(),
        "score": cert.score,
    }


def standing(user, enrollment: Enrollment, course: dict[str, Any]) -> dict[str, Any]:
    """Where this learner stands against the course's certificate, from the internal course
    summary. `parts` carries per-kind averages (mentor scores among them): staff only."""
    cert = _live(user.pk, enrollment.course_id)
    policy = CertificatePolicy.objects.filter(course_id=enrollment.course_id).first()
    if policy is None or not policy.enabled:
        return {"enabled": False, "certificate": certificate_info(cert)}
    result = scoring.course_score(course, policy.weights)
    return {
        "enabled": True,
        "threshold": policy.threshold,
        "score": result["score"],
        "missing": result["missing"],
        "parts": result["parts"],
        "eligible": _eligible(course, policy, result),
        "certificate": certificate_info(cert),
    }


def _eligible(course: dict[str, Any], policy: CertificatePolicy, result: dict) -> bool:
    if course["lessons_total"] == 0 or course["required_lessons_left"] > 0:
        return False
    if result["missing"]:
        return False
    if result["score"] is None:
        # Nothing the course weighs has a score: finishing the course is what earns it.
        return not scoring.has_scored_work(course, policy.weights)
    return round(result["score"] * 100, 2) >= policy.threshold


# --------------------------------------------------------------------------- issuing


def evaluate(enrollment: Enrollment) -> Certificate | None:
    """Issue the certificate if this enrollment has earned it (None otherwise)."""
    from apps.progress import summary

    with transaction.atomic():
        row = (
            Enrollment.objects.select_for_update(of=("self",))
            .select_related("user", "course", "version__root_node")
            .get(pk=enrollment.pk)
        )
        if row.state != Enrollment.State.ACTIVE or row.course.archived_at is not None:
            return None
        if row.version.state not in access.RELEASED:
            return None
        if Certificate.objects.filter(user_id=row.user_id, course_id=row.course_id).exists():
            return None  # issued already (or revoked: only a person brings that back)
        course = summary.course_summary(row.user, row)
        st = course["certification"]
        if not st["enabled"] or not st["eligible"]:
            return None
        policy = CertificatePolicy.objects.get(course_id=row.course_id)
        try:
            with transaction.atomic():
                cert = Certificate.objects.create(
                    user=row.user,
                    course=row.course,
                    version=row.version,
                    enrollment=row,
                    course_title=course["title"],
                    issued_at=timezone.now(),
                    score=st["score"],
                    threshold=policy.threshold,
                    weights=policy.weights,
                    breakdown=st["parts"],
                )
        except IntegrityError:
            return None  # another request issued it a moment ago
        transaction.on_commit(lambda: _tell(cert))
        return cert


def _tell(cert: Certificate) -> None:
    from apps.notifications import services as notifications

    notifications.notify(
        cert.user,
        CERTIFICATE_EARNED,
        f"You’ve earned the {cert.course_title} certificate",
        "Open it to view, print or save it as a PDF.",
        f"/certificates/{cert.code}",
        f"certificate:{cert.pk}",
    )


def evaluate_for(user_id: int, course_id: int) -> None:
    """After something changed for this person on this course. Cheap when the course has no
    certificate switched on. Never raises: it runs after the change has been saved."""
    try:
        if not CertificatePolicy.objects.filter(course_id=course_id, enabled=True).exists():
            return
        row = Enrollment.objects.filter(
            user_id=user_id, course_id=course_id, state=Enrollment.State.ACTIVE
        ).first()
        if row is not None:
            evaluate(row)
    except Exception:  # noqa: BLE001 — a certificate check must never break the learner's action
        log.exception("certificate check failed for user %s on course %s", user_id, course_id)


def evaluate_course(course_id: int) -> int:
    """Check everyone actively enrolled on the course; returns how many certificates were issued."""
    issued = 0
    for row in Enrollment.objects.filter(course_id=course_id, state=Enrollment.State.ACTIVE):
        try:
            if evaluate(row) is not None:
                issued += 1
        except Exception:  # noqa: BLE001
            log.exception("certificate check failed for enrollment %s", row.pk)
    return issued


# --------------------------------------------------------------------------- revoking


@transaction.atomic
def revoke(cert: Certificate, reason: str, *, by=None) -> Certificate:
    row = Certificate.objects.select_for_update().get(pk=cert.pk)
    if row.revoked_at is not None:
        raise Conflict("This certificate is already revoked.")
    reason = (reason or "").strip()
    if not reason:
        raise CertificateError("Say why it is being revoked.")
    if len(reason) > MAX_REASON:
        raise CertificateError(f"Keep the reason to {MAX_REASON} characters or fewer.")
    row.revoked_at = timezone.now()
    row.revoked_by = by
    row.revoked_reason = reason
    row.save(update_fields=["revoked_at", "revoked_by", "revoked_reason"])
    return row


@transaction.atomic
def restore(cert: Certificate) -> Certificate:
    row = Certificate.objects.select_for_update().get(pk=cert.pk)
    if row.revoked_at is None:
        raise Conflict("This certificate isn’t revoked.")
    if _live(row.user_id, row.course_id) is not None:
        raise Conflict("They already hold a certificate for this course.")
    row.revoked_at = None
    row.revoked_by = None
    row.revoked_reason = ""
    row.save(update_fields=["revoked_at", "revoked_by", "revoked_reason"])
    return row


def name_of(user) -> str:
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.username or user.email


def page_payload(cert: Certificate, *, staff: bool) -> dict[str, Any]:
    """What the certificate page shows. Staff also see who revoked it and why."""
    out: dict[str, Any] = {
        "code": cert.code,
        "name": name_of(cert.user),
        "employee_id": cert.user.employee_id,
        "course_title": cert.course_title,
        "course_id": cert.course_id,
        "issued_at": cert.issued_at.isoformat(),
        "score": cert.score,
        "threshold": cert.threshold,
        "revoked": cert.revoked_at is not None,
    }
    if staff:
        out.update(
            id=cert.pk,
            user_id=cert.user_id,
            version=cert.version.version,
            weights=cert.weights,
            breakdown=cert.breakdown,
            revoked_at=cert.revoked_at.isoformat() if cert.revoked_at else None,
            revoked_reason=cert.revoked_reason,
        )
    return out
