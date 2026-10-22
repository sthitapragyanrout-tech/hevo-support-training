import pytest
from django.db import IntegrityError, transaction

from apps.catalog import services
from apps.catalog.models import Activity, ContentNode, Course, CourseVersion

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="trainer1", email="trainer1@example.com", password="x"
    )


@pytest.fixture
def course(user):
    return services.create_course(title="CX Onboarding 2026", description="Intro", user=user)


def draft_of(course: Course) -> CourseVersion:
    version = services.open_version(course)
    assert version is not None
    return version


class TestCreateCourse:
    def test_creates_course_draft_v1_and_root(self, course, user):
        version = draft_of(course)
        assert course.created_by == user
        assert course.slug == "cx-onboarding-2026"
        assert version.version == 1
        assert version.state == CourseVersion.State.DRAFT
        assert version.root_node.kind == ContentNode.Kind.COURSE
        assert version.root_node.title == "CX Onboarding 2026"
        assert course.title == "CX Onboarding 2026"

    def test_slug_is_unique_across_courses(self, course, user):
        other = services.create_course(title="CX Onboarding 2026", user=user)
        assert other.slug == "cx-onboarding-2026-2"

    def test_blank_title_rejected(self, user):
        with pytest.raises(services.InvalidOperation):
            services.create_course(title="   ", user=user)


class TestAddNode:
    def test_kind_slug_order_and_version_come_from_context(self, course):
        root = draft_of(course).root_node

        module = services.add_node(root, title="Product Fundamentals")
        lesson = services.add_node(module, title="Pipeline Concepts")
        section = services.add_node(lesson, title="Sources & Destinations")

        assert (module.kind, lesson.kind, section.kind) == ("segment", "topic", "subtopic")
        assert module.course_version_id == root.course_version_id
        assert module.slug == "product-fundamentals"
        assert section.slug == "sources-destinations"
        assert module.order == 0

    def test_order_appends_and_slugs_stay_unique_among_siblings(self, course):
        root = draft_of(course).root_node
        a = services.add_node(root, title="Basics")
        b = services.add_node(root, title="Basics")
        c = services.add_node(root, title="Other")
        assert (a.order, b.order, c.order) == (0, 1, 2)
        assert (a.slug, b.slug) == ("basics", "basics-2")

    def test_section_cannot_have_children(self, course):
        root = draft_of(course).root_node
        section = services.add_node(
            services.add_node(services.add_node(root, title="M"), title="L"), title="S"
        )
        with pytest.raises(services.InvalidOperation):
            services.add_node(section, title="Too deep")

    def test_blank_title_rejected(self, course):
        with pytest.raises(services.InvalidOperation):
            services.add_node(draft_of(course).root_node, title="")


class TestUpdateAndDelete:
    def test_update_changes_fields_but_not_slug(self, course):
        module = services.add_node(draft_of(course).root_node, title="Old name")
        services.update_node(module, title="New name", estimated_minutes=30)
        module.refresh_from_db()
        assert (module.title, module.slug, module.estimated_minutes) == ("New name", "old-name", 30)

    def test_update_rejects_structural_fields(self, course):
        module = services.add_node(draft_of(course).root_node, title="M")
        with pytest.raises(services.InvalidOperation):
            services.update_node(module, kind="topic")

    def test_delete_reports_impact_and_closes_order_gap(self, course):
        root = draft_of(course).root_node
        m1 = services.add_node(root, title="One")
        m2 = services.add_node(root, title="Two")
        lesson = services.add_node(m1, title="L")
        section = services.add_node(lesson, title="S")
        Activity.objects.create(content_node=section, activity_type="workshop", title="Do it")

        assert services.node_impact(m1) == {"lessons": 1, "sections": 1, "activities": 1}

        services.delete_node(m1)
        m2.refresh_from_db()
        assert m2.order == 0
        assert not ContentNode.objects.filter(pk=lesson.pk).exists()

    def test_root_cannot_be_deleted(self, course):
        with pytest.raises(services.InvalidOperation):
            services.delete_node(draft_of(course).root_node)


class TestReorder:
    def test_reorders_siblings(self, course):
        root = draft_of(course).root_node
        a, b, c = (services.add_node(root, title=t) for t in "ABC")
        services.reorder_children(root, [c.id, a.id, b.id])
        assert list(root.children.values_list("title", flat=True)) == ["C", "A", "B"]

    @pytest.mark.parametrize(
        "make_ids", [lambda ids: ids[:-1], lambda ids: ids + [999999], lambda ids: ids + ids[:1]]
    )
    def test_rejects_partial_foreign_or_duplicate_ids(self, course, make_ids):
        root = draft_of(course).root_node
        ids = [services.add_node(root, title=t).id for t in "ABC"]
        with pytest.raises(services.InvalidOperation):
            services.reorder_children(root, make_ids(ids))


class TestLocking:
    @pytest.mark.parametrize(
        "state",
        [
            CourseVersion.State.PUBLISHED,
            CourseVersion.State.IN_REVIEW,
            CourseVersion.State.ARCHIVED,
        ],
    )
    def test_only_a_draft_is_editable(self, course, state):
        version = draft_of(course)
        module = services.add_node(version.root_node, title="M")
        CourseVersion.objects.filter(pk=version.pk).update(state=state)
        module.course_version.refresh_from_db()

        with pytest.raises(services.NotEditable):
            services.add_node(version.root_node, title="Nope")
        with pytest.raises(services.NotEditable):
            services.update_node(module, title="Nope")
        with pytest.raises(services.NotEditable):
            services.delete_node(module)
        with pytest.raises(services.NotEditable):
            services.reorder_children(version.root_node, [module.id])


class TestOneOpenVersionPerCourse:
    def test_database_rejects_a_second_open_version(self, course):
        with pytest.raises(IntegrityError), transaction.atomic():
            CourseVersion.objects.create(course=course, version=2)  # draft #2

    def test_in_review_also_counts_as_open(self, course):
        CourseVersion.objects.filter(pk=draft_of(course).pk).update(
            state=CourseVersion.State.IN_REVIEW
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            CourseVersion.objects.create(course=course, version=2)

    def test_version_numbers_are_unique_per_course(self, course):
        CourseVersion.objects.filter(pk=draft_of(course).pk).update(
            state=CourseVersion.State.PUBLISHED
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            CourseVersion.objects.create(course=course, version=1)

    def test_different_courses_may_both_have_drafts(self, course, user):
        other = services.create_course(title="Other", user=user)
        assert draft_of(other).version == 1


class TestPublishAndDraftCloning:
    def _build_published(self, course, user):
        version = draft_of(course)
        module = services.add_node(version.root_node, title="Module")
        lesson = services.add_node(module, title="Lesson", description="Hello")
        section = services.add_node(lesson, title="Section", estimated_minutes=12)
        Activity.objects.create(
            content_node=section,
            activity_type="reading",
            title="Read",
            config={"source_url": "https://example.com", "nested": {"a": [1, 2]}},
            points=5,
        )
        version.publish(user)
        return version

    def test_publish_archives_the_previous_published_version(self, course, user):
        v1 = self._build_published(course, user)
        v2 = services.get_or_create_draft(course)
        v2.publish(user)
        v1.refresh_from_db()
        assert v1.state == CourseVersion.State.ARCHIVED
        assert v2.state == CourseVersion.State.PUBLISHED

    def test_get_or_create_draft_clones_the_published_tree(self, course, user):
        v1 = self._build_published(course, user)

        v2 = services.get_or_create_draft(course)

        assert v2.pk != v1.pk
        assert (v2.version, v2.state) == (2, CourseVersion.State.DRAFT)
        assert v2.root_node_id != v1.root_node_id

        def shape(version):
            return [
                (n.kind, n.title, n.slug, n.order, n.description, n.estimated_minutes)
                for n in version.nodes.order_by("kind", "order", "title")
            ]

        assert shape(v2) == shape(v1)
        assert not set(v2.nodes.values_list("id", flat=True)) & set(
            v1.nodes.values_list("id", flat=True)
        )
        # Parent links point inside the new version only.
        for node in v2.nodes.exclude(parent=None):
            assert node.parent.course_version_id == v2.id

    def test_clone_copies_activities_with_independent_config(self, course, user):
        v1 = self._build_published(course, user)
        v2 = services.get_or_create_draft(course)

        old = Activity.objects.get(content_node__course_version=v1)
        new = Activity.objects.get(content_node__course_version=v2)
        assert (new.title, new.points, new.config) == (old.title, old.points, old.config)

        new.config["nested"]["a"].append(3)
        new.save()
        old.refresh_from_db()
        assert old.config["nested"]["a"] == [1, 2]  # source untouched

    def test_editing_the_new_draft_never_changes_the_published_version(self, course, user):
        v1 = self._build_published(course, user)
        v2 = services.get_or_create_draft(course)
        services.add_node(v2.root_node, title="Added only in v2")
        assert v1.nodes.count() == 3 + 1  # root + module + lesson + section
        assert v2.nodes.count() == v1.nodes.count() + 1
        fresh_root = ContentNode.objects.get(pk=v1.root_node_id)  # not a cached stale copy
        with pytest.raises(services.NotEditable):
            services.add_node(fresh_root, title="Nope")

    def test_get_or_create_draft_returns_the_existing_open_version(self, course):
        assert services.get_or_create_draft(course).pk == draft_of(course).pk

    def test_status_reflects_versions(self, course, user):
        assert services.course_status(course).key == "draft"
        self._build_published(course, user)
        assert services.course_status(course).key == "published"
        services.get_or_create_draft(course)
        status = services.course_status(course)
        assert status.key == "published_with_draft"
        assert status.label == "Published v1 · edits in draft"
