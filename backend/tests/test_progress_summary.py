"""The learner's own progress report (`GET /progress/summary/`): facts about *their* courses only,
the same numbers as the course page, nothing another person or a rater may see."""

import json

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.catalog import services as catalog
from apps.catalog.models import Activity
from apps.enrollment import modules
from apps.enrollment import services as enrollment
from apps.enrollment.models import ModuleExclusion
from apps.manual_sim import quiz_reviews
from apps.manual_sim.models import SimCase, SimSubmission
from apps.progress import services as progress
from apps.progress import summary
from apps.progress.models import ActivityAttempt, ActivityProgress
from tests.manual_sim_helpers import good_config
from tests.sim_helpers import approved_scenarios, make_session
from tests.written_quiz_helpers import ALL_RIGHT, CONFIG, cast

pytestmark = pytest.mark.django_db

PLAIN_QUIZ = {
    "questions": [{"text": "Pick", "choices": ["A", "B"], "answer": 0}],
    "pass_threshold": 0.5,
}


def build(make_role_user, *, title="Course", order="free", max_attempts=2):
    """Module One: lesson Intro (a reading, a plain quiz, a written quiz) and lesson Tickets (a
    practice ticket, a mentor-rated simulation). Module Two: lesson Extra (a reading)."""
    author = make_role_user(Role.Name.TRAINER, username=f"a-{title}", email=f"a-{title}@e.com")
    admin = make_role_user(Role.Name.ADMIN, username=f"adm-{title}", email=f"adm-{title}@e.com")
    course = catalog.create_course(title=title, user=author)
    v = catalog.open_version(course)
    one = catalog.add_node(v.root_node, title="Module One")
    two = catalog.add_node(v.root_node, title="Module Two")
    intro = catalog.add_node(one, title="Intro")
    tickets = catalog.add_node(one, title="Tickets")
    extra = catalog.add_node(two, title="Extra")
    reading = Activity.objects.create(
        content_node=intro,
        activity_type="reading",
        title="Read me",
        config={"source_url": "https://x.io"},
    )
    plain = Activity.objects.create(
        content_node=intro,
        activity_type="mcq",
        title="Plain quiz",
        config=PLAIN_QUIZ,
        max_attempts=max_attempts,
    )
    mixed = Activity.objects.create(
        content_node=intro,
        activity_type="mcq",
        title="Mixed quiz",
        config=CONFIG,
        max_attempts=max_attempts,
    )
    ticket = Activity.objects.create(
        content_node=tickets,
        activity_type="bot_sim",
        title="Practice ticket",
        config={"persona": "random", "topics": [], "pass_threshold": 0.7, "max_exchanges": 6},
        max_attempts=0,
    )
    sim = Activity.objects.create(
        content_node=tickets,
        activity_type="manual_sim",
        title="Customer reply",
        config=good_config(),
        max_attempts=0,
    )
    later = Activity.objects.create(
        content_node=extra,
        activity_type="reading",
        title="Later",
        config={"source_url": "https://y.io"},
    )
    catalog.set_learning_order(v, order)
    v.publish(admin)
    return {
        "course": course,
        "version": v,
        "one": one,
        "two": two,
        "intro": intro,
        "tickets": tickets,
        "extra": extra,
        "reading": reading,
        "plain": plain,
        "mixed": mixed,
        "ticket": ticket,
        "sim": sim,
        "later": later,
        "admin": admin,
    }


@pytest.fixture
def world(make_role_user):
    w = build(make_role_user)
    w.update(cast(make_role_user))
    approved_scenarios(3)
    enrollment.enroll(w["learner"], w["course"])
    return w


def mine(world, who="learner"):
    return summary.learner_summary(world[who])["courses"]


def row(world, who="learner"):
    (course,) = mine(world, who)
    return course


def quiz(course, title):
    return next(q for q in course["quizzes"] if q["title"] == title)


class TestWhichCourses:
    def test_nothing_for_a_learner_with_no_enrollment(self, world):
        assert mine(world, "other") == []

    def test_only_the_enrolled_course_with_its_title(self, world):
        course = row(world)
        assert course["title"] == "Course"
        assert (course["course_id"], course["version_id"]) == (
            world["course"].pk,
            world["version"].pk,
        )

    def test_a_withdrawn_course_drops_off_and_comes_back_on_re_enrolling(self, world):
        (enrolled,) = world["learner"].enrollments.all()
        enrollment.withdraw(enrolled, "left")
        assert mine(world) == []
        enrollment.enroll(world["learner"], world["course"])
        assert len(mine(world)) == 1

    def test_an_archived_course_is_not_listed(self, world):
        catalog.archive_course(world["course"])
        assert mine(world) == []

    def test_the_newest_enrollment_comes_first(self, make_role_user, world):
        other = build(make_role_user, title="Second")
        enrollment.enroll(world["learner"], other["course"])
        assert [c["title"] for c in mine(world)] == ["Second", "Course"]

    def test_an_author_who_is_not_enrolled_gets_no_courses(self, world):
        # Authors may open published courses, but this is a report of *their own enrollments*.
        assert mine(world, "trainer") == []

    def test_other_learners_do_not_see_each_others_progress(self, world):
        progress.complete_activity(world["learner"], world["reading"].pk)
        enrollment.enroll(world["other"], world["course"])
        theirs = row(world, "other")
        assert theirs["lessons_done"] == 0 and theirs["quizzes"][0]["status"] == "not_started"


class TestLessons:
    def test_totals_done_awaiting_and_whats_next(self, make_role_user):
        w = build(make_role_user, title="Seq", order="sequential")
        w.update(cast(make_role_user))
        enrollment.enroll(w["learner"], w["course"])
        course = row(w)
        assert (course["lessons_total"], course["lessons_done"]) == (3, 0)
        assert course["next_lesson"] == {"id": w["intro"].pk, "title": "Intro"}
        assert course["lessons_awaiting_review"] == 0

    def test_a_lesson_awaiting_marks_is_counted_apart_from_done(self, make_role_user):
        w = build(make_role_user, title="Seq2", order="sequential")
        w.update(cast(make_role_user))
        enrollment.enroll(w["learner"], w["course"])
        progress.complete_activity(w["learner"], w["reading"].pk)
        progress.submit_attempt(w["learner"], w["plain"].pk, [[0]])
        progress.submit_attempt(w["learner"], w["mixed"].pk, ALL_RIGHT)
        progress.complete_lesson(w["learner"], w["intro"].pk)
        course = row(w)
        assert course["lessons_done"] == 0 and course["lessons_awaiting_review"] == 1
        assert course["next_lesson"]["title"] == "Tickets"  # the next lesson is open

    def test_it_agrees_with_the_course_page_for_the_same_learner(self, world):
        progress.complete_activity(world["learner"], world["reading"].pk)
        progress.submit_attempt(world["learner"], world["plain"].pk, [[0]])
        payload = progress.course_progress(world["learner"], world["version"].pk)
        course = row(world)
        assert course["lessons_done"] == len(payload["completed_lessons"])
        assert course["next_lesson"]["id"] == payload["next_lesson_id"]

    def test_a_module_switched_off_is_left_out_of_everything(self, world):
        ModuleExclusion.objects.create(
            enrollment=world["learner"].enrollments.get(), node=world["two"]
        )
        course = row(world)
        assert course["lessons_total"] == 2
        ModuleExclusion.objects.all().delete()
        modules.set_modules(
            world["learner"].enrollments.get(), [world["two"].pk]
        )  # now Module One is off
        course = row(world)
        assert course["lessons_total"] == 1
        assert course["quizzes"] == [] and course["practice"] == [] and course["rated"] == []


class TestQuizzes:
    def test_every_quiz_with_where_it_stands(self, world):
        course = row(world)
        assert [q["title"] for q in course["quizzes"]] == ["Plain quiz", "Mixed quiz"]
        plain = quiz(course, "Plain quiz")
        assert plain == {
            "activity_id": world["plain"].pk,
            "lesson_id": world["intro"].pk,
            "lesson_title": "Intro",
            "title": "Plain quiz",
            "status": "not_started",
            "attempts_used": 0,
            "max_attempts": 2,
            "best": None,
            "latest": None,
            "required": True,
        }

    def test_a_failed_then_passed_quiz(self, world):
        progress.submit_attempt(world["learner"], world["plain"].pk, [[1]])
        failed = quiz(row(world), "Plain quiz")
        assert failed["status"] == "in_progress" and failed["attempts_used"] == 1
        assert failed["best"] == 0.0 and failed["latest"] == 0.0
        progress.submit_attempt(world["learner"], world["plain"].pk, [[0]])
        passed = quiz(row(world), "Plain quiz")
        assert passed["status"] == "passed" and passed["attempts_used"] == 2
        assert (passed["best"], passed["latest"]) == (1.0, 1.0)

    def test_out_of_tries_is_not_passed(self, world):
        progress.submit_attempt(world["learner"], world["plain"].pk, [[1]])
        progress.submit_attempt(world["learner"], world["plain"].pk, [[1]])
        assert quiz(row(world), "Plain quiz")["status"] == "not_passed"

    def test_a_written_attempt_waiting_for_marks_is_a_try_taken_with_no_score(self, world):
        progress.submit_attempt(world["learner"], world["mixed"].pk, ALL_RIGHT)
        waiting = quiz(row(world), "Mixed quiz")
        assert waiting["status"] == "awaiting_review"
        assert waiting["attempts_used"] == 1
        assert waiting["best"] is None and waiting["latest"] is None

    def test_once_marked_it_has_a_score(self, world):
        progress.submit_attempt(world["learner"], world["mixed"].pk, ALL_RIGHT)
        review = world["learner"].quiz_reviews.get()
        quiz_reviews.rate(world["mentor"], review.pk, {2: 3})
        done = quiz(row(world), "Mixed quiz")
        assert done["status"] == "passed" and done["attempts_used"] == 1
        assert done["best"] == pytest.approx(5 / 6)

    def test_the_answer_key_and_reference_answers_never_appear(self, world):
        progress.submit_attempt(world["learner"], world["mixed"].pk, ALL_RIGHT)
        raw = json.dumps(summary.learner_summary(world["learner"]))
        for secret in (
            "Re-authorise the source, then resync",
            "key_points",
            "token expired",
            "answer",
        ):
            assert secret not in raw


class TestPractice:
    def finished(self, world, scores):
        session = make_session(world["learner"], world["ticket"], state="finished")
        for i, score in enumerate(scores, start=1):
            ActivityAttempt.objects.create(
                user=world["learner"],
                activity=world["ticket"],
                number=i,
                answers={},
                details=[],
                score=score,
                passed=score >= 0.7,
                submitted_at=timezone.now() + timezone.timedelta(minutes=i),
            )
        return session

    def test_before_any_ticket(self, world):
        (ticket,) = row(world)["practice"]
        assert ticket["finished"] == 0 and ticket["average"] is None and ticket["recent"] == []
        assert ticket["in_progress"] is False

    def test_the_count_the_average_out_of_five_and_the_three_most_recent_newest_first(self, world):
        self.finished(world, [0.4, 0.6, 0.8, 1.0])
        (ticket,) = row(world)["practice"]
        assert ticket["finished"] == 4
        assert ticket["average"] == pytest.approx(3.5)  # (0.4+0.6+0.8+1.0)/4 * 5
        assert [r["score"] for r in ticket["recent"]] == [5.0, 4.0, 3.0]
        assert "%" not in json.dumps(ticket)

    def test_a_ticket_in_progress_is_flagged_without_its_scenario(self, world):
        make_session(world["learner"], world["ticket"], state="open")
        (ticket,) = row(world)["practice"]
        assert ticket["in_progress"] is True
        raw = json.dumps(ticket)
        for leak in ("scenario", "persona", "reference_answer", "skip_reason"):
            assert leak not in raw


class TestMentorRatedWork:
    def hand_in(self, world):
        case = SimCase.objects.create(
            user=world["learner"],
            activity=world["sim"],
            opened_at=timezone.now(),
            due_at=timezone.now() + timezone.timedelta(days=7),
        )
        return case

    def test_not_handed_in_yet(self, world):
        (sim,) = row(world)["rated"]
        assert sim["status"] == "not_submitted" and sim["feedback"] is None
        assert "last_score" not in sim

    def test_a_rated_revision_shows_the_status_and_comment_but_never_the_mentors_score(self, world):
        case = self.hand_in(world)
        SimSubmission.objects.create(
            case=case,
            revision=1,
            answer="My reply",
            submitted_at=timezone.now(),
            review_due_at=timezone.now(),
            state=SimSubmission.State.RATED,
            rated_by=world["mentor"],
            rated_at=timezone.now(),
            overall_comment="Name the root cause next time.",
            raw_score=2.5,
            scaled=0.5,
            passed=False,
        )
        (sim,) = row(world)["rated"]
        assert sim["status"] == "changes_requested"
        assert "last_score" not in sim and sim["revisions"] == 1
        assert "2.5" not in json.dumps(row(world)["rated"])
        assert sim["feedback"] == "Name the root cause next time."
        assert sim["due_at"] is not None and sim["rated_at"] is not None

    def test_the_latest_comment_wins_and_raters_notes_never_appear(self, world):
        case = self.hand_in(world)
        for revision, comment in ((1, "First note."), (2, "Second note.")):
            SimSubmission.objects.create(
                case=case,
                revision=revision,
                answer="Reply",
                submitted_at=timezone.now(),
                review_due_at=timezone.now(),
                state=SimSubmission.State.RATED,
                rated_by=world["mentor"],
                rated_at=timezone.now(),
                overall_comment=comment,
                raw_score=3.0,
                scaled=0.6,
                passed=False,
                draft={"comment": "RATER-ONLY draft"},
            )
        raw = json.dumps(summary.learner_summary(world["learner"]))
        assert "Second note." in raw and "First note." not in raw
        assert "RATER-ONLY" not in raw and "guidance" not in raw
        assert "rated_by" not in raw and "routing" not in raw and "assigned_mentor" not in raw


class TestModuleIndex:
    def test_every_module_in_order_with_its_lessons_nothing_started(self, world):
        mods = row(world)["modules"]
        assert [(m["title"], m["lessons_total"], m["lessons_done"], m["state"]) for m in mods] == [
            ("Module One", 2, 0, "not_started"),
            ("Module Two", 1, 0, "not_started"),
        ]
        assert mods[0]["next_lesson"] == {"id": world["intro"].pk, "title": "Intro"}
        assert mods[1]["next_lesson"] is None
        assert [(x["title"], x["state"]) for x in mods[0]["lessons"]] == [
            ("Intro", "next"),
            (mods[0]["lessons"][1]["title"], "not_started"),
        ]
        assert all(set(x) == {"id", "title", "required", "state"} for x in mods[0]["lessons"])

    def test_a_finished_module_is_done_and_the_next_one_holds_what_is_next(self, world):
        learner = world["learner"]
        progress.complete_activity(learner, world["reading"].pk)
        progress.submit_attempt(learner, world["plain"].pk, [[0]])
        progress.complete_activity(learner, world["later"].pk)
        progress.complete_lesson(learner, world["extra"].pk)
        one, two = row(world)["modules"]
        assert (two["state"], two["lessons_done"]) == ("done", 1)
        assert one["state"] == "not_started" and one["lessons_done"] == 0
        assert [x["state"] for x in two["lessons"]] == ["done"]

    def test_an_optional_lesson_says_so(self, world):
        world["extra"].is_required = False
        world["extra"].save()
        (lesson,) = row(world)["modules"][1]["lessons"]
        assert lesson["required"] is False

    def test_a_lesson_waiting_for_marks_starts_a_module_but_does_not_finish_it(
        self, make_role_user
    ):
        w = build(make_role_user, title="Idx", order="sequential")
        w.update(cast(make_role_user))
        enrollment.enroll(w["learner"], w["course"])
        progress.complete_activity(w["learner"], w["reading"].pk)
        progress.submit_attempt(w["learner"], w["plain"].pk, [[0]])
        progress.submit_attempt(w["learner"], w["mixed"].pk, ALL_RIGHT)
        progress.complete_lesson(w["learner"], w["intro"].pk)
        one = row(w)["modules"][0]
        assert (one["state"], one["lessons_done"], one["lessons_awaiting_review"]) == (
            "in_progress",
            0,
            1,
        )
        assert one["next_lesson"]["title"] == "Tickets"
        assert [x["state"] for x in one["lessons"]] == ["awaiting_review", "next"]

    def test_a_switched_off_module_is_not_in_the_index(self, world):
        ModuleExclusion.objects.create(
            enrollment=world["learner"].enrollments.get(), node=world["two"]
        )
        assert [m["title"] for m in row(world)["modules"]] == ["Module One"]

    def test_an_empty_module_is_left_out(self, world):
        from apps.catalog.models import ContentNode

        ContentNode.objects.create(
            course_version=world["version"],
            parent=world["version"].root_node,
            kind=ContentNode.Kind.SEGMENT,
            title="Empty",
            slug="empty",
            order=9,
        )
        assert "Empty" not in [m["title"] for m in row(world)["modules"]]


class TestTheEndpoint:
    def test_it_is_for_signed_in_people_only(self, client):
        assert client.get(reverse("progress_api:summary")).status_code in (401, 403)

    def test_it_returns_only_the_callers_courses(self, client, world):
        client.force_login(world["learner"])
        body = client.get(reverse("progress_api:summary")).json()
        assert [c["title"] for c in body["courses"]] == ["Course"]
        client.force_login(world["other"])
        assert client.get(reverse("progress_api:summary")).json() == {"courses": []}

    def test_nothing_trainer_only_leaks_through_any_key(self, client, world):
        from tests.test_sim_learner_privacy import assert_nothing_trainer_only

        progress.submit_attempt(world["learner"], world["mixed"].pk, ALL_RIGHT)
        make_session(world["learner"], world["ticket"], state="finished")
        client.force_login(world["learner"])
        assert_nothing_trainer_only(client.get(reverse("progress_api:summary")), where="summary")

    def test_the_number_of_queries_does_not_grow_with_the_amount_of_content(self, client, world):
        client.force_login(world["learner"])
        client.get(reverse("progress_api:summary"))  # warm anything cached
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as small:
            client.get(reverse("progress_api:summary"))
        # Ten more quizzes and readings in the same lesson, answered.
        for i in range(10):
            Activity.objects.create(
                content_node=world["intro"],
                activity_type="mcq",
                title=f"Extra quiz {i}",
                config=PLAIN_QUIZ,
                max_attempts=2,
            )
            Activity.objects.create(
                content_node=world["intro"],
                activity_type="reading",
                title=f"Extra read {i}",
                config={"source_url": "https://x.io"},
            )
        ActivityProgress.objects.create(
            user=world["learner"], activity=world["reading"], started_at=timezone.now()
        )
        with CaptureQueriesContext(connection) as big:
            client.get(reverse("progress_api:summary"))
        assert len(big) == len(small), (len(small), len(big))
