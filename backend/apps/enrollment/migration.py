"""Moving a learner from the version they are on to the newest published one.

Nothing a learner did is ever deleted. What happens to each thing depends on whether it is the
*same* content in both versions. "Same" is decided by lineage, not by titles: each node and
activity remembers what it was cloned from (`origin`), so a renamed lesson is still the same
lesson.

* **Preserved**: the same activity with the same *fingerprint* (type, configuration, attempt
  limit, pass mark). The learner's results on it (progress, attempts, watch credit, practice
  tickets, the mentor-rated case with every submission and rating) are **re-pointed** to the
  new version's activity. They are not copied, so reports never count them twice.
* **Changed**: the same activity but a different fingerprint (the quiz questions changed, the
  rubric changed). Old results are not comparable, so by default they **stay on the old
  version** as history and the learner does it afresh. A trainer can choose to carry specific
  ones over anyway (a typo fix); the preview says which fields changed.
* **Added**: new on the new version; starts empty.
* **Removed**: not on the new version. Whatever the learner did there stays attached to the old
  version, still visible in their history; it simply isn't counted toward the new one.
* **Lessons** marked complete are carried when the lesson exists in both, but only if, with the
  results as they stand on the new version, nothing required is left to do: a lesson that now has
  a required activity still to do is no longer complete there (its tick stays on the old version
  as history, so nobody keeps a stale one), while one awaiting a mentor's rating stays awaiting.

* **Modules** a trainer switched off for this learner stay off on the new version (followed
  through lineage, so a renamed module is still the same module). A module with no ancestor is
  **new**: on by default, and the trainer may switch it off in the same step. What the learner did
  in a switched-off module is moved like anything else (history kept) but isn't listed or counted
  in the preview, since it isn't part of their course.

Preview and apply are the same code. The preview runs it for real inside a transaction and rolls
it back, so what is shown is what will happen. Applying is one transaction with the learner's
rows locked, writes a `VersionMove`, and is refused while a practice ticket is open or being
scored (let it finish or close it first). Moving someone who is already on the newest version
is refused ("already up to date").
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.bot_sim.models import SimSession
from apps.catalog.models import Activity, ContentNode, CourseVersion
from apps.manual_sim.models import QuizReview, SimCase
from apps.notifications import events
from apps.progress import services as progress
from apps.progress.models import (
    ActivityAttempt,
    ActivityProgress,
    LessonCompletion,
    VideoWatch,
)

from . import modules as modules_
from .errors import Conflict, EnrollmentError
from .models import Enrollment, VersionMove

# What kinds of work a learner can have on one activity, and the model that holds it.
WORK_MODELS: dict[str, Any] = {
    "progress": ActivityProgress,
    "attempts": ActivityAttempt,
    "watch": VideoWatch,
    "tickets": SimSession,
    "rated": SimCase,
    "quiz_reviews": QuizReview,
}


# ---------------------------------------------------------------------- fingerprints


def fingerprint(activity: Activity) -> str:
    """What has to match for an old result to still mean the same thing on the new copy."""
    return json.dumps(
        {
            "type": activity.activity_type,
            "config": activity.config,
            "attempts": activity.max_attempts,
            "mastery": activity.mastery_threshold,
        },
        sort_keys=True,
        default=str,
    )


def changed_fields(old: Activity, new: Activity) -> list[str]:
    """Which parts differ, by name (shown to the trainer)."""
    out: list[str] = []
    if old.activity_type != new.activity_type:
        out.append("type")
    if old.max_attempts != new.max_attempts:
        out.append("attempts")
    if old.mastery_threshold != new.mastery_threshold:
        out.append("pass mark")
    keys = set(old.config) | set(new.config)
    out += sorted(
        k
        for k in keys
        if json.dumps(old.config.get(k), sort_keys=True, default=str)
        != json.dumps(new.config.get(k), sort_keys=True, default=str)
    )
    return out


# ------------------------------------------------------------------------ lineage


def _node_origins(course) -> dict[int, int | None]:
    nodes = ContentNode.objects.filter(course_version__course=course)
    return dict(nodes.values_list("id", "origin_id"))


def _activity_origins(course) -> dict[int, int | None]:
    activities = Activity.objects.filter(content_node__course_version__course=course)
    return dict(activities.values_list("id", "origin_id"))


def _ancestor(start: int, origins: dict[int, int | None], wanted: set[int]) -> int | None:
    """Follow `origin` links from `start` until one lands in `wanted` (the old version)."""
    seen = {start}
    current = origins.get(start)
    while current is not None and current not in seen:
        if current in wanted:
            return current
        seen.add(current)
        current = origins.get(current)
    return None


def target_for(enrollment: Enrollment) -> CourseVersion | None:
    return (
        CourseVersion.objects.filter(
            course=enrollment.course, state=CourseVersion.State.PUBLISHED, root_node__isnull=False
        )
        .order_by("-version")
        .first()
    )


def blockers(enrollment: Enrollment, target: CourseVersion | None) -> list[str]:
    """Why this learner cannot be moved right now (empty = they can)."""
    out: list[str] = []
    if enrollment.state != Enrollment.State.ACTIVE:
        out.append("They are withdrawn from this course. Re-enroll them first.")
    if enrollment.course.archived_at is not None:
        out.append("The course is archived.")
    if target is None:
        out.append("The course has no published version.")
        return out
    if target.pk == enrollment.version_id:
        out.append("They are already on the newest version.")
    elif target.version < enrollment.version.version:
        out.append("The newest published version is older than the one they are on.")
    if SimSession.objects.filter(
        user=enrollment.user,
        preview=False,
        state__in=[SimSession.State.OPEN, SimSession.State.FINISHING],
        activity__content_node__course_version=enrollment.version,
    ).exists():
        out.append(
            "They have a practice ticket in progress. Let them finish it or close it, "
            "then move them."
        )
    return out


# --------------------------------------------------------------------------- engine


@dataclass
class _Item:
    target: Activity
    source: Activity | None
    status: str  # preserved | changed | added
    work: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    conflict: bool = False
    carried: bool = False


def _work_of(user, activity_ids: list[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for kind, model in WORK_MODELS.items():
        qs = model.objects.filter(user=user, activity_id__in=activity_ids)
        # `order_by()` clears the model's default ordering, which would otherwise be part of the
        # DISTINCT and repeat an activity once per row.
        for activity_id in qs.order_by().values_list("activity_id", flat=True).distinct():
            out.setdefault(activity_id, []).append(kind)
    return {k: sorted(v) for k, v in out.items()}


def _execute(
    enrollment: Enrollment,
    target: CourseVersion,
    carry: set[int],
    new_off: set[int],
    *,
    by,
    now,
    record: bool,
) -> dict[str, Any]:
    """Do the move (inside the caller's transaction) and describe it. `new_off` are new modules
    of the target the trainer chose to switch off."""
    user, course, source = enrollment.user, enrollment.course, enrollment.version

    # Lock what a rating or a hand-in could be changing: cases first (the same order those use),
    # then the learner's progress rows.
    list(
        SimCase.objects.select_for_update().filter(
            user=user, activity__content_node__course_version=source
        )
    )
    # Written quiz answers awaiting marks are locked the way a rating locks them: before the
    # learner's progress rows.
    list(
        QuizReview.objects.select_for_update().filter(
            user=user, activity__content_node__course_version=source
        )
    )
    list(
        ActivityProgress.objects.select_for_update().filter(
            user=user, activity__content_node__course_version=source
        )
    )

    node_origin = _node_origins(course)
    act_origin = _activity_origins(course)
    src_node_ids = set(
        ContentNode.objects.filter(course_version=source).values_list("pk", flat=True)
    )
    src_acts = {a.pk: a for a in Activity.objects.filter(content_node__course_version=source)}

    tgt_nodes = list(ContentNode.objects.filter(course_version=target).order_by("order", "id"))
    tgt_by_id = {n.pk: n for n in tgt_nodes}
    tgt_acts = list(
        Activity.objects.filter(content_node__course_version=target).select_related("content_node")
    )
    src_nodes = {n.pk: n for n in ContentNode.objects.filter(course_version=source)}

    # Modules: off stays off (through lineage); a module with no ancestor is new, and on unless
    # the trainer switched it off here.
    off_src = modules_.excluded_of(enrollment)
    tgt_modules = [n for n in tgt_nodes if n.kind == ContentNode.Kind.SEGMENT]
    module_status: dict[int, str] = {}
    for seg in tgt_modules:
        ancestor = _ancestor(seg.pk, node_origin, src_node_ids)
        module_status[seg.pk] = (
            "new" if ancestor is None else "off" if ancestor in off_src else "on"
        )
    new_ids = {pk for pk, status in module_status.items() if status == "new"}
    if new_off - new_ids:
        raise EnrollmentError("You can only switch off a module that is new in this version.")
    off_target = {pk for pk, status in module_status.items() if status == "off"} | new_off
    if tgt_modules and len(off_target) >= len(tgt_modules):
        raise Conflict(
            "Every module on the newest version is switched off for them (the ones they had "
            "were removed or are off). Give them a module first, then move them."
        )

    def hidden_in_target(node_id: int) -> bool:
        return _module_of(node_id, tgt_by_id) in off_target

    def hidden_in_source(node_id: int) -> bool:
        return _module_of(node_id, src_nodes) in off_src

    # Which old activity each new one continues (first one wins if lineage were ever ambiguous).
    taken: set[int] = set()
    pairs: dict[int, int] = {}
    for activity in sorted(tgt_acts, key=lambda a: (a.content_node_id, a.order, a.pk)):
        found = _ancestor(activity.pk, act_origin, set(src_acts))
        if found is not None and found not in taken:
            taken.add(found)
            pairs[activity.pk] = found

    work = _work_of(user, list(src_acts))
    items: list[_Item] = []
    for activity in tgt_acts:
        old_id = pairs.get(activity.pk)
        if old_id is None:
            items.append(_Item(activity, None, "added"))
            continue
        old = src_acts[old_id]
        same = fingerprint(old) == fingerprint(activity)
        item = _Item(
            activity,
            old,
            "preserved" if same else "changed",
            work=work.get(old_id, []),
            fields=[] if same else changed_fields(old, activity),
        )
        # The learner already has results on the new activity (they used both versions at some
        # point): moving would collide, so their earlier results stay where they are.
        item.conflict = bool(item.work) and any(
            model.objects.filter(user=user, activity=activity).exists()
            for model in WORK_MODELS.values()
        )
        items.append(item)

    carry_able = {i.target.pk for i in items if i.status == "changed" and i.work and not i.conflict}
    unknown = carry - carry_able
    if unknown:
        raise EnrollmentError(
            "Some of the items you chose can’t be carried over: they are unchanged, new, "
            "have nothing to carry, or already have results on the new version."
        )

    for item in items:
        if item.source is None or not item.work or item.conflict:
            continue
        if item.status == "preserved" or item.target.pk in carry:
            _repoint(user, item.source, item.target)
            item.carried = True

    # Lessons: carry the tick where the lesson exists in both, then judge it again.
    lesson_rows = {
        c.node_id: c for c in LessonCompletion.objects.filter(user=user, node_id__in=src_node_ids)
    }
    lesson_outcomes: dict[int, str] = {}
    left_lessons: list[dict[str, Any]] = []
    mapped_sources: set[int] = set()
    for node in tgt_nodes:
        if node.kind != ContentNode.Kind.TOPIC:
            continue
        old_id = _ancestor(node.pk, node_origin, src_node_ids)
        if old_id is None or old_id in mapped_sources:
            continue
        mapped_sources.add(old_id)
        row = lesson_rows.get(old_id)
        if row is None:
            continue
        if LessonCompletion.objects.filter(user=user, node=node).exists():
            lesson_outcomes[node.pk] = "left"  # already has its own completion on the new version
            continue
        # Judge the lesson with the results as they now stand on the new version. If something
        # required is still to do it is no longer complete there, and its tick stays on the old
        # version as history; otherwise the tick moves (provisional while a rating is awaited).
        pending, awaiting = progress._unfinished(user, node)
        if pending:
            lesson_outcomes[node.pk] = "reopened"
            continue
        LessonCompletion.objects.filter(pk=row.pk).update(node=node, provisional=bool(awaiting))
        lesson_outcomes[node.pk] = "awaiting" if awaiting else "kept"
    for old_id in lesson_rows:
        if old_id not in mapped_sources:
            left_lessons.append({"id": old_id, "title": src_nodes[old_id].title})

    removed = [
        {
            "id": a.pk,
            "title": a.title,
            "type": a.activity_type,
            "lesson": _lesson_title(a, src_nodes),
            "work": work.get(a.pk, []),
            "has_work": bool(work.get(a.pk)),
        }
        for a in src_acts.values()
        if a.pk not in taken
    ]

    # What the trainer is shown leaves out switched-off modules; the record below keeps it all.
    hidden_activity_ids = {a.pk for a in src_acts.values() if hidden_in_source(a.content_node_id)}
    result = _describe(
        source,
        target,
        [i for i in items if not hidden_in_target(i.target.content_node_id)],
        tgt_by_id,
        {pk: v for pk, v in lesson_outcomes.items() if not hidden_in_target(pk)},
        [r for r in removed if r["id"] not in hidden_activity_ids],
        [lesson for lesson in left_lessons if not hidden_in_source(lesson["id"])],
    )
    result["modules"] = [
        {
            "id": m.pk,
            "title": m.title,
            "status": module_status[m.pk],  # on | off | new
            "enabled": m.pk not in off_target,
        }
        for m in tgt_modules
    ]
    result["counts"]["modules_new"] = len(new_ids)
    result["counts"]["modules_new_off"] = len(new_off)
    if record:
        enrollment.version = target
        enrollment.save(update_fields=["version"])
        modules_.write_exclusions(enrollment, off_target)
        VersionMove.objects.create(
            enrollment=enrollment,
            from_version=source,
            to_version=target,
            moved_by=by,
            moved_at=now,
            summary={
                "counts": result["counts"],
                "carried": [[i.source.pk, i.target.pk] for i in items if i.carried and i.source],
                "left_behind": [
                    i.source.pk for i in items if i.source is not None and i.work and not i.carried
                ]
                + [r["id"] for r in removed if r["has_work"]],
                "reopened": [pk for pk, v in lesson_outcomes.items() if v == "reopened"],
                "modules": {
                    "off": sorted(off_target),
                    "new": sorted(new_ids),
                    "new_off": sorted(new_off),
                },
            },
        )
    return result


def _module_of(node_id: int, nodes: dict[int, ContentNode]) -> int | None:
    """The module (`segment`) a node of one version sits in, walking up through `nodes`."""
    node = nodes.get(node_id)
    while node is not None and node.kind != ContentNode.Kind.SEGMENT:
        node = nodes.get(node.parent_id) if node.parent_id is not None else None
    return node.pk if node is not None else None


def _lesson_title(activity: Activity, nodes: dict[int, ContentNode]) -> str:
    node = nodes.get(activity.content_node_id)
    if node is not None and node.kind == ContentNode.Kind.SUBTOPIC and node.parent_id in nodes:
        return nodes[node.parent_id].title
    return node.title if node else ""


def _repoint(user, old: Activity, new: Activity) -> None:
    """Move every row this learner has on `old` over to `new`."""
    for model in WORK_MODELS.values():
        model.objects.filter(user=user, activity=old).update(activity=new)
    if old.max_attempts != new.max_attempts and new.activity_type in ("mcq", "bot_sim"):
        _settle_attempts(user, new)


def _settle_attempts(user, activity: Activity) -> None:
    """After carrying results onto a different attempt limit, make the state honest: out of
    tries is "finished, not passed"; tries gained again is "started"."""
    row = ActivityProgress.objects.filter(user=user, activity=activity).first()
    if row is None or row.state == ActivityProgress.State.COMPLETED:
        return
    if QuizReview.objects.filter(
        user=user, activity=activity, state=QuizReview.State.SUBMITTED
    ).exists():
        return  # waiting for marks: whether the tries are used up is decided when it is marked
    taken = ActivityAttempt.objects.filter(user=user, activity=activity).count()
    used_up = bool(activity.max_attempts) and taken >= activity.max_attempts
    wanted = ActivityProgress.State.EXHAUSTED if used_up else ActivityProgress.State.STARTED
    if row.state != wanted:
        row.state = wanted
        row.save(update_fields=["state"])


# ----------------------------------------------------------------------- the report


def _describe(source, target, items, tgt_by_id, lesson_outcomes, removed, left_lessons):
    def lesson_of(activity: Activity) -> ContentNode | None:
        node = tgt_by_id.get(activity.content_node_id)
        if node is None:
            return None
        if node.kind == ContentNode.Kind.SUBTOPIC:
            return tgt_by_id.get(node.parent_id)
        return node

    lessons: dict[int, dict[str, Any]] = {}
    for item in items:
        lesson = lesson_of(item.target)
        if lesson is None:
            continue
        entry = lessons.setdefault(
            lesson.pk,
            {
                "id": lesson.pk,
                "title": lesson.title,
                "module": tgt_by_id[lesson.parent_id].title
                if lesson.parent_id in tgt_by_id
                else "",
                "outcome": lesson_outcomes.get(lesson.pk),
                "activities": [],
            },
        )
        entry["activities"].append(
            {
                "id": item.target.pk,
                "title": item.target.title,
                "type": item.target.activity_type,
                "status": item.status,
                "work": item.work,
                "has_work": bool(item.work),
                "fields": item.fields,
                "conflict": item.conflict,
                "carried": item.carried,
                # A change can be carried over by choice (if there is anything to carry).
                "can_carry": item.status == "changed" and bool(item.work) and not item.conflict,
            }
        )
    for pk, outcome in lesson_outcomes.items():
        lessons.setdefault(
            pk,
            {
                "id": pk,
                "title": tgt_by_id[pk].title,
                "module": tgt_by_id[tgt_by_id[pk].parent_id].title
                if tgt_by_id[pk].parent_id in tgt_by_id
                else "",
                "outcome": outcome,
                "activities": [],
            },
        )["outcome"] = outcome

    counts = {
        "preserved": sum(1 for i in items if i.status == "preserved" and i.carried),
        "preserved_untouched": sum(1 for i in items if i.status == "preserved" and not i.work),
        "changed": sum(1 for i in items if i.status == "changed"),
        "changed_carried": sum(1 for i in items if i.status == "changed" and i.carried),
        "changed_with_work": sum(1 for i in items if i.status == "changed" and i.work),
        "added": sum(1 for i in items if i.status == "added"),
        "removed": len(removed),
        "removed_with_work": sum(1 for r in removed if r["has_work"]),
        "lessons_kept": sum(1 for v in lesson_outcomes.values() if v == "kept"),
        "lessons_awaiting": sum(1 for v in lesson_outcomes.values() if v == "awaiting"),
        "lessons_reopened": sum(1 for v in lesson_outcomes.values() if v == "reopened"),
        "lessons_left": len(left_lessons) + sum(1 for v in lesson_outcomes.values() if v == "left"),
    }
    relevant = [
        e
        for e in lessons.values()
        if e["outcome"] or any(a["status"] != "preserved" or a["has_work"] for a in e["activities"])
    ]
    order = {n.pk: n.order for n in tgt_by_id.values()}
    relevant.sort(key=lambda e: (order.get(e["id"], 0), e["id"]))
    return {
        "from": {"id": source.pk, "number": source.version},
        "to": {"id": target.pk, "number": target.version},
        "counts": counts,
        "lessons": relevant,
        "removed": removed,
        "left_lessons": left_lessons,
    }


# ---------------------------------------------------------------------------- API


def preview(
    enrollment: Enrollment, carry: set[int] | None = None, new_off: set[int] | None = None
) -> dict[str, Any]:
    """What moving this learner would do, exactly: run for real, then roll back."""
    target = target_for(enrollment)
    problems = blockers(enrollment, target)
    base: dict[str, Any] = {"blockers": problems, "can_apply": not problems}
    if problems or target is None:
        return {
            **base,
            "from": {"id": enrollment.version_id, "number": enrollment.version.version},
            "to": {"id": target.pk, "number": target.version} if target else None,
        }
    try:
        with transaction.atomic():
            locked = Enrollment.objects.select_for_update().get(pk=enrollment.pk)
            result = _execute(
                locked,
                target,
                set(carry or ()),
                set(new_off or ()),
                by=None,
                now=timezone.now(),
                record=False,
            )
            transaction.set_rollback(True)
    except Conflict as exc:  # something the trainer must fix first: shown, not an error page
        return {
            "blockers": [exc.message],
            "can_apply": False,
            "from": {"id": enrollment.version_id, "number": enrollment.version.version},
            "to": {"id": target.pk, "number": target.version},
        }
    return {**base, **result}


@transaction.atomic
def apply(
    enrollment: Enrollment,
    *,
    to_version_id: int | None,
    carry: set[int] | None = None,
    new_off: set[int] | None = None,
    by=None,
    now=None,
) -> dict[str, Any]:
    """Move the learner. `to_version_id` is the version the trainer was shown; if a newer one has
    been published since, nothing happens and they are asked to look again."""
    # Lock the enrollment row only: locking the joined user/course rows as well would deadlock
    # against a rating being written for the same learner.
    locked = (
        Enrollment.objects.select_for_update(of=("self",))
        .select_related("version", "course", "user")
        .get(pk=enrollment.pk)
    )
    target = target_for(locked)
    problems = blockers(locked, target)
    if problems:
        raise Conflict(problems[0])
    assert target is not None
    if to_version_id is not None and to_version_id != target.pk:
        raise Conflict("A newer version was published since you looked. Open the preview again.")
    result = _execute(
        locked,
        target,
        set(carry or ()),
        set(new_off or ()),
        by=by,
        now=now or timezone.now(),
        record=True,
    )
    # Only here, never in the preview (which runs `_execute` and rolls back): tell the learner.
    move = VersionMove.objects.filter(enrollment=locked).order_by("-id").first()
    if move is not None:
        events.moved(locked, move)
    return result
