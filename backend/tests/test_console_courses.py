"""Admin Console → Courses: every course in every state, version history, and
archive/restore. Archiving retires a course from learners; nothing is deleted."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.catalog import services as catalog
from apps.catalog.models import Activity, Course, CourseVersion
from apps.progress.models import ActivityProgress

pytestmark = pytest.mark.django_db


def url(name, *args):
    return reverse(f"console_api:{name}", args=args)


@pytest.fixture
def people(make_role_user):
    return {
        "admin": make_role_user(Role.Name.ADMIN, username="adm", email="adm@example.com"),
        "trainer": make_role_user(Role.Name.TRAINER, username="trn", email="trn@example.com"),
        "mentor": make_role_user(Role.Name.MENTOR, username="mnt", email="mnt@example.com"),
        "learner": make_role_user(Role.Name.LEARNER, username="lrn", email="lrn@example.com"),
    }


def make_course(people, title, *, state="published", with_reading=True):
    course = catalog.create_course(title=title, user=people["trainer"])
    version = catalog.open_version(course)
    module = catalog.add_node(version.root_node, title="M")
    lesson = catalog.add_node(module, title=f"{title} lesson")
    reading = None
    if with_reading:
        reading = Activity.objects.create(
            content_node=lesson,
            activity_type="reading",
            title="Read it",
            config={"source_url": "https://x.io"},
        )
    if state == "published":
        version.publish(people["admin"])
    elif state == "in_review":
        version.state = "in_review"
        version.submitted_by = people["trainer"]
        version.save()
    return {"course": course, "version": version, "reading": reading, "lesson": lesson}


@pytest.fixture
def world(people):
    return {
        "live": make_course(people, "Live course"),
        "draft": make_course(people, "Draft course", state="draft"),
        "review": make_course(people, "Review course", state="in_review"),
    }


def as_user(client, user):
    client.force_login(user)
    return client


class TestPermissions:
    def test_anonymous_learners_and_mentors_are_refused(self, client, people, world):
        pk = world["live"]["course"].pk
        paths = [
            ("get", url("courses")),
            ("get", url("course", pk)),
            ("post", url("course-archive", pk)),
            ("post", url("course-restore", pk)),
        ]
        for who in (None, "learner", "mentor"):
            if who:
                as_user(client, people[who])
            for method, path in paths:
                assert getattr(client, method)(path).status_code == 403, (who, path)

    def test_trainers_may_look_but_not_archive(self, client, people, world):
        pk = world["live"]["course"].pk
        as_user(client, people["trainer"])
        assert client.get(url("courses")).status_code == 200
        assert client.get(url("course", pk)).json()["can_archive"] is False
        assert client.post(url("course-archive", pk)).status_code == 403
        assert Course.objects.get(pk=pk).archived_at is None

    def test_admins_may_do_everything(self, client, people, world):
        pk = world["live"]["course"].pk
        as_user(client, people["admin"])
        assert client.get(url("course", pk)).json()["can_archive"] is True
        assert client.post(url("course-archive", pk)).status_code == 200


class TestList:
    def get(self, client, people, **params):
        as_user(client, people["admin"])
        return client.get(url("courses"), params).json()

    def test_every_course_in_every_state(self, client, people, world):
        rows = {r["title"]: r for r in self.get(client, people)["results"]}
        assert rows["Live course"]["status"] == {"key": "published", "label": "Published v1"}
        assert rows["Draft course"]["status"]["key"] == "draft"
        assert rows["Review course"]["status"]["key"] == "in_review"
        live = rows["Live course"]
        assert live["created_by"] == "trn@example.com" and live["versions"] == 1
        assert live["published_version"] == 1 and live["archived_at"] is None
        assert rows["Draft course"]["published_version"] is None

    def test_search_by_title_or_slug(self, client, people, world):
        assert [r["title"] for r in self.get(client, people, search="review")["results"]] == [
            "Review course"
        ]
        assert self.get(client, people, search="live-course")["count"] == 1
        assert self.get(client, people, search="nothing")["count"] == 0

    def test_filter_by_status(self, client, people, world):
        assert [r["title"] for r in self.get(client, people, status="draft")["results"]] == [
            "Draft course"
        ]
        assert self.get(client, people, status="published")["count"] == 1

    def test_a_published_course_with_edits_in_draft_is_its_own_status(self, client, people, world):
        catalog.get_or_create_draft(world["live"]["course"])
        rows = {r["title"]: r for r in self.get(client, people)["results"]}
        status_ = rows["Live course"]["status"]
        assert status_["key"] == "published_with_draft"
        assert status_["label"] == "Published v1 · edits in draft"
        assert rows["Live course"]["versions"] == 2
        assert self.get(client, people, status="published_with_draft")["count"] == 1

    def test_archived_courses_show_as_archived(self, client, people, world):
        as_user(client, people["admin"])
        client.post(url("course-archive", world["live"]["course"].pk))
        rows = {r["title"]: r for r in self.get(client, people)["results"]}
        assert rows["Live course"]["status"] == {"key": "archived", "label": "Archived"}
        assert rows["Live course"]["archived_at"]
        assert self.get(client, people, status="archived")["count"] == 1

    def test_paging(self, client, people, world):
        body = self.get(client, people, page_size=2)
        assert (body["count"], body["pages"], len(body["results"])) == (3, 2, 2)

    def test_query_count_does_not_grow_with_courses(
        self, client, people, world, django_assert_max_num_queries
    ):
        for i in range(8):
            make_course(people, f"Extra {i}", state="draft", with_reading=False)
        as_user(client, people["admin"])
        with django_assert_max_num_queries(10):
            assert client.get(url("courses"), {"page_size": 100}).status_code == 200


class TestDetail:
    def test_shows_the_version_history_with_who_and_when(self, client, people, world):
        as_user(client, people["admin"])
        body = client.get(url("course", world["live"]["course"].pk)).json()
        assert body["title"] == "Live course" and body["slug"] == "live-course"
        (version,) = body["versions_history"]
        assert version["number"] == 1 and version["state"] == "published"
        assert version["state_label"] == "Published"
        assert version["published_by"] == "adm@example.com" and version["published_at"]
        assert (version["lessons"], version["activities"]) == (1, 1)

    def test_counts_the_learners_who_have_started_each_version(self, client, people, world):
        reading = world["live"]["reading"]
        c = Client()
        c.force_login(people["learner"])
        c.post(reverse("progress_api:activity-complete", args=[reading.pk]))
        as_user(client, people["admin"])
        (version,) = client.get(url("course", world["live"]["course"].pk)).json()[
            "versions_history"
        ]
        assert version["learners"] == 1

    def test_an_in_review_version_shows_who_submitted_it(self, client, people, world):
        as_user(client, people["admin"])
        (version,) = client.get(url("course", world["review"]["course"].pk)).json()[
            "versions_history"
        ]
        assert version["state"] == "in_review" and version["submitted_by"] == "trn@example.com"

    def test_newest_version_first_after_a_new_draft(self, client, people, world):
        course = world["live"]["course"]
        CourseVersion.objects.create(course=course, version=2)
        as_user(client, people["admin"])
        numbers = [
            v["number"] for v in client.get(url("course", course.pk)).json()["versions_history"]
        ]
        assert numbers == [2, 1]

    def test_unknown_course_is_404(self, client, people, world):
        as_user(client, people["admin"])
        assert client.get(url("course", 99999)).status_code == 404


class TestArchive:
    def archive(self, client, people, course):
        as_user(client, people["admin"])
        return client.post(url("course-archive", course.pk))

    def learner_list(self, people):
        c = Client()
        c.force_login(people["learner"])
        return c.get(reverse("catalog_api:course-list")).json()

    def test_archiving_hides_the_course_from_learners_and_logs_it(self, client, people, world):
        course = world["live"]["course"]
        assert len(self.learner_list(people)) == 1
        response = self.archive(client, people, course)
        assert response.status_code == 200 and response.json()["status"]["key"] == "archived"
        assert Course.objects.get(pk=course.pk).archived_at is not None
        assert self.learner_list(people) == []
        entry = AuditLog.objects.get(action="courses.archive")
        assert entry.target_label == "Live course" and entry.actor == people["admin"]

    def test_the_course_is_no_longer_reachable_by_direct_link(self, client, people, world):
        version = world["live"]["version"]
        self.archive(client, people, world["live"]["course"])
        c = Client()
        c.force_login(people["learner"])
        assert c.get(reverse("catalog_api:course-tree", args=[version.pk])).status_code == 404

    def test_nothing_more_is_recorded_against_it_but_history_is_kept(self, client, people, world):
        reading = world["live"]["reading"]
        c = Client()
        c.force_login(people["learner"])
        c.post(reverse("progress_api:activity-complete", args=[reading.pk]))
        self.archive(client, people, world["live"]["course"])
        again = c.post(reverse("progress_api:activity-start", args=[reading.pk]))
        assert again.status_code == 404
        assert ActivityProgress.objects.filter(activity=reading).count() == 1  # kept

    def test_studio_stops_listing_it(self, client, people, world):
        as_user(client, people["admin"])
        before = {c["title"] for c in client.get(reverse("authoring_api:courses")).json()}
        assert "Live course" in before
        self.archive(client, people, world["live"]["course"])
        after = {c["title"] for c in client.get(reverse("authoring_api:courses")).json()}
        assert "Live course" not in after

    def test_restoring_brings_it_all_back(self, client, people, world):
        course = world["live"]["course"]
        self.archive(client, people, course)
        as_user(client, people["admin"])
        response = client.post(url("course-restore", course.pk))
        assert response.json()["status"]["key"] == "published"
        assert len(self.learner_list(people)) == 1
        assert AuditLog.objects.get(action="courses.restore").target_label == "Live course"

    def test_doing_it_twice_changes_and_logs_nothing_more(self, client, people, world):
        course = world["live"]["course"]
        self.archive(client, people, course)
        self.archive(client, people, course)
        as_user(client, people["admin"])
        client.post(url("course-restore", course.pk))
        client.post(url("course-restore", course.pk))
        assert AuditLog.objects.filter(action="courses.archive").count() == 1
        assert AuditLog.objects.filter(action="courses.restore").count() == 1

    def test_unknown_course_is_404(self, client, people, world):
        as_user(client, people["admin"])
        assert client.post(url("course-archive", 99999)).status_code == 404


class TestLearningOrderShown:
    def test_the_course_page_reports_how_learners_move_through_it(self, client, people, world):
        as_user(client, people["admin"])
        pk = world["live"]["course"].pk
        assert client.get(url("course", pk)).json()["learning_order"] == "free"
        CourseVersion.objects.filter(course_id=pk).update(learning_order="sequential")
        assert client.get(url("course", pk)).json()["learning_order"] == "sequential"
