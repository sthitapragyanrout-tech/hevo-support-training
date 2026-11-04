"""
Activity-type registry: the one place that knows what each activity type is
called, what its `config` must look like, and how a client should start one.

It replaces the stop-gap `catalog/activity_schemas.py` (whose docstring said
it would be superseded when the plugin framework landed). Future plugins in
`apps/activities/plugins/<type>/` can contribute their own descriptors by
registering them here — the Course Builder reads this registry and never
hard-codes per-type behaviour.

Two validation modes:
  * strict  — the config is complete and publishable.
  * lenient — the config may be unfinished ("needs setup") while a draft is
    being authored: types must be right, but required fields / minimum item
    counts are not enforced.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from . import bot_sim, manual_sim, quiz, video


@dataclass(frozen=True)
class ActivityTypeDescriptor:
    key: str
    label: str
    description: str
    icon: str
    config_schema: dict[str, Any]
    default_config: dict[str, Any] = field(default_factory=dict)
    # Key the learner SPA uses to pick a renderer (arrives with the plugins).
    renderer_key: str = ""
    # How a learner finishes this activity. "manual" = they confirm it
    # themselves (reading); "scored" = they pass it (quiz); "none" = not
    # completable yet (the type's own module hasn't shipped), so it never
    # blocks a lesson.
    completion: str = "none"
    # The only `config` keys a *learner* may see. Everything else (a quiz's
    # answer key, say) never leaves the server.
    learner_fields: tuple[str, ...] = ()
    # Types that need more than a flat allow-list project their own learner
    # view of `config` (a quiz keeps its questions but never its answer key).
    learner_view: Callable[[Any], dict[str, Any]] | None = None
    # Scored types judge a submission; `completion="scored"` means passing is
    # what completes them. `score(config, raw_answers)` returns
    # `(result, normalised_answers)` — `result` has `.score .passed .correct
    # .total .results` — or raises ValueError with a message for the learner.
    # `review` turns a result into per-item feedback; only `reveal=True` may
    # include the answer key.
    score: Callable[[Any, Any], tuple[Any, Any]] | None = None
    review: Callable[..., list[dict[str, Any]]] | None = None
    # Strict-only checks the JSON Schema can't express (publishable configs).
    check_complete: Callable[[Any], list[str]] | None = None
    # `Activity.max_attempts` for a newly added activity (0 = unlimited).
    default_max_attempts: int = 3
    # Some types can only be finished when their config points at something
    # real (a video that exists). Without it, they never block a lesson.
    completable_config: Callable[[Any], bool] | None = None
    # Who-may-do-what rules on a config (an uploaded video must be the author's
    # own). Returns problems; only consulted when an author saves.
    authorize_config: Callable[[Any, Any], list[str]] | None = None
    # Worth knowing before publishing, but not blocking: (config, activity) -> sentences.
    check_warnings: Callable[[Any, Any], list[str]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "icon": self.icon,
            "config_schema": self.config_schema,
            "default_config": self.default_config,
            "renderer_key": self.renderer_key or self.key,
            "completion": self.completion,
        }


ACTIVITY_TYPES: dict[str, ActivityTypeDescriptor] = {
    d.key: d
    for d in [
        ActivityTypeDescriptor(
            key="reading",
            label="Reading",
            description="Read a page or document, then mark it complete.",
            icon="book",
            config_schema={
                "type": "object",
                "properties": {
                    "source_url": {
                        "type": "string",
                        "minLength": 1,
                        "title": "Link to the reading",
                    },
                    "estimated_read_minutes": {
                        "type": "integer",
                        "minimum": 1,
                        "title": "Estimated read time (minutes)",
                    },
                },
                "required": ["source_url"],
                "additionalProperties": True,
            },
            default_config={"source_url": ""},
            completion="manual",
            learner_fields=("source_url", "estimated_read_minutes"),
        ),
        ActivityTypeDescriptor(
            key="video",
            label="Video",
            description="Watch a video in the lesson; completion is tracked.",
            icon="play",
            config_schema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "enum": list(video.SOURCES),
                        "title": "Video source",
                    },
                    "media_asset": {
                        "type": "integer",
                        "minimum": 1,
                        "title": "Uploaded video",
                    },
                    "youtube_url": {"type": "string", "title": "YouTube link"},
                    "drive_url": {"type": "string", "title": "Google Drive link"},
                    "completion_threshold": {
                        "type": "number",
                        "minimum": video.MIN_THRESHOLD,
                        "maximum": 1,
                        "title": "Share of the video that must be watched",
                    },
                    "max_credited_rate": {
                        "type": "number",
                        "minimum": 0.25,
                        "maximum": video.MAX_RATE,
                        "title": "Fastest playback speed credited",
                    },
                },
                "additionalProperties": True,
            },
            default_config={
                "source": video.UPLOAD,
                "completion_threshold": video.DEFAULT_THRESHOLD,
                "max_credited_rate": video.DEFAULT_RATE,
            },
            # Finished by watching it, as measured and re-checked by the server.
            completion="tracked",
            learner_view=video.learner_view,
            check_complete=video.check_complete,
            completable_config=video.is_playable,
            authorize_config=video.authorize_config,
        ),
        ActivityTypeDescriptor(
            key="pdf",
            label="PDF",
            description="A PDF handout or slide deck.",
            icon="file",
            config_schema={
                "type": "object",
                "properties": {"pdf_url": {"type": "string", "title": "Link to the PDF"}},
                "additionalProperties": True,
            },
            default_config={},
        ),
        ActivityTypeDescriptor(
            key="mcq",
            label="Quiz",
            description="Auto-scored questions with a pass mark.",
            icon="quiz",
            config_schema={
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "minItems": 1,
                        "title": "Questions",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string", "title": "Question"},
                                "choices": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "title": "Choices",
                                },
                                "answer": {
                                    "oneOf": [
                                        {"type": "integer", "minimum": 0},
                                        {
                                            "type": "array",
                                            "items": {"type": "integer", "minimum": 0},
                                        },
                                    ],
                                    "title": "Correct answer",
                                },
                                "explanation": {"type": "string", "title": "Explanation"},
                            },
                        },
                    },
                    "pass_threshold": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "title": "Pass mark (0–1)",
                    },
                },
                "required": ["questions"],
                "additionalProperties": True,
            },
            default_config={"questions": [], "pass_threshold": quiz.DEFAULT_PASS_THRESHOLD},
            completion="scored",
            learner_view=quiz.learner_view,
            score=quiz.judge,
            review=quiz.review,
            check_complete=quiz.check_complete,
            default_max_attempts=0,
        ),
        ActivityTypeDescriptor(
            key="workshop",
            label="Workshop",
            description="A hands-on exercise completed with a mentor or on your own.",
            icon="tool",
            config_schema={
                "type": "object",
                "properties": {"instructions": {"type": "string", "title": "Instructions"}},
                "additionalProperties": True,
            },
            default_config={},
        ),
        ActivityTypeDescriptor(
            key="external_course",
            label="External course",
            description="A course hosted elsewhere, with completion verification.",
            icon="external",
            config_schema={
                "type": "object",
                "properties": {
                    "provider_name": {"type": "string", "minLength": 1, "title": "Provider"},
                    "course_url": {"type": "string", "minLength": 1, "title": "Course link"},
                    "requires_verification": {
                        "type": "boolean",
                        "title": "Needs a certificate to verify",
                    },
                },
                "required": ["provider_name", "course_url"],
                "additionalProperties": True,
            },
            default_config={"provider_name": "", "course_url": ""},
        ),
        ActivityTypeDescriptor(
            key="manual_sim",
            label="Simulation (mentor-rated)",
            description=(
                "A realistic task a mentor rates against a rubric; "
                "learners revise from the feedback."
            ),
            icon="chat",
            config_schema={
                "type": "object",
                "properties": {
                    "scenario": {"type": "string", "title": "Scenario for the learner"},
                    "handin": {"type": "string", "title": "What to hand in"},
                    "criteria": {
                        "type": "array",
                        "maxItems": manual_sim.MAX_CRITERIA,
                        "title": "Rubric criteria",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "label": {"type": "string", "title": "Criterion"},
                                "description": {"type": "string", "title": "What it looks at"},
                                "guidance": {"type": "string", "title": "Guidance for raters"},
                            },
                        },
                    },
                    "pass_threshold": {
                        "type": "number",
                        "minimum": manual_sim.MIN_THRESHOLD,
                        "maximum": manual_sim.MAX_THRESHOLD,
                        "title": "Pass mark",
                    },
                    "min_each": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": manual_sim.MAX_SCORE,
                        "title": "Lowest score allowed on any criterion",
                    },
                    "allow_files": {"type": "boolean", "title": "Allow screenshots and PDFs"},
                    "due_days": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": manual_sim.MAX_DAYS,
                        "title": "Days to hand in",
                    },
                    "revision_days": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": manual_sim.MAX_DAYS,
                        "title": "Days to revise after feedback",
                    },
                    "review_hours": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": manual_sim.MAX_REVIEW_HOURS,
                        "title": "Mentor review target (hours)",
                    },
                    "holds_next": {
                        "type": "string",
                        "enum": list(manual_sim.HOLDS_NEXT),
                        "title": "What holds the next lesson",
                    },
                },
                "required": ["scenario"],
                "additionalProperties": True,
            },
            default_config={
                "scenario": "",
                "handin": "",
                "criteria": [],
                "pass_threshold": manual_sim.DEFAULT_THRESHOLD,
                "min_each": 0,
                "allow_files": True,
                "due_days": manual_sim.DEFAULT_DUE_DAYS,
                "revision_days": manual_sim.DEFAULT_REVISION_DAYS,
                "holds_next": manual_sim.DEFAULT_HOLDS_NEXT,
            },
            # Finished only by a mentor's rating passing it; a person judges, not code, so it
            # has no `score`/`review` hooks and never appears in the quiz reports.
            completion="external",
            learner_view=manual_sim.learner_view,
            check_complete=manual_sim.check_complete,
            completable_config=manual_sim.is_ratable,
            # Deadlines, not a count of tries, bound this work (see `apps/manual_sim`).
            default_max_attempts=0,
        ),
        ActivityTypeDescriptor(
            key="bot_sim",
            label="Practice ticket",
            description="Reply to an AI customer in a ticket-style window and get scored.",
            icon="chat",
            config_schema={
                "type": "object",
                "properties": {
                    "persona": {
                        "type": "string",
                        "enum": list(bot_sim.PERSONAS),
                        "title": "Customer type",
                    },
                    "topics": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(bot_sim.TOPIC_POOL)},
                        "title": "Topics",
                    },
                    "pass_threshold": {
                        "type": "number",
                        "minimum": bot_sim.MIN_THRESHOLD,
                        "maximum": bot_sim.MAX_THRESHOLD,
                        "title": "Pass mark",
                    },
                    "max_exchanges": {
                        "type": "integer",
                        "minimum": bot_sim.MIN_EXCHANGES,
                        "maximum": bot_sim.MAX_EXCHANGES,
                        "title": "Replies allowed",
                    },
                    "required_tickets": {
                        "type": "integer",
                        "minimum": bot_sim.MIN_TICKETS,
                        "maximum": bot_sim.MAX_TICKETS,
                        "title": "Tickets to complete",
                    },
                    "require_average": {
                        "type": "boolean",
                        "title": "Also require the average to reach the pass mark",
                    },
                },
                "additionalProperties": True,
            },
            default_config={
                "persona": "random",
                "topics": [],
                "pass_threshold": bot_sim.DEFAULT_THRESHOLD,
                "max_exchanges": bot_sim.DEFAULT_EXCHANGES,
                "required_tickets": bot_sim.DEFAULT_TICKETS,
                "require_average": False,
            },
            # Finished only by finishing enough scored tickets, never by the learner.
            completion="external",
            learner_view=bot_sim.learner_view,
            check_complete=bot_sim.check_complete,
            completable_config=bot_sim.is_playable,
            check_warnings=bot_sim.warnings,
            default_max_attempts=3,
        ),
    ]
}


def list_types() -> list[dict[str, Any]]:
    return [d.to_dict() for d in ACTIVITY_TYPES.values()]


def get_type(key: str) -> ActivityTypeDescriptor | None:
    return ACTIVITY_TYPES.get(key)


def is_completable(key: str, config: Any = None) -> bool:
    """Can a learner finish this activity today? (Gates lessons; see progress.)
    Pass the activity's `config` where there is one: a video with nothing to
    watch behind it can't be finished, so it must not hold a lesson up."""
    descriptor = ACTIVITY_TYPES.get(key)
    if descriptor is None or descriptor.completion == "none":
        return False
    if descriptor.completable_config is not None and config is not None:
        return descriptor.completable_config(config)
    return True


def learner_config(key: str, config: Any) -> dict[str, Any]:
    """The part of `config` a learner is allowed to see (allow-list)."""
    descriptor = ACTIVITY_TYPES.get(key)
    if descriptor is None or not isinstance(config, dict):
        return {}
    if descriptor.learner_view is not None:
        return descriptor.learner_view(config)
    return {k: v for k, v in config.items() if k in descriptor.learner_fields}


def _relax(schema: Any) -> Any:
    """A copy of `schema` with completeness rules (`required`, `minItems`,
    `minLength`) removed, so an unfinished config still type-checks."""
    if isinstance(schema, dict):
        return {
            k: _relax(v)
            for k, v in schema.items()
            if k not in ("required", "minItems", "minLength")
        }
    if isinstance(schema, list):
        return [_relax(v) for v in schema]
    return schema


def validate_config(activity_type: str, config: Any, *, strict: bool) -> list[str]:
    """Human-readable problems with `config` for `activity_type` (empty = ok).
    Unknown types are always an error; types with no constraints always pass."""
    descriptor = ACTIVITY_TYPES.get(activity_type)
    if descriptor is None:
        return [f"Unknown activity type “{activity_type}”."]
    if not isinstance(config, dict):
        return ["Config must be an object."]
    schema = descriptor.config_schema if strict else _relax(copy.deepcopy(descriptor.config_schema))
    validator = jsonschema.Draft202012Validator(schema)
    errors = [
        _message(e) for e in sorted(validator.iter_errors(config), key=lambda e: list(e.path))
    ]
    if strict and not errors and descriptor.check_complete is not None:
        errors = descriptor.check_complete(config)
    return errors


def _message(error: jsonschema.ValidationError) -> str:
    """A sentence an author can act on, using the schema's own field titles."""
    schema = error.schema if isinstance(error.schema, dict) else {}
    properties = schema.get("properties", {}) if isinstance(schema.get("properties"), dict) else {}
    key = str(error.path[-1]) if error.path else None

    def label(name: str | None, sub: dict[str, Any] | None = None) -> str:
        sub = sub or {}
        title = sub.get("title") or (properties.get(name, {}) or {}).get("title") if name else None
        return title or (name.replace("_", " ").capitalize() if name else "This setting")

    if error.validator == "required":
        match = re.match(r"'([^']+)' is a required property", error.message)
        name = match.group(1) if match else None
        return f"{label(name)} is required."
    if error.validator == "minLength":
        return f"{label(key, schema)} is required."
    if error.validator == "minItems":
        count = error.validator_value
        return (
            f"{label(key, schema)} needs at least {count} {'entry' if count == 1 else 'entries'}."
        )
    if len(error.path) >= 2 and isinstance(error.path[1], int):
        # An entry inside a list, e.g. the third question.
        return f"{label(str(error.path[0]))}, item {error.path[1] + 1}: {error.message}"
    if key:
        return f"{label(key, schema)}: {error.message}"
    return error.message
