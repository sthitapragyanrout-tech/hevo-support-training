import pytest
from django.core.management import call_command

from apps.accounts.models import Role
from apps.accounts.rbac import ROLE_PERMISSIONS
from apps.catalog.models import Activity, ContentNode, Course, CourseVersion

pytestmark = pytest.mark.django_db


class TestSeedRoles:
    def test_creates_all_roles(self):
        call_command("seed_roles")
        assert Role.objects.count() == len(Role.Name.values)
        assert set(Role.objects.values_list("name", flat=True)) == set(Role.Name.values)

    def test_assigns_role_permissions(self):
        call_command("seed_roles")
        admin_role = Role.objects.get(name=Role.Name.ADMIN)
        codenames = set(admin_role.permissions.values_list("codename", flat=True))
        expected = {c.split(".", 1)[1] for c in ROLE_PERMISSIONS[Role.Name.ADMIN]}
        assert codenames == expected

    def test_idempotent(self):
        call_command("seed_roles")
        call_command("seed_roles")
        assert Role.objects.count() == len(Role.Name.values)


class TestSeedPlaceholderCourse:
    def test_creates_expected_tree(self):
        call_command("seed_placeholder_course")

        cv = CourseVersion.objects.get(version=1)
        assert cv.root_node is not None
        assert "PLACEHOLDER" in cv.root_node.title

        courses = ContentNode.objects.filter(course_version=cv, kind=ContentNode.Kind.COURSE)
        segments = ContentNode.objects.filter(course_version=cv, kind=ContentNode.Kind.SEGMENT)
        topics = ContentNode.objects.filter(course_version=cv, kind=ContentNode.Kind.TOPIC)
        subtopics = ContentNode.objects.filter(course_version=cv, kind=ContentNode.Kind.SUBTOPIC)

        assert courses.count() == 1
        assert segments.count() == 3
        assert topics.count() == 6  # 2 per segment
        assert subtopics.count() == 12  # 2 per topic
        assert Activity.objects.filter(content_node__course_version=cv).count() >= 12

    def test_running_twice_creates_a_second_course(self):
        call_command("seed_placeholder_course")
        call_command("seed_placeholder_course")
        assert Course.objects.count() == 2
        assert CourseVersion.objects.count() == 2
        # Each course starts at version 1 and has its own slug.
        assert set(CourseVersion.objects.values_list("version", flat=True)) == {1}
        assert Course.objects.values_list("slug", flat=True).distinct().count() == 2
