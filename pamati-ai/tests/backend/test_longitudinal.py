from datetime import UTC, datetime, timedelta

import pytest
from ai.longitudinal.algorithms import DescriptiveTracking
from ai.longitudinal.interface import Observation, TrackingConfig

START = datetime(2026, 1, 1, tzinfo=UTC)
CONFIG = TrackingConfig(minimum_baseline_interactions=4, minimum_baseline_days=4, baseline_days=28,
                        change_threshold=.25, persistence_days=3)


def series(values, missing=()):
    return tuple(Observation(str(i), str(i), START + timedelta(days=i, hours=12), value)
                 for i, value in enumerate(values) if i not in missing)


def summarize(values, missing=(), config=CONFIG):
    return DescriptiveTracking().summarize(series(values, missing), START, START + timedelta(days=len(values)), config)


def test_stable_pattern():
    result = summarize([.2] * 15)
    final = result["daily"][-1]
    assert final["baseline"]["mean"] == pytest.approx(.2)
    assert final["delta_from_baseline"] == pytest.approx(0)
    assert final["slope_per_day"] == pytest.approx(0)
    assert not any(d["persistent_pattern"] for d in result["daily"])


def test_gradual_change():
    result = summarize([.4] * 8 + [.3, .2, .1, 0, -.1, -.2, -.3])
    assert result["daily"][-1]["slope_per_day"] < 0
    assert result["daily"][-1]["persistent_pattern"]
    assert result["daily"][-1]["delta_from_baseline"] < -.25


def test_temporary_negative_interaction():
    result = summarize([.3] * 8 + [-.8] + [.3] * 5)
    assert result["daily"][8]["change_direction"] == "below_baseline"
    assert not any(d["persistent_pattern"] for d in result["daily"])
    assert result["daily"][-1]["change_direction"] is None


def test_insufficient_history_and_no_future_leakage():
    short = summarize([.1, .2, .3])
    assert all(d["baseline"]["mean"] is None for d in short["daily"])
    result = summarize([.2] * 4 + [-1])
    assert result["daily"][4]["baseline"]["mean"] == pytest.approx(.2)
    assert result["daily"][4]["delta_from_baseline"] == pytest.approx(-1.2)


def test_missing_data_gaps_reset_persistence():
    result = summarize([.3] * 8 + [-.7] * 5, missing=(9,))
    assert result["daily"][9]["mean"] is None
    assert result["daily"][9]["uncertainty"]["missing"]
    assert result["daily"][10]["consecutive_change_days"] == 1
    assert result["weekly"][1]["missing_days"] == 1
    assert not result["weekly"][1]["partial_week"]


def test_recovery_toward_baseline():
    result = summarize([.3] * 8 + [-.7] * 3 + [-.3, 0, .15, .25])
    assert result["daily"][10]["persistent_pattern"]
    assert result["daily"][11]["returning_toward_baseline"]
    assert result["daily"][-1]["change_direction"] is None
    assert not result["daily"][-1]["persistent_pattern"]


def test_interactions_equal_weight_not_message_volume():
    records = (Observation("1", "a", START, 1), Observation("2", "a", START, 1),
               Observation("3", "a", START, 1), Observation("4", "b", START, -1))
    result = DescriptiveTracking().summarize(records, START, START + timedelta(days=1), CONFIG)
    assert result["daily"][0]["mean"] == 0
    assert result["daily"][0]["interaction_count"] == 2
    assert result["daily"][0]["observation_count"] == 4


def test_many_messages_in_one_day_cannot_establish_baseline():
    records = tuple(Observation(str(i), str(i), START, .2) for i in range(20))
    result = DescriptiveTracking().summarize(records, START, START + timedelta(days=2), CONFIG)
    assert result["daily"][1]["baseline"]["status"] == "insufficient_history"


def test_weekly_uses_observed_days_only():
    result = summarize([1, -1, 1, -1, 1, -1, 0], missing=(0, 2, 4))
    assert result["weekly"][0]["mean"] == -1  # Thursday-Sunday partial ISO week, observed Friday/Sunday.
    assert result["weekly"][0]["missing_days"] == 2


@pytest.mark.parametrize("config", [TrackingConfig(change_threshold=0), TrackingConfig(change_threshold=float("nan")),
                                   TrackingConfig(minimum_baseline_days=40), TrackingConfig(persistence_days=1)])
def test_invalid_configuration(config):
    with pytest.raises(ValueError):
        summarize([.1] * 5, config=config)


def test_affect_and_visual_targets_remain_separate():
    from types import SimpleNamespace

    from app.longitudinal import dimensions
    affect = dimensions(SimpleNamespace(modality="audio"), {"emotion_probabilities": {"joy": .2, "sadness": .8},
                                                           "emotion_probability_kind": "exclusive"})
    expression = dimensions(SimpleNamespace(modality="visual"), {"expression_probabilities": {"smiling": .7, "frowning": .3},
                                                                "probability_kind": "exclusive"})
    assert affect == {"affect_exclusive:joy": .2, "affect_exclusive:sadness": .8}
    assert expression == {"expression_exclusive:smiling": .7, "expression_exclusive:frowning": .3}
    with pytest.raises(ValueError):
        dimensions(SimpleNamespace(modality="audio"), {"emotion_probabilities": {"joy": .2}, "emotion_probability_kind": "exclusive"})


def test_replacement_algorithm_registry():
    from ai.longitudinal.registry import TrackingRegistry
    registry = TrackingRegistry()
    class Replacement(DescriptiveTracking):
        identifier = "replacement"
        version = "validated-later"
    registry.register("replacement", Replacement)
    assert registry.resolve("replacement").version == "validated-later"
    with pytest.raises(ValueError):
        registry.register("replacement", Replacement)
