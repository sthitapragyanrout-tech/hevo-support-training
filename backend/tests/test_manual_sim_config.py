"""Mentor-rated simulations, stage 1: the configuration, the rating arithmetic, what a learner
may see of the config, when it may hold a lesson up, and the permissions the module adds."""

import importlib

import pytest
from django.contrib.auth.models import Permission
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.accounts.models import Role
from apps.accounts.rbac import ACTION_LABELS, ADMIN_LOCKED_ACTIONS, KNOWN_ACTIONS, ROLE_PERMISSIONS
from apps.activities import manual_sim as cfg
from apps.activities import registry

CRITERIA = [
    {"key": "c1", "label": "Diagnosis", "description": "Found the cause", "guidance": "5 = exact"},
    {"key": "c2", "label": "Tone", "description": "Kind and clear", "guidance": "RATER ONLY"},
]


def config(**over):
    base = {
        "scenario": "A customer's pipeline stopped.",
        "handin": "Your reply.",
        "criteria": CRITERIA,
    }
    return {**base, **over}


@pytest.fixture
def a_rater(make_role_user):
    return make_role_user(Role.Name.MENTOR, username="m", email="m@e.com")


# ---------------------------------------------------------------- rating arithmetic


class TestTheRating:
    def test_the_overall_is_the_mean_rounded_once_half_up(self):
        eight = [{"key": f"k{i}", "label": f"L{i}"} for i in range(8)]
        scores = dict(zip((c["key"] for c in eight), [4, 3, 3, 3, 3, 3, 3, 3], strict=True))
        # 25 / 8 = 3.125: half-up gives 3.13 (banker's rounding would give 3.12)
        result = cfg.rate({"criteria": eight}, scores)
        assert (result.hundredths, result.raw) == (313, 3.13)

    def test_scaled_is_the_overall_over_five_and_never_a_percentage(self):
        result = cfg.rate(config(), {"c1": 4, "c2": 3})
        assert result.raw == 3.5 and result.scaled == 0.7

    @pytest.mark.parametrize(
        ("scores", "passed"),
        [({"c1": 4, "c2": 3}, True), ({"c1": 3, "c2": 3}, False), ({"c1": 5, "c2": 2}, True)],
    )
    def test_the_pass_mark_is_compared_exactly(self, scores, passed):
        assert cfg.rate(config(pass_threshold=0.7), scores).passed is passed

    def test_just_under_the_pass_mark_does_not_pass(self):
        three = [{"key": f"k{i}", "label": f"L{i}"} for i in range(3)]
        # 10 / 3 = 3.33; a 3.5 mark is not met
        result = cfg.rate({"criteria": three, "pass_threshold": 0.7}, {"k0": 4, "k1": 3, "k2": 3})
        assert result.raw == 3.33 and not result.passed

    def test_a_minimum_per_criterion_can_fail_a_good_average(self):
        scores = {"c1": 5, "c2": 2}  # average 3.5 passes on its own
        assert cfg.rate(config(), scores).passed
        result = cfg.rate(config(min_each=3), scores)
        assert not result.passed and result.below_min == ("c2",)

    def test_a_minimum_of_one_means_off(self):
        assert cfg.min_each({"min_each": 1}) == 0 and cfg.min_each({"min_each": 0}) == 0
        assert cfg.min_each({"min_each": 3}) == 3

    @pytest.mark.parametrize(
        "scores",
        [
            {"c1": 4},
            {"c1": 4, "c2": 3, "c3": 5},
            {"c1": 0, "c2": 3},
            {"c1": 6, "c2": 3},
            {"c1": 4.5, "c2": 3},
            {"c1": True, "c2": 3},
        ],
    )
    def test_every_criterion_needs_a_whole_score_from_one_to_five(self, scores):
        with pytest.raises(ValueError):
            cfg.rate(config(), scores)


# ------------------------------------------------------------------------- config


class TestTheConfig:
    def test_defaults_and_bounds(self):
        assert (
            cfg.pass_threshold({}) == 0.7 and cfg.due_days({}) == 7 and cfg.revision_days({}) == 3
        )
        assert cfg.pass_threshold({"pass_threshold": 9}) == 1.0
        assert cfg.pass_threshold({"pass_threshold": 0}) == cfg.MIN_THRESHOLD
        assert cfg.due_days({"due_days": 0}) == 0  # 0 means no deadline
        assert cfg.due_days({"due_days": 10_000}) == cfg.MAX_DAYS
        assert cfg.allow_files({}) is True and cfg.allow_files({"allow_files": False}) is False

    def test_the_review_window_is_the_activitys_own_or_the_platforms_setting(self, settings):
        settings.MANUAL_SIM_REVIEW_HOURS = 36
        assert cfg.review_hours({}) == 36
        assert cfg.review_hours({"review_hours": 12}) == 12
        assert cfg.review_hours({"review_hours": 0}) == 36

    def test_unusable_criteria_are_ignored_and_the_list_is_capped(self):
        messy = [
            {"key": "a", "label": " "},
            {"label": "no key"},
            "nope",
            {"key": "b", "label": "Ok"},
        ]
        assert [c["key"] for c in cfg.criteria({"criteria": messy})] == ["b"]
        many = [{"key": f"k{i}", "label": f"L{i}"} for i in range(20)]
        assert len(cfg.criteria({"criteria": many})) == cfg.MAX_CRITERIA

    def test_the_pass_rule_is_said_in_words(self):
        assert (
            cfg.pass_rule_text({"pass_threshold": 0.7})
            == "You pass with an average of 3.5 out of 5 or more."
        )
        assert cfg.pass_rule_text({"pass_threshold": 0.8, "min_each": 3}).endswith(
            "and no criterion below 3."
        )


class TestWhatALearnerMaySee:
    def test_the_raters_guidance_never_reaches_a_learner(self):
        shown = registry.learner_config("manual_sim", config(min_each=2, due_days=5))
        assert "guidance" not in str(shown) and "RATER ONLY" not in str(shown)
        assert [c["label"] for c in shown["criteria"]] == ["Diagnosis", "Tone"]
        assert shown["criteria"][0]["description"] == "Found the cause"
        assert shown["pass_rule"].startswith("You pass") and shown["due_days"] == 5

    def test_unknown_config_keys_are_not_passed_through(self):
        shown = registry.learner_config("manual_sim", config(secret_note="x", reference_answer="y"))
        assert "secret_note" not in shown and "reference_answer" not in shown

    def test_a_config_that_is_not_an_object_shows_nothing(self):
        assert registry.learner_config("manual_sim", ["x"]) == {}


# --------------------------------------------------------------- registry behaviour


@pytest.mark.django_db
class TestPublishingAndCompletion:
    def test_it_is_finished_only_by_a_rating_and_has_no_quiz_hooks(self):
        d = registry.get_type("manual_sim")
        assert d.completion == "external" and d.default_max_attempts == 0
        # Quiz and practice-ticket code assumes these are absent for anything a person judges.
        assert d.score is None and d.review is None

    def test_a_scenario_and_a_rubric_are_needed_to_hold_a_lesson_up(self):
        assert not registry.is_completable("manual_sim", {})
        assert not registry.is_completable("manual_sim", {"scenario": "x"})
        assert not registry.is_completable("manual_sim", config(criteria=[]))
        assert registry.is_completable("manual_sim", config())

    def test_publishing_needs_a_rater_to_exist(self):
        problems = registry.validate_config("manual_sim", config(), strict=True)
        assert problems == [
            "No one can rate this yet. Give someone the Mentor role (or another role "
            "that may rate simulations) in Admin → Roles."
        ]

    def test_publishing_passes_once_a_mentor_exists(self, a_rater):
        assert registry.validate_config("manual_sim", config(), strict=True) == []

    def test_a_deactivated_mentor_does_not_count(self, a_rater):
        a_rater.is_active = False
        a_rater.save()
        assert registry.validate_config("manual_sim", config(), strict=True)

    def test_what_is_missing_is_named(self, a_rater):
        assert registry.validate_config("manual_sim", {}, strict=True) == [
            "Scenario for the learner is required."
        ]
        problems = registry.validate_config("manual_sim", {"scenario": "x"}, strict=True)
        assert problems == ["Add at least one rubric criterion, with a label."]
        twice = config(criteria=[{"key": "a", "label": "A"}, {"key": "a", "label": "B"}])
        assert registry.validate_config("manual_sim", twice, strict=True) == [
            "Each rubric criterion needs its own key."
        ]

    def test_a_draft_may_be_unfinished(self):
        assert registry.validate_config("manual_sim", {}, strict=False) == []
        assert registry.validate_config("manual_sim", {"pass_threshold": "high"}, strict=False)


# -------------------------------------------------------------------- permissions


class TestThePermissions:
    def test_both_are_in_the_catalogue_with_words_for_the_matrix(self):
        for action in ("manual_sim.rate_submissions", "manual_sim.manage_reviews"):
            assert action in KNOWN_ACTIONS and ACTION_LABELS[action][0] and ACTION_LABELS[action][1]

    def test_who_gets_what_by_default(self):
        rate, manage = "manual_sim.rate_submissions", "manual_sim.manage_reviews"
        assert rate in ROLE_PERMISSIONS["mentor"] and manage not in ROLE_PERMISSIONS["mentor"]
        for name in ("trainer", "admin"):
            assert {rate, manage} <= set(ROLE_PERMISSIONS[name])
        assert not ROLE_PERMISSIONS["learner"]

    def test_an_admin_can_never_lose_the_power_to_intervene(self):
        assert "manual_sim.manage_reviews" in ADMIN_LOCKED_ACTIONS

    @pytest.mark.django_db
    def test_the_rows_exist_after_migrating(self):
        found = Permission.objects.filter(content_type__app_label="manual_sim")
        assert {"rate_submissions", "manage_reviews"} <= set(
            found.values_list("codename", flat=True)
        )


@pytest.mark.django_db
class TestTheOneTimeGrantMigration:
    """The migration adds the permissions to roles that already exist, without touching what
    else they hold and without touching custom roles. (A run from a database that predates
    the app was also done by hand against a throwaway database.)"""

    def migration(self):
        module = importlib.import_module("apps.manual_sim.migrations.0002_grant_rating_permissions")
        state = MigrationExecutor(connection).loader.project_state(
            [("manual_sim", "0002_grant_rating_permissions")]
        )
        return module, state.apps

    def codes(self, role):
        return {p.codename for p in role.permissions.filter(content_type__app_label="manual_sim")}

    def test_it_is_additive_and_leaves_custom_roles_alone(self):
        module, historical = self.migration()
        extra = Permission.objects.get(content_type__app_label="accounts", codename="view_user")
        trainer = Role.objects.create(name="trainer")
        trainer.permissions.add(extra)
        mentor = Role.objects.create(name="mentor")
        custom = Role.objects.create(name="senior_support", label="Senior support")
        module.grant(historical, None)
        assert self.codes(trainer) == {"rate_submissions", "manage_reviews"}
        assert extra in trainer.permissions.all()  # what the role already held survives
        assert self.codes(mentor) == {"rate_submissions"}
        assert self.codes(custom) == set()

    def test_roles_that_do_not_exist_yet_are_skipped_and_running_twice_is_harmless(self):
        module, historical = self.migration()
        module.grant(historical, None)
        module.grant(historical, None)
        admin = Role.objects.create(name="admin")
        module.grant(historical, None)
        assert self.codes(admin) == {"rate_submissions", "manage_reviews"}

    def test_reversing_removes_only_these_from_the_built_in_roles(self):
        module, historical = self.migration()
        trainer = Role.objects.create(name="trainer")
        module.grant(historical, None)
        module.revoke(historical, None)
        assert self.codes(trainer) == set()
