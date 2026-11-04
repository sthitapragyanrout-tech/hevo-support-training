"""
Which lessons a learner may open, and which one is next. Pure functions over
plain values — no database, no request — so the rules can be read and tested
on their own, and replaced by richer ones (per-node rule trees, mentor
sign-off, date windows: docs/architecture.md §7) without touching callers.

V1 has one rule. A course is either `free` (everything is open) or
`sequential`: a lesson is open once **every required lesson before it in the
course is complete**. Optional lessons never hold anyone up, and a lesson that
is already complete is never locked.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

FREE = "free"
SEQUENTIAL = "sequential"
ORDERS = (FREE, SEQUENTIAL)


@dataclass(frozen=True)
class LessonRef:
    """One lesson, in course order."""

    id: int
    title: str
    required: bool = True


@dataclass(frozen=True)
class Availability:
    locked: bool
    #: The lesson to finish first — the earliest incomplete required one before this.
    blocked_by: int | None = None


def lesson_availability(
    lessons: Iterable[LessonRef], completed: set[int], learning_order: str
) -> dict[int, Availability]:
    """Availability of every lesson, keyed by lesson id."""
    result: dict[int, Availability] = {}
    first_unfinished: int | None = None  # earliest incomplete *required* lesson so far
    for lesson in lessons:
        done = lesson.id in completed
        if learning_order != SEQUENTIAL or done or first_unfinished is None:
            result[lesson.id] = Availability(locked=False)
        else:
            result[lesson.id] = Availability(locked=True, blocked_by=first_unfinished)
        if lesson.required and not done and first_unfinished is None:
            first_unfinished = lesson.id
    return result


def next_lesson_id(
    lessons: Iterable[LessonRef], completed: set[int], learning_order: str
) -> int | None:
    """What to do next: the first open, unfinished lesson — required ones
    first, so an optional lesson never pulls someone off the main path."""
    ordered = list(lessons)
    availability = lesson_availability(ordered, completed, learning_order)
    open_unfinished = [
        lesson
        for lesson in ordered
        if lesson.id not in completed and not availability[lesson.id].locked
    ]
    for lesson in open_unfinished:
        if lesson.required:
            return lesson.id
    return open_unfinished[0].id if open_unfinished else None
