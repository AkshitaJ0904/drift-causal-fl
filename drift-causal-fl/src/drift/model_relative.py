"""Drift estimator #1 (model-relative) — see project spec Part 3.

D(i,t) = current-round loss under a LAGGED global model, minus a running
average of the client's own recent loss.

We use the lagged model theta(t-1), not theta(t), specifically to soften
(not eliminate) the circularity loop flagged in the spec:

    theta(t) -> D(i,t) -> R(i,t) -> {who's observed} -> theta(t+1) -> D(i,t+1) -> ...

This is the same style of drift-detection test FedDrift itself uses, kept
deliberately comparable to the literature. Because it depends on the
current global model, EVERY finding produced with this estimator must
also be checked against the model-independent estimator (model_independent.py)
before it's trusted — that's the whole point of building both.
"""
from __future__ import annotations

from collections import defaultdict

import torch
import torch.nn as nn
import torch.nn.functional as F


class ModelRelativeDriftTracker:
    """Holds each client's running loss EMA across rounds — this is the
    per-client state a real deployment would also need to maintain."""

    def __init__(self, ema_decay: float = 0.7):
        self.ema_decay = ema_decay
        self._ema: dict[int, float] = {}

    def compute(self, client_id: int, lagged_model: nn.Module, x: torch.Tensor, y: torch.Tensor, device: str) -> float:
        """Returns D(i,t) for this client at this round using the lagged
        global model. Updates the internal EMA as a side effect — call this
        AT MOST once per (client, round)."""
        if len(y) == 0:
            return 0.0
        lagged_model.eval()
        with torch.no_grad():
            logits = lagged_model(x.to(device))
            current_loss = F.cross_entropy(logits, y.to(device)).item()

        prev_ema = self._ema.get(client_id)
        if prev_ema is None:
            # First time we see this client: no history yet, no drift signal.
            self._ema[client_id] = current_loss
            return 0.0

        d = current_loss - prev_ema
        self._ema[client_id] = self.ema_decay * prev_ema + (1 - self.ema_decay) * current_loss
        return d

    def reset(self) -> None:
        self._ema.clear()
