"""How a mentor-rated simulation affects a course: nothing is finished, failed or unblocked
by a date passing; the only ways out are a pass, or a trainer or admin extending, waiving or
closing. Each row of the plan's progression table, in a course that goes in order and one that
does not. These run with `holds_next="pass"` (the next lesson waits for the rating to
pass); the default, where handing the work in opens the next lesson, is in
`test_manual_sim_handin_gate.py`."""

import pytest

from apps.catalog.models import Activity, ContentNode
from apps.manual_sim import services
from apps.manual_sim.models import SimCase
from apps.progress import services as progress
from apps.progress.models import ActivityProgress, LessonCompletion
from tests.manual_sim_helpers import FAIL, PASS, at, people, rated_course

pytestmark = pytest.mark.django_db

ANSWER = "My reply."


@pytest.fixture
def ordered(make_role_user):
    w = {
        **rated_course(
            make_role_user,
            order="sequential",
            title="Ordered",
            config={"holds_next": "pass"},
        ),
        **people(make_role_user),
    }
    # They have done the first lesson, so the simulation's lesson is the one in front of them.
    first_activity = w["first"].activities.get()
    progress.complete_activity(w["learner"], first_activity.pk)
    progress.complete_lesson(w["learner"], w["first"].pk)
    return w


def third_locked(w) -> bool:
    third = ContentNode.objects.get(
        pk=w["third"].pk
    )  # fresh: the fixture's copy has a stale version
    return progress.lock_of(w["learner"], third) is not None


def lesson_can_finish(w) -> bool:
    try:
        progress.complete_lesson(w["learner"], w["second"].pk)
    except progress.LessonBlocked:
        return False
    return True


def hand_in(w, now=None):
    return services.submit(w["learner"], w["activity"].pk, ANSWER, now=now or at())


def rate(w, sub, scores, now=None):
    return services.rate(w["mentor"], sub.pk, scores, {}, "Comment.", now=now or at(hours=1))


class TestInAnOrderedCourse:
    def test_not_yet_submitted_blocks_the_next_lesson(self, ordered):
        services.open_case(ordered["learner"], ordered["activity"].pk, now=at())
        assert third_locked(ordered) and not lesson_can_finish(ordered)

    def test_overdue_and_unsubmitted_still_blocks_and_nothing_changes_by_itself(self, ordered):
        case = services.open_case(ordered["learner"], ordered["activity"].pk, now=at())
        long_after = at(days=90)
        summary = services.case_summary(case, now=long_after)
        assert summary["overdue"] is True and summary["status"] == "not_submitted"
        assert third_locked(ordered) and not lesson_can_finish(ordered)
        assert ActivityProgress.objects.get(activity=ordered["activity"]).state == "started"

    def test_waiting_for_a_mentor_blocks_even_when_the_review_is_overdue(self, ordered):
        sub = hand_in(ordered)
        assert services.case_summary(SimCase.objects.get(), now=at(days=30))["status"] == "waiting"
        assert third_locked(ordered) and not lesson_can_finish(ordered)
        assert sub.state == "submitted"  # an overdue review is escalated, never auto-completed

    def test_changes_requested_blocks_and_so_does_needing_attention(self, ordered):
        for n in range(3):
            rate(ordered, hand_in(ordered, at(days=n)), FAIL, now=at(days=n, hours=1))
        summary = services.case_summary(SimCase.objects.get(), now=at(days=4))
        assert summary["status"] == "changes_requested" and summary["needs_attention"] is True
        assert third_locked(ordered) and not lesson_can_finish(ordered)

    def test_a_pass_finishes_it_and_opens_the_next_lesson(self, ordered):
        rate(ordered, hand_in(ordered), PASS)
        assert lesson_can_finish(ordered)
        assert not third_locked(ordered)
        assert ActivityProgress.objects.get(activity=ordered["activity"]).state == "completed"

    @pytest.mark.parametrize("act", ["waive", "close"])
    def test_waiving_or_closing_stops_it_blocking_but_is_never_a_pass(self, ordered, act):
        case = services.open_case(ordered["learner"], ordered["activity"].pk, now=at())
        getattr(services, act)(ordered["trainer"], case.pk, "Because.", now=at(days=1))
        assert lesson_can_finish(ordered) and not third_locked(ordered)
        row = ActivityProgress.objects.get(activity=ordered["activity"])
        assert row.state == "exhausted" and row.state != "completed"
        status = services.case_summary(SimCase.objects.get(), now=at(days=2))["status"]
        assert status == ("waived" if act == "waive" else "not_passed")

    def test_reopening_blocks_again_and_reopens_the_finished_lesson(self, ordered):
        case = services.open_case(ordered["learner"], ordered["activity"].pk, now=at())
        services.waive(ordered["trainer"], case.pk, "Because.", now=at(days=1))
        progress.complete_lesson(ordered["learner"], ordered["second"].pk)
        assert LessonCompletion.objects.filter(node=ordered["second"]).exists()
        services.reopen(ordered["trainer"], case.pk, "Mistake.", now=at(days=2))
        assert not LessonCompletion.objects.filter(node=ordered["second"]).exists()
        assert third_locked(ordered) and not lesson_can_finish(ordered)

    def test_extending_does_not_unblock_it(self, ordered):
        case = services.open_case(ordered["learner"], ordered["activity"].pk, now=at())
        services.extend(ordered["trainer"], case.pk, 5, "More time.", now=at(days=8))
        assert third_locked(ordered) and not lesson_can_finish(ordered)


class TestInACourseWithNoOrder:
    @pytest.fixture
    def free(self, make_role_user):
        return {
            **rated_course(
                make_role_user, order="free", title="Free", config={"holds_next": "pass"}
            ),
            **people(make_role_user),
        }

    def test_nothing_gates_other_lessons_but_the_lesson_itself_still_waits(self, free):
        services.open_case(free["learner"], free["activity"].pk, now=at())
        third = ContentNode.objects.get(pk=free["third"].pk)
        assert progress.lock_of(free["learner"], third) is None
        assert not lesson_can_finish(free)
        rate(free, hand_in(free), PASS)
        assert lesson_can_finish(free)


class TestWhatNeverBlocks:
    def test_an_optional_simulation_never_holds_a_lesson_up(self, make_role_user):
        w = {
            **rated_course(make_role_user, required=False, title="Optional"),
            **people(make_role_user),
        }
        assert lesson_can_finish(w)

    def test_an_unconfigured_simulation_never_holds_a_lesson_up(self, make_role_user):
        w = {**rated_course(make_role_user, title="Legacy"), **people(make_role_user)}
        Activity.objects.filter(pk=w["activity"].pk).update(config={}, max_attempts=3)
        assert lesson_can_finish(w)


class TestWhatALearnerAndATrainerCannotDo:
    def test_a_learner_cannot_mark_it_complete_and_is_told_why(self, make_role_user):
        w = {**rated_course(make_role_user), **people(make_role_user)}
        with pytest.raises(progress.NotCompletable) as caught:
            progress.complete_activity(w["learner"], w["activity"].pk)
        assert "mentor passes your work" in caught.value.message
        with pytest.raises(progress.NotCompletable):
            progress.uncomplete_activity(w["learner"], w["activity"].pk)

    def test_attempts_cannot_be_reset_because_the_history_is_the_record(self, make_role_user):
        w = {**rated_course(make_role_user), **people(make_role_user)}
        rate(w, hand_in(w), FAIL)
        with pytest.raises(progress.NotCompletable) as caught:
            progress.reset_attempts_for(w["learner"], w["activity"].pk)
        assert "keeps its history" in caught.value.message
        assert services.case_summary(SimCase.objects.get())["revisions"] == 1  # still all there

    def test_the_quiz_style_attempt_endpoints_do_not_apply_to_it(self, make_role_user):
        w = {**rated_course(make_role_user), **people(make_role_user)}
        with pytest.raises(progress.NotCompletable):
            progress.submit_attempt(w["learner"], w["activity"].pk, [])
        with pytest.raises(progress.NotCompletable):
            progress.attempts_report(w["learner"], w["activity"].pk)

    def test_the_progress_summary_ignores_the_old_attempt_limit(self, make_role_user):
        w = {**rated_course(make_role_user, max_attempts=3), **people(make_role_user)}
        for n in range(4):
            rate(w, hand_in(w, at(days=n)), FAIL, now=at(days=n, hours=1))
        summary = progress.course_progress(w["learner"], w["version"].pk)["attempts"][
            w["activity"].pk
        ]
        assert (
            summary["count"] == 4 and summary["attempts_left"] == 0
        )  # computed from the old field
        assert ActivityProgress.objects.get().state == "started"  # ...which must not be trusted
