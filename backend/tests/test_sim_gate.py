"""The shared limiter, retries with backoff, the circuit breaker and the cost
caps: the model is called carefully, and a provider problem never reaches a
learner as anything but a plain sentence."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.bot_sim import gate, services
from apps.bot_sim.llm import GatedLLM
from apps.bot_sim.models import LLMBudget, LLMCall, SimSession
from simbot_engine.llm import (
    FakeLLM,
    LLMError,
    LLMRefused,
    LLMTimeout,
    RateLimited,
    default_handler,
)
from tests.sim_helpers import approved_scenarios, sim_course

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _limits(settings):
    settings.SIMBOT_LLM_RPM = 5
    settings.SIMBOT_LLM_TPM = 10_000
    settings.SIMBOT_DAILY_TOKEN_CAP = 100_000
    settings.SIMBOT_BREAKER_FAILURES = 3
    settings.SIMBOT_BREAKER_COOLDOWN_SECONDS = 60
    settings.SIMBOT_LLM_CALL_ATTEMPTS = 3
    settings.SIMBOT_LLM_MAX_WAIT_SECONDS = 2.0


def call(llm, task="customer"):
    return llm.complete_json(
        task=task, system="s", messages=[{"role": "user", "content": "hello, can you help me connect my database? " * 3}],
        model="gpt-4o-mini", max_tokens=50, timeout=5,
    )  # fmt: skip


class TestRateLimits:
    def test_requests_per_minute(self):
        now = timezone.now()
        for _ in range(5):
            gate.acquire(10, now)
        with pytest.raises(gate.GateWait) as caught:
            gate.acquire(10, now)
        assert 0 < caught.value.seconds <= 60
        gate.acquire(10, now + timedelta(seconds=61))  # a new minute

    def test_tokens_per_minute(self):
        now = timezone.now()
        gate.acquire(6000, now)
        with pytest.raises(gate.GateWait):
            gate.acquire(6000, now)
        gate.acquire(3000, now)  # still room for a small one

    def test_a_single_huge_call_is_not_stuck_forever(self):
        gate.acquire(
            50_000, timezone.now()
        )  # bigger than the window on its own: allowed once, alone

    def test_the_daily_cap_pauses_everything_until_tomorrow(self):
        now = timezone.now()
        gate.settle(estimated=0, actual=100_000, ok=True, now=now)
        with pytest.raises(gate.Paused):
            gate.acquire(10, now)
        gate.acquire(10, now + timedelta(days=1))

    def test_settling_corrects_the_estimate_with_the_real_cost(self):
        now = timezone.now()
        gate.acquire(5000, now)
        gate.settle(estimated=5000, actual=200, ok=True, now=now)
        gate.acquire(9000, now)  # the 4,800 over-estimate was given back
        assert LLMBudget.objects.get().tokens_in_window == 9200


class TestCircuitBreaker:
    def fail(self, n, now):
        for _ in range(n):
            gate.settle(estimated=10, actual=0, ok=False, now=now)

    def test_it_opens_after_repeated_failures_and_closes_after_the_cooldown(self):
        now = timezone.now()
        self.fail(3, now)
        with pytest.raises(gate.Paused) as caught:
            gate.acquire(10, now + timedelta(seconds=5))
        assert "paused" in caught.value.message.lower()
        gate.acquire(10, now + timedelta(seconds=61))

    def test_a_success_resets_the_count(self):
        now = timezone.now()
        self.fail(2, now)
        gate.settle(estimated=10, actual=10, ok=True, now=now)
        self.fail(2, now)
        gate.acquire(10, now)  # never three in a row

    def test_starting_a_ticket_is_refused_politely_while_paused(self, make_role_user):
        built = sim_course(make_role_user)
        approved_scenarios(2)
        learner = make_role_user(Role.Name.LEARNER, username="l", email="l@e.com")
        self.fail(3, timezone.now())
        with pytest.raises(services.Unavailable) as caught:
            services.start(learner, built["activity"].pk)
        assert caught.value.status_code == 503 and "paused" in caught.value.message.lower()
        assert not SimSession.objects.exists()

    def test_a_ticket_already_in_progress_can_still_be_resumed_while_paused(self, make_role_user):
        built = sim_course(make_role_user)
        approved_scenarios(2)
        learner = make_role_user(Role.Name.LEARNER, username="l", email="l@e.com")
        session = services.start(learner, built["activity"].pk)
        self.fail(3, timezone.now())
        assert services.start(learner, built["activity"].pk).pk == session.pk


class Scripted(FakeLLM):
    def __init__(self, *errors):
        self.errors = list(errors)
        super().__init__(self._h)

    def _h(self, task, system, messages):
        if self.errors:
            error = self.errors.pop(0)
            if error is not None:
                raise error
        return default_handler(task, system, messages)


class TestGatedClient:
    def make(self, *errors, **kw):
        sleeps = []
        inner = Scripted(*errors)
        return GatedLLM(inner, sleep=sleeps.append, **kw), inner, sleeps

    def test_a_rate_limit_is_waited_out_with_the_providers_hint_then_succeeds(self):
        client, inner, sleeps = self.make(RateLimited("429", retry_after=1.5))
        assert call(client).text
        assert sleeps == [1.5] and len(inner.calls) == 2
        assert list(LLMCall.objects.order_by("id").values_list("status", flat=True)) == [
            "rate_limited",
            "ok",
        ]

    def test_transient_errors_back_off_and_succeed(self):
        client, inner, sleeps = self.make(LLMTimeout(), LLMError("down"))
        assert call(client).text and len(inner.calls) == 3 and len(sleeps) == 2
        assert sleeps[1] > sleeps[0] * 0.9  # growing (within jitter)

    def test_it_gives_up_after_the_attempt_limit_with_the_last_error(self):
        client, inner, _ = self.make(
            RateLimited("a", 0.0), RateLimited("b", 0.0), RateLimited("c", 0.0)
        )
        with pytest.raises(RateLimited):
            call(client)
        assert len(inner.calls) == 3

    def test_a_refusal_is_never_retried(self):
        client, inner, sleeps = self.make(LLMRefused("bad key sk-live-123"))
        with pytest.raises(LLMRefused):
            call(client)
        assert len(inner.calls) == 1 and sleeps == []
        assert LLMCall.objects.get().status == "refused"

    def test_waits_for_a_short_gap_but_hands_back_a_long_one(self, settings):
        settings.SIMBOT_LLM_RPM = 1
        client, inner, sleeps = self.make()
        call(client)  # uses the minute's one request
        with pytest.raises(gate.GateWait) as caught:
            call(client)  # the next window is ~60 s away: too long to sit on a worker
        assert caught.value.seconds > settings.SIMBOT_LLM_MAX_WAIT_SECONDS
        assert len(inner.calls) == 1

    def test_failures_feed_the_breaker_and_successes_clear_it(self):
        client, _, _ = self.make(LLMError("1"), LLMError("2"), None)
        assert call(client).text  # two failures then success on the third attempt
        assert LLMBudget.objects.get().consecutive_failures == 0

    def test_every_attempt_is_recorded_with_tokens_and_latency(self):
        client, _, _ = self.make()
        call(client)
        row = LLMCall.objects.get()
        assert (row.task, row.status, row.model) == ("customer", "ok", "gpt-4o-mini")
        assert row.tokens_in > 0 and row.tokens_out > 0

    def test_a_session_has_a_token_budget(self, make_role_user, settings):
        settings.SIMBOT_SESSION_TOKEN_BUDGET = 100
        built = sim_course(make_role_user)
        approved_scenarios(1)
        learner = make_role_user(Role.Name.LEARNER, username="l", email="l@e.com")
        session = services.start(learner, built["activity"].pk)
        SimSession.objects.filter(pk=session.pk).update(tokens_used=101)
        client = GatedLLM(Scripted(), session=session, sleep=lambda s: None)
        with pytest.raises(gate.Paused, match="length limit"):
            call(client)

    def test_usage_is_added_to_the_session(self, make_role_user):
        built = sim_course(make_role_user)
        approved_scenarios(1)
        learner = make_role_user(Role.Name.LEARNER, username="l", email="l@e.com")
        session = services.start(learner, built["activity"].pk)
        client = GatedLLM(Scripted(), session=session, sleep=lambda s: None)
        call(client)
        call(client)
        assert SimSession.objects.get(pk=session.pk).tokens_used == sum(
            c.tokens_in + c.tokens_out for c in LLMCall.objects.all()
        )


class TestWorkerLimits:
    def test_concurrency_is_hard_capped(self, monkeypatch):
        import importlib

        from config.settings import base

        monkeypatch.setenv("SIMBOT_WORKER_CONCURRENCY", "64")
        try:
            importlib.reload(base)
            assert base.SIMBOT_WORKER_CONCURRENCY == 8
        finally:
            monkeypatch.undo()
            importlib.reload(base)

    def test_simulation_and_video_work_are_routed_to_separate_queues(self):
        from config.celery import app

        routes = app.conf.task_routes
        assert routes["bot_sim.*"] == {"queue": "sim"} and routes["media_pipeline.*"] == {
            "queue": "media"
        }
        app.loader.import_default_modules()
        assert {"bot_sim.process_turn", "bot_sim.finalize", "bot_sim.recover"} <= set(app.tasks)
        assert app.conf.beat_schedule["sim-recover"]["task"] == "bot_sim.recover"

    def test_the_fake_model_is_refused_in_production(self, monkeypatch):
        import importlib

        monkeypatch.setenv("SIMBOT_LLM", "fake")
        monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.prod")
        from config.settings import base, prod

        try:
            importlib.reload(base)  # prod copies the setting from base
            with pytest.raises(RuntimeError, match="not allowed in production"):
                importlib.reload(prod)
        finally:
            monkeypatch.undo()
            importlib.reload(base)
            importlib.reload(prod)
