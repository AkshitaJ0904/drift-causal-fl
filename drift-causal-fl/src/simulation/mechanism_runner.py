"""The real MVP loop: drift injection + a dropout mechanism + FedAvg,
combined for the first time.

Everything here was validated independently first (Day 1: FedAvg baseline
works; Day 2: drift estimators detect real drift; Day 3/4: mechanisms
produce correctly-calibrated, correctly-correlated dropout on real data).
This module is where they're finally assembled into one runnable
experiment — the actual MCAR vs MAR vs MNAR comparison the whole project
is built around.
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import numpy as np
import torch

from src.data.loaders import ClientData
from src.drift.injection import DriftSchedule, apply_drift
from src.drift.model_independent import FrozenFeatureExtractor, ModelIndependentDriftTracker
from src.mechanisms.dropout import mar_dropout, mcar_dropout, mnar_drift_dropout, realized_correlation
from src.methods.fedipw import EstimatedPropensityTracker, ipw_aggregate
from src.models.cnn import SmallCNN
from src.simulation.fedavg_baseline import evaluate, fedavg_aggregate, local_train


def run_mechanism_experiment(
    clients: list[ClientData],
    num_classes: int,
    schedule: DriftSchedule,
    mechanism: str,  # "mcar" | "mar" | "mnar"
    target_rate: float,
    rounds: int,
    method: str = "fedavg",  # "fedavg" | "fedipw_oracle" | "fedipw_estimated"
    reserve_pool: list[ClientData] | None = None,  # required if schedule.mode == "label_shift"
    beta: float = 2.0,
    gamma: float = 2.0,
    local_epochs: int = 1,
    lr: float = 0.02,
    batch_size: int = 10,
    eval_every: int = 4,
    seed: int = 0,
    device: str | None = None,
    log_path: str | Path | None = None,
) -> list[dict]:
    """Run one full FL simulation under ONE dropout mechanism AND ONE
    aggregation method, with drift injection active throughout. Only
    clients selected to 'participate' that round contribute to
    aggregation — everyone else's update is silently dropped, exactly like
    a real device that went offline.

    CRITICAL invariant (spec Part 1): the mechanism only ever sees D for
    the round being decided — it never gets god-view of future D, and no
    algorithm here ever sees D for a round it didn't participate in.
    FedIPW-estimated in particular is NEVER given D — only its own past
    participation record (see EstimatedPropensityTracker).
    """
    assert mechanism in ("mcar", "mar", "mnar")
    assert method in ("fedavg", "fedipw_oracle", "fedipw_estimated")
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    device = device or "cpu"

    global_model = SmallCNN(num_classes=num_classes).to(device)
    extractor = FrozenFeatureExtractor(out_dim=32, seed=1234)
    drift_tracker = ModelIndependentDriftTracker(extractor, device=device)
    propensity_tracker = EstimatedPropensityTracker() if method == "fedipw_estimated" else None

    n = len(clients)
    fixed_X = rng.normal(size=n)  # fixed MAR covariate, drift-independent by construction
    reserve_by_id = {c.client_id: c for c in reserve_pool} if reserve_pool else {}

    # Warm-up round: establishes each client's reference window for drift
    # scoring (D=0 by definition on the first observation) — no dropout yet.
    for client in clients:
        drift_tracker.compute(client.client_id, client.train_x)

    log: list[dict] = []
    t0 = time.time()

    for rnd in range(1, rounds + 1):
        # 1. compute this round's drift-affected data + drift score per client.
        #    Every image used here is real, unmodified FEMNIST handwriting —
        #    "drift" (mode=label_shift) means mixing in another real writer's
        #    samples, never corrupting the client's own images.
        D = np.zeros(n)
        round_x, round_y = [], []
        for idx, client in enumerate(clients):
            d_true = schedule.true_drift_magnitude(client.client_id, rnd)
            x, y = apply_drift(client.train_x, client.train_y, d_true, schedule, client.client_id, rng, reserve_by_id)
            round_x.append(x)
            round_y.append(y)
            D[idx] = drift_tracker.compute(client.client_id, x)

        # 2. decide who participates this round, per the chosen mechanism.
        #    p_miss is the TRUE generating miss-probability — only ever used
        #    by the oracle-IPW variant, which is explicitly allowed this
        #    "god view" as its whole point (an upper bound on what any
        #    real correction could achieve). fedipw_estimated NEVER touches
        #    p_miss; it only sees its own tracked participation history.
        if mechanism == "mcar":
            participates, p_miss = mcar_dropout(n, target_rate, rng)
        elif mechanism == "mar":
            participates, p_miss = mar_dropout(fixed_X, target_rate, gamma, rng)
        else:  # mnar
            participates, p_miss = mnar_drift_dropout(D, target_rate, beta, rng)

        rho = realized_correlation(D, participates)

        # 3. local train ONLY participating clients; non-participants' data
        #    (and this round's D for them) is simply never used this round.
        state_dicts, weights, propensities, drifting_participants = [], [], [], 0
        for idx, client in enumerate(clients):
            # FedIPW-estimated tracks EVERY client's participation history,
            # whether or not they participated this round — that's the
            # observable signal it's legitimately allowed to use.
            if propensity_tracker is not None:
                p_hat = propensity_tracker.observe_and_get(client.client_id, bool(participates[idx]))
            if not participates[idx]:
                continue
            local_model = SmallCNN(num_classes=num_classes).to(device)
            local_model.load_state_dict(global_model.state_dict())
            sd = local_train(local_model, ClientData(client.client_id, round_x[idx], round_y[idx], client.test_x, client.test_y), local_epochs, lr, batch_size, device)
            state_dicts.append(sd)
            weights.append(max(len(client.train_y), 1))
            if method == "fedipw_oracle":
                propensities.append(1.0 - p_miss[idx])
            elif method == "fedipw_estimated":
                propensities.append(max(p_hat, 1e-3))
            if schedule.is_drifting(client.client_id, rnd):
                drifting_participants += 1

        if state_dicts:
            if method == "fedavg":
                new_state = fedavg_aggregate(state_dicts, weights)
            else:
                new_state = ipw_aggregate(state_dicts, weights, propensities)
            global_model.load_state_dict(new_state)

        if rnd % eval_every == 0 or rnd == 1 or rnd == rounds:
            acc = evaluate(global_model, clients, device)
            n_drifting_total = sum(1 for c in clients if schedule.is_drifting(c.client_id, rnd))
            entry = {
                "round": rnd,
                "mechanism": mechanism,
                "method": method,
                "accuracy": acc,
                "n_participants": int(participates.sum()),
                "realized_dropout_rate": float(1 - participates.mean()),
                "realized_rho": rho,
                "n_drifting_total": n_drifting_total,
                "n_drifting_participated": drifting_participants,
                "elapsed_sec": round(time.time() - t0, 1),
            }
            log.append(entry)
            print(
                f"[{mechanism:>4} round {rnd:>3}/{rounds}] acc={acc:.4f}  "
                f"participants={int(participates.sum())}/{n}  rho={rho:+.3f}  "
                f"drifting_participated={drifting_participants}/{n_drifting_total}"
            )

    if log_path is not None:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w") as f:
            json.dump(log, f, indent=2)

    return log
