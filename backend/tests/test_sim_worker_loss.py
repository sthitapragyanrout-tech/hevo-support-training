"""A worker that is killed holding a job never reports a failure, so nothing about the job
says it went wrong. These tests pin what stops it being retried for ever: the learner is told,
and a ticket that never finishes is closed (uncounted) so they can start another."""

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.bot_sim import services
from apps.bot_sim.models import SimSession, SimTurn
from simbot_engine.llm import FakeLLM, default_handler
from tests.sim_helpers import (
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
    settings.SIMBOT_LLM_CALL_ATTEMPTS = 1
    settings.SIMBOT_RETRY_BACKOFF_SECONDS = 0
    monkeypatch.setattr(services, "enqueue_turn", lambda *a, **k: True)
    monkeypatch.setattr(services, "enqueue_finalize", lambda *a, **k: True)


@pytest.fixture
def world(make_role_user):
    built = sim_course(make_role_user)
    approved_scenarios(4)
    built["learner"] = make_role_user(Role.Name.LEARNER, username="lena", email="lena@e.com")
    return built


def model() -> FakeLLM:
    return FakeLLM(lambda task, system, messages: default_handler(task, system, messages))


def taken(turn, times):
    """What a killed worker leaves: the job claimed `times` times, never finished."""
    SimTurn.objects.filter(pk=turn.pk).update(job_attempts=times, job_lease_expires_at=None)


class TestAReplyWhoseWorkerKeepDying:
    def test_below_the_cap_it_is_just_worked_on(self, world, settings):
        session = make_session(world["learner"], world["activity"])
        turn = add_intern_turn(session, 2)
        taken(turn, settings.SIMBOT_MAX_JOB_ATTEMPTS - 1)
        assert services.run_turn(turn.pk, inner=model()) == "done"

    def test_at_the_cap_it_is_given_up_and_the_learner_can_try_again(self, world, settings):
        session = make_session(world["learner"], world["activity"])
        turn = add_intern_turn(session, 2)
        taken(turn, settings.SIMBOT_MAX_JOB_ATTEMPTS)
        assert services.run_turn(turn.pk, inner=model()) == "failed"
        turn.refresh_from_db()
        assert turn.job_state == SimTurn.Job.FAILED
        assert "couldn’t reply" in turn.job_error
        assert turn.scores is None and not session.turns.filter(role="customer", seq=3).exists()
        # "Try again" starts the count afresh
        retried = services.retry_turn(world["learner"], session.pk)
        assert retried.job_attempts == 0 and retried.job_state == SimTurn.Job.PENDING

    def test_waiting_for_the_rate_gate_is_not_a_try(self, world, monkeypatch):
        from apps.bot_sim import gate

        session = make_session(world["learner"], world["activity"])
        turn = add_intern_turn(session, 2)

        def wait(*a, **k):
            raise gate.GateWait(1.0)

        monkeypatch.setattr(services, "_evaluate", wait)
        for _ in range(10):  # far more than the cap
            assert services.run_turn(turn.pk, inner=model()) == "waiting"
        turn.refresh_from_db()
        assert turn.job_attempts == 0 and turn.job_state == SimTurn.Job.PENDING


class TestATicketThatNeverFinishes:
    def finishing(self, world):
        rows = [turn_scores(), turn_scores()]
        return scored_session(world["learner"], world["activity"], rows)

    def test_a_ticket_claimed_over_and_over_is_closed_without_counting(self, world, settings):
        session = self.finishing(world)
        SimSession.objects.filter(pk=session.pk).update(
            finalize_claims=settings.SIMBOT_MAX_FINALIZE_CLAIMS
        )
        assert services.finalize(session.pk, inner=model()) == "abandoned"
        session.refresh_from_db()
        assert session.state == SimSession.State.ABANDONED
        assert session.abandon_reason == "feedback_failed"
        assert session.attempt is None

    def test_the_learner_can_then_start_another(self, world, settings):
        session = self.finishing(world)
        SimSession.objects.filter(pk=session.pk).update(
            finalize_claims=settings.SIMBOT_MAX_FINALIZE_CLAIMS
        )
        with pytest.raises(IntegrityError), transaction.atomic():  # still live: no second ticket
            make_session(world["learner"], world["activity"])
        services.finalize(session.pk, inner=model())
        again = make_session(world["learner"], world["activity"])
        assert again.state == SimSession.State.OPEN and again.pk != session.pk

    def test_each_claim_is_counted_and_a_normal_run_finishes(self, world):
        session = self.finishing(world)
        assert services.finalize(session.pk, inner=model()) == "finished"
        session.refresh_from_db()
        assert session.finalize_claims == 1 and session.attempt is not None

    def test_a_claim_that_expires_is_counted_when_taken_again(self, world, settings):
        session = self.finishing(world)
        past = timezone.now() - timedelta(minutes=5)
        SimSession.objects.filter(pk=session.pk).update(
            finalize_claims=3, finalize_lease_expires_at=past
        )
        services.finalize(session.pk, inner=model())
        session.refresh_from_db()
        assert session.finalize_claims == 4
