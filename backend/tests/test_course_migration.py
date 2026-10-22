"""The 0002 migration must wrap every pre-existing CourseVersion in its own
Course without losing anything, and be reversible."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [("catalog", "0001_initial")]
AFTER = [("catalog", "0002_course_and_review_state")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture(autouse=True)
def restore_latest_schema():
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def test_existing_versions_each_get_a_course():
    old_apps = _migrate(BEFORE)
    Version = old_apps.get_model("catalog", "CourseVersion")
    Node = old_apps.get_model("catalog", "ContentNode")

    titles = ["CX Onboarding 2026", "CX Onboarding 2026", ""]
    for i, title in enumerate(titles, start=1):
        version = Version.objects.create(version=i, state="published" if i == 1 else "draft")
        if title:
            root = Node.objects.create(
                course_version=version, kind="course", title=title, slug="root"
            )
            version.root_node = root
            version.save()

    new_apps = _migrate(AFTER)
    Course = new_apps.get_model("catalog", "Course")
    Version = new_apps.get_model("catalog", "CourseVersion")

    assert Course.objects.count() == 3
    assert Version.objects.count() == 3
    assert all(v.course_id for v in Version.objects.all())

    # Slugs come from root titles, are de-duplicated, and have a fallback.
    slugs = sorted(Course.objects.values_list("slug", flat=True))
    assert slugs[0].startswith("course-")  # the version with no root node
    assert "cx-onboarding-2026" in slugs and "cx-onboarding-2026-2" in slugs

    # Versions keep their numbers and state.
    assert sorted(Version.objects.values_list("version", "state")) == [
        (1, "published"),
        (2, "draft"),
        (3, "draft"),
    ]


def test_migration_is_reversible():
    _migrate(AFTER)
    old_apps = _migrate(BEFORE)
    assert old_apps.get_model("catalog", "CourseVersion")
