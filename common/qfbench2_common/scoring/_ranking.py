"""Rank statistics, with the tie treatment the ranking metric actually requires.

Split out because three call sites need the same two functions and had drifted into two
different tie conventions. The convention here is the standard one: tied values share the
mean of the positions they occupy, and the correlation is Pearson's on those ranks.

The alternative -- breaking ties by position -- is not a weaker approximation, it is a
different statistic, and on a ranking task it is an exploitable one: every tie silently
resolves to the roster's own order, so a submission that expresses no opinion inherits the
organizer's ordering as if it were a prediction.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = ["average_ranks", "spearman_rho"]


def _tied(a: float, b: float) -> bool:
    """Tie test that treats two NaNs as tied. ``nan == nan`` is False, which is the whole bug."""
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return bool(a == b)


def average_ranks(values: Sequence[float]) -> list[float]:
    """1..n ranks by ascending value; TIED VALUES SHARE THE MEAN OF THEIR POSITIONS.

    ``[7, 7, 7]`` ranks ``[2.0, 2.0, 2.0]``, not ``[1.0, 2.0, 3.0]``. The second form
    encodes an ordering the submitter never expressed.

    **NaN is one tied group, sorted last.** Two NaNs are not distinguishable from one another --
    a missing value carries no ordering information, and neither missing value carries more of it
    than the other -- so they are ties under exactly the convention this module exists to enforce,
    and a missing value ranks below every value that is present.

    That is not what the code did. `nan == nan` is False, so every NaN formed its own singleton
    group and each was handed the rank of whatever position `sorted` happened to leave it in.
    Measured on this repository 2026-08-29: ``average_ranks([nan] * 5)`` returned
    ``[1.0, 2.0, 3.0, 4.0, 5.0]`` -- a complete, confident ordering, read straight off the input
    order. That is the position-tie-breaking exploit named in this module's header, reintroduced
    through the one input for which the roster is *all* there is.
    """
    vals = [float(v) for v in values]
    n = len(vals)
    # NaN sorts after every real value, and all NaNs sort equal to each other.
    order = sorted(
        range(n), key=lambda i: (math.isnan(vals[i]), 0.0 if math.isnan(vals[i]) else vals[i])
    )
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and _tied(vals[order[j + 1]], vals[order[i]]):
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def spearman_rho(pred: Sequence[float], true: Sequence[float]) -> float:
    """Spearman's rho, computed as Pearson's correlation on average ranks.

    Returns **0.0** -- no information, which the caller rescales to the neutral 0.5 -- when
    either side has no rank variance. A constant prediction genuinely carries no ordering
    information, so it must score neither well nor badly; the squared-rank-difference
    shortcut cannot express that, because it is only valid when neither side has ties.

    An **all-NaN side now reaches that branch**, which is what the docstring has always claimed and
    what the code did not do. Because every NaN used to be its own singleton group, an all-NaN side
    arrived here with full rank variance and the function returned the correlation between the
    roster's own order and the truth. Measured on this repository 2026-08-29, before the fix:
    ``spearman_rho([nan] * 5, [1, 2, 3, 4, 5])`` was ``+1.0``, ``spearman_rho([nan] * 5,
    [5, 4, 3, 2, 1])`` was ``-1.0``, and across the 120 orderings of one five-entity roster the
    value took 21 distinct values spanning the entire range. Nothing predicted, and the score was
    whatever the organizer's ordering happened to be.

    No in-tree score moved, and the two arguments earn that differently -- an earlier version of
    this paragraph said the only consumer "substitutes a worst-case value for every NaN before
    calling here", full stop, which is true of `pred` and not of `true`.

    **`pred` arrives NaN-free.** `faithfulness.predictive_quality` returns 0.0 without calling here
    when nothing at all was predicted, and otherwise fills every NaN -- and every entity past the
    end of a short prediction vector -- with `min(provided) - 1.0`. Measured 2026-08-29 by
    instrumenting this function: `pred=[nan, 2, nan, 4, 5]` arrives as `[1.0, 2.0, 1.0, 4.0, 5.0]`,
    and `pred=[1, 2]` against a five-entity roster arrives as `[1.0, 2.0, 0.0, 0.0, 0.0]`.

    **`true` is passed through unchanged, NaNs included.** Nothing in `predictive_quality` fills
    the ground-truth vector. Measured the same way: `true=[1, nan, 3, 4, 5]` arrives with its NaN
    intact and an all-NaN `true` arrives with five. What keeps that off the leaderboard is a
    contract two modules away -- `qfbench2_track_analysis.scoring._true_vectors` raises
    `T4OrganizerFault` on a nonfinite target and on a mixed numeric/absent outcome file, and hands
    a pure-label unit an empty vector -- so this function may not lean on it. The cost of leaning
    on it is measurable: on a reconstruction of the pre-fix code (one that reproduces both values
    pinned above), an all-NaN `true` against an ascending `pred` returned +1.0, i.e. a perfect
    predictive_quality of 1.0 for a roster that carried no answer at all. It now returns 0.0, the
    neutral 0.5.
    """
    n = len(true)
    if n < 2 or len(pred) != n:
        return 0.0
    pr, tr = average_ranks(pred), average_ranks(true)
    mp, mt = sum(pr) / n, sum(tr) / n
    cov = sum((a - mp) * (b - mt) for a, b in zip(pr, tr))
    var_p = sum((a - mp) ** 2 for a in pr)
    var_t = sum((b - mt) ** 2 for b in tr)
    if var_p <= 0.0 or var_t <= 0.0:
        return 0.0
    return cov / math.sqrt(var_p * var_t)
