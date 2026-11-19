# Detection Dataset Inventory

## Purpose

This document records what data is **real** vs **synthetic** in FinSentinel's
detection calibration pipeline and explains the production-calibration gap.

---

## Sprint 5 Test Datasets (Synthetic)

All scenarios in `scripts/evaluate_detector.py` and `tests/test_sprint5_detection_calibration.py`
use **deterministic arithmetic tensors** constructed in code. No real federated-learning
run data was used.

| Scenario | Label | Description |
|---|---|---|
| `clean_typical` | clean | Small-magnitude weights representative of a normal client round |
| `clean_zero_bias` | clean | Zero-bias layer, nonzero weights — valid but unusual |
| `attack_large_l2` | attack | Weight tensor with very large L2 norm (>500) |
| `attack_all_zeros` | attack | All weights zeroed out (zero-fraction=1.0) |
| `attack_high_variance` | attack | High per-weight variance, elevated std |
| `attack_large_mean` | attack | Abnormally large absolute mean per weight |
| `attack_boosting` | attack | Large L2 + large mean, simulating model poisoning |

**Threshold configs** (`THRESHOLD_CONFIGS` in `evaluate_detector.py`):

| Config name | Rule(s) tested | Notes |
|---|---|---|
| `l2_only_loose` | `max_weight_l2_norm=200` | Should not flag clean scenarios |
| `l2_only_tight` | `max_weight_l2_norm=1.0` | Flags large-L2 attacks |
| `mean_only` | `max_weight_abs_mean=10.0` | Flags high-mean attacks |
| `std_only` | `max_weight_std=5.0` | Flags high-variance attacks |
| `zero_fraction_max` | `max_weight_zero_fraction=0.5` | Flags all-zeros attacks |

---

## Production Calibration Gap

> **DISCLAIMER**: The thresholds above are verified correct for the synthetic
> test scenarios only. They are **not** empirically calibrated for production use.

Production calibration requires:

1. **Clean baseline dataset** — a representative sample of honest client updates
   across your FL task (model architecture, dataset distribution, training rounds).
2. **Attack reference dataset** — adversarially crafted or collected examples of:
   - Model poisoning (large weight perturbations)
   - Gradient inversion (zero-fraction anomalies)
   - Backdoor injection (localised weight boosts)
3. **Statistical threshold selection** — set `max_weight_l2_norm`,
   `max_weight_std`, etc. to minimise false positives on clean data at an
   acceptable true-positive rate on attack data (ROC curve analysis recommended).
4. **Periodic recalibration** — thresholds must be re-evaluated after major
   changes to the model architecture, training procedure, or client population.

---

## How to Add Real Data

Replace or supplement the synthetic scenarios in `scripts/evaluate_detector.py`:

```python
# Example: load a real clean update from a saved .pt file
import torch
clean_weights = torch.load("path/to/real_clean_update.pt")

SCENARIOS.append(DetectionScenario(
    name="real_clean_round42",
    state_dict=clean_weights,
    label="clean",
))
```

Do **not** commit real client update data to this repository — save it outside
the repo and reference it by path.

---

---

## Reproducible Input Format

All synthetic scenarios in `scripts/evaluate_detector.py` and
`tests/test_sprint5_detection_calibration.py` use `torch.Tensor` state dicts
with the following guaranteed properties:

| Property | Value |
|---|---|
| Data type | `torch.float32` |
| Tensor shape | Variable; typically `(N,)` flat vectors constructed via `torch.ones`, `torch.zeros`, `torch.randn` |
| State dict key | `"weight"` (single-layer test model) |
| Sample count | Fixed per scenario (see `evaluate_detector.py`) |
| Determinism | 100% — no random seed required; tensors are arithmetic constants |

The detector receives a `torch.Tensor` via `IsolationForestDetector.score_update(features)`.
Feature extraction (`extract_features` in `detection/isolation_forest.py`) produces a
fixed-length `np.ndarray` of 6 scalar features:
`[l2_norm, abs_mean, std, max_abs, sparsity, kurtosis]`.

Rule-based detection (`DetectionConfig.evaluate`) operates on the same tensor but
accesses raw statistics via `compute_weight_stats` in `detection/rules.py`.

---

## Missing Data and Evaluation Limitations

The following data gaps prevent production deployment of the detection layer without
further calibration work:

| Gap | Impact | Mitigation path |
|---|---|---|
| No real FL client updates in any scenario | Thresholds calibrated only for synthetic arithmetic tensors — unknown true positive rate on production traffic | Collect clean baseline samples from a staging FL run |
| No adversarial examples from an actual attack campaign | Attack scenarios are hand-crafted; real poisoning vectors may differ | Run red-team FL poisoning experiments and add to `SCENARIOS` |
| Single model architecture tested | A single `weight` layer; real models have many layers with different magnitude distributions per layer | Register multi-layer state dicts and test per-layer feature extraction |
| No cross-round stability testing | Thresholds are validated per-round; legitimate weight drift across rounds is not modelled | Collect 20+ round baseline sequence; compute per-round distribution |
| Isolation Forest not trained on real data | `IsolationForestDetector` is exercised in unit tests only; it is not wired into the ingestion pipeline | Train on ≥100 clean production updates; see deployment workflow in `frontend/src/pages/DetectionConfig.tsx` |

---

## Attack Category Coverage

| Attack category | Synthetic scenario | Rule that catches it | Missing from production calibration |
|---|---|---|---|
| Model poisoning (large weight magnitude) | `attack_large_l2`, `attack_boosting` | `max_weight_l2_norm` | Real poisoning vectors; magnitude calibrated to actual FL task |
| Gradient inversion (zero-fraction anomaly) | `attack_all_zeros` | `max_weight_zero_fraction` | True zero-fraction distribution for clean updates |
| Mean-shift backdoor | `attack_large_mean`, `attack_boosting` | `max_weight_abs_mean` | Legitimate high-mean scenarios (transfer learning fine-tuning) |
| High-variance injection | `attack_high_variance` | `max_weight_std` | Per-layer variance norms for multi-layer models |
| Statistical anomaly (density) | (Isolation Forest only — not yet in pipeline) | `IsolationForestDetector` | All production data |

---

## Exact Data Needed for Future Production Calibration

Before enabling detection in production, collect and document the following:

1. **Clean baseline** (minimum 50 samples, target 500+):
   - Source: a controlled FL staging run with verified-honest clients
   - Format: `.pt` files (PyTorch `state_dict`), saved outside the repository
   - Required: at least 10 distinct FL rounds, same model version as production

2. **Per-round magnitude statistics**:
   - For each clean baseline sample, record: `l2_norm`, `abs_mean`, `std` per layer
   - Set `max_weight_l2_norm` = 99th-percentile of clean L2 norms × 1.5 safety margin

3. **Attack reference samples** (minimum 10 per attack type):
   - Source: red-team poisoning experiments or literature-reproduced attacks
   - Required to set minimum detection sensitivity targets (true positive rate ≥ 90%)

4. **False-positive tolerance baseline**:
   - Measure false-positive rate on clean samples for the chosen threshold config
   - Target: < 1% false-positive rate before enabling quarantine action

*Last updated: 2026-11-19 (Sprint 5 → Entry 59 completion)*
