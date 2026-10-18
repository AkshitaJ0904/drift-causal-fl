"""Day 5 — the actual theoretical test this whole project is built around.

Per the spec (Part 11): FedIPW's Mean Ignorability assumption should hold
under MCAR/MAR (participation depends only on things outside D), so its
correction should behave normally there. Under MNAR, participation depends
on D specifically — which FedIPW-estimated never gets to see — so its
propensity estimates should be systematically wrong for high/low-drift
clients, and its correction should degrade relative to how it performs
under MCAR/MAR.

This script runs FedAvg / FedIPW-oracle / FedIPW-estimated under both MCAR
and MNAR (single seed, reduced scale — a first look, not the final sweep)
and reports the mechanism x method pattern directly.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from src.data.loaders import load_clients, load_femnist_reserve_pool
from src.drift.injection import make_drift_schedule
from src.simulation.mechanism_runner import run_mechanism_experiment


def main() -> None:
    seed = 0
    rng = np.random.default_rng(seed)

    print("=" * 70)
    print("DAY 5 — FedAvg vs FedIPW-oracle vs FedIPW-estimated, under MCAR vs MNAR")
    print("=" * 70)

    clients, num_classes, name = load_clients(num_clients=25, seed=seed)
    client_ids = [c.client_id for c in clients]
    reserve_pool = load_femnist_reserve_pool(n_reserve=15, exclude_seed=seed, exclude_num_clients=25)
    schedule = make_drift_schedule(client_ids, drift_fraction=0.4, drift_start_round=2, rng=rng, ramp_rounds=6, mode="label_shift", reserve_pool=reserve_pool)
    print(f"[drift] mode={schedule.mode} (real-writer label shift, no pixel corruption)")

    TARGET_RATE = 0.30
    ROUNDS = 25
    results = {}

    for mechanism in ["mcar", "mnar"]:
        for method in ["fedavg", "fedipw_oracle", "fedipw_estimated"]:
            key = f"{mechanism}_{method}"
            print(f"\n--- {mechanism.upper()} + {method} ---")
            log = run_mechanism_experiment(
                clients=clients,
                num_classes=num_classes,
                schedule=schedule,
                mechanism=mechanism,
                method=method,
                target_rate=TARGET_RATE,
                rounds=ROUNDS,
                beta=4.0,
                local_epochs=1,
                lr=0.03,
                batch_size=10,
                eval_every=5,
                seed=seed,
                reserve_pool=reserve_pool,
                log_path=f"results/day5_{key}.json",
            )
            results[key] = log

    print("\n" + "=" * 70)
    print("SUMMARY — final accuracy (round 25), by mechanism x method")
    print("=" * 70)
    print(f"{'':>10} | {'fedavg':>10} | {'ipw_oracle':>10} | {'ipw_est':>10}")
    for mechanism in ["mcar", "mnar"]:
        row = []
        for method in ["fedavg", "fedipw_oracle", "fedipw_estimated"]:
            acc = results[f"{mechanism}_{method}"][-1]["accuracy"]
            row.append(f"{acc:.4f}")
        print(f"{mechanism.upper():>10} | {row[0]:>10} | {row[1]:>10} | {row[2]:>10}")

    print("\nDoes FedIPW's advantage over FedAvg shrink specifically under MNAR?")
    for method in ["fedipw_oracle", "fedipw_estimated"]:
        mcar_gain = results[f"mcar_{method}"][-1]["accuracy"] - results["mcar_fedavg"][-1]["accuracy"]
        mnar_gain = results[f"mnar_{method}"][-1]["accuracy"] - results["mnar_fedavg"][-1]["accuracy"]
        print(f"  {method}: gain over FedAvg under MCAR = {mcar_gain:+.4f}  |  under MNAR = {mnar_gain:+.4f}")
    print("=" * 70)


if __name__ == "__main__":
    main()
