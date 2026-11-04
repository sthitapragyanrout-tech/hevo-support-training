"""One scoring contract, three places it is stored or shown: the session's result
document, the API response and the attempt row. They must always say the same
thing, on the same scale, with the same verdict."""

import random
from fractions import Fraction

import pytest

from apps.accounts.models import Role
from apps.activities import registry
from apps.bot_sim import services
from apps.progress.models import ActivityAttempt, ActivityProgress
from simbot_engine.llm import FakeLLM
from tests.sim_helpers import approved_scenarios, scored_session, sim_course, turn_scores, u

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _scenarios():
    approved_scenarios(2)


def run(make_role_user, rows, *, threshold=0.7, texts=None, n=0):
    built = sim_course(
        make_role_user, config={"pass_threshold": threshold}, title=f"S{n}", max_attempts=5
    )
    user = make_role_user(Role.Name.LEARNER, username=f"u{n}", email=f"u{n}@e.com")
    session = scored_session(user, built["activity"], rows, texts=texts)
    services.finalize(session.pk, inner=FakeLLM())
    session.refresh_from_db()
    return user, built, session


NO_LINK = {
    0: "Open Sources and pick MySQL, then enter the host.",
    1: "Then add the user and the port.",
}


def api_result(client, user, session):
    client.force_login(user)
    return client.get(u("result", session.pk)).json()["result"]


class TestTheThreeAgree:
    def test_for_many_sessions_and_pass_marks(self, client, make_role_user):
        rng = random.Random(11)
        for n in range(40):
            rows = [
                turn_scores(
                    *(rng.randint(1, 5) for _ in range(5)), tat_seconds=rng.randint(0, 2400)
                )
                for _ in range(rng.randint(2, 6))
            ]
            threshold = rng.choice([0.4, 0.55, 0.7, 0.73, 0.85, 1.0])
            texts = {
                i: "see https://docs.hevodata.com/x" for i in range(len(rows)) if rng.random() < 0.3
            }
            user, built, session = run(make_role_user, rows, threshold=threshold, texts=texts, n=n)
            assert session.state == "finished", n

            result = session.result
            shown = api_result(client, user, session)
            attempt = ActivityAttempt.objects.get(user=user, activity=built["activity"])

            # the API returns the stored document, minus trainer-only fields
            assert shown == {
                k: v
                for k, v in result.items()
                if k not in ("needs_review", "review_reasons", "scenario_ref")
            }
            raw, scaled = result["score"]["raw"], result["score"]["scaled"]
            assert 1.0 <= raw <= 5.0 and result["score"]["max"] == 5
            assert scaled == pytest.approx(raw / 5)
            assert attempt.score == scaled and attempt.passed is result["passed"]
            assert result["passed"] == (Fraction(str(raw)) >= Fraction(str(threshold)) * 5)
            assert result["pass_mark"] == {"raw": pytest.approx(threshold * 5), "scaled": threshold}
            expected_state = "completed" if result["passed"] else "started"
            assert (
                ActivityProgress.objects.get(user=user, activity=built["activity"]).state
                == expected_state
            )

    def test_the_default_pass_mark_is_three_and_a_half_out_of_five(self, make_role_user):
        user, built, session = run(make_role_user, [turn_scores()] * 2)
        assert session.result["pass_mark"] == {"raw": 3.5, "scaled": 0.7}
        assert registry.learner_config("bot_sim", built["activity"].config)["pass_mark"] == {
            "raw": 3.5,
            "scaled": 0.7,
            "max": 5,
        }

    def test_the_boundary_is_exact_either_side(self, make_role_user):
        # communication averages 4.5, the rest 4, no docs link → exactly 3.625 → 3.63 (half-up)
        rows = [turn_scores(c=4, tat=4), turn_scores(c=5, tat=4)]
        _, _, at = run(make_role_user, rows, threshold=0.726, texts=NO_LINK, n=1)  # 3.63 needed
        _, _, over = run(
            make_role_user, rows, threshold=0.7261, texts=NO_LINK, n=2
        )  # 3.6305 needed
        assert at.result["score"]["raw"] == over.result["score"]["raw"] == 3.63
        assert at.result["passed"] is True and over.result["passed"] is False

    def test_a_pass_completes_and_a_fail_leaves_tries(self, make_role_user):
        user, built, passed = run(
            make_role_user,
            [turn_scores(5, 5, 5, 5, 5)] * 2,
            texts={0: "https://docs.hevodata.com/x"},
            n=3,
        )
        assert passed.result["passed"] and passed.result["attempts_left"] == 4
        user, built, failed = run(make_role_user, [turn_scores(1, 1, 1, 1, 1)] * 2, n=4)
        assert not failed.result["passed"] and failed.result["attempts_left"] == 4
        assert (
            ActivityProgress.objects.get(user=user, activity=built["activity"]).state == "started"
        )

    def test_what_the_learner_is_shown_is_honest_about_what_was_checked(
        self, client, make_role_user
    ):
        user, _, session = run(make_role_user, [turn_scores()] * 2, texts=NO_LINK, n=5)
        shown = api_result(client, user, session)
        by = {m["key"]: m for m in shown["metrics"]}
        assert shown["grounded"] is False and by["accuracy"]["basis"] == "model_judgment"
        assert by["reference_docs"]["label"] == "Docs referenced"
        assert by["reference_docs"]["basis"] == "link_check"
        assert "needs_review" not in shown

    def test_the_trainer_sees_what_the_learner_does_not(self, client, make_role_user):
        flagged = [turn_scores(flags=["injection_suspected"]), turn_scores()]
        user, _, session = run(make_role_user, flagged, n=6)
        assert session.result["needs_review"] and session.result["review_reasons"] == [
            "injection_suspected"
        ]
        trainer = make_role_user(Role.Name.TRAINER, username="tr", email="tr@e.com")
        client.force_login(trainer)
        from django.urls import reverse

        body = client.get(reverse("console_api:practice-session", args=[session.pk])).json()
        assert body["result"]["needs_review"] and body["turns"][1]["scores"]["communication"] == 4
        client.force_login(user)
        assert (
            client.get(reverse("console_api:practice-session", args=[session.pk])).status_code
            == 403
        )


class TestResultNotReadyYet:
    def test_the_result_endpoint_says_so_until_it_exists(self, client, make_role_user):
        built = sim_course(make_role_user)
        user = make_role_user(Role.Name.LEARNER, username="x", email="x@e.com")
        session = scored_session(
            user, built["activity"], [turn_scores()] * 2
        )  # finishing, not finalised
        client.force_login(user)
        response = client.get(u("result", session.pk))
        assert response.status_code == 409 and response.json()["state"] == "finishing"
        payload = client.get(u("session", session.pk)).json()
        assert payload["feedback_pending"] is True and payload["result"] is None


class TestRegistry:
    def test_completion_kind_and_what_a_learner_may_see(self):
        d = registry.get_type("bot_sim")
        assert d.completion == "external" and d.default_max_attempts == 3
        view = registry.learner_config(
            "bot_sim",
            {
                "persona": "urgent",
                "topics": ["billing"],
                "pass_threshold": 0.8,
                "max_exchanges": 4,
                "secret": 1,
            },
        )
        # how long it is and what completing takes — never the persona, topics or other config
        assert set(view) == {
            "max_exchanges", "pass_mark", "required_tickets", "skips_allowed", "require_average",
        }  # fmt: skip
        assert view["max_exchanges"] == 4 and view["required_tickets"] == 5
        assert view["require_average"] is False

    @pytest.mark.parametrize(
        "config",
        [
            {"persona": "angry"},
            {"topics": ["weather"]},
            {"pass_threshold": 2},
            {"pass_threshold": 0.1},
            {"max_exchanges": 9},
            {"max_exchanges": 1},
        ],
    )
    def test_bad_settings_are_refused(self, config):
        assert registry.validate_config("bot_sim", config, strict=False)

    def test_a_practice_ticket_holds_a_lesson_up_only_when_the_feature_is_on(self, settings):
        assert registry.is_completable("bot_sim", {})
        settings.SIMBOT_ENABLED = False
        assert not registry.is_completable("bot_sim", {})
