import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import Activity, ContentNode, Course, CourseVersion

pytestmark = pytest.mark.django_db


def make_course_version(version=1):
    course = Course.objects.create(slug=f"course-{Course.objects.count() + 1}")
    return CourseVersion.objects.create(course=course, version=version)


def make_node(course_version, kind, parent=None, slug=None, title=None):
    title = title or kind
    slug = slug or f"{kind}-{parent_id(parent)}"
    return ContentNode(
        course_version=course_version,
        kind=kind,
        parent=parent,
        title=title,
        slug=slug,
    )


def parent_id(parent):
    return parent.id if parent else "root"


class TestContentNodeParentKind:
    @pytest.mark.parametrize(
        "kind,parent_kind",
        [
            (ContentNode.Kind.COURSE, None),
            (ContentNode.Kind.SEGMENT, ContentNode.Kind.COURSE),
            (ContentNode.Kind.TOPIC, ContentNode.Kind.SEGMENT),
            (ContentNode.Kind.SUBTOPIC, ContentNode.Kind.TOPIC),
        ],
    )
    def test_allowed_parent_kind_passes(self, kind, parent_kind):
        cv = make_course_version()
        parent = None
        if parent_kind is not None:
            parent = ContentNode.objects.create(
                course_version=cv, kind=parent_kind, title="parent", slug="parent"
            )
        node = make_node(cv, kind, parent=parent)
        node.full_clean()  # must not raise

    @pytest.mark.parametrize(
        "kind,bad_parent_kind",
        [
            (ContentNode.Kind.COURSE, ContentNode.Kind.COURSE),  # course must be root
            (ContentNode.Kind.SEGMENT, ContentNode.Kind.SEGMENT),
            (ContentNode.Kind.SEGMENT, ContentNode.Kind.TOPIC),
            (ContentNode.Kind.TOPIC, ContentNode.Kind.COURSE),
            (ContentNode.Kind.SUBTOPIC, ContentNode.Kind.SEGMENT),
        ],
    )
    def test_disallowed_parent_kind_raises(self, kind, bad_parent_kind):
        cv = make_course_version()
        bad_parent = ContentNode.objects.create(
            course_version=cv, kind=bad_parent_kind, title="bad-parent", slug="bad-parent"
        )
        node = make_node(cv, kind, parent=bad_parent)
        with pytest.raises(ValidationError):
            node.full_clean()

    def test_segment_with_no_parent_raises(self):
        cv = make_course_version()
        node = make_node(cv, ContentNode.Kind.SEGMENT, parent=None)
        with pytest.raises(ValidationError):
            node.full_clean()

    def test_course_with_parent_raises(self):
        cv = make_course_version()
        other_course = ContentNode.objects.create(
            course_version=cv, kind=ContentNode.Kind.COURSE, title="other", slug="other"
        )
        node = make_node(cv, ContentNode.Kind.COURSE, parent=other_course)
        with pytest.raises(ValidationError):
            node.full_clean()


class TestCourseVersionPublish:
    def _make_root(self, cv):
        root = ContentNode.objects.create(
            course_version=cv, kind=ContentNode.Kind.COURSE, title="root", slug="root"
        )
        cv.root_node = root
        cv.save(update_fields=["root_node"])
        return root

    def test_publish_sets_state_and_metadata(self, django_user_model):
        cv = make_course_version()
        self._make_root(cv)
        user = django_user_model.objects.create_user(username="admin1", email="admin1@example.com")

        cv.publish(user)

        cv.refresh_from_db()
        assert cv.state == CourseVersion.State.PUBLISHED
        assert cv.published_at is not None
        assert cv.published_by_id == user.id

    def test_double_publish_rejected(self, django_user_model):
        cv = make_course_version()
        self._make_root(cv)
        user = django_user_model.objects.create_user(username="admin2", email="admin2@example.com")
        cv.publish(user)

        with pytest.raises(ValidationError):
            cv.publish(user)


class TestActivityConfigValidation:
    def _make_activity(self, activity_type, config):
        cv = make_course_version()
        root = ContentNode.objects.create(
            course_version=cv, kind=ContentNode.Kind.COURSE, title="root", slug="root"
        )
        segment = ContentNode.objects.create(
            course_version=cv, kind=ContentNode.Kind.SEGMENT, parent=root, title="seg", slug="seg"
        )
        topic = ContentNode.objects.create(
            course_version=cv, kind=ContentNode.Kind.TOPIC, parent=segment, title="top", slug="top"
        )
        subtopic = ContentNode.objects.create(
            course_version=cv, kind=ContentNode.Kind.SUBTOPIC, parent=topic, title="sub", slug="sub"
        )
        return Activity(
            content_node=subtopic, activity_type=activity_type, title="a", config=config
        )

    @pytest.mark.parametrize(
        "activity_type,config",
        [
            (Activity.ActivityType.READING, {"source_url": "https://example.com/doc"}),
            (Activity.ActivityType.VIDEO, {"video_asset_ref": "asset-1"}),
            (
                Activity.ActivityType.MCQ,
                {"questions": [{"text": "q1", "choices": ["a", "b"], "answer": 0}]},
            ),
            (
                Activity.ActivityType.EXTERNAL_COURSE,
                {"provider_name": "Scaler", "course_url": "https://scaler.example/course"},
            ),
        ],
    )
    def test_valid_config_passes(self, activity_type, config):
        activity = self._make_activity(activity_type, config)
        activity.full_clean()  # must not raise

    @pytest.mark.parametrize(
        "activity_type,config",
        [
            (Activity.ActivityType.READING, {}),  # missing required source_url
            (Activity.ActivityType.VIDEO, {}),  # missing required video_asset_ref
            (Activity.ActivityType.MCQ, {"questions": []}),  # violates minItems
            # missing course_url
            (Activity.ActivityType.EXTERNAL_COURSE, {"provider_name": "Scaler"}),
        ],
    )
    def test_invalid_config_raises(self, activity_type, config):
        activity = self._make_activity(activity_type, config)
        with pytest.raises(ValidationError):
            activity.full_clean()

    def test_unvalidated_activity_type_skips_schema(self):
        # workshop/manual_sim/bot_sim have no schema in M1 — any config passes.
        activity = self._make_activity(Activity.ActivityType.WORKSHOP, {"anything": "goes"})
        activity.full_clean()  # must not raise
