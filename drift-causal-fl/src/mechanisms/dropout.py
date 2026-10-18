"""The three dropout mechanisms (Days 3-4 of the project plan).

Each mechanism returns a boolean "participates this round" array over
clients, all calibrated so the average dropout rate matches a shared
target — this is the core methodological trick of the whole project: we're
isolating *who* is missing, not *how much* is missing.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def sigmoid(x: np.ndarray) -> np.ndarray:
    """The 'squishing function' — turns any real number into (0, 1)."""
    return 1.0 / (1.0 + np.exp(-x))


def _clip_positivity(p: np.ndarray, lo: float = 0.05, hi: float = 0.95) -> np.ndarray:
    """Keep every participation probability strictly away from 0 and 1.
    Required for FedIPW's own math (inverse-probability weights explode as
    p -> 0), and keeps 'ignorability violation bias' separable from
    'IPW variance blowup from near-zero propensities' as two distinct,
    non-confounded effects (see project spec, Part 2)."""
    return np.clip(p, lo, hi)


def mcar_dropout(num_clients: int, target_rate: float, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """P(miss) = p — a single fixed number, same for every client, every
    round. No relationship to anything about the client.

    Returns (participates, p_miss) — p_miss is trivially the same constant
    for everyone, but returned for interface consistency with the other
    mechanisms (needed by oracle-IPW, which needs the TRUE participation
    probability regardless of which mechanism generated it)."""
    p_miss = np.full(num_clients, target_rate)
    participates = rng.random(num_clients) >= target_rate
    return participates, p_miss


def mar_dropout(
    X: np.ndarray, target_rate: float, gamma: float, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """P(miss) = sigmoid(alpha + gamma * X)

    X is a FIXED, drift-independent covariate per client (assigned once at
    setup — e.g. a device-class label), standardized before use. alpha is
    solved so the *average* miss probability across clients equals
    target_rate, exactly like the MNAR case below — this keeps MAR and
    MNAR fairly comparable.

    Returns (participates, p_miss), same reasoning as mcar_dropout above.
    """
    X_std = (X - X.mean()) / (X.std() + 1e-8)
    alpha = _solve_alpha(X_std, gamma, target_rate)
    p_miss = _clip_positivity(sigmoid(alpha + gamma * X_std))
    participates = rng.random(num_clients_from(X)) >= p_miss
    return participates, p_miss


def mnar_drift_dropout(
    D: np.ndarray, target_rate: float, beta: float, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """P(miss) = sigmoid(alpha + beta * D)  — the core mechanism of the project.

    D = each client's CURRENT drift score, standardized within-round before
    use so beta is comparably scaled across rounds/datasets. alpha is
    re-solved every round (numeric bisection) so the *marginal* dropout
    rate matches target_rate regardless of beta — beta only changes WHO is
    likely to be missing, never HOW MANY are missing on average.

    Returns (participates_mask, realized_miss_probability) — the second
    value is kept so we can later compute the realized correlation
    rho = corr(D, missing) as required by the project's coupling-axis
    design (Part 5/6 of the spec).
    """
    D_std = (D - D.mean()) / (D.std() + 1e-8)
    alpha = _solve_alpha(D_std, beta, target_rate)
    p_miss = _clip_positivity(sigmoid(alpha + beta * D_std))
    participates = rng.random(len(D)) >= p_miss
    return participates, p_miss


def mnar_threshold_dropout(
    D: np.ndarray, target_rate: float, base_rate: float, rng: np.random.Generator
) -> np.ndarray:
    """Robustness-check mechanism (required alongside the logistic version,
    per the project spec's Part 2): the top-`target_rate` percentile of
    drift is deterministically dropped, everything else uses a small base
    Bernoulli rate — tests whether findings depend on the smooth logistic
    shape or hold under a harder, threshold-style censoring too."""
    n = len(D)
    k = int(round(target_rate * n))
    order = np.argsort(-D)  # highest drift first
    dropped = np.zeros(n, dtype=bool)
    dropped[order[:k]] = True
    remaining_random = rng.random(n) < base_rate
    dropped = dropped | (remaining_random & ~dropped)
    return ~dropped  # participates


def _solve_alpha(x: np.ndarray, coef: float, target_rate: float, iters: int = 60) -> float:
    """Numeric bisection for alpha so mean(sigmoid(alpha + coef*x)) == target_rate.
    This is what keeps every mechanism's *average* dropout rate identical —
    the whole point of the matched-rate benchmark design."""
    lo, hi = -20.0, 20.0
    for _ in range(iters):
        mid = (lo + hi) / 2
        rate = sigmoid(mid + coef * x).mean()
        if rate < target_rate:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def num_clients_from(x: np.ndarray) -> int:
    return len(x)


def realized_correlation(D: np.ndarray, participates: np.ndarray) -> float:
    """rho = point-biserial correlation between drift and missingness —
    the project's primary reported coupling-strength axis (spec Part 5).
    Sanity check: this should climb toward 1.0 as beta increases."""
    missing = (~participates).astype(float)
    if missing.std() == 0 or D.std() == 0:
        return 0.0
    return float(np.corrcoef(D, missing)[0, 1])
