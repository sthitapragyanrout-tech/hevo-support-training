"""The ordering rules on their own: no database, no requests."""

import pytest

from apps.progress.sequencing import (
    FREE,
    SEQUENTIAL,
    Availability,
    LessonRef,
    lesson_availability,
    next_lesson_id,
)


def lessons(*spec):
    """lessons(("a", True), ("b", False)) -> refs with ids 1, 2, … in order."""
    return [LessonRef(i, title, required) for i, (title, required) in enumerate(spec, start=1)]


THREE = lessons(("One", True), ("Two", True), ("Three", True))


class TestFreeOrder:
    def test_nothing_is_ever_locked(self):
        result = lesson_availability(THREE, set(), FREE)
        assert all(not a.locked for a in result.values())

    def test_an_unknown_order_behaves_as_free(self):
        assert not any(a.locked for a in lesson_availability(THREE, set(), "whatever").values())


class TestSequential:
    def test_only_the_first_lesson_is_open_at_the_start(self):
        result = lesson_availability(THREE, set(), SEQUENTIAL)
        assert result[1] == Availability(locked=False)
        assert result[2] == Availability(locked=True, blocked_by=1)
        assert result[3] == Availability(locked=True, blocked_by=1)  # the earliest unfinished

    def test_finishing_a_lesson_opens_the_next(self):
        result = lesson_availability(THREE, {1}, SEQUENTIAL)
        assert [result[i].locked for i in (1, 2, 3)] == [False, False, True]
        assert result[3].blocked_by == 2

    def test_everything_is_open_once_everything_before_it_is_done(self):
        result = lesson_availability(THREE, {1, 2}, SEQUENTIAL)
        assert not any(a.locked for a in result.values())

    def test_a_finished_lesson_is_never_locked_even_if_an_earlier_one_is_not(self):
        # Lesson 1 was re-opened after lesson 2 was done: 2 keeps its history.
        result = lesson_availability(THREE, {2}, SEQUENTIAL)
        assert result[2].locked is False
        assert result[3].locked is True and result[3].blocked_by == 1

    def test_an_empty_course_is_fine(self):
        assert lesson_availability([], set(), SEQUENTIAL) == {}


class TestOptionalLessons:
    def mixed(self):
        return lessons(("One", True), ("Bonus", False), ("Two", True))

    def test_an_optional_lesson_never_holds_anyone_up(self):
        result = lesson_availability(self.mixed(), {1}, SEQUENTIAL)
        assert result[2].locked is False  # the bonus itself is open
        assert result[3].locked is False  # and skipping it blocks nothing

    def test_but_an_optional_lesson_still_waits_its_turn(self):
        result = lesson_availability(self.mixed(), set(), SEQUENTIAL)
        assert result[2] == Availability(locked=True, blocked_by=1)

    def test_an_unfinished_optional_lesson_is_not_named_as_the_blocker(self):
        result = lesson_availability(self.mixed(), set(), SEQUENTIAL)
        assert result[3].blocked_by == 1


class TestNextLesson:
    def test_the_first_unfinished_lesson(self):
        assert next_lesson_id(THREE, set(), SEQUENTIAL) == 1
        assert next_lesson_id(THREE, {1}, SEQUENTIAL) == 2
        assert next_lesson_id(THREE, {1, 2}, SEQUENTIAL) == 3

    def test_nothing_when_everything_is_done(self):
        assert next_lesson_id(THREE, {1, 2, 3}, SEQUENTIAL) is None
        assert next_lesson_id([], set(), SEQUENTIAL) is None

    def test_in_a_free_course_it_is_still_the_first_unfinished(self):
        assert next_lesson_id(THREE, {1}, FREE) == 2

    def test_required_lessons_come_before_optional_ones(self):
        mixed = lessons(("Bonus", False), ("One", True))
        assert next_lesson_id(mixed, set(), FREE) == 2
        assert next_lesson_id(mixed, set(), SEQUENTIAL) == 2

    def test_an_optional_lesson_is_offered_once_the_required_ones_are_done(self):
        mixed = lessons(("One", True), ("Bonus", False))
        assert next_lesson_id(mixed, {1}, SEQUENTIAL) == 2

    @pytest.mark.parametrize("order", [FREE, SEQUENTIAL])
    def test_it_is_never_a_locked_lesson(self, order):
        for done in (set(), {1}, {2}, {1, 2}):
            chosen = next_lesson_id(THREE, done, order)
            if chosen is not None:
                assert not lesson_availability(THREE, done, order)[chosen].locked
