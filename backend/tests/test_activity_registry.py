import pytest

from apps.activities import registry
from apps.catalog.models import Activity


def test_registry_covers_exactly_the_model_activity_types():
    assert set(registry.ACTIVITY_TYPES) == set(Activity.ActivityType.values)


def test_descriptors_are_json_serialisable_and_have_schemas():
    for entry in registry.list_types():
        assert entry["label"] and entry["icon"]
        assert entry["config_schema"]["type"] == "object"


@pytest.mark.parametrize("activity_type", sorted(Activity.ActivityType.values))
def test_default_config_is_valid_in_lenient_mode(activity_type):
    descriptor = registry.ACTIVITY_TYPES[activity_type]
    assert registry.validate_config(activity_type, descriptor.default_config, strict=False) == []


def test_strict_requires_what_lenient_allows_to_be_missing():
    assert registry.validate_config("reading", {}, strict=False) == []
    assert registry.validate_config("reading", {}, strict=True)  # source_url missing
    assert registry.validate_config("mcq", {"questions": []}, strict=False) == []
    assert registry.validate_config("mcq", {"questions": []}, strict=True)  # minItems


def test_lenient_still_catches_wrong_types():
    errors = registry.validate_config("reading", {"estimated_read_minutes": "ten"}, strict=False)
    assert errors and "Estimated read time" in errors[0]


def test_complete_config_passes_strict():
    assert registry.validate_config("reading", {"source_url": "https://x"}, strict=True) == []


def test_unknown_type_and_non_object_config():
    assert registry.validate_config("hologram", {}, strict=False)
    assert registry.validate_config("reading", ["nope"], strict=False)


def test_types_without_constraints_accept_any_object():
    for key in ("pdf", "workshop"):
        assert registry.validate_config(key, {"anything": 1}, strict=True) == []


def test_incomplete_config_messages_use_the_field_titles():
    assert registry.validate_config("reading", {}, strict=True) == [
        "Link to the reading is required."
    ]
    assert registry.validate_config("reading", {"source_url": ""}, strict=True) == [
        "Link to the reading is required."
    ]
    assert registry.validate_config("mcq", {"questions": []}, strict=True) == [
        "Questions needs at least 1 entry."
    ]


def test_only_reading_quiz_video_and_the_two_simulations_are_completable_today():
    # With no config given (the type alone). Where a config exists, `completable_config` also
    # decides: a simulation with no scenario or rubric can never hold a lesson up.
    completable = {k for k in registry.ACTIVITY_TYPES if registry.is_completable(k)}
    assert completable == {"reading", "mcq", "video", "bot_sim", "manual_sim"}
    assert not registry.is_completable("manual_sim", {})
    assert not registry.is_completable("hologram")


def test_a_video_with_nothing_to_watch_cannot_hold_a_lesson_up():
    # Completable as a *type*, but only when its config really points at a video.
    assert not registry.is_completable("video", {})
    assert not registry.is_completable("video", {"video_asset_ref": "old-placeholder"})
    assert not registry.is_completable(
        "video", {"source": "youtube", "youtube_url": "https://x.io"}
    )
    assert registry.is_completable(
        "video", {"source": "youtube", "youtube_url": "https://youtu.be/dQw4w9WgXcQ"}
    )


def test_learner_config_is_an_allow_list():
    config = {"source_url": "https://x", "estimated_read_minutes": 5, "internal": "no"}
    assert registry.learner_config("reading", config) == {
        "source_url": "https://x",
        "estimated_read_minutes": 5,
    }
    assert registry.learner_config("workshop", {"instructions": "x"}) == {}
    assert registry.learner_config("hologram", config) == {}
    assert registry.learner_config("reading", "not a dict") == {}


def test_a_practice_ticket_needs_enough_approved_scenarios_before_it_is_complete(db):
    from apps.bot_sim.models import Scenario

    def make(n):
        for i in range(n):
            Scenario.objects.create(
                topic="billing", persona_type="urgent", issue_summary=f"q{i}",
                opening_message="q", personality_notes="n", status="approved",
            )  # fmt: skip

    problems = registry.validate_config("bot_sim", {}, strict=True)
    assert problems and "No approved practice scenarios" in problems[0]
    make(1)
    # the default asks for five finished tickets, so one scenario is not enough
    problems = registry.validate_config("bot_sim", {}, strict=True)
    assert problems and "must finish 5 tickets, but only 1 approved scenario" in problems[0]
    assert registry.validate_config("bot_sim", {"required_tickets": 1}, strict=True) == []
    make(4)
    assert registry.validate_config("bot_sim", {}, strict=True) == []
