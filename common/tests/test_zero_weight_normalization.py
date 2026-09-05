"""Synthetic composite controls: a zero weight excuses only an exactly zero scale.

The division must not happen for that pair. Missing required keys, zero denominators
under nonzero weights, and non-finite results from tiny denominators must remain visible.
Every example below is generated locally; no evaluation artifacts are needed.
"""

from __future__ import annotations

import numpy as np
import pytest

from qfbench2_common.scoring import crps

COMPONENTS = ("marginal", "joint", "tail")


def _example():
    return np.random.default_rng(3).normal(size=(200, 4)), np.array([0.3, -0.2, 0.1, 0.4])


@pytest.mark.parametrize("component", COMPONENTS)
def test_zero_weight_and_zero_scale_equal_a_positive_unused_scale(component):
    samples, y = _example()
    weights = tuple(0.0 if key == component else 0.5 for key in COMPONENTS)
    scale = dict.fromkeys(COMPONENTS, 1.0)
    expected = crps.crps_composite(samples, y, weights=weights, ref_scale=scale)
    scale[component] = 0.0
    actual = crps.crps_composite(samples, y, weights=weights, ref_scale=scale)
    assert np.isfinite(actual["composite"])
    assert actual == expected


def test_single_cell_variogram_has_no_weighted_contribution():
    samples = np.random.default_rng(0).normal(size=(200, 1))
    y = np.array([0.3])
    result = crps.crps_composite(
        samples,
        y,
        weights=(5 / 7, 0.0, 2 / 7),
        ref_scale={"marginal": 0.3, "joint": 0.0, "tail": 0.12},
    )
    assert result["joint"] == 0.0
    expected = (5 / 7) * result["marginal"] / 0.3 + (2 / 7) * result["tail"] / 0.12
    assert result["composite"] == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("component", ("marginal", "joint"))
def test_missing_required_scale_still_raises_under_zero_weight(component):
    samples, y = _example()
    weights = tuple(0.0 if key == component else 0.5 for key in COMPONENTS)
    scale = {key: 1.0 for key in COMPONENTS if key != component}
    with pytest.raises(KeyError, match=component):
        crps.crps_composite(samples, y, weights=weights, ref_scale=scale)


@pytest.mark.parametrize("component", COMPONENTS)
def test_tiny_scale_still_exposes_non_finite_result_under_zero_weight(component):
    samples, y = _example()
    weights = tuple(0.0 if key == component else 0.5 for key in COMPONENTS)
    scale = dict.fromkeys(COMPONENTS, 1.0)
    scale[component] = 5e-324
    result = crps.crps_composite(samples, y, weights=weights, ref_scale=scale)
    assert not np.isfinite(result["composite"])


@pytest.mark.parametrize("component", COMPONENTS)
def test_zero_scale_still_raises_under_nonzero_weight(component):
    samples, y = _example()
    scale = dict.fromkeys(COMPONENTS, 1.0)
    scale[component] = 0.0
    with pytest.raises(ZeroDivisionError):
        crps.crps_composite(samples, y, ref_scale=scale)


@pytest.mark.parametrize("joint", ("variogram", "energy"))
@pytest.mark.parametrize(
    "scale",
    (None, {}, {"marginal": 0.3, "joint": 2.0}, {"marginal": 0.3, "joint": 2.0, "tail": 0.12}),
)
def test_other_composites_keep_the_weighted_normalization(joint, scale):
    samples, y = _example()
    result = crps.crps_composite(samples, y, joint=joint, ref_scale=scale)
    weights = (0.5, 0.3, 0.2)
    expected = sum(
        weight * (result[key] / (scale or {}).get(key, 1.0))
        for weight, key in zip(weights, COMPONENTS, strict=True)
    )
    assert result["composite"] == pytest.approx(expected, rel=1e-12)
