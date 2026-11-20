"""The admin Dashboard: one row per active enrollment with progress, quiz score, course score,
group and certificate; sorting, filtering, the CSV, who may see it, and the learner page behind
each row."""

import csv
import io
import json

import pytest
from django.urls import reverse

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.catalog import services as catalog
from apps.catalog.models import Activity
from apps.certification.models import CertificatePolicy
from apps.enrollment import services as enrollment
from apps.enrollment.models import Program
from apps.progress import services as progress
from tests.test_certificates import answers, quiz_config

pytestmark = [pytest.mark.django_db, pytest.mark.real_enrollment]


@pytest.fixture
def world(make_role_user):
    author = make_role_user(Role.Name.TRAINER, username="tom", email="tom@e.com")
    admin = make_role_user(Role.Name.ADMIN, username="ada", email="ada@e.com")
    course = catalog.create_course(title="Support basics", user=author)
    v = catalog.open_version(course)
    module = catalog.add_node(v.root_node, title="Module")
    one = catalog.add_node(module, title="One")
    two = catalog.add_node(module, title="Two")
    q1 = Activity.objects.create(
        content_node=one, activity_type="mcq", title="Quiz one", config=quiz_config(5)
    )
    reading = Activity.objects.create(
        content_node=two,
        activity_type="reading",
        title="Read",
        config={"source_url": "https://x.io"},
    )
    v.publish(admin)
    l1 = Program.objects.create(name="L1")
    l1.items.create(course=course)
    people = {}
    for username, first, emp in (("ann", "Ann", "E1"), ("bob", "Bob", "E2"), ("cy", "Cy", None)):
        user = make_role_user(
            Role.Name.LEARNER, username=username, email=f"{username}@e.com", first_name=first
        )
        user.employee_id = emp
        user.save()
        people[username] = user
    enrollment.enroll(people["ann"], course, program=l1)
    enrollment.enroll(people["bob"], course)
    enrollment.enroll(people["cy"], course)
    # Ann: both lessons done, quiz 100%. Bob: first lesson, quiz 40%. Cy: nothing yet.
    progress.submit_attempt(people["ann"], q1.pk, answers(5, 5))
    progress.complete_lesson(people["ann"], one.pk)
    progress.complete_activity(people["ann"], reading.pk)
    progress.complete_lesson(people["ann"], two.pk)
    progress.submit_attempt(people["bob"], q1.pk, answers(5, 2))
    progress.complete_lesson(people["bob"], one.pk)
    return {"admin": admin, "author": author, "course": course, "l1": l1, **people}


def get(client, user, **params):
    client.force_login(user)
    return client.get(reverse("console_api:dashboard"), params)


def names(body):
    return [r["name"] for r in body["results"]]


class TestRows:
    def test_one_row_per_enrollment_with_everything_the_list_shows(self, client, world):
        body = get(client, world["admin"]).json()
        assert names(body) == ["Ann", "Bob", "Cy"]
        ann = body["results"][0]
        assert ann["employee_id"] == "E1" and ann["email"] == "ann@e.com"
        assert ann["course"]["title"] == "Support basics" and ann["group"]["name"] == "L1"
        assert (ann["lessons_done"], ann["lessons_total"], ann["progress"]) == (2, 2, 1.0)
        assert ann["quiz_score"] == 1.0 and ann["last_activity"] is not None
        assert ann["certificate_on"] is False and ann["course_score"] is None
        cy = body["results"][2]
        assert cy["quiz_score"] is None and cy["progress"] == 0.0 and cy["group"] is None
        assert body["totals"] == {"learners": 3, "enrollments": 3, "certificates": 0, "courses": 1}
        assert body["groups"] == [{"id": world["l1"].pk, "name": "L1"}]

    def test_withdrawn_people_are_not_listed(self, client, world):
        enrollment.withdraw(world["bob"].enrollments.get(), "left")
        assert names(get(client, world["admin"]).json()) == ["Ann", "Cy"]

    def test_the_course_score_appears_once_a_certificate_is_switched_on(self, client, world):
        CertificatePolicy.objects.create(course=world["course"], enabled=True, threshold=70)
        rows = {r["name"]: r for r in get(client, world["admin"]).json()["results"]}
        assert rows["Ann"]["course_score"] == 1.0 and rows["Bob"]["course_score"] == 0.4
        assert rows["Ann"]["threshold"] == 70


class TestSortingAndFilters:
    @pytest.mark.parametrize(
        "ordering,expected",
        [
            ("progress", ["Cy", "Bob", "Ann"]),
            ("-progress", ["Ann", "Bob", "Cy"]),
            ("quiz", ["Bob", "Ann", "Cy"]),  # no quiz yet always sorts last
            ("-quiz", ["Ann", "Bob", "Cy"]),
            ("-name", ["Cy", "Bob", "Ann"]),
            ("emp", ["Ann", "Bob", "Cy"]),
            ("nonsense", ["Ann", "Bob", "Cy"]),
        ],
    )
    def test_sorting(self, client, world, ordering, expected):
        assert names(get(client, world["admin"], ordering=ordering).json()) == expected

    def test_search_by_name_email_or_employee_id(self, client, world):
        assert names(get(client, world["admin"], search="E2").json()) == ["Bob"]
        assert names(get(client, world["admin"], search="cy@").json()) == ["Cy"]

    def test_filter_by_group_or_no_group(self, client, world):
        assert names(get(client, world["admin"], group=world["l1"].pk).json()) == ["Ann"]
        assert names(get(client, world["admin"], group="none").json()) == ["Bob", "Cy"]

    def test_filter_by_course(self, client, make_role_user, world):
        other = catalog.create_course(title="Other", user=world["author"])
        assert names(get(client, world["admin"], course=other.pk).json()) == []
        assert len(names(get(client, world["admin"], course=world["course"].pk).json())) == 3

    def test_filter_by_certificate(self, client, world, django_capture_on_commit_callbacks):
        from apps.certification import services as certs

        with django_capture_on_commit_callbacks(execute=True):
            certs.set_policy(world["course"], {"enabled": True, "threshold": 90})
        assert names(get(client, world["admin"], certified="yes").json()) == ["Ann"]
        assert names(get(client, world["admin"], certified="no").json()) == ["Bob", "Cy"]
        body = get(client, world["admin"]).json()
        assert body["totals"]["certificates"] == 1
        assert body["results"][0]["certificate"]["code"]


class TestTheCsv:
    def test_same_rows_as_a_download_and_it_is_logged(self, client, world):
        response = get(client, world["admin"], export="csv", ordering="-progress")
        text = b"".join(response.streaming_content).decode()
        lines = list(csv.reader(io.StringIO(text)))
        assert lines[0][:4] == ["Name", "Email", "Employee id", "Course"]
        assert [line[0] for line in lines[1:]] == ["Ann", "Bob", "Cy"]
        assert lines[1][7] == "100.0" and lines[1][4] == "L1"
        assert AuditLog.objects.filter(action="results.dashboard_export").count() == 1


class TestWhoMaySeeIt:
    def test_learners_and_mentors_are_refused(self, client, make_role_user, world):
        mentor = make_role_user(Role.Name.MENTOR, username="mia", email="mia@e.com")
        for who in (world["ann"], mentor):
            assert get(client, who).status_code == 403

    def test_signed_out_is_refused(self, client):
        assert client.get(reverse("console_api:dashboard")).status_code in (401, 403)


class TestTheLearnerPage:
    def detail(self, client, world, who):
        client.force_login(world["admin"])
        return client.get(reverse("console_api:learner", args=(world[who].pk,))).json()

    def test_each_enrolled_course_with_modules_scores_and_group(self, client, world):
        body = self.detail(client, world, "ann")
        (course,) = body["enrolled"]
        assert course["title"] == "Support basics" and course["group"]["name"] == "L1"
        assert course["quiz_score"] == 1.0 and course["version"] == 1
        assert [m["state"] for m in course["modules"]] == ["done"]
        # The detailed activity list for the same version is still there, matched by version.
        assert any(c["version_id"] == course["version_id"] for c in body["courses"])
        # Each activity names its lesson, so the page can file it under the module index.
        (detail,) = [c for c in body["courses"] if c["version_id"] == course["version_id"]]
        lessons = {x["id"] for m in course["modules"] for x in m["lessons"]}
        assert {a["lesson_id"] for a in detail["activities"]} <= lessons
        assert [x["state"] for x in course["modules"][0]["lessons"]] == ["done", "done"]

    def test_staff_see_the_mentor_score_and_the_breakdown(self, client, world):
        CertificatePolicy.objects.create(course=world["course"], enabled=True)
        (course,) = self.detail(client, world, "bob")["enrolled"]
        assert "parts" in course["certification"]
        assert course["certification"]["parts"]["quiz"]["average"] == 0.4

    def test_a_withdrawn_course_is_not_among_the_current_ones(self, client, world):
        enrollment.withdraw(world["bob"].enrollments.get(), "left")
        assert self.detail(client, world, "bob")["enrolled"] == []


def test_too_many_rows_asks_for_a_filter(client, world, monkeypatch):
    from apps.progress import dashboard

    monkeypatch.setattr(dashboard, "MAX_ROWS", 2)
    response = get(client, world["admin"])
    assert response.status_code == 400 and "Choose a course or a group" in response.json()["detail"]


def test_json_is_serialisable(client, world):
    json.dumps(get(client, world["admin"]).json())
