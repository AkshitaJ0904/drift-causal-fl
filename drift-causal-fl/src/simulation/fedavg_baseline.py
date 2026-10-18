"""Day-1 milestone: a trustworthy, full-participation FedAvg baseline.

No dropout mechanism yet (that's Days 3-4 of the plan). The only goal here
is to prove the simulation harness itself is correct — every client
participates in every round, and accuracy should climb the way any standard
FedAvg-on-handwriting-images run would.
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from src.data.loaders import ClientData, TensorDS
from src.models.cnn import SmallCNN


def local_train(model: nn.Module, client: ClientData, epochs: int, lr: float, batch_size: int, device: str) -> dict:
    """One client's local training pass. Returns its updated state_dict."""
    if len(client.train_y) == 0:
        return model.state_dict()
    model.train()
    opt = torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9)
    loss_fn = nn.CrossEntropyLoss()
    loader = DataLoader(TensorDS(client.train_x, client.train_y), batch_size=batch_size, shuffle=True)
    for _ in range(epochs):
        for xb, yb in loader:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            out = model(xb)
            loss = loss_fn(out, yb)
            loss.backward()
            opt.step()
    return model.state_dict()


def fedavg_aggregate(state_dicts: list[dict], weights: list[float]) -> dict:
    """Weighted average of client state_dicts (weighted by #local samples,
    the standard FedAvg weighting)."""
    total = sum(weights)
    avg = copy.deepcopy(state_dicts[0])
    for k in avg:
        avg[k] = sum(sd[k].float() * (w / total) for sd, w in zip(state_dicts, weights))
    return avg


@torch.no_grad()
def evaluate(model: nn.Module, clients: list[ClientData], device: str) -> float:
    model.eval()
    correct, total = 0, 0
    for c in clients:
        if len(c.test_y) == 0:
            continue
        x, y = c.test_x.to(device), c.test_y.to(device)
        pred = model(x).argmax(dim=1)
        correct += (pred == y).sum().item()
        total += len(y)
    return correct / max(total, 1)


def run_fedavg_full_participation(
    clients: list[ClientData],
    num_classes: int,
    rounds: int = 100,
    local_epochs: int = 1,
    lr: float = 0.01,
    batch_size: int = 20,
    eval_every: int = 5,
    seed: int = 0,
    device: str | None = None,
    log_path: str | Path | None = None,
) -> list[dict]:
    """Runs FULL-PARTICIPATION FedAvg (every client, every round) and returns
    the per-round accuracy log. This is the Day-1 sanity-check baseline —
    no dropout mechanism is applied here."""
    torch.manual_seed(seed)
    np.random.seed(seed)
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")

    global_model = SmallCNN(num_classes=num_classes).to(device)
    log: list[dict] = []
    t0 = time.time()

    for rnd in range(1, rounds + 1):
        state_dicts, weights = [], []
        for client in clients:
            local_model = SmallCNN(num_classes=num_classes).to(device)
            local_model.load_state_dict(global_model.state_dict())
            sd = local_train(local_model, client, local_epochs, lr, batch_size, device)
            state_dicts.append(sd)
            weights.append(max(len(client.train_y), 1))

        new_state = fedavg_aggregate(state_dicts, weights)
        global_model.load_state_dict(new_state)

        if rnd % eval_every == 0 or rnd == 1 or rnd == rounds:
            acc = evaluate(global_model, clients, device)
            elapsed = time.time() - t0
            entry = {"round": rnd, "accuracy": acc, "elapsed_sec": round(elapsed, 1)}
            log.append(entry)
            print(f"[round {rnd:>3}/{rounds}] test accuracy = {acc:.4f}  (elapsed {elapsed:.1f}s)")

    if log_path is not None:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w") as f:
            json.dump(log, f, indent=2)
        print(f"[log] wrote {log_path}")

    return log
