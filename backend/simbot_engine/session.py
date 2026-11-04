"""The conversation as plain data, and the rules about when it nudges, closes and
how long a customer has been waiting. No clock, no database: callers pass `now`."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .config import EngineConfig

if TYPE_CHECKING:
    from .evaluator import TurnScores

CUSTOMER = "customer"
INTERN = "intern"
NUDGE = "nudge"  # a customer turn with this action never restarts the turnaround clock

NUDGE_MESSAGE = "Hi! Just checking in — any updates on this whenever you're ready."


@dataclass
class Turn:
    seq: int
    role: str  # "customer" | "intern"
    text: str
    # When it became visible (customer) or was accepted (intern): a server time.
    at: datetime
    action: str | None = None
    scores: TurnScores | None = None


def intern_turns(turns: Sequence[Turn]) -> list[Turn]:
    return [t for t in turns if t.role == INTERN]


def exchange_count(turns: Sequence[Turn]) -> int:
    return len(intern_turns(turns))


def should_close(action: str, turns: Sequence[Turn], config: EngineConfig) -> bool:
    """The customer closes, or the exchange limit is reached."""
    return action == "close" or exchange_count(turns) >= config.max_exchanges


def tat_reference(turns: Sequence[Turn]) -> datetime | None:
    """When the clock the next reply is measured against started: the most recent
    customer message that was not just a nudge."""
    for turn in reversed(turns):
        if turn.role == CUSTOMER and turn.action != NUDGE:
            return turn.at
    return None


def tat_seconds(turns: Sequence[Turn], replied_at: datetime) -> int:
    start = tat_reference(turns)
    if start is None:
        return 0
    return max(0, int((replied_at - start).total_seconds()))


# --------------------------------------------------------------------- idle

# (pattern, seconds per unit) — an intern who says "give me 20 minutes" is waited for.
_ETA = [
    (re.compile(r"\b(\d+)\s*hours?"), 3600),
    (re.compile(r"\bhalf\s+an?\s+hour\b"), 1800),
    (re.compile(r"\b(\d+)\s*min"), 60),
    (re.compile(r"\ba\s+moment\b"), 180),
    (re.compile(r"\ba\s+few\s+min"), 180),
    (re.compile(r"\bshortly\b"), 300),
    (re.compile(r"\bsoon\b"), 300),
]


def nudge_timeout(intern_text: str | None, config: EngineConfig) -> int:
    """How long to wait in silence before nudging: the time the intern said they
    needed (plus a buffer), else the default. (In the original bot this value was
    reset before it was ever used; here it applies as intended.)"""
    lower = (intern_text or "").lower()
    for pattern, unit in _ETA:
        match = pattern.search(lower)
        if match:
            try:
                n = int(match.group(1))
            except (IndexError, ValueError):
                n = 1
            return min(n * unit, 4 * 3600) + config.eta_buffer_seconds
    return config.default_nudge_seconds


def idle_decision(
    turns: Sequence[Turn],
    started_at: datetime,
    now: datetime,
    config: EngineConfig,
) -> str:
    """ "close" once the session has run too long, "nudge" once, after enough silence
    since the customer last spoke, otherwise "none"."""
    if (now - started_at).total_seconds() >= config.session_cap_seconds:
        return "close"
    if not turns or turns[-1].role != CUSTOMER or turns[-1].action == NUDGE:
        return "none"
    last_intern = next((t for t in reversed(turns) if t.role == INTERN), None)
    wait = nudge_timeout(last_intern.text if last_intern else None, config)
    if (now - turns[-1].at).total_seconds() >= wait:
        return "nudge"
    return "none"


@dataclass
class Transcript:
    """A finished conversation, ready for scoring."""

    turns: list[Turn] = field(default_factory=list)

    def as_text(self) -> str:
        return "\n".join(
            f"{'Customer' if t.role == CUSTOMER else 'Intern'}: {t.text}" for t in self.turns
        )


def to_messages(turns: Sequence[Turn]) -> list[dict[str, Any]]:
    """The conversation as chat messages, from the customer's point of view: the
    customer's own lines are the assistant's, the intern's are the user's."""
    return [
        {"role": "assistant" if t.role == CUSTOMER else "user", "content": t.text} for t in turns
    ]
