import pytest
from django.urls import reverse

from apps.catalog.models import Activity, ContentNode, Course, CourseVersion

pytestmark = pytest.mark.django_db


class TestAdminChangelistsAndAddViewsLoad:
    @pytest.mark.parametrize(
        "url_name",
        [
            "admin:catalog_contentnode_changelist",
            "admin:catalog_contentnode_add",
            "admin:catalog_courseversion_changelist",
            "admin:catalog_courseversion_add",
            "admin:accounts_user_changelist",
            "admin:accounts_role_changelist",
            "admin:accounts_role_add",
            "admin:accounts_roleassignment_changelist",
            "admin:accounts_roleassignment_add",
        ],
    )
    def test_returns_200(self, admin_client, url_name):
        response = admin_client.get(reverse(url_name))
        assert response.status_code == 200


class TestFullCourseTreeAuthoringFlow:
    """Walks course -> segment -> topic -> subtopic -> activity through the
    admin's add views, then publishes — this is the M1 "done when" bar
    (§14: "an admin can author the full 2026 course tree in the admin")
    expressed as a test.
    """

    def test_admin_can_author_and_publish_full_tree(self, admin_client):
        add_cv_url = reverse("admin:catalog_courseversion_add")
        course = Course.objects.create(slug="admin-flow-course")
        response = admin_client.post(
            add_cv_url, {"course": course.id, "version": 1, "state": CourseVersion.State.DRAFT}
        )
        assert response.status_code == 302
        cv = CourseVersion.objects.get(version=1)

        add_node_url = reverse("admin:catalog_contentnode_add")

        response = admin_client.post(
            add_node_url,
            {
                "course_version": cv.id,
                "kind": ContentNode.Kind.COURSE,
                "title": "Root Course",
                "slug": "root-course",
                "order": 0,
                "is_required": "on",
                "activities-TOTAL_FORMS": 0,
                "activities-INITIAL_FORMS": 0,
                "activities-MIN_NUM_FORMS": 0,
                "activities-MAX_NUM_FORMS": 1000,
            },
        )
        errors = response.context["adminform"].errors if response.status_code == 200 else None
        assert response.status_code == 302, errors
        course = ContentNode.objects.get(slug="root-course")

        response = admin_client.post(
            add_node_url,
            {
                "course_version": cv.id,
                "parent": course.id,
                "kind": ContentNode.Kind.SEGMENT,
                "title": "Segment 1",
                "slug": "segment-1",
                "order": 0,
                "is_required": "on",
                "activities-TOTAL_FORMS": 0,
                "activities-INITIAL_FORMS": 0,
                "activities-MIN_NUM_FORMS": 0,
                "activities-MAX_NUM_FORMS": 1000,
            },
        )
        assert response.status_code == 302
        segment = ContentNode.objects.get(slug="segment-1")

        response = admin_client.post(
            add_node_url,
            {
                "course_version": cv.id,
                "parent": segment.id,
                "kind": ContentNode.Kind.TOPIC,
                "title": "Topic 1",
                "slug": "topic-1",
                "order": 0,
                "is_required": "on",
                "activities-TOTAL_FORMS": 0,
                "activities-INITIAL_FORMS": 0,
                "activities-MIN_NUM_FORMS": 0,
                "activities-MAX_NUM_FORMS": 1000,
            },
        )
        assert response.status_code == 302
        topic = ContentNode.objects.get(slug="topic-1")

        # Subtopic + one inline Activity in the same POST.
        response = admin_client.post(
            add_node_url,
            {
                "course_version": cv.id,
                "parent": topic.id,
                "kind": ContentNode.Kind.SUBTOPIC,
                "title": "Subtopic 1",
                "slug": "subtopic-1",
                "order": 0,
                "is_required": "on",
                "activities-TOTAL_FORMS": 1,
                "activities-INITIAL_FORMS": 0,
                "activities-MIN_NUM_FORMS": 0,
                "activities-MAX_NUM_FORMS": 1000,
                "activities-0-activity_type": Activity.ActivityType.READING,
                "activities-0-title": "Read the docs",
                "activities-0-config": '{"source_url": "https://example.com"}',
                "activities-0-max_attempts": 3,
                "activities-0-points": 0,
                "activities-0-order": 0,
                "activities-0-is_required": "on",
            },
        )
        assert response.status_code == 302
        subtopic = ContentNode.objects.get(slug="subtopic-1")
        assert subtopic.activities.count() == 1
        assert subtopic.activities.first().activity_type == Activity.ActivityType.READING

        # Publish via the admin action.
        changelist_url = reverse("admin:catalog_courseversion_changelist")
        response = admin_client.post(
            changelist_url,
            {"action": "publish_selected", "_selected_action": [cv.id]},
            follow=True,
        )
        assert response.status_code == 200
        cv.refresh_from_db()
        assert cv.state == CourseVersion.State.PUBLISHED
        assert cv.published_at is not None
        assert cv.published_by is not None

        # Re-publishing the same version is rejected (no state change).
        admin_client.post(
            changelist_url,
            {"action": "publish_selected", "_selected_action": [cv.id]},
            follow=True,
        )
        cv.refresh_from_db()
        assert cv.state == CourseVersion.State.PUBLISHED  # unchanged, not errored-into a new state
