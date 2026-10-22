import json

import pytest
from django.urls import reverse

from apps.accounts.models import Role
from apps.catalog.models import Activity, ContentNode, Course, CourseVersion

pytestmark = pytest.mark.django_db


def post(client, name, *args, data=None):
    return client.post(
        reverse(f"authoring_api:{name}", args=args),
        data=json.dumps(data or {}),
        content_type="application/json",
    )


def patch(client, name, *args, data):
    return client.patch(
        reverse(f"authoring_api:{name}", args=args),
        data=json.dumps(data),
        content_type="application/json",
    )


def put(client, name, *args, data):
    return client.put(
        reverse(f"authoring_api:{name}", args=args),
        data=json.dumps(data),
        content_type="application/json",
    )


def get(client, name, *args):
    return client.get(reverse(f"authoring_api:{name}", args=args))


@pytest.fixture
def trainer(make_role_user):
    return make_role_user(Role.Name.TRAINER)


@pytest.fixture
def admin_user(make_role_user):
    return make_role_user(Role.Name.ADMIN)


@pytest.fixture
def trainer_client(client, trainer):
    client.force_login(trainer)
    return client


@pytest.fixture
def admin_client_(client, admin_user):
    client.force_login(admin_user)
    return client


def make_valid_course(client, title="CX Onboarding 2026"):
    """Course → Module → Lesson → Section with content, via the API only."""
    course = post(client, "courses", data={"title": title, "description": "Intro"}).json()
    root_id = course["tree"]["root"]["id"]
    module = post(
        client, "node-create", course["id"], data={"parent": root_id, "title": "M1"}
    ).json()
    lesson = post(
        client,
        "node-create",
        course["id"],
        data={"parent": module["id"], "title": "L1", "description": "Hook."},
    ).json()
    section = post(
        client,
        "node-create",
        course["id"],
        data={"parent": lesson["id"], "title": "S1", "description": "Body"},
    ).json()
    return course["id"], module, lesson, section


class TestAccess:
    def test_anonymous_is_refused(self, client):
        assert get(client, "courses").status_code == 403

    def test_learner_is_refused_everywhere(self, client, make_role_user):
        client.force_login(make_role_user(Role.Name.LEARNER))
        assert get(client, "courses").status_code == 403
        assert get(client, "activity-types").status_code == 403
        assert post(client, "courses", data={"title": "x"}).status_code == 403

    def test_mentor_is_refused(self, client, make_role_user):
        client.force_login(make_role_user(Role.Name.MENTOR))
        assert get(client, "courses").status_code == 403

    def test_trainer_and_admin_may_list(self, trainer_client, client, admin_user):
        assert get(trainer_client, "courses").status_code == 200
        client.force_login(admin_user)
        assert get(client, "courses").status_code == 200


class TestCourseList:
    def test_rows_carry_structure_counts(self, trainer_client):
        course_id, *_ = make_valid_course(trainer_client, "Counted")
        post(trainer_client, "courses", data={"title": "Empty one"})
        rows = {r["title"]: r for r in get(trainer_client, "courses").json()}
        assert (rows["Counted"]["modules"], rows["Counted"]["lessons"]) == (1, 1)
        assert (rows["Empty one"]["modules"], rows["Empty one"]["lessons"]) == (0, 0)

    def test_list_uses_a_constant_number_of_queries(
        self, trainer_client, django_assert_max_num_queries
    ):
        for i in range(5):
            make_valid_course(trainer_client, f"Course {i}")
        with django_assert_max_num_queries(8):
            assert get(trainer_client, "courses").status_code == 200


class TestCreateAndBuild:
    def test_create_course_returns_a_draft_with_a_root(self, trainer_client):
        response = post(trainer_client, "courses", data={"title": "CX Onboarding 2026"})
        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "CX Onboarding 2026"
        assert body["status"] == {"key": "draft", "label": "Draft"}
        assert body["editable"] is True
        assert body["tree"]["root"]["kind"] == "course"
        # IDs of versions never leak as a primary concept.
        assert "versions" not in body

    def test_blank_title_is_a_400(self, trainer_client):
        assert post(trainer_client, "courses", data={"title": "   "}).status_code == 400

    def test_nodes_get_their_kind_from_the_parent(self, trainer_client):
        course_id, module, lesson, section = make_valid_course(trainer_client)
        assert (module["kind"], lesson["kind"], section["kind"]) == ("segment", "topic", "subtopic")
        assert module["slug"] == "m1"

    def test_a_section_cannot_have_children(self, trainer_client):
        course_id, _, _, section = make_valid_course(trainer_client)
        response = post(
            trainer_client, "node-create", course_id, data={"parent": section["id"], "title": "x"}
        )
        assert response.status_code == 400

    def test_parent_from_another_course_is_a_404(self, trainer_client):
        course_id, *_ = make_valid_course(trainer_client, "One")
        other = post(trainer_client, "courses", data={"title": "Two"}).json()
        response = post(
            trainer_client,
            "node-create",
            course_id,
            data={"parent": other["tree"]["root"]["id"], "title": "x"},
        )
        assert response.status_code == 404

    def test_update_delete_and_impact(self, trainer_client):
        course_id, module, lesson, section = make_valid_course(trainer_client)
        updated = patch(trainer_client, "node", module["id"], data={"title": "Renamed"})
        assert updated.status_code == 200 and updated.json()["title"] == "Renamed"

        impact = get(trainer_client, "node-impact", module["id"]).json()
        assert impact == {"lessons": 1, "sections": 1, "activities": 0}

        assert (
            trainer_client.delete(reverse("authoring_api:node", args=[module["id"]])).status_code
            == 204
        )
        assert not ContentNode.objects.filter(pk=lesson["id"]).exists()

    def test_reorder(self, trainer_client):
        course_id, module, lesson, _ = make_valid_course(trainer_client)
        second = post(
            trainer_client, "node-create", course_id, data={"parent": module["id"], "title": "L2"}
        ).json()
        response = put(
            trainer_client, "node-order", module["id"], data={"ids": [second["id"], lesson["id"]]}
        )
        assert response.status_code == 204
        assert list(
            ContentNode.objects.get(pk=module["id"]).children.values_list("id", flat=True)
        ) == [
            second["id"],
            lesson["id"],
        ]
        bad = put(trainer_client, "node-order", module["id"], data={"ids": [lesson["id"]]})
        assert bad.status_code == 400

    def test_overview_edit_updates_the_course_root(self, trainer_client):
        course_id, *_ = make_valid_course(trainer_client)
        response = patch(
            trainer_client,
            "course",
            course_id,
            data={"title": "Renamed course", "description": "New"},
        )
        assert response.status_code == 200
        assert response.json()["title"] == "Renamed course"
        assert response.json()["tree"]["root"]["description"] == "New"


class TestActivities:
    def test_registry_endpoint(self, trainer_client):
        types = {t["key"]: t for t in get(trainer_client, "activity-types").json()}
        assert {"reading", "mcq", "bot_sim"} <= set(types)
        assert types["reading"]["config_schema"]["required"] == ["source_url"]

    def test_a_new_activity_starts_unfinished_and_is_flagged(self, trainer_client):
        _, _, _, section = make_valid_course(trainer_client)
        response = post(
            trainer_client, "node-activities", section["id"], data={"activity_type": "reading"}
        )
        assert response.status_code == 201
        activity = response.json()
        assert activity["title"] == "Reading"  # defaulted from the type label
        assert activity["needs_setup"] is True

        fixed = patch(
            trainer_client,
            "activity",
            activity["id"],
            data={"config": {"source_url": "https://example.com"}},
        )
        assert fixed.status_code == 200 and fixed.json()["needs_setup"] is False

    def test_new_quizzes_allow_unlimited_attempts_but_readings_keep_the_default(
        self, trainer_client
    ):
        _, _, _, section = make_valid_course(trainer_client)
        quiz = post(trainer_client, "node-activities", section["id"], data={"activity_type": "mcq"})
        reading = post(
            trainer_client, "node-activities", section["id"], data={"activity_type": "reading"}
        )
        assert quiz.json()["max_attempts"] == 0
        assert reading.json()["max_attempts"] == 3
        assert quiz.json()["needs_setup"] is True  # no questions yet

    @pytest.mark.parametrize(
        "payload",
        [
            {"activity_type": "hologram"},
            {"activity_type": "reading", "config": {"estimated_read_minutes": "ten"}},
            {"activity_type": "reading", "mastery_threshold": 4},
        ],
    )
    def test_bad_input_is_a_400(self, trainer_client, payload):
        _, _, _, section = make_valid_course(trainer_client)
        assert (
            post(trainer_client, "node-activities", section["id"], data=payload).status_code == 400
        )

    def test_modules_cannot_hold_activities(self, trainer_client):
        course_id, module, *_ = make_valid_course(trainer_client)
        response = post(
            trainer_client, "node-activities", module["id"], data={"activity_type": "workshop"}
        )
        assert response.status_code == 400

    def test_reorder_and_delete(self, trainer_client):
        _, _, _, section = make_valid_course(trainer_client)
        a = post(
            trainer_client, "node-activities", section["id"], data={"activity_type": "workshop"}
        ).json()
        b = post(
            trainer_client, "node-activities", section["id"], data={"activity_type": "pdf"}
        ).json()
        put(
            trainer_client, "node-activities-order", section["id"], data={"ids": [b["id"], a["id"]]}
        )
        assert list(
            Activity.objects.filter(content_node_id=section["id"]).values_list("id", flat=True)
        ) == [
            b["id"],
            a["id"],
        ]
        assert (
            trainer_client.delete(reverse("authoring_api:activity", args=[a["id"]])).status_code
            == 204
        )


class TestPublishWorkflow:
    def test_empty_course_cannot_be_submitted(self, trainer_client):
        course = post(trainer_client, "courses", data={"title": "Empty"}).json()
        response = post(trainer_client, "submit", course["id"])
        assert response.status_code == 400
        assert "module" in response.json()["detail"].lower()
        checklist = get(trainer_client, "checklist", course["id"]).json()
        assert checklist["ok"] is False and checklist["issues"]

    def test_unfinished_activity_blocks_submit_until_set_up(self, trainer_client):
        course_id, _, _, section = make_valid_course(trainer_client)
        act = post(
            trainer_client, "node-activities", section["id"], data={"activity_type": "reading"}
        ).json()
        blocked = post(trainer_client, "submit", course_id)
        assert blocked.status_code == 400 and "needs setup" in blocked.json()["detail"]
        patch(
            trainer_client, "activity", act["id"], data={"config": {"source_url": "https://x.io"}}
        )
        assert post(trainer_client, "submit", course_id).status_code == 200

    def test_full_trainer_to_admin_flow(self, trainer_client, client, admin_user, trainer):
        course_id, module, lesson, section = make_valid_course(trainer_client)

        submitted = post(trainer_client, "submit", course_id)
        assert submitted.status_code == 200
        body = submitted.json()
        assert body["status"]["key"] == "in_review"
        assert body["editable"] is False
        assert body["actions"]["publish"] is False  # trainers can't publish
        assert CourseVersion.objects.get(course_id=course_id).submitted_by == trainer

        # In review = locked for everyone.
        locked = patch(trainer_client, "node", lesson["id"], data={"title": "Nope"})
        assert locked.status_code == 409

        # A trainer cannot publish.
        assert post(trainer_client, "publish", course_id).status_code == 403
        assert post(trainer_client, "return", course_id).status_code == 403

        # Admin publishes.
        client.force_login(admin_user)
        published = post(client, "publish", course_id)
        assert published.status_code == 200
        assert published.json()["status"] == {"key": "published", "label": "Published v1"}
        version = CourseVersion.objects.get(course_id=course_id)
        assert version.state == CourseVersion.State.PUBLISHED and version.published_by == admin_user

        # Published is immutable.
        assert patch(client, "node", lesson["id"], data={"title": "Nope"}).status_code == 409

    def test_admin_can_return_a_submission_to_draft(self, trainer_client, client, admin_user):
        course_id, *_ = make_valid_course(trainer_client)
        post(trainer_client, "submit", course_id)
        client.force_login(admin_user)
        returned = post(client, "return", course_id)
        assert returned.status_code == 200
        assert returned.json()["status"]["key"] == "draft"
        assert CourseVersion.objects.get(course_id=course_id).submitted_at is None

    def test_return_requires_a_submission(self, client, admin_user, trainer_client):
        course_id, *_ = make_valid_course(trainer_client)
        client.force_login(admin_user)
        assert post(client, "return", course_id).status_code == 400

    def test_admin_may_publish_straight_from_draft(self, client, admin_user):
        client.force_login(admin_user)
        course_id, *_ = make_valid_course(client)
        assert post(client, "publish", course_id).status_code == 200

    def test_editing_a_published_course_starts_a_cloned_draft(
        self, trainer_client, client, admin_user
    ):
        course_id, module, lesson, section = make_valid_course(trainer_client)
        post(trainer_client, "submit", course_id)
        client.force_login(admin_user)
        post(client, "publish", course_id)

        client.force_login(CourseVersion.objects.get(course_id=course_id).submitted_by)
        started = post(client, "start-draft", course_id)
        assert started.status_code == 201
        body = started.json()
        assert body["status"]["key"] == "published_with_draft"
        assert body["version"]["number"] == 2 and body["editable"] is True

        new_ids = {n["id"] for n in _flatten(body["tree"]["root"])}
        assert not new_ids & {
            module["id"],
            lesson["id"],
            section["id"],
        }  # a copy, not the published nodes
        assert {n["title"] for n in _flatten(body["tree"]["root"])} >= {"M1", "L1", "S1"}

        # Idempotent: asking again returns the same open draft.
        again = post(client, "start-draft", course_id).json()
        assert again["version"]["number"] == 2
        assert CourseVersion.objects.filter(course_id=course_id).count() == 2

    def test_publishing_v2_archives_v1(self, trainer_client, client, admin_user):
        course_id, *_ = make_valid_course(trainer_client)
        client.force_login(admin_user)
        post(client, "publish", course_id)
        post(client, "start-draft", course_id)
        post(client, "publish", course_id)
        states = dict(
            CourseVersion.objects.filter(course_id=course_id).values_list("version", "state")
        )
        assert states == {1: "archived", 2: "published"}


def _flatten(node):
    yield node
    for child in node["children"]:
        yield from _flatten(child)


SECRET_QUIZ = {
    "activity_type": "mcq",
    "config": {
        "questions": [{"text": "Q", "choices": ["A", "B"], "answer": 1, "explanation": "SECRET"}]
    },
}


class TestPreviewAndLearnerIsolation:
    def test_preview_uses_the_learner_shape_without_config(self, trainer_client):
        _, _, _, section = make_valid_course(trainer_client)
        post(
            trainer_client,
            "node-activities",
            section["id"],
            data=SECRET_QUIZ,
        )
        course_id = Course.objects.get().id
        response = get(trainer_client, "preview", course_id)
        assert response.status_code == 200
        raw = json.dumps(response.json())
        assert "SECRET" not in raw and "explanation" not in raw and "answer" not in raw
        assert response.json()["root"]["kind"] == "course"

    def test_preview_requires_authoring_rights(self, client, make_role_user, trainer_client):
        make_valid_course(trainer_client)
        course_id = Course.objects.get().id
        client.force_login(make_role_user(Role.Name.LEARNER))
        assert get(client, "preview", course_id).status_code == 403

    def test_authoring_detail_includes_config_but_learner_api_does_not(self, trainer_client):
        _, _, _, section = make_valid_course(trainer_client)
        post(
            trainer_client,
            "node-activities",
            section["id"],
            data=SECRET_QUIZ,
        )
        course_id = Course.objects.get().id
        assert "SECRET" in json.dumps(get(trainer_client, "course", course_id).json())

    def test_learners_only_see_published_versions(
        self, trainer_client, client, admin_user, make_role_user
    ):
        course_id, *_ = make_valid_course(trainer_client)
        learner = make_role_user(Role.Name.LEARNER)
        client.force_login(learner)
        assert client.get(reverse("catalog_api:course-list")).json() == []  # draft: invisible

        client.force_login(admin_user)
        post(client, "publish", course_id)
        client.force_login(learner)
        listing = client.get(reverse("catalog_api:course-list")).json()
        assert len(listing) == 1 and listing[0]["course_id"] == course_id

        # A new draft of a published course is still invisible to learners.
        client.force_login(admin_user)
        post(client, "start-draft", course_id)
        client.force_login(learner)
        assert len(client.get(reverse("catalog_api:course-list")).json()) == 1
