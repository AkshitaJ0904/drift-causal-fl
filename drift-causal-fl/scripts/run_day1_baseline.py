"""Day 1 of the 7-day plan: reproduce a basic FedAvg-on-handwriting-images
run with FULL participation, and confirm accuracy climbs sensibly.

No dropout mechanism is involved yet — this is purely the "is our
simulation harness trustworthy" sanity check that everything else in the
project is built on top of.

Usage:
    python3 scripts/run_day1_baseline.py --clients 20 --rounds 30
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.loaders import load_clients
from src.simulation.fedavg_baseline import run_fedavg_full_participation


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--clients", type=int, default=20, help="number of simulated devices")
    p.add_argument("--rounds", type=int, default=30, help="communication rounds")
    p.add_argument("--local-epochs", type=int, default=1)
    p.add_argument("--lr", type=float, default=0.01)
    p.add_argument("--batch-size", type=int, default=20)
    p.add_argument("--eval-every", type=int, default=5)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--no-femnist", action="store_true", help="skip trying FEMNIST, go straight to the MNIST smoke test")
    p.add_argument("--out", type=str, default="results/day1_baseline.json")
    args = p.parse_args()

    print("=" * 70)
    print("DAY 1 — trustworthy full-participation FedAvg baseline")
    print("=" * 70)

    clients, num_classes, dataset_name = load_clients(
        num_clients=args.clients, seed=args.seed, prefer_femnist=not args.no_femnist
    )

    total_train = sum(len(c.train_y) for c in clients)
    total_test = sum(len(c.test_y) for c in clients)
    print(f"[data] {len(clients)} clients | {total_train} train samples | {total_test} test samples")

    log = run_fedavg_full_participation(
        clients=clients,
        num_classes=num_classes,
        rounds=args.rounds,
        local_epochs=args.local_epochs,
        lr=args.lr,
        batch_size=args.batch_size,
        eval_every=args.eval_every,
        seed=args.seed,
        log_path=args.out,
    )

    print("=" * 70)
    final_acc = log[-1]["accuracy"] if log else float("nan")
    print(f"RESULT: dataset={dataset_name} | final accuracy after {args.rounds} rounds = {final_acc:.4f}")
    print("=" * 70)


if __name__ == "__main__":
    main()
