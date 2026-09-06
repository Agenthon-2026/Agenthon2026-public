"""Track 2 metric: CRPS composite for probabilistic JOINT forecasts.

Headline ranking (lower is better):

    S = w_m * CRPS_marginal  +  w_j * S_joint  +  w_t * P_tail,     w = (0.5, 0.3, 0.2)

  * CRPS_marginal : mean over (asset x horizon) of the univariate CRPS
                    (Gneiting & Raftery, 2007). Energy/ensemble estimator below.
  * S_joint       : multivariate dependence score — energy score (Gneiting & Raftery,
                    2007) or variogram score of order p (Scheuerer & Hamill, 2015).
                    Variogram-p (default p=0.5) is robust and sensitive to mis-specified
                    cross-asset correlation; it is the default for the joint term.
  * P_tail        : tail-calibration penalty = sum over tail levels of |coverage - level|
                    via the probability integral transform.

Because the three components live on different scales, each is divided by the official
baseline's component value (a skill-score normalization) before weighting; pass
`ref_scale` to do so. Without it the raw components are returned (use for diagnostics).
A component with both zero weight and exactly zero reference scale contributes zero.
Missing required scales and zero scales with nonzero weights still raise; a merely tiny
scale is still divided by, preserving non-finite results for callers to diagnose.

Estimator note: the ensemble CRPS uses the "fair" (almost-unbiased) spread term with
1/(m(m-1)) (Ferro 2014; Zamo & Naveau 2018); set `fair=False` for the biased 1/m^2 form.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


# ----------------------------------------------------------------------------- #
# Univariate / marginal CRPS                                                     #
# ----------------------------------------------------------------------------- #
def _mean_abs_pairwise_sorted(x_sorted: NDArray[np.float64], fair: bool) -> NDArray[np.float64]:
    """(1/denom) * sum_{i,j} |x_i - x_j| for each column, x_sorted ascending along axis 0.

    Uses the identity (for ascending x):  sum_{i,j}|x_i-x_j| = 2 * sum_i (2i-m-1) x_(i).
    x_sorted: [m] or [m, d]; returns scalar or [d].
    """
    m = x_sorted.shape[0]
    i = np.arange(1, m + 1, dtype=np.float64)
    coef = 2.0 * i - m - 1.0
    if x_sorted.ndim == 2:
        coef = coef[:, None]
    s = 2.0 * np.sum(coef * x_sorted, axis=0)
    # The "fair" denom m*(m-1) is undefined for a single-member ensemble; fall back to the
    # biased m*m there (which yields spread 0 -> CRPS = |x-y|, the point-forecast value)
    # instead of returning NaN.
    denom = m * (m - 1) if (fair and m > 1) else m * m
    return s / denom


def crps_ensemble(
    samples: NDArray[np.float64],  # [m] or [m, d]
    y: NDArray[np.float64] | float,  # scalar or [d]
    fair: bool = True,
) -> NDArray[np.float64]:  # scalar or [d]
    """Ensemble CRPS = E|X - y| - 0.5 * E|X - X'|, O(m log m) per dimension."""
    samples = np.asarray(samples, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    term1 = np.abs(samples - y).mean(axis=0)  # E|X-y|
    spread = _mean_abs_pairwise_sorted(np.sort(samples, axis=0), fair)  # E|X-X'|
    return term1 - 0.5 * spread


def crps_marginal(
    samples: NDArray[np.float64],  # [m, d]  d = assets*horizons flattened
    y: NDArray[np.float64],  # [d]
    fair: bool = True,
) -> float:
    """Mean univariate CRPS across the d marginals."""
    return float(np.mean(crps_ensemble(samples, y, fair=fair)))


# ----------------------------------------------------------------------------- #
# Multivariate joint scores                                                      #
# ----------------------------------------------------------------------------- #
def energy_score(samples: NDArray[np.float64], y: NDArray[np.float64], fair: bool = True) -> float:
    """ES = E||X - y|| - 0.5 E||X - X'||; samples [m, d], y [d]. O(m^2 d)."""
    samples = np.asarray(samples, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    m = samples.shape[0]
    term1 = np.linalg.norm(samples - y[None, :], axis=1).mean()
    diff = samples[:, None, :] - samples[None, :, :]  # [m, m, d]
    pn = np.linalg.norm(diff, axis=2)  # [m, m]
    denom = m * (m - 1) if (fair and m > 1) else m * m  # m=1: biased denom (spread 0) not NaN
    term2 = pn.sum() / denom
    return float(term1 - 0.5 * term2)


def variogram_score(
    samples: NDArray[np.float64],  # [m, d]
    y: NDArray[np.float64],  # [d]
    p: float = 0.5,
    weights: NDArray[np.float64] | None = None,  # [d, d]
) -> float:
    """Variogram score of order p (Scheuerer & Hamill, 2015). Sensitive to mis-specified
    cross-asset dependence; insensitive to marginal bias (complements the marginal term)."""
    samples = np.asarray(samples, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    d = y.shape[0]
    w = np.ones((d, d)) if weights is None else np.asarray(weights, dtype=np.float64)
    y_vg = np.abs(y[:, None] - y[None, :]) ** p  # [d, d]
    x_vg = (np.abs(samples[:, :, None] - samples[:, None, :]) ** p).mean(axis=0)  # [d, d]
    return float(np.sum(w * (y_vg - x_vg) ** 2))


# ----------------------------------------------------------------------------- #
# Tail calibration                                                               #
# ----------------------------------------------------------------------------- #
def tail_penalty(
    samples: NDArray[np.float64],  # [m, d]
    y: NDArray[np.float64],  # [d]
    levels: tuple[float, ...] = (0.01, 0.05, 0.95, 0.99),
) -> float:
    """Sum over tail levels a of |coverage_a - a|, where coverage_a = mean_d 1{y_d <= Q_a}.
    Under calibration P(y <= Q_a) = a for every a (PIT uniformity)."""
    samples = np.asarray(samples, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    err = 0.0
    for a in levels:
        q = np.quantile(samples, a, axis=0)  # [d]
        cov = float(np.mean(y <= q))
        err += abs(cov - a)
    return err


# ----------------------------------------------------------------------------- #
# Composite                                                                      #
# ----------------------------------------------------------------------------- #
def _normalize(
    value: float,
    ref_scale: dict[str, float] | None,
    key: str,
    weight: float,
    *,
    optional: bool = False,
) -> float:
    """Normalize one component, skipping only a zero-weight, exactly zero-scale pair.

    Read required keys before checking the weight so malformed scale mappings still raise.
    Do not skip merely small denominators: doing so would hide a non-finite statistic.
    This helper does not change a caller's reference-scale validation rules.
    """
    if not ref_scale:
        return value
    if optional and key not in ref_scale:
        return value
    scale = ref_scale[key]
    if scale == 0.0 and weight == 0.0:
        return 0.0
    return value / scale


def crps_composite(
    samples: NDArray[np.float64],  # [m, d]
    y: NDArray[np.float64],  # [d]
    weights: tuple[float, float, float] = (0.5, 0.3, 0.2),
    tail_levels: tuple[float, ...] = (0.01, 0.05, 0.95, 0.99),
    joint: str = "variogram",
    vs_p: float = 0.5,
    ref_scale: dict[str, float] | None = None,  # {'marginal':..,'joint':..} baseline values
    fair: bool = True,
) -> dict[str, float]:
    """Returns {'marginal','joint','tail','composite'}; 'composite' is the leaderboard value
    (lower better). If ref_scale is given, marginal/joint are skill-normalized by it.
    A component with both zero weight and exactly zero scale contributes zero; see
    `_normalize` for the required-key and non-finite behavior."""
    w_m, w_j, w_t = weights
    marg = crps_marginal(samples, y, fair=fair)
    if joint == "energy":
        jnt = energy_score(samples, y, fair=fair)
    elif joint == "variogram":
        jnt = variogram_score(samples, y, p=vs_p)
    else:
        raise ValueError(f"unknown joint score '{joint}'")
    tail = tail_penalty(samples, y, levels=tail_levels)

    # Skill-score normalization by the official baseline's component values. `tail` is a
    # unit-free PIT-coverage penalty, so it is only normalized when ref_scale supplies a
    # 'tail' key; otherwise it is left as-is (its natural scale ~ sum over levels). This keeps
    # all three components on a comparable scale before the (w_m, w_j, w_t) weighting.
    m_n = _normalize(marg, ref_scale, "marginal", w_m)
    j_n = _normalize(jnt, ref_scale, "joint", w_j)
    t_n = _normalize(tail, ref_scale, "tail", w_t, optional=True)
    composite = w_m * m_n + w_j * j_n + w_t * t_n
    return {"marginal": marg, "joint": jnt, "tail": tail, "composite": float(composite)}
