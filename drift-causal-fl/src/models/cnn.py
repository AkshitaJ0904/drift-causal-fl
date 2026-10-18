"""Small CNN used across all experiments.

Matches the reference architecture used by LEAF / FedDrift for FEMNIST-scale
image classification: two conv layers + two fully-connected layers. Kept
identical across every method (FedAvg, FedIPW, FL-FDMS, FedDrift) so that any
difference we measure comes from the *aggregation/participation* logic, not
from architecture differences.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class SmallCNN(nn.Module):
    """2 conv + 2 FC, matching the LEAF FEMNIST reference model.

    Parameters
    ----------
    num_classes: number of output classes (62 for real FEMNIST — digits +
        upper + lower case letters; 10 for the MNIST smoke-test fallback).
    in_channels: 1 for grayscale handwriting images.
    """

    def __init__(self, num_classes: int = 62, in_channels: int = 1) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(in_channels, 32, kernel_size=5, padding=2)
        self.conv2 = nn.Conv2d(32, 64, kernel_size=5, padding=2)
        self.pool = nn.MaxPool2d(2, 2)
        # 28x28 -> pool -> 14x14 -> pool -> 7x7
        self.fc1 = nn.Linear(64 * 7 * 7, 2048)
        self.fc2 = nn.Linear(2048, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.pool(F.relu(self.conv1(x)))
        x = self.pool(F.relu(self.conv2(x)))
        x = torch.flatten(x, 1)
        x = F.relu(self.fc1(x))
        x = self.fc2(x)
        return x

    def get_flat_params(self) -> torch.Tensor:
        """Return all parameters flattened into one vector (used by drift
        metrics / update-distance calculations later in the project)."""
        return torch.cat([p.data.view(-1) for p in self.parameters()])

    def set_flat_params(self, flat: torch.Tensor) -> None:
        offset = 0
        for p in self.parameters():
            n = p.numel()
            p.data.copy_(flat[offset : offset + n].view_as(p))
            offset += n
