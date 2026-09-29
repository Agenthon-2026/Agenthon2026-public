"""Regression predictive quality is the soft ratio against the unit's declared naive rule.

From toolkit 2.5.0, for ``target_type == "regression"``::

    naive_mae = mean |naive - truth|,  mae = mean |pred - truth|
    pq        = 1.0 if naive_mae == 0 == mae else naive_mae / (naive_mae + mae)

The naive rule is a REQUIRED scoring parameter: a regression unit scored without it raises, and
never falls back to the retired MAE-skill-vs-cross-entity-mean formula. Classification and ranking
are untouched; their values below were captured from the pre-change implementation and must stay
identical to the last bit.
"""

from __future__ import annotations

import math

import pytest

from qfbench2_common.scoring import faithfulness as F
from qfbench2_common.scoring.faithfulness import predictive_quality

TRUTH = [1.0, 2.0, 3.0, 4.0, 5.0]
NAIVE = [3.0, 3.0, 3.0, 3.0, 3.0]  # naive MAE 1.2


def reg(pred, naive=NAIVE, truth=TRUTH) -> float:
    return predictive_quality("regression", [], [], pred, truth, naive_values=naive)


class TestAnchors:
    def test_matching_the_naive_rule_scores_one_half(self):
        assert reg(list(NAIVE)) == 0.5

    def test_any_answer_with_the_naive_error_scores_one_half(self):
        # a different answer with the same MAE as the naive rule (1.2) is parity too
        assert reg([2.2, 3.2, 4.2, 5.2, 6.2]) == pytest.approx(0.5, abs=1e-15)

    def test_the_truth_scores_one(self):
        assert reg(list(TRUTH)) == 1.0

    def test_naive_and_prediction_both_exact_scores_one(self):
        assert reg(list(TRUTH), naive=list(TRUTH)) == 1.0

    def test_an_exact_naive_rule_leaves_nothing_to_beat(self):
        assert reg([0.0] * 5, naive=list(TRUTH)) == 0.0

    def test_the_value_is_the_formula(self):
        pred = [1.5, 2.0, 2.0, 4.0, 7.0]  # MAE (0.5 + 0 + 1 + 0 + 2) / 5 = 0.7
        assert reg(pred) == pytest.approx(1.2 / (1.2 + 0.7), abs=1e-15)


class TestAnyMissingPredictionScoresTheUnitZero:
    """From toolkit 2.5.0, any missing or NaN prediction on a graded entity scores the whole
    regression unit 0.0 -- not the naive value, and not partial credit for the entities that were
    answered."""

    def test_an_all_nan_prediction_scores_exactly_zero(self):
        assert reg([math.nan] * 5) == 0.0

    def test_an_empty_prediction_scores_exactly_zero(self):
        assert reg([]) == 0.0

    def test_blank_matches_classification_and_ranking(self):
        assert reg([]) == predictive_quality("classification", [], _LABELS, [], [])
        assert reg([math.nan] * 5) == predictive_quality("ranking", [], [], [math.nan] * 5, TRUTH)

    def test_one_nan_entity_scores_the_unit_zero(self):
        # the other four are exact; one NaN still zeroes the unit
        assert reg([1.0, math.nan, 3.0, 4.0, 5.0]) == 0.0

    def test_one_missing_entity_scores_the_unit_zero(self):
        # a short prediction: the fifth entity is missing
        assert reg([1.0, 2.0, 3.0, 4.0]) == 0.0

    def test_a_missing_entity_is_not_scored_at_the_naive_value(self):
        # the retired parity rule would have filled NAIVE[1] = 3.0 here
        assert reg([1.0, NAIVE[1], 3.0, 4.0, 5.0]) > 0.0
        assert reg([1.0, math.nan, 3.0, 4.0, 5.0]) == 0.0

    def test_a_complete_answer_is_unchanged(self):
        pred = [1.5, 2.0, 2.0, 4.0, 7.0]
        assert reg(pred) == pytest.approx(1.2 / (1.2 + 0.7), abs=1e-15)

    def test_withholding_cannot_beat_the_truth(self):
        assert reg([1.0, 2.0, math.nan, math.nan, math.nan]) == 0.0 < reg(list(TRUTH))

    def test_withholding_a_very_bad_value_scores_below_answering_it(self):
        # the loophole under answered-share scaling: dropping one huge error scored 0.8 there.
        # The soft ratio pools MAE, so only zeroing the unit keeps withholding below answering.
        answered = reg([1.0, 2.0, 3.0, 4.0, 1000.0])
        withheld_nan = reg([1.0, 2.0, 3.0, 4.0, math.nan])
        withheld_short = reg([1.0, 2.0, 3.0, 4.0])
        assert answered == pytest.approx(6.0 / (6.0 + 995.0), abs=1e-15)
        assert withheld_nan == withheld_short == 0.0
        assert withheld_nan < answered


class TestMonotone:
    def test_strictly_decreasing_in_mae(self):
        # the same entity moved further from truth each step: MAE strictly increases
        scores = [reg([1.0, 2.0, 3.0 + d, 4.0, 5.0]) for d in (0.0, 0.1, 0.5, 1.0, 5.0, 50.0)]
        assert all(a > b for a, b in zip(scores, scores[1:])), scores
        assert all(0.0 < s <= 1.0 for s in scores)


class TestTheNaiveRuleIsRequired:
    def test_regression_without_naive_values_raises(self):
        with pytest.raises(ValueError, match="naive"):
            predictive_quality("regression", [], [], list(TRUTH), list(TRUTH))

    def test_a_naive_vector_that_does_not_cover_the_truth_raises(self):
        with pytest.raises(ValueError, match="naive"):
            reg(list(TRUTH), naive=[3.0, 3.0])

    def test_a_nonfinite_naive_value_raises(self):
        with pytest.raises(ValueError, match="naive"):
            reg(list(TRUTH), naive=[3.0, 3.0, math.nan, 3.0, 3.0])

    def test_the_naive_vector_is_ignored_off_regression(self):
        assert predictive_quality("ranking", [], [], list(TRUTH), list(TRUTH)) == 1.0
        assert predictive_quality("classification", ["a"], ["a"], [], []) == 1.0


class TestTheRetiredFormulaIsANamedHelperOnly:
    def test_the_retired_helper_keeps_its_old_values(self):
        # clamp(1 - MAE / MAE_of_mean): MAE_of_mean over TRUTH = 1.2
        assert F.regression_mae_skill_v1([1.5, 2.0, 2.0, 4.0, 7.0], TRUTH) == pytest.approx(
            1 - 0.7 / 1.2, abs=1e-15
        )
        assert F.regression_mae_skill_v1([3.0] * 5, TRUTH) == 0.0
        assert F.regression_mae_skill_v1(list(TRUTH), [2.0, 2.0]) == 0.0
        assert F.regression_mae_skill_v1([2.0, 2.0], [2.0, 2.0]) == 1.0

    def test_the_scoring_path_does_not_use_it(self):
        # the old formula gives 0.0 at the cross-entity mean; the soft ratio gives parity
        pred = [3.0] * 5
        assert F.regression_mae_skill_v1(pred, TRUTH) == 0.0
        assert reg(pred) == 0.5


# Captured from the implementation before the soft-ratio change.
_NAN = math.nan
_RANKING_GOLDEN = [
    ([1.0, 2.0, 3.0, 4.0, 5.0], 1.0),
    ([5.0, 4.0, 3.0, 2.0, 1.0], 0.0),
    ([7.0] * 5, 0.5),
    ([_NAN] * 5, 0.0),
    ([1.0, 1.0, 3.0, 4.0, 5.0], 0.9873397172404482),
    ([2.0, 1.0, 4.0, 3.0, 5.0], 0.9),
    ([_NAN, _NAN, 3.0, _NAN, _NAN], 0.5),
    ([1.0, 2.0], 0.1086881039375368),
    ([0.3, -1.2, 9.9, 4.4, 4.4], 0.7821440468234173),
    ([1e9, -1e9, 0.0, 0.5, 0.25], 0.45),
]
_LABELS = ["beat", "miss", "miss", "inline", "beat"]
_CLASSIFICATION_GOLDEN = [
    (list(_LABELS), 1.0),
    (["beat"] * 5, 0.4),
    (["miss", "miss"], 0.2),
    ([], 0.0),
    (["beat", "miss", "inline", "inline", "beat", "extra"], 0.8),
]


@pytest.mark.parametrize(("pred", "expected"), _RANKING_GOLDEN)
def test_ranking_is_bit_identical_to_before(pred, expected):
    got = predictive_quality("ranking", [], [], pred, TRUTH)
    assert repr(got) == repr(expected)


@pytest.mark.parametrize(("pred", "expected"), _CLASSIFICATION_GOLDEN)
def test_classification_is_bit_identical_to_before(pred, expected):
    got = predictive_quality("classification", pred, _LABELS, [], [])
    assert repr(got) == repr(expected)
