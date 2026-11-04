"""What the API says about a mentor-rated simulation. One place, so a learner never sees what
only raters and trainers should (the guidance, who claimed it, a draft, how it was routed, the
internal "needs attention" flag, a trainer's note)."""

from __future__ import annotations

from typing import Any

from django.conf import settings

from apps.activities import manual_sim as cfg
from apps.catalog.models import Activity
from apps.progress.reporting import display_name

from . import files, services
from .models import SimCase, SimSubmission, SubmissionFile

S = SimSubmission.State


def file_url(file: SubmissionFile) -> str:
    return f"/api/v1/rated-sims/files/{file.uuid}/"


def file_payload(file: SubmissionFile) -> dict[str, Any]:
    return {
        "id": str(file.uuid),
        "name": file.original_name,
        "type": file.content_type,
        "size_bytes": file.size_bytes,
        "url": file_url(file),
        "inline": file.content_type.startswith("image/"),
    }


def _rating(sub: SimSubmission) -> dict[str, Any] | None:
    if sub.state != S.RATED:
        return None
    return {
        "raw_score": sub.raw_score,  # out of 5; never a percentage
        "passed": sub.passed,
        "comment": sub.overall_comment,
        "rated_at": sub.rated_at.isoformat() if sub.rated_at else None,
        "mentor": display_name(sub.rated_by) if sub.rated_by else None,
        "scores": [
            {
                "key": s.criterion_key,
                "label": s.label,
                "score": s.score,
                "max": s.max_score,
                "feedback": s.feedback,
            }
            for s in sub.scores.all()
        ],
    }


def learner_revision(sub: SimSubmission) -> dict[str, Any]:
    """One revision, as its author sees it: an allowlist, field by field."""
    return {
        "id": sub.pk,
        "revision": sub.revision,
        "state": sub.state,
        "submitted_at": sub.submitted_at.isoformat(),
        "late": sub.late,
        "answer": sub.answer,
        "links": list(sub.links or []),
        "files": [file_payload(f) for f in sub.files.all()],
        "expected_by": sub.review_due_at.isoformat() if sub.state == S.SUBMITTED else None,
        "rating": _rating(sub),
    }


def learner_view(user, activity: Activity, now) -> dict[str, Any]:
    case = (
        SimCase.objects.filter(user=user, activity=activity)
        .select_related("user", "activity")
        .first()
    )
    subs = (
        list(
            case.submissions.select_related("rated_by")
            .prefetch_related("files", "scores")
            .order_by("revision")
        )
        if case
        else []
    )
    config = activity.config
    summary = services.case_summary(case, now=now) if case else None
    status = summary["status"] if summary else "not_opened"
    waiting = summary["waiting"] if summary else None
    can_submit = status in ("not_opened", "not_submitted", "changes_requested")
    return {
        "activity": {"id": activity.pk, "title": activity.title},
        "config": cfg.learner_view(config),
        "limits": {
            **files.limits(),
            "allowed": cfg.allow_files(config),
            "max_answer_chars": settings.MANUAL_SIM_MAX_ANSWER_CHARS,
            "max_links": settings.MANUAL_SIM_MAX_LINKS,
        },
        "case": {
            "status": status,
            "due_at": (summary["due_at"].isoformat() if summary and summary["due_at"] else None),
            "due_basis": summary["due_basis"] if summary else None,
            "overdue": bool(summary and summary["overdue"]),
            "revisions": summary["revisions"] if summary else 0,
            "can_submit": can_submit,
            "can_withdraw": bool(
                waiting is not None
                and not services.access.lease(waiting, now)
                and not waiting.draft
            ),
            "closed_at": case.closed_at.isoformat() if case and case.closed_at else None,
        },
        "revisions": [learner_revision(s) for s in subs],
    }
