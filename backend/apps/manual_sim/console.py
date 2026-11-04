"""Admin Console: the review queue, the rating page, and the trainer's actions on a case.

Everyone who rates (`manual_sim.rate_submissions`) and everyone who manages reviews
(`manual_sim.manage_reviews`) may open the queue; what they see is scoped by `access`: a
mentor sees their assigned learners' work and the shared pool, a trainer or admin sees
everything. Every endpoint that touches a submission goes through `access` — the generic
`can(user, action, obj)` scope check is deliberately a no-op.
"""

from __future__ import annotations

from datetime import timedelta
from statistics import median
from typing import Any

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.models import User
from apps.activities import manual_sim as cfg
from apps.audit import services as audit
from apps.console.base import ConsoleError, ConsoleView, optional_int, paginate
from apps.progress.models import ActivityProgress
from apps.progress.reporting import display_name

from . import access, assignments, eligibility, payloads, services
from .errors import SimError
from .models import SimCase, SimSubmission

S = SimSubmission.State
RATE = eligibility.RATE
MANAGE = eligibility.MANAGE


def _who(user) -> dict[str, Any] | None:
    return {"id": user.pk, "name": display_name(user), "email": user.email} if user else None


def _name(user) -> str | None:
    return display_name(user) if user else None


class _Errors:
    """Plain-language refusals from this app, in the console's shape."""

    def handle_exception(self, exc):
        if isinstance(exc, SimError):
            return Response({"detail": exc.message}, status=exc.status_code)
        return super().handle_exception(exc)  # type: ignore[misc]


class _Base(_Errors, ConsoleView):
    """Anyone who may rate or manage reviews; what they see is scoped by `access`."""

    required_any = (RATE, MANAGE)


class _ManagerBase(_Errors, ConsoleView):
    """Trainers and admins only."""

    required_action = MANAGE


def _label(sub: SimSubmission) -> str:
    return f"{sub.case.user.email} · {sub.case.activity.title} · revision {sub.revision}"


def _case_label(case: SimCase) -> str:
    return f"{case.user.email} · {case.activity.title}"


# ------------------------------------------------------------------------- the queue


def _route(sub: SimSubmission, me, now, rater_ids: set[int]) -> str:
    if access.escalated(sub, now) and sub.assigned_mentor_id is not None:
        return "escalated"
    if access.in_pool(sub, now, rater_ids):
        return "pool"
    return "mine" if sub.assigned_mentor_id == me.pk else "routed"


def _queue_row(
    sub: SimSubmission, me, now, rater_ids: set[int], attention: dict[int, bool]
) -> dict:
    activity = sub.case.activity
    holder = access.lease(sub, now)
    decision = access.rating_access(me, sub, now, rater_ids)
    return {
        "id": sub.pk,
        "learner": _who(sub.case.user),
        "activity": {"id": activity.pk, "title": activity.title},
        "course": _course_title(activity),
        "revision": sub.revision,
        "submitted_at": sub.submitted_at.isoformat(),
        "late": sub.late,
        "review_due_at": sub.review_due_at.isoformat(),
        "review_overdue": access.review_overdue(sub, now),
        "route": _route(sub, me, now, rater_ids),
        "assigned_mentor": _name(sub.assigned_mentor),
        "claimed_by": _name(holder),
        "claimed_by_me": bool(holder and holder.pk == me.pk),
        "needs_attention": attention.get(sub.case_id, False),
        "can_rate": decision.allowed,
        # The viewer's own work: listed (in All) so it isn't a mystery, never ratable by them.
        "own": sub.case.user_id == me.pk,
    }


def _course_title(activity) -> str:
    version = activity.content_node.course_version
    return version.root_node.title if version.root_node else version.course.slug


def _attention_map(case_ids: list[int]) -> dict[int, bool]:
    """Which of these cases have had several unsuccessful reviews (one query for the cases,
    one for the learners' progress)."""
    cases = list(
        SimCase.objects.filter(pk__in=case_ids)
        .select_related("user", "activity")
        .prefetch_related("submissions")
    )
    states = {
        (u, a): st
        for u, a, st in ActivityProgress.objects.filter(
            activity_id__in={c.activity_id for c in cases}
        ).values_list("user_id", "activity_id", "state")
    }
    return {
        c.pk: services.case_summary(c, state=states.get((c.user_id, c.activity_id)))[
            "needs_attention"
        ]
        for c in cases
    }


_WAITING = SimSubmission.objects.select_related(
    "case__user",
    "case__activity__content_node__course_version__root_node",
    "case__activity__content_node__course_version__course",
    "assigned_mentor",
    "claimed_by",
)


class QueueView(_Base):
    """`?tab=mine|pool|all|cases` plus `overdue=1` and `attention=1` filters."""

    def get(self, request: Request) -> Response:
        now = timezone.now()
        me = request.user
        tab = request.query_params.get("tab") or ("mine" if access.is_rater(me) else "all")
        if tab not in ("mine", "pool", "all", "cases"):
            raise ConsoleError("Choose one of the listed tabs.")
        if tab in ("all", "cases") and not access.is_manager(me):
            raise ConsoleError("Only a trainer or an admin can see that.", 403)
        if tab in ("mine", "pool") and not access.is_rater(me):
            raise ConsoleError("You can’t rate simulations.", 403)
        overdue = request.query_params.get("overdue") == "1"
        wants_attention = request.query_params.get("attention") == "1"

        if tab == "cases":
            rows = self._cases(now, overdue, wants_attention)
        else:
            rows = self._submissions(me, tab, now, overdue, wants_attention)
        page, meta = paginate(request, rows)
        return Response({"results": page, **meta, "tab": tab, "counts": self._counts(me, now)})

    def _submissions(self, me, tab: str, now, overdue: bool, wants_attention: bool) -> list[dict]:
        rater_ids = set(eligibility.raters().values_list("pk", flat=True))
        waiting = _WAITING.filter(state=S.SUBMITTED)
        # Mine and the pool are what you could rate, so never your own work; All lists it too.
        subs = list(waiting if tab == "all" else waiting.exclude(case__user=me))
        attention = _attention_map([s.case_id for s in subs])
        rows = [_queue_row(s, me, now, rater_ids, attention) for s in subs]
        if tab == "mine":
            rows = [r for r in rows if r["route"] == "mine"]
        elif tab == "pool":
            rows = [r for r in rows if r["route"] in ("pool", "escalated")]
        if overdue:
            rows = [r for r in rows if r["review_overdue"]]
        if wants_attention:
            rows = [r for r in rows if r["needs_attention"]]
        return sorted(rows, key=lambda r: (r["review_due_at"], r["id"]))

    def _cases(self, now, overdue: bool, wants_attention: bool) -> list[dict]:
        cases = list(
            SimCase.objects.filter(closed_at__isnull=True)
            .select_related(
                "user",
                "activity__content_node__course_version__root_node",
                "activity__content_node__course_version__course",
            )
            .prefetch_related("submissions")
        )
        states = {
            (u, a): st
            for u, a, st in ActivityProgress.objects.filter(
                activity_id__in={c.activity_id for c in cases}
            ).values_list("user_id", "activity_id", "state")
        }
        rows = []
        for case in cases:
            summary = services.case_summary(
                case, now=now, state=states.get((case.user_id, case.activity_id))
            )
            if summary["status"] == "passed":
                continue
            late = summary["overdue"]
            flagged = summary["needs_attention"]
            if not (late or flagged):
                continue
            if overdue and not late:
                continue
            if wants_attention and not flagged:
                continue
            rows.append(
                {
                    "case_id": case.pk,
                    "learner": _who(case.user),
                    "activity": {"id": case.activity_id, "title": case.activity.title},
                    "course": _course_title(case.activity),
                    "status": summary["status"],
                    "due_at": summary["due_at"].isoformat() if summary["due_at"] else None,
                    "overdue": late,
                    "revisions": summary["revisions"],
                    "unsuccessful": summary["unsuccessful"],
                    "needs_attention": flagged,
                }
            )
        return sorted(rows, key=lambda r: (r["due_at"] or "9", r["case_id"]))

    def _counts(self, me, now) -> dict[str, int]:
        """How much is waiting, for the tab labels."""
        rater_ids = set(eligibility.raters().values_list("pk", flat=True))
        subs = list(_WAITING.filter(state=S.SUBMITTED))
        out = {"all": len(subs)}
        if access.is_rater(me):
            routes = [_route(s, me, now, rater_ids) for s in subs if s.case.user_id != me.pk]
            out["mine"] = routes.count("mine")
            out["pool"] = routes.count("pool") + routes.count("escalated")
        return out


# ------------------------------------------------------------------ the rating page


def thread_payload(me, sub: SimSubmission, now) -> dict[str, Any]:
    case = sub.case
    activity = case.activity
    config = activity.config
    rater_ids = set(eligibility.raters().values_list("pk", flat=True))
    decision = access.rating_access(me, sub, now, rater_ids)
    holder = access.lease(sub, now)
    summary = services.case_summary(case, now=now)
    revisions = []
    for s in (
        case.submissions.select_related("rated_by")
        .prefetch_related("files", "scores")
        .order_by("revision")
    ):
        item = payloads.learner_revision(s)
        item["review_due_at"] = s.review_due_at.isoformat()
        item["withdrawn_by"] = s.withdrawn_by
        item["routing"] = s.routing
        item["assigned_mentor"] = _name(s.assigned_mentor)
        revisions.append(item)
    mentor = assignments.mentor_for(case.user, assignments.course_of(activity))
    draft = sub.draft if sub.state == S.SUBMITTED and sub.draft else None
    return {
        "id": sub.pk,
        "revision": sub.revision,
        "state": sub.state,
        "learner": _who(case.user),
        "activity": {"id": activity.pk, "title": activity.title},
        "course": _course_title(activity),
        "scenario": cfg.scenario(config),
        "handin": cfg.handin(config),
        "criteria": cfg.criteria(config),  # with the raters' guidance
        "pass_rule": cfg.pass_rule_text(config),
        "pass_threshold": cfg.pass_threshold(config),
        "min_each": cfg.min_each(config),
        "mentor_for_course": _name(mentor),
        "routing": {
            "route": _route(sub, me, now, rater_ids) if sub.state == S.SUBMITTED else None,
            "assigned_mentor": _name(sub.assigned_mentor),
            "claimed_by": _name(holder),
            "claimed_by_me": bool(holder and holder.pk == me.pk),
            "review_due_at": sub.review_due_at.isoformat(),
            "review_overdue": access.review_overdue(sub, now),
            "escalated": access.escalated(sub, now),
        },
        "access": {
            "can_rate": decision.allowed,
            "reason": "" if decision.allowed else decision.reason,
            "can_manage": access.is_manager(me),
        },
        "case": {
            "id": case.pk,
            "status": summary["status"],
            "due_at": summary["due_at"].isoformat() if summary["due_at"] else None,
            "due_basis": summary["due_basis"],
            "overdue": summary["overdue"],
            "needs_attention": summary["needs_attention"],
            "unsuccessful": summary["unsuccessful"],
            "closed_reason": case.closed_reason,
            "close_note": case.close_note if access.is_manager(me) else "",
        },
        "draft": (
            {
                **draft,
                "by": _name(sub.draft_by),
                "mine": bool(sub.draft_by_id == me.pk),
            }
            if draft
            else None
        ),
        "revisions": revisions,
    }


def _visible(request: Request, pk: int) -> SimSubmission:
    sub = get_object_or_404(_WAITING, pk=pk)
    # The same answer as "doesn't exist": nobody learns which ids are taken.
    if not access.can_see(request.user, sub):
        raise Http404()
    return sub


class ThreadView(_Base):
    def get(self, request: Request, pk: int) -> Response:
        return Response(thread_payload(request.user, _visible(request, pk), timezone.now()))


class _Act(_Base):
    """A mutation of one submission: do it, audit it, return the refreshed thread."""

    action = ""

    def perform(self, request: Request, sub: SimSubmission) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def post(self, request: Request, pk: int) -> Response:
        sub = _visible(request, pk)
        body = request.data if isinstance(request.data, dict) else {}
        self.body = body
        changes = self.perform(request, sub)
        if self.action:
            audit.record(
                request,
                self.action,
                target_type="submission",
                target_id=sub.pk,
                target_label=_label(sub),
                changes=changes,
            )
        fresh = _visible(request, pk)
        return Response(thread_payload(request.user, fresh, timezone.now()))


class ClaimView(_Act):
    def perform(self, request, sub):
        holder = access.lease(sub, timezone.now())
        services.claim(request.user, sub.pk)
        if holder is not None and holder.pk != request.user.pk:
            self.action = "simulations.take_over"
            return {"from": holder.email}
        return {}


class ReleaseView(_Act):
    def perform(self, request, sub):
        holder = access.lease(sub, timezone.now())
        services.release(request.user, sub.pk)
        if holder is not None and holder.pk != request.user.pk:
            self.action = "simulations.release_other"
            return {"from": holder.email}
        return {}


class ReassignView(_Act):
    action = "simulations.reassign"

    def perform(self, request, sub):
        raw = self.body.get("mentor_id")
        mentor = None
        if raw is not None:
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise ConsoleError("Choose a mentor, or the shared pool.")
            mentor = get_object_or_404(User, pk=raw)
        before = _name(sub.assigned_mentor) or "shared pool"
        services.reassign(request.user, sub.pk, mentor)
        return {"from": before, "to": _name(mentor) or "shared pool"}


class DraftView(_Act):
    def perform(self, request, sub):
        services.save_draft(
            request.user,
            sub.pk,
            self.body.get("scores"),
            self.body.get("feedback"),
            self.body.get("comment"),
        )
        return {}


class RateView(_Act):
    action = "simulations.rate"

    def perform(self, request, sub):
        done = services.rate(
            request.user,
            sub.pk,
            self.body.get("scores"),
            self.body.get("feedback"),
            self.body.get("comment"),
        )
        return {"revision": done.revision, "score": done.raw_score, "passed": done.passed}


# ------------------------------------------------------------- the case, for trainers


class _CaseAct(_ManagerBase):
    action = ""

    def run(self, request: Request, case_id: int, body: dict) -> SimCase:  # pragma: no cover
        raise NotImplementedError

    def post(self, request: Request, case_id: int) -> Response:
        body = request.data if isinstance(request.data, dict) else {}
        case = self.run(request, case_id, body)
        audit.record(
            request,
            self.action,
            target_type="case",
            target_id=case.pk,
            target_label=_case_label(case),
            changes=self.changes(body, case),
        )
        summary = services.case_summary(case, now=timezone.now())
        return Response(
            {
                "case": {
                    "id": case.pk,
                    "status": summary["status"],
                    "due_at": summary["due_at"].isoformat() if summary["due_at"] else None,
                    "overdue": summary["overdue"],
                }
            }
        )

    def changes(self, body: dict, case: SimCase) -> dict:
        return {"reason": str(body.get("reason", ""))[:500]}


class ExtendView(_CaseAct):
    action = "simulations.extend"

    def run(self, request, case_id, body):
        return services.extend(request.user, case_id, body.get("days"), body.get("reason"))

    def changes(self, body, case):
        return {"days": body.get("days"), "reason": str(body.get("reason", ""))[:500]}


class WaiveView(_CaseAct):
    action = "simulations.waive"

    def run(self, request, case_id, body):
        return services.waive(request.user, case_id, body.get("reason"))


class CloseView(_CaseAct):
    action = "simulations.close"

    def run(self, request, case_id, body):
        return services.close(request.user, case_id, body.get("reason"))


class ReopenView(_CaseAct):
    action = "simulations.reopen"

    def run(self, request, case_id, body):
        return services.reopen(request.user, case_id, body.get("reason"))


# -------------------------------------------------------- mentors and turnaround


class MentorsView(_ManagerBase):
    """Who a single submission may be sent to: active people who may rate."""

    def get(self, request: Request) -> Response:
        learner_id = optional_int(request.query_params.get("learner"))
        people = eligibility.raters().exclude(pk=learner_id) if learner_id else eligibility.raters()
        return Response(
            {"results": [_who(u) for u in people.order_by("first_name", "last_name", "email")]}
        )


class StatsView(_ManagerBase):
    """How long reviews take, kept apart from the learners' deadlines: the last 30 days, and
    what is overdue right now."""

    def get(self, request: Request) -> Response:
        now = timezone.now()
        since = now - timedelta(days=30)
        rated = list(
            SimSubmission.objects.filter(state=S.RATED, rated_at__gte=since)
            .select_related("rated_by")
            .values_list(
                "rated_by_id",
                "rated_by__first_name",
                "rated_by__last_name",
                "rated_by__email",
                "submitted_at",
                "rated_at",
                "review_due_at",
            )
        )
        per: dict[int, dict] = {}
        hours: list[float] = []
        for uid, first, last, email, submitted, done, due in rated:
            if uid is None or done is None:
                continue
            h = (done - submitted).total_seconds() / 3600
            hours.append(h)
            row = per.setdefault(
                uid,
                {
                    "id": uid,
                    "name": f"{first} {last}".strip() or email,
                    "rated": 0,
                    "hours": [],
                    "late": 0,
                },
            )
            row["rated"] += 1
            row["hours"].append(h)
            row["late"] += 1 if done > due else 0
        waiting = list(SimSubmission.objects.filter(state=S.SUBMITTED))
        return Response(
            {
                "window_days": 30,
                "rated": len(hours),
                "median_hours": round(median(hours), 1) if hours else None,
                "waiting": len(waiting),
                "waiting_overdue": sum(1 for s in waiting if access.review_overdue(s, now)),
                "escalated": sum(1 for s in waiting if access.escalated(s, now)),
                "mentors": sorted(
                    (
                        {
                            "id": r["id"],
                            "name": r["name"],
                            "rated": r["rated"],
                            "median_hours": round(median(r["hours"]), 1),
                            "reviewed_late": r["late"],
                        }
                        for r in per.values()
                    ),
                    key=lambda r: (-r["rated"], r["name"]),
                ),
            }
        )
