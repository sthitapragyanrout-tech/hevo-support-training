"""Who is told what, and when: each change raises exactly the right notices for exactly the right
people, and never more than once. The wording is checked lightly (what matters is who, the link,
and that nothing private rides along)."""

import pytest

from apps.catalog.models import ContentNode
from apps.enrollment import migration, modules
from apps.enrollment import services as enrollment
from apps.enrollment.errors import Conflict as EnrollmentConflict
from apps.manual_sim import assignments, quiz_reviews
from apps.manual_sim import services as sims
from apps.manual_sim.errors import BadInput
from apps.manual_sim.models import QuizReview, SimSubmission
from apps.notifications.models import Notification
from apps.progress import services as progress
from tests.enrollment_helpers import course_with, publish_next
from tests.manual_sim_helpers import FAIL, PASS, at, people, rated_course
from tests.written_quiz_helpers import ALL_RIGHT, cast, written_course

pytestmark = pytest.mark.django_db


def told(user, kind=None):
    rows = Notification.objects.filter(user=user)
    return list(rows.filter(kind=kind) if kind else rows)


def titles(user):
    return [n.title for n in told(user)]


# -------------------------------------------------------------------------- enrollment


@pytest.mark.real_enrollment
class TestEnrollment:
    @pytest.fixture
    def world(self, make_role_user):
        w = course_with(make_role_user)
        w.update(people(make_role_user))
        return w

    def test_enrolling_tells_the_learner_and_links_to_the_course(self, world):
        enrollment.enroll(world["learner"], world["course"])
        (n,) = told(world["learner"])
        assert n.kind == "enrolled" and n.title == "You’re enrolled on Course"
        assert n.link == f"/courses/{world['course'].pk}" and n.read_at is None

    def test_nobody_else_is_told(self, world):
        enrollment.enroll(world["learner"], world["course"], mentor=world["mentor"])
        assert Notification.objects.exclude(user=world["learner"]).count() == 0

    def test_enrolling_someone_already_on_it_says_nothing_more(self, world):
        enrollment.enroll(world["learner"], world["course"])
        enrollment.enroll(world["learner"], world["course"])
        assert len(told(world["learner"])) == 1

    def test_an_enrollment_that_already_existed_without_a_notice_is_not_announced_late(self, world):
        # e.g. one from the backfill: it was never "enrolled" in front of anyone, and saying so now
        # (on a later no-op enroll) would be a message about nothing that just happened.
        from tests.enrollment_helpers import pin

        pin(world["learner"], world["version"])
        enrollment.enroll(world["learner"], world["course"])
        assert told(world["learner"]) == []

    def test_enrolling_again_after_leaving_is_a_new_message(self, world):
        row, _ = enrollment.enroll(world["learner"], world["course"])
        enrollment.withdraw(row, "left")
        enrollment.enroll(world["learner"], world["course"])
        assert titles(world["learner"]) == [
            "You’re enrolled on Course again",
            "You’re enrolled on Course",
        ]

    def test_a_program_gives_one_notice_per_course(self, world, make_role_user):
        other = course_with(make_role_user, title="Second")
        program = enrollment.save_program(
            None, name="P", courses=[(world["course"].pk, True), (other["course"].pk, True)]
        )
        enrollment.enroll_program(world["learner"], program)
        assert sorted(titles(world["learner"])) == [
            "You’re enrolled on Course",
            "You’re enrolled on Second",
        ]

    def test_a_failed_enrollment_tells_nobody(self, world):
        world["learner"].is_active = False
        world["learner"].save()
        with pytest.raises(enrollment.EnrollmentError):
            enrollment.enroll(world["learner"], world["course"])
        assert Notification.objects.count() == 0

    def test_a_preview_of_a_move_tells_nobody_but_the_move_itself_does(self, world):
        row, _ = enrollment.enroll(world["learner"], world["course"])
        Notification.objects.all().delete()
        v2 = publish_next(world)
        migration.preview(row)
        assert Notification.objects.count() == 0
        migration.apply(row, to_version_id=v2.pk)
        (n,) = told(world["learner"])
        assert n.kind == "course_updated" and n.title == "Course has been updated"
        assert "version 2" in n.body and n.link == f"/courses/{world['course'].pk}"

    def test_a_refused_move_tells_nobody(self, world):
        row, _ = enrollment.enroll(world["learner"], world["course"])
        Notification.objects.all().delete()
        with pytest.raises(EnrollmentConflict, match="already on the newest version"):
            migration.apply(row, to_version_id=world["version"].pk)
        assert Notification.objects.count() == 0

    def three_modules(self, world):
        version = world["version"]
        extra = [
            ContentNode.objects.create(
                course_version=version,
                parent=version.root_node,
                kind=ContentNode.Kind.SEGMENT,
                title=f"M{i}",
                slug=f"m{i}",
                order=10 + i,
            )
            for i in range(2)
        ]
        return [world["module"], *extra]

    def test_changing_a_learners_modules_tells_them_how_many_they_have(self, world):
        mods = self.three_modules(world)
        row, _ = enrollment.enroll(world["learner"], world["course"])
        Notification.objects.all().delete()
        modules.set_modules(row, [mods[0].pk, mods[1].pk])
        (n,) = told(world["learner"])
        assert n.kind == "modules_changed" and "2 of 3 modules" in n.body

    def test_saving_the_same_modules_again_says_nothing(self, world):
        mods = self.three_modules(world)
        row, _ = enrollment.enroll(world["learner"], world["course"])
        Notification.objects.all().delete()
        modules.set_modules(row, [m.pk for m in mods])  # everything was already on
        assert Notification.objects.count() == 0


# ------------------------------------------------------------------------ written quiz


class TestWrittenQuiz:
    @pytest.fixture
    def world(self, make_role_user):
        w = written_course(make_role_user)
        w.update(cast(make_role_user))
        return w

    def submit(self, world):
        progress.submit_attempt(world["learner"], world["quiz"].pk, ALL_RIGHT)
        return QuizReview.objects.get(user=world["learner"])

    def test_work_in_the_pool_tells_every_rater_but_not_the_learner(self, world):
        review = self.submit(world)
        for who in ("mentor", "mentor2", "trainer", "root"):
            (n,) = told(world[who], "work_waiting")
            assert n.link == f"/admin/ratings/quiz/{review.pk}"
            assert "Lea" in n.body or "lea@e.com" in n.body  # a marker may see who
        assert told(world["learner"]) == [] and told(world["other"]) == []

    def test_work_routed_to_a_mentor_tells_only_that_mentor(self, world):
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        self.submit(world)
        assert len(told(world["mentor"], "work_waiting")) == 1
        for who in ("mentor2", "trainer", "root"):
            assert told(world[who]) == []

    def test_a_trainer_who_is_also_a_learner_is_not_told_about_their_own_work(self, world):
        progress.submit_attempt(world["trainer"], world["quiz"].pk, ALL_RIGHT)
        assert told(world["trainer"]) == []
        assert len(told(world["root"], "work_waiting")) == 1

    def test_marking_tells_the_learner_the_result_and_clears_the_waiting_notices(self, world):
        review = self.submit(world)
        quiz_reviews.rate(world["mentor"], review.pk, {2: 3})
        (n,) = told(world["learner"], "quiz_marked")
        assert "marked" in n.title and "passed (83%)" in n.body
        assert n.link == f"/courses/{world['course'].pk}/lessons/{world['one'].pk}"
        for who in ("mentor", "mentor2", "trainer", "root"):
            (waiting,) = told(world[who], "work_waiting")
            assert waiting.read_at is not None  # no longer waiting: cleared

    def test_a_fail_says_not_passed(self, world):
        review = self.submit(world)
        quiz_reviews.rate(world["mentor"], review.pk, {2: 0})
        (n,) = told(world["learner"], "quiz_marked")
        assert "not passed" in n.body

    def test_nothing_private_rides_along_with_the_learners_notice(self, world):
        review = self.submit(world)
        quiz_reviews.rate(world["mentor"], review.pk, {2: 3}, {2: "PRIVATE-NOTE?"}, "Well done")
        text = " ".join(f"{n.title} {n.body}" for n in told(world["learner"]))
        for secret in ("Re-authorise the source, then resync", "token expired", "mia", "Mentor"):
            assert secret not in text

    def test_reassigning_moves_the_notice_to_the_new_owner(self, world):
        review = self.submit(world)
        quiz_reviews.reassign(world["trainer"], review.pk, world["mentor2"])
        assert told(world["mentor"])[0].read_at is not None  # cleared for the pool
        fresh = [n for n in told(world["mentor2"]) if n.read_at is None]
        assert len(fresh) == 1 and fresh[0].kind == "work_waiting"
        # ...and sending it back to them later is not swallowed as a repeat.
        quiz_reviews.reassign(world["trainer"], review.pk, world["mentor"])
        assert len([n for n in told(world["mentor"]) if n.read_at is None]) == 1

    def test_a_failing_notification_never_stops_the_marking(self, world, monkeypatch):
        review = self.submit(world)

        def boom(*args, **kwargs):
            raise RuntimeError("no")

        monkeypatch.setattr(Notification.objects, "create", boom)
        monkeypatch.setattr(Notification.objects, "get_or_create", boom)
        done = quiz_reviews.rate(world["mentor"], review.pk, {2: 3})
        assert done.state == QuizReview.State.RATED


# ----------------------------------------------------------------------- simulations


class TestSimulations:
    ANSWER = "The pipeline stopped because the source password expired; rotate it and resume."

    @pytest.fixture
    def world(self, make_role_user):
        return {**rated_course(make_role_user), **people(make_role_user)}

    def hand_in(self, world, now=None):
        return sims.submit(world["learner"], world["activity"].pk, self.ANSWER, now=now or at())

    def rate(self, world, sub, scores=PASS):
        return sims.rate(world["mentor"], sub.pk, scores, {}, "Good work.", now=at(hours=1))

    def test_a_hand_in_in_the_pool_tells_the_raters_with_the_learners_name(self, world):
        sub = self.hand_in(world)
        for who in ("mentor", "mentor2", "trainer", "root"):
            (n,) = told(world[who], "work_waiting")
            assert n.link == f"/admin/ratings/{sub.pk}"
            assert "revision 1" in n.body and "Review due" in n.body
        assert told(world["learner"]) == []

    def test_a_hand_in_routed_to_a_mentor_tells_only_them(self, world):
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        self.hand_in(world)
        assert len(told(world["mentor"], "work_waiting")) == 1
        assert all(told(world[w]) == [] for w in ("mentor2", "trainer", "root"))

    def test_a_pass_tells_the_learner_and_clears_the_waiting_notices(self, world):
        sub = self.hand_in(world)
        self.rate(world, sub)
        (n,) = told(world["learner"], "sim_rated")
        assert n.title == "Your work on “Customer reply” passed"
        assert all(told(world[w])[0].read_at is not None for w in ("mentor", "mentor2", "trainer"))

    def test_changes_requested_says_to_revise_by_the_new_date(self, world):
        sub = self.hand_in(world)
        self.rate(world, sub, FAIL)
        (n,) = told(world["learner"], "sim_rated")
        assert n.title == "Changes requested on “Customer reply”"
        case = sub.case
        case.refresh_from_db()
        assert f"by {case.due_at.day} " in n.body

    def test_nobody_but_the_learner_gets_the_learners_notice_and_it_names_no_one(self, world):
        sub = self.hand_in(world)
        self.rate(world, sub)
        text = " ".join(f"{n.title} {n.body}" for n in told(world["learner"], "sim_rated"))
        assert "mia" not in text.lower() and "Mentor" not in text
        assert told(world["other"]) == []

    def test_taking_it_back_clears_the_waiting_notices(self, world):
        sub = self.hand_in(world)
        sims.withdraw(world["learner"], sub.pk)
        assert all(n.read_at is not None for w in ("mentor", "trainer") for n in told(world[w]))

    def test_closing_the_case_clears_them_too(self, world):
        sub = self.hand_in(world)
        sims.close(world["trainer"], sub.case.pk, "No longer needed")
        assert all(n.read_at is not None for w in ("mentor", "mentor2") for n in told(world[w]))

    def test_reassigning_tells_the_new_owner(self, world):
        sub = self.hand_in(world)
        sims.reassign(world["trainer"], sub.pk, world["mentor2"])
        assert len([n for n in told(world["mentor2"]) if n.read_at is None]) == 1
        assert told(world["mentor"])[0].read_at is not None

    def test_assigning_a_mentor_tells_them_their_waiting_work_moved_to_them(self, world):
        self.hand_in(world)  # waiting in the pool
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        moved = told(world["mentor"], "work_assigned")
        assert [n.title for n in moved] == ["1 review moved to you"]
        assert moved[0].link == "/admin/ratings"

    def test_assigning_a_mentor_with_no_waiting_work_says_nothing(self, world):
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        assert told(world["mentor"], "work_assigned") == []

    def test_a_revision_is_new_work_and_is_announced_again(self, world):
        sub = self.hand_in(world)
        self.rate(world, sub, FAIL)
        sims.submit(world["learner"], world["activity"].pk, self.ANSWER + " More.", now=at(days=1))
        assert len(told(world["mentor"], "work_waiting")) == 2
        second = SimSubmission.objects.get(revision=2)
        assert told(world["mentor"])[0].link == f"/admin/ratings/{second.pk}"

    def test_a_failing_notification_never_stops_a_hand_in_or_a_rating(self, world, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("no")

        monkeypatch.setattr(Notification.objects, "create", boom)
        monkeypatch.setattr(Notification.objects, "get_or_create", boom)
        sub = self.hand_in(world)
        assert self.rate(world, sub).state == SimSubmission.State.RATED
        assert Notification.objects.count() == 0


def test_nothing_is_told_for_a_hand_in_that_fails(make_role_user):
    world = {**rated_course(make_role_user), **people(make_role_user)}
    with pytest.raises(BadInput):
        sims.submit(world["learner"], world["activity"].pk, "", now=at())  # an empty answer
    assert Notification.objects.count() == 0
