"""Quiz rules in isolation: what learners may see, how answers are judged,
what makes a quiz publishable. (Recording attempts is test_quiz_attempts.)"""

import pytest

from apps.activities import quiz, registry

QUESTIONS = [
    {"text": "Pick one", "choices": ["A", "B", "C"], "answer": 1, "explanation": "B is right."},
    {"text": "Pick all", "choices": ["W", "X", "Y"], "answer": [0, 2]},
    {"text": "Pick one again", "choices": ["P", "Q"], "answer": 0},
]


def config(**extra):
    return {"questions": QUESTIONS, **extra}


class TestLearnerView:
    def test_questions_and_choices_yes_answer_key_never(self):
        view = quiz.learner_view(config(pass_threshold=0.5))
        assert view["pass_threshold"] == 0.5
        assert view["questions"][0] == {
            "text": "Pick one",
            "choices": ["A", "B", "C"],
            "multiple": False,
        }
        assert view["questions"][1]["multiple"] is True
        raw = repr(view)
        assert "answer" not in raw and "explanation" not in raw and "B is right" not in raw

    def test_registry_uses_the_projection(self):
        assert registry.learner_config("mcq", config()) == quiz.learner_view(config())

    def test_malformed_config_degrades_to_nothing_to_answer(self):
        assert quiz.learner_view({})["questions"] == []
        assert quiz.learner_view({"questions": "nope"})["questions"] == []
        assert quiz.learner_view({"questions": [1, None]})["questions"] == []


class TestScoring:
    def test_all_correct(self):
        result, answers = quiz.judge(config(), [[1], [0, 2], [0]])
        assert (result.correct, result.total, result.score, result.passed) == (3, 3, 1.0, True)
        assert answers == [[1], [0, 2], [0]]

    def test_a_multi_answer_must_match_exactly(self):
        for picked in ([0], [0, 1, 2], [1, 2]):
            result, _ = quiz.judge(config(), [[1], picked, [0]])
            assert result.results == [True, False, True]

    def test_choice_order_does_not_matter(self):
        result, answers = quiz.judge(config(), [[1], [2, 0], [0]])
        assert result.passed and answers[1] == [0, 2]

    @pytest.mark.parametrize(
        ("threshold", "passed"),
        [
            (0.7, False),
            (0.68, False),
            (0.67, True),
            (0.66, True),
            (2 / 3, True),
            (0, True),
            (1, False),
        ],
    )
    def test_threshold_boundary(self, threshold, passed):
        result, _ = quiz.judge(config(pass_threshold=threshold), [[1], [0, 2], [1]])  # 2 of 3
        assert result.correct == 2
        assert result.passed is passed

    def test_default_pass_mark_is_70_percent(self):
        assert quiz.pass_threshold({}) == 0.7
        assert quiz.pass_threshold({"pass_threshold": "high"}) == 0.7
        assert quiz.pass_threshold({"pass_threshold": True}) == 0.7

    def test_required_correct_is_what_the_learner_is_told(self):
        assert quiz.required_correct(config(pass_threshold=0.8)) == 3
        assert quiz.required_correct(config(pass_threshold=0.67)) == 2  # 2 of 3 is 67%
        assert quiz.required_correct(config(pass_threshold=0.5)) == 2
        assert quiz.required_correct(config(pass_threshold=0)) == 0
        assert quiz.required_correct({"questions": []}) == 0

    def test_an_empty_quiz_can_never_be_passed(self):
        result, _ = quiz.judge({"questions": []}, [])
        assert result.passed is False


class TestAnswerValidation:
    @pytest.mark.parametrize(
        "answers",
        [
            None,
            "x",
            [],
            [[1], [0]],  # too few
            [[1], [0], [0], [0]],  # too many
            [[], [0], [0]],  # unanswered
            [1, [0], [0]],  # not lists
            [["1"], [0], [0]],  # not ints
            [[True], [0], [0]],  # bools are not indexes
            [[5], [0], [0]],  # out of range
            [[-1], [0], [0]],
            [[0, 1], [0], [0]],  # two picks on a single-answer question
        ],
    )
    def test_bad_submissions_are_refused_with_a_readable_message(self, answers):
        with pytest.raises(quiz.InvalidAnswers) as err:
            quiz.judge(config(), answers)
        assert str(err.value)[-1] == "."

    def test_duplicates_collapse(self):
        _, answers = quiz.judge(config(), [[1], [0, 0, 2], [0]])
        assert answers[1] == [0, 2]


class TestReview:
    def test_without_reveal_only_right_or_wrong(self):
        result, _ = quiz.judge(config(), [[0], [0, 2], [0]])
        review = quiz.review(config(), result, reveal=False)
        assert review == [{"correct": False}, {"correct": True}, {"correct": True}]

    def test_with_reveal_the_key_and_explanations_come_out(self):
        result, _ = quiz.judge(config(), [[0], [0, 2], [0]])
        review = quiz.review(config(), result, reveal=True)
        assert review[0] == {"correct": False, "correct_answers": [1], "explanation": "B is right."}
        assert review[1] == {"correct": True, "correct_answers": [0, 2]}  # no explanation authored


class TestAuthoringValidation:
    def test_a_complete_quiz_is_publishable(self):
        assert registry.validate_config("mcq", config(), strict=True) == []

    def test_an_unfinished_quiz_saves_but_is_flagged(self):
        draft = {"questions": [{"text": "", "choices": ["only"], "answer": []}]}
        assert registry.validate_config("mcq", draft, strict=False) == []
        problems = registry.validate_config("mcq", draft, strict=True)
        assert "Question 1 needs some text." in problems
        assert "Question 1 needs at least 2 choices." in problems
        assert "Question 1 needs a correct answer." in problems

    def test_a_correct_answer_must_be_one_of_the_choices(self):
        bad = {"questions": [{"text": "Q", "choices": ["a", "b"], "answer": 4}]}
        assert registry.validate_config("mcq", bad, strict=True) == [
            "Question 1 has a correct answer that isn’t one of its choices."
        ]

    def test_wrong_types_are_refused_even_while_drafting(self):
        errors = registry.validate_config(
            "mcq", {"questions": [{"text": "Q", "choices": "ab", "answer": "x"}]}, strict=False
        )
        assert errors and "Questions, item 1" in errors[0]

    def test_pass_mark_must_be_a_fraction(self):
        assert registry.validate_config("mcq", config(pass_threshold=1.5), strict=False)

    def test_new_quizzes_default_to_unlimited_attempts(self):
        assert registry.get_type("mcq").default_max_attempts == 0
        assert registry.get_type("reading").default_max_attempts == 3
