"""Synthetic drift injection (Day 2 of the plan; drift MECHANISM fixed after
the Day 5 confound finding — see PROGRESS.md).

FEMNIST has no natural short-timescale drift — writers don't change their
handwriting mid-simulation. So, exactly like FedDrift and other
concept-drift FL papers do, we SCRIPT a drift event: a chosen subset of
clients gets their local data changed starting at a chosen round, with a
known ground-truth magnitude we can use later to validate our two drift
*estimators* (model-relative and model-independent) against the truth.

Two injection MODES are implemented (see DriftSchedule):
  - "label_shift" (DEFAULT, fixed): mixes in real samples from a different
    real writer — no image is ever corrupted, only the client's local
    distribution shifts. Use this one.
  - "rotation" (LEGACY): rotates the client's own images. Kept only for
    reference / comparison — Day 5 found this confounds "drift" with
    "objectively harder data," which made the FedIPW result uninterpretable.

This keeps a clean separation, spelled out in the project spec:
  - D_true   = what we, the simulator, actually injected (known exactly)
  - D_model  = what the model-relative estimator infers (Days 2, method 1)
  - D_indep  = what the model-independent estimator infers (Days 2, method 2)
Only D_model / D_indep are ever visible to an FL algorithm; D_true is for
our own validation only — never leaked into the mechanisms or algorithms.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import torch
import torch.nn.functional as F


@dataclass
class DriftSchedule:
    """Per-client drift assignment: which clients drift, from which round,
    how severe it ramps up to, and by which mechanism.

    mode="rotation": LEGACY, kept for reference only — confounds drift with
      objective data corruption (Day 5 finding, see PROGRESS.md). Rotating
      a character's image makes it genuinely harder to classify, so a
      drifting client's data isn't just "different," it's "worse" — any
      result using this mode can't distinguish "informativeness of
      dropout" from "we're accidentally filtering out harder data."

    mode="label_shift": THE FIX, and the default going forward. A
      drifting client's data is progressively replaced with real,
      undegraded samples from a DIFFERENT real FEMNIST writer (see
      loaders.load_femnist_reserve_pool). Every single image involved is
      genuine, unmodified handwriting — nothing is corrupted or made
      objectively harder. The client's local distribution genuinely
      shifts (different writer's style + label mix), which is exactly
      what "drift" is supposed to mean, without smuggling in a quality
      confound.
    """

    drift_start_round: dict[int, int]  # client_id -> round drift begins (absent = never drifts)
    mode: str = "label_shift"  # "label_shift" (default/fixed) | "rotation" (legacy/confounded)
    drift_source_id: dict[int, int] = field(default_factory=dict)  # client_id -> reserve client_id (label_shift mode)
    max_angle_deg: float = 35.0  # rotation magnitude at full ramp (rotation mode only)
    ramp_rounds: int = 10  # rounds to reach max severity after drift starts

    def true_drift_magnitude(self, client_id: int, round_num: int) -> float:
        """D_true — ground truth, 0..1 normalized severity. Never given to
        any algorithm; used only to validate our estimators."""
        start = self.drift_start_round.get(client_id)
        if start is None or round_num < start:
            return 0.0
        progress = min(1.0, (round_num - start + 1) / self.ramp_rounds)
        return progress

    def is_drifting(self, client_id: int, round_num: int) -> bool:
        return self.true_drift_magnitude(client_id, round_num) > 0.0


def make_drift_schedule(
    client_ids: list[int],
    drift_fraction: float,
    drift_start_round: int,
    rng: np.random.Generator,
    ramp_rounds: int = 10,
    max_angle_deg: float = 35.0,
    mode: str = "label_shift",
    reserve_pool: list | None = None,
) -> DriftSchedule:
    """Pick a random subset of clients (drift_fraction of them) to start
    drifting at drift_start_round. Everyone else never drifts (D_true = 0
    for the whole run) — they're the 'stable' comparison population.

    mode="label_shift" (default): each drifting client is assigned a
    random, distinct reserve-pool writer as its drift source. Requires
    reserve_pool with at least as many entries as drifting clients.
    """
    n_drift = max(1, int(round(len(client_ids) * drift_fraction)))
    chosen = rng.choice(client_ids, size=n_drift, replace=False)
    schedule = {int(cid): drift_start_round for cid in chosen}

    drift_source_id: dict[int, int] = {}
    if mode == "label_shift":
        if not reserve_pool or len(reserve_pool) < n_drift:
            raise ValueError(f"label_shift mode needs a reserve_pool with >= {n_drift} clients, got {len(reserve_pool) if reserve_pool else 0}")
        source_order = rng.permutation(len(reserve_pool))[:n_drift]
        for cid, src_idx in zip(chosen, source_order):
            drift_source_id[int(cid)] = reserve_pool[int(src_idx)].client_id

    return DriftSchedule(
        drift_start_round=schedule,
        mode=mode,
        drift_source_id=drift_source_id,
        max_angle_deg=max_angle_deg,
        ramp_rounds=ramp_rounds,
    )


def apply_label_shift_drift(
    orig_x: torch.Tensor, orig_y: torch.Tensor, source_x: torch.Tensor, source_y: torch.Tensor, magnitude: float, rng: np.random.Generator
) -> tuple[torch.Tensor, torch.Tensor]:
    """Replace a `magnitude` fraction of a client's own (real) samples with
    real samples from a DIFFERENT writer (the drift source). Every image
    involved is genuine, unmodified FEMNIST handwriting — this is what
    makes it a clean distributional shift instead of a data-quality
    confound (see DriftSchedule docstring)."""
    if magnitude <= 0 or len(orig_y) == 0:
        return orig_x, orig_y
    n = len(orig_y)
    n_swap = int(round(magnitude * n))
    if n_swap == 0:
        return orig_x, orig_y

    swap_idx = rng.choice(n, size=n_swap, replace=False)
    source_idx = rng.choice(len(source_y), size=n_swap, replace=True)

    x = orig_x.clone()
    y = orig_y.clone()
    x[swap_idx] = source_x[source_idx]
    y[swap_idx] = source_y[source_idx]
    return x, y


def apply_drift(
    orig_x: torch.Tensor,
    orig_y: torch.Tensor,
    magnitude: float,
    schedule: DriftSchedule,
    client_id: int,
    rng: np.random.Generator,
    reserve_by_id: dict[int, "ClientData"] | None = None,  # noqa: F821
) -> tuple[torch.Tensor, torch.Tensor]:
    """Single dispatcher used by all callers — routes to whichever drift
    mode the schedule specifies, so downstream code never has to know the
    difference between rotation (legacy) and label_shift (fixed)."""
    if magnitude <= 0:
        return orig_x, orig_y
    if schedule.mode == "rotation":
        return apply_drift_transform(orig_x, magnitude, schedule.max_angle_deg), orig_y
    elif schedule.mode == "label_shift":
        src_id = schedule.drift_source_id[client_id]
        source = reserve_by_id[src_id]
        return apply_label_shift_drift(orig_x, orig_y, source.train_x, source.train_y, magnitude, rng)
    raise ValueError(f"unknown drift mode: {schedule.mode}")


def apply_drift_transform(x: torch.Tensor, magnitude: float, max_angle_deg: float) -> torch.Tensor:
    """Apply a rotation of magnitude*max_angle_deg to a batch of images
    (N,1,28,28). magnitude in [0,1] — this is the actual mechanism that
    makes a 'drifted' client's data look different, used for BOTH training
    (the client really is seeing different data) and as the source signal
    our drift estimators are trying to detect."""
    if magnitude <= 0:
        return x
    angle = magnitude * max_angle_deg
    theta = torch.tensor(
        [[np.cos(np.radians(angle)), -np.sin(np.radians(angle)), 0], [np.sin(np.radians(angle)), np.cos(np.radians(angle)), 0]],
        dtype=torch.float32,
    ).unsqueeze(0).repeat(x.size(0), 1, 1)
    grid = F.affine_grid(theta, x.size(), align_corners=False)
    return F.grid_sample(x, grid, align_corners=False)
