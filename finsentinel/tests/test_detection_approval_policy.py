"""Tests for risk-based initial approval actions and detector configuration."""

import pytest

from core.config import Settings, get_detection_config, get_high_risk_action
from policy.detection_approval_policy import select_initial_approval_status


@pytest.mark.parametrize("severity", ["LOW", "MEDIUM"])
def test_low_and_medium_risk_updates_remain_pending(severity: str) -> None:
    assert select_initial_approval_status(severity) == "pending_approval"


@pytest.mark.parametrize("severity", ["HIGH", "CRITICAL"])
def test_high_and_critical_risk_updates_are_quarantined(severity: str) -> None:
    assert select_initial_approval_status(severity) == "quarantined"


def test_high_risk_action_can_require_human_review_without_quarantine() -> None:
    assert (
        select_initial_approval_status("HIGH", high_risk_action="pending_approval")
        == "pending_approval"
    )


def test_unknown_severity_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown detection severity"):
        select_initial_approval_status("UNKNOWN")


def test_development_has_explicit_uncalibrated_detector_baseline() -> None:
    config = get_detection_config(Settings(environment="development"))
    assert config.max_weight_l2_norm == 100.0
    assert config.max_update_l2_norm is None


def test_non_development_requires_configured_detector_thresholds() -> None:
    with pytest.raises(ValueError, match="Detection thresholds must be configured"):
        get_detection_config(Settings(environment="production"))


def test_explicit_production_threshold_is_accepted() -> None:
    config = get_detection_config(
        Settings(environment="production", max_weight_l2_norm=25.0)
    )
    assert config.max_weight_l2_norm == 25.0


def test_high_risk_action_setting_defaults_to_quarantine() -> None:
    assert get_high_risk_action(Settings()) == "quarantined"


def test_finsentinel_prefixed_env_var_enables_pending_review(monkeypatch) -> None:
    """FINSENTINEL_HIGH_RISK_ACTION is the documented env var name."""
    monkeypatch.setenv("FINSENTINEL_HIGH_RISK_ACTION", "pending_approval")
    assert get_high_risk_action() == "pending_approval"


def test_finsentinel_prefixed_env_var_accepts_quarantine(monkeypatch) -> None:
    monkeypatch.setenv("FINSENTINEL_HIGH_RISK_ACTION", "quarantined")
    assert get_high_risk_action() == "quarantined"


def test_finsentinel_env_var_takes_priority_over_settings_field(monkeypatch) -> None:
    """FINSENTINEL_HIGH_RISK_ACTION overrides the HIGH_RISK_ACTION settings field."""
    monkeypatch.setenv("FINSENTINEL_HIGH_RISK_ACTION", "pending_approval")
    # Settings field defaults to quarantined; env var must win.
    assert get_high_risk_action(Settings()) == "pending_approval"


def test_unprefixed_high_risk_action_still_works_as_fallback() -> None:
    """HIGH_RISK_ACTION via the settings field works when the prefixed var is absent."""
    assert get_high_risk_action(Settings(high_risk_action="pending_approval")) == "pending_approval"


def test_invalid_high_risk_action_via_env_var_raises(monkeypatch) -> None:
    """An unrecognized value must fail closed, never silently default."""
    monkeypatch.setenv("FINSENTINEL_HIGH_RISK_ACTION", "auto_approve")
    with pytest.raises(ValueError, match="FINSENTINEL_HIGH_RISK_ACTION must be"):
        get_high_risk_action()


def test_empty_finsentinel_env_var_falls_back_to_settings(monkeypatch) -> None:
    """An empty FINSENTINEL_HIGH_RISK_ACTION is treated as absent; settings wins."""
    monkeypatch.setenv("FINSENTINEL_HIGH_RISK_ACTION", "")
    assert get_high_risk_action(Settings()) == "quarantined"


def test_high_risk_action_absent_env_var_defaults_to_quarantine(monkeypatch) -> None:
    monkeypatch.delenv("FINSENTINEL_HIGH_RISK_ACTION", raising=False)
    assert get_high_risk_action() == "quarantined"
