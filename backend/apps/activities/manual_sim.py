"""The mentor-rated simulation: configuration, what a learner may see of it, the rating
arithmetic, and when it can hold a lesson up.

`config` keys:

  scenario        what the learner is asked to do (text)
  handin          what to hand in (text, optional)
  criteria        1–8 of {key, label, description, guidance}; `description` is shown to the
                  learner, `guidance` (what a 1, 3 and 5 look like) only to raters
  pass_threshold  scaled 0–1 (0.7 ≙ 3.5 out of 5); the Studio shows it out of 5
  min_each        optional: no criterion may be scored below this (0 = off)
  allow_files     whether screenshots / PDFs may be attached (default on)
  due_days        days from first opening to hand in (0 = no deadline)
  revision_days   days to revise after changes are requested (0 = no deadline)
  review_hours    the mentor's review target for this activity (blank = the platform's)
  holds_next      "submit" (default): handing the work in opens the next lesson, and the lesson
                  counts as complete once the rating passes; "pass": the next lesson stays
                  locked until the rating passes

Completion is `external`: only a mentor's rating completes it, never the learner. A rating
is built the way a practice ticket is (the contract in `simbot_engine.outcome`): the mean of
the criteria on the 1–5 scale, rounded once, half-up, to two decimals; scaled = overall / 5;
passed ⇔ overall ≥ threshold × 5 (compared exactly) and, when set, no criterion below
`min_each`. It is never shown as a percentage.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from simbot_engine.outcome import hundredths_to_float, passes, round_hundredths

MAX_SCORE = 5
MIN_SCORE = 1
MAX_CRITERIA = 8
DEFAULT_THRESHOLD = 0.7
MIN_THRESHOLD, MAX_THRESHOLD = 0.2, 1.0
DEFAULT_DUE_DAYS = 7
DEFAULT_REVISION_DAYS = 3
MAX_DAYS = 365
MAX_REVIEW_HOURS = 24 * 30
HOLDS_NEXT = ("submit", "pass")
DEFAULT_HOLDS_NEXT = "submit"


def _text(config: Any, key: str) -> str:
    value = config.get(key) if isinstance(config, dict) else None
    return value.strip() if isinstance(value, str) else ""


def scenario(config: Any) -> str:
    return _text(config, "scenario")


def handin(config: Any) -> str:
    return _text(config, "handin")


def criteria(config: Any) -> list[dict[str, str]]:
    """The criteria that are usable (a label), in order, at most `MAX_CRITERIA`."""
    raw = config.get("criteria") if isinstance(config, dict) else None
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        key = item.get("key")
        if not isinstance(label, str) or not label.strip() or not isinstance(key, str) or not key:
            continue
        out.append(
            {
                "key": key,
                "label": label.strip(),
                "description": _str(item.get("description")),
                "guidance": _str(item.get("guidance")),
            }
        )
    return out[:MAX_CRITERIA]


def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _int(config: Any, key: str, default: int, low: int, high: int) -> int:
    value = config.get(key) if isinstance(config, dict) else None
    if isinstance(value, int) and not isinstance(value, bool):
        return min(max(value, low), high)
    return default


def pass_threshold(config: Any) -> float:
    value = config.get("pass_threshold") if isinstance(config, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return min(max(float(value), MIN_THRESHOLD), MAX_THRESHOLD)
    return DEFAULT_THRESHOLD


def min_each(config: Any) -> int:
    """No criterion may score below this; 0 (or 1, which no score can fall under) = off."""
    value = _int(config, "min_each", 0, 0, MAX_SCORE)
    return value if value > MIN_SCORE else 0


def allow_files(config: Any) -> bool:
    value = config.get("allow_files") if isinstance(config, dict) else None
    return value if isinstance(value, bool) else True


def due_days(config: Any) -> int:
    return _int(config, "due_days", DEFAULT_DUE_DAYS, 0, MAX_DAYS)


def revision_days(config: Any) -> int:
    return _int(config, "revision_days", DEFAULT_REVISION_DAYS, 0, MAX_DAYS)


def review_hours(config: Any) -> int:
    """The mentor's review target in hours: this activity's, else the platform's setting."""
    from django.conf import settings

    own = _int(config, "review_hours", 0, 0, MAX_REVIEW_HOURS)
    return own or int(settings.MANUAL_SIM_REVIEW_HOURS)


def holds_next(config: Any) -> str:
    """What the next lesson waits for: "submit" (the work being handed in) or "pass"."""
    value = config.get("holds_next") if isinstance(config, dict) else None
    return value if value in HOLDS_NEXT else DEFAULT_HOLDS_NEXT


def pass_rule_text(config: Any) -> str:
    """The pass rule in words, shown to the learner before they submit."""
    needed = round(pass_threshold(config) * MAX_SCORE, 2)
    needed_text = f"{needed:g}"
    text = f"You pass with an average of {needed_text} out of 5 or more"
    floor = min_each(config)
    if floor:
        text += f", and no criterion below {floor}"
    return text + "."


# ----------------------------------------------------------------- rating maths


@dataclass(frozen=True)
class Rating:
    hundredths: int  # the overall on the 1–5 scale × 100, rounded once, half-up
    raw: float  # hundredths / 100
    scaled: float  # raw / 5 — never shown as a percentage
    passed: bool
    below_min: tuple[str, ...]  # keys of criteria under `min_each`


def rate(config: Any, scores: dict[str, int]) -> Rating:
    """Combine one score per criterion. `scores` must hold exactly the config's criteria,
    each a whole number 1–5 (the caller validates and words the errors)."""
    wanted = [c["key"] for c in criteria(config)]
    if not wanted or set(scores) != set(wanted):
        raise ValueError("Score every criterion.")
    values = [scores[k] for k in wanted]
    if any(
        isinstance(v, bool) or not isinstance(v, int) or not MIN_SCORE <= v <= MAX_SCORE
        for v in values
    ):
        raise ValueError("Each score must be a whole number from 1 to 5.")
    hundredths = round_hundredths(Fraction(sum(values), len(values)))
    floor = min_each(config)
    below = tuple(k for k in wanted if floor and scores[k] < floor)
    return Rating(
        hundredths=hundredths,
        raw=hundredths_to_float(hundredths),
        scaled=round(hundredths / (100 * MAX_SCORE), 4),
        passed=passes(hundredths, pass_threshold(config)) and not below,
        below_min=below,
    )


# ------------------------------------------------------------- registry hooks


def learner_view(config: Any) -> dict[str, Any]:
    """What a learner may see of the config: never the raters' guidance."""
    return {
        "scenario": scenario(config),
        "handin": handin(config),
        "criteria": [
            {"key": c["key"], "label": c["label"], "description": c["description"]}
            for c in criteria(config)
        ],
        "pass_threshold": pass_threshold(config),
        "pass_rule": pass_rule_text(config),
        "min_each": min_each(config),
        "allow_files": allow_files(config),
        "due_days": due_days(config),
        "revision_days": revision_days(config),
        "review_hours": review_hours(config),
        "holds_next": holds_next(config),
    }


def is_ratable(config: Any) -> bool:
    """Has this a scenario and at least one criterion? (Only then may it hold a lesson up.)"""
    return bool(scenario(config)) and bool(criteria(config))


def check_complete(config: Any) -> list[str]:
    """What stops this being published."""
    problems: list[str] = []
    if not scenario(config):
        problems.append("Describe the scenario the learner is asked to work on.")
    raw = config.get("criteria") if isinstance(config, dict) else None
    items = raw if isinstance(raw, list) else []
    if not criteria(config):
        problems.append("Add at least one rubric criterion, with a label.")
    elif len(items) > MAX_CRITERIA:
        problems.append(f"Use at most {MAX_CRITERIA} rubric criteria.")
    keys = [i.get("key") for i in items if isinstance(i, dict)]
    labels = [i.get("label") for i in items if isinstance(i, dict)]
    if len(set(keys)) != len(keys):
        problems.append("Each rubric criterion needs its own key.")
    elif any(not isinstance(label, str) or not label.strip() for label in labels):
        problems.append("Give every rubric criterion a label.")
    from apps.manual_sim import eligibility

    if not eligibility.someone_can_rate():
        problems.append(
            "No one can rate this yet. Give someone the Mentor role (or another role "
            "that may rate simulations) in Admin → Roles."
        )
    return problems
