"""The scoring contract: turn scores in, one result document out.

This is the **only** place scores are combined, rounded and compared with the pass
mark; every layer above (database, API, attempt row) copies what it returns.

  * each dimension = the mean over the session's scored replies (docs referenced
    is the exception: a link at *any* point counts, so it is judged for the whole
    conversation — the original bot's own rule);
  * overall = the weighted mean of the six on the 1–5 scale, rounded **once**,
    half-up, to two decimals; everything else derives from that rounded value;
  * scaled = overall / 5 (the lowest possible overall is 1.0, so scaled starts at
    0.2 — it is not a percentage);
  * passed ⇔ overall ≥ threshold × 5, compared exactly (no float equality).
"""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
from typing import Any

from .config import METRIC_KEYS, METRIC_LABELS, EngineConfig
from .evaluator import LLM_DIMENSIONS, tat_label
from .scenario import Scenario
from .session import INTERN, Turn
from .text import classify_links

MAX = 5
_REVIEW_FLAGS = {"injection_suspected", "copy_of_customer"}


class NotEnoughEvidence(Exception):
    """Too few scored replies for a result (the session is abandoned, not failed)."""


class PendingScores(Exception):
    """Some replies haven't been scored yet; a result can't be built honestly."""


def _fraction(value: float | str | Fraction) -> Fraction:
    return value if isinstance(value, Fraction) else Fraction(str(value))


def round_hundredths(value: Fraction) -> int:
    """`value` × 100, rounded half-up, as an integer (no float involved)."""
    return int((value * 100 + Fraction(1, 2)) // 1)


def hundredths_to_float(hundredths: int) -> float:
    return hundredths / 100


def passes(raw_hundredths: int, threshold: float | str | Fraction) -> bool:
    return Fraction(raw_hundredths, 100) >= _fraction(threshold) * MAX


def docs_score(turns: Sequence[Turn], config: EngineConfig) -> tuple[int, str]:
    """(1–5, kind) for the whole conversation. No link → 1; a link but not to the
    documentation → 2; a link on the documentation host → 3, plus 0–2 for how
    relevant the model judged it to look (never verified against the page)."""
    interns = [t for t in turns if t.role == INTERN]
    kind = classify_links((t.text for t in interns), config.docs_hosts)
    if kind == "none":
        return 1, kind
    if kind == "other":
        return 2, kind
    relevance = max(
        (
            t.scores.docs_relevance or 0
            for t in interns
            if t.scores and t.scores.docs_relevance is not None
        ),
        default=0,
    )
    return 3 + max(0, min(2, relevance)), kind


def _docs_feedback(kind: str, relevance: int, config: EngineConfig) -> str:
    host = config.docs_hosts[0]
    if kind == "none":
        return "No documentation link was shared in this conversation."
    if kind == "other":
        return f"A link was shared, but not to {host}."
    word = {0: "doubtful", 1: "plausible", 2: "good"}.get(relevance, "plausible")
    return (
        f"Shared a {host} link. Its relevance to the question looks {word} — "
        "an AI judgment; the page itself wasn't opened."
    )


def build(
    turns: Sequence[Turn],
    *,
    config: EngineConfig,
    scenario: Scenario,
    pass_threshold: float | str | Fraction,
    narrative: dict[str, str] | None = None,
) -> dict[str, Any]:
    interns = [t for t in turns if t.role == INTERN]
    if any(t.scores is None for t in interns):
        raise PendingScores("Some replies are still being scored.")
    n = len(interns)
    if n < config.min_scored_exchanges:
        raise NotEnoughEvidence(f"{n} scored replies, {config.min_scored_exchanges} needed.")
    scored = [t.scores for t in interns if t.scores is not None]

    means: dict[str, Fraction] = {
        key: Fraction(sum(getattr(s, key) for s in scored), n) for key in (*LLM_DIMENSIONS, "tat")
    }
    docs, docs_kind = docs_score(turns, config)
    means["reference_docs"] = Fraction(docs)

    weights = {key: _fraction(config.weights[key]) for key in METRIC_KEYS}
    if sum(weights.values()) != 1:
        raise ValueError("Metric weights must add up to 1.")
    overall = sum((weights[key] * means[key] for key in METRIC_KEYS), Fraction(0))
    raw_h = round_hundredths(overall)
    passed = passes(raw_h, pass_threshold)

    avg_tat = sum(s.tat_seconds for s in scored) / n
    relevance = max((s.docs_relevance for s in scored if s.docs_relevance is not None), default=0)

    def worst_note(key: str) -> str:
        pairs = [(getattr(s, key), i, s.notes.get(key, "")) for i, s in enumerate(scored)]
        return min(pairs, key=lambda p: (p[0], -p[1]))[2]

    grounded = scenario.grounded
    metrics = []
    for key in METRIC_KEYS:
        if key in LLM_DIMENSIONS:
            feedback = worst_note(key)
            basis = "grounded" if key == "accuracy" and grounded else "model_judgment"
        elif key == "tat":
            minutes = avg_tat / 60
            feedback = (
                f"Average reply time {minutes:.1f} min ({tat_label(int(avg_tat), config.tat_bands)}); "
                "ideal is within 15 min."
            )
            basis = "deterministic"
        else:
            feedback = _docs_feedback(docs_kind, relevance, config)
            basis = "link_check+model_relevance" if docs_kind == "docs" else "link_check"
        metrics.append(
            {
                "key": key,
                "label": METRIC_LABELS[key],
                "raw": hundredths_to_float(round_hundredths(means[key])),
                "max": MAX,
                "feedback": feedback,
                "basis": basis,
            }
        )

    reasons = sorted({f for s in scored for f in s.flags if f in _REVIEW_FLAGS})
    if raw_h == MAX * 100 and n <= 2:
        reasons.append("perfect_short_session")

    return {
        "score": {
            "raw": hundredths_to_float(raw_h),
            "max": MAX,
            "scaled": float(Fraction(raw_h, MAX * 100)),
        },
        "pass_mark": {
            "raw": float(_fraction(pass_threshold) * MAX),
            "scaled": float(_fraction(pass_threshold)),
        },
        "passed": passed,
        "metrics": metrics,
        "narrative": narrative,
        "grounded": grounded,
        "exchanges": n,
        "avg_tat_seconds": round(avg_tat),
        "needs_review": bool(reasons),
        "review_reasons": reasons,
        "scenario_ref": {
            "topic": scenario.topic,
            "persona_type": scenario.persona_type,
            "issue_summary": scenario.issue_summary,
        },
    }
