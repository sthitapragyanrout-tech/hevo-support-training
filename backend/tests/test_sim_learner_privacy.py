"""What a learner may learn about a practice ticket — and what they may not.

Every response a learner can reach (starting, polling, resuming, replying, finishing,
the result, the course tree, the progress payload) is walked for trainer-only *keys*
and for *values* planted in the scenario. The result is built from an allowlist, so a
field added later stays hidden until someone decides otherwise.
"""

import json
import uuid

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.accounts.models import Role
from apps.bot_sim import payloads
from apps.bot_sim.models import Scenario, SimSession
from tests.sim_helpers import GOOD, approved_scenarios, play, post_json, sim_course, u

pytestmark = pytest.mark.django_db

# Planted in the scenario: if any of these text values reaches a learner, it leaked.
SENTINELS = {
    "notes": "ZQ-PERSONALITY-NOTES-7731",
    "reference": "ZQ-REFERENCE-ANSWER-7731",
    "hint": "zq-doc-hint-7731",
    "docurl": "https://docs.hevodata.com/zq-doc-url-7731",
    "ticket": "ZQ-TICKET-7731",
    "review": "ZQ-REVIEW-NOTE-7731",
}
# Key names that only trainers may ever see.
TRAINER_KEYS = {
    "persona",
    "persona_type",
    "personality_notes",
    "doc_hints",
    "reference_answer",
    "doc_url",
    "scenario_ref",
    "scenario",
    "needs_review",
    "review_reasons",
    "scores",
    "flags",
    "topic",
    "topics",
    # where a question came from and how it is being reviewed (trainers only)
    "source",
    "source_ticket_id",
    "auto_approved",
    "review_note",
    "import_run",
    "skip_reason",
    "skips",
    "imported",
}


def keys_of(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield path + k, k
            yield from keys_of(v, f"{path}{k}.")
    elif isinstance(value, list):
        for item in value:
            yield from keys_of(item, path)


def assert_nothing_trainer_only(response_or_json, *, where, allow=()):
    body = response_or_json.json() if hasattr(response_or_json, "json") else response_or_json
    leaked = [full for full, k in keys_of(body) if k in TRAINER_KEYS and full not in allow]
    assert not leaked, f"{where}: trainer-only keys {leaked}"
    text = json.dumps(body)
    for name, value in SENTINELS.items():
        assert value not in text, f"{where}: scenario {name} leaked"


@pytest.fixture(autouse=True)
def _clean(media_dirs):
    cache.clear()


@pytest.fixture
def commits(django_capture_on_commit_callbacks):
    return lambda: django_capture_on_commit_callbacks(execute=True)


@pytest.fixture
def world(make_role_user):
    built = sim_course(make_role_user)
    approved_scenarios(
        3,
        personality_notes=SENTINELS["notes"],
        reference_answer=SENTINELS["reference"],
        doc_hints=[SENTINELS["hint"]],
        doc_url=SENTINELS["docurl"],
        review_note=SENTINELS["review"],
    )
    first = Scenario.objects.order_by("id").first()
    Scenario.objects.filter(pk=first.pk).update(
        source="zendesk", source_ticket_id=SENTINELS["ticket"], auto_approved=True
    )
    return built


@pytest.fixture
def learner(make_role_user):
    return make_role_user(Role.Name.LEARNER, username="lena", email="lena@e.com")


@pytest.fixture
def lc(client, learner):
    client.force_login(learner)
    return client


def progress_url(world):
    return reverse("progress_api:course", args=[world["version"].pk])


class TestEveryLearnerResponse:
    def test_the_whole_life_of_a_ticket(self, lc, world, commits):
        activity = world["activity"]
        seen = []

        def look(where, response):
            assert response.status_code in (200, 201, 202), (where, response.content)
            assert_nothing_trainer_only(response, where=where)
            seen.append(where)
            return response.json()

        # before and after starting: the course tree and the learner's progress
        assert_nothing_trainer_only(lc.get(progress_url(world)), where="progress before")
        tree = lc.get(reverse("catalog_api:course-tree", args=[world["version"].pk]))
        assert tree.status_code == 200
        assert_nothing_trainer_only(tree, where="course tree")

        with commits():
            started = look("start", post_json(lc, u("start", activity.pk)))
        sid = started["id"]
        look("resume (start again)", post_json(lc, u("start", activity.pk)))
        look("poll", lc.get(u("session", sid)))
        assert_nothing_trainer_only(lc.get(progress_url(world)), where="progress while open")

        with commits():
            look(
                "message",
                post_json(lc, u("message", sid), {"text": GOOD, "client_id": str(uuid.uuid4())}),
            )
        look("poll after a reply", lc.get(u("session", sid)))
        with commits():
            look(
                "second message",
                post_json(lc, u("message", sid), {"text": GOOD, "client_id": str(uuid.uuid4())}),
            )
        with commits():
            finished = look("finish", post_json(lc, u("finish", sid)))
        final = look("poll at the end", lc.get(u("session", sid)))
        assert final["state"] == "finished" and finished["state"] in ("finishing", "finished")
        result = look("result", lc.get(u("result", sid)))
        assert result["result"]["score"]["max"] == 5
        assert_nothing_trainer_only(lc.get(progress_url(world)), where="progress after")
        assert len(seen) >= 8

    def test_a_skipped_question_and_the_next_one(self, lc, world, commits):
        with commits():
            first = post_json(lc, u("start", world["activity"].pk))
        sid = first.json()["id"]
        skipped = post_json(lc, u("skip", sid), {"reason": "duplicate"})
        assert skipped.status_code == 200
        assert_nothing_trainer_only(skipped, where="skip")
        assert skipped.json()["abandoned_reason"] == "skipped"
        assert_nothing_trainer_only(lc.get(u("session", sid)), where="poll after a skip")
        progress = lc.get(progress_url(world))
        assert_nothing_trainer_only(progress, where="progress after a skip")
        mine = progress.json()["sim"][str(world["activity"].pk)]
        assert mine["skips_used"] == 1 and set(mine) <= {
            "live", "last_finished", "skips_used", "average",
        }  # fmt: skip
        with commits():
            second = post_json(lc, u("start", world["activity"].pk))
        assert_nothing_trainer_only(second, where="the next question")

    def test_a_failed_reply_and_its_retry(self, lc, world, commits, monkeypatch):
        from apps.bot_sim.models import SimTurn

        with commits():
            sid = post_json(lc, u("start", world["activity"].pk)).json()["id"]
        with commits():
            post_json(lc, u("message", sid), {"text": GOOD, "client_id": str(uuid.uuid4())})
        SimTurn.objects.filter(session_id=sid, role="intern").update(
            job_state="failed", job_error="The customer couldn’t reply just now."
        )
        failed = lc.get(u("session", sid))
        assert failed.json()["failed"] is True
        assert_nothing_trainer_only(failed, where="failed poll")
        with commits():
            retried = lc.post(u("retry", sid))
        assert retried.status_code == 200
        assert_nothing_trainer_only(retried, where="retry")

    def test_a_replay_of_the_last_result_after_a_miss(self, lc, make_role_user, commits):
        built = sim_course(
            make_role_user, max_attempts=2, config={"pass_threshold": 1.0}, title="Strict"
        )
        approved_scenarios(3, personality_notes=SENTINELS["notes"])
        payload = play(lc, built["activity"], [GOOD] * 3, run_commits=commits)
        assert payload["result"]["passed"] is False
        assert_nothing_trainer_only(payload, where="a missed attempt")
        assert_nothing_trainer_only(
            lc.get(reverse("progress_api:course", args=[built["version"].pk])),
            where="progress after a miss",
        )


class TestTheResultIsAnAllowlist:
    STORED = {
        "score": {"raw": 4.1, "max": 5, "scaled": 0.82, "internal": "x"},
        "pass_mark": {"raw": 3.5, "scaled": 0.7, "internal": "x"},
        "passed": True,
        "metrics": [
            {
                "key": "empathy",
                "label": "Empathy",
                "raw": 4,
                "max": 5,
                "feedback": "Kind.",
                "basis": "model_judgment",
                "raw_model_output": "SECRET",
            }
        ],
        "narrative": {"strengths": "a", "weaknesses": "b", "overall": "c", "prompt": "SECRET"},
        "grounded": False,
        "exchanges": 3,
        "avg_tat_seconds": 12,
        "attempt": 1,
        "attempts_left": 2,
        "state": "completed",
        # none of these may ever reach a learner
        "needs_review": True,
        "review_reasons": ["too_fast"],
        "scenario_ref": {"topic": "billing", "persona_type": "urgent", "issue_summary": "x"},
        "model": "gpt-x",
        "tokens": 1234,
        "a_field_added_next_year": "SECRET",
    }

    def test_only_listed_fields_survive_at_every_level(self):
        shown = payloads.learner_result(self.STORED)
        assert shown is not None
        assert "SECRET" not in json.dumps(shown)
        assert set(shown) == {
            "state",
            "passed",
            "attempt",
            "attempts_left",
            "grounded",
            "exchanges",
            "avg_tat_seconds",
            "score",
            "pass_mark",
            "metrics",
            "narrative",
        }
        assert shown["score"] == {"raw": 4.1, "max": 5, "scaled": 0.82}
        assert shown["pass_mark"] == {"raw": 3.5, "scaled": 0.7}
        assert set(shown["metrics"][0]) == {"key", "label", "raw", "max", "feedback", "basis"}
        assert set(shown["narrative"]) == {"strengths", "weaknesses", "overall"}

    def test_odd_shapes_do_not_break_it(self):
        assert payloads.learner_result(None) is None
        shown = payloads.learner_result({"passed": False, "narrative": None, "metrics": None})
        assert shown is not None and shown["narrative"] is None and shown["metrics"] == []

    def test_a_trainer_still_gets_everything(self, client, lc, world, commits):
        play(lc, world["activity"], [GOOD] * 3, run_commits=commits)
        session = SimSession.objects.get()
        client.force_login(world["author"])
        body = client.get(reverse("console_api:practice-session", args=[session.pk])).json()
        assert body["result"]["scenario_ref"]["persona_type"]
        assert body["result"]["needs_review"] in (True, False)
        assert "review_reasons" in body["result"]
        assert all(t["scores"] for t in body["turns"] if t["role"] == "intern")
        assert SENTINELS["notes"] in json.dumps(body["scenario"])


class TestAttemptRestrictions:
    def test_a_passed_activity_cannot_start_another_ticket(self, lc, world, commits):
        play(lc, world["activity"], [GOOD] * 3, run_commits=commits)
        before = SimSession.objects.count()
        response = post_json(lc, u("start", world["activity"].pk))
        assert response.status_code == 409 and "already passed" in response.json()["detail"]
        assert SimSession.objects.count() == before

    def test_an_exhausted_activity_cannot_start_another_ticket(self, lc, make_role_user, commits):
        built = sim_course(
            make_role_user, max_attempts=1, config={"pass_threshold": 1.0}, title="One try"
        )
        approved_scenarios(2)
        play(lc, built["activity"], [GOOD] * 3, run_commits=commits)
        before = SimSession.objects.count()
        assert post_json(lc, u("start", built["activity"].pk)).status_code == 409
        assert SimSession.objects.count() == before

    def test_nothing_can_be_added_to_or_finished_in_an_ended_ticket(self, lc, world, commits):
        payload = play(lc, world["activity"], [GOOD] * 3, run_commits=commits)
        sid = payload["id"]
        sent = post_json(lc, u("message", sid), {"text": "more", "client_id": str(uuid.uuid4())})
        assert sent.status_code == 409
        assert lc.post(u("retry", sid)).status_code in (400, 409)
        assert SimSession.objects.get(pk=sid).state == "finished"

    def test_a_locked_lesson_has_no_ticket_to_reach(self, lc, make_role_user):
        built = sim_course(make_role_user, order="sequential", title="Seq")
        approved_scenarios(2)
        assert post_json(lc, u("start", built["activity"].pk)).status_code == 409
        assert not SimSession.objects.exists()
        # …and the learner endpoints for an id that was never theirs answer like "not found"
        for name in ("session", "result"):
            assert lc.get(u(name, 424242)).status_code == 404

    def test_a_learner_cannot_use_the_author_endpoints(self, lc, world):
        assert post_json(lc, u("preview", world["activity"].pk)).status_code == 403
        assert lc.get(reverse("sim_api:scenario-count")).status_code == 403
