"""Drift estimator #2 (model-independent) — see project spec Part 3.

Never touches the global model at all, so it CANNOT have the circularity
problem the model-relative estimator has. Instead: embed the client's
current-round images with a small, FIXED, never-trained feature extractor
(random weights, frozen forever), and measure how far the current-round
embedding distribution has moved from an early "reference window" for that
same client — a standard domain-shift-detection technique.

D(i,t) = squared distance between mean embeddings (a simplified / linear
MMD with a fixed random feature map). Cheap, standard, defensible — no
need for anything fancier than this for the MVP.
"""
from __future__ import annotations

import torch
import torch.nn as nn


class FrozenFeatureExtractor(nn.Module):
    """Small random CNN, weights frozen at init, NEVER updated during FL.
    Exists purely to produce a fixed embedding space for drift detection —
    it is not part of the model being federated-trained."""

    def __init__(self, out_dim: int = 32, seed: int = 1234):
        super().__init__()
        g = torch.Generator().manual_seed(seed)
        self.conv = nn.Conv2d(1, 8, kernel_size=5, stride=2, padding=2)
        self.pool = nn.AdaptiveAvgPool2d(4)
        self.fc = nn.Linear(8 * 4 * 4, out_dim)
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p, generator=g)
            else:
                nn.init.zeros_(p)
            p.requires_grad_(False)

    @torch.no_grad()
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = torch.relu(self.conv(x))
        h = self.pool(h)
        h = torch.flatten(h, 1)
        return self.fc(h)


class ModelIndependentDriftTracker:
    """Holds each client's reference-window embedding mean (captured the
    first time we see them) and compares later rounds against it."""

    def __init__(self, extractor: FrozenFeatureExtractor, device: str):
        self.extractor = extractor.to(device)
        self.device = device
        self._reference_mean: dict[int, torch.Tensor] = {}

    @torch.no_grad()
    def compute(self, client_id: int, x: torch.Tensor) -> float:
        if len(x) == 0:
            return 0.0
        emb = self.extractor(x.to(self.device))
        current_mean = emb.mean(dim=0)

        ref = self._reference_mean.get(client_id)
        if ref is None:
            # First observation becomes this client's reference window.
            self._reference_mean[client_id] = current_mean.clone()
            return 0.0

        d = torch.sum((current_mean - ref) ** 2).item()
        return d

    def reset(self) -> None:
        self._reference_mean.clear()
