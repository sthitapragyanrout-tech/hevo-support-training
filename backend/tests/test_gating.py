"""A course that goes in order: what is locked, what refuses to record, and
how finishing a lesson opens the next."""

import json

import pytest
from django.urls import reverse

from apps.accounts.models import Role
from apps.catalog import services as catalog
from apps.catalog.models import Activity, CourseVersion
from apps.progress.models import LessonCompletion

pytestmark = pytest.mark.django_db

QUESTIONS = [{"text": "Q", "choices": ["A", "B"], "answer": 0}]
RIGHT = [[0]]
WRONG = [[1]]


def build(make_role_user, order="sequential"):
    author = make_role_user(Role.Name.TRAINER, username="author", email="a@example.com")
    admin = make_role_user(Role.Name.ADMIN, username="adm", email="adm@example.com")
    course = catalog.create_course(title="Course", user=author)
    version = catalog.open_version(course)
    module = catalog.add_node(version.root_node, title="Module")

    def lesson(title, required=True):
        node = catalog.add_node(module, title=title, is_required=required)
        reading = Activity.objects.create(
            content_node=node,
            activity_type="reading",
            title=f"Read {title}",
            config={"source_url": "https://x.io"},
        )
        return node, reading

    one, r1 = lesson("One")
    quiz = Activity.objects.create(
        content_node=one,
        activity_type="mcq",
        title="Quiz",
        config={"questions": QUESTIONS, "pass_threshold": 1},
        max_attempts=2,
    )
    two, r2 = lesson("Two")
    bonus, r3 = lesson("Bonus", required=False)
    four, r4 = lesson("Four")
    catalog.set_learning_order(version, order)
    version.publish(admin)
    return {
        "version": version,
        "one": one, "two": two, "bonus": bonus, "four": four,
        "r1": r1, "quiz": quiz, "r2": r2, "r3": r3, "r4": r4,
    }  # fmt: skip


@pytest.fixture
def world(make_role_user):
    return build(make_role_user)


@pytest.fixture
def lc(client, make_role_user):
    client.force_login(make_role_user(Role.Name.LEARNER, username="lrn", email="l@example.com"))
    return client


def post(client, name, *args, **body):
    return client.post(
        reverse(f"progress_api:{name}", args=args),
        data=json.dumps(body) if body else None,
        content_type="application/json",
    )


def progress(client, world):
    return client.get(reverse("progress_api:course", args=[world["version"].id])).json()


def finish_lesson_one(client, world, *, quiz=RIGHT):
    post(client, "activity-complete", world["r1"].id)
    post(client, "activity-attempts", world["quiz"].id, answers=quiz)
    return post(client, "lesson-complete", world["one"].id)


class TestWhatIsLocked:
    def test_only_the_first_lesson_is_open_at_the_start(self, lc, world):
        body = progress(lc, world)
        assert body["learning_order"] == "sequential"
        assert body["next_lesson_id"] == world["one"].id
        locked = {int(k): v for k, v in body["locked"].items()}
        assert set(locked) == {world["two"].id, world["bonus"].id, world["four"].id}
        assert locked[world["two"].id] == {"blocked_by": world["one"].id, "blocked_by_title": "One"}

    def test_a_free_course_locks_nothing(self, client, make_role_user):
        world = build(make_role_user, order="free")
        client.force_login(make_role_user(Role.Name.LEARNER, username="l2", email="l2@example.com"))
        body = progress(client, world)
        assert body["learning_order"] == "free" and body["locked"] == {}
        assert post(client, "activity-complete", world["r4"].id).status_code == 200

    def test_the_payload_is_a_fixed_number_of_queries(
        self, lc, world, django_assert_max_num_queries
    ):
        with django_assert_max_num_queries(10):
            assert (
                lc.get(reverse("progress_api:course", args=[world["version"].id])).status_code
                == 200
            )


class TestRefusingOutOfOrder:
    def test_nothing_can_be_recorded_against_a_locked_lesson(self, lc, world):
        for response in (
            post(lc, "activity-start", world["r2"].id),
            post(lc, "activity-complete", world["r2"].id),
            post(lc, "lesson-complete", world["two"].id),
        ):
            assert response.status_code == 409
            assert response.json()["detail"] == "Finish “One” first."
            assert response.json()["blocked_by"] == world["one"].id
        assert not LessonCompletion.objects.exists()

    def test_nor_a_quiz_attempt(self, lc, world):
        quiz2 = Activity.objects.create(
            content_node=world["two"],
            activity_type="mcq",
            title="Quiz two",
            config={"questions": QUESTIONS, "pass_threshold": 1},
        )
        response = post(lc, "activity-attempts", quiz2.id, answers=RIGHT)
        assert response.status_code == 409 and "Finish “One”" in response.json()["detail"]

    def test_the_open_lesson_records_normally(self, lc, world):
        assert post(lc, "activity-complete", world["r1"].id).status_code == 200

    def test_a_section_of_a_locked_lesson_is_locked_too(self, lc, world):
        section = catalog.add_node(world["four"], title="Section")
        Activity.objects.filter(pk=world["r4"].pk).update(content_node=section)
        # (the draft is published, but the guard reads structure, not state)
        response = post(lc, "activity-complete", world["r4"].id)
        assert response.status_code == 409

    def test_the_lesson_gate_on_required_activities_still_applies(self, lc, world):
        post(lc, "activity-complete", world["r1"].id)
        blocked = post(lc, "lesson-complete", world["one"].id)
        assert blocked.status_code == 409 and "required activit" in blocked.json()["detail"]


class TestUnlocking:
    def test_finishing_a_lesson_opens_the_next_one_straight_away(self, lc, world):
        assert finish_lesson_one(lc, world).status_code == 200
        body = progress(lc, world)
        locked = {int(k) for k in body["locked"]}
        assert world["two"].id not in locked
        assert world["four"].id in locked  # still waiting on Two
        assert body["next_lesson_id"] == world["two"].id
        assert post(lc, "activity-complete", world["r2"].id).status_code == 200

    def test_a_quiz_that_is_failed_with_tries_left_does_not_open_the_next(self, lc, world):
        post(lc, "activity-complete", world["r1"].id)
        post(lc, "activity-attempts", world["quiz"].id, answers=WRONG)
        assert post(lc, "lesson-complete", world["one"].id).status_code == 409
        assert world["two"].id in {int(k) for k in progress(lc, world)["locked"]}

    def test_using_every_attempt_does_open_the_next(self, lc, world):
        post(lc, "activity-complete", world["r1"].id)
        post(lc, "activity-attempts", world["quiz"].id, answers=WRONG)
        post(lc, "activity-attempts", world["quiz"].id, answers=WRONG)
        assert post(lc, "lesson-complete", world["one"].id).status_code == 200
        assert world["two"].id not in {int(k) for k in progress(lc, world)["locked"]}

    def test_an_optional_lesson_never_holds_up_the_ones_after_it(self, lc, world):
        finish_lesson_one(lc, world)
        post(lc, "activity-complete", world["r2"].id)
        post(lc, "lesson-complete", world["two"].id)
        locked = {int(k) for k in progress(lc, world)["locked"]}
        assert locked == set()  # Bonus (optional) is open, and Four doesn't wait for it
        assert post(lc, "activity-complete", world["r4"].id).status_code == 200

    def test_next_prefers_required_lessons(self, lc, world):
        finish_lesson_one(lc, world)
        post(lc, "activity-complete", world["r2"].id)
        post(lc, "lesson-complete", world["two"].id)
        assert progress(lc, world)["next_lesson_id"] == world["four"].id

    def test_nothing_is_next_when_everything_is_done(self, lc, world):
        finish_lesson_one(lc, world)
        for lesson, reading in (("two", "r2"), ("bonus", "r3"), ("four", "r4")):
            post(lc, "activity-complete", world[reading].id)
            post(lc, "lesson-complete", world[lesson].id)
        assert progress(lc, world)["next_lesson_id"] is None


class TestRelocking:
    def test_reopening_an_earlier_lesson_locks_only_what_is_not_done(self, lc, world):
        finish_lesson_one(lc, world)
        post(lc, "activity-complete", world["r2"].id)
        post(lc, "lesson-complete", world["two"].id)
        lc.delete(reverse("progress_api:lesson-complete", args=[world["one"].id]))
        body = progress(lc, world)
        locked = {int(k): v for k, v in body["locked"].items()}
        assert world["two"].id not in locked  # already finished: history stays open
        assert locked[world["four"].id]["blocked_by"] == world["one"].id
        assert body["next_lesson_id"] == world["one"].id

    def test_a_reset_that_reopens_a_lesson_relocks_what_followed(self, lc, world, settings):
        settings.ALLOW_ATTEMPT_RESET = True
        finish_lesson_one(lc, world)
        assert world["two"].id not in {int(k) for k in progress(lc, world)["locked"]}
        lc.delete(reverse("progress_api:activity-attempts", args=[world["quiz"].id]))
        assert world["two"].id in {int(k) for k in progress(lc, world)["locked"]}


class TestPerLearner:
    def test_each_learner_has_their_own_locks(self, client, make_role_user, world):
        ann = make_role_user(Role.Name.LEARNER, username="ann", email="ann@example.com")
        bob = make_role_user(Role.Name.LEARNER, username="bob", email="bob@example.com")
        client.force_login(ann)
        finish_lesson_one(client, world)
        client.force_login(bob)
        assert world["two"].id in {int(k) for k in progress(client, world)["locked"]}
        assert post(client, "activity-complete", world["r2"].id).status_code == 409


class TestNewDraftsKeepTheOrder:
    def test_the_order_is_copied_into_a_new_draft(self, world, make_role_user):
        course = world["version"].course
        draft = catalog.get_or_create_draft(course)
        assert draft.learning_order == CourseVersion.LearningOrder.SEQUENTIAL
