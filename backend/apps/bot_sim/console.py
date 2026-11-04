"""Admin Console: the practice-scenario bank and transcripts.

Trainers and administrators (`catalog.author_content`) write, review and approve
scenarios; learners never see this. Every change is audited.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.rbac import can
from apps.activities import bot_sim as cfg
from apps.audit import services as audit
from apps.console.base import ConsoleError, ConsoleView, paginate
from simbot_engine.scenario import PERSONA_TYPES, TOPIC_POOL

from . import importing, llm, payloads, scenarios
from .errors import SimError
from .models import PracticeSettings, Scenario, ScenarioImport, SimSession

AUTHOR = "catalog.author_content"
VIEW_RESULTS = "progress.view_results"
ADMIN = "catalog.publish_courseversion"  # administrators only (it also gates publishing)


def _who(user) -> str | None:
    return (user.email or user.username) if user else None


def scenario_payload(
    s: Scenario, *, uses: int | None = None, stats: dict[str, Any] | None = None
) -> dict[str, Any]:
    stats = stats or {}
    return {
        "id": s.pk,
        "topic": s.topic,
        "topic_label": TOPIC_POOL.get(s.topic, s.topic),
        "persona_type": s.persona_type,
        "issue_summary": s.issue_summary,
        "opening_message": s.opening_message,
        "personality_notes": s.personality_notes,
        "doc_hints": list(s.doc_hints or []),
        "reference_answer": s.reference_answer,
        "doc_url": s.doc_url,
        "status": s.status,
        "source": s.source,
        "created_by": _who(s.created_by),
        "approved_by": _who(s.approved_by),
        "approved_at": s.approved_at.isoformat() if s.approved_at else None,
        "created_at": s.created_at.isoformat(),
        "uses": uses if uses is not None else s.sessions.filter(preview=False).count(),
        "source_ticket_id": s.source_ticket_id,
        "auto_approved": s.auto_approved,
        "review_note": s.review_note,
        "import_run": s.import_run_id,
        # How it has gone in practice, so a poor question shows itself.
        "skips": stats.get("skips", {}),
        "finished": stats.get("finished", 0),
        "average": stats.get("average"),
    }


def full_payload(s: Scenario) -> dict[str, Any]:
    return scenario_payload(s, stats=_stats_for([s.pk])[s.pk])


def _stats_for(ids: list[int]) -> dict[int, dict[str, Any]]:
    """Skips by reason, finished tickets and their average score, for a page of scenarios."""
    out: dict[int, dict[str, Any]] = {i: {"skips": {}, "finished": 0, "scores": []} for i in ids}
    for sid, reason in SimSession.objects.filter(
        scenario_id__in=ids, abandon_reason="skipped", preview=False
    ).values_list("scenario_id", "skip_reason"):
        skips = out[sid]["skips"]
        skips[reason] = skips.get(reason, 0) + 1
    for sid, result in SimSession.objects.filter(
        scenario_id__in=ids, state=SimSession.State.FINISHED, preview=False
    ).values_list("scenario_id", "result"):
        out[sid]["finished"] += 1
        raw = ((result or {}).get("score") or {}).get("raw")
        if isinstance(raw, (int, float)):
            out[sid]["scores"].append(float(raw))
    for row in out.values():
        scores = row.pop("scores")
        row["average"] = round(sum(scores) / len(scores), 2) if scores else None
    return out


class _Base(ConsoleView):
    required_any = (AUTHOR,)

    def handle_exception(self, exc):
        if isinstance(exc, SimError):
            return Response({"detail": exc.message}, status=exc.status_code)
        return super().handle_exception(exc)


class OptionsView(_Base):
    def get(self, request: Request) -> Response:
        return Response(
            {
                "topics": [{"key": k, "label": v} for k, v in TOPIC_POOL.items()],
                "personas": list(PERSONA_TYPES),
                "model_ready": llm.configured(),
                "zendesk": importing.status(),
                "bank": importing.bank_status(),
                "topup": importing.topup_status(),
                "skips_allowed": cfg.skips_allowed(),
                "import_max": importing.MAX_PER_IMPORT,
                "counts": {
                    row["status"]: row["n"]
                    for row in Scenario.objects.values("status").annotate(n=Count("pk"))
                },
            }
        )


class ScenarioListView(_Base):
    def get(self, request: Request) -> Response:
        p = request.query_params
        qs = Scenario.objects.select_related("created_by", "approved_by").annotate(
            n_uses=Count("sessions", filter=Q(sessions__preview=False))
        )
        if p.get("status") in {s.value for s in Scenario.Status}:
            qs = qs.filter(status=p["status"])
        if p.get("topic") in TOPIC_POOL:
            qs = qs.filter(topic=p["topic"])
        if p.get("persona") in PERSONA_TYPES:
            qs = qs.filter(persona_type=p["persona"])
        if p.get("source") in {s.value for s in Scenario.Source}:
            qs = qs.filter(source=p["source"])
        if p.get("auto") == "1":
            qs = qs.filter(auto_approved=True)
        if p.get("import_run", "").isdigit():
            qs = qs.filter(import_run_id=int(p["import_run"]))
        if p.get("attention") == "1":  # sent back by learners' skips, or skipped at all
            skipped = SimSession.objects.filter(
                scenario=OuterRef("pk"), abandon_reason="skipped", preview=False
            )
            qs = qs.annotate(was_skipped=Exists(skipped)).filter(
                Q(review_note__gt="") | Q(was_skipped=True)
            )
        search = p.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(issue_summary__icontains=search) | Q(opening_message__icontains=search)
            )
        page, meta = paginate(request, qs.order_by("-created_at", "-id"))
        stats = _stats_for([s.pk for s in page])
        return Response(
            {
                "results": [scenario_payload(s, uses=s.n_uses, stats=stats[s.pk]) for s in page],
                **meta,  # type: ignore[attr-defined]
            }
        )

    def post(self, request: Request) -> Response:
        body = request.data if isinstance(request.data, dict) else {}
        scenario = scenarios.create(request.user, body)
        audit.record(
            request,
            "scenarios.create",
            target_type="scenario",
            target_id=scenario.pk,
            target_label=scenario.issue_summary,
        )
        return Response(scenario_payload(scenario), status=status.HTTP_201_CREATED)


class ScenarioDetailView(_Base):
    def get(self, request: Request, pk: int) -> Response:
        return Response(full_payload(get_object_or_404(Scenario, pk=pk)))

    def patch(self, request: Request, pk: int) -> Response:
        scenario = get_object_or_404(Scenario, pk=pk)
        body = request.data if isinstance(request.data, dict) else {}
        before = {k: getattr(scenario, k) for k in scenarios.EDITABLE}
        scenario, sent_back = scenarios.update(scenario, body)
        fields = [k for k in scenarios.EDITABLE if getattr(scenario, k) != before[k]]
        if fields:
            audit.record(
                request,
                "scenarios.update",
                target_type="scenario",
                target_id=scenario.pk,
                target_label=scenario.issue_summary,
                changes={"fields": fields, "sent_back_to_draft": sent_back},
            )
        return Response(full_payload(scenario))


class _Transition(_Base):
    action = ""
    audit_action = ""

    def apply(self, scenario: Scenario, request: Request) -> Scenario:  # pragma: no cover
        raise NotImplementedError

    def post(self, request: Request, pk: int) -> Response:
        scenario = get_object_or_404(Scenario, pk=pk)
        before = scenario.status
        scenario = self.apply(scenario, request)
        audit.record(
            request,
            self.audit_action,
            target_type="scenario",
            target_id=scenario.pk,
            target_label=scenario.issue_summary,
            changes={"from": before, "to": scenario.status},
        )
        return Response(full_payload(scenario))


class ApproveView(_Transition):
    audit_action = "scenarios.approve"

    def apply(self, scenario, request):
        return scenarios.approve(scenario, request.user)


class RetireView(_Transition):
    audit_action = "scenarios.retire"

    def apply(self, scenario, request):
        return scenarios.retire(scenario)


class RestoreView(_Transition):
    audit_action = "scenarios.restore"

    def apply(self, scenario, request):
        return scenarios.restore(scenario)


class GenerateView(_Base):
    """Queue draft scenarios from the model (never approved automatically)."""

    def post(self, request: Request) -> Response:
        from .tasks import generate_scenarios

        body = request.data if isinstance(request.data, dict) else {}
        count = body.get("count", 5)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 20:
            raise ConsoleError("Choose between 1 and 20 scenarios to generate.")
        topic = body.get("topic") or None
        persona = body.get("persona") or None
        if topic is not None and topic not in TOPIC_POOL:
            raise ConsoleError("Choose one of the listed topics.")
        if persona is not None and persona not in PERSONA_TYPES:
            raise ConsoleError("Choose one of the customer types.")
        if not llm.configured():
            raise ConsoleError(llm.NOT_CONFIGURED, status.HTTP_503_SERVICE_UNAVAILABLE)
        generate_scenarios.delay(request.user.pk, count, topic, persona)
        audit.record(
            request,
            "scenarios.generate",
            target_type="scenario",
            target_label=f"{count} drafts requested",
            changes={"count": count, "topic": topic, "persona": persona},
        )
        return Response(
            {"detail": f"Generating {count} draft scenarios."}, status=status.HTTP_202_ACCEPTED
        )


def import_payload(run: ScenarioImport) -> dict[str, Any]:
    return {
        "id": run.pk,
        "state": run.state,
        "state_label": run.get_state_display(),
        "requested": run.requested,
        "topic": run.topic,
        "examined": run.examined,
        "approved": run.approved,
        "drafted": run.drafted,
        "duplicates": run.duplicates,
        "failed": run.failed,
        "rejected": run.rejected,
        "auto_approve": run.auto_approve,
        "error": run.error,
        "started_by": _who(run.started_by),
        "trigger": run.trigger,
        "created_at": run.created_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "approved_now": run.scenarios.filter(
            status=Scenario.Status.APPROVED, auto_approved=True
        ).count(),
    }


class ImportListView(_Base):
    """Past customer queries → scenarios. Anyone who can author may see the runs; only an
    administrator may start one, because it sends customer text to a third party."""

    def get(self, request: Request) -> Response:
        runs = ScenarioImport.objects.select_related("started_by")[:10]
        return Response({"results": [import_payload(r) for r in runs]})

    def post(self, request: Request) -> Response:
        if not can(request.user, ADMIN):
            raise PermissionDenied()
        body = request.data if isinstance(request.data, dict) else {}
        topic = body.get("topic") or None
        try:
            run = importing.start_import(request.user, body.get("count", 10), topic)
        except SimError:
            audit.record(
                request,
                "scenarios.import_refused",
                target_type="scenario_import",
                target_label="Import from Zendesk refused",
                changes={"reason": importing.blocked_reason() or "invalid request"},
            )
            raise
        audit.record(
            request,
            "scenarios.import",
            target_type="scenario_import",
            target_id=run.pk,
            target_label=f"Import of {run.requested} past queries",
            changes={"count": run.requested, "topic": topic, "auto_approve": run.auto_approve},
        )
        return Response(import_payload(run), status=status.HTTP_202_ACCEPTED)


class ImportDetailView(_Base):
    def get(self, request: Request, pk: int) -> Response:
        return Response(import_payload(get_object_or_404(ScenarioImport, pk=pk)))


class ImportRevertView(_Base):
    """Send what an import approved automatically back to draft."""

    def post(self, request: Request, pk: int) -> Response:
        if not can(request.user, ADMIN):
            raise PermissionDenied()
        run = get_object_or_404(ScenarioImport, pk=pk)
        back = importing.revert_import(run)
        audit.record(
            request,
            "scenarios.import_revert",
            target_type="scenario_import",
            target_id=run.pk,
            target_label=f"Import #{run.pk} sent back to draft",
            changes={"scenarios": back},
        )
        return Response({"sent_back": back, **import_payload(run)})


class SettingsView(_Base):
    """The switches an administrator may flip."""

    def get(self, request: Request) -> Response:
        return Response(importing.status()["auto_approve"])

    def patch(self, request: Request) -> Response:
        if not can(request.user, ADMIN):
            raise PermissionDenied()
        body = request.data if isinstance(request.data, dict) else {}
        value = body.get("auto_approve_enabled")
        if not isinstance(value, bool):
            raise ConsoleError("Say whether automatic approval should be on or off.")
        row = PracticeSettings.load()
        before = row.auto_approve_enabled
        row.auto_approve_enabled = value
        row.updated_by = request.user  # type: ignore[assignment]
        row.save()
        audit.record(
            request,
            "scenarios.auto_approve",
            target_type="setting",
            target_label="Automatic approval of imported questions",
            changes={"from": before, "to": value},
        )
        return Response(importing.status()["auto_approve"])


class TranscriptView(ConsoleView):
    required_any = (VIEW_RESULTS,)

    def get(self, request: Request, session_id: int) -> Response:
        session = get_object_or_404(
            SimSession.objects.select_related("user", "activity"), pk=session_id
        )
        return Response(payloads.trainer_payload(session))


class TopUpView(_Base):
    """Switch the nightly top-up of the question bank on or off (administrators only: it
    reads Zendesk and spends model calls with nobody watching)."""

    def get(self, request: Request) -> Response:
        return Response(importing.topup_status())

    def patch(self, request: Request) -> Response:
        if not can(request.user, ADMIN):
            raise PermissionDenied()
        body = request.data if isinstance(request.data, dict) else {}
        value = body.get("enabled")
        if not isinstance(value, bool):
            raise ConsoleError("Say whether the nightly top-up should be on or off.")
        row = PracticeSettings.load()
        before = row.topup_enabled
        row.topup_enabled = value
        if value and not before:
            row.topup_resumed_at = timezone.now()  # switching it on again lifts a pause
        row.updated_by = request.user  # type: ignore[assignment]
        row.save()
        audit.record(
            request,
            "scenarios.topup",
            target_type="setting",
            target_label="Nightly top-up of practice questions",
            changes={"from": before, "to": value},
        )
        return Response(importing.topup_status())
