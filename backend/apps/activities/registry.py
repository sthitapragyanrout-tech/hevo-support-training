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

from . import quiz


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
            description="Watch a video; completion is tracked.",
            icon="play",
            config_schema={
                "type": "object",
                "properties": {
                    "video_asset_ref": {
                        "type": "string",
                        "minLength": 1,
                        "title": "Video reference",
                    },
                    "completion_threshold": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "title": "Watched fraction needed (0–1)",
                    },
                    "max_credited_rate": {
                        "type": "number",
                        "minimum": 0.25,
                        "title": "Fastest playback speed credited",
                    },
                },
                "required": ["video_asset_ref"],
                "additionalProperties": True,
            },
            default_config={"video_asset_ref": "", "completion_threshold": 0.9},
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
            description="A realistic task a mentor rates against a rubric.",
            icon="chat",
            config_schema={
                "type": "object",
                "properties": {"scenario": {"type": "string", "title": "Scenario for the learner"}},
                "additionalProperties": True,
            },
            default_config={},
        ),
        ActivityTypeDescriptor(
            key="bot_sim",
            label="Chat simulation",
            description="A simulated customer conversation, evaluated automatically.",
            icon="chat",
            config_schema={
                "type": "object",
                "properties": {"persona_key": {"type": "string", "title": "Customer persona"}},
                "additionalProperties": True,
            },
            default_config={},
        ),
    ]
}


def list_types() -> list[dict[str, Any]]:
    return [d.to_dict() for d in ACTIVITY_TYPES.values()]


def get_type(key: str) -> ActivityTypeDescriptor | None:
    return ACTIVITY_TYPES.get(key)


def is_completable(key: str) -> bool:
    """Can a learner finish this type today? (Gates lessons; see progress.)"""
    descriptor = ACTIVITY_TYPES.get(key)
    return descriptor is not None and descriptor.completion != "none"


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
