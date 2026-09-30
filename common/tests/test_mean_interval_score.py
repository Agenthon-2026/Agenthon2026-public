"""The Track 4 interval score, moved into the toolkit from ``qfbench2_track_analysis.scoring``.

Per roster row, with ``alpha = 1 - interval_level``::

    IS = (hi - lo) + (2/alpha) * (lo - y)+ + (2/alpha) * (y - hi)+

averaged over the roster exactly as MAE is. The fixtures (truth, the flat naive band, the wide,
sharp-hit and sharp-miss bands) are the ones in the Track 4 package's interval-leg tests, so the
numbers here are the numbers that suite measures through the scorer.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import pytest

from qfbench2_common.contracts.errors import OrganizerFault
from qfbench2_common.scoring.faithfulness import mean_interval_score

TRUTH = (1.0, 2.0, 3.0)
NAIVE_BAND = (1.5, 2.5)  # flat naive interval: covers y=2 only
NAIVE_BANDS = (NAIVE_BAND,) * 3
WIDE = ((-10.0, 14.0),) * 3  # covers every row, width 24
SHARP_HIT = tuple((y - 0.01, y + 0.01) for y in TRUTH)
SHARP_MISS = tuple((y + 2.0, y + 2.02) for y in TRUTH)  # misses every row by 2


def _is_row(lo: float, hi: float, y: float, alpha: float) -> float:
    """The interval score formula, written out independently of the toolkit."""
    return (hi - lo) + (2.0 / alpha) * max(lo - y, 0.0) + (2.0 / alpha) * max(y - hi, 0.0)


def _mean_is(bands: Sequence[tuple[float, float]], ys: Sequence[float], alpha: float) -> float:
    return sum(_is_row(lo, hi, y, alpha) for (lo, hi), y in zip(bands, ys)) / len(ys)


def _mis(bands: Sequence[tuple[float, float]], level: float = 0.90) -> float:
    return mean_interval_score([b[0] for b in bands], [b[1] for b in bands], list(TRUTH), level)


def _iq(bands: Sequence[tuple[float, float]]) -> float:
    naive = _mis(NAIVE_BANDS)
    return naive / (naive + _mis(bands))


@pytest.mark.parametrize("bands", [NAIVE_BANDS, WIDE, SHARP_HIT, SHARP_MISS])
@pytest.mark.parametrize("level", [0.50, 0.80, 0.90, 0.95])
def test_matches_the_independent_formula(bands, level):
    assert _mis(bands, level) == pytest.approx(_mean_is(bands, TRUTH, 1.0 - level), abs=1e-12)


def test_the_track_fixture_values():
    # alpha = 0.1, so a miss costs 20x its distance
    assert _mis(NAIVE_BANDS) == pytest.approx(23.0 / 3.0, abs=1e-12)  # 11 + 1 + 11
    assert _mis(WIDE) == pytest.approx(24.0, abs=1e-12)
    assert _mis(SHARP_HIT) == pytest.approx(0.02, abs=1e-12)
    assert _mis(SHARP_MISS) == pytest.approx(40.02, abs=1e-12)


def test_interval_quality_ordering_matches_the_track_suite():
    # the inversion the 5.0.0 rule had: covering everything now scores well below the naive band
    assert _iq(WIDE) < 0.3 < _iq(NAIVE_BANDS) == 0.5
    assert _iq(SHARP_HIT) > 0.99
    assert _iq(SHARP_MISS) < _iq(WIDE)


@pytest.mark.parametrize(
    ("lo", "hi", "y"),
    [([], [], []), ([1.0], [2.0, 3.0], [1.5, 2.5]), ([1.0, 2.0], [2.0, 3.0], [1.5])],
)
def test_an_empty_or_misaligned_roster_is_an_organizer_fault(lo, hi, y):
    with pytest.raises(OrganizerFault, match="one lo, hi and y per roster row"):
        mean_interval_score(lo, hi, y, 0.90)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("where", ["lo", "hi", "y"])
def test_a_nonfinite_value_is_an_organizer_fault(where, bad):
    # Callers validate the participant's bounds and the truth first, so a nonfinite value here
    # is a caller defect. It used to return NaN or inf and score silently.
    vals = {"lo": [0.0, 1.0], "hi": [2.0, 3.0], "y": [1.0, 2.0]}
    vals[where][1] = bad
    with pytest.raises(OrganizerFault, match="finite"):
        mean_interval_score(vals["lo"], vals["hi"], vals["y"], 0.90)


@pytest.mark.parametrize("level", [1.0, 0.0, 1.5, math.nan])
def test_an_interval_level_outside_zero_one_is_an_organizer_fault(level):
    # interval_level = 1.0 used to raise a bare ZeroDivisionError
    with pytest.raises(OrganizerFault, match="interval_level"):
        mean_interval_score([0.0], [2.0], [1.0], level)


def test_it_is_exported():
    from qfbench2_common.scoring import faithfulness as F

    assert "mean_interval_score" in F.__all__
