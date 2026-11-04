"""Practice, not a test: finishing enough scored tickets completes the activity; skipping
a question costs nothing; a skipped or already-seen question is not served again."""

import uuid

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.accounts.models import Role
from apps.activities import bot_sim as cfg
from apps.bot_sim import services
from apps.bot_sim.models import Scenario, SimSession
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
def learner(make_role_user):
    return make_role_user(Role.Name.LEARNER, username="lena", email="lena@e.com")


@pytest.fixture
def lc(client, learner):
    client.force_login(learner)
    return client


def course(make_role_user, **config):
    """A practice course with the *shipped* defaults (five tickets, no pass needed)."""
    built = sim_course(make_role_user, max_attempts=0, config=config)
    built["activity"].config = {k: v for k, v in built["activity"].config.items()
                                if k not in ("required_tickets", "require_average")}  # fmt: skip
    built["activity"].config.update(config)
    built["activity"].save()
    return built


def state(learner, activity):
    row = ActivityProgress.objects.filter(user=learner, activity=activity).first()
    return row.state if row else None


class TestThePureRule:
    @pytest.mark.parametrize(
        ("config", "scores", "expected"),
        [
            ({}, [0.1] * 4, False),  # the default is five
            ({}, [0.1] * 5, True),  # …and scores don't matter
            ({"required_tickets": 2}, [0.5], False),
            ({"required_tickets": 2}, [0.5, 0.5], True),
            (
                {"required_tickets": 2, "require_average": True, "pass_threshold": 0.7},
                [0.5, 0.6],
                False,
            ),
            (
                {"required_tickets": 2, "require_average": True, "pass_threshold": 0.7},
                [0.6, 0.8],
                True,
            ),
            # only the last N count: an early poor ticket is forgiven by improving
            (
                {"required_tickets": 2, "require_average": True, "pass_threshold": 0.7},
                [0.1, 0.7, 0.7],
                True,
            ),
            (
                {"required_tickets": 2, "require_average": True, "pass_threshold": 0.7},
                [0.9, 0.5, 0.5],
                False,
            ),
            ({"required_tickets": "x"}, [0.1] * 5, True),  # junk falls back to the default
            ({"required_tickets": 99}, [0.1] * 20, True),  # …and is capped
        ],
    )
    def test_completes(self, config, scores, expected):
        assert cfg.completes(config, scores) is expected


class TestFinishingTheQuota:
    def run(self, lc, activity, commits, n):
        return [play(lc, activity, [GOOD] * 3, run_commits=commits) for _ in range(n)]

    def test_five_finished_tickets_complete_it_whatever_they_scored(
        self, lc, learner, make_role_user, commits
    ):
        built = course(make_role_user, pass_threshold=1.0)  # no ticket can "pass"
        approved_scenarios(8)
        results = self.run(lc, built["activity"], commits, 4)
        assert all(r["result"]["passed"] is False for r in results)
        assert state(learner, built["activity"]) == "started"
        assert results[-1]["result"]["quota"] == {"done": 4, "required": 5}

        last = self.run(lc, built["activity"], commits, 1)[0]
        assert last["result"]["quota"] == {"done": 5, "required": 5}
        assert state(learner, built["activity"]) == "completed"
        # each attempt still records its own pass/not-pass
        assert not ActivityAttempt.objects.filter(user=learner, passed=True).exists()
        assert ActivityAttempt.objects.filter(user=learner).count() == 5
        # …and the lesson can now be completed
        assert (
            lc.post(reverse("progress_api:lesson-complete", args=[built["second"].pk])).status_code
            == 200
        )
        # completed: no further ticket
        assert post_json(lc, u("start", built["activity"].pk)).status_code == 409

    def test_the_quota_is_configurable(self, lc, learner, make_role_user, commits):
        built = course(make_role_user, required_tickets=2)
        approved_scenarios(4)
        self.run(lc, built["activity"], commits, 1)
        assert state(learner, built["activity"]) == "started"
        self.run(lc, built["activity"], commits, 1)
        assert state(learner, built["activity"]) == "completed"

    def test_when_asked_the_average_must_reach_the_pass_mark(
        self, lc, learner, make_role_user, commits
    ):
        built = course(make_role_user, required_tickets=2, require_average=True, pass_threshold=1.0)
        approved_scenarios(6)
        self.run(lc, built["activity"], commits, 3)
        assert state(learner, built["activity"]) == "started"  # 4.1/5 never averages 5/5

    def test_the_average_rule_completes_when_it_is_met(self, lc, learner, make_role_user, commits):
        built = course(make_role_user, required_tickets=2, require_average=True, pass_threshold=0.8)
        approved_scenarios(4)
        self.run(lc, built["activity"], commits, 2)
        assert state(learner, built["activity"]) == "completed"

    def test_a_cap_below_the_quota_ends_as_exhausted_not_stuck(
        self, lc, learner, make_role_user, commits
    ):
        built = sim_course(make_role_user, max_attempts=2, config={"required_tickets": 5})
        approved_scenarios(6)
        self.run(lc, built["activity"], commits, 2)
        assert state(learner, built["activity"]) == "exhausted"
        assert post_json(lc, u("start", built["activity"].pk)).status_code == 409

    def test_a_ticket_ended_too_early_is_not_counted(self, lc, learner, make_role_user, commits):
        built = course(make_role_user, required_tickets=2)
        approved_scenarios(4)
        with commits():
            sid = post_json(lc, u("start", built["activity"].pk)).json()["id"]
        with commits():
            post_json(lc, u("finish", sid))
        assert ActivityAttempt.objects.count() == 0
        self.run(lc, built["activity"], commits, 1)
        assert state(learner, built["activity"]) == "started"  # one counted, one needed more


class TestSkipping:
    @pytest.fixture
    def world(self, make_role_user):
        built = course(make_role_user, required_tickets=2)
        approved_scenarios(6)
        return built

    def start(self, lc, world, commits):
        with commits():
            return post_json(lc, u("start", world["activity"].pk)).json()

    def skip(self, lc, sid, reason="duplicate"):
        return post_json(lc, u("skip", sid), {"reason": reason})

    def test_a_skip_ends_the_question_without_costing_a_ticket(self, lc, learner, world, commits):
        first = self.start(lc, world, commits)
        reply = self.skip(lc, first["id"], "unclear")
        assert reply.status_code == 200 and reply.json()["state"] == "abandoned"
        assert reply.json()["abandoned_reason"] == "skipped"
        session = SimSession.objects.get(pk=first["id"])
        assert session.skip_reason == "unclear" and session.abandon_reason == "skipped"
        assert ActivityAttempt.objects.count() == 0
        assert state(learner, world["activity"]) in (None, "started")

    def test_the_skipped_question_never_comes_back(self, lc, learner, world, commits):
        seen = set()
        for _ in range(5):  # five skips: the cap; with six questions each one is different
            session = self.start(lc, world, commits)
            seen.add(SimSession.objects.get(pk=session["id"]).scenario_id)
            self.skip(lc, session["id"])
        assert len(seen) == 5

    def test_skipping_twice_is_one_skip(self, lc, world, commits):
        sid = self.start(lc, world, commits)["id"]
        assert self.skip(lc, sid).status_code == 200
        assert self.skip(lc, sid).status_code == 200
        assert SimSession.objects.filter(abandon_reason="skipped").count() == 1

    def test_only_before_a_reply(self, lc, world, commits):
        sid = self.start(lc, world, commits)["id"]
        with commits():
            post_json(lc, u("message", sid), {"text": GOOD, "client_id": str(uuid.uuid4())})
        response = self.skip(lc, sid)
        assert response.status_code == 409 and "before you reply" in response.json()["detail"]

    def test_it_needs_a_reason(self, lc, world, commits):
        sid = self.start(lc, world, commits)["id"]
        assert post_json(lc, u("skip", sid), {}).status_code == 400
        assert self.skip(lc, sid, "boring").status_code == 400

    def test_only_a_few_are_allowed(self, lc, world, commits, settings):
        settings.SIMBOT_SKIPS_PER_ACTIVITY = 2
        for _ in range(2):
            assert self.skip(lc, self.start(lc, world, commits)["id"]).status_code == 200
        sid = self.start(lc, world, commits)["id"]
        response = self.skip(lc, sid)
        assert response.status_code == 409 and "used all 2 skips" in response.json()["detail"]
        assert SimSession.objects.get(pk=sid).state == "open"  # still theirs to answer

    def test_someone_elses_ticket_is_not_found(self, client, lc, world, commits, make_role_user):
        sid = self.start(lc, world, commits)["id"]
        client.force_login(make_role_user(Role.Name.LEARNER, username="o", email="o@e.com"))
        assert self.skip(client, sid).status_code == 404

    def test_a_preview_cannot_be_skipped(self, client, world, commits):
        client.force_login(world["author"])
        with commits():
            sid = post_json(client, u("preview", world["activity"].pk)).json()["id"]
        assert self.skip(client, sid).status_code == 409

    def test_an_ended_ticket_cannot_be_skipped(self, lc, world, commits):
        payload = play(lc, world["activity"], [GOOD] * 3, run_commits=commits)
        assert self.skip(lc, payload["id"]).status_code == 409

    def test_skips_do_not_use_up_the_days_tickets(self, lc, world, commits, settings):
        settings.SIMBOT_DAILY_SESSIONS_PER_USER = 2
        for _ in range(4):
            assert self.skip(lc, self.start(lc, world, commits)["id"]).status_code == 200
        assert post_json(lc, u("start", world["activity"].pk)).status_code == 201

    def test_the_learners_summary_counts_their_skips(self, lc, learner, world, commits):
        self.skip(lc, self.start(lc, world, commits)["id"])
        body = lc.get(reverse("progress_api:course", args=[world["version"].pk])).json()
        assert body["sim"][str(world["activity"].pk)]["skips_used"] == 1


class TestWidelySkippedQuestionsGoBackToATrainer:
    def skipped_by(self, make_role_user, client, world, scenario, reasons, commits):
        for i, reason in enumerate(reasons):
            user = make_role_user(Role.Name.LEARNER, username=f"s{i}", email=f"s{i}@e.com")
            client.force_login(user)
            session = services.start(user, world["activity"].pk)
            # make this learner be dealt that question
            SimSession.objects.filter(pk=session.pk).update(scenario=scenario)
            services.skip(user, session.pk, reason)

    @pytest.fixture
    def world(self, make_role_user):
        built = course(make_role_user, required_tickets=1)
        built["scenarios"] = approved_scenarios(3)
        return built

    def test_three_different_learners_skipping_it_as_unclear(
        self, client, make_role_user, world, commits
    ):
        s = world["scenarios"][0]
        self.skipped_by(make_role_user, client, world, s, ["unclear"] * 2, commits)
        s.refresh_from_db()
        assert s.status == "approved"
        self.skipped_by_more = make_role_user(Role.Name.LEARNER, username="s9", email="s9@e.com")
        session = services.start(self.skipped_by_more, world["activity"].pk)
        SimSession.objects.filter(pk=session.pk).update(scenario=s)
        services.skip(self.skipped_by_more, session.pk, "unclear")
        s.refresh_from_db()
        assert s.status == "draft" and s.review_note == "Skipped as unclear by 3 learners."
        assert s.approved_by is None and not s.auto_approved

    def test_different_reasons_do_not_add_up(self, client, make_role_user, world, commits):
        s = world["scenarios"][0]
        self.skipped_by(
            make_role_user, client, world, s, ["unclear", "duplicate", "not_relevant"], commits
        )
        s.refresh_from_db()
        assert s.status == "approved" and s.review_note == ""

    def test_one_learner_skipping_repeatedly_counts_once(self, make_role_user, world, settings):
        settings.SIMBOT_SKIPS_PER_ACTIVITY = 9
        s = world["scenarios"][0]
        user = make_role_user(Role.Name.LEARNER, username="solo", email="solo@e.com")
        for _ in range(3):
            session = services.start(user, world["activity"].pk)
            SimSession.objects.filter(pk=session.pk).update(scenario=s)
            services.skip(user, session.pk, "unclear")
        s.refresh_from_db()
        assert s.status == "approved"


class TestWhichQuestionComesNext:
    def world(self, make_role_user, **config):
        built = course(make_role_user, **config)
        return built

    def test_a_different_topic_than_the_one_just_had(self, lc, make_role_user, commits):
        built = self.world(make_role_user, required_tickets=3)
        for i in range(3):
            Scenario.objects.create(
                topic="billing", persona_type="urgent", issue_summary=f"billing q{i}",
                opening_message="m", personality_notes="n", status="approved",
            )  # fmt: skip
            Scenario.objects.create(
                topic="alerts", persona_type="urgent", issue_summary=f"alerts q{i}",
                opening_message="m", personality_notes="n", status="approved",
            )  # fmt: skip
        play(lc, built["activity"], [GOOD] * 3, run_commits=commits)
        with commits():
            second = post_json(lc, u("start", built["activity"].pk)).json()["id"]
        topics = list(
            SimSession.objects.filter(user__username="lena")
            .order_by("started_at", "id")
            .values_list("scenario__topic", flat=True)
        )
        assert len(topics) == 2 and topics[0] != topics[1], second

    def test_a_small_bank_repeats_only_when_it_must(self, lc, make_role_user, commits):
        built = self.world(make_role_user, required_tickets=3)
        approved_scenarios(2)
        play(lc, built["activity"], [GOOD] * 3, run_commits=commits)
        play(lc, built["activity"], [GOOD] * 3, run_commits=commits)
        third = play(lc, built["activity"], [GOOD] * 3, run_commits=commits)
        assert SimSession.objects.get(pk=third["id"]).repeated is True
        assert not SimSession.objects.filter(pk__in=[1, 2], repeated=True).exists()

    def test_nothing_left_to_ask_is_said_plainly(self, lc, make_role_user, commits, settings):
        settings.SIMBOT_SKIPS_PER_ACTIVITY = 9
        built = self.world(make_role_user, required_tickets=3)
        approved_scenarios(2)
        for _ in range(2):
            with commits():
                sid = post_json(lc, u("start", built["activity"].pk)).json()["id"]
            post_json(lc, u("skip", sid), {"reason": "duplicate"})
        response = post_json(lc, u("start", built["activity"].pk))
        assert response.status_code == 409 and "no more new questions" in response.json()["detail"]
