"""
Authoring services: every change to a course's content goes through here, so
the API (and later imports) share one set of rules instead of re-deriving
them. Callers never choose a node's `kind`, `slug`, `order` or version —
those come from context (the parent node / the course's open draft).

Rules enforced here:
  * only a plain draft is editable (published and in-review versions are
    immutable → `NotEditable`);
  * a node's kind follows from its parent's kind (`ContentNode.ALLOWED_PARENT_KIND`);
  * slugs are generated from titles and unique among siblings;
  * a course has at most one open (draft / in-review) version.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.text import slugify

from apps.activities.registry import get_type, validate_config

from .models import Activity, ContentNode, Course, CourseVersion

# Which kind a "+ add" under a given parent creates (inverse of
# ContentNode.ALLOWED_PARENT_KIND). Subtopics can't have children.
CHILD_KIND: dict[str, str] = {
    ContentNode.Kind.COURSE: ContentNode.Kind.SEGMENT,
    ContentNode.Kind.SEGMENT: ContentNode.Kind.TOPIC,
    ContentNode.Kind.TOPIC: ContentNode.Kind.SUBTOPIC,
}

EDITABLE_NODE_FIELDS = ("title", "description", "estimated_minutes", "is_required")


class AuthoringError(Exception):
    """Base class; `.message` is safe to show the author."""

    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotEditable(AuthoringError):
    """The target version is published / in review / archived."""

    status_code = 409


class InvalidOperation(AuthoringError):
    status_code = 400


# --------------------------------------------------------------------- helpers


def assert_editable(version: CourseVersion) -> None:
    if not version.is_editable:
        raise NotEditable(
            f"This course is {version.get_state_display().lower()} and can't be edited. "
            "Start a new draft to make changes."
        )


def open_version(course: Course) -> CourseVersion | None:
    """The course's single draft / in-review version, if any."""
    return course.versions.filter(state__in=CourseVersion.OPEN_STATES).first()


def latest_published(course: Course) -> CourseVersion | None:
    return course.versions.filter(state=CourseVersion.State.PUBLISHED).order_by("-version").first()


def _unique_slug(base_text: str, siblings: list[str], *, fallback: str) -> str:
    base = slugify(base_text) or fallback
    slug, n = base, 2
    while slug in siblings:
        slug = f"{base}-{n}"
        n += 1
    return slug


def _clean_title(title: str) -> str:
    title = (title or "").strip()
    if not title:
        raise InvalidOperation("Give it a title.")
    if len(title) > 255:
        raise InvalidOperation("Titles can be at most 255 characters.")
    return title


# --------------------------------------------------------------------- courses


@transaction.atomic
def create_course(*, title: str, description: str = "", user) -> Course:
    """A new course starts life as version 1, in draft, with its root node."""
    title = _clean_title(title)
    taken = list(Course.objects.values_list("slug", flat=True))
    course = Course.objects.create(
        slug=_unique_slug(title, taken, fallback="course"), created_by=user
    )
    version = CourseVersion.objects.create(course=course, version=1)
    root = ContentNode.objects.create(
        course_version=version,
        kind=ContentNode.Kind.COURSE,
        title=title,
        slug=slugify(title) or "course",
        description=description,
    )
    version.root_node = root
    version.save(update_fields=["root_node"])
    return course


@transaction.atomic
def clone_version(source: CourseVersion) -> CourseVersion:
    """Copy `source`'s whole tree (nodes + activities, config deep-copied)
    into a new draft version of the same course. The source is untouched."""
    latest = source.course.versions.order_by("-version").values_list("version", flat=True).first()
    new_version = CourseVersion.objects.create(course=source.course, version=(latest or 0) + 1)

    nodes = list(source.nodes.prefetch_related("activities"))
    children: dict[int | None, list[ContentNode]] = defaultdict(list)
    for node in nodes:
        children[node.parent_id].append(node)

    new_root: ContentNode | None = None
    queue: list[tuple[ContentNode, ContentNode | None]] = [(root, None) for root in children[None]]
    while queue:
        old, new_parent = queue.pop(0)
        clone = ContentNode.objects.create(
            course_version=new_version,
            parent=new_parent,
            kind=old.kind,
            title=old.title,
            slug=old.slug,
            order=old.order,
            description=old.description,
            is_required=old.is_required,
            estimated_minutes=old.estimated_minutes,
        )
        if old.id == source.root_node_id:
            new_root = clone
        for activity in old.activities.all():
            Activity.objects.create(
                content_node=clone,
                activity_type=activity.activity_type,
                title=activity.title,
                config=copy.deepcopy(activity.config),
                is_required=activity.is_required,
                max_attempts=activity.max_attempts,
                mastery_threshold=activity.mastery_threshold,
                points=activity.points,
                order=activity.order,
            )
        queue.extend((child, clone) for child in children[old.id])

    new_version.root_node = new_root
    new_version.save(update_fields=["root_node"])
    return new_version


@transaction.atomic
def get_or_create_draft(course: Course) -> CourseVersion:
    """The course's open version, creating a draft (cloned from the latest
    published version) if none exists. Serialised per course so two authors
    pressing "Edit" at once end up on the same draft."""
    Course.objects.select_for_update().get(pk=course.pk)
    existing = open_version(course)
    if existing:
        return existing
    source = latest_published(course)
    if source is None:
        raise InvalidOperation("This course has nothing to copy a draft from.")
    return clone_version(source)


# ----------------------------------------------------------------------- nodes


@transaction.atomic
def add_node(
    parent: ContentNode,
    *,
    title: str,
    description: str = "",
    estimated_minutes: int | None = None,
    is_required: bool = True,
) -> ContentNode:
    """Add a child under `parent`. Kind, slug, order and version are derived."""
    version = parent.course_version
    assert_editable(version)

    kind = CHILD_KIND.get(parent.kind)
    if kind is None:
        raise InvalidOperation("A section can't contain anything else.")

    siblings = list(parent.children.values_list("slug", "order"))
    node = ContentNode(
        course_version=version,
        parent=parent,
        kind=kind,
        title=_clean_title(title),
        slug=_unique_slug(title, [s for s, _ in siblings], fallback=kind),
        order=(max((o for _, o in siblings), default=-1)) + 1,
        description=description,
        estimated_minutes=estimated_minutes,
        is_required=is_required,
    )
    _save_validated(node)
    return node


@transaction.atomic
def update_node(node: ContentNode, **changes) -> ContentNode:
    """Edit title / description / minutes / required. The slug never changes
    on rename (it may already be part of links or imports)."""
    assert_editable(node.course_version)
    unknown = set(changes) - set(EDITABLE_NODE_FIELDS)
    if unknown:
        raise InvalidOperation(f"Can't change: {', '.join(sorted(unknown))}.")
    if "title" in changes:
        changes["title"] = _clean_title(changes["title"])
    for field, value in changes.items():
        setattr(node, field, value)
    _save_validated(node)
    return node


def node_impact(node: ContentNode) -> dict[str, int]:
    """What deleting `node` would remove (shown before confirming)."""
    ids = [node.id]
    frontier = [node.id]
    while frontier:
        frontier = list(
            ContentNode.objects.filter(parent_id__in=frontier).values_list("id", flat=True)
        )
        ids.extend(frontier)
    kinds = ContentNode.objects.filter(id__in=ids).exclude(id=node.id)
    return {
        "lessons": kinds.filter(kind=ContentNode.Kind.TOPIC).count(),
        "sections": kinds.filter(kind=ContentNode.Kind.SUBTOPIC).count(),
        "activities": Activity.objects.filter(content_node_id__in=ids).count(),
    }


@transaction.atomic
def delete_node(node: ContentNode) -> None:
    assert_editable(node.course_version)
    if node.parent_id is None:
        raise InvalidOperation("The course itself can't be deleted here.")
    parent_id = node.parent_id
    node.delete()
    # Close the gap so `order` stays a clean 0..n-1 sequence.
    for index, sibling in enumerate(ContentNode.objects.filter(parent_id=parent_id)):
        if sibling.order != index:
            ContentNode.objects.filter(pk=sibling.pk).update(order=index)


@transaction.atomic
def reorder_children(parent: ContentNode, child_ids: list[int]) -> None:
    """Set the order of `parent`'s children. `child_ids` must be exactly the
    current children — no partial lists, no foreign ids."""
    assert_editable(parent.course_version)
    current = set(parent.children.values_list("id", flat=True))
    if len(child_ids) != len(set(child_ids)) or set(child_ids) != current:
        raise InvalidOperation("The new order must list every item exactly once.")
    for index, node_id in enumerate(child_ids):
        ContentNode.objects.filter(pk=node_id).update(order=index)


def _save_validated(node: ContentNode) -> None:
    try:
        node.full_clean()
    except ValidationError as exc:
        raise InvalidOperation(" ".join(exc.messages)) from exc
    node.save()


# ------------------------------------------------------------------ tree reads


@dataclass(frozen=True)
class CourseStatus:
    """How a course looks to an author: derived from its versions, so the
    UI can talk about "Draft" / "Published" without exposing versions."""

    key: str  # draft | in_review | published | published_with_draft
    label: str
    open_version: CourseVersion | None
    published_version: CourseVersion | None


def course_status(course: Course) -> CourseStatus:
    # Reads `course.versions.all()` so callers that prefetched versions (the
    # list screen) don't pay two queries per course.
    versions = list(course.versions.all())
    open_v = next((v for v in versions if v.state in CourseVersion.OPEN_STATES), None)
    published = max(
        (v for v in versions if v.state == CourseVersion.State.PUBLISHED),
        key=lambda v: v.version,
        default=None,
    )
    if open_v and open_v.state == CourseVersion.State.IN_REVIEW:
        return CourseStatus("in_review", "In review", open_v, published)
    if open_v and published:
        label = f"Published v{published.version} · edits in draft"
        return CourseStatus("published_with_draft", label, open_v, published)
    if open_v:
        return CourseStatus("draft", "Draft", open_v, published)
    if published:
        return CourseStatus("published", f"Published v{published.version}", None, published)
    return CourseStatus("archived", "Archived", None, None)


def archive_course(course: Course) -> bool:
    """Retire a course: hidden from learners and from Studio's list, nothing
    more recorded against it. Versions and history are untouched. Returns
    whether anything changed."""
    if course.archived_at is not None:
        return False
    course.archived_at = timezone.now()
    course.save(update_fields=["archived_at"])
    return True


def restore_course(course: Course) -> bool:
    if course.archived_at is None:
        return False
    course.archived_at = None
    course.save(update_fields=["archived_at"])
    return True


# ------------------------------------------------------------------ activities

ACTIVITY_EDITABLE_FIELDS = (
    "title",
    "config",
    "is_required",
    "points",
    "max_attempts",
    "mastery_threshold",
)


def activity_needs_setup(activity: Activity) -> bool:
    """Valid enough to save in a draft, but not yet publishable."""
    return bool(validate_config(activity.activity_type, activity.config, strict=True))


def _validate_activity_config(activity_type: str, config) -> None:
    errors = validate_config(activity_type, config, strict=False)
    if errors:
        raise InvalidOperation(errors[0])


@transaction.atomic
def add_activity(node: ContentNode, *, activity_type: str, title: str = "", **fields) -> Activity:
    """Add an activity to a lesson or section. The config may be unfinished
    (it is then flagged "needs setup" and blocks publishing, not saving)."""
    assert_editable(node.course_version)
    if node.kind not in (ContentNode.Kind.TOPIC, ContentNode.Kind.SUBTOPIC):
        raise InvalidOperation("Activities belong to lessons and sections.")
    descriptor = get_type(activity_type)
    if descriptor is None:
        raise InvalidOperation(f"Unknown activity type “{activity_type}”.")
    config = fields.pop("config", None)
    config = copy.deepcopy(descriptor.default_config) if config is None else config
    _validate_activity_config(activity_type, config)
    unknown = set(fields) - set(ACTIVITY_EDITABLE_FIELDS)
    if unknown:
        raise InvalidOperation(f"Can't set: {', '.join(sorted(unknown))}.")
    fields.setdefault("max_attempts", descriptor.default_max_attempts)
    last = node.activities.aggregate(m=Max("order"))["m"]
    activity = Activity(
        content_node=node,
        activity_type=activity_type,
        title=_clean_title(title or descriptor.label),
        config=config,
        order=0 if last is None else last + 1,
        **fields,
    )
    _save_activity(activity)
    return activity


@transaction.atomic
def update_activity(activity: Activity, **changes) -> Activity:
    assert_editable(activity.content_node.course_version)
    unknown = set(changes) - set(ACTIVITY_EDITABLE_FIELDS)
    if unknown:
        raise InvalidOperation(f"Can't change: {', '.join(sorted(unknown))}.")
    if "config" in changes:
        _validate_activity_config(activity.activity_type, changes["config"])
    if "title" in changes:
        changes["title"] = _clean_title(changes["title"])
    for field, value in changes.items():
        setattr(activity, field, value)
    _save_activity(activity)
    return activity


@transaction.atomic
def delete_activity(activity: Activity) -> None:
    assert_editable(activity.content_node.course_version)
    node_id = activity.content_node_id
    activity.delete()
    for index, sibling in enumerate(Activity.objects.filter(content_node_id=node_id)):
        if sibling.order != index:
            Activity.objects.filter(pk=sibling.pk).update(order=index)


@transaction.atomic
def reorder_activities(node: ContentNode, activity_ids: list[int]) -> None:
    assert_editable(node.course_version)
    current = set(node.activities.values_list("id", flat=True))
    if len(activity_ids) != len(set(activity_ids)) or set(activity_ids) != current:
        raise InvalidOperation("The new order must list every activity exactly once.")
    for index, activity_id in enumerate(activity_ids):
        Activity.objects.filter(pk=activity_id).update(order=index)


def _save_activity(activity: Activity) -> None:
    # Lenient on config completeness (see add_activity), so this validates
    # fields only — `full_clean()` would run `Activity.clean()`, which is
    # strict. Field rules (e.g. mastery_threshold's range) still apply.
    try:
        activity.clean_fields(exclude=["config"])
    except ValidationError as exc:
        raise InvalidOperation(" ".join(exc.messages)) from exc
    activity.save()


# ----------------------------------------------------- overview (course root)


@transaction.atomic
def update_overview(version: CourseVersion, *, title: str | None, description: str | None):
    """Edit the course's title / description (they live on the version's root)."""
    assert_editable(version)
    root = version.root_node
    if root is None:  # pragma: no cover - create_course always sets it
        raise InvalidOperation("This course has no root node.")
    changes = {}
    if title is not None:
        changes["title"] = title
    if description is not None:
        changes["description"] = description
    return update_node(root, **changes)


# --------------------------------------------------------- review and publish


@dataclass(frozen=True)
class ChecklistIssue:
    message: str
    node_id: int | None = None
    level: str = "error"  # "error" blocks submit/publish; "warning" doesn't


def publish_checklist(version: CourseVersion) -> list[ChecklistIssue]:
    """What stands between this draft and being publishable."""
    issues: list[ChecklistIssue] = []
    nodes = list(version.nodes.prefetch_related("activities"))
    by_parent: dict[int | None, list[ContentNode]] = defaultdict(list)
    for node in nodes:
        by_parent[node.parent_id].append(node)

    modules = [n for n in nodes if n.kind == ContentNode.Kind.SEGMENT]
    lessons = [n for n in nodes if n.kind == ContentNode.Kind.TOPIC]
    if not modules:
        issues.append(ChecklistIssue("Add at least one module."))
    for module in modules:
        if not by_parent[module.id]:
            issues.append(ChecklistIssue(f"Module “{module.title}” has no lessons.", module.id))
    for lesson in lessons:
        has_content = (
            lesson.description.strip()
            or by_parent[lesson.id]
            or any(True for _ in lesson.activities.all())
        )
        if not has_content:
            issues.append(ChecklistIssue(f"Lesson “{lesson.title}” is empty.", lesson.id))
    for node in nodes:
        for activity in node.activities.all():
            errors = validate_config(activity.activity_type, activity.config, strict=True)
            if errors:
                issues.append(
                    ChecklistIssue(
                        f"“{activity.title}” in “{node.title}” needs setup: {errors[0]}", node.id
                    )
                )
    return issues


def _blocking(issues: list[ChecklistIssue]) -> list[ChecklistIssue]:
    return [i for i in issues if i.level == "error"]


def _fix_first(blocking: list[ChecklistIssue], action: str) -> str:
    return f"Fix {len(blocking)} thing(s) before {action}: {blocking[0].message}"


@transaction.atomic
def submit_for_publish(version: CourseVersion, user) -> CourseVersion:
    if version.state != CourseVersion.State.DRAFT:
        raise NotEditable("Only a draft can be submitted for publishing.")
    blocking = _blocking(publish_checklist(version))
    if blocking:
        raise InvalidOperation(_fix_first(blocking, "submitting"))
    version.state = CourseVersion.State.IN_REVIEW
    version.submitted_at = timezone.now()
    version.submitted_by = user
    version.save(update_fields=["state", "submitted_at", "submitted_by"])
    return version


@transaction.atomic
def publish_version(version: CourseVersion, user) -> CourseVersion:
    if version.state not in CourseVersion.OPEN_STATES:
        raise NotEditable("This version is already published or archived.")
    blocking = _blocking(publish_checklist(version))
    if blocking:
        raise InvalidOperation(_fix_first(blocking, "publishing"))
    try:
        version.publish(user)
    except ValidationError as exc:
        raise InvalidOperation(" ".join(exc.messages)) from exc
    return version


@transaction.atomic
def return_to_draft(version: CourseVersion) -> CourseVersion:
    if version.state != CourseVersion.State.IN_REVIEW:
        raise InvalidOperation("Only a version that is in review can be returned to draft.")
    version.state = CourseVersion.State.DRAFT
    version.submitted_at = None
    version.submitted_by = None
    version.save(update_fields=["state", "submitted_at", "submitted_by"])
    return version
