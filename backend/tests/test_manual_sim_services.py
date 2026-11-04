"""Mentor-rated simulations, stages 2–3: assignment and routing, the lifecycle (open, submit,
revise, withdraw, rate), the two clocks, who may act, and what a trainer or admin can do. The
progression rules are in test_manual_sim_progression.py. Time is injected with `now=`."""

from datetime import timedelta

import pytest

from apps.manual_sim import access, assignments, services
from apps.manual_sim.errors import BadInput, Conflict, Forbidden, NotFound
from apps.manual_sim.models import MentorAssignment, RubricScore, SimCase, SimSubmission
from apps.progress import services as progress
from apps.progress.models import ActivityAttempt, ActivityProgress
from tests.manual_sim_helpers import FAIL, PASS, at, jpeg, pdf, people, png, rated_course

pytestmark = pytest.mark.django_db

ANSWER = "The pipeline stopped because the source password expired; rotate it and resume."


@pytest.fixture
def world(make_role_user):
    course = rated_course(make_role_user)
    return {**course, **people(make_role_user)}


def hand_in(world, now=None, *, who="learner", answer=ANSWER, **kw):
    return services.submit(world[who], world["activity"].pk, answer, now=now or at(), **kw)


def rate(world, sub, scores=PASS, *, by="mentor", now=None, comment="Good work."):
    return services.rate(world[by], sub.pk, scores, {}, comment, now=now or at(hours=1))


# ------------------------------------------------------------------------ assignment


class TestAssignmentRouting:
    def test_with_no_assignment_everything_goes_to_the_pool(self, world):
        sub = hand_in(world)
        assert (sub.assigned_mentor, sub.routing) == (None, "pool")

    def test_the_mentor_is_per_learner_and_per_course(self, world, make_role_user):
        other_course = rated_course(make_role_user, title="Second course")
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        assignments.assign_mentor(world["learner"], other_course["course"], world["mentor2"])
        assert assignments.mentor_for(world["learner"], world["course"]) == world["mentor"]
        assert assignments.mentor_for(world["learner"], other_course["course"]) == world["mentor2"]
        assert assignments.mentor_for(world["other"], world["course"]) is None
        first = hand_in(world)
        second = services.submit(world["learner"], other_course["activity"].pk, ANSWER, now=at())
        assert (first.assigned_mentor, first.routing) == (world["mentor"], "assignment")
        assert (second.assigned_mentor, second.routing) == (world["mentor2"], "assignment")

    @pytest.mark.parametrize("who", ["learner", "other", "nobody"])
    def test_only_an_eligible_mentor_can_be_assigned(self, world, who):
        # a learner, a different learner, or the learner themselves can't be a mentor
        candidates = {"learner": world["learner"], "other": world["other"], "nobody": None}
        with pytest.raises(BadInput):
            assignments.assign_mentor(world["learner"], world["course"], candidates[who])

    def test_a_mentor_cannot_mentor_themselves(self, world):
        with pytest.raises(BadInput):
            assignments.assign_mentor(world["mentor"], world["course"], world["mentor"])

    def test_a_deactivated_mentor_is_ignored_so_the_work_is_not_stranded(self, world):
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        world["mentor"].is_active = False
        world["mentor"].save()
        sub = hand_in(world)
        assert (sub.assigned_mentor, sub.routing) == (None, "pool")

    def test_a_mentor_who_lost_the_permission_is_ignored(self, world):
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        from apps.accounts.models import Role

        Role.objects.get(name="mentor").permissions.clear()
        assert assignments.mentor_for(world["learner"], world["course"]) is None

    def test_one_row_per_learner_and_course(self, world):
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        assignments.assign_mentor(world["learner"], world["course"], world["mentor2"])
        assert MentorAssignment.objects.count() == 1
        assert MentorAssignment.objects.get().mentor == world["mentor2"]


class TestWhenAssignmentsChange:
    def test_unrated_work_follows_the_assignment_and_rated_work_is_left_alone(self, world):
        first = hand_in(world)  # pool
        rate(world, first, FAIL)
        second = hand_in(world, at(days=1))  # pool, unrated
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        first.refresh_from_db(), second.refresh_from_db()
        assert second.assigned_mentor == world["mentor"] and second.routing == "assignment"
        assert first.state == "rated" and first.assigned_mentor is None  # history untouched

    def test_unassigning_sends_unrated_work_back_to_the_pool(self, world):
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        sub = hand_in(world)
        assert assignments.unassign_mentor(world["learner"], world["course"]) is True
        sub.refresh_from_db()
        assert (sub.assigned_mentor, sub.routing) == (None, "pool")
        assert assignments.unassign_mentor(world["learner"], world["course"]) is False

    def test_a_claim_is_cleared_but_a_saved_draft_stays(self, world):
        sub = hand_in(world)
        services.save_draft(
            world["mentor2"], sub.pk, {"diagnosis": 4}, {}, "Half done", now=at(hours=1)
        )
        assert services._submission(sub.pk).claimed_by == world["mentor2"]
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        sub.refresh_from_db()
        assert sub.claimed_by is None and sub.assigned_mentor == world["mentor"]
        assert sub.draft["comment"] == "Half done" and sub.draft_by == world["mentor2"]

    def test_work_a_trainer_routed_by_hand_stays_put(self, world):
        sub = hand_in(world)
        services.reassign(world["trainer"], sub.pk, world["mentor2"])
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        sub.refresh_from_db()
        assert (sub.assigned_mentor, sub.routing) == (world["mentor2"], "admin")

    def test_other_learners_and_other_courses_are_not_touched(self, world, make_role_user):
        other_course = rated_course(make_role_user, title="Elsewhere")
        mine = hand_in(world)
        theirs = services.submit(world["other"], world["activity"].pk, ANSWER, now=at())
        elsewhere = services.submit(world["learner"], other_course["activity"].pk, ANSWER, now=at())
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        for sub in (theirs, elsewhere):
            sub.refresh_from_db()
            assert sub.routing == "pool"
        mine.refresh_from_db()
        assert mine.routing == "assignment"


# ---------------------------------------------------------------------- the case & clock


class TestOpeningAndTheDeadline:
    def test_the_deadline_starts_when_the_learner_first_opens_it(self, world):
        case = services.open_case(world["learner"], world["activity"].pk, now=at())
        assert case.due_at == at(days=7) and case.due_basis == "initial"
        again = services.open_case(world["learner"], world["activity"].pk, now=at(days=3))
        assert again.pk == case.pk and again.due_at == at(days=7)  # opening again never moves it
        assert SimCase.objects.count() == 1

    def test_no_deadline_when_the_author_sets_none(self, make_role_user):
        w = {**rated_course(make_role_user, config={"due_days": 0}), **people(make_role_user)}
        assert services.open_case(w["learner"], w["activity"].pk, now=at()).due_at is None

    def test_each_learner_has_their_own_clock(self, world):
        a = services.open_case(world["learner"], world["activity"].pk, now=at())
        b = services.open_case(world["other"], world["activity"].pk, now=at(days=2))
        assert (a.due_at, b.due_at) == (at(days=7), at(days=9))

    def test_it_must_be_a_simulation_that_exists(self, world):
        with pytest.raises(progress.NotFound):
            services.open_case(world["learner"], 999_999)
        reading = world["first"].activities.first()
        with pytest.raises(Conflict):
            services.open_case(world["learner"], reading.pk)


class TestSubmitting:
    def test_the_first_submission_is_revision_one_and_starts_the_mentors_clock(self, world):
        sub = hand_in(world, at(days=1))
        assert sub.revision == 1 and sub.previous is None and sub.state == "submitted"
        assert sub.review_due_at == at(days=1, hours=48)
        assert sub.due_snapshot == at(days=8) and sub.late is False  # opened by submitting

    def test_the_review_window_is_a_setting_with_a_per_activity_override(self, world, settings):
        settings.MANUAL_SIM_REVIEW_HOURS = 24
        assert hand_in(world).review_due_at == at(hours=24)
        services.withdraw(world["learner"], SimSubmission.objects.get().pk, now=at())
        world["activity"].config = {**world["activity"].config, "review_hours": 6}
        world["activity"].save()
        assert hand_in(world, at(hours=2)).review_due_at == at(hours=8)

    def test_late_work_is_accepted_and_marked_late_and_the_mentors_clock_is_separate(self, world):
        services.open_case(world["learner"], world["activity"].pk, now=at())
        sub = hand_in(world, at(days=9))  # two days after the deadline
        assert sub.late is True and sub.state == "submitted"
        assert sub.review_due_at == at(days=9, hours=48)  # not shortened by lateness

    def test_a_submission_on_the_deadline_is_not_late(self, world):
        services.open_case(world["learner"], world["activity"].pk, now=at())
        assert hand_in(world, at(days=7)).late is False

    def test_the_answer_is_required_and_bounded(self, world, settings):
        settings.MANUAL_SIM_MAX_ANSWER_CHARS = 20
        for bad in ("", "   ", None, 5):
            with pytest.raises(BadInput):
                hand_in(world, answer=bad)
        with pytest.raises(BadInput):
            hand_in(world, answer="x" * 21)
        assert SimSubmission.objects.count() == 0

    @pytest.mark.parametrize(
        "links",
        [
            ["javascript:alert(1)"],
            ["ftp://x.io/a"],
            ["http://"],
            ["https://a b.io"],
            ["//x.io"],
            [5],
            "https://x.io",
            ["https://x.io/" + "a" * 600],
        ],
    )
    def test_links_must_be_plain_http_or_https(self, world, links):
        with pytest.raises(BadInput):
            hand_in(world, links=links)

    def test_good_links_are_kept_and_the_count_is_capped(self, world, settings):
        settings.MANUAL_SIM_MAX_LINKS = 2
        sub = hand_in(world, links=["https://docs.hevodata.com/x", " http://a.io/b "])
        assert sub.links == ["https://docs.hevodata.com/x", "http://a.io/b"]
        services.withdraw(world["learner"], sub.pk, now=at())
        with pytest.raises(BadInput):
            hand_in(world, links=["https://a.io", "https://b.io", "https://c.io"])

    def test_only_one_piece_of_work_can_wait_at_a_time(self, world):
        hand_in(world)
        with pytest.raises(Conflict):
            hand_in(world, at(hours=1))
        assert SimSubmission.objects.count() == 1

    def test_the_activity_must_be_open_to_the_learner(self, make_role_user):
        w = {
            **rated_course(make_role_user, order="sequential", title="Ordered"),
            **people(make_role_user),
        }
        with pytest.raises(progress.LessonLocked):
            services.submit(w["learner"], w["activity"].pk, ANSWER, now=at())
        assert SimSubmission.objects.count() == 0

    def test_files_are_refused_when_the_activity_takes_none(self, make_role_user):
        w = {
            **rated_course(make_role_user, config={"allow_files": False}),
            **people(make_role_user),
        }
        with pytest.raises(BadInput):
            services.submit(w["learner"], w["activity"].pk, ANSWER, uploads=[png()], now=at())

    def test_files_are_stored_with_a_name_we_chose(self, world):
        sub = hand_in(world, uploads=[png("../../etc/passwd.png"), pdf("my notes.pdf"), jpeg()])
        names = [f.original_name for f in sub.files.all()]
        assert names == ["passwd.png", "my notes.pdf", "shot.jpg"]
        for f in sub.files.all():
            assert f.relative_path == f"attachments/{f.uuid}.{f.extension}"
            assert f.uuid and f.extension in {"png", "pdf", "jpg"}

    def test_a_bad_file_stops_everything_and_leaves_nothing(self, world):
        from django.core.files.uploadedfile import SimpleUploadedFile

        bad = SimpleUploadedFile(
            "fine.png", b"<html><script>alert(1)</script>", content_type="image/png"
        )
        with pytest.raises(BadInput):
            hand_in(world, uploads=[png(), bad])
        assert (
            SimSubmission.objects.count() == 0
            and SimCase.objects.filter(submissions__isnull=False).count() == 0
        )


# ------------------------------------------------------------------------ withdrawing


class TestWithdrawing:
    def test_a_learner_can_take_back_work_nobody_has_started_on(self, world):
        sub = hand_in(world)
        gone = services.withdraw(world["learner"], sub.pk, now=at(hours=1))
        assert gone.state == "withdrawn" and gone.withdrawn_by == "learner"
        assert ActivityAttempt.objects.count() == 0  # it cost nothing

    def test_it_does_not_move_the_deadline_and_numbering_continues(self, world):
        services.open_case(world["learner"], world["activity"].pk, now=at())
        first = hand_in(world, at(days=1))
        services.withdraw(world["learner"], first.pk, now=at(days=2))
        assert SimCase.objects.get().due_at == at(days=7)
        second = hand_in(world, at(days=3))
        assert second.revision == 2 and second.previous is None  # nothing was rated before it

    def test_not_once_a_mentor_has_started(self, world):
        sub = hand_in(world)
        services.claim(world["mentor"], sub.pk, now=at(hours=1))
        with pytest.raises(Conflict):
            services.withdraw(world["learner"], sub.pk, now=at(hours=1, minutes=5))

    def test_a_stale_claim_no_longer_blocks_it(self, world):
        sub = hand_in(world)
        services.claim(world["mentor"], sub.pk, now=at(hours=1))
        assert services.withdraw(world["learner"], sub.pk, now=at(hours=4)).state == "withdrawn"

    def test_not_after_it_was_rated_and_not_someone_elses(self, world):
        sub = hand_in(world)
        with pytest.raises(NotFound):
            services.withdraw(world["other"], sub.pk, now=at())
        rate(world, sub)
        with pytest.raises(Conflict):
            services.withdraw(world["learner"], sub.pk, now=at(hours=2))


# --------------------------------------------------------------------------- rating


class TestRating:
    def test_a_passing_rating_completes_the_activity(self, world):
        sub = hand_in(world)
        done = rate(world, sub, PASS)
        assert (done.state, done.passed, done.raw_score, done.scaled) == ("rated", True, 4.5, 0.9)
        assert done.rated_by == world["mentor"] and done.overall_comment == "Good work."
        row = ActivityProgress.objects.get(user=world["learner"], activity=world["activity"])
        assert row.state == "completed" and row.completed_at == at(hours=1)
        attempt = ActivityAttempt.objects.get()
        assert (attempt.score, attempt.passed, attempt.number) == (0.9, True, 1)
        assert done.attempt == attempt

    def test_each_criterion_is_recorded_with_its_label(self, world):
        sub = hand_in(world)
        services.rate(
            world["mentor"], sub.pk, PASS, {"tone": "Warm, but long."}, "Good.", now=at(hours=1)
        )
        rows = list(RubricScore.objects.filter(submission=sub))
        assert [(r.criterion_key, r.label, r.score, r.max_score) for r in rows] == [
            ("diagnosis", "Diagnosis", 5, 5),
            ("tone", "Tone", 4, 5),
        ]
        assert rows[1].feedback == "Warm, but long."

    def test_not_passing_asks_for_changes_and_starts_a_revision_window(self, world):
        services.open_case(world["learner"], world["activity"].pk, now=at())
        sub = hand_in(world, at(days=1))
        done = rate(world, sub, FAIL, now=at(days=2))
        assert done.passed is False and done.raw_score == 2.5
        case = SimCase.objects.get()
        assert case.due_at == at(days=5) and case.due_basis == "revision"
        assert ActivityProgress.objects.get().state == "started"  # not finished, not exhausted

    def test_a_minimum_per_criterion_can_fail_a_good_average(self, make_role_user):
        w = {**rated_course(make_role_user, config={"min_each": 3}), **people(make_role_user)}
        sub = services.submit(w["learner"], w["activity"].pk, ANSWER, now=at())
        done = services.rate(
            w["mentor"], sub.pk, {"diagnosis": 5, "tone": 2}, {}, "Hmm.", now=at(hours=1)
        )
        assert done.raw_score == 3.5 and done.passed is False

    def test_a_rating_is_final(self, world):
        sub = hand_in(world)
        rate(world, sub)
        with pytest.raises(Conflict):
            rate(world, sub, FAIL)
        sub.refresh_from_db()
        assert sub.passed is True and RubricScore.objects.filter(submission=sub).count() == 2

    def test_every_criterion_and_an_overall_comment_are_needed(self, world):
        sub = hand_in(world)
        for scores in (
            {"diagnosis": 5},
            {"diagnosis": 5, "tone": 0},
            {"diagnosis": 5, "tone": 4, "x": 1},
            {"diagnosis": 5, "tone": None},
        ):
            with pytest.raises(BadInput):
                services.rate(world["mentor"], sub.pk, scores, {}, "ok", now=at(hours=1))
        for comment in ("", "  ", None):
            with pytest.raises(BadInput):
                services.rate(world["mentor"], sub.pk, PASS, {}, comment, now=at(hours=1))
        assert RubricScore.objects.count() == 0 and ActivityAttempt.objects.count() == 0

    def test_the_legacy_attempt_limit_is_ignored(self, make_role_user):
        w = {**rated_course(make_role_user, max_attempts=3), **people(make_role_user)}
        for n in range(5):  # a fifth try would be refused if the old limit applied
            sub = services.submit(w["learner"], w["activity"].pk, ANSWER, now=at(days=n))
            services.rate(w["mentor"], sub.pk, FAIL, {}, "Again.", now=at(days=n, hours=1))
        assert ActivityAttempt.objects.count() == 5
        assert ActivityProgress.objects.get().state == "started"  # never "exhausted" by count


class TestRevisionsAndHistory:
    def test_revising_chains_the_revisions_and_keeps_every_one(self, world):
        first = hand_in(world, uploads=[png()])
        rate(world, first, FAIL, now=at(hours=1))
        second = hand_in(world, at(days=1), answer="Second try.")
        rate(world, second, FAIL, now=at(days=1, hours=1))
        third = hand_in(world, at(days=2), answer="Third try.")
        assert [s.revision for s in SimSubmission.objects.order_by("revision")] == [1, 2, 3]
        assert (second.previous, third.previous) == (first, second)
        first.refresh_from_db()
        assert first.answer == ANSWER and first.files.count() == 1  # nothing earlier was rewritten
        assert RubricScore.objects.filter(submission=first).count() == 2

    def test_nothing_can_be_handed_in_before_a_rating_asks_for_changes(self, world):
        sub = hand_in(world)
        services.withdraw(world["learner"], sub.pk, now=at())
        with_rating = hand_in(world, at(hours=2))
        rate(world, with_rating, FAIL)
        assert hand_in(world, at(days=1)).revision == 3  # allowed: changes were requested

    def test_after_a_pass_nothing_more_can_be_handed_in(self, world):
        rate(world, hand_in(world), PASS)
        with pytest.raises(Conflict):
            hand_in(world, at(days=1))

    def test_a_learner_never_sees_another_learners_work(self, world):
        mine = hand_in(world)
        theirs = services.submit(world["other"], world["activity"].pk, "Other's answer.", now=at())
        assert mine.case != theirs.case
        with pytest.raises(NotFound):
            services.withdraw(world["learner"], theirs.pk, now=at())

    def test_three_unsuccessful_reviews_flag_it_for_attention(self, world):
        summaries = []
        for n in range(3):
            sub = hand_in(world, at(days=n))
            rate(world, sub, FAIL, now=at(days=n, hours=1))
            case = SimCase.objects.get()
            summaries.append(services.case_summary(case, now=at(days=n, hours=2)))
        assert [s["needs_attention"] for s in summaries] == [False, False, True]
        assert summaries[2]["status"] == "changes_requested" and summaries[2]["unsuccessful"] == 3

    def test_a_pass_clears_the_flag(self, world):
        for n in range(3):
            rate(world, hand_in(world, at(days=n)), FAIL, now=at(days=n, hours=1))
        rate(world, hand_in(world, at(days=4)), PASS, now=at(days=4, hours=1))
        summary = services.case_summary(SimCase.objects.get(), now=at(days=5))
        assert summary["status"] == "passed" and summary["needs_attention"] is False


# ---------------------------------------------------------------- who may do what


class TestWhoMayRate:
    def test_a_learner_without_the_permission_cannot_rate(self, world):
        sub = hand_in(world)
        with pytest.raises(Forbidden):
            services.rate(world["other"], sub.pk, PASS, {}, "x", now=at(hours=1))

    def test_nobody_rates_their_own_work_whatever_their_role(self, world):
        sub = services.submit(world["mentor"], world["activity"].pk, ANSWER, now=at())
        with pytest.raises(Forbidden):
            services.rate(world["mentor"], sub.pk, PASS, {}, "Mine.", now=at(hours=1))
        own_trainer = services.submit(world["trainer"], world["activity"].pk, ANSWER, now=at())
        with pytest.raises(Forbidden):
            services.rate(world["trainer"], own_trainer.pk, PASS, {}, "Mine.", now=at(hours=1))
        assert access.rating_access(world["root"], sub, at(hours=1)).allowed  # others still may

    def test_the_assigned_mentor_rates_and_another_mentor_cannot_until_it_is_escalated(self, world):
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        sub = hand_in(world)
        with pytest.raises(Forbidden):
            services.claim(world["mentor2"], sub.pk, now=at(hours=1))
        late = sub.review_due_at + timedelta(hours=23)
        with pytest.raises(Forbidden):
            services.claim(world["mentor2"], sub.pk, now=late)  # overdue, still inside the grace
        past_grace = sub.review_due_at + timedelta(hours=25)
        assert (
            services.claim(world["mentor2"], sub.pk, now=past_grace).claimed_by == world["mentor2"]
        )
        assert access.escalated(sub, past_grace) and not access.escalated(sub, late)

    def test_the_assigned_mentor_needs_no_claim(self, world):
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        sub = hand_in(world)
        assert rate(world, sub).state == "rated"

    def test_any_rater_can_take_a_pool_item_and_a_claim_is_a_lease(self, world):
        sub = hand_in(world)
        services.claim(world["mentor"], sub.pk, now=at(hours=1))
        with pytest.raises(Conflict):
            services.claim(world["mentor2"], sub.pk, now=at(hours=1, minutes=30))
        with pytest.raises(Conflict):
            services.rate(world["mentor2"], sub.pk, PASS, {}, "x", now=at(hours=1, minutes=30))
        # after the two-hour lease anyone may take it
        assert (
            services.claim(world["mentor2"], sub.pk, now=at(hours=3, minutes=1)).claimed_by
            == world["mentor2"]
        )

    def test_releasing_gives_it_back_and_only_the_holder_or_a_manager_may(self, world):
        sub = hand_in(world)
        services.claim(world["mentor"], sub.pk, now=at(hours=1))
        with pytest.raises(Forbidden):
            services.release(world["mentor2"], sub.pk, now=at(hours=1, minutes=5))
        services.release(world["mentor"], sub.pk, now=at(hours=1, minutes=5))
        assert (
            services.claim(world["mentor2"], sub.pk, now=at(hours=1, minutes=6)).claimed_by
            == world["mentor2"]
        )
        assert (
            services.release(world["trainer"], sub.pk, now=at(hours=1, minutes=7)).claimed_by
            is None
        )

    def test_a_trainer_can_take_over_a_claim_and_rate_any_submission(self, world):
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        sub = hand_in(world)
        services.claim(world["trainer"], sub.pk, now=at(hours=1))
        assert rate(world, sub, by="trainer").rated_by == world["trainer"]

    def test_a_draft_is_kept_until_rated_and_belongs_to_whoever_wrote_it(self, world):
        sub = hand_in(world)
        services.save_draft(
            world["mentor"], sub.pk, {"diagnosis": 4}, {"tone": "Maybe"}, "Draft", now=at(hours=1)
        )
        sub.refresh_from_db()
        assert sub.draft == {
            "scores": {"diagnosis": 4, "tone": None},
            "feedback": {"tone": "Maybe"},
            "comment": "Draft",
        }
        assert sub.draft_by == world["mentor"]
        rate(world, sub)
        sub.refresh_from_db()
        assert sub.draft == {} and sub.draft_by is None

    def test_a_draft_may_be_incomplete_but_not_nonsense(self, world):
        sub = hand_in(world)
        services.save_draft(world["mentor"], sub.pk, None, None, None, now=at(hours=1))
        with pytest.raises(BadInput):
            services.save_draft(world["mentor"], sub.pk, {"nope": 3}, None, None, now=at(hours=1))
        with pytest.raises(BadInput):
            services.save_draft(world["mentor"], sub.pk, {"tone": 9}, None, None, now=at(hours=1))


class TestTrainerAndAdminActions:
    def test_reassigning_one_submission_names_a_mentor_or_the_pool(self, world):
        sub = hand_in(world)
        moved = services.reassign(world["trainer"], sub.pk, world["mentor2"])
        assert (moved.assigned_mentor, moved.routing) == (world["mentor2"], "admin")
        back = services.reassign(world["root"], sub.pk, None)
        assert (back.assigned_mentor, back.routing) == (None, "admin")  # explicitly the pool
        assert access.in_pool(back, at())

    def test_only_a_manager_can_reassign_and_only_to_someone_who_may_rate(self, world):
        sub = hand_in(world)
        with pytest.raises(Forbidden):
            services.reassign(world["mentor"], sub.pk, world["mentor2"])
        with pytest.raises(BadInput):
            services.reassign(world["trainer"], sub.pk, world["other"])  # a learner
        with pytest.raises(BadInput):
            services.reassign(world["trainer"], sub.pk, world["learner"])  # the author themselves

    def test_extending_counts_from_now_or_the_deadline_if_later(self, world):
        case = services.open_case(world["learner"], world["activity"].pk, now=at())
        extended = services.extend(world["trainer"], case.pk, 5, "Was ill", now=at(days=2))
        assert extended.due_at == at(days=12) and extended.due_basis == "extended"
        again = services.extend(world["trainer"], case.pk, 2, "More", now=at(days=20))
        assert again.due_at == at(days=22)  # already past: counted from now

    def test_extending_is_bounded_needs_a_reason_and_is_not_for_mentors(self, world, settings):
        case = services.open_case(world["learner"], world["activity"].pk, now=at())
        for days in (0, -1, 15, "3", True, None):
            with pytest.raises(BadInput):
                services.extend(world["trainer"], case.pk, days, "why", now=at())
        for reason in ("", "  ", None):
            with pytest.raises(BadInput):
                services.extend(world["trainer"], case.pk, 3, reason, now=at())
        with pytest.raises(Forbidden):
            services.extend(world["mentor"], case.pk, 3, "why", now=at())
        settings.MANUAL_SIM_EXTEND_MAX_DAYS = 30
        assert services.extend(world["trainer"], case.pk, 30, "Long leave", now=at()).due_at

    @pytest.mark.parametrize("act", ["waive", "close", "reopen"])
    def test_waiving_closing_and_reopening_are_not_for_mentors_and_need_a_reason(self, world, act):
        case = services.open_case(world["learner"], world["activity"].pk, now=at())
        fn = getattr(services, act)
        with pytest.raises(Forbidden):
            fn(world["mentor"], case.pk, "why", now=at())
        with pytest.raises(BadInput):
            fn(world["trainer"], case.pk, "", now=at())

    def test_closing_ends_the_case_and_withdraws_what_was_waiting(self, world):
        sub = hand_in(world)
        case = SimCase.objects.get()
        closed = services.close(world["trainer"], case.pk, "Left the company", now=at(days=1))
        assert closed.closed_reason == "not_passed" and closed.closed_by == world["trainer"]
        sub.refresh_from_db()
        assert sub.state == "withdrawn" and sub.withdrawn_by == "closed"
        assert ActivityProgress.objects.get().state == "exhausted"  # "finished, not passed"
        with pytest.raises(Conflict):
            hand_in(world, at(days=2))
        with pytest.raises(Conflict):
            rate(world, sub, now=at(days=2))  # the rating can no longer arrive
        assert services.case_summary(closed, now=at(days=2))["status"] == "not_passed"

    def test_waived_is_recorded_as_waived_and_never_as_passed(self, world):
        case = services.open_case(world["learner"], world["activity"].pk, now=at())
        waived = services.waive(world["root"], case.pk, "Equivalent course done", now=at(days=1))
        summary = services.case_summary(waived, now=at(days=2))
        assert summary["status"] == "waived" and summary["overdue"] is False
        assert ActivityProgress.objects.get().state == "exhausted"
        assert ActivityProgress.objects.filter(state="completed").count() == 0
        with pytest.raises(Conflict):
            services.waive(world["root"], case.pk, "again", now=at(days=3))

    def test_a_passed_case_cannot_be_waived_closed_or_extended(self, world):
        rate(world, hand_in(world))
        case = SimCase.objects.get()
        for fn in (services.waive, services.close):
            with pytest.raises(Conflict):
                fn(world["trainer"], case.pk, "x", now=at(days=1))
        with pytest.raises(Conflict):
            services.extend(world["trainer"], case.pk, 3, "x", now=at(days=1))

    def test_reopening_gives_a_fresh_deadline_and_lets_the_learner_continue(self, world):
        sub = hand_in(world)
        rate(world, sub, FAIL)
        case = SimCase.objects.get()
        services.close(world["trainer"], case.pk, "Mistake", now=at(days=5))
        reopened = services.reopen(world["trainer"], case.pk, "It was a mistake", now=at(days=6))
        assert (
            reopened.closed_at is None
            and reopened.due_at == at(days=9)
            and reopened.due_basis == "extended"
        )
        assert ActivityProgress.objects.get().state == "started"
        assert hand_in(world, at(days=6)).revision == 2
        with pytest.raises(Conflict):
            services.reopen(world["trainer"], case.pk, "again", now=at(days=7))
