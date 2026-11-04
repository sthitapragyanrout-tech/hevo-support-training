"""The practice-ticket activity: configuration, what a learner may see of it, and
when it can hold a lesson up.

`config` keys:

  persona          "random" | "urgent" | "technical" | "non-technical" | "terse"
  topics           a list of topic keys, or empty for any
  pass_threshold   scaled 0–1 (0.7 ≙ 3.5 out of 5); the Studio shows it out of 5
  max_exchanges    how many replies the intern may send (3–6)
  required_tickets how many finished, scored tickets complete the activity (1–20, default 5)
  require_average  also require the average of the last `required_tickets` scores to reach
                   the pass mark (default off — this is practice, not a test)

Completion is `external`: only finishing enough scored tickets completes it — the
learner can never mark it done (the scoring is in `simbot_engine.outcome`). A ticket's own
"Passed / Not passed" is feedback; it does not decide completion.
"""

from __future__ import annotations

from typing import Any

from simbot_engine.scenario import PERSONA_TYPES, TOPIC_POOL

PERSONAS = ("random", *PERSONA_TYPES)
DEFAULT_THRESHOLD = 0.7
MIN_THRESHOLD, MAX_THRESHOLD = 0.4, 1.0
DEFAULT_EXCHANGES = 6
MIN_EXCHANGES, MAX_EXCHANGES = 3, 6
MIN_TICKETS, MAX_TICKETS = 1, 20
DEFAULT_TICKETS = 5
MAX = 5


def persona(config: Any) -> str:
    value = config.get("persona") if isinstance(config, dict) else None
    return value if value in PERSONAS else "random"


def topics(config: Any) -> list[str]:
    value = config.get("topics") if isinstance(config, dict) else None
    return [t for t in value if t in TOPIC_POOL] if isinstance(value, list) else []


def pass_threshold(config: Any) -> float:
    value = config.get("pass_threshold") if isinstance(config, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return min(max(float(value), MIN_THRESHOLD), MAX_THRESHOLD)
    return DEFAULT_THRESHOLD


def max_exchanges(config: Any) -> int:
    value = config.get("max_exchanges") if isinstance(config, dict) else None
    if isinstance(value, int) and not isinstance(value, bool):
        return min(max(value, MIN_EXCHANGES), MAX_EXCHANGES)
    return DEFAULT_EXCHANGES


def required_tickets(config: Any) -> int:
    value = config.get("required_tickets") if isinstance(config, dict) else None
    if isinstance(value, int) and not isinstance(value, bool):
        return min(max(value, MIN_TICKETS), MAX_TICKETS)
    return DEFAULT_TICKETS


def require_average(config: Any) -> bool:
    return bool(config.get("require_average")) if isinstance(config, dict) else False


def skips_allowed() -> int:
    from django.conf import settings

    return int(settings.SIMBOT_SKIPS_PER_ACTIVITY)


def completes(config: Any, scaled_scores: list[float]) -> bool:
    """Does this learner's run of finished tickets (oldest first) complete the activity?"""
    needed = required_tickets(config)
    if len(scaled_scores) < needed:
        return False
    if not require_average(config):
        return True
    recent = scaled_scores[-needed:]
    return round(sum(recent) / needed, 4) >= pass_threshold(config)


def matching_scenarios(config: Any):
    """Approved scenarios this activity may use (a queryset)."""
    from apps.bot_sim.models import Scenario

    qs = Scenario.objects.filter(status=Scenario.Status.APPROVED)
    if persona(config) != "random":
        qs = qs.filter(persona_type=persona(config))
    chosen = topics(config)
    if chosen:
        qs = qs.filter(topic__in=chosen)
    return qs


def is_playable(config: Any) -> bool:
    """Can a learner actually do this today? (Only then may it hold a lesson up.)"""
    from django.conf import settings

    from apps.bot_sim import llm

    return bool(settings.SIMBOT_ENABLED and llm.configured())


def check_complete(config: Any) -> list[str]:
    """What stops this being published: too little to practise on, or no model."""
    from django.conf import settings

    if not settings.SIMBOT_ENABLED:
        return ["Practice tickets are switched off on this server."]
    needed = required_tickets(config)
    have = matching_scenarios(config).count()
    if have == 0:
        return [
            "No approved practice scenarios match these settings. "
            "Import some from past customer queries (or approve some) "
            "in Admin → Practice scenarios."
        ]
    if have < needed:
        return [
            f"Learners must finish {needed} tickets, but only {have} approved "
            f"scenario{'s' if have != 1 else ''} match these settings."
        ]
    return []


def warnings(config: Any, activity: Any) -> list[str]:
    """Worth knowing, but not blocking: some learners may run out of fresh questions."""
    needed = required_tickets(config)
    have = matching_scenarios(config).count()
    spare = needed + skips_allowed()
    out = []
    if needed <= have < spare:
        out.append(
            f"{have} approved scenario{'s' if have != 1 else ''} match, and learners may skip up "
            f"to {skips_allowed()} — a learner who skips a lot could run out of new questions."
        )
    tries = getattr(activity, "max_attempts", 0) or 0
    if tries and tries < needed:
        out.append(
            f"Learners may take at most {tries} tickets but must finish {needed}, "
            "so no one could complete this."
        )
    return out


def learner_view(config: Any) -> dict[str, Any]:
    """What a learner may see before starting: how long it is and what completing
    takes. Never the persona, topics or any scenario text."""
    threshold = pass_threshold(config)
    return {
        "max_exchanges": max_exchanges(config),
        "pass_mark": {"raw": round(threshold * MAX, 2), "scaled": threshold, "max": MAX},
        "required_tickets": required_tickets(config),
        "skips_allowed": skips_allowed(),
        "require_average": require_average(config),
    }
