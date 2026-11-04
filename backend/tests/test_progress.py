import json

import pytest
from django.urls import reverse

from apps.accounts.models import Role
from apps.catalog import services as catalog
from apps.catalog.models import Activity, CourseVersion
from apps.progress.models import ActivityProgress, LessonCompletion

pytestmark = pytest.mark.django_db


@pytest.fixture
def course(make_role_user):
    """A published course: one module, lesson A (reading + section with a
    required reading and an optional one + a video), lesson B (no activities)."""
    author = make_role_user(Role.Name.TRAINER, username="author", email="a@example.com")
    c = catalog.create_course(title="Course", user=author)
    version = catalog.open_version(c)
    module = catalog.add_node(version.root_node, title="M")
    lesson_a = catalog.add_node(module, title="Lesson A", description="Hook.")
    section = catalog.add_node(lesson_a, title="Section")
    lesson_b = catalog.add_node(module, title="Lesson B", description="Just reading.")

    def act(node, kind, title, **extra):
        config = {"source_url": "https://x.io"} if kind == "reading" else {}
        return Activity.objects.create(
            content_node=node, activity_type=kind, title=title, config=config, **extra
        )

    data = {
        "lesson_own": act(lesson_a, "reading", "Own reading"),
        "section_reading": act(section, "reading", "Section reading"),
        "optional": act(section, "reading", "Optional reading", is_required=False),
        "video": act(lesson_a, "video", "Video"),  # required, but not completable yet
        "lesson_a": lesson_a,
        "lesson_b": lesson_b,
        "version": version,
    }
    version.publish(author)
    return data


@pytest.fixture
def learner(make_role_user):
    return make_role_user(Role.Name.LEARNER)


@pytest.fixture
def lc(client, learner):
    client.force_login(learner)
    return client


def url(name, *args):
    return reverse(f"progress_api:{name}", args=args)


def post(client, name, *args):
    return client.post(url(name, *args), content_type="application/json")


def delete(client, name, *args):
    return client.delete(url(name, *args))


class TestAccessAndAvailability:
    def test_anonymous_is_refused(self, client, course):
        assert client.get(url("course", course["version"].id)).status_code == 403
        assert post(client, "activity-start", course["lesson_own"].id).status_code == 403
        assert post(client, "lesson-complete", course["lesson_b"].id).status_code == 403

    @pytest.mark.parametrize(
        "state",
        [CourseVersion.State.DRAFT, CourseVersion.State.IN_REVIEW, CourseVersion.State.ARCHIVED],
    )
    def test_only_published_versions_are_recordable(self, lc, course, state):
        CourseVersion.objects.filter(pk=course["version"].pk).update(state=state)
        assert lc.get(url("course", course["version"].id)).status_code == 404
        assert post(lc, "activity-complete", course["lesson_own"].id).status_code == 404
        assert post(lc, "lesson-complete", course["lesson_b"].id).status_code == 404

    def test_unknown_ids_are_404(self, lc):
        assert post(lc, "activity-start", 9999).status_code == 404
        assert post(lc, "lesson-complete", 9999).status_code == 404
        assert lc.get(url("course", 9999)).status_code == 404


class TestActivities:
    def test_start_then_complete_then_undo(self, lc, course):
        a = course["lesson_own"]
        assert post(lc, "activity-start", a.id).json() == {"state": "started"}
        assert post(lc, "activity-complete", a.id).json() == {"state": "completed"}
        row = ActivityProgress.objects.get()
        assert row.completed_at is not None
        assert delete(lc, "activity-complete", a.id).json() == {"state": "started"}
        row.refresh_from_db()
        assert row.state == "started" and row.completed_at is None

    def test_completing_without_starting_is_fine_and_everything_is_idempotent(self, lc, course):
        a = course["lesson_own"]
        for _ in range(2):
            assert post(lc, "activity-complete", a.id).json() == {"state": "completed"}
        for _ in range(2):
            assert post(lc, "activity-start", a.id).status_code == 200
        assert ActivityProgress.objects.count() == 1
        assert ActivityProgress.objects.get().state == "completed"  # start didn't downgrade it

    def test_uncompleting_something_never_done_is_a_quiet_noop(self, lc, course):
        assert delete(lc, "activity-complete", course["lesson_own"].id).json() == {"state": None}

    def test_types_that_cannot_be_completed_yet_are_refused(self, lc, course):
        response = post(lc, "activity-complete", course["video"].id)
        assert response.status_code == 400
        assert "can’t be completed yet" in response.json()["detail"]
        assert post(lc, "activity-start", course["video"].id).status_code == 400

    def test_progress_is_per_user(self, client, make_role_user, course):
        one = make_role_user(Role.Name.LEARNER, username="one", email="one@example.com")
        two = make_role_user(Role.Name.LEARNER, username="two", email="two@example.com")
        client.force_login(one)
        post(client, "activity-complete", course["lesson_own"].id)
        client.force_login(two)
        body = client.get(url("course", course["version"].id)).json()
        assert body == {
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
            "next_lesson_id": course["lesson_a"].id,
        }


class TestLessons:
    def test_a_lesson_with_nothing_to_finish_completes_and_undoes(self, lc, course):
        assert post(lc, "lesson-complete", course["lesson_b"].id).status_code == 200
        assert post(lc, "lesson-complete", course["lesson_b"].id).status_code == 200  # idempotent
        assert LessonCompletion.objects.count() == 1
        assert delete(lc, "lesson-complete", course["lesson_b"].id).status_code == 204
        assert LessonCompletion.objects.count() == 0

    def test_required_completable_activities_gate_the_lesson(self, lc, course):
        blocked = post(lc, "lesson-complete", course["lesson_a"].id)
        assert blocked.status_code == 409
        body = blocked.json()
        # The lesson's own reading and the section's required reading; NOT the
        # optional reading or the (not yet completable) video.
        assert sorted(body["pending"]) == sorted(
            [course["lesson_own"].id, course["section_reading"].id]
        )
        assert "2 required activities" in body["detail"]

        post(lc, "activity-complete", course["lesson_own"].id)
        assert post(lc, "lesson-complete", course["lesson_a"].id).status_code == 409
        post(lc, "activity-complete", course["section_reading"].id)
        assert post(lc, "lesson-complete", course["lesson_a"].id).status_code == 200

    def test_unmarking_a_required_activity_reopens_a_completed_lesson(self, lc, course):
        for key in ("lesson_own", "section_reading"):
            post(lc, "activity-complete", course[key].id)
        post(lc, "lesson-complete", course["lesson_a"].id)
        delete(lc, "activity-complete", course["section_reading"].id)
        assert LessonCompletion.objects.count() == 0

    def test_unmarking_an_optional_activity_leaves_the_lesson_complete(self, lc, course):
        for key in ("lesson_own", "section_reading"):
            post(lc, "activity-complete", course[key].id)
        post(lc, "lesson-complete", course["lesson_a"].id)
        # optional reading can't gate; undoing it must not reopen the lesson
        Activity.objects.filter(pk=course["optional"].pk).update(is_required=False)
        post(lc, "activity-complete", course["optional"].id)
        delete(lc, "activity-complete", course["optional"].id)
        assert LessonCompletion.objects.count() == 1

    def test_only_lessons_can_be_completed(self, lc, course):
        module = course["lesson_a"].parent
        section = course["section_reading"].content_node
        assert post(lc, "lesson-complete", module.id).status_code == 404
        assert post(lc, "lesson-complete", section.id).status_code == 404


class TestCourseProgress:
    def test_reports_completed_lessons_and_activity_states(self, lc, course):
        post(lc, "activity-complete", course["lesson_own"].id)
        post(lc, "activity-start", course["section_reading"].id)
        post(lc, "lesson-complete", course["lesson_b"].id)
        body = lc.get(url("course", course["version"].id)).json()
        assert body["completed_lessons"] == [course["lesson_b"].id]
        assert body["activities"] == {
            str(course["lesson_own"].id): "completed",
            str(course["section_reading"].id): "started",
        }

    def test_is_a_constant_number_of_queries(self, lc, course, django_assert_max_num_queries):
        post(lc, "activity-complete", course["lesson_own"].id)
        with django_assert_max_num_queries(10):
            assert lc.get(url("course", course["version"].id)).status_code == 200


class TestLearnerPayload:
    def test_reading_config_is_visible_and_unbuilt_types_expose_nothing(self, lc, course):
        response = lc.get(reverse("catalog_api:course-tree", args=[course["version"].id]))
        raw = json.dumps(response.json())
        assert "SECRET" not in raw

        acts = {}

        def walk(n):
            for a in n["activities"]:
                acts[a["title"]] = a
            for c in n["children"]:
                walk(c)

        walk(response.json()["root"])
        assert acts["Own reading"]["config"] == {"source_url": "https://x.io"}
        assert acts["Own reading"]["completable"] is True
        # A video with nothing behind it exposes no source, and can't hold a lesson up.
        assert acts["Video"]["config"].get("source") is None
        assert "media_url" not in acts["Video"]["config"]
        assert acts["Video"]["completable"] is False

    def test_unknown_config_keys_on_a_reading_are_not_exposed(self, lc, course):
        Activity.objects.filter(pk=course["lesson_own"].pk).update(
            config={"source_url": "https://x.io", "internal_note": "staff only"}
        )
        raw = lc.get(reverse("catalog_api:course-tree", args=[course["version"].id])).content
        assert b"internal_note" not in raw


def test_admin_changelists_load(admin_client, course, lc):
    post(lc, "activity-complete", course["lesson_own"].id)
    post(lc, "lesson-complete", course["lesson_b"].id)
    for name in ("activityprogress", "lessoncompletion"):
        assert admin_client.get(reverse(f"admin:progress_{name}_changelist")).status_code == 200
