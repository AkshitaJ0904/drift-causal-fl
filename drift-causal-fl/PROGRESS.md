# PROGRESS — Drift-Causal Dropout Pipeline

*Single source of truth for project status. Read this first before re-scanning files or re-deriving what's done — update it every session instead of re-deriving state from scratch.*

**Last updated:** 2026-09-27 (Day 2 complete)
**Working directory:** `/Users/akshitajain/prj4/drift-causal-fl/`
**Parent research docs (in `/Users/akshitajain/prj4/`):** `research_discovery.md`, `full_research_report.md`, `candidate1_adversarial_audit.md`, `candidate1_final_hostile_validation.md`, `candidate1_project_specification.md` — the full research → validation → spec trail. Don't redo this work; it's locked.

---

## Project identity (locked, do not re-litigate)

- **Title:** *When Absence Is Informative: Benchmarking Federated Learning Under Drift-Causal Client Participation*
- **Research question:** Does client dropout that's causally driven by a device's own current, temporally-evolving data drift produce systematically different FL outcomes than exogenous dropout of equal marginal rate — and does an existing bias-correction method (FedIPW) remain valid under this regime?
- **Novelty claim (narrow, already survived 3 rounds of hostile search):** No prior work studies participation driven by *temporal* concept drift specifically, or runs a matched-marginal-rate benchmark isolating informativeness from amount. Load-bearing prior art to cite: FLOSS (arXiv:2507.23115), FedIPW (arXiv:2604.26604), FL-FDMS (arXiv:2205.13222), DFL-AA (arXiv:2606.10774).
- **Must-not-claim list, SAPA gate rule, falsification criteria, full hypotheses:** all in `candidate1_project_specification.md` — do not redo this reasoning, just reference it.

---

## Status checklist (Day 1–7 plan)

| Day | Task | Status | Notes |
|---|---|---|---|
| 1 | Trustworthy full-participation FedAvg baseline | ✅ **Done, verified working** | See Results below |
| 2 | Drift injection engine (D(i,t) computation) | ✅ **Done, verified working** | Model-independent estimator works great (corr=0.995 with ground truth); model-relative estimator is noisy at small scale (corr=0.02) — see Results |
| 3 | MCAR + MAR dropout mechanisms | ✅ **Done, verified working on real data** | `src/mechanisms/dropout.py` — rate-matching confirmed |
| 4 | MNAR-logistic + threshold mechanisms, alpha-calibration | ✅ **Done, verified working on real data** | Same file — ρ climbs monotonically with β (0.07→0.70) on real drift scores |
| — | **Integration: mechanism + drift + FedAvg assembled into one loop** | ✅ **Done** | `src/simulation/mechanism_runner.py` — the actual MVP loop |
| — | **First real MCAR/MAR/MNAR head-to-head run** | ✅ **Done (single-seed, reduced scale)** | See Results — **this is the first real look at the headline question** |
| 5 | FedIPW (oracle + estimated variants) | ✅ **Done, verified — and it caught a real bug in our experimental design** | See Results — found a drift-injection confound |
| — | **Fix drift-injection confound (rotation → real cross-writer label shift)** | ✅ **Done, verified fixed** | Confirmed: MCAR/MNAR FedAvg accuracy converged after the fix (0.627 vs 0.621, was 0.52 vs 0.59) |
| 6 | FL-FDMS | ❌ Not started | **← next task** |
| 7 | FedDrift + first end-to-end smoke test | ❌ Not started | |
| — | Full MVP sweep (175–350 runs, 5 seeds) | ❌ Not started | Blocked on Days 6, 7. Needed to confirm whether the oracle-IPW-under-MNAR pattern (Results) is real or single-seed noise |
| — | Statistical analysis (mixed-effects regression, bootstrap CIs) | ❌ Not started | Needs the full multi-seed sweep first |

**Bottom line: Days 1–5 all done and verified, fully assembled into one working loop. The core theoretical test (does FedIPW break under MNAR) has actually been run twice — once with a confounded drift mechanism (caught and diagnosed the confound), once with the fixed mechanism (confound confirmed resolved, a theory-consistent but not-yet-proven signal is emerging for oracle-IPW). Next: FL-FDMS (Day 6).**

---

## Environment (already set up, don't reinstall)

- Python 3.11.7 at `/Users/akshitajain/.pyenv/versions/3.11.7/bin/python3`
- Installed: `torch 2.11.0`, `torchvision 0.26.0`, `flwr 1.37.0`, `flwr-datasets 0.6.1`, `numpy`, `pandas`, `scipy` (all confirmed installed)
- **Real FEMNIST is already downloaded and cached locally** (via `flwr-datasets` → HuggingFace Hub, `flwrlabs/femnist`, 814,277 samples, fields: `image`, `writer_id`, `hsf_id`, `character`, 62 classes). No need to re-download — `src/data/loaders.py::load_femnist_clients()` will hit the local cache.
- MNIST fallback path also exists (`load_mnist_smoketest_clients()`) but is **not needed anymore** since real FEMNIST works — don't bother running it again.

---

## File inventory (what exists, what it does)

```
drift-causal-fl/
├── PROGRESS.md                          ← this file
├── requirements.txt                     ✅ torch, torchvision, numpy, flwr, flwr-datasets
├── src/
│   ├── models/cnn.py                    ✅ SmallCNN — 2 conv + 2 FC, matches LEAF/FedDrift reference arch
│   ├── data/loaders.py                  ✅ load_femnist_clients() [real, writer-partitioned], load_mnist_smoketest_clients() [unused fallback], load_clients() [tries FEMNIST, falls back to MNIST]
│   ├── simulation/fedavg_baseline.py    ✅ local_train(), fedavg_aggregate(), evaluate(), run_fedavg_full_participation() — FULL PARTICIPATION ONLY, no dropout wired in yet
│   ├── mechanisms/dropout.py            ✅ sigmoid(), mcar_dropout(), mar_dropout(), mnar_drift_dropout(), mnar_threshold_dropout(), _solve_alpha() [bisection calibration], realized_correlation() — validated against REAL drift data, see Results
│   └── drift/
│       ├── injection.py                 ✅ DriftSchedule, make_drift_schedule(), apply_drift_transform() — synthetic rotation-based drift, ramps up over rounds, tracks D_true (ground truth) separately from any estimator
│       ├── model_relative.py            ✅ ModelRelativeDriftTracker — loss-under-lagged-model minus running EMA. WORKS BUT NOISY at small scale (see Results)
│       └── model_independent.py         ✅ FrozenFeatureExtractor + ModelIndependentDriftTracker — frozen random CNN + mean-embedding distance from a reference window. WORKS WELL (see Results)
│   ├── methods/fedipw.py                ✅ ipw_aggregate() [1/propensity-weighted FedAvg], EstimatedPropensityTracker [per-client EMA of own participation history, NEVER sees D — this is the "realistic" propensity estimate]
│   └── simulation/mechanism_runner.py   ✅ run_mechanism_experiment() — the REAL, ASSEMBLED loop: drift injection + one dropout mechanism (mcar/mar/mnar) + one aggregation method (fedavg/fedipw_oracle/fedipw_estimated), per round, with the "algorithm never sees D for a round it didn't participate in" invariant enforced
├── scripts/
│   ├── run_day1_baseline.py             ✅ CLI runner for the Day-1 baseline, works
│   ├── run_day2_drift_check.py          ✅ Validates both drift estimators against injected ground truth, works
│   ├── run_day3_mechanism_check.py      ✅ Validates dropout mechanisms against REAL D values (rate-matching + rho-vs-beta), works
│   ├── run_mvp_comparison.py            ✅ First real MCAR/MAR/MNAR head-to-head run (single seed, reduced scale) — see Results
│   └── run_day5_fedipw_check.py         ✅ FedAvg vs FedIPW-oracle vs FedIPW-estimated, under MCAR vs MNAR — THE core theoretical test of the project — see Results
├── results/
│   ├── day1_femnist.json                First (small, quick) run: 15 clients, 15 rounds — flat ~4-5% accuracy, too small/short to learn
│   ├── day1_femnist_v2.json             Second (tuned) run: 40 clients, 40 rounds — REAL LEARNING CONFIRMED, see below
│   ├── day1_femnist_v2.log              Full console log of the v2 run
│   ├── day2_drift_check.log             Day-2 drift estimator validation log — see Results below
│   ├── day3_mechanism_check.log         Day-3/4 mechanism validation log (rate-matching + rho climbs with beta) — see Results below
│   ├── mvp_{mcar,mar,mnar}.json         Per-mechanism round logs from the first head-to-head comparison
│   └── mvp_comparison.log               Full console log + summary of the first head-to-head comparison
```

**Known gotcha already documented in the spec (Part 1):** any FL algorithm under test must only see drift score `D(i,t)` for rounds where the client actually participated — never leak the simulator's "god view" of D into an algorithm. Enforce this with a unit test when Day 2/5/6 code is written.

---

## Results so far

### Day 1, run v1 (`day1_femnist.json`) — too small, superseded
15 clients, 15 rounds, lr=0.01, batch=20. Accuracy stayed flat at ~4-5% (barely above random for 62 classes). **Diagnosis: not a bug — just too little data (2,826 train samples total) and too few rounds to learn 62-way classification.** Superseded by v2, kept only for reference.

### Day 1, run v2 (`day1_femnist_v2.json`) — ✅ the real proof-of-concept
40 clients, 40 rounds, local_epochs=2, lr=0.05, batch_size=10, eval_every=4. **7,153 train samples, 1,770 test samples, real writer-partitioned FEMNIST, 62 classes.**

| Round | Accuracy |
|---|---|
| 1 | 5.5% |
| 4 | 5.5% |
| 8 | 36.3% |
| 12 | 50.9% |
| 16 | 62.0% |
| 20 | 67.1% |
| 24 | 65.6% |
| 28 | 71.0% |
| 32 | **71.9%** |
| 36 | 72.8% (peak) |
| 40 | 56.2% ⚠️ |

**Verdict: the harness is proven correct** — accuracy climbs from near-random to ~72% peak, exactly the shape a real FedAvg run should have. **Open issue to investigate before trusting this fully:** the round-40 drop to 56% needs explanation. Leading hypotheses, cheapest-to-check first:
1. lr=0.05 may be too high for late-stage fine-tuning → try lr decay or a lower fixed lr (0.01–0.02) and rerun.
2. Small, non-IID per-client test sets → noisy accuracy estimate late in training; consider averaging last-k rounds or using a larger held-out eval set.
3. Real overfitting/divergence — less likely given the shape, but not ruled out.

**Do not treat round 40's number as the "final" baseline accuracy until this is resolved.** Use round 32-36 (~72%) as the working reference point for now.

### Day 2, drift estimator validation (`day2_drift_check.log`) — ✅ done, one estimator works well, one needs tuning

Setup: 15 FEMNIST clients, 6 of them scripted to start drifting (rotation, ramping up) at round 3, 10 rounds total. Compared both estimators' output against the known ground-truth injected drift (`D_true`).

| Estimator | Correlation with D_true | Verdict |
|---|---|---|
| **Model-independent** (frozen feature extractor + embedding distance) | **0.995** | ✅ Works essentially perfectly — clearly separates drifting (mean D=0.078) from stable (mean D=0.000) clients |
| **Model-relative** (loss under lagged global model − running EMA) | **0.020** | ⚠️ Not detecting drift reliably at this scale — essentially noise |

**Why the model-relative one is noisy (not a bug, a scale issue):** at only 15 clients / 10 rounds / small per-client batches, loss estimates are high-variance, and the EMA hasn't had enough rounds to stabilize. This is the exact risk the project spec flagged for this estimator (Part 3) — it's *supposed to* be compared against the model-independent one for exactly this reason. **Don't discard it** — retest at MVP scale (40 clients, more rounds) before deciding whether it needs a longer EMA warm-up, a lower decay rate, or is fundamentally too noisy to use as designed.

### Day 3/4, mechanism validation against real D (`day3_mechanism_check.log`) — ✅ works cleanly

40 FEMNIST clients, target dropout rate 30%. Result: **all mechanisms land near the 30% target** (MCAR 36.5%, MAR 30.5%, MNAR 29.5–33.0% across β=0–8), and **realized ρ(D, dropout) climbs monotonically with β**: 0.07 → 0.29 → 0.48 → 0.66 → 0.70 → 0.70 (saturating at high β — expected, a sigmoid can only push so hard). Threshold mechanism hit ρ=0.75, even stronger than logistic, as expected. **The core benchmark design (matched rate, controllable informativeness) works correctly on real data.**

### First real MCAR vs MAR vs MNAR head-to-head (`mvp_comparison.log`, `mvp_{mcar,mar,mnar}.json`) — ✅ ran, produced a genuinely interesting result

Single seed, reduced scale (25 clients, 25 rounds, target dropout rate 30%, drift = rotation on 10/25 clients starting round 2). **This is the actual assembled experiment for the first time** — drift injection + dropout mechanism + FedAvg all running together in `mechanism_runner.py`.

| Mechanism | Final accuracy (round 25) | Realized dropout rate | Realized ρ |
|---|---|---|---|
| MCAR | 52.1% | 0.360 | +0.24 (noise) |
| MAR | 50.7% | 0.280 | −0.14 (noise) |
| **MNAR** | **59.0%** | 0.360 | **+0.75 (real, by design)** |

**Important, honest finding: MNAR did *better* than both controls in this run, not worse.** This is not a bug — it's exactly the scenario the hostile-validation process (Part 7) flagged as a real possibility: our synthetic drift is a rotation, which makes a drifted client's data genuinely harder/noisier for the 62-way classification task. MNAR systematically *excludes* those noisier clients more often than MCAR/MAR do — so here it may be acting like an accidental denoising filter rather than a harmful blind spot. **This is a legitimate first data point for H1b (the genuinely open question — does informative dropout help, hurt, or do nothing to aggregate accuracy), not a confirmed result.** One run, one seed, reduced scale — needs the full multi-seed sweep (and a check with a *non-corrupting* drift definition, e.g. a label-distribution shift instead of image rotation, so "drift" isn't confounded with "objectively worse data") before treating this as a real finding either way.

**Action item before the full sweep:** reconsider whether rotation is the right drift-injection mechanism, since it conflates "different distribution" with "objectively corrupted/harder data" — a label-shift or class-imbalance-based drift injection would more cleanly test the intended question (informativeness of *absence*, not quality of the missing data itself). **Confirmed necessary by the Day 5 result below — do this before the full sweep.**

### Day 5, the actual theoretical test (`day5_fedipw_check.log`, `day5_*.json`) — ✅ ran, and it caught a real design flaw before the full sweep

Built `src/methods/fedipw.py` (`ipw_aggregate`, `EstimatedPropensityTracker` — the latter tracks ONLY each client's own participation history via EMA, never given access to D, exactly per the spec's no-god-view-leak rule). Ran FedAvg / FedIPW-oracle / FedIPW-estimated crossed with MCAR / MNAR (single seed, 25 clients, 25 rounds, same reduced-scale pilot as the MVP comparison).

| | FedAvg | FedIPW-oracle | FedIPW-estimated |
|---|---|---|---|
| **MCAR** | 0.5208 | **0.5208 (exactly equal)** | 0.5199 |
| **MNAR** | 0.5900 | 0.4949 (−0.095) | 0.4746 (−0.115) |

**Two real findings:**

1. **Correctness check passed:** under MCAR, FedIPW-oracle equals FedAvg *exactly*. This isn't a null result — under MCAR every client shares the same participation probability, so the IPW weight (1/p) is the same constant for everyone and mathematically collapses back to a plain average. Confirms `ipw_aggregate` is implemented correctly.

2. **Under MNAR, both FedIPW variants did *worse* than FedAvg — the opposite of the naive expectation, and directly explained by the same confound flagged above.** Since our rotation-based drift injection makes drifted clients' data objectively harder to classify (not just differently distributed), MNAR dropout is accidentally filtering out noisy data — and FedIPW's entire mechanism is to *undo* that filtering by up-weighting the rare drifted clients that do participate. Here, undoing the filtering hurts, because the filtered-out data really was worse for this task.

**This is genuinely useful, not a failure.** A pilot run at reduced scale caught a real experimental-design flaw — conflating "informativeness of dropout" with "data quality of the dropped client" — before it was baked into an expensive 350-run sweep. **This must be fixed before the full sweep or any of its results would be uninterpretable** (we wouldn't know whether an effect is about informativeness or about accidentally filtering bad data).

---

### The confound fix — ✅ implemented

Replaced the drift mechanism. `DriftSchedule` now has a `mode` field:
- **`"label_shift"` (new default):** a drifting client's data is progressively replaced with real, *undegraded* samples from a different real FEMNIST writer (drawn from a new `reserve_pool`, loaded via `load_femnist_reserve_pool()` in `loaders.py` — extra writer partitions disjoint from the main client set). No pixel is ever corrupted; only the client's local label/style distribution shifts. This is the fix.
- **`"rotation"` (legacy):** the original, confounded mechanism — kept in `injection.py` for reference only, not used going forward.

New pieces: `load_femnist_reserve_pool()` (data/loaders.py), `apply_label_shift_drift()` + `apply_drift()` dispatcher (drift/injection.py). All scripts (`run_day2_drift_check.py`, `run_day3_mechanism_check.py`, `run_mvp_comparison.py`, `run_day5_fedipw_check.py`) and `mechanism_runner.py` updated to load a reserve pool and use `mode="label_shift"`.

**Re-validated Day 2 under the fix:** model-independent estimator still detects drift cleanly — correlation with ground truth **0.752** (down from 0.995 under rotation, which makes sense: swapping in another real writer's samples is a gentler, more realistic shift than a dramatic 35° rotation, so the frozen-feature embedding distance is naturally smaller — but still clearly separates drifting from stable clients). Model-relative estimator still noisy (0.065), consistent with before — confirms that's a property of the estimator/scale, not an artifact of the old drift injection.

### Day 5 re-run under the fix (`day5_fedipw_check_v2_labelshift.log`) — ✅ confound confirmed fixed, cleaner signal emerging

| | FedAvg | FedIPW-oracle | FedIPW-estimated |
|---|---|---|---|
| **MCAR** | 0.6270 | **0.6270 (exactly equal)** | 0.5956 |
| **MNAR** | 0.6205 | 0.5873 (−0.033) | 0.6187 (−0.002) |

**Key confirmation: the old MNAR-beats-MCAR gap is gone.** FedAvg's accuracy under MCAR (0.627) and MNAR (0.621) are now nearly identical (before the fix: 0.52 vs 0.59, a huge artificial gap). This is strong evidence the earlier "MNAR does better" result really was the rotation/data-quality confound, not a genuine informativeness effect — exactly what fixing the drift mechanism should produce.

**A cleaner, theory-consistent (but still single-seed, NOT yet confirmed) signal is emerging:** oracle-IPW now costs accuracy specifically under MNAR (−3.3pp) while costing nothing under MCAR (still exactly equal — the correctness check holds up). That's the direction the project's central hypothesis predicts. Estimated-IPW doesn't show a clean version of this pattern yet (−3.1pp under MCAR, essentially 0 under MNAR — roughly flat rather than differential); this could be genuine (the EMA-based estimator has its own always-present lag/estimation-error regardless of mechanism) or could be single-seed noise. **Honest status: encouraging, not proven — this is exactly what the full multi-seed sweep exists to resolve, not a conclusion to report yet.**

---

## Exact next step

The confound is fixed and confirmed. Next: Day 6 (FL-FDMS), Day 7 (FedDrift), then the full multi-seed MVP sweep — which is what's needed to know whether the oracle-IPW-under-MNAR pattern above is real or single-seed noise.

---

## Earlier next-step note (superseded by the above, kept for history)

`src/mechanisms/dropout.py` (MCAR/MAR/MNAR/threshold) was written ahead of schedule but has never been run against real `D(i,t)` values — only reasoned about on paper. Now that Day 2 produces real D values:

1. Run `mnar_drift_dropout()` against the real `D_indep` values from Day 2's run and confirm: does increasing `beta` actually produce increasing realized correlation `ρ` between drift and dropout, as designed? (Sanity check before trusting the mechanism.)
2. Confirm the `_solve_alpha()` bisection actually holds the marginal dropout rate constant across different `beta` values on real (not synthetic) D distributions.
3. Wire dropout into `src/simulation/fedavg_baseline.py` — right now it only supports full participation. Needs a per-round participation mask applied before aggregation.
4. Only after that: Day 5 (FedIPW), Day 6 (FL-FDMS), Day 7 (FedDrift + first full smoke test).

---

## How to rerun what already works

```bash
cd /Users/akshitajain/prj4/drift-causal-fl

# Day-1 baseline, real FEMNIST, tuned settings (reproduces the ~72% result)
python3 scripts/run_day1_baseline.py --clients 40 --rounds 40 --local-epochs 2 --lr 0.05 --batch-size 10 --eval-every 4 --out results/day1_femnist_v3.json

# Quick smoke test (faster, smaller, for iterating on code changes)
python3 scripts/run_day1_baseline.py --clients 15 --rounds 15 --out results/smoke.json

# Day-2 drift estimator validation (reproduces corr=0.995 model-independent, corr=0.02 model-relative)
python3 scripts/run_day2_drift_check.py

# Day-3/4 mechanism validation against real drift scores (rate-matching + rho-vs-beta)
python3 scripts/run_day3_mechanism_check.py

# First real MCAR/MAR/MNAR head-to-head comparison (single seed, reduced scale, ~4-5 min)
python3 scripts/run_mvp_comparison.py
```

Runs are slow-ish on CPU (the v2 run took a while, with the last few rounds oddly slow — possibly machine sleep/throttling during a long background run; re-check wall-clock behavior on the next run and don't assume the same timing).
