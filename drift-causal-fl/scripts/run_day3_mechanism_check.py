"""Day 3/4 validation: run the dropout mechanisms against REAL drift scores
for the first time (previously only reasoned about on paper).

Checks the two things the whole benchmark design depends on (project spec,
Parts 2 and 5-6):
  1. Marginal dropout rate stays ~constant across MCAR / MAR / MNAR and
     across every beta value (the "matched-rate" design — informativeness
     changes, but amount of missing data does not).
  2. Realized correlation rho(D, dropout) actually climbs as beta increases
     (proof the MNAR mechanism is doing what it's supposed to).

Uses the model-independent drift estimator (D_indep) since Day 2 showed
that one is reliable; the model-relative one is noted as still-noisy and
revisited later.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import torch

from src.data.loaders import load_clients, load_femnist_reserve_pool
from src.drift.injection import make_drift_schedule, apply_drift
from src.drift.model_independent import ModelIndependentDriftTracker, FrozenFeatureExtractor
from src.mechanisms.dropout import (
    mcar_dropout,
    mar_dropout,
    mnar_drift_dropout,
    mnar_threshold_dropout,
    realized_correlation,
)


def main() -> None:
    device = "cpu"
    seed = 0
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)

    print("=" * 70)
    print("DAY 3/4 — dropout mechanisms tested against REAL drift scores")
    print("=" * 70)

    clients, num_classes, name = load_clients(num_clients=40, seed=seed)
    client_ids = np.array([c.client_id for c in clients])
    n = len(client_ids)
    reserve_pool = load_femnist_reserve_pool(n_reserve=20, exclude_seed=seed, exclude_num_clients=40)
    reserve_by_id = {c.client_id: c for c in reserve_pool}

    DRIFT_START = 2
    schedule = make_drift_schedule(list(client_ids), drift_fraction=0.4, drift_start_round=DRIFT_START, rng=rng, ramp_rounds=6, mode="label_shift", reserve_pool=reserve_pool)

    extractor = FrozenFeatureExtractor(out_dim=32, seed=1234)
    tracker = ModelIndependentDriftTracker(extractor, device=device)

    # Warm up: round 1 establishes each client's reference window (D=0 by definition).
    for client in clients:
        tracker.compute(client.client_id, client.train_x)

    # Round 2: apply drift, get real, meaningful D_indep values to test mechanisms against.
    TEST_ROUND = 2
    D = np.zeros(n)
    for idx, client in enumerate(clients):
        d_true = schedule.true_drift_magnitude(client.client_id, TEST_ROUND)
        x, _y = apply_drift(client.train_x, client.train_y, d_true, schedule, client.client_id, rng, reserve_by_id)
        D[idx] = tracker.compute(client.client_id, x)

    print(f"[data] D_indep at round {TEST_ROUND}: min={D.min():.4f} max={D.max():.4f} mean={D.mean():.4f} std={D.std():.4f}")
    n_drifting = sum(1 for cid in client_ids if schedule.is_drifting(int(cid), TEST_ROUND))
    print(f"[data] {n_drifting}/{n} clients actively drifting at this round")

    TARGET_RATE = 0.30
    N_SEEDS = 5

    print("\n--- Check 1: marginal dropout rate stays matched across mechanisms ---")
    print(f"Target rate: {TARGET_RATE:.2f}\n")

    mcar_rates = []
    for s in range(N_SEEDS):
        local_rng = np.random.default_rng(1000 + s)
        participates, _ = mcar_dropout(n, TARGET_RATE, local_rng)
        mcar_rates.append(1 - participates.mean())
    print(f"MCAR:              realized dropout rate = {np.mean(mcar_rates):.4f} (+/- {np.std(mcar_rates):.4f})")

    X_fixed = rng.normal(size=n)  # fixed, drift-independent covariate for MAR
    mar_rates = []
    for s in range(N_SEEDS):
        local_rng = np.random.default_rng(2000 + s)
        participates, _ = mar_dropout(X_fixed, TARGET_RATE, gamma=2.0, rng=local_rng)
        mar_rates.append(1 - participates.mean())
    print(f"MAR (gamma=2.0):   realized dropout rate = {np.mean(mar_rates):.4f} (+/- {np.std(mar_rates):.4f})")

    print("\nMNAR-logistic, sweeping beta:")
    betas = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0]
    rhos = []
    for beta in betas:
        rates, corrs = [], []
        for s in range(N_SEEDS):
            local_rng = np.random.default_rng(3000 + s)
            participates, p_miss = mnar_drift_dropout(D, TARGET_RATE, beta, local_rng)
            rates.append(1 - participates.mean())
            corrs.append(realized_correlation(D, participates))
        mean_rate, mean_rho = np.mean(rates), np.mean(corrs)
        rhos.append(mean_rho)
        print(f"  beta={beta:>4.1f}:  realized dropout rate = {mean_rate:.4f}  |  realized rho(D, dropout) = {mean_rho:+.4f}")

    print("\n--- Check 2: does rho climb monotonically with beta? ---")
    increasing = all(rhos[i] <= rhos[i + 1] + 1e-6 for i in range(len(rhos) - 1))
    print(f"rho sequence: {[round(r, 3) for r in rhos]}")
    print(f"Monotonically non-decreasing: {'YES' if increasing else 'NO — investigate'}")

    print("\n--- Threshold mechanism (robustness check) ---")
    participates = mnar_threshold_dropout(D, TARGET_RATE, base_rate=0.05, rng=rng)
    rate = 1 - participates.mean()
    rho = realized_correlation(D, participates)
    print(f"threshold: realized dropout rate = {rate:.4f}  |  realized rho(D, dropout) = {rho:+.4f}")

    print("=" * 70)
    print("PASS conditions: (1) all realized rates land near", TARGET_RATE, "(2) rho climbs with beta (3) rho stays 0 for MCAR/MAR, clearly nonzero for MNAR/threshold.")


if __name__ == "__main__":
    main()
