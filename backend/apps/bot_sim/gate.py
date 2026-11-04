"""The shared limiter in front of the model: requests and tokens per minute, a
daily token cap, and a circuit breaker. One database row, locked for each
decision, so it holds across every worker process.

(In-flight calls are bounded by the worker's own concurrency; a database counter
of calls "in flight" would leak whenever a worker is killed.)
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from simbot_engine.llm import LLMError

from .errors import Unavailable
from .models import LLMBudget

PAUSED = "Practice is paused for a short while. Please try again in a few minutes."


class Paused(LLMError):
    """The breaker is open or a cap was reached: don't call the model right now."""

    retryable = False

    def __init__(self, message: str = PAUSED):
        super().__init__(message)


class GateWait(Exception):
    """Over the provider's rate for now; ask again after `seconds`."""

    def __init__(self, seconds: float):
        super().__init__(f"Rate limited for {seconds:.1f}s")
        self.seconds = seconds


def _budget() -> LLMBudget:
    budget, _ = LLMBudget.objects.select_for_update().get_or_create(id=1)
    return budget


def _roll(budget: LLMBudget, now) -> None:
    if budget.window_start is None or (now - budget.window_start).total_seconds() >= 60:
        budget.window_start = now
        budget.requests_in_window = 0
        budget.tokens_in_window = 0
    if budget.day != now.date():
        budget.day = now.date()
        budget.tokens_today = 0


def assert_available(now=None) -> None:
    """For starting a session: refuse politely while the model is paused."""
    now = now or timezone.now()
    with transaction.atomic():
        budget = _budget()
        _roll(budget, now)
        budget.save()
        if budget.breaker_open_until and budget.breaker_open_until > now:
            raise Unavailable(PAUSED)
        if budget.tokens_today >= settings.SIMBOT_DAILY_TOKEN_CAP:
            raise Unavailable(PAUSED)


def acquire(estimated_tokens: int, now=None) -> None:
    """Reserve one call. Raises `Paused` (breaker/cap) or `GateWait` (rate)."""
    now = now or timezone.now()
    with transaction.atomic():
        budget = _budget()
        _roll(budget, now)
        if budget.breaker_open_until and budget.breaker_open_until > now:
            budget.save()
            raise Paused()
        if budget.tokens_today >= settings.SIMBOT_DAILY_TOKEN_CAP:
            budget.save()
            raise Paused()
        over_rate = budget.requests_in_window + 1 > settings.SIMBOT_LLM_RPM
        over_tokens = (
            budget.tokens_in_window > 0
            and budget.tokens_in_window + estimated_tokens > settings.SIMBOT_LLM_TPM
        )
        if over_rate or over_tokens:
            assert budget.window_start is not None
            wait = max(0.05, 60 - (now - budget.window_start).total_seconds())
            budget.save()
            raise GateWait(wait)
        budget.requests_in_window += 1
        budget.tokens_in_window += estimated_tokens
        budget.save()


def settle(*, estimated: int, actual: int, ok: bool, now=None) -> None:
    """Record what a call really cost and whether it worked (feeds the breaker)."""
    now = now or timezone.now()
    with transaction.atomic():
        budget = _budget()
        _roll(budget, now)
        budget.tokens_in_window = max(0, budget.tokens_in_window + actual - estimated)
        budget.tokens_today += actual
        if ok:
            budget.consecutive_failures = 0
            budget.breaker_open_until = None
        else:
            budget.consecutive_failures += 1
            if budget.consecutive_failures >= settings.SIMBOT_BREAKER_FAILURES:
                budget.breaker_open_until = now + timedelta(
                    seconds=settings.SIMBOT_BREAKER_COOLDOWN_SECONDS
                )
                budget.consecutive_failures = 0
        budget.save()
