"""The ranking metric, and the exploit it used to carry.

Before 2.3.1 ties were broken by POSITION, so every tie silently resolved to the roster's own
order. Measured on this repository at the time: a constant prediction scored **1.0000**, and a
submission predicting nothing at all also scored **1.0000**, whenever the roster happened to be
in ascending truth order. Neither expresses any opinion about the ordering.

These tests pin the corrected contract: ties are ties, a prediction carrying no ordering
information scores neutral, and answering nothing scores worst.
"""

from __future__ import annotations

import itertools
import math

import pytest

from qfbench2_common.scoring._ranking import average_ranks, spearman_rho
from qfbench2_common.scoring.faithfulness import predictive_quality

TRUTH = [1.0, 2.0, 3.0, 4.0, 5.0]


def rank_quality(pred: list[float], truth: list[float] = TRUTH) -> float:
    return predictive_quality("ranking", [], [], pred, truth)


class TestCorrectAndReversedAreUnchanged:
    def test_a_perfect_ranking_scores_one(self):
        assert rank_quality([1.0, 2.0, 3.0, 4.0, 5.0]) == pytest.approx(1.0)

    def test_an_exactly_reversed_ranking_scores_zero(self):
        assert rank_quality([5.0, 4.0, 3.0, 2.0, 1.0]) == pytest.approx(0.0)

    @pytest.mark.parametrize("n", [2, 3, 5, 10, 50])
    def test_perfect_and_inverted_hold_at_every_size(self, n):
        truth = [float(i) for i in range(1, n + 1)]
        assert rank_quality(truth, truth) == pytest.approx(1.0)
        assert rank_quality(truth[::-1], truth) == pytest.approx(0.0)


class TestConstantPredictionsAreNeutral:
    """A constant expresses no ordering. It must score neither well nor badly."""

    @pytest.mark.parametrize("value", [0.0, 7.0, -3.5, 1e9])
    def test_a_constant_prediction_scores_neutral(self, value):
        assert rank_quality([value] * 5) == pytest.approx(0.5)

    def test_a_constant_prediction_is_invariant_to_roster_order(self):
        """The exploit, stated as a property. Before the fix this ranged 0.0 to 1.0 across the
        120 orderings and took 21 distinct values -- the roster was the prediction."""
        seen = {
            round(rank_quality([7.0] * 5, list(order)), 12)
            for order in itertools.permutations(TRUTH)
        }
        assert seen == {0.5}

    def test_a_constant_cannot_beat_an_honest_wrong_answer_by_luck(self):
        """Whatever the roster order, a constant never scores above neutral -- so it can never
        outrank a submission that actually tried and got it partly right."""
        for order in itertools.permutations(TRUTH):
            assert rank_quality([7.0] * 5, list(order)) <= 0.5


class TestMissingPredictions:
    def test_predicting_nothing_scores_worst_not_best(self):
        assert rank_quality([math.nan] * 5) == pytest.approx(0.0)

    def test_predicting_nothing_is_invariant_to_roster_order(self):
        seen = {
            round(rank_quality([math.nan] * 5, list(order)), 12)
            for order in itertools.permutations(TRUTH)
        }
        assert seen == {0.0}

    def test_answering_a_favourable_subset_cannot_beat_answering_all(self):
        full = rank_quality([1.0, 2.0, 3.0, 4.0, 5.0])
        subset = rank_quality([1.0, 2.0, math.nan, math.nan, math.nan])
        assert subset < full


class TestTies:
    def test_tied_values_share_the_mean_of_their_positions(self):
        assert average_ranks([7.0, 7.0, 7.0]) == [2.0, 2.0, 2.0]
        assert average_ranks([1.0, 1.0, 3.0]) == [1.5, 1.5, 3.0]

    def test_a_single_tied_pair_barely_moves_a_perfect_ranking(self):
        assert rank_quality([1.0, 1.0, 3.0, 4.0, 5.0]) == pytest.approx(0.9873, abs=1e-4)

    def test_ties_agree_with_scipy(self):
        """The only INDEPENDENT check that this module's tie convention is the standard one.

        It used to be `pytest.importorskip("scipy.stats")`. `scipy>=1.11` is a REQUIRED install
        dependency of `qfbench2-common` (`pyproject.toml` `[project] dependencies`), so its absence
        is a broken environment and never a reason to pass. `importorskip` turned the check into a
        green no-op in exactly that environment: measured 2026-08-29 in a venv installed with
        `--no-deps`, the suite reported `84 passed, 1 skipped` and exited 0, with the tie
        convention unverified. Project rule 7: a required check that cannot run is a FAILURE.
        """
        try:
            from scipy import stats as scipy_stats
        except ImportError as exc:  # pragma: no cover - only in a broken install
            raise AssertionError(
                "scipy is a required dependency of qfbench2-common and is not importable, so the "
                "independent cross-check of the rank-tie convention cannot run. A check that "
                "cannot run is a failure, not a skip: install the package's dependencies."
            ) from exc
        cases = [
            ([1.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0]),
            ([2.0, 2.0, 2.0, 1.0], [4.0, 3.0, 2.0, 1.0]),
            ([1.0, 2.0, 2.0, 2.0], [1.0, 1.0, 2.0, 3.0]),
        ]
        for pred, true in cases:
            assert spearman_rho(pred, true) == pytest.approx(
                scipy_stats.spearmanr(pred, true).statistic, abs=1e-12
            )


class TestAnAllNaNSideCarriesNoOrdering:
    """`spearman_rho` / `average_ranks` promised 0.0 on an information-free side and gave +-1.0.

    `nan == nan` is False, so every NaN formed its own singleton tie group and was handed the rank
    of whatever position `sorted` left it in. An all-NaN side therefore arrived at the correlation
    with FULL rank variance, and the function returned the correlation between the roster's own
    order and the truth. Measured before the fix, 2026-08-29:

        average_ranks([nan] * 5)                -> [1.0, 2.0, 3.0, 4.0, 5.0]
        spearman_rho([nan] * 5, [1,2,3,4,5])    -> +1.0
        spearman_rho([nan] * 5, [5,4,3,2,1])    -> -1.0
        across the 120 orderings of one roster  -> 21 distinct values spanning [-1.0, +1.0]

    This is the same position-tie-breaking exploit the module header condemns, reached through the
    one input for which the roster is all there is.
    """

    def test_all_nan_ranks_share_one_group(self):
        assert average_ranks([math.nan] * 5) == [3.0] * 5
        assert average_ranks([math.nan] * 3) == [2.0] * 3

    @pytest.mark.parametrize("truth", [TRUTH, TRUTH[::-1], [3.0, 1.0, 5.0, 2.0, 4.0]])
    def test_an_all_nan_prediction_scores_zero_not_plus_or_minus_one(self, truth):
        assert spearman_rho([math.nan] * 5, truth) == 0.0

    def test_an_all_nan_truth_column_scores_zero(self):
        assert spearman_rho(TRUTH, [math.nan] * 5) == 0.0

    def test_an_all_nan_side_is_invariant_to_roster_order(self):
        seen = {
            round(spearman_rho([math.nan] * 5, list(order)), 12)
            for order in itertools.permutations(TRUTH)
        }
        assert seen == {0.0}, "the roster must not be readable out of an empty prediction"

    def test_a_missing_value_ranks_below_every_value_present(self):
        """NaN is one tied group sorted LAST, matching `predictive_quality`'s 'ranked last'."""
        assert average_ranks([1.0, math.nan, 3.0]) == [1.0, 3.0, 2.0]
        assert average_ranks([math.nan, 5.0, math.nan]) == [2.5, 1.0, 2.5]

    def test_finite_input_is_untouched(self):
        """The fix must be invisible to every input that has no NaN in it."""
        assert average_ranks([7.0, 7.0, 7.0]) == [2.0, 2.0, 2.0]
        assert average_ranks([1.0, 1.0, 3.0]) == [1.5, 1.5, 3.0]
        assert average_ranks([3.0, 1.0, 2.0]) == [3.0, 1.0, 2.0]
        assert spearman_rho(TRUTH, TRUTH) == pytest.approx(1.0)
        assert spearman_rho(TRUTH[::-1], TRUTH) == pytest.approx(-1.0)


class TestWithholdingCanMoveARankingScoreEitherWay:
    """`predictive_quality`'s docstring claimed a monotonicity it does not have.

    It said a solver "can never raise its score by predicting only a favourable subset and
    omitting / NaN-ing the rest". True for classification and regression, which are per-entity
    averages. FALSE for ranking, because Spearman is a correlation over the whole vector: worst-
    casing one entity moves every other entity's rank as well.

    The counterexample is pinned here so the claim cannot be quietly restated. The behaviour is
    deliberate -- changing it means changing the ranking metric, and these numbers are shared with
    the sealed scorer -- so what this test protects is the DOCUMENTATION being honest about it.
    """

    def test_nan_ing_the_wrong_answers_raises_a_ranking_score(self):
        fully_wrong = rank_quality([5.0, 4.0, 3.0, 2.0, 1.0])
        withheld = rank_quality([math.nan, math.nan, 3.0, math.nan, math.nan])
        assert fully_wrong == pytest.approx(0.0)
        assert withheld == pytest.approx(0.5)
        assert withheld > fully_wrong

    def test_the_docstring_states_what_coverage_enforcement_actually_buys(self):
        """The prose is the deliverable here, so it is asserted rather than trusted.

        The old sentence is allowed to appear -- the docstring quotes it in order to retract it --
        but it must appear inside the retraction, and the retraction must name `ranking` as the
        target type where the property fails.
        """
        doc = predictive_quality.__doc__ or ""
        assert "denominator never shrinks" in doc, "the guarantee that DOES hold must be stated"
        claim = "can never raise its score"
        if claim in doc:
            retraction = doc.split(claim, 1)[0]
            assert "does **not** amount to" in retraction or "used to claim" in retraction, (
                "the monotonicity claim appears without a retraction in front of it"
            )
        assert "``ranking`` it is false" in doc, "the retraction must name the failing target type"

    def test_classification_really_is_monotone_under_withholding(self):
        truth = ["beat"] * 5
        full = predictive_quality("classification", ["beat"] * 5, truth, [], [])
        subset = predictive_quality("classification", ["beat", "beat"], truth, [], [])
        assert subset < full

    def test_regression_really_is_monotone_under_withholding(self):
        truth = [1.0, 2.0, 3.0, 4.0, 5.0]
        full = predictive_quality("regression", [], [], truth, truth)
        subset = predictive_quality(
            "regression", [], [], [1.0, 2.0, math.nan, math.nan, math.nan], truth
        )
        assert subset < full


class TestMalformedInput:
    def test_a_single_entity_is_not_scoreable_and_returns_neutral(self):
        assert predictive_quality("ranking", [], [], [1.0], [1.0]) == pytest.approx(0.5)

    def test_an_empty_roster_returns_neutral_rather_than_raising(self):
        assert predictive_quality("ranking", [], [], [], []) == pytest.approx(0.5)

    def test_a_length_mismatch_does_not_raise(self):
        assert 0.0 <= rank_quality([1.0, 2.0]) <= 1.0

    def test_a_constant_truth_column_is_neutral_not_perfect(self):
        """Undefined on the organizer's side too -- an unrankable unit must not award credit."""
        assert rank_quality([1.0, 2.0, 3.0, 4.0, 5.0], [3.0] * 5) == pytest.approx(0.5)

    def test_every_output_stays_in_range(self):
        for pred in (
            [1.0, 2, 3, 4, 5],
            [5.0, 4, 3, 2, 1],
            [7.0] * 5,
            [math.nan] * 5,
            [1.0, 1, 1, 2, 3],
            [-1e9, 1e9, 0, 0, 0],
        ):
            assert 0.0 <= rank_quality([float(x) for x in pred]) <= 1.0
