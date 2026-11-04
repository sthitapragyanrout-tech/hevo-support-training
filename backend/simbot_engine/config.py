"""Everything tunable about the engine, passed in by the caller. The engine reads
no environment variables and no Django settings."""

from __future__ import annotations

from dataclasses import dataclass, field

# The six metrics, in the order the results are shown (HALO outcome metric keys).
METRIC_KEYS = (
    "communication",
    "empathy",
    "tat",
    "concreteness",
    "accuracy",
    "reference_docs",
)

METRIC_LABELS = {
    "communication": "Communication",
    "empathy": "Empathy",
    "tat": "Turnaround",
    "concreteness": "Concreteness",
    "accuracy": "Accuracy",
    "reference_docs": "Docs referenced",
}

# Same weights as the original bot; they sum to 1.0.
DEFAULT_WEIGHTS = {
    "communication": 0.15,
    "empathy": 0.15,
    "accuracy": 0.25,
    "reference_docs": 0.15,
    "concreteness": 0.20,
    "tat": 0.10,
}

# (upper bound in seconds, score). Anything slower scores 1.
DEFAULT_TAT_BANDS = ((300, 5), (600, 4), (900, 3), (1800, 2))


@dataclass(frozen=True)
class EngineConfig:
    customer_model: str = "gpt-4o-mini"
    eval_model: str = "gpt-4o-mini"
    persona_model: str = "gpt-4o-mini"
    max_exchanges: int = 6
    min_scored_exchanges: int = 2
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    tat_bands: tuple[tuple[int, int], ...] = DEFAULT_TAT_BANDS
    docs_hosts: tuple[str, ...] = ("docs.hevodata.com",)
    # Idle handling, as in the original bot.
    default_nudge_seconds: int = 10 * 60
    eta_buffer_seconds: int = 3 * 60
    session_cap_seconds: int = 90 * 60
    max_reply_chars: int = 4000
    call_timeout_seconds: float = 30.0
    max_tokens_customer: int = 400
    max_tokens_eval: int = 700
    max_tokens_persona: int = 600
    max_tokens_rewrite: int = 700
    max_tokens_narrative: int = 450
