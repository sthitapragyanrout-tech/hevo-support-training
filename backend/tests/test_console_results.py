"""Admin Console → learner results: who did what with which scores, the CSV,
and the (audited) attempt reset. Every endpoint is permission-checked."""

import csv
import io
import json

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.catalog import services as catalog
from apps.catalog.models import Activity, CourseVersion
from apps.progress.models import ActivityAttempt, ActivityProgress, LessonCompletion

pytestmark = pytest.mark.django_db

QUESTIONS = [
    {"text": "One", "choices": ["A", "B"], "answer": 0},
    {"text": "Two", "choices": ["X", "Y"], "answer": 1},
]
RIGHT = [[0], [1]]
WRONG = [[1], [0]]


def build_course(author, admin, title, *, quiz_title="Quiz", attempts=2):
    course = catalog.create_course(title=title, user=author)
    version = catalog.open_version(course)
    module = catalog.add_node(version.root_node, title="M")
    lesson = catalog.add_node(module, title=f"{title} lesson")
    reading = Activity.objects.create(
        content_node=lesson,
        activity_type="reading",
        title="Read it",
        config={"source_url": "https://x.io"},
    )
    quiz = Activity.objects.create(
        content_node=lesson,
        activity_type="mcq",
        title=quiz_title,
        config={"questions": QUESTIONS, "pass_threshold": 1},
        max_attempts=attempts,
    )
    version.publish(admin)
    return {
        "course": course,
        "version": version,
        "lesson": lesson,
        "reading": reading,
        "quiz": quiz,
    }


@pytest.fixture
def people(make_role_user):
    return {
        "admin": make_role_user(Role.Name.ADMIN, username="adm", email="adm@example.com"),
        "trainer": make_role_user(Role.Name.TRAINER, username="trn", email="trn@example.com"),
        "mentor": make_role_user(Role.Name.MENTOR, username="mnt", email="mnt@example.com"),
        "ann": make_role_user(
            Role.Name.LEARNER,
            username="ann",
            email="ann@example.com",
            first_name="Ann",
            last_name="Ames",
        ),
        "bob": make_role_user(Role.Name.LEARNER, username="bob", email="bob@example.com"),
        "cy": make_role_user(Role.Name.LEARNER, username="cy", email="cy@example.com"),
    }


@pytest.fixture
def world(people):
    """Ann passes on try 2; Bob fails every try (exhausted); Cy only reads."""
    a = build_course(people["trainer"], people["admin"], "Alpha")
    b = build_course(people["trainer"], people["admin"], "Beta", quiz_title="Beta quiz")
    from django.test import Client

    def submit(user, activity, answers):
        client = Client()
        client.force_login(user)
        return client.post(
            reverse("progress_api:activity-attempts", args=[activity.id]),
            data=json.dumps({"answers": answers}),
            content_type="application/json",
        )

    submit(people["ann"], a["quiz"], WRONG)
    submit(people["ann"], a["quiz"], RIGHT)
    submit(people["bob"], a["quiz"], WRONG)
    submit(people["bob"], a["quiz"], WRONG)
    submit(people["ann"], b["quiz"], RIGHT)
    cy = Client()
    cy.force_login(people["cy"])
    cy.post(reverse("progress_api:activity-complete", args=[a["reading"].id]))
    return {"alpha": a, "beta": b}


def as_user(client, user):
    client.force_login(user)
    return client


def url(name, *args):
    return reverse(f"console_api:{name}", args=args)


class TestPermissions:
    @pytest.fixture
    def endpoints(self, people, world):
        ann, quiz = people["ann"].pk, world["alpha"]["quiz"].pk
        return [
            ("get", url("result-courses")),
            ("get", url("learners")),
            ("get", url("learner", ann)),
            ("get", url("quizzes")),
            ("get", url("quiz", quiz)),
            ("get", url("results-export")),
        ]

    def test_anonymous_is_refused_everywhere(self, client, endpoints, people, world):
        for method, path in endpoints:
            assert getattr(client, method)(path).status_code == 403, path
        reset = url("reset-attempts", people["ann"].pk, world["alpha"]["quiz"].pk)
        assert client.delete(reset).status_code == 403

    @pytest.mark.parametrize("who", ["ann", "mentor"])
    def test_learners_and_mentors_see_nothing(self, client, endpoints, people, world, who):
        as_user(client, people[who])
        for method, path in endpoints:
            assert getattr(client, method)(path).status_code == 403, path
        reset = url("reset-attempts", people["ann"].pk, world["alpha"]["quiz"].pk)
        assert client.delete(reset).status_code == 403
        assert ActivityAttempt.objects.filter(user=people["ann"]).count() == 3

    @pytest.mark.parametrize("who", ["trainer", "admin"])
    def test_trainers_and_admins_may_read(self, client, endpoints, people, who):
        as_user(client, people[who])
        for method, path in endpoints:
            assert getattr(client, method)(path).status_code == 200, path


class TestLearnerList:
    def get(self, client, people, **params):
        as_user(client, people["trainer"])
        return client.get(url("learners"), params).json()

    def test_lists_learners_with_what_they_have_done(self, client, people, world):
        body = self.get(client, people)
        rows = {r["email"]: r for r in body["results"]}
        assert set(rows) == {"ann@example.com", "bob@example.com", "cy@example.com"}
        assert rows["ann@example.com"]["name"] == "Ann Ames"
        assert rows["ann@example.com"]["quiz_attempts"] == 3
        assert rows["bob@example.com"]["quiz_attempts"] == 2
        assert rows["cy@example.com"]["quiz_attempts"] == 0
        assert rows["ann@example.com"]["last_activity"]
        assert body["count"] == 3 and body["page"] == 1

    def test_staff_who_never_did_anything_are_not_listed(self, client, people, world):
        emails = {r["email"] for r in self.get(client, people)["results"]}
        assert not emails & {"adm@example.com", "trn@example.com"}

    def test_a_staff_member_who_tried_a_quiz_appears(self, client, people, world):
        from django.test import Client

        other = Client()
        other.force_login(people["trainer"])
        other.post(
            reverse("progress_api:activity-attempts", args=[world["alpha"]["quiz"].id]),
            data=json.dumps({"answers": RIGHT}),
            content_type="application/json",
        )
        emails = {r["email"] for r in self.get(client, people)["results"]}
        assert "trn@example.com" in emails

    def test_search_matches_name_email_and_username(self, client, people, world):
        assert [r["email"] for r in self.get(client, people, search="ames")["results"]] == [
            "ann@example.com"
        ]
        assert self.get(client, people, search="bob")["count"] == 1
        assert self.get(client, people, search="nobody")["count"] == 0

    def test_filtering_by_course_scopes_who_and_the_counts(self, client, people, world):
        beta = world["beta"]["course"].pk
        body = self.get(client, people, course=beta)
        assert [r["email"] for r in body["results"]] == ["ann@example.com"]
        assert body["results"][0]["quiz_attempts"] == 1  # only her Beta try

    def test_ordering_and_paging(self, client, people, world):
        body = self.get(client, people, ordering="-attempts", page_size=2)
        assert [r["email"] for r in body["results"]] == ["ann@example.com", "bob@example.com"]
        assert (body["count"], body["pages"], body["page_size"]) == (3, 2, 2)
        page2 = self.get(client, people, ordering="-attempts", page_size=2, page=2)
        assert [r["email"] for r in page2["results"]] == ["cy@example.com"]

    def test_bad_paging_values_fall_back_safely(self, client, people, world):
        body = self.get(client, people, page="x", page_size="9999", course="abc")
        assert body["page"] == 1 and body["page_size"] == 100 and body["count"] == 3

    def test_query_count_does_not_grow_with_learners(
        self, client, people, world, make_role_user, django_assert_max_num_queries
    ):
        for i in range(10):
            make_role_user(Role.Name.LEARNER, username=f"x{i}", email=f"x{i}@example.com")
        as_user(client, people["trainer"])
        with django_assert_max_num_queries(12):
            assert client.get(url("learners"), {"page_size": 100}).status_code == 200


class TestLearnerDetail:
    def get(self, client, people, who):
        as_user(client, people["trainer"])
        return client.get(url("learner", people[who].pk)).json()

    def test_shows_each_course_with_lessons_and_quiz_attempts(self, client, people, world):
        body = self.get(client, people, "ann")
        assert body["name"] == "Ann Ames"
        courses = {c["title"]: c for c in body["courses"]}
        assert set(courses) == {"Alpha", "Beta"}
        alpha = courses["Alpha"]
        assert (alpha["lessons_total"], alpha["lessons_completed"]) == (1, 0)
        quiz = next(a for a in alpha["activities"] if a["type"] == "mcq")
        assert quiz["state"] == "completed" and quiz["scored"] is True
        assert [a["score"] for a in quiz["attempts"]] == [0.0, 1.0]
        assert quiz["best_score"] == 1.0
        assert quiz["attempts"][0]["submitted_at"]
        assert quiz["max_attempts"] == 2 and quiz["lesson"] == "Alpha lesson"

    def test_an_exhausted_quiz_is_visible_as_not_passed(self, client, people, world):
        quiz = next(
            a
            for a in self.get(client, people, "bob")["courses"][0]["activities"]
            if a["type"] == "mcq"
        )
        assert quiz["state"] == "exhausted" and quiz["best_score"] == 0.0
        assert len(quiz["attempts"]) == 2

    def test_untouched_activities_read_not_started(self, client, people, world):
        reading = next(
            a
            for a in self.get(client, people, "bob")["courses"][0]["activities"]
            if a["type"] == "reading"
        )
        assert reading["state"] == "not_started" and reading["attempts"] == []

    def test_a_learner_with_no_activity_has_no_courses(self, client, people, world):
        as_user(client, people["trainer"])
        assert client.get(url("learner", people["admin"].pk)).json()["courses"] == []

    def test_unknown_learner_is_404(self, client, people):
        as_user(client, people["trainer"])
        assert client.get(url("learner", 99999)).status_code == 404


class TestQuizResults:
    def test_summarises_how_learners_did_per_quiz(self, client, people, world):
        as_user(client, people["trainer"])
        rows = {r["title"]: r for r in client.get(url("quizzes")).json()["results"]}
        alpha = rows["Quiz"]
        assert (alpha["learners"], alpha["passed"], alpha["not_passed"], alpha["in_progress"]) == (
            2,
            1,
            1,
            0,
        )
        assert alpha["average_best_score"] == pytest.approx(0.5)
        assert alpha["course"] == "Alpha" and alpha["lesson"] == "Alpha lesson"
        assert rows["Beta quiz"]["learners"] == 1

    def test_filter_by_course(self, client, people, world):
        as_user(client, people["trainer"])
        body = client.get(url("quizzes"), {"course": world["beta"]["course"].pk}).json()
        assert [r["title"] for r in body["results"]] == ["Beta quiz"]

    def test_draft_versions_are_not_listed(self, client, people, world):
        CourseVersion.objects.filter(pk=world["beta"]["version"].pk).update(state="draft")
        as_user(client, people["trainer"])
        titles = [r["title"] for r in client.get(url("quizzes")).json()["results"]]
        assert titles == ["Quiz"]

    def test_detail_lists_each_learner_with_state_and_scores(self, client, people, world):
        as_user(client, people["trainer"])
        body = client.get(url("quiz", world["alpha"]["quiz"].pk)).json()
        rows = {r["email"]: r for r in body["learners"]}
        assert set(rows) == {"ann@example.com", "bob@example.com"}
        assert rows["ann@example.com"]["state"] == "completed"
        assert (rows["ann@example.com"]["attempts"], rows["ann@example.com"]["best_score"]) == (
            2,
            1.0,
        )
        assert rows["bob@example.com"]["state"] == "exhausted"
        assert rows["bob@example.com"]["last_attempt_at"]

    def test_detail_404s_for_a_reading(self, client, people, world):
        as_user(client, people["trainer"])
        assert client.get(url("quiz", world["alpha"]["reading"].pk)).status_code == 404


class TestResetAttempts:
    def reset(self, client, learner, activity):
        return client.delete(url("reset-attempts", learner.pk, activity.pk))

    def test_a_trainer_can_reset_a_learner_and_it_is_audited(self, client, people, world):
        as_user(client, people["trainer"])
        quiz = world["alpha"]["quiz"]
        LessonCompletion.objects.create(
            user=people["bob"], node=world["alpha"]["lesson"], completed_at=timezone.now()
        )
        assert self.reset(client, people["bob"], quiz).status_code == 204

        assert not ActivityAttempt.objects.filter(user=people["bob"], activity=quiz).exists()
        assert not ActivityProgress.objects.filter(user=people["bob"], activity=quiz).exists()
        assert not LessonCompletion.objects.filter(user=people["bob"]).exists()  # reopened
        assert ActivityAttempt.objects.filter(user=people["ann"], activity=quiz).count() == 2

        entry = AuditLog.objects.get(action="results.reset_attempts")
        assert entry.actor == people["trainer"] and entry.target_id == str(quiz.pk)
        assert "bob@example.com" in entry.target_label
        assert entry.changes == {
            "learner": "bob@example.com",
            "attempts_deleted": 2,
            "previous_state": "exhausted",
        }

    def test_it_works_even_where_the_learner_self_reset_is_off(
        self, client, people, world, settings
    ):
        settings.ALLOW_ATTEMPT_RESET = False
        as_user(client, people["admin"])
        assert self.reset(client, people["ann"], world["alpha"]["quiz"]).status_code == 204

    def test_the_learner_can_then_try_again(self, client, people, world):
        as_user(client, people["trainer"])
        self.reset(client, people["bob"], world["alpha"]["quiz"])
        from django.test import Client

        bob = Client()
        bob.force_login(people["bob"])
        response = bob.post(
            reverse("progress_api:activity-attempts", args=[world["alpha"]["quiz"].pk]),
            data=json.dumps({"answers": RIGHT}),
            content_type="application/json",
        )
        assert response.status_code == 201 and response.json()["passed"] is True

    def test_unknown_learner_or_activity_is_404_and_nothing_is_logged(self, client, people, world):
        as_user(client, people["trainer"])
        assert (
            client.delete(url("reset-attempts", 99999, world["alpha"]["quiz"].pk)).status_code
            == 404
        )
        assert client.delete(url("reset-attempts", people["bob"].pk, 99999)).status_code == 404
        assert not AuditLog.objects.exists()

    def test_a_reading_has_no_attempts_to_reset(self, client, people, world):
        as_user(client, people["trainer"])
        response = self.reset(client, people["bob"], world["alpha"]["reading"])
        assert response.status_code == 400 and response.json()["detail"]
        assert not AuditLog.objects.exists()


class TestExport:
    def rows(self, client, **params):
        response = client.get(url("results-export"), params)
        assert response["Content-Type"].startswith("text/csv")
        assert "attachment" in response["Content-Disposition"]
        return list(csv.reader(io.StringIO(b"".join(response.streaming_content).decode())))

    def test_one_row_per_attempt_with_a_header(self, client, people, world):
        as_user(client, people["trainer"])
        rows = self.rows(client)
        assert rows[0][:2] == ["Learner email", "Learner name"]
        assert len(rows) == 1 + 5  # ann (Alpha 2, Beta 1) + bob (Alpha 2)
        ann = [r for r in rows[1:] if r[0] == "ann@example.com" and r[3] == "Alpha"]
        assert [(r[6], r[7], r[8]) for r in ann] == [
            ("1", "0", "Not passed"),
            ("2", "100", "Passed"),
        ]

    def test_filter_by_course(self, client, people, world):
        as_user(client, people["trainer"])
        rows = self.rows(client, course=world["beta"]["course"].pk)
        assert len(rows) == 2 and rows[1][3] == "Beta"

    def test_an_export_is_logged(self, client, people, world):
        as_user(client, people["trainer"])
        self.rows(client)
        entry = AuditLog.objects.get(action="results.export")
        assert entry.actor == people["trainer"] and entry.changes == {"rows": 5}


class TestCourseOptions:
    def test_lists_courses_with_a_published_version(self, client, people, world):
        as_user(client, people["trainer"])
        titles = [c["title"] for c in client.get(url("result-courses")).json()["results"]]
        assert titles == ["Alpha", "Beta"]
