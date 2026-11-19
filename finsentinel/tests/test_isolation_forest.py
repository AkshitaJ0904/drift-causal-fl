"""Tests for the Isolation Forest anomaly detector.

Coverage
--------
Configuration
  - Empty feature_names raises ValueError
  - Duplicate feature_names raises ValueError
  - Invalid n_estimators raises ValueError
  - Invalid contamination raises ValueError
  - contamination=0.1 is accepted
  - contamination="auto" is accepted
  - Invalid random_state raises ValueError

Unfitted detector
  - detect() raises DetectorNotFittedError
  - save() raises DetectorNotFittedError
  - is_fitted is False before fit

Fit
  - Empty feature_vectors list raises ValueError
  - Feature vector missing a required key raises FeatureMismatchError
  - Non-finite feature value raises ValueError
  - Non-numeric feature value raises ValueError
  - Fit on clean vectors succeeds; is_fitted becomes True

Detection
  - Inlier sample is not anomalous (score > threshold after fit on inliers)
  - Outlier sample is anomalous (extreme features after fit on inliers)
  - detect() result contains correct feature_names and n_estimators
  - Non-finite feature in detect() raises ValueError

Persistence
  - save + load produces a fitted detector that returns the same decision
  - Loading a non-existent file raises DetectorPersistenceError
  - save() on unfitted raises DetectorNotFittedError
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest

from detection.isolation_forest import (
    DetectorNotFittedError,
    DetectorPersistenceError,
    FeatureMismatchError,
    IsolationForestConfig,
    IsolationForestDetectionResult,
    IsolationForestDetector,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_FEATURES = ("weight_l2_norm", "weight_abs_mean", "weight_std")


def _make_config(
    feature_names: tuple[str, ...] = _FEATURES,
    n_estimators: int = 20,
    contamination: float | str = "auto",
    random_state: int | None = 0,
) -> IsolationForestConfig:
    return IsolationForestConfig(
        feature_names=feature_names,
        n_estimators=n_estimators,
        contamination=contamination,
        random_state=random_state,
    )


def _clean_vectors(n: int = 60) -> list[dict[str, float]]:
    """Return n near-identical feature vectors representing normal updates."""
    return [
        {"weight_l2_norm": 1.0 + 0.01 * i, "weight_abs_mean": 0.5, "weight_std": 0.1}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# IsolationForestConfig validation
# ---------------------------------------------------------------------------


def test_config_empty_feature_names_raises():
    with pytest.raises(ValueError, match="non-empty"):
        IsolationForestConfig(feature_names=())


def test_config_duplicate_feature_names_raises():
    with pytest.raises(ValueError, match="duplicate"):
        IsolationForestConfig(feature_names=("a", "a"))


def test_config_zero_n_estimators_raises():
    with pytest.raises(ValueError, match="n_estimators"):
        IsolationForestConfig(feature_names=("a",), n_estimators=0)


def test_config_negative_n_estimators_raises():
    with pytest.raises(ValueError, match="n_estimators"):
        IsolationForestConfig(feature_names=("a",), n_estimators=-1)


def test_config_invalid_contamination_string_raises():
    with pytest.raises(ValueError, match="contamination"):
        IsolationForestConfig(feature_names=("a",), contamination="bad")


def test_config_zero_contamination_raises():
    with pytest.raises(ValueError, match="contamination"):
        IsolationForestConfig(feature_names=("a",), contamination=0.0)


def test_config_too_high_contamination_raises():
    with pytest.raises(ValueError, match="contamination"):
        IsolationForestConfig(feature_names=("a",), contamination=0.6)


def test_config_valid_numeric_contamination():
    cfg = IsolationForestConfig(feature_names=("a",), contamination=0.1)
    assert cfg.contamination == 0.1


def test_config_auto_contamination():
    cfg = IsolationForestConfig(feature_names=("a",), contamination="auto")
    assert cfg.contamination == "auto"


def test_config_negative_random_state_raises():
    with pytest.raises(ValueError, match="random_state"):
        IsolationForestConfig(feature_names=("a",), random_state=-1)


def test_config_none_random_state_ok():
    cfg = IsolationForestConfig(feature_names=("a",), random_state=None)
    assert cfg.random_state is None


# ---------------------------------------------------------------------------
# Unfitted detector
# ---------------------------------------------------------------------------


def test_is_fitted_false_before_fit():
    det = IsolationForestDetector(_make_config())
    assert det.is_fitted is False


def test_detect_raises_before_fit():
    det = IsolationForestDetector(_make_config())
    with pytest.raises(DetectorNotFittedError):
        det.detect({"weight_l2_norm": 1.0, "weight_abs_mean": 0.5, "weight_std": 0.1})


def test_save_raises_before_fit():
    det = IsolationForestDetector(_make_config())
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(DetectorNotFittedError):
            det.save(Path(tmp) / "model.joblib")


# ---------------------------------------------------------------------------
# fit() validation
# ---------------------------------------------------------------------------


def test_fit_empty_list_raises():
    det = IsolationForestDetector(_make_config())
    with pytest.raises(ValueError, match="empty"):
        det.fit([])


def test_fit_missing_feature_raises():
    det = IsolationForestDetector(_make_config())
    with pytest.raises(FeatureMismatchError, match="missing"):
        det.fit([{"weight_l2_norm": 1.0}])


def test_fit_non_finite_value_raises():
    det = IsolationForestDetector(_make_config())
    vec = {"weight_l2_norm": float("inf"), "weight_abs_mean": 0.5, "weight_std": 0.1}
    with pytest.raises(ValueError, match="finite"):
        det.fit([vec])


def test_fit_non_numeric_value_raises():
    det = IsolationForestDetector(_make_config())
    vec = {"weight_l2_norm": "not_a_float", "weight_abs_mean": 0.5, "weight_std": 0.1}  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="numeric"):
        det.fit([vec])


def test_fit_succeeds_and_sets_is_fitted():
    det = IsolationForestDetector(_make_config())
    det.fit(_clean_vectors())
    assert det.is_fitted is True


# ---------------------------------------------------------------------------
# detect() after fit
# ---------------------------------------------------------------------------


def test_detect_returns_result_type():
    det = IsolationForestDetector(_make_config())
    det.fit(_clean_vectors())
    result = det.detect({"weight_l2_norm": 1.0, "weight_abs_mean": 0.5, "weight_std": 0.1})
    assert isinstance(result, IsolationForestDetectionResult)


def test_detect_result_has_correct_feature_names():
    det = IsolationForestDetector(_make_config())
    det.fit(_clean_vectors())
    result = det.detect({"weight_l2_norm": 1.0, "weight_abs_mean": 0.5, "weight_std": 0.1})
    assert result.feature_names == _FEATURES


def test_detect_result_has_correct_n_estimators():
    det = IsolationForestDetector(_make_config())
    det.fit(_clean_vectors())
    result = det.detect({"weight_l2_norm": 1.0, "weight_abs_mean": 0.5, "weight_std": 0.1})
    assert result.n_estimators == 20


def test_detect_inlier_is_not_anomalous():
    """A sample near the training distribution should not be flagged."""
    det = IsolationForestDetector(_make_config(contamination=0.05))
    det.fit(_clean_vectors(n=100))
    # Feature values similar to training data
    result = det.detect({"weight_l2_norm": 1.05, "weight_abs_mean": 0.5, "weight_std": 0.1})
    assert result.is_anomalous is False


def test_detect_extreme_outlier_is_anomalous():
    """A sample far from the training distribution should be flagged."""
    det = IsolationForestDetector(_make_config(contamination=0.05))
    det.fit(_clean_vectors(n=100))
    # Feature values orders of magnitude outside training range
    result = det.detect({
        "weight_l2_norm": 9999.0,
        "weight_abs_mean": 500.0,
        "weight_std": 1000.0,
    })
    assert result.is_anomalous is True


def test_detect_non_finite_feature_raises():
    det = IsolationForestDetector(_make_config())
    det.fit(_clean_vectors())
    with pytest.raises(ValueError, match="finite"):
        det.detect({"weight_l2_norm": float("nan"), "weight_abs_mean": 0.5, "weight_std": 0.1})


def test_detect_missing_feature_raises():
    det = IsolationForestDetector(_make_config())
    det.fit(_clean_vectors())
    with pytest.raises(FeatureMismatchError, match="missing"):
        det.detect({"weight_l2_norm": 1.0})


def test_anomaly_score_is_finite():
    det = IsolationForestDetector(_make_config())
    det.fit(_clean_vectors())
    result = det.detect({"weight_l2_norm": 1.0, "weight_abs_mean": 0.5, "weight_std": 0.1})
    assert math.isfinite(result.anomaly_score)


# ---------------------------------------------------------------------------
# Persistence (save / load)
# ---------------------------------------------------------------------------


def test_save_and_load_produces_same_decision():
    det = IsolationForestDetector(_make_config())
    det.fit(_clean_vectors())
    test_vec = {"weight_l2_norm": 1.0, "weight_abs_mean": 0.5, "weight_std": 0.1}
    original_result = det.detect(test_vec)

    with tempfile.TemporaryDirectory() as tmp:
        model_path = Path(tmp) / "detector.joblib"
        det.save(model_path)
        loaded = IsolationForestDetector.load(model_path)

    loaded_result = loaded.detect(test_vec)
    assert loaded_result.is_anomalous == original_result.is_anomalous
    assert abs(loaded_result.anomaly_score - original_result.anomaly_score) < 1e-9


def test_load_nonexistent_file_raises():
    with pytest.raises(DetectorPersistenceError, match="Failed to load"):
        IsolationForestDetector.load("/does/not/exist/model.joblib")


def test_save_creates_file():
    det = IsolationForestDetector(_make_config())
    det.fit(_clean_vectors())
    with tempfile.TemporaryDirectory() as tmp:
        model_path = Path(tmp) / "saved.joblib"
        det.save(model_path)
        assert model_path.exists()


def test_loaded_detector_is_fitted():
    det = IsolationForestDetector(_make_config())
    det.fit(_clean_vectors())
    with tempfile.TemporaryDirectory() as tmp:
        model_path = Path(tmp) / "det.joblib"
        det.save(model_path)
        loaded = IsolationForestDetector.load(model_path)
    assert loaded.is_fitted is True


def test_loaded_detector_config_matches():
    cfg = _make_config(n_estimators=15, contamination=0.1, random_state=7)
    det = IsolationForestDetector(cfg)
    det.fit(_clean_vectors())
    with tempfile.TemporaryDirectory() as tmp:
        model_path = Path(tmp) / "det.joblib"
        det.save(model_path)
        loaded = IsolationForestDetector.load(model_path)
    assert loaded.config.n_estimators == 15
    assert loaded.config.contamination == 0.1
    assert loaded.config.random_state == 7
