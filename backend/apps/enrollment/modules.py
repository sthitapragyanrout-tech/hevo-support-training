"""Which modules of a course a learner gets, per enrollment.

A module is a `segment` of the pinned version. The default is **all of them**; a trainer may
switch some off for one learner (`ModuleExclusion`). Switching a module off hides it from the
learner and the server refuses it (see `access.disabled_module_ids` and its callers); nothing the
learner already did in it is deleted, it just stops counting, and switching it back on brings it
back.

This file only decides and writes the selection; callers audit (they know the request).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q

from apps.bot_sim.models import SimSession
from apps.catalog.models import ContentNode, CourseVersion
from apps.notifications import events

from .errors import Conflict, EnrollmentError
from .models import Enrollment, ModuleExclusion


def modules_of(version: CourseVersion) -> list[ContentNode]:
    """The modules of a version, in course order."""
    return list(
        ContentNode.objects.filter(course_version=version, kind=ContentNode.Kind.SEGMENT).order_by(
            "order", "id"
        )
    )


def excluded_ids(version: CourseVersion, enabled: Iterable[int] | None) -> list[int]:
    """The module ids to switch **off** when `enabled` is what the trainer ticked (None = all on).

    Refuses an id that is not a module of this version (someone else's, or a lesson) and an empty
    choice: a learner with no module has no course."""
    if enabled is None:
        return []
    wanted = set(enabled)
    modules = modules_of(version)
    known = {m.pk for m in modules}
    if wanted - known:
        raise EnrollmentError("One of the chosen modules isn’t part of this course.")
    if not wanted:
        raise EnrollmentError("A learner needs at least one module. Tick at least one.")
    return [m.pk for m in modules if m.pk not in wanted]


def excluded_of(enrollment: Enrollment) -> set[int]:
    return set(
        ModuleExclusion.objects.filter(enrollment=enrollment).values_list("node_id", flat=True)
    )


def write_exclusions(enrollment: Enrollment, excluded: Iterable[int]) -> None:
    """Make the enrollment's switched-off set exactly `excluded`."""
    wanted = set(excluded)
    have = excluded_of(enrollment)
    if have - wanted:
        ModuleExclusion.objects.filter(enrollment=enrollment, node_id__in=have - wanted).delete()
    ModuleExclusion.objects.bulk_create(
        [ModuleExclusion(enrollment=enrollment, node_id=n) for n in sorted(wanted - have)]
    )


@dataclass
class Change:
    enrollment: Enrollment
    before_off: list[int]
    after_off: list[int]


def open_ticket_blockers(enrollment: Enrollment, newly_off: set[int]) -> list[str]:
    """Why these modules cannot be switched off right now (empty = they can)."""
    if not newly_off:
        return []
    live = SimSession.objects.filter(
        user=enrollment.user,
        preview=False,
        state__in=[SimSession.State.OPEN, SimSession.State.FINISHING],
    ).filter(
        Q(activity__content_node__parent_id__in=newly_off)
        | Q(activity__content_node__parent__parent_id__in=newly_off)
    )
    if live.exists():
        return [
            "They have a practice ticket in progress in a module you are switching off. "
            "Let them finish it or close it first."
        ]
    return []


@transaction.atomic
def set_modules(enrollment: Enrollment, enabled: Iterable[int]) -> Change:
    """Set exactly which modules the learner gets (the ticked ones)."""
    row = Enrollment.objects.select_for_update().select_related("version").get(pk=enrollment.pk)
    if row.state != Enrollment.State.ACTIVE:
        raise Conflict("They are withdrawn from this course; re-enroll them first.")
    after = excluded_ids(row.version, list(enabled))
    before = excluded_of(row)
    problems = open_ticket_blockers(row, set(after) - before)
    if problems:
        raise Conflict(problems[0])
    write_exclusions(row, after)
    if set(after) != before:
        total = len(modules_of(row.version))
        events.modules_changed(row, total - len(after), total)
    return Change(row, sorted(before), sorted(after))
