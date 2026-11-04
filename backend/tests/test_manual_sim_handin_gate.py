"""Handing the work in opens the next lesson; the lesson is not *complete* until the rating
passes. (`holds_next="pass"` keeps the strict rule: see `test_manual_sim_progression.py`.)"""

import json

import pytest
from django.urls import reverse

from apps.activities import manual_sim as cfg
from apps.activities.registry import validate_config
from apps.catalog.models import Activity, ContentNode
from apps.manual_sim import services
from apps.progress import reporting
from apps.progress import services as progress
from apps.progress.models import ActivityProgress, LessonCompletion
from tests.manual_sim_helpers import FAIL, PASS, at, good_config, people, rated_course

pytestmark = pytest.mark.django_db

ANSWER = "My reply."


@pytest.fixture
def ordered(make_role_user):
    w = {
        **rated_course(make_role_user, order="sequential", title="Ordered"),
        **people(make_role_user),
    }
    progress.complete_activity(w["learner"], w["first"].activities.get().pk)
    progress.complete_lesson(w["learner"], w["first"].pk)
    return w


def third_locked(w) -> bool:
    third = ContentNode.objects.get(pk=w["third"].pk)
    return progress.lock_of(w["learner"], third) is not None


def can_finish(w) -> bool:
    try:
        progress.complete_lesson(w["learner"], w["second"].pk)
    except progress.LessonBlocked:
        return False
    return True


def hand_in(w, now=None):
    return services.submit(w["learner"], w["activity"].pk, ANSWER, now=now or at())


def rate(w, sub, scores, now=None):
    return services.rate(w["mentor"], sub.pk, scores, {}, "Comment.", now=now or at(hours=1))


def second_row(w) -> LessonCompletion | None:
    return LessonCompletion.objects.filter(user=w["learner"], node=w["second"]).first()


def view(w) -> dict:
    return progress.course_progress(w["learner"], w["version"].pk)


class TestTheConfigSetting:
    def test_it_defaults_to_handing_in_and_reads_only_the_two_values(self):
        assert cfg.holds_next({}) == "submit"
        assert cfg.holds_next({"holds_next": "pass"}) == "pass"
        assert cfg.holds_next({"holds_next": "later"}) == "submit"
        assert cfg.holds_next(None) == "submit"

    def test_the_studio_may_only_save_a_known_value(self):
        ok = good_config(holds_next="pass")
        assert validate_config("manual_sim", ok, strict=False) == []
        assert validate_config("manual_sim", good_config(holds_next="soon"), strict=False)

    def test_the_learner_is_told_which_it_is(self):
        assert cfg.learner_view(good_config())["holds_next"] == "submit"
        assert cfg.learner_view(good_config(holds_next="pass"))["holds_next"] == "pass"


class TestHandingInOpensTheNextLesson:
    def test_before_handing_in_the_lesson_and_what_follows_stay_locked(self, ordered):
        services.open_case(ordered["learner"], ordered["activity"].pk, now=at())
        assert not can_finish(ordered) and third_locked(ordered)

    def test_overdue_and_not_handed_in_still_blocks(self, ordered):
        case = services.open_case(ordered["learner"], ordered["activity"].pk, now=at())
        assert services.case_summary(case, now=at(days=90))["overdue"] is True
        assert not can_finish(ordered) and third_locked(ordered)

    def test_after_handing_in_the_lesson_can_be_finished_and_the_next_one_opens(self, ordered):
        hand_in(ordered)
        assert can_finish(ordered)
        assert not third_locked(ordered)
        row = second_row(ordered)
        assert row is not None and row.provisional is True
        assert ActivityProgress.objects.get(activity=ordered["activity"]).state == "started"

    def test_it_opens_even_when_the_review_is_overdue_and_nothing_completes_by_itself(
        self, ordered
    ):
        sub = hand_in(ordered)
        assert can_finish(ordered) and not third_locked(ordered)
        assert services.case_summary(sub.case, now=at(days=30))["status"] == "waiting"
        assert sub.state == "submitted"

    def test_the_learner_sees_it_as_open_but_not_complete(self, ordered):
        hand_in(ordered)
        can_finish(ordered)
        body = view(ordered)
        assert ordered["second"].pk not in body["completed_lessons"]
        assert body["awaiting_review_lessons"] == [ordered["second"].pk]
        assert ordered["third"].pk not in body["locked"]
        assert body["next_lesson_id"] == ordered["third"].pk

    def test_the_other_work_in_the_lesson_must_still_be_done(self, ordered):
        Activity.objects.create(
            content_node=ordered["second"],
            activity_type="reading",
            title="Also read",
            config={"source_url": "https://z.io"},
        )
        hand_in(ordered)
        assert not can_finish(ordered)
        extra = ordered["second"].activities.get(activity_type="reading")
        progress.complete_activity(ordered["learner"], extra.pk)
        assert can_finish(ordered)
        assert second_row(ordered).provisional is True

    def test_work_handed_in_by_someone_else_does_not_count(self, ordered):
        other = ordered["other"]
        progress.complete_activity(other, ordered["first"].activities.get().pk)
        progress.complete_lesson(other, ordered["first"].pk)
        services.submit(other, ordered["activity"].pk, ANSWER, now=at())
        assert not can_finish(ordered)

    def test_a_pass_mark_setting_of_pass_keeps_the_next_lesson_locked(self, make_role_user):
        w = {
            **rated_course(
                make_role_user,
                order="sequential",
                title="Strict",
                config={"holds_next": "pass"},
            ),
            **people(make_role_user),
        }
        progress.complete_activity(w["learner"], w["first"].activities.get().pk)
        progress.complete_lesson(w["learner"], w["first"].pk)
        hand_in(w)
        assert not can_finish(w) and third_locked(w)


class TestItIsNotCompleteUntilItPasses:
    def test_reports_do_not_count_a_lesson_awaiting_its_rating(self, ordered):
        hand_in(ordered)
        can_finish(ordered)
        learner = reporting.learners_queryset(course_id=ordered["course"].pk).get(
            pk=ordered["learner"].pk
        )
        assert learner.lessons_completed == 1  # the first lesson only
        detail = reporting.learner_detail(ordered["learner"])
        assert detail["courses"][0]["lessons_completed"] == 1

    def test_changes_requested_keeps_what_they_unlocked(self, ordered):
        sub = hand_in(ordered)
        can_finish(ordered)
        rate(ordered, sub, FAIL)
        assert second_row(ordered).provisional is True
        assert not third_locked(ordered)
        assert ordered["second"].pk in view(ordered)["awaiting_review_lessons"]

    def test_a_pass_settles_it_and_it_then_counts(self, ordered):
        sub = hand_in(ordered)
        can_finish(ordered)
        rate(ordered, sub, FAIL)
        revised = hand_in(ordered, at(days=1))
        rate(ordered, revised, PASS, now=at(days=1, hours=1))
        assert second_row(ordered).provisional is False
        body = view(ordered)
        assert ordered["second"].pk in body["completed_lessons"]
        assert body["awaiting_review_lessons"] == []
        learner = reporting.learners_queryset(course_id=ordered["course"].pk).get(
            pk=ordered["learner"].pk
        )
        assert learner.lessons_completed == 2

    def test_a_pass_before_marking_the_lesson_complete_is_plain_complete(self, ordered):
        rate(ordered, hand_in(ordered), PASS)
        assert can_finish(ordered)
        assert second_row(ordered).provisional is False

    def test_marking_it_complete_again_is_harmless(self, ordered):
        hand_in(ordered)
        can_finish(ordered)
        assert can_finish(ordered)
        assert LessonCompletion.objects.filter(node=ordered["second"]).count() == 1
        assert second_row(ordered).provisional is True

    @pytest.mark.parametrize("act", ["waive", "close"])
    def test_waiving_or_closing_settles_it_without_calling_it_passed(self, ordered, act):
        sub = hand_in(ordered)
        can_finish(ordered)
        getattr(services, act)(ordered["trainer"], sub.case_id, "Because.", now=at(days=1))
        assert second_row(ordered).provisional is False
        assert ActivityProgress.objects.get(activity=ordered["activity"]).state == "exhausted"


class TestWithdrawingAndReopening:
    def test_withdrawing_after_moving_on_does_not_lock_anything_again(self, ordered):
        sub = hand_in(ordered)
        can_finish(ordered)
        services.withdraw(ordered["learner"], sub.pk, now=at(hours=1))
        assert second_row(ordered) is not None and second_row(ordered).provisional is True
        assert not third_locked(ordered)
        assert ordered["second"].pk not in view(ordered)["completed_lessons"]

    def test_reopening_with_work_on_file_leaves_the_lesson_awaiting_a_rating(self, ordered):
        sub = hand_in(ordered)
        rate(ordered, sub, FAIL)
        can_finish(ordered)
        services.close(ordered["trainer"], sub.case_id, "Stop.", now=at(days=1))
        assert second_row(ordered).provisional is False
        services.reopen(ordered["trainer"], sub.case_id, "Mistake.", now=at(days=2))
        assert second_row(ordered) is not None and second_row(ordered).provisional is True
        assert not third_locked(ordered)

    def test_reopening_with_nothing_handed_in_closes_the_lesson_again(self, ordered):
        case = services.open_case(ordered["learner"], ordered["activity"].pk, now=at())
        services.waive(ordered["trainer"], case.pk, "Because.", now=at(days=1))
        assert can_finish(ordered)
        services.reopen(ordered["trainer"], case.pk, "Mistake.", now=at(days=2))
        assert second_row(ordered) is None
        assert third_locked(ordered) and not can_finish(ordered)


class TestYourOwnWorkInTheQueue:
    @pytest.fixture
    def world(self, make_role_user, media_dirs):
        return {**rated_course(make_role_user), **people(make_role_user)}

    def rows(self, client, world, who, tab):
        client.force_login(world[who])
        r = client.get(reverse("console_api:ratings-queue"), {"tab": tab})
        assert r.status_code == 200, r.content
        return r.json()

    def test_a_trainer_sees_their_own_work_in_all_but_can_not_rate_it(self, client, world):
        mine = services.submit(world["trainer"], world["activity"].pk, ANSWER, now=at())
        theirs = hand_in(world)
        body = self.rows(client, world, "trainer", "all")
        by_id = {row["id"]: row for row in body["results"]}
        assert set(by_id) == {mine.pk, theirs.pk}
        assert by_id[mine.pk]["own"] is True and by_id[mine.pk]["can_rate"] is False
        assert by_id[theirs.pk]["own"] is False and by_id[theirs.pk]["can_rate"] is True
        assert body["counts"]["all"] == 2

    def test_it_is_still_never_in_mine_or_the_pool(self, client, world):
        services.submit(world["trainer"], world["activity"].pk, ANSWER, now=at())
        for tab in ("mine", "pool"):
            assert self.rows(client, world, "trainer", tab)["results"] == []
        counts = self.rows(client, world, "trainer", "pool")["counts"]
        assert counts["pool"] == 0 and counts["mine"] == 0

    def test_they_can_open_it_but_are_told_they_can_not_rate_it(self, client, world):
        mine = services.submit(world["trainer"], world["activity"].pk, ANSWER, now=at())
        client.force_login(world["trainer"])
        thread = client.get(reverse("console_api:ratings-thread", args=[mine.pk]))
        assert thread.status_code == 200
        r = client.post(
            reverse("console_api:ratings-rate", args=[mine.pk]),
            json.dumps({"scores": PASS, "comment": "Fine."}),
            content_type="application/json",
        )
        assert r.status_code in (403, 409), r.content
        mine.refresh_from_db()
        assert mine.state == "submitted"
