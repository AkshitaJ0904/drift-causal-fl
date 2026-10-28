
"""Explainable rule-based anomaly detection for federated-learning updates.

This module flags unusual update statistics. It does not prove that an
update is malicious, and it does not replace security validation.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RuleBasedDetectionConfig:
    """Optional thresholds for detecting unusual update features.

    A rule is disabled when its threshold is None. Configure thresholds
    using representative clean-update data before using this detector.
    """

    max_weight_l2_norm: float | None = None
    max_update_l2_norm: float | None = None
    max_weight_abs_mean: float | None = None
    max_weight_std: float | None = None
    max_weight_zero_fraction: float | None = None
    min_weight_zero_fraction: float | None = None

    def __post_init__(self) -> None:
        configured = 0

        for name, threshold in (
            ("max_weight_l2_norm", self.max_weight_l2_norm),
            ("max_update_l2_norm", self.max_update_l2_norm),
            ("max_weight_abs_mean", self.max_weight_abs_mean),
            ("max_weight_std", self.max_weight_std),
            ("max_weight_zero_fraction", self.max_weight_zero_fraction),
            ("min_weight_zero_fraction", self.min_weight_zero_fraction),
        ):
            if threshold is None:
                continue

            if isinstance(threshold, bool) or not isinstance(
                threshold, (int, float)
            ):
                raise ValueError(f"{name} must be a finite number or None.")

            if not math.isfinite(float(threshold)):
                raise ValueError(f"{name} must be finite.")

            if name in {
                "max_weight_zero_fraction",
                "min_weight_zero_fraction",
            }:
                if not 0.0 <= float(threshold) <= 1.0:
                    raise ValueError(f"{name} must be between 0 and 1.")
            elif float(threshold) < 0.0:
                raise ValueError(f"{name} must be non-negative.")

            configured += 1

        if configured == 0:
            raise ValueError(
                "Configure at least one detection threshold. "
                "Calibrate thresholds using clean-update data."
            )

        if (
            self.min_weight_zero_fraction is not None
            and self.max_weight_zero_fraction is not None
            and self.min_weight_zero_fraction
            > self.max_weight_zero_fraction
        ):
            raise ValueError(
                "min_weight_zero_fraction cannot exceed "
                "max_weight_zero_fraction."
            )


@dataclass(frozen=True)
class DetectionResult:
    """Explainable anomaly assessment for one update."""

    risk_score: int
    severity: str
    suspicious: bool
    reasons: tuple[str, ...]


def detect_update_anomalies(
    features: Mapping[str, float],
    *,
    config: RuleBasedDetectionConfig,
) -> DetectionResult:
    """Evaluate extracted update features against configured thresholds.

    Each triggered rule contributes 25 points, capped at 100. This is a
    transparent rule-count score, not a calibrated probability of attack.
    """

    if not isinstance(features, Mapping) or not features:
        raise ValueError("features must be a non-empty mapping.")

    validated: dict[str, float] = {}

    for name, value in features.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Feature names must be non-empty strings.")

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Feature {name!r} must be numeric.")

        numeric_value = float(value)
        if not math.isfinite(numeric_value):
            raise ValueError(f"Feature {name!r} must be finite.")

        validated[name] = numeric_value

    reasons: list[str] = []

    def check_max(
        feature_name: str,
        threshold: float | None,
        description: str,
    ) -> None:
        if threshold is None:
            return

        if feature_name not in validated:
            raise ValueError(
                f"Configured rule requires feature {feature_name!r}."
            )

        value = validated[feature_name]
        if value > threshold:
            reasons.append(
                f"{description}: observed {value:.6g} exceeds "
                f"configured threshold {threshold:.6g}."
            )

    check_max(
        "weight_l2_norm",
        config.max_weight_l2_norm,
        "Weight L2 norm is unusually high",
    )
    check_max(
        "update_l2_norm",
        config.max_update_l2_norm,
        "Update L2 norm is unusually high",
    )
    check_max(
        "weight_abs_mean",
        config.max_weight_abs_mean,
        "Mean absolute weight is unusually high",
    )
    check_max(
        "weight_std",
        config.max_weight_std,
        "Weight standard deviation is unusually high",
    )
    check_max(
        "weight_zero_fraction",
        config.max_weight_zero_fraction,
        "Fraction of zero weights is unusually high",
    )

    if config.min_weight_zero_fraction is not None:
        feature_name = "weight_zero_fraction"
        if feature_name not in validated:
            raise ValueError(
                f"Configured rule requires feature {feature_name!r}."
            )

        value = validated[feature_name]
        if value < config.min_weight_zero_fraction:
            reasons.append(
                "Fraction of zero weights is unusually low: "
                f"observed {value:.6g} is below configured threshold "
                f"{config.min_weight_zero_fraction:.6g}."
            )

    risk_score = min(100, len(reasons) * 25)

    if risk_score >= 75:
        severity = "CRITICAL"
    elif risk_score >= 50:
        severity = "HIGH"
    elif risk_score >= 25:
        severity = "MEDIUM"
    else:
        severity = "LOW"

    return DetectionResult(
        risk_score=risk_score,
        severity=severity,
        suspicious=bool(reasons),
        reasons=tuple(reasons),
    )
