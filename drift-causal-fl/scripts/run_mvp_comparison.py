"""First real MCAR vs MAR vs MNAR comparison — the actual headline
experiment of the whole project, assembled for the first time.

This is a SINGLE-SEED, reduced-scale first look, not the full MVP sweep
(that's 350 runs per the spec). The goal here is just: does anything
interesting even show up? If yes, that justifies committing compute to
the full sweep. If not, that's useful too (see falsification criteria in
the spec).
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
    print("FIRST MCAR vs MAR vs MNAR COMPARISON (single seed, reduced scale)")
    print("=" * 70)

    clients, num_classes, name = load_clients(num_clients=25, seed=seed)
    client_ids = [c.client_id for c in clients]
    reserve_pool = load_femnist_reserve_pool(n_reserve=15, exclude_seed=seed, exclude_num_clients=25)

    schedule = make_drift_schedule(client_ids, drift_fraction=0.4, drift_start_round=2, rng=rng, ramp_rounds=6, mode="label_shift", reserve_pool=reserve_pool)
    print(f"[drift] {len(schedule.drift_start_round)}/{len(client_ids)} clients will drift (mode={schedule.mode}, real-writer label shift, no pixel corruption)")

    TARGET_RATE = 0.30
    ROUNDS = 25
    results = {}

    for mechanism, kwargs in [
        ("mcar", {}),
        ("mar", {"gamma": 2.0}),
        ("mnar", {"beta": 4.0}),
    ]:
        print(f"\n--- Running mechanism: {mechanism.upper()} ---")
        log = run_mechanism_experiment(
            clients=clients,
            num_classes=num_classes,
            schedule=schedule,
            mechanism=mechanism,
            target_rate=TARGET_RATE,
            rounds=ROUNDS,
            local_epochs=1,
            lr=0.03,
            batch_size=10,
            eval_every=5,
            seed=seed,
            reserve_pool=reserve_pool,
            log_path=f"results/mvp_{mechanism}.json",
            **kwargs,
        )
        results[mechanism] = log

    print("\n" + "=" * 70)
    print("SUMMARY — final-round accuracy by mechanism (matched dropout rate)")
    print("=" * 70)
    for mechanism, log in results.items():
        final = log[-1]
        print(
            f"{mechanism.upper():>4}: final accuracy = {final['accuracy']:.4f}  "
            f"(realized dropout rate = {final['realized_dropout_rate']:.3f}, rho = {final['realized_rho']:+.3f})"
        )
    print("=" * 70)


if __name__ == "__main__":
    main()
