"""
Curriculum import: spreadsheet (CSV / XLSX) → a validated *plan* → new
content in the course's open draft.

The spreadsheet is never the source of truth. It is read once, validated
row-by-row (errors name the spreadsheet row), previewed as a tree, and only
then written — all-or-nothing — through the same `services` the Studio UI
uses, so imported content obeys every authoring rule.

Row model: hierarchy cells *fill down* (as in merged-cell sheets). A new
Module cell starts a module (and resets lesson/section); a new Lesson cell
starts a lesson; a new Section cell starts a section. Blank cells inherit the
current one. Activity columns attach to the deepest current node.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

from django.db import transaction

from apps.activities import registry

from . import services
from .models import ContentNode, CourseVersion

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
MAX_COLUMNS = 50

FIELDS = (
    "module",
    "lesson",
    "section",
    "description",
    "minutes",
    "activity",
    "activity_type",
    "required",
    "points",
    "url",
)

# Normalised header text → field. Learner vocabulary first, legacy names too.
HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "module": ("module", "segment"),
    "lesson": ("lesson", "topic"),
    "section": ("section", "subtopic", "subtopictitle"),
    "description": ("description", "content", "summary", "details"),
    "minutes": ("minutes", "duration", "estimatedminutes", "estimatedtime", "time"),
    "activity": ("activity", "activitytitle", "activityname"),
    "activity_type": ("activitytype", "type"),
    "required": ("required", "isrequired", "mandatory"),
    "points": ("points", "score"),
    "url": ("url", "link", "resource", "sourceurl", "resourceurl"),
}

# What authors might type for an activity type → registry key.
TYPE_ALIASES: dict[str, str] = {
    "reading": "reading",
    "read": "reading",
    "article": "reading",
    "video": "video",
    "pdf": "pdf",
    "quiz": "mcq",
    "mcq": "mcq",
    "test": "mcq",
    "workshop": "workshop",
    "handson": "workshop",
    "externalcourse": "external_course",
    "external": "external_course",
    "course": "external_course",
    "simulation": "manual_sim",
    "manualsim": "manual_sim",
    "mentorsimulation": "manual_sim",
    "chatsimulation": "bot_sim",
    "botsim": "bot_sim",
    "bot": "bot_sim",
}

# The config key a spreadsheet URL populates, per activity type.
URL_CONFIG_KEY: dict[str, str] = {
    "reading": "source_url",
    "pdf": "pdf_url",
    "video": "video_asset_ref",
    "external_course": "course_url",
}

FALSE_WORDS = {"n", "no", "false", "0", "optional"}


class ImportFileError(services.AuthoringError):
    """The file itself can't be read (type, size, shape)."""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


# ------------------------------------------------------------------- reading


def read_table(filename: str, data: bytes) -> tuple[list[str], list[list[str]]]:
    """(headers, rows) from a CSV or XLSX upload. Cells are stripped strings."""
    if len(data) > MAX_BYTES:
        raise ImportFileError("That file is larger than 2 MB.")
    name = filename.lower()
    if name.endswith(".csv"):
        table = _read_csv(data)
    elif name.endswith(".xlsx"):
        table = _read_xlsx(data)
    else:
        raise ImportFileError("Upload a .csv or .xlsx file.")

    table = [_trim(row) for row in table if any(cell for cell in row)]
    if not table:
        raise ImportFileError("The file is empty.")
    headers, rows = table[0], table[1:]
    if len(headers) > MAX_COLUMNS:
        raise ImportFileError("Too many columns.")
    if len(rows) > MAX_ROWS:
        raise ImportFileError(f"At most {MAX_ROWS} rows can be imported at once.")
    return headers, rows


def _trim(row: list[str]) -> list[str]:
    """Drop trailing empty cells (XLSX sheets are padded to a fixed width)."""
    end = len(row)
    while end and not row[end - 1]:
        end -= 1
    return row[:end]


def _read_csv(data: bytes) -> list[list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]
    return [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text), dialect)]


def _read_xlsx(data: bytes) -> list[list[str]]:
    from openpyxl import load_workbook  # imported lazily: only imports need it

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises a zoo of exceptions for bad files
        raise ImportFileError("That doesn't look like a valid .xlsx file.") from exc
    try:
        sheet = workbook.worksheets[0]
        return [
            ["" if cell is None else str(cell).strip() for cell in row]
            for row in sheet.iter_rows(values_only=True, max_col=MAX_COLUMNS + 1)
        ]
    finally:
        workbook.close()


def suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    """field → header text that matches it (first match wins), or None."""
    by_norm = {_norm(h): h for h in headers if h}
    mapping: dict[str, str | None] = {}
    taken: set[str] = set()
    for field_name in FIELDS:
        match = None
        for synonym in HEADER_SYNONYMS[field_name]:
            header = by_norm.get(synonym)
            if header and header not in taken:
                match = header
                break
        if match:
            taken.add(match)
        mapping[field_name] = match
    return mapping


# ---------------------------------------------------------------------- plan


@dataclass
class PlanActivity:
    activity_type: str
    title: str
    url: str = ""
    required: bool = True
    points: int = 0
    row: int = 0


@dataclass
class PlanNode:
    title: str
    row: int
    description: str = ""
    minutes: int | None = None
    children: list[PlanNode] = field(default_factory=list)
    activities: list[PlanActivity] = field(default_factory=list)


@dataclass
class Message:
    row: int | None
    message: str


@dataclass
class Plan:
    modules: list[PlanNode] = field(default_factory=list)
    errors: list[Message] = field(default_factory=list)
    warnings: list[Message] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        lessons = sections = activities = 0
        for module in self.modules:
            activities += len(module.activities)
            for lesson in module.children:
                lessons += 1
                activities += len(lesson.activities)
                for section in lesson.children:
                    sections += 1
                    activities += len(section.activities)
        return {
            "modules": len(self.modules),
            "lessons": lessons,
            "sections": sections,
            "activities": activities,
        }

    def outline(self) -> list[dict[str, Any]]:
        def convert(node: PlanNode, level: str) -> dict[str, Any]:
            child_level = {"module": "lesson", "lesson": "section"}.get(level, "")
            return {
                "title": node.title,
                "level": level,
                "activities": [
                    {"type": a.activity_type, "title": a.title} for a in node.activities
                ],
                "children": [convert(c, child_level) for c in node.children],
            }

        return [convert(m, "module") for m in self.modules]


def build_plan(headers: list[str], rows: list[list[str]], mapping: dict[str, str | None]) -> Plan:
    plan = Plan()
    index = {
        name: headers.index(header) if header in headers else None
        for name, header in mapping.items()
        if name in FIELDS
    }
    if index.get("module") is None and index.get("lesson") is None:
        plan.errors.append(Message(None, "Map at least a Module or a Lesson column."))
        return plan

    def cell(row: list[str], name: str) -> str:
        i = index.get(name)
        return row[i].strip() if i is not None and i < len(row) else ""

    module: PlanNode | None = None
    lesson: PlanNode | None = None
    section: PlanNode | None = None
    seen_titles: dict[tuple[int, str], int] = {}

    for offset, row in enumerate(rows):
        number = offset + 2  # spreadsheet row (the header is row 1)
        titles = {name: cell(row, name) for name in ("module", "lesson", "section")}
        activity_title = cell(row, "activity")
        activity_type_raw = cell(row, "activity_type")
        if not any(titles.values()) and not activity_title and not activity_type_raw:
            continue  # nothing structural on this row

        newest: PlanNode | None = None
        newest_parent: PlanNode | None = None

        if titles["module"]:
            module = PlanNode(title=titles["module"], row=number)
            plan.modules.append(module)
            lesson = section = None
            newest = module
        if titles["lesson"]:
            if module is None:
                plan.errors.append(Message(number, "This lesson has no module above it."))
                continue
            lesson = PlanNode(title=titles["lesson"], row=number)
            module.children.append(lesson)
            section = None
            newest, newest_parent = lesson, module
        if titles["section"]:
            if lesson is None:
                plan.errors.append(Message(number, "This section has no lesson above it."))
                continue
            section = PlanNode(title=titles["section"], row=number)
            lesson.children.append(section)
            newest, newest_parent = section, lesson

        if newest is not None:
            if len(newest.title) > 255:
                plan.errors.append(Message(number, "A title is longer than 255 characters."))
            description = cell(row, "description")
            if description:
                newest.description = description
            minutes_raw = cell(row, "minutes")
            if minutes_raw:
                minutes = _parse_minutes(minutes_raw)
                if minutes is None:
                    plan.errors.append(
                        Message(number, f"“{minutes_raw}” isn't a number of minutes.")
                    )
                else:
                    newest.minutes = minutes
            key = (id(newest_parent), newest.title.lower())
            if key in seen_titles:
                plan.warnings.append(
                    Message(number, f"“{newest.title}” appears twice under the same parent.")
                )
            seen_titles[key] = number

        if activity_title or activity_type_raw:
            target = section or lesson
            if target is None:
                plan.errors.append(
                    Message(number, "This activity has no lesson or section above it.")
                )
                continue
            type_key = _resolve_type(activity_type_raw)
            if not activity_type_raw:
                plan.errors.append(
                    Message(number, "This activity needs a type (e.g. Reading, Quiz).")
                )
                continue
            if type_key is None:
                known = ", ".join(sorted({t["label"] for t in registry.list_types()}))
                plan.errors.append(
                    Message(
                        number, f"Unknown activity type “{activity_type_raw}”. Use one of: {known}."
                    )
                )
                continue
            points_raw = cell(row, "points")
            points = _parse_minutes(points_raw) if points_raw else 0
            if points is None:
                plan.errors.append(Message(number, f"“{points_raw}” isn't a number of points."))
                points = 0
            target.activities.append(
                PlanActivity(
                    activity_type=type_key,
                    title=activity_title,
                    url=cell(row, "url"),
                    required=_parse_required(cell(row, "required")),
                    points=points,
                    row=number,
                )
            )

    if not plan.modules and not plan.errors:
        plan.errors.append(Message(None, "No modules were found in this file."))
    return plan


def _parse_minutes(raw: str) -> int | None:
    match = re.fullmatch(r"\s*(\d+)(?:\.0+)?\s*(?:m|min|mins|minutes)?\s*", raw.lower())
    return int(match.group(1)) if match else None


def _parse_required(raw: str) -> bool:
    """Blank or anything but an explicit no means required."""
    return raw.strip().lower() not in FALSE_WORDS


def _resolve_type(raw: str) -> str | None:
    key = _norm(raw)
    if key in TYPE_ALIASES:
        return TYPE_ALIASES[key]
    for type_key, descriptor in registry.ACTIVITY_TYPES.items():
        if key in (_norm(type_key), _norm(descriptor.label)):
            return type_key
    return None


# --------------------------------------------------------------------- apply


@transaction.atomic
def apply_plan(version: CourseVersion, plan: Plan) -> dict[str, int]:
    """Append the plan under the course root of `version` (an editable draft)."""
    services.assert_editable(version)
    if plan.errors:
        raise services.InvalidOperation("Fix the errors in the file before importing.")
    root = version.root_node
    if root is None:  # pragma: no cover - create_course always sets it
        raise services.InvalidOperation("This course has no root node.")

    def write(plan_node: PlanNode, parent: ContentNode) -> None:
        node = services.add_node(
            parent,
            title=plan_node.title,
            description=plan_node.description,
            estimated_minutes=plan_node.minutes,
        )
        for activity in plan_node.activities:
            _write_activity(node, activity)
        for child in plan_node.children:
            write(child, node)

    for module in plan.modules:
        module_node = services.add_node(
            root,
            title=module.title,
            description=module.description,
            estimated_minutes=module.minutes,
        )
        for lesson in module.children:
            write(lesson, module_node)
    return plan.counts


def _write_activity(node: ContentNode, activity: PlanActivity) -> None:
    descriptor = registry.get_type(activity.activity_type)
    assert descriptor is not None  # resolved against the registry in build_plan
    config = dict(descriptor.default_config)
    url_key = URL_CONFIG_KEY.get(activity.activity_type)
    if url_key and activity.url:
        config[url_key] = activity.url
    services.add_activity(
        node,
        activity_type=activity.activity_type,
        title=activity.title or descriptor.label,
        config=config,
        is_required=activity.required,
        points=activity.points,
    )
