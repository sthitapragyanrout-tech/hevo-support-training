"""The question bank's status and the nightly top-up: when it asks for more, when it holds
back and says why, that it uses the same gate and run as a manual import, and who may
switch it. Zendesk and the model are fakes, as in test_sim_import.py; the first live night
is not covered here."""

import json
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.bot_sim import importing
from apps.bot_sim.models import PracticeSettings, Scenario, ScenarioImport
from simbot_engine.llm import FakeLLM
from tests.test_sim_import import (  # noqa: F401  (fixtures are reused)
    SIGNOFF,
    TOKEN,
    FakeReader,
    Script,
    ok,
    opened,
    rewrite_answer,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean(media_dirs):
    cache.clear()


@pytest.fixture
def admin(make_role_user):
    return make_role_user(Role.Name.ADMIN, username="adm", email="adm@e.com")


@pytest.fixture
def trainer(make_role_user):
    return make_role_user(Role.Name.TRAINER, username="trn", email="trn@e.com")


@pytest.fixture
def queued(monkeypatch):
    """Record what the top-up asks the worker to do instead of doing it."""
    sent: list[int] = []
    monkeypatch.setattr(importing, "enqueue", lambda run_id: sent.append(run_id) or True)
    return sent


@pytest.fixture
def on(opened):  # noqa: F811
    """The gate is open and the administrator has switched the top-up on."""
    row = PracticeSettings.load()
    row.topup_enabled = True
    row.save()


def scenarios(n, status="approved"):
    for i in range(n):
        Scenario.objects.create(
            topic="billing",
            persona_type="non-technical",
            issue_summary=f"Question number {i} about billing",
            opening_message=f"Hello, question {i}?",
            status=status,
            source="seed",
        )


def last_check():
    return PracticeSettings.load().topup_last_check


class TestTheBankStatus:
    def test_empty_low_and_ok(self, settings):
        settings.SIMBOT_BANK_TARGET = 3
        assert importing.bank_status() == {
            "approved": 0,
            "drafts": 0,
            "target": 3,
            "state": "empty",
        }
        scenarios(2)
        assert importing.bank_status()["state"] == "low"
        scenarios(1)
        assert importing.bank_status()["state"] == "ok"

    def test_drafts_and_retired_do_not_count_as_available(self, settings):
        settings.SIMBOT_BANK_TARGET = 3
        scenarios(5, "draft")
        scenarios(5, "retired")
        status = importing.bank_status()
        assert (status["approved"], status["drafts"], status["state"]) == (0, 5, "empty")


class TestWhenTheTopUpAsksForMore:
    def test_a_short_bank_queues_one_scheduled_import(self, on, queued, settings):
        settings.SIMBOT_BANK_TARGET, settings.SIMBOT_TOPUP_COUNT = 5, 12
        scenarios(2)
        assert importing.top_up() == "queued"
        run = ScenarioImport.objects.get()
        assert queued == [run.pk]
        assert (run.trigger, run.requested, run.started_by) == ("scheduled", 12, None)
        assert run.state == "queued" and run.auto_approve is True
        assert last_check()["outcome"] == "queued"

    def test_the_size_never_exceeds_the_manual_limit(self, on, queued, settings):
        settings.SIMBOT_TOPUP_COUNT = 500
        importing.top_up()
        assert ScenarioImport.objects.get().requested == importing.MAX_PER_IMPORT

    def test_two_firings_make_one_run(self, on, queued):
        assert importing.top_up() == "queued"
        assert importing.top_up() == "skipped"
        assert ScenarioImport.objects.count() == 1 and len(queued) == 1
        assert "already running" in last_check()["reason"]

    def test_the_run_is_an_ordinary_import_with_every_safeguard(self, on, queued, settings):
        settings.SIMBOT_BANK_TARGET = 5
        importing.top_up()
        run = ScenarioImport.objects.get()
        # no queued worker in this test: run it the way the worker would
        done = importing.run_import(
            run.pk, reader=FakeReader([ok(1)]), inner=FakeLLM(Script([rewrite_answer(0)]))
        )
        run.refresh_from_db()
        assert done == "done" and (run.approved, run.trigger) == (1, "scheduled")
        scenario = Scenario.objects.get()
        assert scenario.auto_approved and scenario.import_run == run
        assert importing.revert_import(run) == 1  # undo works on a nightly run too


class TestWhenItHoldsBackAndWhy:
    def test_off_by_default_even_when_everything_else_is_ready(self, opened, queued):  # noqa: F811
        assert importing.topup_effective() is False
        assert importing.top_up() == "off"
        assert not ScenarioImport.objects.exists() and queued == []

    def test_the_environment_master_overrides_the_console_switch(self, on, queued, settings):
        settings.SIMBOT_TOPUP_ENABLED = False
        assert importing.topup_effective() is False
        assert importing.top_up() == "off" and not ScenarioImport.objects.exists()

    def test_a_closed_gate_is_named(self, on, queued, settings):
        settings.ZENDESK_API_TOKEN = ""
        assert importing.top_up() == "skipped"
        assert "Zendesk isn’t connected" in last_check()["reason"]
        assert not ScenarioImport.objects.exists()

    def test_the_audit_is_still_required(self, on, queued):
        row = PracticeSettings.load()
        row.zendesk_audited_at = None
        row.save()
        assert importing.top_up() == "skipped"
        assert "audit" in last_check()["reason"]

    def test_a_full_bank_asks_for_nothing(self, on, queued, settings):
        settings.SIMBOT_BANK_TARGET = 2
        scenarios(2)
        assert importing.top_up() == "skipped"
        assert "Enough approved" in last_check()["reason"] and not ScenarioImport.objects.exists()

    def test_it_does_not_pile_up_drafts_nobody_has_reviewed(self, on, queued, settings):
        settings.SIMBOT_TOPUP_MAX_DRAFTS = 3
        scenarios(3, "draft")
        assert importing.top_up() == "skipped"
        assert "waiting for a trainer" in last_check()["reason"]
        assert not ScenarioImport.objects.exists()

    def test_a_run_in_progress_is_left_alone(self, on, queued, admin):
        importing.create_run(admin, 3)
        assert importing.top_up() == "skipped"
        assert ScenarioImport.objects.count() == 1


def finished_empty_night(when):
    run = ScenarioImport.objects.create(
        trigger="scheduled", requested=20, state="done", examined=20, finished_at=when
    )
    ScenarioImport.objects.filter(pk=run.pk).update(created_at=when)
    return run


class TestPausingWhenNothingNewComesIn:
    def test_three_empty_nights_in_a_row_pause_it(self, on, queued):
        now = timezone.now()
        for n in (3, 2):
            finished_empty_night(now - timedelta(days=n))
        assert importing.topup_paused() is False  # two is not enough
        finished_empty_night(now - timedelta(days=1))
        assert importing.topup_paused() is True
        assert importing.top_up() == "skipped"
        assert "Paused" in last_check()["reason"] and queued == []

    def test_a_night_that_found_something_prevents_the_pause(self, on):
        now = timezone.now()
        finished_empty_night(now - timedelta(days=3))
        found = finished_empty_night(now - timedelta(days=2))
        ScenarioImport.objects.filter(pk=found.pk).update(drafted=1)
        finished_empty_night(now - timedelta(days=1))
        assert importing.topup_paused() is False

    def test_a_manual_import_lifts_the_pause(self, on, admin):
        now = timezone.now()
        for n in (3, 2, 1):
            finished_empty_night(now - timedelta(days=n))
        assert importing.topup_paused() is True
        ScenarioImport.objects.create(trigger="manual", requested=5, started_by=admin)
        assert importing.topup_paused() is False

    def test_switching_it_off_and_on_lifts_the_pause(self, on, client, admin):
        now = timezone.now()
        for n in (3, 2, 1):
            finished_empty_night(now - timedelta(days=n))
        assert importing.topup_paused() is True
        url = reverse("console_api:practice-top-up")
        client.force_login(admin)
        for value in (False, True):
            client.patch(url, {"enabled": value}, content_type="application/json")
        assert importing.topup_paused() is False


class TestTheConsole:
    url = staticmethod(lambda name: reverse(f"console_api:{name}"))

    def patch(self, client, who, value):
        client.force_login(who)
        return client.patch(
            self.url("practice-top-up"), {"enabled": value}, content_type="application/json"
        )

    def test_only_an_administrator_switches_it_and_it_is_audited(self, client, admin, trainer):
        assert self.patch(client, trainer, True).status_code == 403
        assert PracticeSettings.load().topup_enabled is False
        response = self.patch(client, admin, True)
        assert response.status_code == 200 and response.json()["setting"] is True
        assert PracticeSettings.load().topup_enabled is True
        assert AuditLog.objects.filter(action="scenarios.topup").exists()
        assert self.patch(client, admin, "yes").status_code == 400

    def test_the_options_carry_the_bank_and_the_topup_without_secrets(self, client, on, admin):
        scenarios(1)
        client.force_login(admin)
        body = client.get(self.url("practice-options")).json()
        assert body["bank"]["approved"] == 1 and body["bank"]["state"] == "low"
        assert body["topup"]["on"] is True and body["topup"]["master"] is True
        assert body["topup"]["next_run_at"]
        text = json.dumps(body)
        assert TOKEN not in text and SIGNOFF not in text

    def test_a_nightly_run_appears_in_the_history_labelled(self, client, on, queued, admin):
        importing.top_up()
        client.force_login(admin)
        runs = client.get(self.url("practice-imports")).json()["results"]
        assert runs[0]["trigger"] == "scheduled" and runs[0]["started_by"] is None

    def test_next_run_is_the_scheduled_time_in_the_future(self, settings):
        settings.SIMBOT_TOPUP_HOUR, settings.SIMBOT_TOPUP_MINUTE = 2, 30
        before = timezone.now().replace(hour=1, minute=0, second=0, microsecond=0)
        assert importing.next_topup_at(before).hour == 2
        assert importing.next_topup_at(before).date() == before.date()
        after = before.replace(hour=3)
        assert importing.next_topup_at(after).date() == after.date() + timedelta(days=1)


class TestTheSchedule:
    def test_the_beat_entry_and_task_exist_and_route_to_the_practice_queue(self, settings):
        from config.celery import app

        assert settings.CELERY_BEAT_SCHEDULE["sim-top-up"]["task"] == "bot_sim.top_up"
        app.loader.import_default_modules()
        assert "bot_sim.top_up" in app.tasks
        assert settings.CELERY_TASK_ROUTES["bot_sim.*"] == {"queue": "sim"}
