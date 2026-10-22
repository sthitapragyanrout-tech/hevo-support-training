import json

import pytest
from django.urls import reverse

from apps.catalog.models import Activity, ContentNode, Course, CourseVersion

pytestmark = pytest.mark.django_db


def _build_course(state=CourseVersion.State.PUBLISHED, version=1, title="Course A"):
    course = Course.objects.create(slug=f"course-{Course.objects.count() + 1}")
    cv = CourseVersion.objects.create(course=course, version=version, state=state)
    course = ContentNode.objects.create(
        course_version=cv, kind="course", title=title, slug=f"course-{version}-{state}"
    )
    cv.root_node = course
    cv.save(update_fields=["root_node"])
    return cv, course


@pytest.fixture
def learner(django_user_model):
    return django_user_model.objects.create_user(
        username="learner1", email="learner1@example.com", password="testpass123"
    )


@pytest.fixture
def auth_client(client, learner):
    client.force_login(learner)
    return client


class TestAuthRequired:
    def test_list_requires_login(self, client):
        assert client.get(reverse("catalog_api:course-list")).status_code == 403

    def test_tree_requires_login(self, client):
        cv, _ = _build_course()
        assert client.get(reverse("catalog_api:course-tree", args=[cv.pk])).status_code == 403


class TestCourseList:
    def test_only_published_versions_listed(self, auth_client):
        published, _ = _build_course(CourseVersion.State.PUBLISHED, version=1, title="Live")
        _build_course(CourseVersion.State.DRAFT, version=2, title="Draft")
        _build_course(CourseVersion.State.ARCHIVED, version=3, title="Old")

        response = auth_client.get(reverse("catalog_api:course-list"))

        assert response.status_code == 200
        body = response.json()
        assert [c["id"] for c in body] == [published.id]
        assert body[0]["title"] == "Live"

    def test_version_without_root_node_hidden(self, auth_client):
        course = Course.objects.create(slug="no-root")
        CourseVersion.objects.create(course=course, version=1, state=CourseVersion.State.PUBLISHED)
        response = auth_client.get(reverse("catalog_api:course-list"))
        assert response.json() == []


class TestCourseTree:
    def _build_full_tree(self):
        cv, course = _build_course()
        segment = ContentNode.objects.create(
            course_version=cv, parent=course, kind="segment", title="Seg", slug="seg"
        )
        topic = ContentNode.objects.create(
            course_version=cv, parent=segment, kind="topic", title="Topic", slug="topic"
        )
        # Created out of order on purpose: `order` must win over insertion order.
        second = ContentNode.objects.create(
            course_version=cv, parent=topic, kind="subtopic", title="Second", slug="b", order=1
        )
        first = ContentNode.objects.create(
            course_version=cv, parent=topic, kind="subtopic", title="First", slug="a", order=0
        )
        Activity.objects.create(
            content_node=first,
            activity_type="mcq",
            title="Quiz",
            config={
                "questions": [
                    {
                        "text": "Q",
                        "choices": ["A", "B"],
                        "answer": 1,
                        "explanation": "SECRET-ANSWER-KEY",
                    }
                ]
            },
        )
        return cv, first, second

    def test_nesting_and_sibling_order(self, auth_client):
        cv, first, second = self._build_full_tree()

        response = auth_client.get(reverse("catalog_api:course-tree", args=[cv.pk]))

        assert response.status_code == 200
        root = response.json()["root"]
        assert root["kind"] == "course"
        topic = root["children"][0]["children"][0]
        assert topic["kind"] == "topic"
        assert [c["id"] for c in topic["children"]] == [first.id, second.id]

    def test_activities_attached_to_correct_node(self, auth_client):
        cv, first, second = self._build_full_tree()
        root = auth_client.get(reverse("catalog_api:course-tree", args=[cv.pk])).json()["root"]
        subtopics = root["children"][0]["children"][0]["children"]
        assert [a["title"] for a in subtopics[0]["activities"]] == ["Quiz"]
        assert subtopics[1]["activities"] == []

    def test_config_never_exposed(self, auth_client):
        cv, _, _ = self._build_full_tree()
        response = auth_client.get(reverse("catalog_api:course-tree", args=[cv.pk]))
        raw = json.dumps(response.json())
        assert "SECRET-ANSWER-KEY" not in raw
        assert '"answer"' not in raw and '"explanation"' not in raw
        # A quiz's questions and choices are visible; its key is not.
        quiz = [a for n in _walk(response.json()["root"]) for a in n["activities"]][0]
        assert quiz["config"]["questions"] == [
            {"text": "Q", "choices": ["A", "B"], "multiple": False}
        ]

    def test_draft_version_is_404(self, auth_client):
        cv, _ = _build_course(CourseVersion.State.DRAFT)
        assert auth_client.get(reverse("catalog_api:course-tree", args=[cv.pk])).status_code == 404

    def test_unknown_version_is_404(self, auth_client):
        assert auth_client.get(reverse("catalog_api:course-tree", args=[9999])).status_code == 404

    def test_query_count_does_not_grow_with_nodes(self, auth_client, django_assert_max_num_queries):
        cv, course = _build_course()
        for i in range(15):
            node = ContentNode.objects.create(
                course_version=cv, parent=course, kind="segment", title=f"S{i}", slug=f"s{i}"
            )
            Activity.objects.create(content_node=node, activity_type="reading", title="R")

        # session + user lookup + version + nodes + activities prefetch
        with django_assert_max_num_queries(6):
            response = auth_client.get(reverse("catalog_api:course-tree", args=[cv.pk]))
        assert response.status_code == 200


def _walk(node):
    yield node
    for child in node["children"]:
        yield from _walk(child)
