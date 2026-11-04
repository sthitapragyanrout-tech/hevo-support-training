"""Where mentor-rated work shows up beside everything else: the learner's own course summary,
the trainer's learner page, the CSV — and that quizzes and practice tickets are unaffected."""

import csv
import io

import pytest
from django.urls import reverse

from apps.manual_sim import files, services
from apps.manual_sim.models import SimCase, SimSubmission, SubmissionFile
from apps.progress import reporting
from apps.progress import services as progress
from tests.manual_sim_helpers import FAIL, PASS, at, people, png, rated_course

pytestmark = pytest.mark.django_db

ANSWER = "My reply."


@pytest.fixture
def world(make_role_user, media_dirs):
    return {**rated_course(make_role_user), **people(make_role_user)}


def hand_in(world, now=None, who="learner"):
    return services.submit(world[who], world["activity"].pk, ANSWER, now=now or at())


class TestTheLearnersCourseSummary:
    def test_nothing_until_they_have_opened_it(self, world):
        assert progress.course_progress(world["learner"], world["version"].pk)["rated"] == {}

    def test_the_status_is_small_and_has_no_internals(self, world):
        sub = hand_in(world)
        summary = progress.course_progress(world["learner"], world["version"].pk)["rated"]
        entry = summary[world["activity"].pk]
        assert entry == {
            "status": "waiting",
            "revisions": 1,
            "due_at": entry["due_at"],
            "overdue": False,
            "last_score": None,
            "holds_next": "submit",
        }
        services.rate(world["mentor"], sub.pk, FAIL, {}, "No.", now=at(hours=1))
        again = progress.course_progress(world["learner"], world["version"].pk)["rated"]
        assert again[world["activity"].pk]["status"] == "changes_requested"
        assert again[world["activity"].pk]["last_score"] == 2.5

    def test_overdue_is_computed_from_the_clock(self, world):
        case = services.open_case(world["learner"], world["activity"].pk, now=at())
        from apps.manual_sim import reporting as manual

        assert (
            manual.course_summaries(world["learner"], world["version"], now=at(days=6))[
                world["activity"].pk
            ]["overdue"]
            is False
        )
        assert (
            manual.course_summaries(world["learner"], world["version"], now=at(days=8))[
                world["activity"].pk
            ]["overdue"]
            is True
        )
        assert SimCase.objects.get(pk=case.pk).due_at == at(days=7)  # reading never changed it


class TestTheTrainersLearnerPage:
    def entry(self, world):
        detail = reporting.learner_detail(world["learner"])
        activities = [
            a for c in detail["courses"] for a in c["activities"] if a["type"] == "manual_sim"
        ]
        assert len(activities) == 1
        return activities[0]

    def test_it_shows_the_whole_picture_a_trainer_needs(self, world):
        for n in range(3):
            sub = hand_in(world, at(days=n))
            services.rate(world["mentor"], sub.pk, FAIL, {}, "No.", now=at(days=n, hours=1))
        activity = self.entry(world)
        assert activity["scored"] is False and activity["attempts"] == []  # not a quiz
        rated = activity["rated"]
        assert (
            rated["status"],
            rated["revisions"],
            rated["unsuccessful"],
            rated["needs_attention"],
        ) == (
            "changes_requested",
            3,
            3,
            True,
        )
        assert rated["case_id"] == SimCase.objects.get().pk and rated["waiting"] is None

    def test_a_waiting_review_and_a_closing_note_are_there(self, world):
        sub = hand_in(world)
        assert self.entry(world)["rated"]["waiting"]["id"] == sub.pk
        services.close(
            world["trainer"], SimCase.objects.get().pk, "Left the company", now=at(days=1)
        )
        rated = self.entry(world)["rated"]
        assert rated["status"] == "not_passed" and rated["close_note"] == "Left the company"
        assert rated["closed_reason"] == "not_passed"

    def test_other_kinds_of_activity_carry_no_rated_block(self, world):
        detail = reporting.learner_detail(world["learner"])
        hand_in(world)
        detail = reporting.learner_detail(world["learner"])
        others = [
            a for c in detail["courses"] for a in c["activities"] if a["type"] != "manual_sim"
        ]
        assert all(a["rated"] is None for a in others)


class TestQuizAndPracticeReportsAreUnaffected:
    def test_a_rated_attempt_is_not_a_quiz_attempt(self, world):
        sub = hand_in(world)
        services.rate(world["mentor"], sub.pk, PASS, {}, "Good.", now=at(hours=1))
        assert reporting.quiz_rows() == []  # nothing here is a quiz
        entry = reporting.learner_detail(world["learner"])["courses"][0]
        mine = next(a for a in entry["activities"] if a["type"] == "manual_sim")
        assert mine["best_score"] is None and mine["max_attempts"] == 0

    def test_the_export_row(self, world):
        sub = hand_in(world)
        services.rate(world["mentor"], sub.pk, PASS, {}, "Good.", now=at(hours=1))
        (row,) = list(reporting.export_rows())
        assert row[6] == 1  # attempt number
        assert row[7] == ""  # no percent
        assert row[8] == "Passed" and row[10] == "Mentor-rated" and row[11] == 4.5

    def test_the_console_export_still_has_the_same_columns(self, client, world):
        sub = hand_in(world)
        services.rate(world["mentor"], sub.pk, FAIL, {}, "No.", now=at(hours=1))
        client.force_login(world["trainer"])
        response = client.get(reverse("console_api:results-export"))
        table = list(csv.reader(io.StringIO(b"".join(response.streaming_content).decode())))
        assert table[0][-2:] == ["Type", "Score out of 5"] and len(table[1]) == len(table[0])
        assert table[1][-2:] == ["Mentor-rated", "2.5"]


class TestFileCleanup:
    def test_deleting_a_submission_deletes_its_files(self, world):
        sub = services.submit(
            world["learner"], world["activity"].pk, ANSWER, uploads=[png()], now=at()
        )
        path = files.path_of(sub.files.get())
        assert path.is_file()
        SimSubmission.objects.filter(pk=sub.pk).delete()
        assert not path.exists() and SubmissionFile.objects.count() == 0

    def test_deleting_the_learner_deletes_their_files(self, world):
        sub = services.submit(
            world["learner"], world["activity"].pk, ANSWER, uploads=[png()], now=at()
        )
        path = files.path_of(sub.files.get())
        world["learner"].delete()
        assert not path.exists()

    def test_the_sweep_removes_only_unreferenced_old_files(self, world, settings):
        import os

        from django.core.management import call_command

        sub = services.submit(
            world["learner"], world["activity"].pk, ANSWER, uploads=[png()], now=at()
        )
        kept = files.path_of(sub.files.get())
        stray = kept.with_name("11111111-1111-1111-1111-111111111111.png")
        stray.write_bytes(b"x")
        fresh = kept.with_name("22222222-2222-2222-2222-222222222222.png")
        fresh.write_bytes(b"x")
        old = os.stat(stray).st_mtime - 10_000
        os.utime(stray, (old, old))
        call_command("purge_orphan_attachments", "--dry-run")
        assert stray.exists()  # dry run changes nothing
        call_command("purge_orphan_attachments")
        assert not stray.exists() and kept.exists() and fresh.exists()


class TestTheCourseViewStaysAFixedNumberOfQueries:
    def count(self, world):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            progress.course_progress(world["learner"], world["version"].pk)
        return len(ctx)

    def test_more_cases_cost_no_more_queries(self, world):
        from apps.catalog.models import Activity
        from tests.manual_sim_helpers import good_config

        empty = self.count(world)
        services.open_case(world["learner"], world["activity"].pk, now=at())
        one = self.count(world)
        for n in range(4):
            extra = Activity.objects.create(
                content_node=world["second"],
                activity_type="manual_sim",
                title=f"More {n}",
                config=good_config(),
                max_attempts=0,
            )
            services.open_case(world["learner"], extra.pk, now=at())
        many = self.count(world)
        assert one == many and one <= empty + 3
