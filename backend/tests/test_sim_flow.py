"""A practice ticket end to end through the API, with every guard on the way."""

import json
import uuid
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.bot_sim import services
from apps.bot_sim.models import LLMCall, SimSession, SimTurn
from apps.catalog import services as catalog
from apps.progress.models import ActivityAttempt, ActivityProgress
from tests.sim_helpers import GOOD, approved_scenarios, play, post_json, sim_course, u

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean(media_dirs):
    cache.clear()


@pytest.fixture
def commits(django_capture_on_commit_callbacks):
    return lambda: django_capture_on_commit_callbacks(execute=True)


@pytest.fixture
def world(make_role_user):
    built = sim_course(make_role_user)
    approved_scenarios(4)
    return built


@pytest.fixture
def learner(make_role_user):
    return make_role_user(Role.Name.LEARNER, username="lena", email="lena@e.com")


@pytest.fixture
def lc(client, learner):
    client.force_login(learner)
    return client


class TestAFullTicket:
    def test_three_replies_a_close_and_a_result(self, lc, learner, world, commits):
        payload = play(
            lc,
            world["activity"],
            [GOOD, GOOD + " Anything else?", GOOD + " Happy to help!"],
            run_commits=commits,
        )
        assert payload["state"] == "finished" and payload["exchanges"] == 3
        result = payload["result"]
        assert result["score"]["max"] == 5 and 3.5 <= result["score"]["raw"] <= 5
        assert result["passed"] is True
        assert [m["key"] for m in result["metrics"]] == [
            "communication", "empathy", "tat", "concreteness", "accuracy", "reference_docs",
        ]  # fmt: skip
        # the learner never sees the trainer-only review flags
        assert "needs_review" not in result and "review_reasons" not in result
        # …nor which kind of customer it was (found by attacking the API in the browser)
        assert "scenario_ref" not in result
        assert not any(w in json.dumps(payload) for w in ("persona", "personality", "doc_hints"))

        session = SimSession.objects.get()
        attempt = ActivityAttempt.objects.get()
        assert session.attempt == attempt
        assert (attempt.score, attempt.passed, attempt.number) == (
            result["score"]["scaled"],
            True,
            1,
        )
        assert (
            ActivityProgress.objects.get(user=learner, activity=world["activity"]).state
            == "completed"
        )

    def test_passing_lets_the_lesson_be_completed(self, lc, world, commits):
        lesson = world["second"]
        assert lc.post(reverse("progress_api:lesson-complete", args=[lesson.pk])).status_code == 409
        play(lc, world["activity"], [GOOD] * 3, run_commits=commits)
        assert lc.post(reverse("progress_api:lesson-complete", args=[lesson.pk])).status_code == 200

    def test_the_thread_shows_both_sides_and_hides_scores_until_the_end(self, lc, world, commits):
        with commits():
            sid = post_json(lc, u("start", world["activity"].pk)).json()["id"]
        with commits():
            post_json(lc, u("message", sid), {"text": GOOD, "client_id": str(uuid.uuid4())})
        payload = lc.get(u("session", sid)).json()
        assert [t["role"] for t in payload["thread"]] == ["customer", "intern", "customer"]
        assert payload["can_reply"] and not payload["waiting_for_customer"]
        assert payload["result"] is None
        text = str(payload)
        assert "scores" not in text and "persona" not in text and "personality" not in text

    def test_a_failed_pass_uses_up_tries_and_finishes_the_activity(
        self, lc, learner, make_role_user, commits
    ):
        built = sim_course(
            make_role_user, max_attempts=1, config={"pass_threshold": 1.0}, title="Strict"
        )
        approved_scenarios(2)
        payload = play(lc, built["activity"], [GOOD] * 3, run_commits=commits)
        assert payload["result"]["passed"] is False
        assert payload["result"]["attempts_left"] == 0
        assert (
            ActivityProgress.objects.get(user=learner, activity=built["activity"]).state
            == "exhausted"
        )
        # an exhausted activity no longer blocks the lesson, and cannot be started again
        assert (
            lc.post(reverse("progress_api:lesson-complete", args=[built["second"].pk])).status_code
            == 200
        )
        assert post_json(lc, u("start", built["activity"].pk)).status_code == 409


class TestStartAndResume:
    def test_start_is_201_then_resumes_with_200(self, lc, world, commits):
        first = post_json(lc, u("start", world["activity"].pk))
        again = post_json(lc, u("start", world["activity"].pk))
        assert (first.status_code, again.status_code) == (201, 200)
        assert first.json()["id"] == again.json()["id"]
        assert SimSession.objects.count() == 1

    def test_the_opening_message_is_the_scenarios(self, lc, world):
        payload = post_json(lc, u("start", world["activity"].pk)).json()
        session = SimSession.objects.get()
        assert payload["thread"][0]["text"] == session.scenario.opening_message
        assert payload["subject"] == session.scenario.issue_summary
        assert payload["can_reply"] and payload["max_exchanges"] == 6

    def test_a_passed_activity_cannot_be_started_again(self, lc, world, commits):
        play(lc, world["activity"], [GOOD] * 3, run_commits=commits)
        response = post_json(lc, u("start", world["activity"].pk))
        assert response.status_code == 409 and "already passed" in response.json()["detail"]

    def test_the_daily_limit(self, lc, learner, world, settings):
        settings.SIMBOT_DAILY_SESSIONS_PER_USER = 2
        for _ in range(2):
            sid = post_json(lc, u("start", world["activity"].pk)).json()["id"]
            services.abandon(sid, "test")
        response = post_json(lc, u("start", world["activity"].pk))
        assert response.status_code == 429 and "today’s limit" in response.json()["detail"]


class TestGuards:
    def test_anonymous(self, client, world):
        assert client.post(u("start", world["activity"].pk)).status_code == 403

    def test_unknown_unpublished_and_wrong_type(self, lc, make_role_user, world):
        assert post_json(lc, u("start", 987654)).status_code == 404
        draft = sim_course(make_role_user, publish=False, title="Draft")
        assert post_json(lc, u("start", draft["activity"].pk)).status_code == 404
        reading = world["first"].activities.get()
        assert post_json(lc, u("start", reading.pk)).status_code == 409

    def test_a_locked_lesson_cannot_be_started(self, lc, make_role_user, commits):
        built = sim_course(make_role_user, order="sequential", title="Seq")
        approved_scenarios(2)
        response = post_json(lc, u("start", built["activity"].pk))
        assert response.status_code == 409 and "Finish “First” first" in response.json()["detail"]
        assert not SimSession.objects.exists()

    def test_an_archived_course_stops_new_sessions(self, lc, world):
        catalog.archive_course(world["course"])
        assert post_json(lc, u("start", world["activity"].pk)).status_code == 404

    def test_the_generic_complete_endpoints_refuse_it(self, lc, world):
        complete = reverse("progress_api:activity-complete", args=[world["activity"].pk])
        response = lc.post(complete)
        assert response.status_code == 400 and "practice ticket" in response.json()["detail"]
        assert lc.delete(complete).status_code == 400
        assert not ActivityProgress.objects.filter(state="completed").exists()

    def test_other_learners_cannot_see_or_touch_a_session(
        self, client, lc, world, make_role_user, commits
    ):
        sid = post_json(lc, u("start", world["activity"].pk)).json()["id"]
        other = make_role_user(Role.Name.LEARNER, username="o", email="o@e.com")
        client.force_login(other)
        for method, name in [
            ("get", "session"),
            ("get", "result"),
            ("post", "finish"),
            ("post", "retry"),
        ]:
            assert getattr(client, method)(u(name, sid)).status_code == 404, name
        assert (
            post_json(
                client, u("message", sid), {"text": "hi", "client_id": str(uuid.uuid4())}
            ).status_code
            == 404
        )

    def test_a_trainer_is_not_given_access_to_a_learners_live_session_either(
        self, client, lc, world, make_role_user
    ):
        sid = post_json(lc, u("start", world["activity"].pk)).json()["id"]
        client.force_login(world["author"])
        assert client.get(u("session", sid)).status_code == 404


class TestReplying:
    @pytest.fixture
    def sid(self, lc, world):
        return post_json(lc, u("start", world["activity"].pk)).json()["id"]

    def send(self, lc, sid, text=GOOD, client_id=None):
        return post_json(
            lc, u("message", sid), {"text": text, "client_id": str(client_id or uuid.uuid4())}
        )

    @pytest.mark.parametrize("text", ["", "   ", None, 5, ["x"]])
    def test_nothing_to_send(self, lc, sid, text):
        assert (
            post_json(
                lc, u("message", sid), {"text": text, "client_id": str(uuid.uuid4())}
            ).status_code
            == 400
        )

    def test_too_long(self, lc, sid, settings):
        response = self.send(lc, sid, "x" * (settings.SIMBOT_MAX_REPLY_CHARS + 1))
        assert response.status_code == 400 and "too long" in response.json()["detail"]
        assert SimTurn.objects.filter(role="intern").count() == 0

    def test_a_bad_client_id(self, lc, sid):
        assert (
            post_json(lc, u("message", sid), {"text": "hi there", "client_id": "nope"}).status_code
            == 400
        )

    def test_a_repeat_of_the_same_message_is_one_message(self, lc, sid, commits):
        cid = uuid.uuid4()
        with commits():
            first = self.send(lc, sid, client_id=cid)
        again = self.send(lc, sid, client_id=cid)
        assert (first.status_code, again.status_code) == (202, 200)
        assert SimTurn.objects.filter(role="intern").count() == 1
        assert SimTurn.objects.filter(role="customer").count() == 2  # opening + one answer

    def test_cannot_send_again_before_the_customer_answers(self, lc, sid):
        self.send(lc, sid)  # not processed: the worker hasn't run
        response = self.send(lc, sid)
        assert response.status_code == 409 and "hasn’t replied" in response.json()["detail"]
        assert lc.get(u("session", sid)).json()["waiting_for_customer"] is True

    def test_after_the_ticket_ends_nothing_more_is_accepted(self, lc, sid, commits):
        with commits():
            post_json(lc, u("finish", sid))
        response = self.send(lc, sid)
        assert response.status_code == 409 and "has ended" in response.json()["detail"]

    def test_the_reply_is_rate_limited(self, lc, sid):
        codes = [self.send(lc, sid).status_code for _ in range(25)]
        assert 429 in codes


class TestFinishingEarly:
    def test_with_nothing_sent_it_is_abandoned_and_costs_no_attempt(self, lc, world):
        sid = post_json(lc, u("start", world["activity"].pk)).json()["id"]
        payload = post_json(lc, u("finish", sid)).json()
        assert payload["state"] == "abandoned"
        assert not ActivityAttempt.objects.exists()
        # and the learner can simply start again
        assert post_json(lc, u("start", world["activity"].pk)).status_code == 201

    def test_one_reply_is_too_little_to_score(self, lc, world, commits):
        payload = play(lc, world["activity"], [GOOD], run_commits=commits, finish=True)
        assert payload["state"] == "abandoned" and payload["abandoned_reason"] == "too_short"
        assert not ActivityAttempt.objects.exists()
        assert ActivityProgress.objects.get().state == "started"

    def test_two_replies_then_finish_scores_what_was_said(self, lc, world, commits):
        payload = play(lc, world["activity"], [GOOD, GOOD], run_commits=commits, finish=True)
        assert payload["state"] == "finished" and payload["result"]["exchanges"] == 2

    def test_finish_is_repeatable(self, lc, world, commits):
        play(lc, world["activity"], [GOOD, GOOD], run_commits=commits, finish=True)
        sid = SimSession.objects.get().pk
        assert post_json(lc, u("finish", sid)).status_code == 202
        assert ActivityAttempt.objects.count() == 1


class TestIdleRules:
    def test_a_nudge_after_enough_silence_shows_on_the_next_look(self, lc, world):
        sid = post_json(lc, u("start", world["activity"].pk)).json()["id"]
        SimTurn.objects.filter(session_id=sid).update(at=timezone.now() - timedelta(minutes=11))
        thread = lc.get(u("session", sid)).json()["thread"]
        assert [t["kind"] for t in thread] == ["message", "nudge"]
        assert len(lc.get(u("session", sid)).json()["thread"]) == 2  # not nudged twice

    def test_a_nudge_does_not_restart_the_turnaround_clock(self, lc, world, commits):
        sid = post_json(lc, u("start", world["activity"].pk)).json()["id"]
        long_ago = timezone.now() - timedelta(minutes=40)
        SimTurn.objects.filter(session_id=sid).update(at=long_ago)
        lc.get(u("session", sid))  # nudge appears now
        SimSession.objects.filter(pk=sid).update(started_at=long_ago)
        with commits():
            post_json(lc, u("message", sid), {"text": GOOD, "client_id": str(uuid.uuid4())})
        reply = SimTurn.objects.get(session_id=sid, role="intern")
        assert reply.tat_seconds >= 40 * 60 - 5  # measured from the question, not the nudge
        assert reply.scores["tat"] == 1

    def test_a_session_that_runs_too_long_is_closed_and_scored(self, lc, world, commits):
        with commits():
            sid = post_json(lc, u("start", world["activity"].pk)).json()["id"]
        for _ in range(2):
            with commits():
                post_json(lc, u("message", sid), {"text": GOOD, "client_id": str(uuid.uuid4())})
        SimSession.objects.filter(pk=sid).update(started_at=timezone.now() - timedelta(minutes=91))
        with commits():
            payload = lc.get(u("session", sid)).json()
        assert payload["thread"][-1]["kind"] == "close"
        assert lc.get(u("session", sid)).json()["state"] == "finished"

    def test_a_silent_session_that_expires_is_abandoned_not_scored_zero(self, lc, world):
        sid = post_json(lc, u("start", world["activity"].pk)).json()["id"]
        SimSession.objects.filter(pk=sid).update(started_at=timezone.now() - timedelta(minutes=91))
        payload = lc.get(u("session", sid)).json()
        assert payload["state"] == "abandoned" and payload["abandoned_reason"] == "timed_out"
        assert not ActivityAttempt.objects.exists()


class TestFailuresAreSurvivable:
    def test_a_failed_reply_can_be_retried_by_the_learner(
        self, lc, world, commits, settings, tmp_path, monkeypatch
    ):
        import json

        control = tmp_path / "control.json"
        control.write_text(json.dumps({"fail_tasks": ["customer"]}))
        monkeypatch.setenv("SIMBOT_FAKE_CONTROL", str(control))
        with commits():
            sid = post_json(lc, u("start", world["activity"].pk)).json()["id"]
        with commits():
            post_json(lc, u("message", sid), {"text": GOOD, "client_id": str(uuid.uuid4())})
        payload = lc.get(u("session", sid)).json()
        assert payload["failed"] and "couldn’t reply" in payload["failed_message"]
        assert payload["thread"][-1]["status"] == "failed"
        assert "scripted" not in str(payload)  # nothing from the model layer leaks out

        control.write_text("{}")  # the provider recovers
        with commits():
            retry = post_json(lc, u("retry", sid))
        assert retry.status_code == 200
        payload = lc.get(u("session", sid)).json()
        assert not payload["failed"] and payload["can_reply"]
        assert SimTurn.objects.filter(session_id=sid, role="customer").count() == 2

    def test_every_model_call_is_recorded(self, lc, world, commits):
        play(lc, world["activity"], [GOOD] * 3, run_commits=commits)
        tasks = set(LLMCall.objects.values_list("task", flat=True))
        assert tasks == {"evaluate", "customer", "narrative"}
        assert not LLMCall.objects.exclude(status="ok").exists()
        assert SimSession.objects.get().tokens_used > 0


class TestScenarioCountEndpoint:
    def test_authors_see_the_count_learners_do_not(self, client, world, learner):
        client.force_login(world["author"])
        body = client.get(reverse("sim_api:scenario-count") + "?persona=urgent").json()
        assert body["count"] == len(
            [
                1
                for s in __import__(
                    "apps.bot_sim.models", fromlist=["Scenario"]
                ).Scenario.objects.filter(persona_type="urgent", status="approved")
            ]
        )
        client.force_login(learner)
        assert client.get(reverse("sim_api:scenario-count")).status_code == 403

    def test_preview_needs_the_authoring_permission(self, client, world, learner):
        client.force_login(learner)
        assert post_json(client, u("preview", world["activity"].pk)).status_code == 403
        client.force_login(world["author"])
        response = post_json(client, u("preview", world["activity"].pk))
        assert response.status_code == 201 and response.json()["preview"] is True


class TestTrainerSide:
    """What a trainer sees and can do about a learner's practice tickets."""

    def trainer_client(self, client, make_role_user):
        trainer = make_role_user(Role.Name.TRAINER, username="tr", email="tr@e.com")
        client.force_login(trainer)
        return client

    def test_the_learner_page_lists_each_session_with_its_score(
        self, client, lc, learner, world, commits, make_role_user
    ):
        play(lc, world["activity"], [GOOD] * 3, run_commits=commits)
        trainer = self.trainer_client(client, make_role_user)
        body = trainer.get(reverse("console_api:learner", args=[learner.pk])).json()
        row = next(a for c in body["courses"] for a in c["activities"] if a["type"] == "bot_sim")
        assert row["state"] == "completed"
        [session] = row["sim"]["sessions"]
        assert (
            session["state"] == "finished"
            and session["passed"] is True
            and 1 <= session["raw"] <= 5
        )
        assert row["sim"]["best_raw"] == session["raw"]
        transcript = trainer.get(
            reverse("console_api:practice-session", args=[session["id"]])
        ).json()
        assert transcript["learner"]["id"] == learner.pk and len(transcript["turns"]) >= 7
        assert (
            transcript["scenario"]["opening_message"] and transcript["result"]["score"]["max"] == 5
        )

    def test_a_trainer_can_reset_a_learners_practice_tickets_and_they_can_try_again(
        self, client, lc, learner, world, commits, make_role_user
    ):
        play(lc, world["activity"], [GOOD] * 3, run_commits=commits)
        assert post_json(lc, u("start", world["activity"].pk)).status_code == 409  # already passed
        trainer = self.trainer_client(client, make_role_user)
        response = trainer.delete(
            reverse("console_api:reset-attempts", args=[learner.pk, world["activity"].pk])
        )
        assert response.status_code in (200, 204), response.content
        assert not ActivityAttempt.objects.exists()
        assert not ActivityProgress.objects.filter(
            user=learner, activity=world["activity"]
        ).exists()
        lc.force_login(learner)
        assert post_json(lc, u("start", world["activity"].pk)).status_code == 201

    def test_resetting_also_ends_a_ticket_still_in_progress(
        self, client, lc, learner, world, make_role_user
    ):
        sid = post_json(lc, u("start", world["activity"].pk)).json()["id"]
        trainer = self.trainer_client(client, make_role_user)
        trainer.delete(
            reverse("console_api:reset-attempts", args=[learner.pk, world["activity"].pk])
        )
        session = SimSession.objects.get(pk=sid)
        assert session.state == "abandoned" and session.abandon_reason == "reset"

    def test_a_learner_cannot_use_the_trainer_endpoints(self, client, lc, learner, world):
        sid = post_json(lc, u("start", world["activity"].pk)).json()["id"]
        assert client.get(reverse("console_api:practice-session", args=[sid])).status_code == 403
        assert client.get(reverse("console_api:practice-scenarios")).status_code == 403
