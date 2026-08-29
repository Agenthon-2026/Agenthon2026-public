"""Track 4 metric: factor-replication composite for code-execution units.

The agent replicates a canonical return-based factor (e.g. MAX, 12-1 momentum, BAB)
from a raw CRSP panel and submits (a) per-stock factor scores by formation month and
(b) the monthly long-short factor return series. The verifier compares both against
frozen reference series (OSAP primary, JKP secondary; Chen & Zimmermann 2022; Jensen,
Kelly & Pedersen 2023) and aggregates:

    composite = w_sc * series_corr        # corr(agent LS returns, reference LS returns)
              + w_rc * signal_rank_corr   # mean monthly cross-sectional Spearman vs ref signal
              + w_ir * icir_ratio         # agent ICIR / reference ICIR, capped at 1
              + w_sp * spread_sanity      # decile-spread sign + magnitude vs reference
              + w_re * reasoning          # structural sub-score of the qualitative layer

Every component is clipped to [0, 1] before weighting, so the composite is bounded in
[0, 1] and a sign-flipped (actively wrong) replication scores 0 on the return-based
components rather than earning partial credit. Weights come from the unit card's
`[scoring.params].composite_weights`; per-unit thresholds gate the binary Harbor reward.

Alpha vs the market is reported with Newey-West (1987) HAC standard errors as a
diagnostic component of `spread_sanity`-style checks; the IC/ICIR conventions follow
Grinold & Kahn (2000).
"""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray


# ----------------------------------------------------------------------------- #
# Ranking helpers                                                                #
# ----------------------------------------------------------------------------- #
def _average_ranks(x: NDArray[np.float64]) -> NDArray[np.float64]:
    """Ranks in [1, n] with ties assigned the average of their positions."""
    x = np.asarray(x, dtype=np.float64)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty_like(x)
    ranks[order] = np.arange(1, x.size + 1, dtype=np.float64)
    # average ties: group equal values in sorted order
    sorted_x = x[order]
    i = 0
    while i < sorted_x.size:
        j = i
        while j + 1 < sorted_x.size and sorted_x[j + 1] == sorted_x[i]:
            j += 1
        if j > i:
            avg = 0.5 * (i + j) + 1.0  # positions are i..j (0-based) -> ranks i+1..j+1
            ranks[order[i : j + 1]] = avg
        i = j + 1
    return ranks


def spearman(x: NDArray[np.float64], y: NDArray[np.float64]) -> float:
    """Spearman rank correlation with average-tie ranks; NaN if degenerate."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if x.size != y.size or x.size < 3:
        return float("nan")
    rx, ry = _average_ranks(x), _average_ranks(y)
    sx, sy = rx.std(), ry.std()
    if sx == 0.0 or sy == 0.0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


# ----------------------------------------------------------------------------- #
# Information coefficient / ICIR                                                 #
# ----------------------------------------------------------------------------- #
def monthly_ic(
    scores: Sequence[NDArray[np.float64]],
    fwd_returns: Sequence[NDArray[np.float64]],
    min_names: int = 10,
) -> NDArray[np.float64]:
    """Per-month cross-sectional Spearman IC between factor scores and next-period
    returns. Months with fewer than `min_names` aligned names yield NaN (dropped by
    `icir`). `scores[t]` and `fwd_returns[t]` must be aligned same-length vectors."""
    if len(scores) != len(fwd_returns):
        raise ValueError(f"got {len(scores)} score months vs {len(fwd_returns)} return months")
    out = np.full(len(scores), np.nan, dtype=np.float64)
    for t, (s, r) in enumerate(zip(scores, fwd_returns)):
        s = np.asarray(s, dtype=np.float64)
        r = np.asarray(r, dtype=np.float64)
        keep = np.isfinite(s) & np.isfinite(r)
        if int(keep.sum()) >= min_names:
            out[t] = spearman(s[keep], r[keep])
    return out


def icir(ics: NDArray[np.float64], annualize: bool = False, periods_per_year: int = 12) -> float:
    """ICIR = mean(IC) / std(IC) over non-NaN months (Grinold & Kahn 2000).
    With `annualize`, multiplied by sqrt(periods_per_year)."""
    ics = np.asarray(ics, dtype=np.float64)
    ics = ics[np.isfinite(ics)]
    if ics.size < 12:
        return float("nan")
    sd = float(ics.std(ddof=1))
    if sd == 0.0:
        return float("nan")
    ratio = float(ics.mean()) / sd
    return ratio * float(np.sqrt(periods_per_year)) if annualize else ratio


# ----------------------------------------------------------------------------- #
# Decile spread                                                                  #
# ----------------------------------------------------------------------------- #
def decile_spread(
    scores: NDArray[np.float64],
    fwd_returns: NDArray[np.float64],
    n_groups: int = 10,
    weights: NDArray[np.float64] | None = None,
) -> float:
    """One-month top-minus-bottom group return spread, groups formed on `scores`
    (group 1 = lowest score). Optional `weights` (e.g. market cap) weight the group
    means; default equal-weight. NaN if the cross-section is too thin."""
    s = np.asarray(scores, dtype=np.float64)
    r = np.asarray(fwd_returns, dtype=np.float64)
    w = np.ones_like(s) if weights is None else np.asarray(weights, dtype=np.float64)
    keep = np.isfinite(s) & np.isfinite(r) & np.isfinite(w) & (w >= 0)
    s, r, w = s[keep], r[keep], w[keep]
    if s.size < 2 * n_groups:
        return float("nan")
    edges = np.quantile(s, np.linspace(0.0, 1.0, n_groups + 1))
    top = s >= edges[-2]
    bot = s <= edges[1]
    if w[top].sum() <= 0 or w[bot].sum() <= 0:
        return float("nan")
    top_ret = float(np.average(r[top], weights=w[top]))
    bot_ret = float(np.average(r[bot], weights=w[bot]))
    return top_ret - bot_ret


def mean_decile_spread(
    scores: Sequence[NDArray[np.float64]],
    fwd_returns: Sequence[NDArray[np.float64]],
    n_groups: int = 10,
    weights: Sequence[NDArray[np.float64]] | None = None,
) -> float:
    """Time-series mean of the monthly decile spread (NaN months dropped)."""
    spreads = [
        decile_spread(s, r, n_groups=n_groups, weights=None if weights is None else weights[t])
        for t, (s, r) in enumerate(zip(scores, fwd_returns))
    ]
    arr = np.asarray(spreads, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    return float(arr.mean()) if arr.size else float("nan")


# ----------------------------------------------------------------------------- #
# Alpha with Newey-West errors                                                   #
# ----------------------------------------------------------------------------- #
def alpha_newey_west(
    ls_returns: NDArray[np.float64],
    mkt_excess: NDArray[np.float64],
    lags: int = 6,
) -> tuple[float, float]:
    """(alpha, t-stat) from ls_t = alpha + beta * mkt_t + e_t with Newey-West (1987)
    HAC standard errors using `lags` Bartlett-weighted autocovariance lags."""
    y = np.asarray(ls_returns, dtype=np.float64)
    m = np.asarray(mkt_excess, dtype=np.float64)
    keep = np.isfinite(y) & np.isfinite(m)
    y, m = y[keep], m[keep]
    n = y.size
    if n < max(24, lags + 2):
        return float("nan"), float("nan")
    x = np.column_stack([np.ones(n), m])  # [n, 2]
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)  # [2]
    e = y - x @ beta
    xe = x * e[:, None]  # [n, 2] score contributions
    s = xe.T @ xe / n  # lag-0
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)  # Bartlett weight
        gamma = xe[lag:].T @ xe[:-lag] / n  # [2, 2]
        s += w * (gamma + gamma.T)
    xtx_inv = np.linalg.inv(x.T @ x / n)
    cov = xtx_inv @ s @ xtx_inv / n
    se_alpha = float(np.sqrt(cov[0, 0]))
    alpha = float(beta[0])
    return alpha, (alpha / se_alpha if se_alpha > 0 else float("nan"))


# ----------------------------------------------------------------------------- #
# Series correlation                                                             #
# ----------------------------------------------------------------------------- #
def series_correlation(
    a_keys: Sequence[int | str],
    a_vals: NDArray[np.float64],
    b_keys: Sequence[int | str],
    b_vals: NDArray[np.float64],
    min_overlap: int = 120,
    method: str = "pearson",
) -> float:
    """Correlation of two time series inner-joined on period keys (e.g. yyyymm ints).
    NaN when the finite overlap is shorter than `min_overlap` months."""
    a_map = {k: float(v) for k, v in zip(a_keys, np.asarray(a_vals, dtype=np.float64))}
    common = [k for k in b_keys if k in a_map]
    b_map = {k: float(v) for k, v in zip(b_keys, np.asarray(b_vals, dtype=np.float64))}
    a = np.asarray([a_map[k] for k in common], dtype=np.float64)
    b = np.asarray([b_map[k] for k in common], dtype=np.float64)
    keep = np.isfinite(a) & np.isfinite(b)
    a, b = a[keep], b[keep]
    if a.size < min_overlap or a.std() == 0.0 or b.std() == 0.0:
        return float("nan")
    if method == "spearman":
        return spearman(a, b)
    if method != "pearson":
        raise ValueError(f"unknown method '{method}'")
    return float(np.corrcoef(a, b)[0, 1])


# ----------------------------------------------------------------------------- #
# Composite                                                                      #
# ----------------------------------------------------------------------------- #
_COMPONENT_KEYS = ("series_corr", "signal_rank_corr", "icir_ratio", "spread_sanity", "reasoning")

DEFAULT_WEIGHTS: dict[str, float] = {
    "series_corr": 0.35,
    "signal_rank_corr": 0.25,
    "icir_ratio": 0.20,
    "spread_sanity": 0.10,
    "reasoning": 0.10,
}


def clip01(x: float) -> float:
    """Clip to [0, 1]; NaN maps to 0 (a missing/degenerate component earns nothing)."""
    if not np.isfinite(x):
        return 0.0
    return float(min(1.0, max(0.0, x)))


def replication_composite(
    components: Mapping[str, float],
    weights: Mapping[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    """Weighted [0,1] composite over the five components (missing key = error: the
    verifier must compute every component explicitly, scoring 0 via NaN if degenerate).
    Returns (composite, clipped_components). Weights must sum to 1 within 1e-9."""
    w = dict(DEFAULT_WEIGHTS if weights is None else weights)
    unknown = set(w) - set(_COMPONENT_KEYS)
    if unknown:
        raise ValueError(f"unknown composite weight keys: {sorted(unknown)}")
    total = sum(w.values())
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"composite weights must sum to 1, got {total}")
    missing = [k for k in w if k not in components]
    if missing:
        raise KeyError(f"missing composite components: {missing}")
    clipped = {k: clip01(float(components[k])) for k in w}
    composite = float(sum(w[k] * clipped[k] for k in w))
    return composite, clipped
