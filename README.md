# Drift-Causal Dropout Pipeline

**Does client dropout caused by a device's own current data drift hurt federated learning differently than ordinary dropout, when the total amount of missing data is held exactly equal — and does an existing bias-correction method (FedIPW) stay valid under this condition?**

Federated learning trains one shared model across many devices without centralizing their data. Not every device participates in every round. Almost all existing work assumes dropout is unrelated to what's happening on the device locally. This project tests what happens when that assumption breaks: a device that's more or less likely to report *because of* the condition it's currently experiencing (e.g. a sensor going offline exactly when it detects an anomaly).

## Repository layout

- **`research_discovery.md`** — the structured literature search that identified this research gap, with novelty classification against the closest prior work.
- **`full_research_report.md`** — consolidated discovery pass plus a first adversarial audit.
- **`candidate1_adversarial_audit.md`**, **`candidate1_final_hostile_validation.md`** — two further rounds of hostile novelty/validity checks against the strongest counter-arguments, run before committing engineering time to the idea.
- **`candidate1_project_specification.md`** — the formal research specification: problem definition, hypotheses, benchmark design, baselines, metrics, implementation architecture, and build plan.
- **`drift-causal-fl/`** — the implementation.

## `drift-causal-fl/`

```
src/
  data/        dataset loading and client partitioning (real FEMNIST, writer-partitioned)
  drift/       drift injection and two independent drift estimators
  mechanisms/  the three dropout conditions (random, irrelevant-factor, drift-caused)
  methods/     FedIPW (the bias-correction method under test)
  models/      the CNN used across all experiments
  simulation/  the federated learning round loop
scripts/       runnable experiments, one per project milestone
results/       logs and output from every run so far
PROGRESS.md    live status: what's implemented, what's verified, current results, next step
```

### Running it

```bash
cd drift-causal-fl
pip install -r requirements.txt
python3 scripts/run_day1_baseline.py --clients 40 --rounds 40
```

See `PROGRESS.md` for the full set of experiments and how to reproduce each one.

## Status

Baseline federated training, drift detection, the three dropout conditions, and the FedIPW bias-correction method are implemented and validated on real data. See `drift-causal-fl/PROGRESS.md` for current results and what's next.
