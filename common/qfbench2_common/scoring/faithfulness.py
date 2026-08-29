"""Track 4: citation-faithfulness gate + analysis composite.

A submission's analysis is *eligible* only if (i) citation faithfulness >= threshold and
(ii) no embargo violation (every cited document predates the question cutoff). Eligible
submissions are ranked by a composite of directional accuracy + interval coverage +
tail calibration. Faithfulness uses an ensemble NLI judge (Laurer et al., 2024,
"Less Annotating, More Classifying", DeBERTa-v3 NLI) — a claim is supported iff some
cited span entails it above tau.

## The embargo gate fails closed (changed 2026-08-22)

`embargo_violations` used to be **unfalsifiable in the direction that matters**. Three separate
defaults added up to "clean by construction":

1. A `doc_id` that did not resolve produced no violation — the `except` swallowed the lookup and
   left `doc_date` at `None`.
2. A resolved document with no `doc_date` produced no violation either, for the same reason.
3. Both then fell back to **the citation's own `doc_date`** — a field `analysis.schema.json` does
   not define, so in practice always absent, so always `None`, so always silent.

Compose them and an unresolvable citation was embargo-clean *by construction*: the cheapest way
past the gate was to cite a document that does not exist. Track 4 refuses such citations in its own
`CorpusIndex` before this helper is reached, which made the tolerant path unreachable **there** and
left it live for every other consumer — and unreachable-today is how a latent defect waits.

Now: the trusted corpus is the only source of dates, a citation that cannot be dated **from it** is
a violation, and dates are parsed to `datetime.date` and compared as dates. The old comment said
"lexical == chronological", which is true of exactly one spelling — `date.fromisoformat` alone
accepts `20240201` and ISO week dates on 3.11+, and two spellings of one day is how a string
comparison stops being either lexical or chronological.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
from collections.abc import Mapping
from typing import Any, Protocol, Sequence

import numpy as np
from numpy.typing import NDArray

from ..contracts.errors import ContractError, OrganizerFault, ParticipantFailure
from ._ranking import spearman_rho

__all__ = [
    "EMBARGO_REASONS",
    "ISO_DATE_RE",
    "EnsembleNLIJudge",
    "NLIJudge",
    "analysis_composite",
    "citation_faithfulness",
    "directional_accuracy",
    "embargo_violations",
    "interval_coverage",
    "iter_claims",
    "parse_embargo_date",
    "predictive_quality",
]

#: The ONE accepted spelling of a date on this path. `date.fromisoformat` is too permissive on
#: 3.11+ (it takes `20240201` and ISO week dates), and the whole point of parsing is that two
#: spellings of one day cannot compare differently. Deliberately identical to Track 4's
#: `qfbench2_track_analysis.corpus.ISO_DATE_RE`: one date grammar, or the gate is two gates.
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Why one citation failed the embargo gate. Closed, and every member is a VIOLATION — there is no
#: "could not tell" member, because "could not tell" was the bug.
#:
#: `undated_doc` deserves a note on fault attribution. A corpus document with no usable `doc_date`
#: is ORGANIZER material that was staged wrong, not participant misbehaviour, and Track 4's trusted
#: `CorpusIndex` refuses one at construction — before any citation is looked at — so a consumer
#: resolving through a trusted index never sees this reason. It exists here because this helper
#: takes an arbitrary `corpus_lookup`, and a lookup that is not a trusted index must not be able to
#: come back clean. A caller that sees it should treat it as an organizer fault and abort, not as a
#: participant zero.
EMBARGO_REASONS = ("malformed_citation", "unresolved_doc", "undated_doc", "post_cutoff")


class NLIJudge(Protocol):
    def entail(self, premise: str, hypothesis: str) -> float:
        """P(premise entails hypothesis) in [0, 1]."""
        ...


class EnsembleNLIJudge:
    """Mean entailment probability over a set of NLI models (robustness to single-model
    idiosyncrasy). The concrete model list is pinned in the private scorer config."""

    def __init__(self, judges: Sequence[NLIJudge]) -> None:
        if not judges:
            raise ValueError("need >=1 judge")
        self._judges = list(judges)

    def entail(self, premise: str, hypothesis: str) -> float:
        return float(np.mean([j.entail(premise, hypothesis) for j in self._judges]))


# --------------------------------------------------------------------------- #
# Answer-format adapters                                                        #
# --------------------------------------------------------------------------- #
# Two answer shapes are supported so the toolkit works for both the single-entity
# (`claims` at top level; citation `span=[s,e]`, claim `text`) and the multi-entity
# (`entity_predictions[].claims`; citation `span_start`/`span_end`, claim `claim`) formats.
def _normalize_claim(raw: dict) -> dict:
    """Return a claim in the uniform shape {text, citations:[{doc_id, span/span_start.., doc_date?}]}.

    Camp A claims already have a `citations` list. Camp B claim elements bundle the claim text
    AND a single citation in one object ({doc_id, span_start, span_end, claim}); wrap those so
    the rest of the module sees one consistent shape.
    """
    if "citations" in raw:
        return raw
    return {"text": _claim_text(raw), "citations": [raw]}


def iter_claims(answer: dict) -> list[dict]:
    """Flatten an answer to a list of normalized claim dicts, regardless of format."""
    if "entity_predictions" in answer:
        raws = [
            c for ent in answer.get("entity_predictions", []) for c in (ent.get("claims", []) or [])
        ]
    else:
        raws = answer.get("claims", []) or []
    return [_normalize_claim(c) for c in raws]


def _claim_text(claim: dict) -> str:
    return claim.get("text") or claim.get("claim") or ""


def _citation_span(cite: dict) -> tuple[int, int] | None:
    if "span" in cite and cite["span"] is not None:
        s, e = cite["span"]
        return int(s), int(e)
    if "span_start" in cite and "span_end" in cite:
        return int(cite["span_start"]), int(cite["span_end"])
    return None


def _doc_text(doc) -> str:
    """Corpus docs may be a raw string or a dict ({'text': ...} or {'spans': [{'text': ...}]})."""
    if isinstance(doc, str):
        return doc
    if isinstance(doc, dict):
        if isinstance(doc.get("text"), str):
            return doc["text"]
        if isinstance(doc.get("spans"), list):
            return " ".join(sp.get("text", "") for sp in doc["spans"] if isinstance(sp, dict))
    return ""


def citation_faithfulness(
    claims: Sequence[dict],  # flat list of claim dicts (use iter_claims())
    corpus_lookup,  # callable doc_id -> doc (str or dict)
    judge: NLIJudge,
    tau: float = 0.5,
) -> float:
    """Fraction of claims whose text is entailed (> tau) by at least one cited span.

    Tolerant of malformed citations (missing span / doc / out-of-range) — these simply do
    not support the claim rather than raising, so a bad submission scores low, not crashes.
    """
    claims = list(claims)
    if not claims:
        return 0.0
    supported = 0
    for claim in claims:
        hypothesis = _claim_text(claim)
        best = 0.0
        for cite in claim.get("citations", []) or []:
            span = _citation_span(cite)
            doc_id = cite.get("doc_id")
            if span is None or doc_id is None:
                continue
            try:
                text = _doc_text(corpus_lookup(doc_id))
            except (KeyError, LookupError, TypeError):
                continue
            s, e = span
            premise = text[s:e]
            if premise:
                best = max(best, judge.entail(premise, hypothesis))
        supported += int(best > tau)
    return supported / len(claims)


def parse_embargo_date(value: Any, *, field: str, fault: str = "participant") -> _dt.date:
    """Parse an ISO-8601 *calendar* date under the single policy this module compares under.

    `fault="organizer"` is for organizer-authored values — the unit cutoff, a corpus document's
    date. A malformed one of those is our mistake and must abort, never charge a participant.
    Deliberately the same policy and the same knob as
    `qfbench2_track_analysis.corpus.parse_iso_date`: one date grammar across the two halves of the
    gate, or the halves can disagree about what day a document is from.
    """
    if not isinstance(value, str) or not ISO_DATE_RE.match(value):
        message = f"{field} must be an ISO-8601 calendar date 'YYYY-MM-DD', got {value!r}"
        raise OrganizerFault(message) if fault == "organizer" else ParticipantFailure(message)
    try:
        return _dt.date.fromisoformat(value)
    except ValueError as exc:  # e.g. 2024-02-31 — well-spelled, not a real day
        message = f"{field} is not a real calendar date: {value!r}"
        if fault == "organizer":
            raise OrganizerFault(message) from exc
        raise ParticipantFailure(message) from exc


def _iter_citations(answer: Any) -> list[Any]:
    """Every citation object in an answer, in document order, whichever answer shape it uses."""
    if not isinstance(answer, Mapping):
        return [answer]
    out: list[Any] = []
    for claim in iter_claims(dict(answer)):
        citations = claim.get("citations") if isinstance(claim, Mapping) else None
        if isinstance(citations, list):
            out.extend(citations)
        elif citations is not None:
            out.append(citations)
    return out


def embargo_violations(
    answer: dict, cutoff: str, corpus_lookup: Any = None
) -> list[dict[str, Any]]:
    """Every citation this answer cannot prove predates `cutoff`. **Fails closed.**

    Returns one record per failing citation, in document order, as
    `{"doc_id": <str|None>, "reason": <one of EMBARGO_REASONS>}` — no free-form text, so a caller
    may count the reasons into a C4 public projection without redacting anything. An empty list
    means every citation resolved to a trusted, dated document at or before the cutoff. It does
    **not** mean "nothing was checked": that case raises.

    Four ways a citation fails, and all four used to be silence:

    * `malformed_citation` — the citation is not an object, or names no usable `doc_id`.
    * `unresolved_doc` — `corpus_lookup(doc_id)` raised or returned nothing. This was the
      load-bearing hole: the cheapest way past the old gate was to cite a document that does not
      exist.
    * `undated_doc` — the resolved document carries no `doc_date`, or one this module's date
      policy refuses. See `EMBARGO_REASONS` on why this is an organizer-fault signal.
    * `post_cutoff` — the trusted date is after the cutoff. The actual embargo breach.

    The citation's own `doc_date` is **never read**. `analysis.schema.json` defines no such field,
    so the old fallback to it was always absent and therefore always clean; and even if a producer
    wrote one, a date the participant supplies about their own evidence is not evidence.

    Raises `OrganizerFault` — never a violation — for the two things that are ours: a `cutoff` that
    is not an ISO calendar date, and a missing `corpus_lookup`. A verdict computed without the
    trusted corpus is not a lenient verdict, it is not a verdict.
    """
    if corpus_lookup is None:
        raise OrganizerFault(
            "embargo_violations requires corpus_lookup: the trusted corpus is the only source of "
            "document dates. Called without one, this gate used to fall back to the citation's "
            "self-reported doc_date — a field analysis.schema.json does not define — and so "
            "returned [] for every answer, which reads exactly like 'no violations'."
        )
    cutoff_date = parse_embargo_date(cutoff, field="cutoff", fault="organizer")

    out: list[dict[str, Any]] = []
    for cite in _iter_citations(answer):
        if not isinstance(cite, Mapping):
            out.append({"doc_id": None, "reason": "malformed_citation"})
            continue
        doc_id = cite.get("doc_id")
        if not isinstance(doc_id, str) or not doc_id:
            out.append({"doc_id": None, "reason": "malformed_citation"})
            continue
        try:
            doc = corpus_lookup(doc_id)
        except (KeyError, LookupError, TypeError, ValueError, OSError):
            doc = None
        if doc is None:
            out.append({"doc_id": doc_id, "reason": "unresolved_doc"})
            continue
        raw_date = doc.get("doc_date") if isinstance(doc, Mapping) else None
        if raw_date is None:
            out.append({"doc_id": doc_id, "reason": "undated_doc"})
            continue
        try:
            doc_date = parse_embargo_date(raw_date, field=f"corpus[{doc_id}].doc_date")
        except ContractError:
            out.append({"doc_id": doc_id, "reason": "undated_doc"})
            continue
        if doc_date > cutoff_date:
            out.append({"doc_id": doc_id, "reason": "post_cutoff"})
    return out


def directional_accuracy(pred_dir: NDArray, true_dir: NDArray) -> float:
    """Fraction of questions with the correct {beat, miss, inline} call."""
    return float(np.mean(np.asarray(pred_dir) == np.asarray(true_dir)))


def interval_coverage(
    lo: NDArray[np.float64], hi: NDArray[np.float64], y: NDArray[np.float64]
) -> float:
    """Empirical coverage of the reported intervals (target = level, e.g. 0.90)."""
    lo, hi, y = map(np.asarray, (lo, hi, y))
    return float(np.mean((y >= lo) & (y <= hi)))


def analysis_composite(
    pred_dir: NDArray,
    true_dir: NDArray,
    lo: NDArray[np.float64],
    hi: NDArray[np.float64],
    y: NDArray[np.float64],
    faithfulness: float,
    faithfulness_threshold: float = 0.80,
    interval_level: float = 0.90,
    weights: tuple[float, float] = (0.7, 0.3),
) -> dict[str, float | bool]:
    """Composite = w_a * directional_accuracy - w_c * |coverage - level|, reported with the
    faithfulness gate. `eligible` is False if faithfulness < threshold (set elsewhere if an
    embargo violation exists). Higher composite is better; ineligible => unranked."""
    w_a, w_c = weights
    acc = directional_accuracy(pred_dir, true_dir)
    cov = interval_coverage(lo, hi, y)
    cov_err = abs(cov - interval_level)
    composite = w_a * acc - w_c * cov_err
    return {
        "directional_accuracy": acc,
        "coverage": cov,
        "coverage_error": cov_err,
        "faithfulness": faithfulness,
        "eligible": bool(faithfulness >= faithfulness_threshold),
        "composite": float(composite),
    }


# --------------------------------------------------------------------------- #
# Per-target-type predictive quality (classification / regression / ranking)    #
# --------------------------------------------------------------------------- #
# Track 4 units come in three target types. `directional_accuracy` (above) covers the
# classification/directional case only; `predictive_quality` generalises it so the public
# verifier and the private final scorer share ONE implementation of the regression (MAE-skill)
# and ranking (Spearman) metrics instead of each carrying a duplicate copy.


def predictive_quality(
    target_type: str,
    pred_labels: Sequence,
    true_labels: Sequence,
    pred_values: Sequence[float],
    true_values: Sequence[float],
) -> float:
    """Predictive quality in [0, 1] for one Track-4 unit, by ``target_type``:

      classification -> label accuracy (fraction of entities whose predicted label matches);
      regression     -> MAE skill = clamp(1 - MAE / baseline_MAE, 0, 1), where baseline_MAE is the
                        MAE of predicting the cross-entity mean of the realized values;
      ranking        -> Spearman rank correlation (average ranks, so ties are ties) rescaled
                        to [0, 1]; n < 2 -> 0.5; a constant or information-free prediction ->
                        0.5; nothing predicted at all -> 0.0.

    Unknown ``target_type`` falls back to label accuracy. The four sequences are aligned by entity;
    the ground-truth (``true_*``) sequence fixes the entity count that is graded. This is the single
    shared definition the track scorers delegate to.

    COVERAGE IS ENFORCED, and here is exactly what that buys. Note the direction: every rule below
    is about the PREDICTION vectors. The ``true_*`` sequences are used exactly as handed over --
    nothing here fills, drops or worst-cases a NaN in the ground truth, and on ``ranking`` such a
    NaN is passed straight into ``spearman_rho``. A NaN-free truth vector is the CALLER's contract
    (``qfbench2_track_analysis.scoring._true_vectors`` raises ``T4OrganizerFault`` on a nonfinite
    target and on a mixed numeric/absent outcome file), not a property of this function.

    **The denominator never shrinks**: a
    missing prediction (``pred`` shorter than the truth) or a ``NaN`` prediction is still graded,
    scored worst-case on its own entity -- classification -> counted wrong; regression -> scored at
    the baseline/mean, i.e. zero skill on that entity; ranking -> ranked below every value the
    submission did provide. Withholding an entity is therefore never *free*, and no answer can be
    made to look better by being made shorter.

    What this does **not** amount to is a monotonicity guarantee, and this docstring used to claim
    one: it said a solver "can never raise its score by predicting only a favourable subset and
    omitting / NaN-ing the rest". For ``classification`` and ``regression`` that holds, because both
    are per-entity averages and a worst-cased entity can only pull the average down. For
    ``ranking`` it is false, and measurably so, because Spearman is a correlation over the whole
    vector rather than a sum of per-entity terms: worst-casing an entity moves every other entity's
    rank too. Measured on this repository 2026-08-29 against truth ``[1, 2, 3, 4, 5]``: the fully
    reversed answer ``[5, 4, 3, 2, 1]`` scores **0.0**, and the same solver NaN-ing everything it
    would have got wrong -- ``[nan, nan, 3, nan, nan]`` -- scores **0.5**. Withholding raised the
    score by 0.5 on that unit.

    That is a property of ranking-by-correlation, not a defect in the coverage rule, and it is left
    in place deliberately: the alternative is a different ranking metric, and the numbers this one
    produces are pinned by the shipped tests and by the sealed scorer that shares this code.
    ``test_ranking_quality.py`` pins the counterexample above so the claim cannot be quietly
    restated. Track 4 unit authors: the exposure is bounded by ``worst_case``/``clip_to_domain`` in
    ``qfbench2_track_analysis.scoring``, and it is only reachable on ``target_type = "ranking"``.
    """
    if target_type == "regression":
        tv_all = [float(t) for t in true_values]
        idx = [i for i in range(len(tv_all)) if not math.isnan(tv_all[i])]
        n = len(idx)
        if n == 0:
            return 0.0
        tv = [tv_all[i] for i in idx]
        mean_true = sum(tv) / n
        baseline_mae = sum(abs(t - mean_true) for t in tv) / n

        def _pred_at(i: int) -> float:
            return float(pred_values[i]) if i < len(pred_values) else float("nan")

        if baseline_mae <= 0:
            # No cross-entity variance to predict: skill is only meaningful as perfect-or-nothing.
            solved = all(
                (not math.isnan(_pred_at(i))) and abs(_pred_at(i) - tv_all[i]) <= 1e-12 for i in idx
            )
            return 1.0 if solved else 0.0
        # A missing / NaN prediction is scored at the baseline (mean) -> zero skill on that entity,
        # so omitting hard entities can neither help nor be dropped for gain.
        err = 0.0
        for i in idx:
            p = _pred_at(i)
            if math.isnan(p):
                p = mean_true
            err += abs(p - tv_all[i])
        mae = err / n
        return max(0.0, min(1.0, 1.0 - mae / baseline_mae))

    if target_type == "ranking":
        tv = [float(t) for t in true_values]
        n = len(tv)
        if n < 2:
            return 0.5
        # A missing / NaN prediction is ranked below every value the submission did provide, so
        # withholding an entity is never free -- but on `ranking` it is not a guarantee that a
        # partial answer scores no higher than a full one, and this comment used to say it was.
        # Spearman is a correlation over the whole vector, so worst-casing one entity moves every
        # other entity's rank: the docstring's pinned counterexample (fully reversed -> 0.0,
        # the same solver NaN-ing its wrong answers -> 0.5) is this branch, not a caveat about it.
        provided = [
            float(pred_values[i])
            for i in range(min(len(pred_values), n))
            if not math.isnan(float(pred_values[i]))
        ]
        if not provided:
            # Nothing was predicted. Scoring this by rank would compare the roster against
            # itself and return a number that depends only on how the organizer happened to
            # order it -- measured at 1.0 on an ascending roster. An empty answer is the
            # worst answer, and must not be able to beat a real one.
            return 0.0
        worst = min(provided) - 1.0
        pv = [
            float(pred_values[i])
            if i < len(pred_values) and not math.isnan(float(pred_values[i]))
            else worst
            for i in range(n)
        ]
        return (spearman_rho(pv, tv) + 1.0) / 2.0

    # classification / unknown -> accuracy over ALL ground-truth entities; a missing prediction
    # (pred shorter than truth) counts as wrong, so partial answers cannot inflate accuracy.
    n = len(true_labels)
    if n == 0:
        return 0.0
    matches = sum(1 for i in range(n) if i < len(pred_labels) and pred_labels[i] == true_labels[i])
    return matches / n
