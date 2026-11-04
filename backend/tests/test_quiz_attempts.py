"""Submitting a quiz: judging, recording, completing, limits and secrecy."""

import json
import threading

import pytest
from django.db import connection
from django.urls import reverse

from apps.accounts.models import Role
from apps.catalog import services as catalog
from apps.catalog.models import Activity, CourseVersion
from apps.progress.models import ActivityAttempt, ActivityProgress, LessonCompletion

pytestmark = pytest.mark.django_db

QUESTIONS = [
    {"text": "One", "choices": ["A", "B", "C"], "answer": 1, "explanation": "SECRET-EXPLAIN-1"},
    {
        "text": "Two",
        "choices": ["W", "X", "Y"],
        "answer": [0, 2],
        "explanation": "SECRET-EXPLAIN-2",
    },
]
RIGHT = [[1], [0, 2]]
HALF = [[0], [0, 2]]  # one of two: 50%
WRONG = [[0], [1]]


@pytest.fixture
def course(make_role_user):
    author = make_role_user(Role.Name.TRAINER, username="author", email="a@example.com")
    c = catalog.create_course(title="Course", user=author)
    version = catalog.open_version(c)
    module = catalog.add_node(version.root_node, title="M")
    lesson = catalog.add_node(module, title="Lesson")
    quiz = Activity.objects.create(
        content_node=lesson,
        activity_type="mcq",
        title="Quiz",
        config={"questions": QUESTIONS, "pass_threshold": 1},
        max_attempts=3,
    )
    version.publish(author)
    return {"quiz": quiz, "lesson": lesson, "version": version}


@pytest.fixture
def lc(client, make_role_user):
    client.force_login(make_role_user(Role.Name.LEARNER))
    return client


def attempt(client, activity, answers):
    return client.post(
        reverse("progress_api:activity-attempts", args=[activity.id]),
        data=json.dumps({"answers": answers}),
        content_type="application/json",
    )


def progress(client, course):
    return client.get(reverse("progress_api:course", args=[course["version"].id])).json()


class TestPassing:
    def test_a_pass_records_the_attempt_and_completes_the_activity(self, lc, course):
        response = attempt(lc, course["quiz"], RIGHT)
        assert response.status_code == 201
        body = response.json()
        assert body["passed"] is True and body["state"] == "completed"
        assert (body["correct"], body["total"], body["score"]) == (2, 2, 1.0)
        assert ActivityAttempt.objects.get().number == 1
        assert ActivityProgress.objects.get().state == "completed"
        assert progress(lc, course)["activities"] == {str(course["quiz"].id): "completed"}

    def test_a_required_quiz_gates_the_lesson_until_passed(self, lc, course):
        lesson_url = reverse("progress_api:lesson-complete", args=[course["lesson"].id])
        blocked = lc.post(lesson_url)
        assert blocked.status_code == 409 and blocked.json()["pending"] == [course["quiz"].id]

        attempt(lc, course["quiz"], WRONG)
        assert lc.post(lesson_url).status_code == 409  # a failed try isn't a pass

        attempt(lc, course["quiz"], RIGHT)
        assert lc.post(lesson_url).status_code == 200
        assert LessonCompletion.objects.count() == 1

    def test_a_pass_is_permanent(self, lc, course):
        attempt(lc, course["quiz"], RIGHT)
        again = attempt(lc, course["quiz"], WRONG)
        assert again.status_code == 409 and "already passed" in again.json()["detail"]
        assert ActivityProgress.objects.get().state == "completed"
        assert ActivityAttempt.objects.count() == 1


class TestFailing:
    def test_a_fail_is_recorded_and_leaves_the_activity_started(self, lc, course):
        body = attempt(lc, course["quiz"], HALF).json()
        assert body["passed"] is False and body["state"] == "started"
        assert (body["correct"], body["total"], body["attempts_left"]) == (1, 2, 2)
        assert body["needed"] == 2
        assert ActivityProgress.objects.get().state == "started"
        attempt_row = ActivityAttempt.objects.get()
        assert attempt_row.score == 0.5 and attempt_row.details == [False, True]

    def test_attempts_are_numbered_and_summarised(self, lc, course):
        attempt(lc, course["quiz"], WRONG)
        attempt(lc, course["quiz"], HALF)
        assert [a.number for a in ActivityAttempt.objects.all()] == [1, 2]
        summary = progress(lc, course)["attempts"][str(course["quiz"].id)]
        assert summary == {"count": 2, "best_score": 0.5, "last_score": 0.5, "attempts_left": 1}

    def test_running_out_of_attempts_stops_further_tries(self, lc, course):
        for _ in range(3):
            attempt(lc, course["quiz"], WRONG)
        blocked = attempt(lc, course["quiz"], RIGHT)
        assert blocked.status_code == 409 and "all your attempts" in blocked.json()["detail"]
        assert ActivityAttempt.objects.count() == 3

    def test_zero_means_unlimited(self, lc, course):
        Activity.objects.filter(pk=course["quiz"].pk).update(max_attempts=0)
        for _ in range(6):
            assert attempt(lc, course["quiz"], WRONG).status_code == 201
        assert progress(lc, course)["attempts"][str(course["quiz"].id)]["attempts_left"] is None
        assert attempt(lc, course["quiz"], RIGHT).json()["passed"] is True


class TestExhaustion:
    """Using every attempt without a pass finishes the quiz: the lesson may
    proceed, and every score stays on record."""

    def fail_all(self, lc, course, tries=3):
        for _ in range(tries):
            attempt(lc, course["quiz"], WRONG)

    def test_the_last_failed_attempt_marks_it_finished_not_passed(self, lc, course):
        self.fail_all(lc, course, tries=2)
        assert ActivityProgress.objects.get().state == "started"  # tries remain
        last = attempt(lc, course["quiz"], WRONG).json()
        assert last["state"] == "exhausted" and last["passed"] is False
        assert progress(lc, course)["activities"] == {str(course["quiz"].id): "exhausted"}

    def test_a_quiz_with_tries_left_still_blocks_the_lesson(self, lc, course):
        self.fail_all(lc, course, tries=2)
        blocked = lc.post(reverse("progress_api:lesson-complete", args=[course["lesson"].id]))
        assert blocked.status_code == 409

    def test_an_exhausted_quiz_no_longer_blocks_the_lesson(self, lc, course):
        self.fail_all(lc, course)
        done = lc.post(reverse("progress_api:lesson-complete", args=[course["lesson"].id]))
        assert done.status_code == 200
        assert LessonCompletion.objects.count() == 1

    def test_every_score_is_still_on_record(self, lc, course):
        attempt(lc, course["quiz"], WRONG)
        attempt(lc, course["quiz"], HALF)
        attempt(lc, course["quiz"], WRONG)
        assert [a.score for a in ActivityAttempt.objects.order_by("number")] == [0.0, 0.5, 0.0]
        summary = progress(lc, course)["attempts"][str(course["quiz"].id)]
        assert summary["best_score"] == 0.5 and summary["attempts_left"] == 0

    def test_it_cannot_be_retaken_afterwards(self, lc, course):
        self.fail_all(lc, course)
        assert attempt(lc, course["quiz"], RIGHT).status_code == 409
        assert ActivityProgress.objects.get().state == "exhausted"


class TestAttemptReport:
    def report(self, client, activity):
        return client.get(reverse("progress_api:activity-attempts", args=[activity.id]))

    def test_nothing_yet(self, lc, course):
        assert self.report(lc, course["quiz"]).json() == {"history": [], "latest": None}

    def test_history_lists_every_try_oldest_first(self, lc, course):
        attempt(lc, course["quiz"], WRONG)
        attempt(lc, course["quiz"], HALF)
        history = self.report(lc, course["quiz"]).json()["history"]
        assert [(h["number"], h["score"], h["passed"]) for h in history] == [
            (1, 0.0, False),
            (2, 0.5, False),
        ]
        assert history[1]["correct"] == 1 and history[1]["total"] == 2
        assert history[1]["submitted_at"]

    def test_the_submit_response_carries_the_same_history_and_their_picks(self, lc, course):
        body = attempt(lc, course["quiz"], HALF).json()
        assert body["picks"] == HALF
        assert [h["number"] for h in body["history"]] == [1]

    def test_the_latest_try_is_reviewed_without_the_key_while_tries_remain(self, lc, course):
        attempt(lc, course["quiz"], HALF)
        latest = self.report(lc, course["quiz"]).json()["latest"]
        assert latest["picks"] == HALF and latest["attempts_left"] == 2
        assert latest["review"] == [{"correct": False}, {"correct": True}]

    def test_the_key_appears_once_passed_or_exhausted(self, lc, course):
        attempt(lc, course["quiz"], RIGHT)
        passed = self.report(lc, course["quiz"]).json()["latest"]
        assert passed["state"] == "completed"
        assert passed["review"][0]["correct_answers"] == [1]

    def test_exhausted_reveals_too(self, lc, course):
        for _ in range(3):
            attempt(lc, course["quiz"], WRONG)
        latest = self.report(lc, course["quiz"]).json()["latest"]
        assert latest["state"] == "exhausted"
        assert latest["review"][0]["correct_answers"] == [1]
        assert latest["review"][0]["explanation"] == "SECRET-EXPLAIN-1"

    def test_it_is_your_own_history_only(self, client, make_role_user, course):
        one = make_role_user(Role.Name.LEARNER, username="one", email="one@example.com")
        two = make_role_user(Role.Name.LEARNER, username="two", email="two@example.com")
        client.force_login(one)
        attempt(client, course["quiz"], HALF)
        client.force_login(two)
        assert self.report(client, course["quiz"]).json() == {"history": [], "latest": None}

    def test_refusals(self, client, lc, course):
        assert self.report(lc, Activity(id=9999)).status_code == 404
        CourseVersion.objects.filter(pk=course["version"].pk).update(state="archived")
        assert self.report(lc, course["quiz"]).status_code == 404
        client.logout()
        assert self.report(client, course["quiz"]).status_code == 403


class TestResetAttempts:
    def reset(self, client, activity):
        return client.delete(reverse("progress_api:activity-attempts", args=[activity.id]))

    def test_it_is_off_unless_switched_on(self, lc, course):
        attempt(lc, course["quiz"], WRONG)
        response = self.reset(lc, course["quiz"])
        assert response.status_code == 403
        assert ActivityAttempt.objects.count() == 1
        assert progress(lc, course)["can_reset_attempts"] is False

    def test_when_on_it_clears_the_tries_and_the_quiz_can_be_taken_again(
        self, lc, course, settings
    ):
        settings.ALLOW_ATTEMPT_RESET = True
        for _ in range(3):
            attempt(lc, course["quiz"], WRONG)
        assert attempt(lc, course["quiz"], RIGHT).status_code == 409
        assert progress(lc, course)["can_reset_attempts"] is True

        assert self.reset(lc, course["quiz"]).status_code == 204
        assert not ActivityAttempt.objects.exists()
        assert not ActivityProgress.objects.exists()
        assert progress(lc, course)["activities"] == {}
        assert attempt(lc, course["quiz"], RIGHT).json()["passed"] is True

    def test_it_also_reopens_a_lesson_that_depended_on_the_quiz(self, lc, course, settings):
        settings.ALLOW_ATTEMPT_RESET = True
        attempt(lc, course["quiz"], RIGHT)
        lesson_url = reverse("progress_api:lesson-complete", args=[course["lesson"].id])
        assert lc.post(lesson_url).status_code == 200
        self.reset(lc, course["quiz"])
        assert not LessonCompletion.objects.exists()
        assert lc.post(lesson_url).status_code == 409

    def test_it_only_touches_your_own_attempts_and_is_idempotent(
        self, client, make_role_user, course, settings
    ):
        settings.ALLOW_ATTEMPT_RESET = True
        one = make_role_user(Role.Name.LEARNER, username="one", email="one@example.com")
        two = make_role_user(Role.Name.LEARNER, username="two", email="two@example.com")
        client.force_login(one)
        attempt(client, course["quiz"], WRONG)
        client.force_login(two)
        attempt(client, course["quiz"], WRONG)
        assert self.reset(client, course["quiz"]).status_code == 204
        assert self.reset(client, course["quiz"]).status_code == 204
        assert ActivityAttempt.objects.get().user == one

    def test_other_types_have_nothing_to_reset(self, lc, course, settings):
        settings.ALLOW_ATTEMPT_RESET = True
        reading = Activity.objects.create(
            content_node=course["lesson"],
            activity_type="reading",
            title="R",
            config={"source_url": "https://x.io"},
        )
        assert self.reset(lc, reading).status_code == 400


class TestAnswerKeySecrecy:
    """The key and explanations leave the server only when trying again can't
    be gamed with them: after a pass, or once the last attempt is spent."""

    def test_a_failed_attempt_with_tries_left_reveals_only_right_or_wrong(self, lc, course):
        response = attempt(lc, course["quiz"], HALF)
        assert response.json()["review"] == [{"correct": False}, {"correct": True}]
        assert "SECRET" not in response.content.decode()
        assert "correct_answers" not in response.content.decode()

    def test_passing_reveals_the_key_and_explanations(self, lc, course):
        review = attempt(lc, course["quiz"], RIGHT).json()["review"]
        assert review[0] == {
            "correct": True,
            "correct_answers": [1],
            "explanation": "SECRET-EXPLAIN-1",
        }
        assert review[1]["correct_answers"] == [0, 2]

    def test_spending_the_last_attempt_reveals_too(self, lc, course):
        attempt(lc, course["quiz"], WRONG)
        attempt(lc, course["quiz"], WRONG)
        last = attempt(lc, course["quiz"], WRONG).json()
        assert last["attempts_left"] == 0
        assert last["review"][0]["correct_answers"] == [1]

    def test_nothing_else_the_learner_can_fetch_carries_the_key(self, lc, course):
        attempt(lc, course["quiz"], HALF)
        tree = lc.get(reverse("catalog_api:course-tree", args=[course["version"].id]))
        for payload in (tree.content.decode(), json.dumps(progress(lc, course))):
            assert "SECRET" not in payload
            assert '"answer"' not in payload and "explanation" not in payload
        assert ActivityAttempt.objects.get().answers == HALF  # their picks, not the key


class TestRefusals:
    @pytest.mark.parametrize(
        "answers",
        [None, [], [[1]], [[1], []], [[1], [9]], [[0, 1], [0]], "x", [["a"], [0]]],
    )
    def test_bad_answers_are_a_400_and_cost_no_attempt(self, lc, course, answers):
        response = attempt(lc, course["quiz"], answers)
        assert response.status_code == 400 and response.json()["detail"]
        assert not ActivityAttempt.objects.exists()

    def test_anonymous_is_refused(self, client, course):
        assert attempt(client, course["quiz"], RIGHT).status_code == 403

    @pytest.mark.parametrize(
        "state",
        [CourseVersion.State.DRAFT, CourseVersion.State.IN_REVIEW, CourseVersion.State.ARCHIVED],
    )
    def test_only_published_quizzes_take_attempts(self, lc, course, state):
        CourseVersion.objects.filter(pk=course["version"].pk).update(state=state)
        assert attempt(lc, course["quiz"], RIGHT).status_code == 404

    def test_unknown_activity_is_404(self, lc):
        response = lc.post(
            reverse("progress_api:activity-attempts", args=[9999]),
            data=json.dumps({"answers": []}),
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_other_types_take_no_attempts(self, lc, course):
        reading = Activity.objects.create(
            content_node=course["lesson"],
            activity_type="reading",
            title="R",
            config={"source_url": "https://x.io"},
        )
        assert attempt(lc, reading, [[0]]).status_code == 400

    def test_a_quiz_cannot_be_ticked_off_or_unticked_by_hand(self, lc, course):
        complete = reverse("progress_api:activity-complete", args=[course["quiz"].id])
        assert lc.post(complete).status_code == 400
        assert lc.delete(complete).status_code == 400
        attempt(lc, course["quiz"], RIGHT)
        assert lc.delete(complete).status_code == 400
        assert ActivityProgress.objects.get().state == "completed"


class TestIsolationAndLoad:
    def test_attempts_belong_to_one_learner(self, client, make_role_user, course):
        one = make_role_user(Role.Name.LEARNER, username="one", email="one@example.com")
        two = make_role_user(Role.Name.LEARNER, username="two", email="two@example.com")
        client.force_login(one)
        attempt(client, course["quiz"], RIGHT)
        client.force_login(two)
        assert progress(client, course) == {
            "completed_lessons": [],
            "awaiting_review_lessons": [],
            "activities": {},
            "attempts": {},
            "can_reset_attempts": False,
            "watch": {},
            "sim": {},
            "rated": {},
            "learning_order": "free",
            "locked": {},
            "next_lesson_id": course["lesson"].id,
        }
        assert (
            attempt(client, course["quiz"], WRONG).json()["attempts_left"] == 2
        )  # their own count

    def test_progress_read_stays_a_fixed_number_of_queries(
        self, lc, course, django_assert_max_num_queries
    ):
        for _ in range(3):
            attempt(lc, course["quiz"], WRONG)
        with django_assert_max_num_queries(10):
            assert (
                lc.get(reverse("progress_api:course", args=[course["version"].id])).status_code
                == 200
            )

    def test_admin_lists_attempts_read_only(self, admin_client, lc, course):
        attempt(lc, course["quiz"], WRONG)
        changelist = admin_client.get(reverse("admin:progress_activityattempt_changelist"))
        assert changelist.status_code == 200
        assert admin_client.get(reverse("admin:progress_activityattempt_add")).status_code == 403


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor == "sqlite", reason="needs row locks")
def test_concurrent_submits_cannot_overrun_the_limit(client, make_role_user, course):
    user = make_role_user(Role.Name.LEARNER, username="racer", email="r@example.com")
    Activity.objects.filter(pk=course["quiz"].pk).update(max_attempts=2)
    statuses: list[int] = []

    def submit():
        from django.test import Client

        c = Client()
        c.force_login(user)
        statuses.append(attempt(c, course["quiz"], WRONG).status_code)
        connection.close()

    threads = [threading.Thread(target=submit) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(statuses).count(201) == 2
    assert ActivityAttempt.objects.filter(user=user).count() == 2
    assert sorted(a.number for a in ActivityAttempt.objects.filter(user=user)) == [1, 2]
