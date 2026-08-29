"""Track 1 metric: unbiased pass@k.

Reference: Chen et al., 2021, "Evaluating Large Language Models Trained on Code",
Eq. (1). For a task with `n` sampled agent attempts of which `c` pass the
admissibility+correctness verifier, the unbiased estimator of the probability that
at least one of k independent samples passes is

    pass@k = 1 - C(n-c, k) / C(n, k) = 1 - prod_{i=n-c+1}^{n} (1 - k/i).

The product form is used for numerical stability (no large binomials).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k for a single task.

    Args:
        n: number of agent attempts sampled (n >= k).
        c: number of attempts that passed the verifier (0 <= c <= n).
        k: target k.
    Returns:
        Estimated P(at least one of k samples passes) in [0, 1].
    """
    if not (0 <= c <= n):
        raise ValueError(f"require 0<=c<=n, got n={n}, c={c}")
    if k > n:
        raise ValueError(f"require k<=n, got k={k}, n={n}")
    if n - c < k:
        return 1.0
    idx = np.arange(n - c + 1, n + 1, dtype=np.float64)  # shape [c]
    return float(1.0 - np.prod(1.0 - k / idx))


def pass_at_k_suite(
    passed: NDArray[np.bool_],  # shape [T, n_attempts]
    k: int,
) -> NDArray[np.float64]:  # shape [T]
    """Per-task pass@k over a suite of T tasks, each with the same n_attempts."""
    if passed.ndim != 2:
        raise ValueError(f"expected [T, n_attempts], got shape {passed.shape}")
    n = passed.shape[1]
    c = passed.sum(axis=1)  # shape [T]
    return np.array([pass_at_k(n, int(ci), k) for ci in c], dtype=np.float64)


def suite_summary(
    passed: NDArray[np.bool_],  # shape [T, n_attempts]
    ks: tuple[int, ...] = (1, 3),
) -> dict[str, NDArray[np.float64]]:
    """Returns {'pass@1': [T], 'pass@3': [T], ...}; feed each to bootstrap.bootstrap_ci
    for the leaderboard point estimate + CI across tasks."""
    return {f"pass@{k}": pass_at_k_suite(passed, k) for k in ks}
