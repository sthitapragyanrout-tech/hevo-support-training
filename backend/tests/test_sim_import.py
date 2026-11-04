"""Past customer queries becoming practice scenarios: the gate that must be opened first,
what is kept and what is not, strict approval, duplicates, and the undo.

A fake reader stands in for Zendesk and a scripted model for the provider. Nothing here
talks to a real Zendesk; that is reported as not run.
"""

import json

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.bot_sim import gate, importing
from apps.bot_sim.errors import Conflict
from apps.bot_sim.models import LLMCall, PracticeSettings, Scenario, ScenarioImport
from apps.bot_sim.zendesk import AuditSummary, Verdict
from simbot_engine.llm import FakeLLM, LLMRefused

pytestmark = pytest.mark.django_db

RAW = "SENTINEL-RAW-CUSTOMER-TEXT-9917"
SIGNOFF = "Priya Nair, 2026-10-27, DPA-114"
TOKEN = "SECRET-ZENDESK-TOKEN-4471"

QUESTIONS = [
    ("source_setup", "How do I connect my MySQL database to Hevo as a source?"),
    ("billing", "How does Hevo count billable events each month on my plan?"),
    ("alerts", "How can I get Slack alerts when a pipeline fails to sync?"),
    ("team_management", "How do I invite a colleague and give them read only access?"),
    ("destination_setup", "What permissions does Hevo need to load into BigQuery?"),
]


def rewrite_answer(i: int, **over) -> dict:
    topic, question = QUESTIONS[i % len(QUESTIONS)]
    base = {
        "answerable": True, "confidence": 0.93, "single_question": True, "language": "en",
        "reason": "documented", "topic": topic, "persona_type": "non-technical",
        "issue_summary": question,
        "initial_message": f"Hello, {question[0].lower()}{question[1:]} I am new to this.",
        "personality_notes": "Polite and a little unsure.", "doc_hints": ["hevo", topic.split("_")[0]],
    }  # fmt: skip
    return {**base, **over}


class Script:
    """A scripted model: answers each rewrite from a list, in order."""

    def __init__(self, answers):
        self.answers, self.n = list(answers), 0

    def __call__(self, task, system, messages):
        assert task == "rewrite"
        answer = self.answers[self.n % len(self.answers)]
        self.n += 1
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeReader:
    def __init__(self, verdicts):
        self.verdicts, self.asked = verdicts, []

    def sample(self, count, *, exclude_ids=None):
        self.asked.append((count, set(exclude_ids or ())))
        return [v for v in self.verdicts if v.ticket_id not in (exclude_ids or ())][: count * 6]


def ok(i):
    return Verdict(1000 + i, True, "ok", subject="Help", message=f"{RAW} {i}")


def no(i, reason="author_not_requester"):
    return Verdict(2000 + i, False, reason)


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
def opened(settings):
    """Every part of the gate satisfied."""
    settings.SIMBOT_ZENDESK_IMPORT_ENABLED = True
    settings.SIMBOT_ZENDESK_SIGNOFF = SIGNOFF
    settings.ZENDESK_SUBDOMAIN, settings.ZENDESK_EMAIL = "acme", "ops@acme.io"
    settings.ZENDESK_API_TOKEN = TOKEN
    settings.SIMBOT_AUTO_APPROVE = True
    row = PracticeSettings.load()
    row.zendesk_audited_at = timezone.now()
    row.save()


def run_with(admin, reader, answers, *, count=5, topic=None):
    run = importing.create_run(admin, count, topic)
    result = importing.run_import(run.pk, reader=reader, inner=FakeLLM(Script(answers)))
    return ScenarioImport.objects.get(pk=run.pk), result


class TestTheGate:
    def test_open_means_everything_is_in_place(self, opened):
        assert importing.blocked_reason() is None

    @pytest.mark.parametrize(
        ("change", "expected"),
        [
            (lambda s: setattr(s, "SIMBOT_ENABLED", False), "switched off on this server"),
            (
                lambda s: setattr(s, "SIMBOT_ZENDESK_IMPORT_ENABLED", False),
                "data-protection sign-off",
            ),
            (
                lambda s: setattr(s, "SIMBOT_ZENDESK_SIGNOFF", "   "),
                "sign-off hasn’t been recorded",
            ),
            (lambda s: setattr(s, "ZENDESK_API_TOKEN", ""), "Zendesk isn’t connected"),
            (lambda s: setattr(s, "SIMBOT_LLM", "openai"), "isn't set up"),
        ],
    )
    def test_each_missing_piece_is_named(self, opened, settings, change, expected):
        change(settings)
        settings.OPENAI_API_KEY = ""
        assert expected in (importing.blocked_reason() or "")

    def test_nothing_is_imported_before_a_sample_audit(self, opened):
        PracticeSettings.objects.update(zendesk_audited_at=None)
        assert "audit" in importing.blocked_reason()

    def test_a_refused_import_creates_nothing(self, admin, settings):
        settings.SIMBOT_ZENDESK_IMPORT_ENABLED = False
        with pytest.raises(Conflict, match="data-protection"):
            importing.start_import(admin, 5)
        assert not ScenarioImport.objects.exists()

    def test_a_run_that_started_before_the_gate_closed_does_not_proceed(
        self, opened, admin, settings
    ):
        run = importing.create_run(admin, 3)
        settings.SIMBOT_ZENDESK_SIGNOFF = ""
        assert importing.run_import(run.pk, reader=FakeReader([ok(1)])) == "failed"
        assert not Scenario.objects.exists()
        assert "sign-off" in ScenarioImport.objects.get(pk=run.pk).error

    @pytest.mark.parametrize("count", [0, 51, True, "5", None])
    def test_the_count_is_bounded(self, opened, admin, count):
        with pytest.raises(Exception, match="between 1 and 50"):
            importing.create_run(admin, count)

    def test_one_import_at_a_time(self, opened, admin):
        importing.create_run(admin, 3)
        with pytest.raises(Conflict, match="already running"):
            importing.create_run(admin, 3)

    def test_the_status_never_shows_the_token_or_the_signoff_text(self, opened):
        text = json.dumps(importing.status())
        assert TOKEN not in text and SIGNOFF not in text and "Priya" not in text
        assert importing.status()["signoff_recorded"] is True


class TestWhatIsKeptAndWhatIsNot:
    def test_a_good_query_becomes_an_automatically_approved_scenario(self, opened, admin):
        run, result = run_with(admin, FakeReader([ok(1)]), [rewrite_answer(0)])
        assert result == "done" and (run.examined, run.approved, run.drafted) == (1, 1, 0)
        s = Scenario.objects.get()
        assert s.status == "approved" and s.auto_approved and s.approved_by is None
        assert s.approved_at is not None and s.source == "zendesk" and s.import_run == run
        assert s.source_ticket_id == "1001" and s.created_by == admin and s.review_note == ""

    def test_the_customers_own_words_are_stored_nowhere(self, opened, admin):
        run_with(admin, FakeReader([ok(1), ok(2)]), [rewrite_answer(0), rewrite_answer(1)])
        everything = json.dumps(
            [
                list(Scenario.objects.values()),
                list(ScenarioImport.objects.values()),
                list(LLMCall.objects.values()),
                list(PracticeSettings.objects.values()),
            ],
            default=str,
        )
        assert RAW not in everything

    def test_only_genuine_customer_tickets_reach_the_model(self, opened, admin):
        llm_script = Script([rewrite_answer(0)])
        run = importing.create_run(admin, 5)
        reader = FakeReader([no(1, "not_typed_by_customer"), no(2), ok(3), no(4, "excluded_tag")])
        importing.run_import(run.pk, reader=reader, inner=FakeLLM(llm_script))
        run.refresh_from_db()
        assert llm_script.n == 1  # one model call: the rejected tickets never left the reader
        assert run.rejected == {
            "zendesk:not_typed_by_customer": 1, "zendesk:author_not_requester": 1,
            "zendesk:excluded_tag": 1,
        }  # fmt: skip

    def test_the_model_saying_no_is_counted_not_stored(self, opened, admin):
        no_answer = {"answerable": False, "reason": "needs account access"}
        run, _ = run_with(admin, FakeReader([ok(1)]), [no_answer])
        assert not Scenario.objects.exists() and run.rejected == {"rewrite:not_usable": 1}

    def test_personal_data_in_the_rewrite_is_dropped(self, opened, admin):
        leaky = rewrite_answer(
            0, initial_message="Hello, mail me at jo@acme.io about MySQL please."
        )
        run, _ = run_with(admin, FakeReader([ok(1)]), [leaky])
        assert not Scenario.objects.exists() and run.rejected == {"rewrite:pii_left": 1}

    def test_an_unsure_rewrite_waits_for_a_trainer(self, opened, admin):
        run, _ = run_with(admin, FakeReader([ok(1)]), [rewrite_answer(0, confidence=0.7)])
        s = Scenario.objects.get()
        assert s.status == "draft" and not s.auto_approved and "not sure" in s.review_note
        assert (run.approved, run.drafted) == (0, 1)

    def test_several_questions_wait_for_a_trainer(self, opened, admin):
        run_with(admin, FakeReader([ok(1)]), [rewrite_answer(0, single_question=False)])
        assert Scenario.objects.get().status == "draft"

    def test_a_topic_filter_keeps_only_that_topic(self, opened, admin):
        run, _ = run_with(
            admin,
            FakeReader([ok(1), ok(2)]),
            [rewrite_answer(0), rewrite_answer(1)],
            topic="billing",
        )
        assert list(Scenario.objects.values_list("topic", flat=True)) == ["billing"]
        assert run.rejected == {"rewrite:other_topic": 1}


class TestDuplicatesAndRepeats:
    def test_a_near_duplicate_of_the_bank_is_not_saved(self, opened, admin):
        Scenario.objects.create(
            topic="source_setup", persona_type="urgent", status="retired",
            issue_summary="How can I connect a MySQL database to Hevo as a source?",
            opening_message="Hello, how do I connect my MySQL database to Hevo as a source?",
            personality_notes="n",
        )  # fmt: skip
        run, _ = run_with(admin, FakeReader([ok(1)]), [rewrite_answer(0)])
        assert run.duplicates == 1 and Scenario.objects.count() == 1  # even a retired one counts

    def test_two_near_identical_rewrites_in_one_run_make_one(self, opened, admin):
        run, _ = run_with(admin, FakeReader([ok(1), ok(2)]), [rewrite_answer(0), rewrite_answer(0)])
        assert (run.approved, run.duplicates) == (1, 1)

    def test_a_ticket_already_imported_is_not_even_read_again(self, opened, admin):
        run_with(admin, FakeReader([ok(1)]), [rewrite_answer(0)])
        reader = FakeReader([ok(1), ok(2)])
        importing.run_import(
            importing.create_run(admin, 5).pk,
            reader=reader,
            inner=FakeLLM(Script([rewrite_answer(1)])),
        )
        assert 1001 in reader.asked[0][1]
        assert sorted(Scenario.objects.values_list("source_ticket_id", flat=True)) == [
            "1001",
            "1002",
        ]

    def test_the_unique_ticket_id_is_the_last_line_of_defence(self, opened, admin):
        class Racing(FakeReader):
            """Another import saves ticket 1001 after this one has chosen its tickets."""

            def sample(self, count, *, exclude_ids=None):
                chosen = super().sample(count, exclude_ids=exclude_ids)
                Scenario.objects.create(
                    topic="billing",
                    persona_type="urgent",
                    issue_summary="Something unrelated entirely",
                    opening_message="Totally different words about invoices",
                    personality_notes="n",
                    source_ticket_id="1001",
                )
                return chosen

        run = importing.create_run(admin, 3)
        importing.run_import(
            run.pk, reader=Racing([ok(1)]), inner=FakeLLM(Script([rewrite_answer(0)]))
        )
        run.refresh_from_db()
        assert run.duplicates == 1 and run.approved == 0 and run.state == "done"
        assert Scenario.objects.filter(source_ticket_id="1001").count() == 1

    def test_delivering_the_same_run_twice_does_nothing_the_second_time(self, opened, admin):
        run = importing.create_run(admin, 3)
        reader = FakeReader([ok(1)])
        assert (
            importing.run_import(run.pk, reader=reader, inner=FakeLLM(Script([rewrite_answer(0)])))
            == "done"
        )
        assert (
            importing.run_import(run.pk, reader=reader, inner=FakeLLM(Script([rewrite_answer(0)])))
            == "skipped"
        )
        assert Scenario.objects.count() == 1 and len(reader.asked) == 1


class TestAutomaticApprovalCanBeSwitchedOff:
    def test_off_in_the_console_means_drafts(self, opened, admin):
        PracticeSettings.objects.update(auto_approve_enabled=False)
        run, _ = run_with(admin, FakeReader([ok(1)]), [rewrite_answer(0)])
        s = Scenario.objects.get()
        assert s.status == "draft" and not s.auto_approved and run.auto_approve is False
        assert s.review_note == "Automatic approval is off."

    def test_off_in_the_environment_overrides_the_console(self, opened, admin, settings):
        settings.SIMBOT_AUTO_APPROVE = False
        PracticeSettings.objects.update(auto_approve_enabled=True)
        run_with(admin, FakeReader([ok(1)]), [rewrite_answer(0)])
        assert Scenario.objects.get().status == "draft"

    def test_the_setting_decides_when_the_run_is_requested(self, opened, admin):
        run = importing.create_run(admin, 3)
        assert run.auto_approve is True
        ScenarioImport.objects.all().delete()
        PracticeSettings.objects.update(auto_approve_enabled=False)
        assert importing.create_run(admin, 3).auto_approve is False


class TestWhenThingsGoWrong:
    def test_zendesk_failing_stops_the_run_with_a_sentence(self, opened, admin):
        from apps.bot_sim.zendesk import ZendeskError

        class Broken:
            def sample(self, count, *, exclude_ids=None):
                raise ZendeskError("Zendesk is busy or unavailable. Try again later.")

        run, result = run_with(admin, Broken(), [rewrite_answer(0)])
        assert result == "failed" and run.state == "failed" and "busy" in run.error

    def test_one_failed_rewrite_does_not_stop_the_rest(self, opened, admin):
        run, _ = run_with(admin, FakeReader([ok(1), ok(2)]), [LLMRefused("no"), rewrite_answer(1)])
        assert (run.failed, run.approved, run.state) == (1, 1, "done")

    def test_a_paused_model_stops_the_run_early_but_keeps_what_was_done(self, opened, admin):
        run, result = run_with(
            admin, FakeReader([ok(1), ok(2)]), [rewrite_answer(0), gate.Paused()]
        )
        assert result == "failed" and run.approved == 1 and "paused" in run.error.lower()

    def test_a_crashed_run_is_marked_and_a_lost_one_is_requeued(self, opened, admin, monkeypatch):
        old = timezone.now() - importing.STALE_AFTER - importing.timedelta(minutes=1)
        stuck = ScenarioImport.objects.create(requested=3, state="running")
        lost = ScenarioImport.objects.create(requested=3, state="queued")
        ScenarioImport.objects.update(created_at=old)
        queued = []
        monkeypatch.setattr(importing, "enqueue", queued.append)
        assert importing.recover() == 1
        stuck.refresh_from_db()
        assert stuck.state == "failed" and "start it again" in stuck.error
        assert queued == [lost.pk]


class TestAuditBeforeAnything_Is_Imported:
    def test_it_records_counts_and_ids_but_no_text(self, settings):
        reader = FakeReader([ok(1), no(2, "excluded_group"), no(3, "excluded_group")])
        summary = importing.run_audit(5, reader=reader)
        assert isinstance(summary, AuditSummary) and summary.accepted == 1
        row = PracticeSettings.load()
        assert row.zendesk_audited_at is not None
        assert row.zendesk_audit["reasons"] == {"excluded_group": 2}
        assert RAW not in json.dumps(row.zendesk_audit)

    def test_the_command_needs_a_connection(self, settings):
        settings.ZENDESK_SUBDOMAIN = ""
        with pytest.raises(CommandError, match="isn't connected"):
            call_command("audit_zendesk_sample")

    def test_the_import_command_obeys_the_gate(self, settings):
        settings.SIMBOT_ZENDESK_IMPORT_ENABLED = False
        with pytest.raises(CommandError, match="data-protection"):
            call_command("import_zendesk_scenarios")


class TestUndoingABadBatch:
    def test_only_what_the_run_approved_by_itself_goes_back(self, opened, admin):
        run, _ = run_with(admin, FakeReader([ok(1), ok(2)]), [rewrite_answer(0), rewrite_answer(1)])
        mine = list(Scenario.objects.order_by("id"))
        mine[1].auto_approved, mine[1].approved_by = False, admin  # a person approved this one
        mine[1].save()
        assert importing.revert_import(run) == 1
        mine[0].refresh_from_db()
        mine[1].refresh_from_db()
        assert mine[0].status == "draft" and not mine[0].auto_approved
        assert f"import #{run.pk}" in mine[0].review_note
        assert mine[1].status == "approved"

    def test_forgetting_ticket_links_keeps_the_questions(self, opened, admin):
        run_with(admin, FakeReader([ok(1)]), [rewrite_answer(0)])
        call_command("purge_zendesk_ids")
        s = Scenario.objects.get()
        assert s.source_ticket_id is None and s.status == "approved"


class TestTheConsole:
    def url(self, name, *args):
        return reverse(f"console_api:{name}", args=args)

    def test_only_an_administrator_may_start_an_import(self, client, opened, admin, trainer):
        client.force_login(trainer)
        denied = client.post(
            self.url("practice-imports"), {"count": 3}, content_type="application/json"
        )
        assert denied.status_code == 403
        assert client.get(self.url("practice-imports")).status_code == 200  # but may look
        client.force_login(admin)
        sent = client.post(
            self.url("practice-imports"), {"count": 3}, content_type="application/json"
        )
        assert sent.status_code == 202 and sent.json()["requested"] == 3

    def test_a_refusal_says_why_and_is_audited(self, client, admin, settings):
        settings.SIMBOT_ZENDESK_IMPORT_ENABLED = False
        client.force_login(admin)
        response = client.post(
            self.url("practice-imports"), {"count": 3}, content_type="application/json"
        )
        assert response.status_code == 409 and "data-protection" in response.json()["detail"]
        assert AuditLog.objects.filter(action="scenarios.import_refused").exists()

    def test_starting_is_audited_and_queues_the_work(
        self, client, opened, admin, monkeypatch, django_capture_on_commit_callbacks
    ):
        queued = []
        monkeypatch.setattr(importing, "enqueue", queued.append)
        client.force_login(admin)
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(
                self.url("practice-imports"),
                {"count": 3, "topic": "billing"},
                content_type="application/json",
            )
        assert response.status_code == 202
        run = ScenarioImport.objects.get()
        assert queued == [run.pk] and run.topic == "billing" and run.started_by == admin
        assert AuditLog.objects.filter(action="scenarios.import").exists()

    def test_the_options_say_whether_import_may_run_without_secrets(self, client, opened, admin):
        client.force_login(admin)
        body = client.get(self.url("practice-options")).json()
        assert body["zendesk"]["configured"] and body["zendesk"]["blocked_reason"] is None
        assert body["zendesk"]["auto_approve"]["on"] is True
        text = json.dumps(body)
        assert TOKEN not in text and SIGNOFF not in text

    def test_only_an_administrator_flips_automatic_approval_and_it_is_audited(
        self, client, admin, trainer
    ):
        patch = lambda who, value: (  # noqa: E731
            client.force_login(who),
            client.patch(
                self.url("practice-settings"),
                {"auto_approve_enabled": value},
                content_type="application/json",
            ),
        )[1]
        assert patch(trainer, False).status_code == 403
        assert PracticeSettings.load().auto_approve_enabled is True
        response = patch(admin, False)
        assert response.status_code == 200 and response.json()["on"] is False
        assert AuditLog.objects.filter(action="scenarios.auto_approve").exists()
        assert patch(admin, "maybe").status_code == 400

    def test_the_list_shows_where_a_question_came_from_and_how_it_is_doing(
        self, client, opened, admin
    ):
        from apps.bot_sim.models import SimSession  # noqa: F401

        run, _ = run_with(admin, FakeReader([ok(1)]), [rewrite_answer(0)])
        hand = Scenario.objects.create(
            topic="billing", persona_type="urgent", issue_summary="Written by hand",
            opening_message="m", personality_notes="n", review_note="Skipped as unclear by 3 learners.",
        )  # fmt: skip
        client.force_login(admin)
        body = client.get(self.url("practice-scenarios")).json()
        by = {r["issue_summary"]: r for r in body["results"]}
        imported = by[QUESTIONS[0][1]]
        assert imported["source"] == "zendesk" and imported["auto_approved"] is True
        assert imported["import_run"] == run.pk and imported["source_ticket_id"] == "1001"
        assert imported["skips"] == {} and imported["finished"] == 0 and imported["average"] is None

        # the review queue and the other filters
        def ids(**q):
            return [
                r["id"] for r in client.get(self.url("practice-scenarios"), q).json()["results"]
            ]

        assert ids(attention=1) == [hand.pk]
        assert ids(source="zendesk") == [imported["id"]]
        assert ids(auto=1) == [imported["id"]]
        assert ids(import_run=run.pk) == [imported["id"]]

    def test_reverting_is_for_administrators_and_audited(self, client, opened, admin, trainer):
        run, _ = run_with(admin, FakeReader([ok(1)]), [rewrite_answer(0)])
        client.force_login(trainer)
        assert client.post(self.url("practice-import-revert", run.pk)).status_code == 403
        client.force_login(admin)
        response = client.post(self.url("practice-import-revert", run.pk))
        assert response.status_code == 200 and response.json()["sent_back"] == 1
        assert AuditLog.objects.filter(action="scenarios.import_revert").exists()
        assert Scenario.objects.get().status == "draft"
