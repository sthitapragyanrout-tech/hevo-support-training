"""A scripted stand-in for the model, for development, tests and load tests.

It wraps the engine's `FakeLLM` and reads an optional JSON *control file*
(`SIMBOT_FAKE_CONTROL`) on every call, so a test can change its behaviour from
outside a running worker process:

    {"latency": [0.05, 0.4],      # seconds, uniform
     "rate_limit_rate": 0.05,     # fraction of calls answered with a 429
     "timeout_rate": 0.0,
     "eval_score": 4,             # what the fake judge awards
     "customer_turns": 3,         # the customer closes after this many replies
     "hang": {"task": "customer", "seconds": 30, "marker": "/tmp/x"},  # then die/kill it
     "fail_tasks": ["narrative"]}

Never selectable in production (`config/settings/prod.py`).
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any

from simbot_engine.llm import FakeLLM, LLMResult, LLMTimeout, RateLimited, default_handler


def _control() -> dict[str, Any]:
    path = os.environ.get("SIMBOT_FAKE_CONTROL", "")
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def _handler(task: str, system, messages):
    control = _control()
    answer = default_handler(task, system, messages)
    if task == "customer" and "customer_turns" in control:
        replies = sum(1 for m in messages if m["role"] == "user")
        if replies >= int(control["customer_turns"]):
            return {"action": "close", "message": "That's all clear, thank you!"}
        return {"action": "follow_up", "message": f"Thanks. And what about step {replies + 1}?"}
    if task == "evaluate":
        score = int(control.get("eval_score", 4))
        for key in ("communication_quality", "empathy", "accuracy", "concreteness"):
            answer[key]["score"] = score
    return answer


class ControlledFake:
    def __init__(self) -> None:
        self._inner = FakeLLM(_handler)
        self._rng = random.Random()

    def complete_json(self, *, task, system, messages, model, max_tokens, timeout) -> LLMResult:
        control = _control()
        if task in control.get("fail_tasks", []):
            from simbot_engine.llm import LLMRefused

            raise LLMRefused("scripted failure")
        low, high = control.get("latency", [0, 0])
        if high:
            time.sleep(self._rng.uniform(low, high))
        hang = control.get("hang")
        if hang and hang.get("task") == task:
            marker = hang.get("marker")
            if marker:
                Path(marker).write_text(str(os.getpid()))
            time.sleep(float(hang.get("seconds", 30)))
        if self._rng.random() < float(control.get("rate_limit_rate", 0)):
            raise RateLimited("scripted 429", retry_after=0.05)
        if self._rng.random() < float(control.get("timeout_rate", 0)):
            raise LLMTimeout("scripted timeout")
        return self._inner.complete_json(
            task=task,
            system=system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            timeout=timeout,
        )
