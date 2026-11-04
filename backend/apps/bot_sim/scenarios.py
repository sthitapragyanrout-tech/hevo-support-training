"""The scenario bank: what trainers write, generate, review and approve.

Only `approved` scenarios are ever given to a learner. Generated scenarios are
always created as drafts; editing an approved scenario sends it back to draft so
nothing changes under learners' feet without a second look.
"""

from __future__ import annotations

import logging
import random

from django.db import transaction
from django.utils import timezone

from simbot_engine.llm import LLMError
from simbot_engine.scenario import (
    PERSONA_TYPES,
    TOPIC_POOL,
    Sample,
    choose_persona,
    generate_scenario,
)

from . import llm
from .errors import Conflict, SimError
from .models import Scenario

log = logging.getLogger(__name__)

EDITABLE = (
    "topic",
    "persona_type",
    "issue_summary",
    "opening_message",
    "personality_notes",
    "doc_hints",
    "reference_answer",
    "doc_url",
)
S = Scenario.Status


def validate(data: dict) -> dict:
    """Clean what a trainer typed; raises `SimError` with a sentence on a problem."""
    out = {k: data[k] for k in EDITABLE if k in data}
    if "topic" in out and out["topic"] not in TOPIC_POOL:
        raise SimError("Choose one of the listed topics.")
    if "persona_type" in out and out["persona_type"] not in PERSONA_TYPES:
        raise SimError("Choose one of the customer types.")
    for key, limit in (
        ("issue_summary", 300),
        ("opening_message", 2000),
        ("personality_notes", 1000),
    ):
        if key in out:
            value = str(out[key]).strip()
            if not value:
                raise SimError("That field can’t be empty.")
            out[key] = value[:limit]
    if "doc_hints" in out:
        hints = out["doc_hints"]
        if not isinstance(hints, list):
            raise SimError("Documentation keywords must be a list.")
        out["doc_hints"] = [str(h).lower().strip()[:40] for h in hints if str(h).strip()][:8]
    for key, limit in (("reference_answer", 4000), ("doc_url", 300)):
        if key in out:
            out[key] = str(out[key]).strip()[:limit]
    return out


def create(user, data: dict, *, source: str = Scenario.Source.MANUAL) -> Scenario:
    clean = validate(data)
    missing = {
        "topic",
        "persona_type",
        "issue_summary",
        "opening_message",
        "personality_notes",
    } - clean.keys()
    if missing:
        raise SimError("Fill in the topic, customer type, question, opening message and notes.")
    return Scenario.objects.create(created_by=user, source=source, status=S.DRAFT, **clean)


@transaction.atomic
def update(scenario: Scenario, data: dict) -> tuple[Scenario, bool]:
    """Edit a scenario. Returns (scenario, sent_back_to_draft)."""
    clean = validate(data)
    changed = {k: v for k, v in clean.items() if getattr(scenario, k) != v}
    sent_back = False
    for key, value in changed.items():
        setattr(scenario, key, value)
    if changed and scenario.status == S.APPROVED:
        scenario.status = S.DRAFT
        scenario.approved_by = None
        scenario.approved_at = None
        sent_back = True
    if changed:
        scenario.save()
    return scenario, sent_back


def approve(scenario: Scenario, user) -> Scenario:
    if scenario.status == S.RETIRED:
        raise Conflict("Restore this scenario to a draft before approving it.")
    scenario.status = S.APPROVED
    scenario.approved_by = user
    scenario.approved_at = timezone.now()
    scenario.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    return scenario


def retire(scenario: Scenario) -> Scenario:
    scenario.status = S.RETIRED
    scenario.save(update_fields=["status", "updated_at"])
    return scenario


def restore(scenario: Scenario) -> Scenario:
    if scenario.status != S.RETIRED:
        raise Conflict("Only a retired scenario can be restored.")
    scenario.status = S.DRAFT
    scenario.approved_by = None
    scenario.approved_at = None
    scenario.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    return scenario


def generate_drafts(
    count: int,
    *,
    user=None,
    topic: str | None = None,
    persona: str | None = None,
    samples: list[Sample] | None = None,
    inner=None,
    rng: random.Random | None = None,
) -> dict[str, int]:
    """Ask the model for `count` new scenarios, all saved as **drafts**. Skips
    near-duplicates; stops early (and says so) if the model keeps failing."""
    rng = rng or random.Random()
    client = llm.GatedLLM(inner)
    config = llm.engine_config()
    made = skipped = failed = 0
    existing = {s.lower() for s in Scenario.objects.values_list("issue_summary", flat=True)}
    for _ in range(count):
        topic_key = topic or rng.choice(list(TOPIC_POOL))
        persona_type = persona or choose_persona(rng)
        try:
            scenario = generate_scenario(client, config, topic_key, persona_type, samples or [])
        except LLMError as exc:
            failed += 1
            log.warning("Scenario generation failed: %s", exc)
            if failed >= 3:
                break
            continue
        if scenario.issue_summary.lower() in existing:
            skipped += 1
            continue
        existing.add(scenario.issue_summary.lower())
        Scenario.objects.create(
            topic=scenario.topic,
            persona_type=scenario.persona_type,
            issue_summary=scenario.issue_summary,
            opening_message=scenario.opening_message,
            personality_notes=scenario.personality_notes,
            doc_hints=list(scenario.doc_hints),
            status=S.DRAFT,
            source=Scenario.Source.GENERATED,
            created_by=user,
        )
        made += 1
    return {"created": made, "duplicates": skipped, "failed": failed}
