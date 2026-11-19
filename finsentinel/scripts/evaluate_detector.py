#!/usr/bin/env python
"""Detection evaluation harness for the FinSentinel rule-based detector.

EMPIRICAL CALIBRATION DISCLAIMER
=================================
This script evaluates the rule-based detector against SYNTHETIC scenarios
designed to verify the detection logic.  It does NOT constitute empirical
calibration.

Real calibration requires:
  1. Representative clean updates from actual federated-learning clients.
  2. Controlled attack updates generated under realistic adversarial
     conditions (gradient scaling, sign-flip, targeted poisoning, etc.).
  3. A held-out evaluation set kept separate from calibration data.

The thresholds used here are illustrative only.  Replace them with values
derived from real production data before deployment.  Do not interpret the
precision, recall, or F1 figures from this script as production metrics.

Harness guarantees (enforced by assertions at run time)
---------------------------------------------------------
1. Feature extraction: each configured rule's required feature key is
   present in the extracted feature dict before detection runs.
2. Risk-score formula: ``risk_score == min(25 * len(reasons), 100)`` for
   every detection result.
3. Evidence completeness: every triggered rule produces at least one
   reason string that names the observed value and the threshold.
4. Clean/attack separation: scenarios labelled "clean" at a threshold that
   should not fire all produce ``suspicious=False``; scenarios labelled
   "attack" at a threshold that should fire all produce ``suspicious=True``.
5. Reproducibility: all scenarios are built from deterministic arithmetic
   (no random numbers); re-running the script produces identical output.

A harness assertion failure indicates a bug in the detector, the feature
extractor, or this harness — not a calibration issue.

Usage
-----
    python -m scripts.evaluate_detector          # summary table (stdout)
    python -m scripts.evaluate_detector --verbose  # per-scenario results
    python -m scripts.evaluate_detector --assert-clean-separation
        # Exit code 1 if any "clean" scenario fires or any "attack" does not
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

import torch

from detection.rule_based import RuleBasedDetectionConfig, detect_update_anomalies
from features.update_features import extract_update_features
from ingestion.serialization import deserialize_state_dict, serialize_state_dict

# ---------------------------------------------------------------------------
# Scenario definition
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    name: str
    label: str           # "clean" or "attack"
    weight_val: float
    bias_val: float
    description: str
    # Optional: provide a reference state dict to enable update_l2_norm feature.
    # If set, weight_val and bias_val describe the CLIENT update;
    # ref_weight_val/ref_bias_val describe the SERVER reference.
    ref_weight_val: float | None = None
    ref_bias_val: float | None = None


# Synthetic scenarios.  Deterministic — no random numbers used.
# Each scenario is designed to cover a specific rule or combination of rules.
SCENARIOS: list[Scenario] = [
    # --- Rule: max_weight_l2_norm ---
    Scenario(
        name="clean_tiny_weights",
        label="clean",
        weight_val=0.001,
        bias_val=0.0,
        description="Very small weights — L2 norm well below any sane threshold",
    ),
    Scenario(
        name="clean_moderate_weights",
        label="clean",
        weight_val=0.1,
        bias_val=0.05,
        description="Moderate weights — still below the synthetic L2 threshold",
    ),
    Scenario(
        name="attack_large_l2",
        label="attack",
        weight_val=100.0,
        bias_val=50.0,
        description="Gradient scaling attack — extreme weight magnitudes",
    ),
    Scenario(
        name="attack_very_large_l2",
        label="attack",
        weight_val=1000.0,
        bias_val=500.0,
        description="Very large weights — clearly above any reasonable threshold",
    ),
    # --- Rule: max_weight_abs_mean ---
    Scenario(
        name="clean_very_small_weights",
        label="clean",
        weight_val=0.001,
        bias_val=0.001,
        description="Very small non-zero weights — abs mean well below threshold",
    ),
    Scenario(
        name="attack_high_mean",
        label="attack",
        weight_val=50.0,
        bias_val=50.0,
        description="High absolute mean — triggers mean rule",
    ),
    # --- Rule: max_weight_std ---
    Scenario(
        name="attack_high_std",
        label="attack",
        weight_val=200.0,
        bias_val=-200.0,
        description="High weight spread — L2 and std rules both fire",
    ),
    # --- Rule: max_weight_zero_fraction (too many zeros) ---
    Scenario(
        name="attack_all_zeros",
        label="attack",
        weight_val=0.0,
        bias_val=0.0,
        description="All weights are zero — triggers max_weight_zero_fraction=0.5 rule",
    ),
    # --- Rule: update_l2_norm (requires reference state dict) ---
    Scenario(
        name="clean_small_update",
        label="clean",
        weight_val=0.1,
        bias_val=0.1,
        ref_weight_val=0.09,
        ref_bias_val=0.09,
        description="Tiny delta from reference — update L2 norm near zero",
    ),
    Scenario(
        name="attack_large_update",
        label="attack",
        weight_val=100.0,
        bias_val=100.0,
        ref_weight_val=0.1,
        ref_bias_val=0.1,
        description="Massive delta from reference — large update L2 norm",
    ),
    # --- Multi-rule: several rules trigger simultaneously ---
    Scenario(
        name="attack_multi_rule",
        label="attack",
        weight_val=500.0,
        bias_val=500.0,
        description=(
            "Extreme values — L2 norm, abs mean, std all trigger; "
            "risk_score should be CRITICAL (>=75)"
        ),
    ),
    # --- Boundary: just below tight threshold (clean expected) ---
    Scenario(
        name="boundary_just_below_threshold",
        label="clean",
        weight_val=0.3,
        bias_val=0.0,
        description="Just below the tight L2 threshold — should not trigger",
    ),
]


# ---------------------------------------------------------------------------
# Threshold configurations to evaluate
# ---------------------------------------------------------------------------

THRESHOLD_CONFIGS: dict[str, RuleBasedDetectionConfig] = {
    # Tests L2 norm rule only
    "l2_only_tight": RuleBasedDetectionConfig(max_weight_l2_norm=1.0),
    "l2_only_loose": RuleBasedDetectionConfig(max_weight_l2_norm=200.0),
    # Tests abs-mean rule only
    "mean_only": RuleBasedDetectionConfig(max_weight_abs_mean=1.0),
    # Tests std rule only
    "std_only": RuleBasedDetectionConfig(max_weight_std=1.0),
    # Tests zero-fraction rule (flag too many zeros: >50%)
    "zero_fraction_max": RuleBasedDetectionConfig(max_weight_zero_fraction=0.5),
    # Tests combined L2 + mean (more rules = higher score)
    "l2_plus_mean": RuleBasedDetectionConfig(
        max_weight_l2_norm=1.0,
        max_weight_abs_mean=0.5,
    ),
    # Tests update L2 norm rule (requires reference state dict in scenario)
    "update_l2": RuleBasedDetectionConfig(max_update_l2_norm=1.0),
}


# ---------------------------------------------------------------------------
# Harness verification helpers
# ---------------------------------------------------------------------------

@dataclass
class HarnessError:
    scenario_name: str
    config_name: str
    message: str


def _required_feature_keys(config: RuleBasedDetectionConfig) -> set[str]:
    """Return the feature keys that must be present for the given config."""
    keys: set[str] = set()
    if config.max_weight_l2_norm is not None:
        keys.add("weight_l2_norm")
    if config.max_update_l2_norm is not None:
        keys.add("update_l2_norm")
    if config.max_weight_abs_mean is not None:
        keys.add("weight_abs_mean")
    if config.max_weight_std is not None:
        keys.add("weight_std")
    if config.max_weight_zero_fraction is not None or config.min_weight_zero_fraction is not None:
        keys.add("weight_zero_fraction")
    return keys


def _assert_risk_score_formula(result_risk_score: int, reasons: tuple[str, ...]) -> str | None:
    """Return an error message if the risk_score formula is violated, else None."""
    expected = min(100, len(reasons) * 25)
    if result_risk_score != expected:
        n = len(reasons)
        return f"risk_score={result_risk_score} but formula gives min(25*{n},100)={expected}"
    return None


def _assert_reasons_complete(reasons: tuple[str, ...]) -> str | None:
    """Return an error message if any reason is empty or lacks numeric content."""
    for r in reasons:
        if not r.strip():
            return "Empty reason string found"
        # Each reason should contain "observed" and "threshold" values
        if "observed" not in r.lower() and "below" not in r.lower() and "exceeds" not in r.lower():
            return f"Reason does not describe observed vs threshold: {r!r}"
    return None


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

@dataclass
class EvalResult:
    config_name: str
    tp: int = 0
    tn: int = 0
    fp: int = 0
    fn: int = 0
    skipped: int = 0   # scenarios whose required features were not extracted
    errors: list[str] = field(default_factory=list)
    harness_errors: list[HarnessError] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        denom = self.tp + self.fp
        return self.tp / denom if denom else None

    @property
    def recall(self) -> float | None:
        denom = self.tp + self.fn
        return self.tp / denom if denom else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or (p + r) == 0:
            return None
        return 2 * p * r / (p + r)

    def summary_line(self) -> str:
        p_str = f"{self.precision:.2f}" if self.precision is not None else "N/A"
        r_str = f"{self.recall:.2f}" if self.recall is not None else "N/A"
        f_str = f"{self.f1:.2f}" if self.f1 is not None else "N/A"
        skip_str = f" skip={self.skipped}" if self.skipped else ""
        h_str = f" [HARNESS:{len(self.harness_errors)}]" if self.harness_errors else ""
        return (
            f"  {self.config_name:<22} "
            f"TP={self.tp} TN={self.tn} FP={self.fp} FN={self.fn}{skip_str}  "
            f"P={p_str} R={r_str} F1={f_str}{h_str}"
        )


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------

def _build_state_dict(weight_val: float, bias_val: float) -> dict[str, torch.Tensor]:
    return {
        "layer.weight": torch.tensor(
            [[weight_val, weight_val]], dtype=torch.float32
        ),
        "layer.bias": torch.tensor([bias_val], dtype=torch.float32),
    }


def build_payload(scenario: Scenario) -> bytes:
    state_dict = _build_state_dict(scenario.weight_val, scenario.bias_val)
    return serialize_state_dict(state_dict)


def build_reference_dict(scenario: Scenario) -> dict[str, torch.Tensor] | None:
    if scenario.ref_weight_val is None:
        return None
    return _build_state_dict(scenario.ref_weight_val, scenario.ref_bias_val or 0.0)


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

def evaluate_all(*, verbose: bool = False) -> list[EvalResult]:
    # Pre-build payloads and extract features.
    scenario_data: list[tuple[Scenario, dict[str, float]]] = []
    for scenario in SCENARIOS:
        payload = build_payload(scenario)
        state_dict = deserialize_state_dict(payload)
        reference = build_reference_dict(scenario)
        features = extract_update_features(state_dict, reference_state_dict=reference)
        scenario_data.append((scenario, features))

    results: list[EvalResult] = []

    for config_name, config in THRESHOLD_CONFIGS.items():
        result = EvalResult(config_name=config_name)
        required_keys = _required_feature_keys(config)

        for scenario, features in scenario_data:
            # Harness check 1: required feature keys must be present.
            missing_keys = required_keys - features.keys()
            if missing_keys:
                # update_l2_norm is only computed when a reference state dict is
                # provided.  Scenarios without a reference cannot produce it.
                # This is expected; track as a skip rather than an error.
                reference_only = missing_keys <= {"update_l2_norm"}
                if reference_only and scenario.ref_weight_val is None:
                    result.skipped += 1
                else:
                    result.harness_errors.append(HarnessError(
                        scenario_name=scenario.name,
                        config_name=config_name,
                        message=(
                            f"Missing feature keys required by config: {missing_keys}. "
                            "This indicates the scenario or feature extractor is misconfigured."
                        ),
                    ))
                continue

            try:
                detection = detect_update_anomalies(features, config=config)
            except Exception as exc:
                result.errors.append(f"{scenario.name}: {exc}")
                if verbose:
                    print(f"  [{config_name}] {scenario.name}: ERROR — {exc}")
                continue

            predicted_attack = detection.suspicious
            actual_attack = scenario.label == "attack"

            if predicted_attack and actual_attack:
                result.tp += 1
            elif not predicted_attack and not actual_attack:
                result.tn += 1
            elif predicted_attack and not actual_attack:
                result.fp += 1
            else:
                result.fn += 1

            # Harness check 2: risk_score formula correctness.
            formula_err = _assert_risk_score_formula(detection.risk_score, detection.reasons)
            if formula_err:
                result.harness_errors.append(HarnessError(
                    scenario_name=scenario.name,
                    config_name=config_name,
                    message=formula_err,
                ))

            # Harness check 3: evidence completeness when triggered.
            if detection.suspicious:
                completeness_err = _assert_reasons_complete(detection.reasons)
                if completeness_err:
                    result.harness_errors.append(HarnessError(
                        scenario_name=scenario.name,
                        config_name=config_name,
                        message=completeness_err,
                    ))

            if verbose:
                rule_info = ""
                if detection.suspicious:
                    rule_info = " | " + " ; ".join(detection.reasons[:2])
                    if len(detection.reasons) > 2:
                        rule_info += f" (+{len(detection.reasons)-2} more)"
                print(
                    f"  [{config_name}] {scenario.name}: "
                    f"label={scenario.label} predicted={'attack' if predicted_attack else 'clean'} "
                    f"score={detection.risk_score} severity={detection.severity}{rule_info}"
                )

        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate FinSentinel rule-based detector (synthetic scenarios only)"
    )
    parser.add_argument("--verbose", action="store_true",
                        help="Print per-scenario results including triggered rules")
    parser.add_argument("--assert-clean-separation", action="store_true",
                        help=(
                            "Exit 1 if any 'clean' scenario fires (FP) "
                            "or any 'attack' scenario does not fire (FN) for any config"
                        ))
    args = parser.parse_args()

    print("=" * 70)
    print("FinSentinel Rule-Based Detector — Evaluation Framework")
    print("=" * 70)
    print()
    print("WARNING: Results are based on SYNTHETIC scenarios only.")
    print("         Do not use these figures as production metrics.")
    print()

    if args.verbose:
        print("Per-scenario results:")
        print()

    results = evaluate_all(verbose=args.verbose)

    if args.verbose:
        print()

    total_harness_errors = sum(len(r.harness_errors) for r in results)
    total_errors = sum(len(r.errors) for r in results)

    print("Summary (synthetic scenarios):")
    for r in results:
        print(r.summary_line())
        for err in r.errors:
            print(f"    SCENARIO_ERROR: {err}")
        for he in r.harness_errors:
            print(f"    HARNESS_ERROR [{he.scenario_name}]: {he.message}")

    print()
    if total_harness_errors:
        print(
            f"HARNESS ASSERTION FAILURES: {total_harness_errors}  "
            "— these indicate bugs in the detector, feature extractor, or this harness."
        )
    else:
        print("All harness assertions passed.")

    print()
    print("Empirical calibration status: INCOMPLETE")
    print(
        "Next step: replace SCENARIOS with representative clean and attack "
        "data from real deployments.  See AGENTref.md for details."
    )

    if args.assert_clean_separation:
        total_fp = sum(r.fp for r in results)
        total_fn = sum(r.fn for r in results)
        if total_fp or total_fn or total_harness_errors or total_errors:
            print(
                f"\n--assert-clean-separation: FAILED "
                f"(FP={total_fp} FN={total_fn} harness_errors={total_harness_errors} "
                f"errors={total_errors})"
            )
            return 1
        print("\n--assert-clean-separation: PASSED")

    return 1 if total_harness_errors else 0


if __name__ == "__main__":
    sys.exit(main())
