"""The scenario bank: who may manage it, the draft → approved → retired workflow, and
the rule that a scored session never uses anything but an approved scenario."""

import json

import pytest
from django.urls import reverse

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.bot_sim import scenarios, services
from apps.bot_sim.errors import NoScenarios
from apps.bot_sim.models import Scenario
from apps.catalog import services as catalog
from simbot_engine.llm import FakeLLM, LLMRefused
from tests.sim_helpers import approved_scenarios, sim_course

pytestmark = pytest.mark.django_db


def url(name, *args):
    return reverse(f"console_api:{name}", args=args)


def call(client, method, path, data=None):
    return getattr(client, method)(path, json.dumps(data or {}), content_type="application/json")


@pytest.fixture
def people(make_role_user):
    return {
        "trainer": make_role_user(Role.Name.TRAINER, username="t", email="t@e.com"),
        "admin": make_role_user(Role.Name.ADMIN, username="adm", email="adm@e.com"),
        "learner": make_role_user(Role.Name.LEARNER, username="l", email="l@e.com"),
    }


NEW = {
    "topic": "billing",
    "persona_type": "urgent",
    "issue_summary": "How are events counted?",
    "opening_message": "How does billing count events?",
    "personality_notes": "Short on time.",
    "doc_hints": ["billing", "Events", " "],
}


class TestWhoMayManageTheBank:
    @pytest.mark.parametrize(
        "who,expected",
        [(None, (401, 403)), ("learner", (403,)), ("trainer", (200,)), ("admin", (200,))],
    )
    def test_list(self, client, people, who, expected):
        if who:
            client.force_login(people[who])
        assert client.get(url("practice-scenarios")).status_code in expected

    @pytest.mark.parametrize("name", ["practice-options"])
    def test_options_follow_the_same_rule(self, client, people, name):
        client.force_login(people["learner"])
        assert client.get(url(name)).status_code == 403

    def test_a_learner_cannot_approve_or_create(self, client, people):
        scenario = Scenario.objects.create(**{**NEW, "doc_hints": []})
        client.force_login(people["learner"])
        assert call(client, "post", url("practice-approve", scenario.pk)).status_code == 403
        assert call(client, "post", url("practice-scenarios"), NEW).status_code == 403
        scenario.refresh_from_db()
        assert scenario.status == "draft"


class TestWorkflow:
    def test_create_edit_approve_retire_restore_with_an_audit_trail(self, client, people):
        client.force_login(people["trainer"])
        made = call(client, "post", url("practice-scenarios"), NEW)
        assert made.status_code == 201
        body = made.json()
        assert body["status"] == "draft" and body["doc_hints"] == ["billing", "events"]
        pk = body["id"]

        approved = call(client, "post", url("practice-approve", pk)).json()
        assert approved["status"] == "approved" and approved["approved_by"] == "t@e.com"

        edited = call(
            client, "patch", url("practice-scenario", pk), {"issue_summary": "Billing events"}
        ).json()
        assert (
            edited["status"] == "draft" and edited["approved_by"] is None
        )  # a second look is needed

        call(client, "post", url("practice-approve", pk))
        assert call(client, "post", url("practice-retire", pk)).json()["status"] == "retired"
        assert call(client, "post", url("practice-restore", pk)).json()["status"] == "draft"

        actions = list(
            AuditLog.objects.filter(target_type="scenario", target_id=str(pk))
            .order_by("id")
            .values_list("action", flat=True)
        )
        assert actions == [
            "scenarios.create", "scenarios.approve", "scenarios.update",
            "scenarios.approve", "scenarios.retire", "scenarios.restore",
        ]  # fmt: skip
        update = AuditLog.objects.get(action="scenarios.update")
        assert update.changes == {"fields": ["issue_summary"], "sent_back_to_draft": True}

    def test_a_no_op_edit_is_not_audited_and_keeps_approval(self, client, people):
        [s] = approved_scenarios(1)
        client.force_login(people["trainer"])
        body = call(
            client, "patch", url("practice-scenario", s.pk), {"issue_summary": s.issue_summary}
        ).json()
        assert body["status"] == "approved"
        assert not AuditLog.objects.filter(action="scenarios.update").exists()

    def test_a_retired_scenario_cannot_be_approved_directly(self, client, people):
        s = Scenario.objects.create(**{**NEW, "doc_hints": []}, status="retired")
        client.force_login(people["trainer"])
        response = call(client, "post", url("practice-approve", s.pk))
        assert response.status_code == 409 and "Restore" in response.json()["detail"]

    def test_only_a_retired_scenario_can_be_restored(self, client, people):
        [s] = approved_scenarios(1)
        client.force_login(people["trainer"])
        assert call(client, "post", url("practice-restore", s.pk)).status_code == 409

    @pytest.mark.parametrize(
        "patch,message",
        [
            ({"topic": "weather"}, "listed topics"),
            ({"persona_type": "angry"}, "customer types"),
            ({"issue_summary": "  "}, "can’t be empty"),
            ({"doc_hints": "mysql"}, "must be a list"),
        ],
    )
    def test_bad_edits_get_a_sentence(self, client, people, patch, message):
        [s] = approved_scenarios(1)
        client.force_login(people["trainer"])
        response = call(client, "patch", url("practice-scenario", s.pk), patch)
        assert response.status_code == 400 and message in response.json()["detail"]

    def test_create_needs_every_required_part(self, client, people):
        client.force_login(people["trainer"])
        response = call(client, "post", url("practice-scenarios"), {"topic": "billing"})
        assert response.status_code == 400

    def test_filters_and_search(self, client, people):
        approved_scenarios(3)
        Scenario.objects.create(**{**NEW, "doc_hints": []}, status="draft")
        client.force_login(people["trainer"])
        assert client.get(url("practice-scenarios") + "?status=draft").json()["count"] == 1
        assert client.get(url("practice-scenarios") + "?persona=urgent").json()["count"] >= 1
        assert client.get(url("practice-scenarios") + "?search=events").json()["count"] == 1
        assert client.get(url("practice-scenarios") + "?topic=billing").json()["count"] == 1

    def test_options_list_topics_and_status_counts(self, client, people):
        approved_scenarios(2)
        client.force_login(people["admin"])
        body = client.get(url("practice-options")).json()
        assert len(body["topics"]) == 10 and body["counts"]["approved"] == 2 and body["model_ready"]


class TestGeneratingDrafts:
    def test_generated_scenarios_are_always_drafts(self, client, people):
        client.force_login(people["trainer"])
        response = call(
            client,
            "post",
            url("practice-generate"),
            {"count": 2, "topic": "billing", "persona": "urgent"},
        )
        assert response.status_code == 202
        made = Scenario.objects.filter(source="generated")
        assert (
            made.count() == 1
        )  # the scripted model repeats one question: the duplicate is skipped
        assert {s.status for s in made} == {"draft"} and made[0].created_by == people["trainer"]
        assert AuditLog.objects.filter(action="scenarios.generate").count() == 1

    @pytest.mark.parametrize(
        "payload",
        [
            {"count": 0},
            {"count": 21},
            {"count": "5"},
            {"count": True},
            {"topic": "x"},
            {"persona": "y"},
        ],
    )
    def test_bad_requests(self, client, people, payload):
        client.force_login(people["trainer"])
        assert call(client, "post", url("practice-generate"), payload).status_code == 400

    def test_duplicates_and_failures_are_counted_not_hidden(self):
        result = scenarios.generate_drafts(3, inner=FakeLLM())
        assert result == {"created": 1, "duplicates": 2, "failed": 0}

        def refuse(task, system, messages):
            raise LLMRefused("no")

        assert scenarios.generate_drafts(5, inner=FakeLLM(refuse))["failed"] == 3  # gives up early

    def test_generation_needs_a_configured_model(self, client, people, settings):
        settings.SIMBOT_LLM = "openai"
        settings.OPENAI_API_KEY = ""
        client.force_login(people["trainer"])
        response = call(client, "post", url("practice-generate"), {"count": 1})
        assert response.status_code == 503


class TestOnlyApprovedScenariosAreUsed:
    def test_drafts_and_retired_scenarios_are_never_given_to_a_learner(self, make_role_user):
        built = sim_course(make_role_user)
        learner = make_role_user(Role.Name.LEARNER, username="lr", email="lr@e.com")
        Scenario.objects.create(**{**NEW, "doc_hints": []}, status="draft")
        Scenario.objects.create(**{**NEW, "doc_hints": []}, status="retired")
        with pytest.raises(NoScenarios) as caught:
            services.start(learner, built["activity"].pk)
        assert (
            "trainer needs to approve" in caught.value.message and caught.value.status_code == 409
        )

    def test_no_session_attempt_or_model_call_happens_when_there_is_nothing_to_use(
        self, make_role_user
    ):
        from apps.bot_sim.models import LLMCall, SimSession
        from apps.progress.models import ActivityAttempt

        built = sim_course(make_role_user)
        learner = make_role_user(Role.Name.LEARNER, username="lr", email="lr@e.com")
        with pytest.raises(NoScenarios):
            services.start(learner, built["activity"].pk)
        assert not SimSession.objects.exists() and not LLMCall.objects.exists()
        assert not ActivityAttempt.objects.exists()

    def test_the_refusal_reaches_the_api_as_a_plain_409(self, client, make_role_user):
        built = sim_course(make_role_user)
        learner = make_role_user(Role.Name.LEARNER, username="lr", email="lr@e.com")
        client.force_login(learner)
        response = client.post(reverse("sim_api:start", args=[built["activity"].pk]))
        assert response.status_code == 409
        assert response.json()["detail"].startswith("Practice isn’t available yet")

    def test_the_persona_and_topic_settings_narrow_the_choice(self, make_role_user):
        built = sim_course(make_role_user, config={"persona": "terse", "topics": ["alerts"]})
        learner = make_role_user(Role.Name.LEARNER, username="lr", email="lr@e.com")
        approved_scenarios(10)  # a mix of personas and topics (one terse 'alerts')
        session = services.start(learner, built["activity"].pk)
        assert session.scenario.persona_type == "terse" and session.scenario.topic == "alerts"

    def test_a_retake_prefers_a_scenario_not_yet_seen_then_repeats_the_oldest(self, make_role_user):
        built = sim_course(make_role_user, max_attempts=0)
        learner = make_role_user(Role.Name.LEARNER, username="lr", email="lr@e.com")
        pool = approved_scenarios(3)
        seen = []
        for _ in range(3):
            session = services.start(learner, built["activity"].pk)
            assert not session.repeated
            seen.append(session.scenario_id)
            services.abandon(session.pk, "test")
        assert sorted(seen) == sorted(s.pk for s in pool)  # three different ones
        fourth = services.start(learner, built["activity"].pk)
        assert fourth.repeated and fourth.scenario_id == seen[0]  # least recently seen

    def test_a_session_keeps_the_scenario_as_it_was(self, make_role_user):
        built = sim_course(make_role_user)
        learner = make_role_user(Role.Name.LEARNER, username="lr", email="lr@e.com")
        [s] = approved_scenarios(1)
        session = services.start(learner, built["activity"].pk)
        scenarios.update(s, {"opening_message": "Completely different now."})
        scenarios.retire(s)
        session.refresh_from_db()
        assert session.scenario_snapshot["opening_message"] != "Completely different now."
        assert session.turns.get(seq=1).text == session.scenario_snapshot["opening_message"]

    def test_an_authors_preview_may_use_a_draft_and_records_nothing(self, make_role_user):
        from apps.progress.models import ActivityAttempt, ActivityProgress

        built = sim_course(make_role_user, publish=False)
        Scenario.objects.create(**{**NEW, "doc_hints": []}, status="draft")
        session = services.start_preview(built["author"], built["activity"].pk)
        assert session.preview and session.scenario.status == "draft"
        assert not ActivityAttempt.objects.exists() and not ActivityProgress.objects.exists()

    def test_a_preview_never_uses_a_retired_scenario(self, make_role_user):
        built = sim_course(make_role_user, publish=False)
        Scenario.objects.create(**{**NEW, "doc_hints": []}, status="retired")
        with pytest.raises(NoScenarios):
            services.start_preview(built["author"], built["activity"].pk)


class TestPublishChecklist:
    def issues(self, built):
        return catalog.publish_checklist(built["version"])

    def test_publishing_is_blocked_with_no_approved_scenario(self, make_role_user):
        built = sim_course(make_role_user, publish=False)
        errors = [i for i in self.issues(built) if i.level == "error"]
        assert any("No approved practice scenarios" in i.message for i in errors)

    def test_fewer_scenarios_than_tickets_needed_blocks_publishing(self, make_role_user):
        built = sim_course(make_role_user, publish=False, config={"required_tickets": 5})
        approved_scenarios(4)
        errors = [i for i in self.issues(built) if i.level == "error"]
        assert any(
            "must finish 5 tickets, but only 4 approved scenarios" in i.message for i in errors
        )

    def test_it_warns_when_a_learner_who_skips_could_run_out(self, make_role_user, settings):
        settings.SIMBOT_SKIPS_PER_ACTIVITY = 5
        built = sim_course(make_role_user, publish=False, config={"required_tickets": 3})
        approved_scenarios(4)  # enough to finish (3) but not if they skip up to 5
        issues = self.issues(built)
        assert not [i for i in issues if i.level == "error" and "Practice" in i.message]
        assert any(
            i.level == "warning" and "could run out of new questions" in i.message for i in issues
        )

    def test_a_ticket_cap_below_the_quota_is_flagged(self, make_role_user):
        built = sim_course(
            make_role_user, publish=False, max_attempts=2, config={"required_tickets": 3}
        )
        approved_scenarios(12)
        assert any("so no one could complete this" in i.message for i in self.issues(built))

    def test_enough_scenarios_is_clean(self, make_role_user, settings):
        settings.SIMBOT_SKIPS_PER_ACTIVITY = 5
        built = sim_course(
            make_role_user, publish=False, max_attempts=0, config={"required_tickets": 3}
        )
        approved_scenarios(8)
        assert not [i for i in self.issues(built) if "Practice ticket" in i.message]

    def test_unapproving_the_last_one_blocks_again(self, make_role_user):
        built = sim_course(make_role_user, publish=False)
        [s] = approved_scenarios(1)
        assert not [i for i in self.issues(built) if i.level == "error" and "Practice" in i.message]
        scenarios.retire(s)
        assert any(i.level == "error" for i in self.issues(built))
