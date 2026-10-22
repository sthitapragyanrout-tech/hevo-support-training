"""
The quiz (`mcq`) activity: what a learner may see, how answers are judged, and
what is revealed afterwards. Pure functions over the activity's `config` — no
Django, no database — so every rule here is unit-testable and the answer key
has exactly one door out of the server (`reveal`).

A question is `{text, choices: [str], answer: int | [int], explanation?: str}`.
`answer` as a list means "select all that apply". Questions are addressed by
position: a published version never changes, so positions are stable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_PASS_THRESHOLD = 0.7


class InvalidAnswers(ValueError):
    """The submission isn't a complete, well-formed set of answers."""


@dataclass(frozen=True)
class ScoreResult:
    score: float  # 0–1: correct questions / total
    correct: int
    total: int
    passed: bool
    needed: int  # questions that must be right to pass
    results: list[bool]  # per question, in order


def questions(config: Any) -> list[dict[str, Any]]:
    raw = config.get("questions") if isinstance(config, dict) else None
    return [q for q in raw if isinstance(q, dict)] if isinstance(raw, list) else []


def pass_threshold(config: Any) -> float:
    value = config.get("pass_threshold") if isinstance(config, dict) else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return DEFAULT_PASS_THRESHOLD
    return float(value)


def is_multiple(question: dict[str, Any]) -> bool:
    return isinstance(question.get("answer"), list)


def correct_choices(question: dict[str, Any]) -> list[int]:
    answer = question.get("answer")
    raw = answer if isinstance(answer, list) else [answer]
    return sorted({a for a in raw if isinstance(a, int) and not isinstance(a, bool)})


def _choices(question: dict[str, Any]) -> list[str]:
    raw = question.get("choices")
    return [str(c) for c in raw] if isinstance(raw, list) else []


def required_correct(config: Any) -> int:
    """How many questions must be right to pass (for "you need 4"). Compared
    in whole percent, the way the pass mark is shown and typed: with a 67%
    pass mark, 2 of 3 (66.7%) passes."""
    total = len(questions(config))
    if total == 0:
        return 0
    target = round(pass_threshold(config) * 100)
    for needed in range(total + 1):
        if round(needed / total * 100) >= target:
            return needed
    return total


# ------------------------------------------------------------ what learners see


def learner_view(config: Any) -> dict[str, Any]:
    """Everything a learner needs to answer — never the answer key or the
    explanations."""
    return {
        "questions": [
            {"text": q.get("text", ""), "choices": _choices(q), "multiple": is_multiple(q)}
            for q in questions(config)
        ],
        "pass_threshold": pass_threshold(config),
    }


# ------------------------------------------------------------------ authoring


def check_complete(config: Any) -> list[str]:
    """Cross-checks the JSON Schema can't express; strict (publishable) only."""
    problems: list[str] = []
    for number, question in enumerate(questions(config), start=1):
        prefix = f"Question {number}"
        if not str(question.get("text", "")).strip():
            problems.append(f"{prefix} needs some text.")
        choices = _choices(question)
        if len(choices) < 2:
            problems.append(f"{prefix} needs at least 2 choices.")
        if any(not c.strip() for c in choices):
            problems.append(f"{prefix} has an empty choice.")
        correct = correct_choices(question)
        if not correct:
            problems.append(f"{prefix} needs a correct answer.")
        elif any(c >= len(choices) for c in correct):
            problems.append(f"{prefix} has a correct answer that isn’t one of its choices.")
    return problems


# -------------------------------------------------------------------- judging


def validate_answers(config: Any, answers: Any) -> list[list[int]]:
    """Normalise a submission to one sorted list of choice indexes per
    question, or raise `InvalidAnswers` with a sentence the learner can read."""
    qs = questions(config)
    if not isinstance(answers, list) or len(answers) != len(qs):
        raise InvalidAnswers("Answer every question before you submit.")
    normalised: list[list[int]] = []
    for number, (question, picked) in enumerate(zip(qs, answers, strict=True), start=1):
        if not isinstance(picked, list) or not picked:
            raise InvalidAnswers(f"Question {number} hasn’t been answered.")
        if not all(isinstance(p, int) and not isinstance(p, bool) for p in picked):
            raise InvalidAnswers(f"Question {number} has an invalid answer.")
        unique = sorted(set(picked))
        if unique[0] < 0 or unique[-1] >= len(_choices(question)):
            raise InvalidAnswers(f"Question {number} has an invalid answer.")
        if not is_multiple(question) and len(unique) != 1:
            raise InvalidAnswers(f"Question {number} takes a single answer.")
        normalised.append(unique)
    return normalised


def score(config: Any, answers: list[list[int]]) -> ScoreResult:
    """All-or-nothing per question: the picked set must equal the correct set."""
    qs = questions(config)
    results = [picked == correct_choices(q) for q, picked in zip(qs, answers, strict=True)]
    total = len(qs)
    correct = sum(results)
    needed = required_correct(config)
    return ScoreResult(
        score=correct / total if total else 0.0,
        correct=correct,
        total=total,
        passed=total > 0 and correct >= needed,
        needed=needed,
        results=results,
    )


def judge(config: Any, raw_answers: Any) -> tuple[ScoreResult, list[list[int]]]:
    """Validate then score one submission (the registry's `score` hook)."""
    answers = validate_answers(config, raw_answers)
    return score(config, answers), answers


def review(config: Any, result: ScoreResult, *, reveal: bool) -> list[dict[str, Any]]:
    """Per-question feedback. `reveal` is the only switch that lets the answer
    key and explanations out (see the reveal policy in progress.services)."""
    items: list[dict[str, Any]] = []
    for question, ok in zip(questions(config), result.results, strict=True):
        item: dict[str, Any] = {"correct": ok}
        if reveal:
            item["correct_answers"] = correct_choices(question)
            explanation = question.get("explanation")
            if isinstance(explanation, str) and explanation.strip():
                item["explanation"] = explanation
        items.append(item)
    return items
