"""Day 2 validation: does either drift estimator actually track injected drift?

We inject known synthetic drift (label_shift — mixing in real samples from
a different real writer, no pixel corruption; see injection.py for why
this replaced the original rotation-based injection) into a subset of
clients, then check whether our two estimators (model-relative,
model-independent) produce HIGHER scores for drifting clients than for
stable ones, and whether the score correlates with the known ramp.

This is a sanity check, not a hypothesis test (that comes later once
mechanisms are wired in) — it just proves Day 2's code is real and working,
not just written.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import torch

from src.data.loaders import load_clients, load_femnist_reserve_pool
from src.drift.injection import make_drift_schedule, apply_drift
from src.drift.model_relative import ModelRelativeDriftTracker
from src.drift.model_independent import ModelIndependentDriftTracker, FrozenFeatureExtractor
from src.models.cnn import SmallCNN
from src.simulation.fedavg_baseline import local_train, fedavg_aggregate


def main() -> None:
    device = "cpu"
    seed = 0
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)

    print("=" * 70)
    print("DAY 2 — drift injection + estimator validation")
    print("=" * 70)

    clients, num_classes, name = load_clients(num_clients=15, seed=seed)
    client_ids = [c.client_id for c in clients]
    reserve_pool = load_femnist_reserve_pool(n_reserve=10, exclude_seed=seed, exclude_num_clients=15)
    reserve_by_id = {c.client_id: c for c in reserve_pool}

    DRIFT_START = 3
    schedule = make_drift_schedule(client_ids, drift_fraction=0.4, drift_start_round=DRIFT_START, rng=rng, ramp_rounds=8, mode="label_shift", reserve_pool=reserve_pool)
    drifting_ids = set(schedule.drift_start_round.keys())
    print(f"[drift] {len(drifting_ids)}/{len(client_ids)} clients will drift starting round {DRIFT_START}: {sorted(drifting_ids)}")

    global_model = SmallCNN(num_classes=num_classes).to(device)
    model_rel_tracker = ModelRelativeDriftTracker(ema_decay=0.7)
    extractor = FrozenFeatureExtractor(out_dim=32, seed=1234)
    model_indep_tracker = ModelIndependentDriftTracker(extractor, device=device)

    rows = []  # (round, client_id, D_true, D_model, D_indep)
    lagged_model = SmallCNN(num_classes=num_classes).to(device)
    lagged_model.load_state_dict(global_model.state_dict())

    ROUNDS = 10
    for rnd in range(1, ROUNDS + 1):
        state_dicts, weights = [], []
        for client in clients:
            d_true = schedule.true_drift_magnitude(client.client_id, rnd)
            x, y = apply_drift(client.train_x, client.train_y, d_true, schedule, client.client_id, rng, reserve_by_id)

            d_model = model_rel_tracker.compute(client.client_id, lagged_model, x, y, device)
            d_indep = model_indep_tracker.compute(client.client_id, x)
            rows.append((rnd, client.client_id, d_true, d_model, d_indep))

            local_model = SmallCNN(num_classes=num_classes).to(device)
            local_model.load_state_dict(global_model.state_dict())
            sd = local_train(local_model, type(client)(client.client_id, x, y, client.test_x, client.test_y), epochs=1, lr=0.02, batch_size=10, device=device)
            state_dicts.append(sd)
            weights.append(max(len(client.train_y), 1))

        lagged_model.load_state_dict(global_model.state_dict())
        new_state = fedavg_aggregate(state_dicts, weights)
        global_model.load_state_dict(new_state)
        print(f"[round {rnd:>2}] trained + drift-scored all clients")

    # --- validation: do our estimators correlate with the injected ground truth? ---
    d_true = np.array([r[2] for r in rows])
    d_model = np.array([r[3] for r in rows])
    d_indep = np.array([r[4] for r in rows])

    def safe_corr(a, b):
        if a.std() == 0 or b.std() == 0:
            return float("nan")
        return float(np.corrcoef(a, b)[0, 1])

    print("=" * 70)
    print(f"corr(D_true, D_model)  = {safe_corr(d_true, d_model):.3f}   (model-relative estimator)")
    print(f"corr(D_true, D_indep)  = {safe_corr(d_true, d_indep):.3f}   (model-independent estimator)")

    # also: drifting clients vs stable clients, at the last round only
    last_round_rows = [r for r in rows if r[0] == ROUNDS]
    drift_vals_model = [r[3] for r in last_round_rows if r[1] in drifting_ids]
    stable_vals_model = [r[3] for r in last_round_rows if r[1] not in drifting_ids]
    drift_vals_indep = [r[4] for r in last_round_rows if r[1] in drifting_ids]
    stable_vals_indep = [r[4] for r in last_round_rows if r[1] not in drifting_ids]

    print(f"\nAt final round ({ROUNDS}):")
    print(f"  model-relative:   drifting clients mean D = {np.mean(drift_vals_model):+.4f}  |  stable clients mean D = {np.mean(stable_vals_model):+.4f}")
    print(f"  model-independent: drifting clients mean D = {np.mean(drift_vals_indep):.4f}  |  stable clients mean D = {np.mean(stable_vals_indep):.4f}")
    print("=" * 70)
    print("PASS condition: drifting clients' mean D should be clearly higher than stable clients' for at least one estimator.")


if __name__ == "__main__":
    main()
