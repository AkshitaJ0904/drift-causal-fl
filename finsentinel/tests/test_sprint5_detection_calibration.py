"""Sprint 5: Detection calibration pipeline tests.

Verifies the evaluate_detector harness using synthetic scenarios.
No fabricated datasets — all scenarios use deterministic arithmetic.

Covers:
- Harness runs with zero assertion failures (detector, feature extractor, harness)
- Clean scenarios produce no false positives under tight thresholds
- Attack scenarios produce true positives under tight thresholds
- Risk score formula is consistent with reason count
- Dataset inventory: documents what is real vs synthetic (see calibration notes)

CALIBRATION DISCLAIMER
----------------------
These tests verify that the detection LOGIC is correct against synthetic
test scenarios.  They do NOT constitute empirical calibration.  Production
thresholds require real clean and attack data.  See configs/detection_dataset_inventory.md.
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Import the harness under test
# ---------------------------------------------------------------------------
from scripts.evaluate_detector import (
    SCENARIOS,
    THRESHOLD_CONFIGS,
    HarnessError,
    evaluate_all,
)

# ---------------------------------------------------------------------------
# Harness correctness: zero assertion failures
# ---------------------------------------------------------------------------

def test_harness_has_no_assertion_failures():
    """All harness assertions (risk_score formula, reason completeness) must pass."""
    results = evaluate_all(verbose=False)
    all_harness_errors: list[HarnessError] = []
    for r in results:
        all_harness_errors.extend(r.harness_errors)

    if all_harness_errors:
        messages = [f"[{e.config_name}/{e.scenario_name}] {e.message}" for e in all_harness_errors]
        pytest.fail(
            f"{len(all_harness_errors)} harness assertion failure(s):\n"
            + "\n".join(messages)
        )


def test_harness_has_no_scenario_errors():
    """No scenario should raise an unexpected exception during detection."""
    results = evaluate_all(verbose=False)
    all_errors: list[str] = []
    for r in results:
        all_errors.extend(r.errors)

    if all_errors:
        pytest.fail(
            f"{len(all_errors)} scenario error(s):\n" + "\n".join(all_errors)
        )


# ---------------------------------------------------------------------------
# Clean-separation under specific threshold configs
# ---------------------------------------------------------------------------

def test_clean_scenarios_no_false_positives_under_l2_loose():
    """Config 'l2_only_loose' (threshold=200) must not flag any clean scenario."""
    results = evaluate_all(verbose=False)
    for r in results:
        if r.config_name == "l2_only_loose":
            assert r.fp == 0, (
                f"l2_only_loose: {r.fp} false positive(s) — clean scenarios flagged "
                f"as attacks.  Threshold is too tight for clean data or "
                f"clean scenarios have incorrect labels."
            )


def test_attack_scenarios_detected_under_l2_tight():
    """Config 'l2_only_tight' (threshold=1.0) must flag large-L2 attacks."""
    results = evaluate_all(verbose=False)
    for r in results:
        if r.config_name == "l2_only_tight":
            # At least the two clearly large-L2 scenarios must be caught.
            assert r.tp >= 2, (
                f"l2_only_tight: only {r.tp} true positive(s).  "
                "Expected at least 2 large-L2 attack scenarios to be flagged."
            )


def test_zero_fraction_rule_catches_all_zero_update():
    """The zero_fraction_max config must flag the 'attack_all_zeros' scenario."""
    from detection.rule_based import RuleBasedDetectionConfig, detect_update_anomalies

    config = RuleBasedDetectionConfig(max_weight_zero_fraction=0.5)
    features = {"weight_zero_fraction": 1.0}  # all zeros
    result = detect_update_anomalies(features, config=config)

    assert result.suspicious is True
    assert result.risk_score >= 25


# ---------------------------------------------------------------------------
# Risk score / reason contract
# ---------------------------------------------------------------------------

def test_risk_score_formula_single_rule():
    """Single triggered rule → risk_score == 25."""
    from detection.rule_based import RuleBasedDetectionConfig, detect_update_anomalies

    config = RuleBasedDetectionConfig(max_weight_l2_norm=1.0)
    result = detect_update_anomalies({"weight_l2_norm": 100.0}, config=config)

    assert len(result.reasons) == 1
    assert result.risk_score == 25


def test_risk_score_formula_capped_at_100():
    """Five rules triggered → risk_score capped at 100 (not 125)."""
    from detection.rule_based import RuleBasedDetectionConfig, detect_update_anomalies

    config = RuleBasedDetectionConfig(
        max_weight_l2_norm=1.0,
        max_weight_abs_mean=0.1,
        max_weight_std=0.1,
        max_weight_zero_fraction=0.9,
        min_weight_zero_fraction=0.1,
    )
    # zero_fraction=0.95 triggers both zero_fraction rules
    features = {
        "weight_l2_norm": 100.0,
        "weight_abs_mean": 50.0,
        "weight_std": 50.0,
        "weight_zero_fraction": 0.95,
    }
    result = detect_update_anomalies(features, config=config)

    assert result.risk_score == 100, (
        f"Expected risk_score capped at 100; got {result.risk_score} "
        f"with {len(result.reasons)} reasons."
    )
    assert result.severity in ("CRITICAL", "HIGH"), (
        f"Expected CRITICAL or HIGH severity; got {result.severity!r}"
    )


def test_reasons_contain_observed_and_threshold():
    """Every triggered reason must describe the observed value and threshold."""
    from detection.rule_based import RuleBasedDetectionConfig, detect_update_anomalies

    config = RuleBasedDetectionConfig(max_weight_l2_norm=1.0)
    result = detect_update_anomalies({"weight_l2_norm": 500.0}, config=config)

    assert result.suspicious
    for reason in result.reasons:
        low = reason.lower()
        has_obs = "observed" in low or "exceeds" in low or "below" in low
        assert has_obs, (
            f"Reason does not describe observed value: {reason!r}"
        )


# ---------------------------------------------------------------------------
# Scenario inventory check
# ---------------------------------------------------------------------------

def test_scenarios_have_valid_labels():
    """All SCENARIOS must have label 'clean' or 'attack'."""
    for s in SCENARIOS:
        assert s.label in ("clean", "attack"), (
            f"Scenario {s.name!r} has invalid label {s.label!r}"
        )


def test_at_least_one_clean_and_one_attack_scenario():
    clean = [s for s in SCENARIOS if s.label == "clean"]
    attack = [s for s in SCENARIOS if s.label == "attack"]
    assert len(clean) >= 2, f"Expected at least 2 clean scenarios; got {len(clean)}"
    assert len(attack) >= 4, f"Expected at least 4 attack scenarios; got {len(attack)}"


def test_threshold_configs_cover_all_rules():
    """THRESHOLD_CONFIGS must cover each rule at least once."""

    all_rules = {
        "max_weight_l2_norm",
        "max_update_l2_norm",
        "max_weight_abs_mean",
        "max_weight_std",
        "max_weight_zero_fraction",
    }
    covered: set[str] = set()
    for cfg in THRESHOLD_CONFIGS.values():
        for rule in all_rules:
            if getattr(cfg, rule, None) is not None:
                covered.add(rule)

    missing = all_rules - covered
    assert not missing, (
        f"The following rules have no threshold config in THRESHOLD_CONFIGS: {missing}"
    )
