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
    for key in ("pdf", "workshop", "manual_sim", "bot_sim"):
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


def test_only_reading_and_quiz_are_completable_today():
    completable = {k for k in registry.ACTIVITY_TYPES if registry.is_completable(k)}
    assert completable == {"reading", "mcq"}
    assert not registry.is_completable("hologram")


def test_learner_config_is_an_allow_list():
    config = {"source_url": "https://x", "estimated_read_minutes": 5, "internal": "no"}
    assert registry.learner_config("reading", config) == {
        "source_url": "https://x",
        "estimated_read_minutes": 5,
    }
    assert registry.learner_config("workshop", {"instructions": "x"}) == {}
    assert registry.learner_config("hologram", config) == {}
    assert registry.learner_config("reading", "not a dict") == {}
