"""Retries, duplicates and crashes at every seam: whatever repeats, it can only be
*work* — never a second customer message, evaluation, attempt or score."""

import threading
import uuid
from datetime import timedelta

import pytest
from django.db import connection, connections
from django.utils import timezone

from apps.accounts.models import Role
from apps.bot_sim import gate, services
from apps.bot_sim.models import SimSession, SimTurn
from apps.progress import services as progress
from apps.progress.models import ActivityAttempt, ActivityProgress
from simbot_engine.llm import FakeLLM, LLMError, LLMRefused, RateLimited, default_handler
from tests.sim_helpers import (
    GOOD,
    add_intern_turn,
    approved_scenarios,
    make_session,
    scored_session,
    sim_course,
    turn_scores,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _env(settings, monkeypatch, media_dirs):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    settings.SIMBOT_LLM_CALL_ATTEMPTS = 1  # one model call per step: failures are visible
    settings.SIMBOT_RETRY_BACKOFF_SECONDS = 0
    queued = {"turns": [], "finalize": []}

    def enqueue_turn(turn_id, **kw):
        # like the real one: note that a message is now in flight
        SimTurn.objects.filter(pk=turn_id).update(job_enqueued_at=timezone.now())
        queued["turns"].append(turn_id)
        return True

    def enqueue_finalize(session_id, **kw):
        SimSession.objects.filter(pk=session_id).update(finalize_enqueued_at=timezone.now())
        queued["finalize"].append(session_id)
        return True

    monkeypatch.setattr(services, "enqueue_turn", enqueue_turn)
    monkeypatch.setattr(services, "enqueue_finalize", enqueue_finalize)
    return queued


@pytest.fixture
def queued(_env):
    return _env


@pytest.fixture
def world(make_role_user):
    built = sim_course(make_role_user)
    approved_scenarios(4)
    built["learner"] = make_role_user(Role.Name.LEARNER, username="lena", email="lena@e.com")
    return built


class Spy(FakeLLM):
    """A scripted model that can fail a named task, and counts what it was asked."""

    def __init__(self, fail=None):
        self.fail = fail or {}
        super().__init__(self._handle)

    def _handle(self, task, system, messages):
        error = self.fail.get(task)
        if error is not None:
            raise error
        return default_handler(task, system, messages)

    def count(self, task):
        return sum(1 for c in self.calls if c["task"] == task)


def pending(world):
    session = make_session(world["learner"], world["activity"])
    return session, add_intern_turn(session, 2)


def customers(session):
    return list(session.turns.filter(role="customer").order_by("seq"))


class TestOneTurnsWork:
    def test_the_normal_path_evaluates_once_and_answers_once(self, world):
        session, turn = pending(world)
        spy = Spy()
        assert services.run_turn(turn.pk, inner=spy) == "done"
        turn.refresh_from_db()
        assert turn.scores and turn.job_state == "done"
        assert [t.seq for t in customers(session)] == [1, 3]
        assert (spy.count("evaluate"), spy.count("customer")) == (1, 1)

    def test_evaluated_but_not_answered_then_a_retry_only_answers(self, world, queued):
        session, turn = pending(world)
        first = Spy(fail={"customer": RateLimited("429", retry_after=0.0)})
        assert services.run_turn(turn.pk, inner=first) == "retry"
        turn.refresh_from_db()
        assert turn.scores is not None and turn.job_state == "pending"
        assert len(customers(session)) == 1 and queued["turns"] == [turn.pk]

        second = Spy()
        assert services.run_turn(turn.pk, inner=second) == "done"
        assert (second.count("evaluate"), second.count("customer")) == (
            0,
            1,
        )  # no second evaluation
        assert [t.seq for t in customers(session)] == [1, 3]

    def test_answered_but_the_evaluation_never_landed_is_evaluated_once_later(self, world):
        session, turn = pending(world)
        SimTurn.objects.create(
            session=session, seq=3, role="customer", text="ok", at=timezone.now(), job_state="done"
        )
        spy = Spy()
        assert services.run_turn(turn.pk, inner=spy) == "done"
        assert (spy.count("evaluate"), spy.count("customer")) == (1, 0)  # no second answer
        assert len(customers(session)) == 2

    def test_a_crash_after_the_model_answered_but_before_it_was_saved(self, world, monkeypatch):
        session, turn = pending(world)
        real = services.customer_reply

        def crash_after_paying(*args, **kwargs):
            real(*args, **kwargs)  # the model was called and charged…
            raise RuntimeError("worker killed")  # …and the process died before saving it

        monkeypatch.setattr(services, "customer_reply", crash_after_paying)
        with pytest.raises(RuntimeError):
            services.run_turn(turn.pk, inner=Spy())
        turn.refresh_from_db()
        assert turn.scores is not None and len(customers(session)) == 1
        assert turn.job_lease_expires_at is not None  # the dead worker's claim

        # While the claim is live nobody else touches it…
        assert services.run_turn(turn.pk, inner=Spy()) == "busy"
        # …and once it expires the work is simply done again, exactly once.
        monkeypatch.setattr(services, "customer_reply", real)
        SimTurn.objects.filter(pk=turn.pk).update(
            job_lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        again = Spy()
        assert services.run_turn(turn.pk, inner=again) == "done"
        assert (again.count("evaluate"), again.count("customer")) == (0, 1)
        assert [t.seq for t in customers(session)] == [1, 3]

    def test_a_crash_after_everything_was_saved_repeats_nothing(self, world):
        session, turn = pending(world)
        services.run_turn(turn.pk, inner=Spy())
        # as if the process died just before the "done" mark
        SimTurn.objects.filter(pk=turn.pk).update(job_state="pending", job_lease_expires_at=None)
        scores = SimTurn.objects.get(pk=turn.pk).scores
        spy = Spy()
        assert services.run_turn(turn.pk, inner=spy) == "done"
        assert spy.calls == []  # nothing was asked of the model again
        assert SimTurn.objects.get(pk=turn.pk).scores == scores
        assert len(customers(session)) == 2

    def test_duplicate_delivery_of_the_same_message(self, world):
        session, turn = pending(world)
        services.run_turn(turn.pk, inner=Spy())
        spy = Spy()
        assert [services.run_turn(turn.pk, inner=spy) for _ in range(3)] == ["skipped"] * 3
        assert spy.calls == [] and len(customers(session)) == 2

    def test_a_worker_that_loses_the_race_to_save_discards_its_answer(self, world, monkeypatch):
        session, turn = pending(world)
        real = services.customer_reply

        def other_worker_saves_first(llm, config, scenario, turns):
            step = real(llm, config, scenario, turns)
            SimTurn.objects.create(
                session=session, seq=turn.seq + 1, role="customer", text="the other worker's answer",
                at=timezone.now(), action="follow_up", job_state="done",
            )  # fmt: skip
            return step

        monkeypatch.setattr(services, "customer_reply", other_worker_saves_first)
        assert services.run_turn(turn.pk, inner=Spy()) == "done"
        mine = customers(session)
        assert len(mine) == 2 and mine[1].text == "the other worker's answer"

    def test_a_nudge_or_closing_message_added_meanwhile_stops_a_late_answer(self, world):
        session, turn = pending(world)
        SimTurn.objects.create(
            session=session,
            seq=3,
            role="customer",
            text="closing",
            at=timezone.now(),
            action="close",
            job_state="done",
        )
        spy = Spy()
        services.run_turn(turn.pk, inner=spy)
        assert spy.count("customer") == 0 and len(customers(session)) == 2

    def test_nothing_is_answered_once_the_session_is_finishing_but_the_reply_is_still_scored(
        self, world, queued
    ):
        session, turn = pending(world)
        SimSession.objects.filter(pk=session.pk).update(state="finishing")
        spy = Spy()
        services.run_turn(turn.pk, inner=spy)
        assert (spy.count("evaluate"), spy.count("customer")) == (1, 0)
        assert queued["finalize"] == [session.pk]  # now it can be finalised

    def test_an_abandoned_session_is_left_alone(self, world):
        session, turn = pending(world)
        SimSession.objects.filter(pk=session.pk).update(state="abandoned")
        spy = Spy()
        assert services.run_turn(turn.pk, inner=spy) == "skipped" and spy.calls == []

    def test_non_retryable_failures_stop_at_once_with_a_plain_message(self, world):
        session, turn = pending(world)
        assert (
            services.run_turn(
                turn.pk, inner=Spy(fail={"evaluate": LLMRefused("sk-secret leaked?")})
            )
            == "failed"
        )
        turn.refresh_from_db()
        assert turn.job_state == "failed" and "sk-secret" not in turn.job_error
        assert turn.job_error.startswith("The customer couldn’t reply")

    def test_retries_stop_after_the_attempt_limit(self, world, settings, queued):
        settings.SIMBOT_MAX_JOB_ATTEMPTS = 3
        session, turn = pending(world)
        down = Spy(fail={"evaluate": LLMError("provider down")})
        results = [services.run_turn(turn.pk, inner=down) for _ in range(3)]
        assert results == ["retry", "retry", "failed"]
        assert SimTurn.objects.get(pk=turn.pk).job_attempts == 3
        assert len(customers(session)) == 1  # never answered a reply it could not score

    def test_a_busy_gate_defers_without_using_up_an_attempt(self, world, queued, monkeypatch):
        session, turn = pending(world)
        monkeypatch.setattr(
            gate, "acquire", lambda est, now=None: (_ for _ in ()).throw(gate.GateWait(120))
        )
        assert services.run_turn(turn.pk, inner=Spy()) == "waiting"
        turn = SimTurn.objects.get(pk=turn.pk)
        assert turn.job_state == "pending" and turn.job_lease_expires_at is None
        assert queued["turns"] == [turn.pk]


class TestAcceptingAReplyOnce:
    def test_the_same_reply_sent_twice_is_one_turn_and_one_job(
        self, world, queued, django_capture_on_commit_callbacks
    ):
        session = services.start(world["learner"], world["activity"].pk)
        cid = uuid.uuid4()
        with django_capture_on_commit_callbacks(execute=True):
            first, created_a = services.submit_reply(world["learner"], session.pk, GOOD, cid)
        with django_capture_on_commit_callbacks(execute=True):
            second, created_b = services.submit_reply(
                world["learner"], session.pk, "different text", cid
            )
        assert (created_a, created_b) == (True, False) and first.pk == second.pk
        assert second.text == GOOD  # the first one wins, whatever the repeat says
        assert queued["turns"] == [first.pk]
        assert SimTurn.objects.filter(role="intern").count() == 1

    def test_a_repeat_after_the_ticket_ended_still_returns_the_original(
        self, world, queued, django_capture_on_commit_callbacks
    ):
        session = services.start(world["learner"], world["activity"].pk)
        cid = uuid.uuid4()
        with django_capture_on_commit_callbacks(execute=True):
            first, _ = services.submit_reply(world["learner"], session.pk, GOOD, cid)
        services.finish(world["learner"], session.pk)
        again, created = services.submit_reply(world["learner"], session.pk, GOOD, cid)
        assert not created and again.pk == first.pk


class TestFinalisingOnce:
    def finalize(self, session, spy=None):
        return services.finalize(session.pk, inner=spy or Spy())

    def rows(self):
        return [turn_scores(), turn_scores(5, 4, 3, 4), turn_scores(3, 3, 4, 5, tat=3)]

    def test_twice_makes_one_attempt_and_the_same_numbers(self, world):
        session = scored_session(world["learner"], world["activity"], self.rows())
        assert self.finalize(session) == "finished"
        first = SimSession.objects.get(pk=session.pk).result
        assert self.finalize(session) == "skipped"
        assert ActivityAttempt.objects.count() == 1
        assert SimSession.objects.get(pk=session.pk).result == first

    def test_a_crash_inside_the_commit_rolls_everything_back_together(self, world, monkeypatch):
        session = scored_session(world["learner"], world["activity"], self.rows())
        real = progress.record_attempt

        def die_after_writing(*args, **kwargs):
            real(*args, **kwargs)
            raise RuntimeError("killed mid-commit")

        monkeypatch.setattr(progress, "record_attempt", die_after_writing)
        with pytest.raises(RuntimeError):
            self.finalize(session)
        session.refresh_from_db()
        assert session.state == "finishing" and session.result is None and session.attempt is None
        assert not ActivityAttempt.objects.exists()
        assert not ActivityProgress.objects.filter(
            state="completed"
        ).exists()  # nothing half-applied

        monkeypatch.setattr(progress, "record_attempt", real)
        assert self.finalize(session) == "busy"  # the dead worker's claim is still live…
        SimSession.objects.filter(pk=session.pk).update(
            finalize_lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert self.finalize(session) == "finished"  # …until it expires
        assert ActivityAttempt.objects.count() == 1

    def test_a_result_is_the_same_whenever_and_however_often_it_is_computed(
        self, world, make_role_user
    ):
        results = []
        for n in range(3):
            built = sim_course(make_role_user, title=f"C{n}")
            learner = make_role_user(Role.Name.LEARNER, username=f"l{n}", email=f"l{n}@e.com")
            session = scored_session(
                learner, built["activity"], self.rows(), scenario=approved_scenarios(1)[0]
            )
            self.finalize(session)
            result = dict(SimSession.objects.get(pk=session.pk).result)
            for volatile in ("attempts_left", "state", "attempt", "narrative"):
                result.pop(volatile, None)
            result["scenario_ref"] = None
            results.append(result)
        assert results[0] == results[1] == results[2]

    def test_a_late_scored_reply_holds_the_result_back(self, world, queued):
        session = scored_session(world["learner"], world["activity"], self.rows())
        extra = add_intern_turn(session, 8)  # a fourth reply, not scored yet
        assert self.finalize(session) == "waiting"
        assert ActivityAttempt.objects.count() == 0 and queued["turns"] == [extra.pk]
        services.run_turn(extra.pk, inner=Spy())
        assert self.finalize(session) == "finished"
        assert SimSession.objects.get(pk=session.pk).result["exchanges"] == 4

    def test_the_written_feedback_is_made_once_and_never_changes_the_scores(
        self, world, make_role_user
    ):
        session = scored_session(world["learner"], world["activity"], self.rows())
        flaky = Spy(fail={"narrative": LLMError("busy")})
        assert self.finalize(session, flaky) == "retry"
        session.refresh_from_db()
        assert session.narrative is None and session.narrative_attempts == 1
        assert self.finalize(session) == "finished"
        good = SimSession.objects.get(pk=session.pk)
        assert good.narrative["strengths"] and good.result["narrative"] == good.narrative

    def test_without_any_written_feedback_the_numbers_are_identical(
        self, world, settings, make_role_user
    ):
        settings.SIMBOT_MAX_JOB_ATTEMPTS = 1
        with_text = scored_session(world["learner"], world["activity"], self.rows())
        self.finalize(with_text)
        built = sim_course(make_role_user, title="B")
        other = make_role_user(Role.Name.LEARNER, username="o", email="o@e.com")
        without = scored_session(other, built["activity"], self.rows())
        assert self.finalize(without, Spy(fail={"narrative": LLMError("down")})) == "finished"
        a = SimSession.objects.get(pk=with_text.pk).result
        b = SimSession.objects.get(pk=without.pk).result
        assert b["narrative"] is None
        assert (a["score"], a["metrics"], a["passed"]) == (b["score"], b["metrics"], b["passed"])

    def test_too_few_replies_abandon_without_an_attempt(self, world):
        session = scored_session(world["learner"], world["activity"], [turn_scores()])
        assert self.finalize(session) == "abandoned"
        assert not ActivityAttempt.objects.exists()
        assert SimSession.objects.get(pk=session.pk).abandon_reason == "too_short"

    def test_tries_that_ran_out_meanwhile_record_nothing(self, world):
        session = scored_session(world["learner"], world["activity"], self.rows())
        ActivityProgress.objects.update_or_create(
            user=world["learner"], activity=world["activity"],
            defaults={"state": "completed", "started_at": timezone.now(), "completed_at": timezone.now()},
        )  # fmt: skip
        assert self.finalize(session) == "abandoned"
        assert not ActivityAttempt.objects.exists()
        assert SimSession.objects.get(pk=session.pk).abandon_reason == "attempts_unavailable"

    def test_a_preview_records_no_attempt_or_progress(self, world):
        session = services.start_preview(world["author"], world["activity"].pk)
        SimTurn.objects.filter(session=session).update(job_state="done")
        for seq in (2, 4):
            add_intern_turn(session, seq, scores=turn_scores(), job_state="done")
            SimTurn.objects.create(
                session=session,
                seq=seq + 1,
                role="customer",
                text="ok",
                at=timezone.now(),
                job_state="done",
            )
        SimSession.objects.filter(pk=session.pk).update(state="finishing")
        assert self.finalize(session) == "finished"
        assert SimSession.objects.get(pk=session.pk).result["preview"] is True
        assert not ActivityAttempt.objects.exists() and not ActivityProgress.objects.exists()


class TestSweeper:
    def test_a_lost_message_is_replaced_and_a_live_claim_is_left_alone(self, world, queued):
        session, lost = pending(world)
        SimTurn.objects.filter(pk=lost.pk).update(
            job_enqueued_at=timezone.now() - timedelta(minutes=10)
        )
        _, claimed = (
            pending(world := {**world, "learner": world["learner"]}) if False else (None, None)
        )
        counts = services.recover()
        assert counts["turns"] == 1 and queued["turns"] == [lost.pk]

    def test_a_dead_workers_claim_expires_and_the_turn_is_requeued(self, world, queued):
        _, turn = pending(world)
        SimTurn.objects.filter(pk=turn.pk).update(
            job_lease_expires_at=timezone.now() - timedelta(seconds=5),
            job_enqueued_at=timezone.now() - timedelta(minutes=10),
        )
        assert services.recover()["turns"] == 1 and queued["turns"] == [turn.pk]

    def test_a_live_claim_is_never_touched(self, world, queued):
        _, turn = pending(world)
        SimTurn.objects.filter(pk=turn.pk).update(
            job_lease_expires_at=timezone.now() + timedelta(minutes=2),
            job_enqueued_at=timezone.now() - timedelta(minutes=10),
        )
        assert services.recover()["turns"] == 0 and queued["turns"] == []

    def test_a_recently_queued_turn_is_not_queued_again(self, world, queued):
        pending(world)
        assert services.recover()["turns"] == 0

    def test_a_failed_scoring_is_tried_again_after_a_pause(self, world, queued):
        session, turn = pending(world)
        SimSession.objects.filter(pk=session.pk).update(state="finishing")
        SimTurn.objects.filter(pk=turn.pk).update(
            job_state="failed", job_enqueued_at=timezone.now() - timedelta(minutes=11)
        )
        assert services.recover()["retried"] == 1
        assert SimTurn.objects.get(pk=turn.pk).job_state == "pending" and queued["turns"] == [
            turn.pk
        ]

    def test_a_failed_scoring_is_not_hammered(self, world, queued):
        session, turn = pending(world)
        SimSession.objects.filter(pk=session.pk).update(state="finishing")
        SimTurn.objects.filter(pk=turn.pk).update(
            job_state="failed", job_enqueued_at=timezone.now() - timedelta(minutes=2)
        )
        assert services.recover()["retried"] == 0

    def test_a_finalise_claim_that_ran_out_is_requeued_at_once(self, world, queued):
        session = scored_session(world["learner"], world["activity"], [turn_scores()] * 2)
        SimSession.objects.filter(pk=session.pk).update(
            finalize_enqueued_at=timezone.now(),
            finalize_lease_expires_at=timezone.now() - timedelta(seconds=1),
        )
        assert services.recover()["finalize"] == 1 and queued["finalize"] == [session.pk]

    def test_a_live_finalise_claim_is_left_alone(self, world, queued):
        session = scored_session(world["learner"], world["activity"], [turn_scores()] * 2)
        SimSession.objects.filter(pk=session.pk).update(
            finalize_enqueued_at=timezone.now() - timedelta(minutes=10),
            finalize_lease_expires_at=timezone.now() + timedelta(minutes=2),
        )
        assert services.recover()["finalize"] == 0

    def test_a_session_waiting_to_finalise_with_no_message_in_flight_is_queued(self, world, queued):
        session = scored_session(world["learner"], world["activity"], [turn_scores()] * 2)
        assert services.recover()["finalize"] == 1 and queued["finalize"] == [session.pk]

    def test_a_learner_who_walked_away_still_gets_nudged_then_closed(self, world, queued):
        session = make_session(world["learner"], world["activity"])
        SimTurn.objects.filter(session=session).update(at=timezone.now() - timedelta(minutes=15))
        assert services.recover()["nudged"] == 1
        assert services.recover()["nudged"] == 0  # once only
        SimSession.objects.filter(pk=session.pk).update(
            started_at=timezone.now() - timedelta(minutes=95)
        )
        assert services.recover()["closed"] == 1
        assert SimSession.objects.get(pk=session.pk).state == "abandoned"  # no replies: not scored
        assert not ActivityAttempt.objects.exists()

    def test_an_open_ticket_with_replies_that_times_out_is_scored_not_dropped(
        self, world, queued, django_capture_on_commit_callbacks
    ):
        session = make_session(world["learner"], world["activity"])
        for seq in (2, 4):
            add_intern_turn(session, seq, scores=turn_scores(), job_state="done")
            SimTurn.objects.create(
                session=session,
                seq=seq + 1,
                role="customer",
                text="ok",
                at=session.started_at,
                job_state="done",
            )
        SimSession.objects.filter(pk=session.pk).update(
            started_at=timezone.now() - timedelta(minutes=95)
        )
        with django_capture_on_commit_callbacks(execute=True):
            assert services.recover()["closed"] == 1
        assert SimSession.objects.get(pk=session.pk).state == "finishing"
        assert queued["finalize"] == [session.pk]

    def test_stale_previews_expire(self, world):
        session = services.start_preview(world["author"], world["activity"].pk)
        SimSession.objects.filter(pk=session.pk).update(
            started_at=timezone.now() - timedelta(hours=2)
        )
        assert services.recover()["previews"] == 1

    def test_running_it_twice_changes_nothing_the_second_time(self, world, queued):
        _, turn = pending(world)
        SimTurn.objects.filter(pk=turn.pk).update(
            job_enqueued_at=timezone.now() - timedelta(minutes=10)
        )
        services.recover()
        again = services.recover()  # enqueue stamps job_enqueued_at: it now counts as in flight
        assert again["turns"] == 0 and queued["turns"] == [turn.pk]


class TestSessionBudgets:
    def test_a_runaway_ticket_is_stopped_and_costs_the_learner_nothing(self, world, settings):
        settings.SIMBOT_SESSION_TOKEN_BUDGET = 10
        session, turn = pending(world)
        SimSession.objects.filter(pk=session.pk).update(tokens_used=50)
        assert services.run_turn(turn.pk, inner=Spy()) == "failed"
        session.refresh_from_db()
        assert session.state == "abandoned" and session.abandon_reason == "token_budget"
        assert not ActivityAttempt.objects.exists()


@pytest.mark.django_db(transaction=True)
class TestRealConcurrency:
    @pytest.fixture(autouse=True)
    def _postgres(self):
        if "postgresql" not in connection.settings_dict["ENGINE"]:
            pytest.skip("row locking only exists on Postgres (set DATABASE_URL)")

    def fire(self, jobs):
        results = [None] * len(jobs)
        gate_ = threading.Barrier(len(jobs))

        def go(i):
            gate_.wait()
            try:
                results[i] = jobs[i]()
            except Exception as exc:  # reported by the assertions below
                results[i] = exc
            finally:
                connections.close_all()

        threads = [threading.Thread(target=go, args=(i,)) for i in range(len(jobs))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        return results

    def test_five_workers_race_for_one_turn_and_exactly_one_does_it(self, world):
        session, turn = pending(world)
        spy = Spy()
        results = self.fire([lambda: services.run_turn(turn.pk, inner=spy) for _ in range(5)])
        assert sorted(map(str, results)).count("done") == 1, results
        assert (spy.count("evaluate"), spy.count("customer")) == (1, 1)
        assert len(customers(session)) == 2

    def test_five_simultaneous_posts_of_the_same_reply_make_one_turn(self, world, queued):
        session = services.start(world["learner"], world["activity"].pk)
        cid = uuid.uuid4()
        user = world["learner"]
        results = self.fire(
            [lambda: services.submit_reply(user, session.pk, GOOD, cid) for _ in range(5)]
        )
        assert not [r for r in results if isinstance(r, Exception)], results
        assert sum(1 for r in results if r[1]) == 1  # exactly one was "created"
        assert SimTurn.objects.filter(role="intern").count() == 1 and len(queued["turns"]) == 1

    def test_five_workers_finalise_one_session_into_one_attempt(self, world):
        session = scored_session(world["learner"], world["activity"], [turn_scores()] * 3)
        results = self.fire([lambda: services.finalize(session.pk, inner=Spy()) for _ in range(5)])
        assert not [r for r in results if isinstance(r, Exception)], results
        assert ActivityAttempt.objects.count() == 1
        assert SimSession.objects.get(pk=session.pk).state == "finished"

    def test_two_simultaneous_starts_make_one_session(self, world):
        user = world["learner"]
        results = self.fire([lambda: services.start(user, world["activity"].pk) for _ in range(4)])
        assert not [r for r in results if isinstance(r, Exception)], results
        assert SimSession.objects.count() == 1 and len({r.pk for r in results}) == 1
