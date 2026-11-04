"""Mentor-rated simulations over HTTP: the learner's endpoints, the review queue, the rating
page, and the trainer's actions — including who may reach each one, and that a learner is never
shown anything meant for raters."""

import json
from datetime import timedelta

import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.manual_sim import assignments, services
from apps.manual_sim.models import SimCase, SimSubmission
from tests.manual_sim_helpers import FAIL, PASS, T0, at, people, rated_course

pytestmark = pytest.mark.django_db

ANSWER = "Rotate the source password and resume the pipeline."


@pytest.fixture
def world(make_role_user, media_dirs):
    return {**rated_course(make_role_user), **people(make_role_user)}


def lurl(name, *args):
    return reverse(f"rated_sim_api:{name}", args=args)


def curl(name, *args):
    return reverse(f"console_api:{name}", args=args)


def jpost(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def as_user(client, world, who):
    client.force_login(world[who])
    return client


def hand_in(world, now=None, who="learner", answer=ANSWER):
    return services.submit(world[who], world["activity"].pk, answer, now=now or at())


# ------------------------------------------------------------------- the learner's side


class TestTheLearnersEndpoints:
    def test_before_opening_nothing_has_started(self, client, world):
        body = as_user(client, world, "learner").get(lurl("activity", world["activity"].pk)).json()
        assert body["case"]["status"] == "not_opened" and body["case"]["can_submit"] is True
        assert body["case"]["due_at"] is None and body["revisions"] == []
        assert body["config"]["pass_rule"].startswith("You pass")
        assert body["limits"]["max_files"] == 5 and body["limits"]["allowed"] is True

    def test_reading_it_never_starts_the_clock_but_opening_does(self, client, world):
        as_user(client, world, "learner")
        client.get(lurl("activity", world["activity"].pk))
        assert SimCase.objects.count() == 0
        opened = jpost(client, lurl("open", world["activity"].pk)).json()
        assert opened["case"]["status"] == "not_submitted" and opened["case"]["due_at"]
        again = jpost(client, lurl("open", world["activity"].pk)).json()
        assert again["case"]["due_at"] == opened["case"]["due_at"]

    def test_handing_in_and_taking_it_back(self, client, world):
        as_user(client, world, "learner")
        url = lurl("submit", world["activity"].pk)
        made = jpost(client, url, {"answer": ANSWER, "links": ["https://x.io"]})
        assert made.status_code == 201
        case = made.json()["case"]
        assert (
            case["status"] == "waiting"
            and case["can_submit"] is False
            and case["can_withdraw"] is True
        )
        assert jpost(client, url, {"answer": "again"}).status_code == 409  # one at a time
        sub_id = made.json()["revisions"][0]["id"]
        back = jpost(client, lurl("withdraw", sub_id)).json()
        assert (
            back["case"]["status"] == "not_submitted"
            and back["revisions"][0]["state"] == "withdrawn"
        )

    def test_a_refusal_is_a_sentence(self, client, world):
        as_user(client, world, "learner")
        r = jpost(client, lurl("submit", world["activity"].pk), {"answer": "  "})
        assert (
            r.status_code == 400 and r.json()["detail"] == "Write your answer before handing it in."
        )

    def test_signed_out_is_refused_and_so_is_an_unknown_activity(self, client, world):
        assert client.get(lurl("activity", world["activity"].pk)).status_code == 403
        assert as_user(client, world, "learner").get(lurl("activity", 999_999)).status_code == 404

    def test_a_learner_cannot_touch_anothers_submission(self, client, world):
        sub = hand_in(world)
        as_user(client, world, "other")
        assert jpost(client, lurl("withdraw", sub.pk)).status_code == 404
        assert SimSubmission.objects.get().state == "submitted"

    def test_a_locked_lesson_cannot_be_handed_in_to(self, client, make_role_user, media_dirs):
        w = {
            **rated_course(make_role_user, order="sequential", title="Ordered"),
            **people(make_role_user),
        }
        r = jpost(
            as_user(client, w, "learner"), lurl("submit", w["activity"].pk), {"answer": ANSWER}
        )
        assert r.status_code == 409 and r.json()["blocked_by"]

    def test_the_whole_revision_story_is_visible_to_the_learner(self, client, world):
        first = hand_in(world)
        services.rate(
            world["mentor"], first.pk, FAIL, {"tone": "Softer please."}, "Not yet.", now=at(hours=1)
        )
        second = hand_in(world, at(days=1), answer="Second try.")
        services.rate(world["mentor"], second.pk, PASS, {}, "Better.", now=at(days=1, hours=1))
        body = as_user(client, world, "learner").get(lurl("activity", world["activity"].pk)).json()
        assert body["case"]["status"] == "passed" and body["case"]["can_submit"] is False
        one, two = body["revisions"]
        assert (one["revision"], one["answer"], one["rating"]["passed"]) == (1, ANSWER, False)
        assert one["rating"]["comment"] == "Not yet." and one["rating"]["raw_score"] == 2.5
        assert [s["feedback"] for s in one["rating"]["scores"]] == ["", "Softer please."]
        assert (two["revision"], two["rating"]["passed"], two["rating"]["raw_score"]) == (
            2,
            True,
            4.5,
        )


# One allowlist for everything a learner may be told. A field added to a payload later stays
# hidden until someone adds it here on purpose.
ALLOWED = {
    # the activity and its config
    "activity",
    "id",
    "title",
    "config",
    "scenario",
    "handin",
    "criteria",
    "key",
    "label",
    "description",
    "pass_threshold",
    "holds_next",
    "pass_rule",
    "min_each",
    "allow_files",
    "due_days",
    "revision_days",
    "review_hours",
    "limits",
    "max_files",
    "max_file_mb",
    "max_total_mb",
    "types",
    "allowed",
    "max_answer_chars",
    "max_links",
    # the learner's case
    "case",
    "status",
    "due_at",
    "due_basis",
    "overdue",
    "revisions",
    "can_submit",
    "can_withdraw",
    "closed_at",
    # one revision and its rating
    "revision",
    "state",
    "submitted_at",
    "late",
    "answer",
    "links",
    "files",
    "name",
    "type",
    "size_bytes",
    "url",
    "inline",
    "expected_by",
    "rating",
    "raw_score",
    "passed",
    "comment",
    "rated_at",
    "mentor",
    "scores",
    "score",
    "max",
    "feedback",
}
SECRET_TEXT = [
    "RATER-ONLY",
    "guidance",
    "claimed",
    "draft",
    "routing",
    "assigned",
    "needs_attention",
    "closed_by",
    "close_note",
    "unsuccessful",
    "Left the company",
    "rated_by",
]


def keys_of(value):
    found = set()
    if isinstance(value, dict):
        for k, v in value.items():
            found.add(k)
            found |= keys_of(v)
    elif isinstance(value, list):
        for v in value:
            found |= keys_of(v)
    return found


class TestWhatALearnerNeverSees:
    def stages(self, client, world):
        """The learner's payload at every stage of a case, including after a trainer acts."""
        as_user(client, world, "learner")
        url = lurl("activity", world["activity"].pk)
        out = [client.get(url).json()]
        sub = hand_in(world)
        services.claim(world["mentor"], sub.pk, now=at(hours=1))
        services.save_draft(
            world["mentor"],
            sub.pk,
            {"diagnosis": 4},
            {"tone": "SECRET draft note"},
            "SECRET draft",
            now=at(hours=1),
        )
        out.append(client.get(url).json())  # waiting, claimed, with a draft in progress
        services.reassign(world["trainer"], sub.pk, world["mentor2"])
        out.append(client.get(url).json())
        services.rate(world["mentor2"], sub.pk, FAIL, {}, "Changes please.", now=at(hours=2))
        for n in range(3):  # reach the "needs attention" state
            again = hand_in(world, at(days=n + 1))
            services.rate(
                world["mentor"], again.pk, FAIL, {}, "Still no.", now=at(days=n + 1, hours=1)
            )
        out.append(client.get(url).json())
        case = SimCase.objects.get()
        services.close(world["trainer"], case.pk, "Left the company", now=at(days=6))
        out.append(client.get(url).json())
        return out

    def test_only_allowlisted_fields_and_nothing_meant_for_raters(self, client, world):
        for payload in self.stages(client, world):
            assert keys_of(payload) <= ALLOWED, keys_of(payload) - ALLOWED
            text = json.dumps(payload)
            for secret in SECRET_TEXT + ["SECRET"]:
                assert secret not in text, secret

    def test_a_closed_case_says_it_is_closed_but_not_why(self, client, world):
        payloads = self.stages(client, world)
        closed = payloads[-1]["case"]
        assert (
            closed["status"] == "not_passed"
            and closed["closed_at"]
            and closed["can_submit"] is False
        )


# ------------------------------------------------------------------------- the queue


class TestTheQueue:
    def ids(self, client, world, who, **params):
        r = as_user(client, world, who).get(curl("ratings-queue"), params)
        assert r.status_code == 200, r.content
        return [row["id"] for row in r.json()["results"]]

    def test_a_mentor_sees_the_pool_and_a_trainer_sees_everything(self, client, world):
        pool = hand_in(world)
        assert self.ids(client, world, "mentor", tab="pool") == [pool.pk]
        assert self.ids(client, world, "mentor2", tab="pool") == [pool.pk]
        assert self.ids(client, world, "trainer", tab="all") == [pool.pk]
        assert self.ids(client, world, "mentor", tab="mine") == []

    def test_assigned_work_is_mine_to_one_mentor_and_hidden_from_the_other(self, client, world):
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        sub = hand_in(world)
        assert self.ids(client, world, "mentor", tab="mine") == [sub.pk]
        assert self.ids(client, world, "mentor", tab="pool") == []
        assert self.ids(client, world, "mentor2", tab="mine") == []
        assert self.ids(client, world, "mentor2", tab="pool") == []  # not theirs, not in the pool

    def test_an_overdue_review_opens_to_other_mentors_after_the_grace(
        self, client, world, monkeypatch
    ):
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        sub = hand_in(world, at())  # review due at +48 h; open to all after +72 h
        from apps.manual_sim import console

        for hours, expect in ((60, []), (80, [sub.pk])):
            monkeypatch.setattr(console.timezone, "now", lambda h=hours: T0 + timedelta(hours=h))
            assert self.ids(client, world, "mentor2", tab="pool") == expect
        monkeypatch.setattr(console.timezone, "now", lambda: T0 + timedelta(hours=80))
        row = (
            as_user(client, world, "mentor2")
            .get(curl("ratings-queue"), {"tab": "pool"})
            .json()["results"][0]
        )
        assert row["route"] == "escalated" and row["review_overdue"] is True

    def test_your_own_work_is_never_in_your_queue(self, client, world):
        hand_in(world, who="mentor")
        assert self.ids(client, world, "mentor", tab="pool") == []
        assert self.ids(client, world, "mentor2", tab="pool") != []

    def test_the_manager_tabs_are_not_for_mentors(self, client, world):
        for tab in ("all", "cases"):
            assert (
                as_user(client, world, "mentor")
                .get(curl("ratings-queue"), {"tab": tab})
                .status_code
                == 403
            )
        assert (
            as_user(client, world, "mentor")
            .get(curl("ratings-queue"), {"tab": "nonsense"})
            .status_code
            == 400
        )

    def test_a_trainer_defaults_to_mine_and_a_learner_has_no_queue(self, client, world):
        assert as_user(client, world, "trainer").get(curl("ratings-queue")).json()["tab"] == "mine"
        assert as_user(client, world, "learner").get(curl("ratings-queue")).status_code == 403

    def test_the_most_urgent_review_is_first_and_the_counts_are_for_the_tabs(self, client, world):
        later = services.submit(world["other"], world["activity"].pk, "x", now=at(hours=5))
        first = hand_in(world, at())
        body = as_user(client, world, "mentor").get(curl("ratings-queue"), {"tab": "pool"}).json()
        assert [r["id"] for r in body["results"]] == [first.pk, later.pk]
        assert body["counts"] == {"all": 2, "mine": 0, "pool": 2}

    def test_filters_for_overdue_reviews_and_needs_attention(self, client, world, monkeypatch):
        from apps.manual_sim import console

        old = hand_in(world, at())
        fresh = services.submit(world["other"], world["activity"].pk, "x", now=at(hours=60))
        monkeypatch.setattr(console.timezone, "now", lambda: T0 + timedelta(hours=60))
        assert self.ids(client, world, "mentor", tab="pool", overdue="1") == [old.pk]
        assert self.ids(client, world, "mentor", tab="pool", attention="1") == []
        assert fresh.pk in self.ids(client, world, "mentor", tab="pool")

    def test_the_cases_tab_lists_overdue_learners_and_those_needing_attention(
        self, client, world, monkeypatch
    ):
        from apps.manual_sim import console

        services.open_case(world["learner"], world["activity"].pk, now=at())  # due in 7 days
        for n in range(3):
            sub = services.submit(world["other"], world["activity"].pk, "x", now=at(days=n))
            services.rate(world["mentor"], sub.pk, FAIL, {}, "No.", now=at(days=n, hours=1))
        monkeypatch.setattr(console.timezone, "now", lambda: T0 + timedelta(days=4))
        rows = (
            as_user(client, world, "trainer")
            .get(curl("ratings-queue"), {"tab": "cases"})
            .json()["results"]
        )
        assert [(r["learner"]["email"], r["needs_attention"], r["overdue"]) for r in rows] == [
            ("oth@e.com", True, False)
        ]
        monkeypatch.setattr(console.timezone, "now", lambda: T0 + timedelta(days=30))
        rows = (
            as_user(client, world, "trainer")
            .get(curl("ratings-queue"), {"tab": "cases", "overdue": "1"})
            .json()["results"]
        )
        assert {r["learner"]["email"] for r in rows} == {"lea@e.com", "oth@e.com"}


# --------------------------------------------------------------- the rating page


class TestTheRatingPage:
    def test_a_rater_sees_the_guidance_and_the_whole_thread(self, client, world):
        first = hand_in(world)
        services.rate(world["mentor"], first.pk, FAIL, {}, "No.", now=at(hours=1))
        second = hand_in(world, at(days=1), answer="Second.")
        body = as_user(client, world, "mentor").get(curl("ratings-thread", second.pk)).json()
        assert body["criteria"][0]["guidance"].startswith("RATER-ONLY")
        assert [r["revision"] for r in body["revisions"]] == [1, 2]
        assert body["revisions"][0]["rating"]["comment"] == "No."
        assert body["access"] == {"can_rate": True, "reason": "", "can_manage": False}
        assert body["routing"]["route"] == "pool" and body["case"]["unsuccessful"] == 1

    def test_a_mentor_cannot_open_work_that_is_with_another_mentor(self, client, world):
        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        sub = hand_in(world)
        assert (
            as_user(client, world, "mentor2").get(curl("ratings-thread", sub.pk)).status_code == 404
        )
        assert (
            as_user(client, world, "mentor").get(curl("ratings-thread", sub.pk)).status_code == 200
        )

    def test_the_author_can_read_their_thread_but_not_rate_it(self, client, world):
        sub = hand_in(world, who="mentor")
        r = as_user(client, world, "mentor").get(curl("ratings-thread", sub.pk))
        assert r.status_code == 200 and r.json()["access"]["can_rate"] is False
        assert as_user(client, world, "mentor").post(
            curl("ratings-rate", sub.pk), {}
        ).status_code in (400, 403)

    def test_claim_draft_and_rate_through_the_api(self, client, world):
        sub = hand_in(world)
        as_user(client, world, "mentor")
        claimed = jpost(client, curl("ratings-claim", sub.pk)).json()
        assert claimed["routing"]["claimed_by_me"] is True
        drafted = jpost(
            client, curl("ratings-draft", sub.pk), {"scores": {"diagnosis": 4}, "comment": "Half"}
        ).json()
        assert (
            drafted["draft"]["scores"] == {"diagnosis": 4, "tone": None}
            and drafted["draft"]["mine"] is True
        )
        rated = jpost(
            client,
            curl("ratings-rate", sub.pk),
            {"scores": PASS, "feedback": {"tone": "Lovely."}, "comment": "Great work."},
        ).json()
        assert rated["state"] == "rated" and rated["draft"] is None
        assert rated["revisions"][0]["rating"]["raw_score"] == 4.5

    def test_a_second_rating_is_a_409_and_bad_input_a_400_sentence(self, client, world):
        sub = hand_in(world)
        as_user(client, world, "mentor")
        bad = jpost(
            client, curl("ratings-rate", sub.pk), {"scores": {"diagnosis": 5}, "comment": "x"}
        )
        assert bad.status_code == 400 and "Score every criterion" in bad.json()["detail"]
        assert (
            jpost(
                client, curl("ratings-rate", sub.pk), {"scores": PASS, "comment": "ok"}
            ).status_code
            == 200
        )
        assert (
            jpost(
                client, curl("ratings-rate", sub.pk), {"scores": FAIL, "comment": "ok"}
            ).status_code
            == 409
        )

    def test_two_mentors_cannot_both_hold_a_pool_item(self, client, world):
        sub = hand_in(world)
        assert (
            jpost(as_user(client, world, "mentor"), curl("ratings-claim", sub.pk)).status_code
            == 200
        )
        r = jpost(as_user(client, world, "mentor2"), curl("ratings-claim", sub.pk))
        assert r.status_code == 409 and "Another mentor" in r.json()["detail"]

    def test_a_trainer_taking_over_is_audited_and_a_mentor_cannot_release_anothers(
        self, client, world
    ):
        sub = hand_in(world)
        jpost(as_user(client, world, "mentor"), curl("ratings-claim", sub.pk))
        assert jpost(
            as_user(client, world, "mentor2"), curl("ratings-release", sub.pk)
        ).status_code in (403, 409)
        jpost(as_user(client, world, "trainer"), curl("ratings-claim", sub.pk))
        entry = AuditLog.objects.get(action="simulations.take_over")
        assert entry.changes == {"from": "mia@e.com"} and entry.target_label.endswith("revision 1")

    def test_rating_is_audited_without_the_comment_text(self, client, world):
        sub = hand_in(world)
        jpost(
            as_user(client, world, "mentor"),
            curl("ratings-rate", sub.pk),
            {"scores": PASS, "comment": "Private words."},
        )
        entry = AuditLog.objects.get(action="simulations.rate")
        assert entry.changes == {"revision": 1, "score": 4.5, "passed": True}
        assert "Private words" not in json.dumps(entry.changes)


# ---------------------------------------------------------------- trainer's actions


class TestTheTrainersActions:
    def test_reassign_one_submission_and_see_who_could_take_it(self, client, world):
        sub = hand_in(world)
        as_user(client, world, "trainer")
        people_ = client.get(curl("ratings-mentors"), {"learner": world["learner"].pk}).json()[
            "results"
        ]
        assert {p["email"] for p in people_} >= {"mia@e.com", "max@e.com"}
        assert "lea@e.com" not in {p["email"] for p in people_}
        r = jpost(client, curl("ratings-reassign", sub.pk), {"mentor_id": world["mentor2"].pk})
        assert r.status_code == 200 and r.json()["routing"]["assigned_mentor"] == "max@e.com"
        assert AuditLog.objects.get(action="simulations.reassign").changes == {
            "from": "shared pool",
            "to": "max@e.com",
        }
        back = jpost(client, curl("ratings-reassign", sub.pk), {"mentor_id": None})
        assert back.json()["routing"]["assigned_mentor"] is None
        assert (
            jpost(client, curl("ratings-reassign", sub.pk), {"mentor_id": "x"}).status_code == 400
        )
        assert (
            jpost(
                client, curl("ratings-reassign", sub.pk), {"mentor_id": world["other"].pk}
            ).status_code
            == 400
        )

    @pytest.mark.parametrize("name", ["extend", "waive", "close", "reopen"])
    def test_mentors_and_learners_cannot_act_on_a_case(self, client, world, name):
        case = services.open_case(world["learner"], world["activity"].pk, now=at())
        body = {"reason": "why", "days": 3}
        for who in ("mentor", "learner", "other"):
            assert (
                jpost(
                    as_user(client, world, who), curl(f"ratings-{name}", case.pk), body
                ).status_code
                == 403
            )
        assert SimCase.objects.get().closed_at is None

    def test_each_action_is_audited_with_its_reason(self, client, world):
        case = services.open_case(world["learner"], world["activity"].pk, now=at())
        as_user(client, world, "trainer")
        r = jpost(client, curl("ratings-extend", case.pk), {"days": 4, "reason": "Was ill"})
        assert r.status_code == 200 and r.json()["case"]["status"] == "not_submitted"
        assert AuditLog.objects.get(action="simulations.extend").changes == {
            "days": 4,
            "reason": "Was ill",
        }
        jpost(client, curl("ratings-close", case.pk), {"reason": "Left the company"})
        assert AuditLog.objects.get(action="simulations.close").changes == {
            "reason": "Left the company"
        }
        r = jpost(client, curl("ratings-reopen", case.pk), {"reason": "Mistake"})
        assert (
            r.status_code == 200 and AuditLog.objects.filter(action="simulations.reopen").exists()
        )
        waived = jpost(client, curl("ratings-waive", case.pk), {"reason": "Equivalent course"})
        assert waived.json()["case"]["status"] == "waived"

    def test_a_reason_is_required_and_bounds_are_enforced(self, client, world):
        case = services.open_case(world["learner"], world["activity"].pk, now=at())
        as_user(client, world, "trainer")
        assert jpost(client, curl("ratings-waive", case.pk), {"reason": ""}).status_code == 400
        assert (
            jpost(client, curl("ratings-extend", case.pk), {"days": 99, "reason": "x"}).status_code
            == 400
        )
        assert not AuditLog.objects.filter(action__startswith="simulations.").exists()

    def test_the_turnaround_numbers_are_for_managers(self, client, world):
        sub = hand_in(world)
        services.rate(world["mentor"], sub.pk, PASS, {}, "ok", now=at(hours=6))
        waiting = hand_in(world, at(days=3), who="other")
        assert waiting.state == "submitted"
        body = as_user(client, world, "trainer").get(curl("ratings-stats")).json()
        assert body["rated"] == 1 and body["median_hours"] == 6.0 and body["waiting"] == 1
        assert (
            body["mentors"][0]["name"] == "mia@e.com" and body["mentors"][0]["reviewed_late"] == 0
        )
        assert as_user(client, world, "mentor").get(curl("ratings-stats")).status_code == 403


# -------------------------------------- who may reach each endpoint, in one place


class TestEveryEndpointChecksWhoIsAsking:
    @pytest.fixture
    def pieces(self, world):
        sub = hand_in(world)
        case = SimCase.objects.get()
        return {"sub": sub, "case": case}

    def endpoints(self, pieces):
        s, c = pieces["sub"].pk, pieces["case"].pk
        return [
            ("get", curl("ratings-queue"), {}),
            ("get", curl("ratings-mentors"), {}),
            ("get", curl("ratings-stats"), {}),
            ("get", curl("ratings-thread", s), {}),
            ("post", curl("ratings-claim", s), {}),
            ("post", curl("ratings-release", s), {}),
            ("post", curl("ratings-reassign", s), {"mentor_id": None}),
            ("post", curl("ratings-draft", s), {}),
            ("post", curl("ratings-rate", s), {}),
            ("post", curl("ratings-extend", c), {"days": 1, "reason": "x"}),
            ("post", curl("ratings-waive", c), {"reason": "x"}),
            ("post", curl("ratings-close", c), {"reason": "x"}),
            ("post", curl("ratings-reopen", c), {"reason": "x"}),
        ]

    def call(self, client, method, url, data):
        if method == "get":
            return client.get(url)
        return jpost(client, url, data)

    def test_nobody_signed_out_gets_in(self, client, world, pieces):
        for method, url, data in self.endpoints(pieces):
            assert self.call(client, method, url, data).status_code in (401, 403), url

    def test_a_learner_with_no_rating_permission_gets_in_nowhere(self, client, world, pieces):
        as_user(client, world, "other")
        for method, url, data in self.endpoints(pieces):
            assert self.call(client, method, url, data).status_code in (403, 404), url

    def test_a_mentor_gets_into_the_rating_endpoints_and_not_the_managers(
        self, client, world, pieces
    ):
        as_user(client, world, "mentor")
        expected = {
            curl("ratings-queue"): 200,
            curl("ratings-mentors"): 403,
            curl("ratings-stats"): 403,
            curl("ratings-thread", pieces["sub"].pk): 200,
            curl("ratings-claim", pieces["sub"].pk): 200,
            curl("ratings-release", pieces["sub"].pk): 200,
            curl("ratings-reassign", pieces["sub"].pk): 403,
            curl("ratings-draft", pieces["sub"].pk): 200,
            curl("ratings-rate", pieces["sub"].pk): 400,  # reached, then refused for missing scores
            curl("ratings-extend", pieces["case"].pk): 403,
            curl("ratings-waive", pieces["case"].pk): 403,
            curl("ratings-close", pieces["case"].pk): 403,
            curl("ratings-reopen", pieces["case"].pk): 403,
        }
        for method, url, data in self.endpoints(pieces):
            assert self.call(client, method, url, data).status_code == expected[url], url

    def test_a_trainer_gets_into_all_of_them(self, client, world, pieces):
        as_user(client, world, "trainer")
        for method, url, data in self.endpoints(pieces):
            if url.endswith(("/rate/",)):
                continue  # needs real scores; covered above
            if url.endswith(("/waive/", "/close/", "/reopen/")):
                continue  # these end the case; each is covered on its own
            assert self.call(client, method, url, data).status_code == 200, url
