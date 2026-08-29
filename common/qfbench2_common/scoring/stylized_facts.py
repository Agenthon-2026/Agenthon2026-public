"""Track 3: stylized-fact divergences + admissibility.

A candidate ABIDES-compatible simulator is *admissible* iff (a) it passes the 26-scenario
semantic regression suite (matching-engine semantics + sealed-trace reproduction within
tolerance, checked elsewhere) and (b) every stylized-fact divergence below is under its
calibrated ceiling. Admissible submissions are then ranked by events/sec.

Stylized facts (Cont, 2001, "Empirical properties of asset returns"):
  * heavy-tailed return distribution      -> KS distance vs reference; Hill tail index
  * volatility clustering                  -> ACF of |r_t| at lags
  * intraday seasonality (U-shape)         -> profile divergence
  * order-book depth distribution          -> Jensen-Shannon divergence
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

try:
    from scipy.stats import ks_2samp  # type: ignore

    _HAVE_SCIPY = True
except Exception:  # pragma: no cover - scipy optional at import time
    _HAVE_SCIPY = False


def log_returns(prices: NDArray[np.float64]) -> NDArray[np.float64]:
    """[T] mid/last prices -> [T-1] log returns."""
    prices = np.asarray(prices, dtype=np.float64)
    return np.diff(np.log(prices))


def ks_distance(r: NDArray[np.float64], r_ref: NDArray[np.float64]) -> float:
    """Two-sample KS statistic between candidate and reference return distributions."""
    if _HAVE_SCIPY:
        return float(ks_2samp(r, r_ref).statistic)
    # Fallback: empirical-CDF sup distance on the pooled grid.
    grid = np.sort(np.concatenate([r, r_ref]))

    def cdf(x: NDArray[np.float64], g: NDArray[np.float64]) -> NDArray[np.float64]:
        return np.searchsorted(np.sort(x), g, side="right") / x.size

    return float(np.max(np.abs(cdf(r, grid) - cdf(r_ref, grid))))


def acf(x: NDArray[np.float64], lags: tuple[int, ...]) -> NDArray[np.float64]:
    """Sample autocorrelation of x at the given lags. Returns [len(lags)].

    Raises ValueError on an invalid lag (k < 0 or k >= len(x)) rather than silently
    returning 0.0 from an empty slice, and on a constant/degenerate series (zero variance)
    rather than emitting NaN — both would otherwise mask a broken simulator as "passing"
    the volatility-clustering gate.
    """
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    bad = [k for k in lags if k < 0 or k >= n]
    if bad:
        raise ValueError(
            f"acf lags {bad} out of range for series of length {n} (need 0 <= lag < n)"
        )
    x = x - x.mean()
    denom = np.dot(x, x)
    if denom == 0.0:
        raise ValueError("acf undefined for a constant (zero-variance) series")
    out = np.empty(len(lags), dtype=np.float64)
    for i, k in enumerate(lags):
        out[i] = 1.0 if k == 0 else np.dot(x[:-k], x[k:]) / denom
    return out


def acf_abs_l2(
    r: NDArray[np.float64],
    r_ref: NDArray[np.float64],
    lags: tuple[int, ...] = (1, 5, 10, 20, 50),
) -> float:
    """RMS difference between ACF(|r|) of candidate and reference over lags
    (volatility-clustering fidelity)."""
    d = acf(np.abs(r), lags) - acf(np.abs(r_ref), lags)
    return float(np.sqrt(np.mean(d**2)))


def hill_estimator(r: NDArray[np.float64], k: int) -> float:
    """Hill (1975) tail-index estimator on the upper tail of |r| using the top-k order stats.
    Returns alpha = 1 / xi (larger alpha = lighter tail)."""
    a = np.sort(np.abs(np.asarray(r, dtype=np.float64)))[::-1]
    k = min(k, a.size - 1)
    top = a[: k + 1]
    xi = np.mean(np.log(top[:-1]) - np.log(top[-1]))
    return float(1.0 / xi) if xi > 0 else np.inf


def hill_error(r: NDArray[np.float64], r_ref: NDArray[np.float64], k: int = 100) -> float:
    """|alpha_candidate - alpha_reference| (tail-index fidelity)."""
    return abs(hill_estimator(r, k) - hill_estimator(r_ref, k))


def jensen_shannon(p: NDArray[np.float64], q: NDArray[np.float64], eps: float = 1e-12) -> float:
    """JS divergence between two histograms (normalized internally). Used for depth dist."""
    p = np.asarray(p, dtype=np.float64) + eps
    q = np.asarray(q, dtype=np.float64) + eps
    p /= p.sum()
    q /= q.sum()
    m = 0.5 * (p + q)

    def kl(a: NDArray[np.float64], b: NDArray[np.float64]) -> np.float64:
        return np.sum(a * np.log(a / b))

    return float(0.5 * kl(p, m) + 0.5 * kl(q, m))


def stylized_fact_report(
    cand_prices: NDArray[np.float64],
    ref_prices: NDArray[np.float64],
    cand_intraday_vol: NDArray[np.float64] | None = None,
    ref_intraday_vol: NDArray[np.float64] | None = None,
    cand_depth_hist: NDArray[np.float64] | None = None,
    ref_depth_hist: NDArray[np.float64] | None = None,
    lags: tuple[int, ...] = (1, 5, 10, 20, 50),
    hill_k: int = 100,
) -> dict[str, float]:
    """Compute all stylized-fact divergences between candidate and reference runs."""
    rc, rr = log_returns(cand_prices), log_returns(ref_prices)
    rep = {
        "ks": ks_distance(rc, rr),
        "acf_abs_l2": acf_abs_l2(rc, rr, lags),
        "hill_abs": hill_error(rc, rr, hill_k),
    }
    if cand_intraday_vol is not None and ref_intraday_vol is not None:
        d = np.asarray(cand_intraday_vol) - np.asarray(ref_intraday_vol)
        rep["intraday_l2"] = float(np.sqrt(np.mean(d**2)))
    if cand_depth_hist is not None and ref_depth_hist is not None:
        rep["depth_js"] = jensen_shannon(cand_depth_hist, ref_depth_hist)
    return rep


def admissible(report: dict[str, float], ceilings: dict[str, float]) -> tuple[bool, list[str]]:
    """True iff every reported divergence with a ceiling is under it. Returns (ok, breaches)."""
    breaches = [
        f"{k}={report[k]:.4g}>{ceilings[k]:.4g}"
        for k in ceilings
        if k in report and report[k] > ceilings[k]
    ]
    return (len(breaches) == 0, breaches)
