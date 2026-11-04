"""The platform's way of calling the model: the engine's `LLMClient`, wrapped with
the shared limiter, retries with backoff, per-call accounting and the per-session
token budget. Only workers ever build one; the web process makes no model calls."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.db.models import F

from simbot_engine.config import EngineConfig
from simbot_engine.llm import (
    LLMClient,
    LLMError,
    LLMRefused,
    LLMResult,
    OpenAIClient,
    RateLimited,
)

from . import gate
from .models import LLMCall, SimSession, SimTurn

log = logging.getLogger(__name__)

NOT_CONFIGURED = "Practice isn't set up yet. Ask an administrator to add the model key."


def engine_config(*, max_exchanges: int | None = None) -> EngineConfig:
    """The engine's settings, built from Django settings in one place."""
    return EngineConfig(
        customer_model=settings.SIMBOT_MODEL,
        persona_model=settings.SIMBOT_MODEL,
        eval_model=settings.SIMBOT_EVAL_MODEL,
        max_exchanges=max_exchanges or settings.SIMBOT_MAX_EXCHANGES,
        session_cap_seconds=settings.SIMBOT_SESSION_CAP_MINUTES * 60,
        max_reply_chars=settings.SIMBOT_MAX_REPLY_CHARS,
        call_timeout_seconds=settings.SIMBOT_LLM_CALL_TIMEOUT,
    )


def configured() -> bool:
    """Can a model be reached at all? (The scripted model needs no key.)"""
    return settings.SIMBOT_LLM == "fake" or bool(settings.OPENAI_API_KEY)


def build_client() -> LLMClient:
    if settings.SIMBOT_LLM == "fake":
        from .fake import ControlledFake

        return ControlledFake()
    if not settings.OPENAI_API_KEY:
        raise LLMRefused(NOT_CONFIGURED)
    return OpenAIClient(settings.OPENAI_API_KEY)


class GatedLLM:
    """An `LLMClient` that obeys the shared limits. Raises `gate.GateWait` when the
    provider rate is exhausted for longer than it is willing to sleep, so the task
    can be retried later instead of tying up a worker."""

    def __init__(
        self,
        inner: LLMClient | None = None,
        *,
        session: SimSession | None = None,
        turn: SimTurn | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.inner = inner or build_client()
        self.session = session
        self.turn = turn
        self.sleep = sleep

    def _record(self, task: str, model: str, result: LLMResult | None, status: str, started: float):
        tokens_in = result.tokens_in if result else 0
        tokens_out = result.tokens_out if result else 0
        LLMCall.objects.create(
            session=self.session,
            turn=self.turn,
            task=task,
            model=model[:60],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=int((time.monotonic() - started) * 1000),
            status=status,
        )
        if self.session is not None and (tokens_in or tokens_out):
            SimSession.objects.filter(pk=self.session.pk).update(
                tokens_used=F("tokens_used") + tokens_in + tokens_out
            )

    def _reserve(self, estimated: int) -> None:
        deadline = time.monotonic() + settings.SIMBOT_LLM_MAX_WAIT_SECONDS
        while True:
            try:
                gate.acquire(estimated)
                return
            except gate.GateWait as wait:
                if time.monotonic() + wait.seconds > deadline:
                    raise
                log.info("LLM rate gate: waiting %.1fs", wait.seconds)
                self.sleep(wait.seconds)

    def complete_json(self, **kw: Any) -> LLMResult:
        task, model = kw["task"], kw["model"]
        if self.session is not None:
            used = SimSession.objects.filter(pk=self.session.pk).values_list(
                "tokens_used", flat=True
            )[0]
            if used >= settings.SIMBOT_SESSION_TOKEN_BUDGET:
                raise gate.Paused("This practice ticket reached its length limit.")
        estimated = (
            sum(len(m["content"]) for m in kw["messages"]) // 4
            + (len(kw["system"] or "") // 4)
            + kw["max_tokens"]
        )
        last: LLMError | None = None
        for attempt in range(settings.SIMBOT_LLM_CALL_ATTEMPTS):
            self._reserve(estimated)
            started = time.monotonic()
            try:
                result = self.inner.complete_json(**kw)
            except RateLimited as exc:
                last = exc
                self._record(task, model, None, "rate_limited", started)
                gate.settle(estimated=estimated, actual=0, ok=False)
                self.sleep(min(exc.retry_after or self._backoff(attempt), 10.0))
            except LLMError as exc:
                last = exc
                kind = type(exc).__name__.lower().replace("llm", "")
                self._record(task, model, None, kind or "error", started)
                gate.settle(estimated=estimated, actual=0, ok=False)
                if not exc.retryable:
                    raise
                self.sleep(self._backoff(attempt))
            else:
                self._record(task, model, result, "ok", started)
                gate.settle(
                    estimated=estimated, actual=result.tokens_in + result.tokens_out, ok=True
                )
                return result
        assert last is not None
        raise last

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(0.5 * (2**attempt), 8.0) * random.uniform(0.7, 1.3)
