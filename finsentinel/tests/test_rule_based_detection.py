
"""Tests for explainable rule-based update anomaly detection."""

import math

import pytest

from detection.rule_based import (
    RuleBasedDetectionConfig,
    detect_update_anomalies,
)


def test_normal_update_has_no_anomaly():
    config = RuleBasedDetectionConfig(
        max_weight_l2_norm=10.0,
        max_update_l2_norm=2.0,
        max_weight_abs_mean=1.0,
    )
    features = {
        "weight_l2_norm": 5.0,
        "update_l2_norm": 0.5,
        "weight_abs_mean": 0.2,
    }

    result = detect_update_anomalies(features, config=config)

    assert result.risk_score == 0
    assert result.severity == "LOW"
    assert result.suspicious is False
    assert result.reasons == ()


def test_flags_excessive_update_norm():
    config = RuleBasedDetectionConfig(max_update_l2_norm=2.0)
    features = {"update_l2_norm": 5.0}

    result = detect_update_anomalies(features, config=config)

    assert result.risk_score == 25
    assert result.severity == "MEDIUM"
    assert result.suspicious is True
    assert len(result.reasons) == 1
    assert "Update L2 norm" in result.reasons[0]


def test_flags_multiple_threshold_violations():
    config = RuleBasedDetectionConfig(
        max_weight_l2_norm=10.0,
        max_update_l2_norm=2.0,
        max_weight_abs_mean=1.0,
        max_weight_std=3.0,
    )
    features = {
        "weight_l2_norm": 15.0,
        "update_l2_norm": 5.0,
        "weight_abs_mean": 0.5,
        "weight_std": 4.0,
    }

    result = detect_update_anomalies(features, config=config)

    assert result.risk_score == 75
    assert result.severity == "CRITICAL"
    assert result.suspicious is True
    assert len(result.reasons) == 3


def test_threshold_boundary_is_not_flagged():
    config = RuleBasedDetectionConfig(max_update_l2_norm=2.0)

    result = detect_update_anomalies(
        {"update_l2_norm": 2.0},
        config=config,
    )

    assert result.suspicious is False
    assert result.risk_score == 0


def test_flags_zero_fraction_above_maximum():
    config = RuleBasedDetectionConfig(max_weight_zero_fraction=0.8)

    result = detect_update_anomalies(
        {"weight_zero_fraction": 0.9},
        config=config,
    )

    assert result.suspicious is True
    assert "unusually high" in result.reasons[0]


def test_flags_zero_fraction_below_minimum():
    config = RuleBasedDetectionConfig(min_weight_zero_fraction=0.1)

    result = detect_update_anomalies(
        {"weight_zero_fraction": 0.05},
        config=config,
    )

    assert result.suspicious is True
    assert "unusually low" in result.reasons[0]


def test_rejects_empty_features():
    config = RuleBasedDetectionConfig(max_update_l2_norm=2.0)

    with pytest.raises(ValueError, match="non-empty"):
        detect_update_anomalies({}, config=config)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), -float("inf")])
def test_rejects_non_finite_feature_values(bad_value):
    config = RuleBasedDetectionConfig(max_update_l2_norm=2.0)

    with pytest.raises(ValueError, match="must be finite"):
        detect_update_anomalies(
            {"update_l2_norm": bad_value},
            config=config,
        )


def test_rejects_boolean_feature_value():
    config = RuleBasedDetectionConfig(max_update_l2_norm=2.0)

    with pytest.raises(ValueError, match="must be numeric"):
        detect_update_anomalies(
            {"update_l2_norm": True},
            config=config,
        )


def test_rejects_missing_feature_required_by_rule():
    config = RuleBasedDetectionConfig(max_update_l2_norm=2.0)

    with pytest.raises(ValueError, match="requires feature"):
        detect_update_anomalies(
            {"weight_l2_norm": 1.0},
            config=config,
        )


def test_requires_at_least_one_configured_threshold():
    with pytest.raises(ValueError, match="at least one detection threshold"):
        RuleBasedDetectionConfig()


def test_rejects_invalid_zero_fraction_threshold():
    with pytest.raises(ValueError, match="between 0 and 1"):
        RuleBasedDetectionConfig(max_weight_zero_fraction=1.5)


def test_rejects_inverted_zero_fraction_range():
    with pytest.raises(ValueError, match="cannot exceed"):
        RuleBasedDetectionConfig(
            min_weight_zero_fraction=0.8,
            max_weight_zero_fraction=0.2,
        )
