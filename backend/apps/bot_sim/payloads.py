"""What the API says about a practice ticket. One place, so the learner never sees
what only a trainer should (scores mid-session, scenario notes, review flags)."""

from __future__ import annotations

from typing import Any

from .models import SimSession, SimTurn

# What a learner may be told about a finished ticket — an allowlist, so a field added to
# the stored result later (review flags, the customer type, scenario notes…) stays
# trainer-only until someone decides otherwise here. Trainers get `trainer_payload`.
_RESULT_KEYS = (
    "state",
    "passed",
    "attempt",
    "attempts_left",
    "grounded",
    "exchanges",
    "avg_tat_seconds",
)
_SCORE_KEYS = ("raw", "max", "scaled")
_PASS_MARK_KEYS = ("raw", "scaled")
_QUOTA_KEYS = ("done", "required")
_METRIC_KEYS = ("key", "label", "raw", "max", "feedback", "basis")
_NARRATIVE_KEYS = ("strengths", "weaknesses", "overall")


def _pick(source: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: source[k] for k in keys if isinstance(source, dict) and k in source}


def _thread(turns: list[SimTurn]) -> list[dict[str, Any]]:
    out = []
    for index, t in enumerate(turns):
        item: dict[str, Any] = {
            "seq": t.seq,
            "role": t.role,
            "text": t.text,
            "at": t.at.isoformat(),
            "kind": t.action if t.action in ("nudge", "close") else "message",
        }
        if t.role == SimTurn.Role.INTERN:
            answered = index + 1 < len(turns)
            item["status"] = (
                "failed" if t.job_state == SimTurn.Job.FAILED else "sent" if answered else "sending"
            )
            if t.job_state == SimTurn.Job.FAILED:
                item["error"] = t.job_error
        out.append(item)
    return out


def learner_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    shown = _pick(result, _RESULT_KEYS)
    shown["score"] = _pick(result.get("score"), _SCORE_KEYS)
    shown["pass_mark"] = _pick(result.get("pass_mark"), _PASS_MARK_KEYS)
    if isinstance(result.get("quota"), dict):
        shown["quota"] = _pick(result["quota"], _QUOTA_KEYS)
    shown["metrics"] = [_pick(m, _METRIC_KEYS) for m in result.get("metrics") or []]
    narrative = result.get("narrative")
    shown["narrative"] = _pick(narrative, _NARRATIVE_KEYS) if isinstance(narrative, dict) else None
    return shown


def session_payload(session: SimSession) -> dict[str, Any]:
    turns = list(session.turns.order_by("seq"))
    last = turns[-1] if turns else None
    live = session.state == SimSession.State.OPEN
    failed = next((t for t in reversed(turns) if t.job_state == SimTurn.Job.FAILED), None)
    interns = sum(t.role == SimTurn.Role.INTERN for t in turns)
    customer_turns = [t for t in turns if t.role == SimTurn.Role.CUSTOMER and t.action != "nudge"]
    max_exchanges = int((session.config_snapshot or {}).get("max_exchanges", 6))
    return {
        "id": session.pk,
        "activity_id": session.activity_id,
        "state": session.state,
        "preview": session.preview,
        "subject": session.scenario_snapshot.get("issue_summary", ""),
        "thread": _thread(turns),
        "can_reply": bool(live and last and last.role == SimTurn.Role.CUSTOMER),
        "waiting_for_customer": bool(
            live and last and last.role == SimTurn.Role.INTERN and failed is None
        ),
        "failed": bool(failed and live),
        "failed_message": failed.job_error if failed else "",
        "exchanges": interns,
        "max_exchanges": max_exchanges,
        "started_at": session.started_at.isoformat(),
        # When the customer last spoke: how long they have been waiting.
        "customer_waiting_since": customer_turns[-1].at.isoformat() if customer_turns else None,
        "feedback_pending": session.state == SimSession.State.FINISHING,
        "abandoned_reason": session.abandon_reason
        if session.state == SimSession.State.ABANDONED
        else "",
        "result": learner_result(session.result)
        if session.state == SimSession.State.FINISHED
        else None,
    }


def trainer_payload(session: SimSession) -> dict[str, Any]:
    """The whole transcript with each reply's scores and notes, for trainers."""
    turns = list(session.turns.order_by("seq"))
    return {
        "id": session.pk,
        "learner": {
            "id": session.user_id,
            "name": (
                f"{session.user.first_name} {session.user.last_name}".strip() or session.user.email
            ),
        },
        "activity": {"id": session.activity_id, "title": session.activity.title},
        "state": session.state,
        "preview": session.preview,
        "repeated": session.repeated,
        "abandon_reason": session.abandon_reason,
        "scenario": session.scenario_snapshot,
        "started_at": session.started_at.isoformat(),
        "finished_at": session.finished_at.isoformat() if session.finished_at else None,
        "tokens_used": session.tokens_used,
        "models": {
            "customer": session.config_snapshot.get("customer_model"),
            "evaluator": session.config_snapshot.get("eval_model"),
        },
        "turns": [
            {
                "seq": t.seq,
                "role": t.role,
                "text": t.text,
                "at": t.at.isoformat(),
                "action": t.action,
                "tat_seconds": t.tat_seconds,
                "scores": t.scores,
                "job_state": t.job_state,
                "job_error": t.job_error,
            }
            for t in turns
        ],
        "result": session.result,
    }
