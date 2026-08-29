"""Cluster bootstrap confidence intervals.

Every leaderboard-relevant number in QFBench 2.0 ships with a bootstrap CI
(resampling over tasks / forecast windows / scenarios). When evaluation units are
correlated (e.g. multiple horizons of the same forecast card, multiple seeds of one
scenario) pass `cluster` to resample whole clusters and avoid CI under-coverage.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
from numpy.typing import NDArray


def bootstrap_ci(
    values: NDArray[np.float64],  # shape [N]
    agg: Callable[[NDArray[np.float64]], float] = np.mean,
    n_boot: int = 10_000,
    alpha: float = 0.05,
    cluster: NDArray[np.int_] | None = None,  # shape [N], cluster id per value
    seed: int = 0,
) -> tuple[float, float, float]:
    """Percentile bootstrap CI.

    Returns:
        (point, lo, hi) where point = agg(values) and (lo, hi) is the
        (1 - alpha) percentile interval of the bootstrap distribution of agg.
    """
    rng = np.random.default_rng(seed)
    values = np.asarray(values, dtype=np.float64)
    point = float(agg(values))

    if cluster is None:
        n = values.shape[0]
        idx = rng.integers(0, n, size=(n_boot, n))  # [n_boot, n]
        boot = np.array([agg(values[row]) for row in idx])  # [n_boot]
    else:
        cluster = np.asarray(cluster)
        groups = [values[cluster == c] for c in np.unique(cluster)]
        g = len(groups)
        boot = np.empty(n_boot, dtype=np.float64)
        for b in range(n_boot):
            pick = rng.integers(0, g, size=g)
            boot[b] = agg(np.concatenate([groups[i] for i in pick]))

    lo, hi = np.quantile(boot, [alpha / 2, 1 - alpha / 2])
    return point, float(lo), float(hi)


def paired_gap_ci(
    a: NDArray[np.float64],  # shape [N] metric for submission A
    b: NDArray[np.float64],  # shape [N] metric for submission B (same units)
    n_boot: int = 10_000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Bootstrap CI for the paired performance gap mean(a - b); used to decide whether
    a leaderboard ranking difference is statistically meaningful."""
    return bootstrap_ci(np.asarray(a) - np.asarray(b), np.mean, n_boot, alpha, None, seed)
