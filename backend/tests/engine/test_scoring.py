"""The scoring contract: one function turns replies into the result document, and
every number in it is consistent with every other."""

import random
from datetime import timedelta
from fractions import Fraction

import pytest

from simbot_engine import outcome
from simbot_engine.config import DEFAULT_TAT_BANDS, DEFAULT_WEIGHTS, METRIC_KEYS, EngineConfig
from simbot_engine.evaluator import TurnScores, clamp, tat_label, tat_score
from simbot_engine.llm import BadModelOutput
from simbot_engine.scenario import Scenario
from simbot_engine.session import CUSTOMER, INTERN, Turn
from tests.engine.runner import SCENARIO, T0

CONFIG = EngineConfig()


def scores(c=4, e=4, a=4, k=4, tat=4, tat_seconds=500, docs=None, notes=None, flags=()):
    return TurnScores(
        communication=c,
        empathy=e,
        accuracy=a,
        concreteness=k,
        tat=tat,
        tat_seconds=tat_seconds,
        notes=notes or {},
        docs_relevance=docs,
        flags=list(flags),
    )


def conversation(per_turn, texts=None):
    """Customer opens, then each intern reply carries the given scores."""
    turns = [Turn(1, CUSTOMER, SCENARIO.opening_message, T0)]
    for i, s in enumerate(per_turn):
        text = (texts or {}).get(i, "Here is how you do it: open Sources and pick MySQL.")
        turns.append(Turn(len(turns) + 1, INTERN, text, T0 + timedelta(minutes=i + 1), scores=s))
        turns.append(Turn(len(turns) + 1, CUSTOMER, "ok", T0 + timedelta(minutes=i + 1, seconds=3)))
    return turns


def build(per_turn, threshold=0.7, scenario=SCENARIO, texts=None, config=CONFIG):
    return outcome.build(
        conversation(per_turn, texts), config=config, scenario=scenario, pass_threshold=threshold
    )


class TestTurnaround:
    @pytest.mark.parametrize(
        "seconds,score,label",
        [
            (0, 5, "excellent"),
            (300, 5, "excellent"),
            (301, 4, "good"),
            (600, 4, "good"),
            (601, 3, "acceptable"),
            (900, 3, "acceptable"),
            (901, 2, "slow"),
            (1800, 2, "slow"),
            (1801, 1, "very slow"),
            (10**6, 1, "very slow"),
        ],
    )
    def test_bands(self, seconds, score, label):
        assert tat_score(seconds, DEFAULT_TAT_BANDS) == score
        assert tat_label(seconds, DEFAULT_TAT_BANDS) == label


class TestClamp:
    @pytest.mark.parametrize(
        "raw,expected", [(0, 1), (-3, 1), (1, 1), (3.4, 3), (3.6, 4), (5, 5), (9, 5), ("4", 4)]
    )
    def test_clamp(self, raw, expected):
        assert clamp(raw) == expected

    @pytest.mark.parametrize("bad", [None, "high", [], {}, float("nan")])
    def test_not_numbers(self, bad):
        with pytest.raises(BadModelOutput):
            clamp(bad)


class TestWeights:
    def test_they_add_up_to_one_and_cover_every_metric(self):
        assert sum(Fraction(str(w)) for w in DEFAULT_WEIGHTS.values()) == 1
        assert set(DEFAULT_WEIGHTS) == set(METRIC_KEYS)

    def test_a_broken_set_of_weights_is_refused(self):
        bad = EngineConfig(weights={**DEFAULT_WEIGHTS, "accuracy": 0.5})
        with pytest.raises(ValueError):
            build([scores(), scores()], config=bad)


class TestRoundingAndPassMark:
    def test_half_up_in_hundredths(self):
        assert outcome.round_hundredths(Fraction(3495, 1000)) == 350
        assert outcome.round_hundredths(Fraction(3494, 1000)) == 349
        assert outcome.round_hundredths(Fraction(3505, 1000)) == 351
        assert outcome.round_hundredths(Fraction(1)) == 100

    def test_the_default_pass_mark_is_exactly_three_and_a_half_out_of_five(self):
        assert outcome.passes(350, 0.7)
        assert not outcome.passes(349, 0.7)
        result = build([scores(), scores()])
        assert result["pass_mark"] == {"raw": 3.5, "scaled": 0.7}

    @pytest.mark.parametrize(
        "threshold,raw_h,expected",
        [
            (0.4, 200, True),
            (0.4, 199, False),
            (1.0, 500, True),
            (1.0, 499, False),
            (0.733, 367, True),
            (0.733, 366, False),
        ],
    )
    def test_other_pass_marks(self, threshold, raw_h, expected):
        assert outcome.passes(raw_h, threshold) is expected

    def test_a_score_sitting_exactly_on_a_half_hundredth_rounds_up(self):
        # communication averages 4.5 and everything else is 4 (docs: no link = 1), so
        # overall = .15*4.5 + .15*4 + .25*4 + .20*4 + .10*4 + .15*1 = 3.625 exactly.
        r = build([scores(c=4), scores(c=5)])
        assert r["score"]["raw"] == 3.63  # half-up, not banker's rounding or float luck
        assert r["score"]["scaled"] == pytest.approx(3.63 / 5)
        assert r["passed"] is True  # 3.63 ≥ 3.50

    def test_just_under_the_pass_mark_fails(self):
        # all fours but no docs link: .15*4 + .15*4 + .25*4 + .20*4 + .10*4 + .15*1 = 3.55
        assert build([scores(), scores()])["passed"] is True
        weak = build([scores(c=3, e=3, a=3, k=3, tat=3), scores(c=3, e=3, a=3, k=3, tat=3)])
        assert weak["score"]["raw"] == 2.7 and weak["passed"] is False

    def test_overall_scaled_and_passed_agree_for_many_random_sessions(self):
        rng = random.Random(7)
        for _ in range(300):
            n = rng.randint(2, 6)
            per = [
                scores(*(rng.randint(1, 5) for _ in range(5)), tat_seconds=rng.randint(0, 3000))
                for _ in range(n)
            ]
            thr = rng.choice([0.4, 0.5, 0.7, 0.75, 0.9, 1.0])
            texts = {i: "see https://docs.hevodata.com/x" for i in range(n) if rng.random() < 0.3}
            r = build(per, thr, texts=texts)
            raw, scaled = r["score"]["raw"], r["score"]["scaled"]
            assert 1.0 <= raw <= 5.0
            assert scaled == pytest.approx(raw / 5)
            assert r["passed"] == (Fraction(str(raw)) >= Fraction(str(thr)) * 5)
            assert r["score"]["max"] == 5
            # recomputing the weighted mean from the published metrics lands within rounding
            rebuilt = sum(DEFAULT_WEIGHTS[m["key"]] * m["raw"] for m in r["metrics"])
            assert abs(rebuilt - raw) <= 0.0125  # six metrics each rounded to 2 dp

    def test_it_is_deterministic(self):
        per = [scores(5, 3, 4, 2, 5), scores(4, 4, 4, 4, 4), scores(1, 2, 3, 4, 5)]
        assert build(per) == build(per)


class TestEvidence:
    def test_too_few_replies_is_not_a_result(self):
        with pytest.raises(outcome.NotEnoughEvidence):
            build([scores()])
        with pytest.raises(outcome.NotEnoughEvidence):
            outcome.build(conversation([]), config=CONFIG, scenario=SCENARIO, pass_threshold=0.7)

    def test_an_unscored_reply_blocks_the_result(self):
        turns = conversation([scores(), scores()])
        turns[3].scores = None
        with pytest.raises(outcome.PendingScores):
            outcome.build(turns, config=CONFIG, scenario=SCENARIO, pass_threshold=0.7)

    def test_the_minimum_is_configurable(self):
        one = EngineConfig(min_scored_exchanges=1)
        assert build([scores()], config=one)["exchanges"] == 1


class TestDocsReferenced:
    def test_no_link_scores_one(self):
        m = {m["key"]: m for m in build([scores(), scores()])["metrics"]}["reference_docs"]
        assert m["raw"] == 1.0 and m["basis"] == "link_check"
        assert "No documentation link" in m["feedback"]

    def test_a_link_to_another_site_scores_two(self):
        texts = {0: "Try https://example.com/guide"}
        m = {m["key"]: m for m in build([scores(), scores()], texts=texts)["metrics"]}[
            "reference_docs"
        ]
        assert m["raw"] == 2.0 and "not to docs.hevodata.com" in m["feedback"]

    @pytest.mark.parametrize("relevance,expected", [(0, 3.0), (1, 4.0), (2, 5.0)])
    def test_a_docs_link_scores_three_plus_relevance(self, relevance, expected):
        texts = {1: "Docs: https://docs.hevodata.com/sources/mysql/"}
        per = [scores(), scores(docs=relevance)]
        m = {m["key"]: m for m in build(per, texts=texts)["metrics"]}["reference_docs"]
        assert m["raw"] == expected
        assert m["basis"] == "link_check+model_relevance"
        assert "wasn't opened" in m["feedback"]  # never claims the page was checked

    def test_a_late_link_counts_as_much_as_an_early_one(self):
        early = build([scores(docs=2), scores()], texts={0: "https://docs.hevodata.com/a"})
        late = build([scores(), scores(docs=2)], texts={1: "https://docs.hevodata.com/a"})
        pick = lambda r: {m["key"]: m for m in r["metrics"]}["reference_docs"]["raw"]  # noqa: E731
        assert pick(early) == pick(late) == 5.0

    def test_a_lookalike_host_does_not_get_docs_credit(self):
        texts = {0: "https://docs.hevodata.com.evil.io/mysql"}
        m = {m["key"]: m for m in build([scores(docs=2), scores()], texts=texts)["metrics"]}[
            "reference_docs"
        ]
        assert m["raw"] == 2.0


class TestHonestyOfTheResult:
    def test_unverified_accuracy_is_labelled_as_model_judgment(self):
        r = build([scores(), scores()])
        by = {m["key"]: m for m in r["metrics"]}
        assert r["grounded"] is False
        assert by["accuracy"]["basis"] == "model_judgment"
        assert by["tat"]["basis"] == "deterministic"
        assert {by[k]["basis"] for k in ("communication", "empathy", "concreteness")} == {
            "model_judgment"
        }

    def test_a_scenario_with_a_reference_answer_is_grounded(self):
        grounded = Scenario(
            **{**SCENARIO.__dict__, "reference_answer": "Open Sources, pick MySQL…"}
        )
        r = build([scores(), scores()], scenario=grounded)
        assert r["grounded"] is True
        assert {m["key"]: m for m in r["metrics"]}["accuracy"]["basis"] == "grounded"

    def test_the_document_has_the_halo_shape_and_metric_order(self):
        r = build([scores(), scores()])
        assert [m["key"] for m in r["metrics"]] == list(METRIC_KEYS)
        assert set(r) >= {
            "score",
            "pass_mark",
            "passed",
            "metrics",
            "narrative",
            "grounded",
            "scenario_ref",
        }
        assert all(
            set(m) == {"key", "label", "raw", "max", "feedback", "basis"} for m in r["metrics"]
        )

    def test_feedback_quotes_the_weakest_reply(self):
        per = [
            scores(c=5, notes={"communication": "great"}),
            scores(c=2, notes={"communication": "typos"}),
        ]
        by = {m["key"]: m for m in build(per)["metrics"]}
        assert by["communication"]["feedback"] == "typos"

    def test_turnaround_feedback_states_minutes_and_ideal(self):
        per = [scores(tat_seconds=600), scores(tat_seconds=1200)]
        fb = {m["key"]: m for m in build(per)["metrics"]}["tat"]["feedback"]
        assert "15.0 min" in fb and "ideal" in fb


class TestReviewFlags:
    def test_injection_and_copy_flags_surface_for_trainers(self):
        r = build([scores(flags=["injection_suspected"]), scores(flags=["too_short"])])
        assert r["needs_review"] and r["review_reasons"] == ["injection_suspected"]

    def test_a_perfect_score_from_a_very_short_session_is_flagged(self):
        s = scores(5, 5, 5, 5, 5)
        # tat 5 + docs: 5 needs a docs link with relevance 2
        r = build([s, s], texts={0: "https://docs.hevodata.com/x"})
        r2 = build([scores(5, 5, 5, 5, 5, docs=2)] * 2, texts={0: "https://docs.hevodata.com/x"})
        assert r2["score"]["raw"] == 5.0 and "perfect_short_session" in r2["review_reasons"]
        assert r["score"]["raw"] < 5.0

    def test_an_ordinary_session_is_not_flagged(self):
        assert build([scores(), scores()])["needs_review"] is False
