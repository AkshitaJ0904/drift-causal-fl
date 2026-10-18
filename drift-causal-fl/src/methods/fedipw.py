"""FedIPW — Day 5 of the plan, and the single most important method in the
whole project: this is the existing correction whose own math (Mean
Ignorability, Corollary 6.2 in the source paper) predicts it should fail
specifically under MNAR, because participation there depends on a state
(drift) outside its observed-covariate set.

Two variants, per the spec (Part 7/11):

  - ORACLE  : reweight by 1 / p_true, where p_true is the ACTUAL generating
              participation probability (only knowable because we're the
              ones simulating it). Upper bound — isolates whether the
              ignorability violation itself causes bias, independent of any
              estimation error.
  - ESTIMATED: reweight by 1 / p_hat, where p_hat is estimated PURELY from
              each client's own observed participation history (empirical
              frequency, matching DFL-AA's own approach) — NEVER given
              access to drift D. This is the realistic version: it can
              only correct for what it can actually observe.

Under MCAR/MAR, p_hat should track p_true reasonably well (participation
doesn't depend on anything the estimator can't see). Under MNAR, p_hat is
expected to systematically mis-estimate p_true for high/low-drift clients,
since D is invisible to it — this is the predicted failure mode.
"""
from __future__ import annotations

import copy

import numpy as np


def ipw_aggregate(state_dicts: list[dict], sample_weights: list[float], propensities: list[float]) -> dict:
    """Inverse-probability-weighted FedAvg: each participant's update is
    weighted by (sample_count / propensity) instead of just sample_count —
    a client who was UNLIKELY to show up gets extra weight when it does,
    to compensate for similar clients who didn't."""
    ipw_weights = [w / max(p, 1e-6) for w, p in zip(sample_weights, propensities)]
    total = sum(ipw_weights)
    avg = copy.deepcopy(state_dicts[0])
    for k in avg:
        avg[k] = sum(sd[k].float() * (w / total) for sd, w in zip(state_dicts, ipw_weights))
    return avg


class EstimatedPropensityTracker:
    """Tracks each client's empirical participation frequency across
    rounds — an exponential moving average, matching DFL-AA's own
    approach. This is the ONLY thing FedIPW-estimated is allowed to see:
    past participation record, nothing about current drift."""

    def __init__(self, decay: float = 0.8, prior: float = 0.5):
        self.decay = decay
        self.prior = prior
        self._freq: dict[int, float] = {}

    def observe_and_get(self, client_id: int, participated_this_round: bool) -> float:
        """Returns the propensity estimate to USE FOR THIS ROUND (based on
        history up to, not including, this round's outcome), then updates
        the running estimate with this round's outcome for next time."""
        p_hat = self._freq.get(client_id, self.prior)
        observed = 1.0 if participated_this_round else 0.0
        self._freq[client_id] = self.decay * p_hat + (1 - self.decay) * observed
        return p_hat

    def reset(self) -> None:
        self._freq.clear()
