"""The one interface between the engine and a language model.

`LLMClient.complete_json` returns the model's JSON text plus usage, or raises one
of the errors below. Real adapters (OpenAI here) and `FakeLLM` (tests, load
tests) implement it; rate limiting, retries and cost accounting wrap it in the
platform's adapter layer, not here.
"""

from __future__ import annotations

import json
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

TASKS = ("persona", "customer", "evaluate", "narrative")


class LLMError(Exception):
    """The model call failed. `retryable` says whether trying again can help."""

    retryable = True

    def __init__(self, message: str = "The language model call failed."):
        super().__init__(message)
        self.message = message


class RateLimited(LLMError):
    def __init__(
        self, message: str = "Rate limited by the provider.", retry_after: float | None = None
    ):
        super().__init__(message)
        self.retry_after = retry_after


class LLMTimeout(LLMError):
    pass


class LLMRefused(LLMError):
    """A bad request, an auth problem or a refusal: retrying the same call won't help."""

    retryable = False


class BadModelOutput(LLMError):
    """The model answered, but not with the JSON we asked for."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


class LLMClient(Protocol):
    def complete_json(
        self,
        *,
        task: str,
        system: str | None,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        timeout: float,
    ) -> LLMResult: ...


def parse_json(text: str) -> dict[str, Any]:
    """The model's JSON object, tolerating a Markdown code fence around it."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    try:
        value = json.loads(cleaned.strip())
    except ValueError as exc:
        raise BadModelOutput("The model didn’t return valid JSON.") from exc
    if not isinstance(value, dict):
        raise BadModelOutput("The model didn’t return a JSON object.")
    return value


class OpenAIClient:
    """Adapter for OpenAI chat completions (JSON mode)."""

    def __init__(self, api_key: str, *, base_url: str | None = None):
        import openai  # imported lazily: the engine runs without the SDK in tests

        self._openai = openai
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    def complete_json(
        self,
        *,
        task: str,
        system: str | None,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        timeout: float,
    ) -> LLMResult:
        openai = self._openai
        payload = ([{"role": "system", "content": system}] if system else []) + messages
        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(  # type: ignore[call-overload]
                model=model,
                messages=payload,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                timeout=timeout,
            )
        except openai.RateLimitError as exc:
            header = getattr(getattr(exc, "response", None), "headers", {}).get("retry-after")
            try:
                retry_after = float(header) if header is not None else None
            except ValueError:
                retry_after = None
            raise RateLimited(retry_after=retry_after) from exc
        except openai.APITimeoutError as exc:
            raise LLMTimeout("The model took too long to answer.") from exc
        except (
            openai.AuthenticationError,
            openai.BadRequestError,
            openai.PermissionDeniedError,
        ) as exc:
            raise LLMRefused("The model request was refused.") from exc
        except (openai.APIConnectionError, openai.InternalServerError) as exc:
            raise LLMError("The model service is unavailable.") from exc
        except openai.APIError as exc:
            raise LLMError("The model call failed.") from exc
        choice = response.choices[0]
        usage = response.usage
        return LLMResult(
            text=choice.message.content or "",
            model=response.model or model,
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=int((time.monotonic() - started) * 1000),
        )


Handler = Callable[[str, str | None, list[dict[str, str]]], dict[str, Any] | str]


class FakeLLM:
    """A deterministic stand-in for tests and load tests. `handler(task, system,
    messages)` returns the JSON object (or raw text) to answer with; it may also
    raise an `LLMError` to inject a failure. Records every call."""

    def __init__(
        self,
        handler: Handler | None = None,
        *,
        latency: Callable[[str], float] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.handler = handler or default_handler
        self.latency = latency
        self.sleep = sleep
        self.calls: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        task: str,
        system: str | None,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        timeout: float,
    ) -> LLMResult:
        self.calls.append(
            {
                "task": task,
                "system": system,
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
            }
        )
        delay = self.latency(task) if self.latency else 0.0
        if delay:
            self.sleep(delay)
        answer = self.handler(task, system, messages)
        text = answer if isinstance(answer, str) else json.dumps(answer)
        size = sum(len(m["content"]) for m in messages) + len(system or "")
        return LLMResult(
            text=text,
            model=model,
            tokens_in=size // 4,
            tokens_out=len(text) // 4,
            latency_ms=int(delay * 1000),
        )


_SCRIPTED_QUESTIONS = (
    ("source_setup", "How do I connect MySQL as a source?", "Hello, how do I connect my MySQL database to Hevo? I am not sure which permissions it needs."),
    ("billing", "How are billable events counted?", "Hi, how does Hevo count billable events each month? I want to understand my plan."),
    ("alerts", "How do I get Slack alerts for failures?", "Hello, can I get a Slack message when a pipeline fails? Where do I set that up?"),
    ("team_management", "How do I invite a colleague?", "Hi, how do I add a teammate to our Hevo account with read only access?"),
    ("destination_setup", "What does Hevo need to load into BigQuery?", "Hello, what permissions does Hevo need on BigQuery before I add it as a destination?"),
    ("sync_modes", "What is the difference between full and incremental load?", "Hi, what is the difference between full load and incremental load, and when should I use each?"),
)  # fmt: skip


def default_handler(
    task: str, system: str | None, messages: list[dict[str, str]]
) -> dict[str, Any]:
    """Reasonable canned answers for every task, so a whole conversation can run
    without a model. Not clever: tests that care supply their own handler."""
    if task == "persona":
        return {
            "persona_type": "non-technical",
            "issue_summary": "How do I set up a MySQL source?",
            "initial_message": "Hello, how do I connect my MySQL database to Hevo?",
            "personality_notes": "Polite, unsure about jargon, wants simple steps.",
            "doc_hints": ["mysql", "source", "prerequisites"],
        }
    if task == "rewrite":
        # A scripted answer for tests and development. Words in the ticket steer it:
        # "[[reject]]" → not usable, "[[unsure]]" → usable but low confidence. Otherwise the
        # question depends on the ticket text, so a batch of tickets gives different questions.
        text = " ".join(m["content"] for m in messages)
        if "[[reject]]" in text:
            return {"answerable": False, "reason": "needs account investigation"}
        topic, summary, opening = _SCRIPTED_QUESTIONS[
            zlib.crc32(text.encode()) % len(_SCRIPTED_QUESTIONS)
        ]
        return {
            "answerable": True,
            "confidence": 0.7 if "[[unsure]]" in text else 0.92,
            "single_question": True,
            "language": "en",
            "reason": "can be answered from the documentation",
            "topic": topic,
            "persona_type": "non-technical",
            "issue_summary": summary,
            "initial_message": opening,
            "personality_notes": "Polite, unsure about jargon, wants simple steps.",
            "doc_hints": ["hevo", topic.split("_")[0], "setup"],
        }
    if task == "customer":
        replies = sum(1 for m in messages if m["role"] == "user")
        if replies >= 3:
            return {"action": "close", "message": "That's all clear, thank you!"}
        return {"action": "follow_up", "message": f"Thanks. And what about step {replies + 1}?"}
    if task == "evaluate":
        return {
            "communication_quality": {"score": 4, "note": "Clear and well structured."},
            "empathy": {"score": 4, "note": "Friendly and acknowledging."},
            "accuracy": {"score": 4, "note": "Answers the question asked."},
            "concreteness": {"score": 4, "note": "Specific, actionable steps."},
            "docs_relevance": {"score": 1, "note": "The link looks relevant."},
        }
    if task == "narrative":
        return {
            "strengths": "Clear step-by-step instructions.",
            "weaknesses": "Could confirm the customer's setup before answering.",
            "overall": "A solid, friendly practice session.",
        }
    raise LLMRefused(f"Unknown task {task!r}")
