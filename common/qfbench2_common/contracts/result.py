"""C4 — the scorer result, the closed public detail, and the fixed-denominator aggregate.

## Executive summary (read this first)

C4 is what a scorer says about one unit, and what the driver says about a submission. Two frozen
rulings shape it:

1. **C1 is authoritative for failure *treatment*; C4 merely reports the *code*.** A track scorer
   cannot override the signed plan. `Aggregate.from_results` asks the plan for the value.
2. **The public projection of `detail` is a closed schema: enum code plus integer counts only.**
   No free-form strings. This concretely removes `note` and `resolves_after` from the old
   `_WHY_KEYS` allowlist — `note` is arbitrary participant-influenced text and `resolves_after` is
   the channel by which a sealed Track 2 target date reaches a public artifact. `public_detail_keys`
   is the shared function so all consumers use one allowlist rather than four copies.

The aggregate is **"mean over the C1 roster"**, in those words. It carries `n_expected`,
`n_scored`, `n_participant_failure`, `n_organizer_failure` and **refuses to emit when they do not
sum to `n_expected`**. That refusal is A01: the pre-fix driver averaged only the admissible units,
so answering 2 of 4 scored `1.0000` while answering all 4 honestly scored `0.5000`.

Other frozen rules encoded here:

* `organizer_failure` is expressible at **whole-evaluation scope**, not only per unit: an organizer
  fault aborts rather than producing a partial leaderboard.
* Non-finite values in participant **data** are a participant failure; non-finite intermediate
  **statistics** are an organizer failure.
* Participant-visible rows use **opaque unit handles**, never sealed unit ids.
* A result carries `run_record_digest` and `sanitized_tree_digest`, not only the inputs, so an
  aggregate can prove which evidence produced which row.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .codes import FailureCode, parse_failure_code
from .digest import parse_digest
from .errors import (
    ContractError,
    OrganizerFault,
    ParticipantFailure,
    req,
    req_int,
    req_str,
    reject_unknown_keys,
)
from .plan import EvaluationPlan

__all__ = [
    "Aggregate",
    "JudgeRecord",
    "ResultState",
    "UnitResult",
    "public_detail_keys",
    "validate_public_detail",
]

SCHEMA_VERSION = "1.0.0"


class ResultState(StrEnum):
    PARTICIPANT_SUCCESS = "participant_success"
    PARTICIPANT_FAILURE = "participant_failure"
    ORGANIZER_FAILURE = "organizer_failure"
    UNRANKABLE = "unrankable"


#: The ONLY keys a participant-visible `detail` object may carry, and every value is an integer
#: except `code`, which is a public failure code. Frozen C4: "enum code plus integer counts only".
_PUBLIC_DETAIL_KEYS: tuple[str, ...] = (
    "code",
    "missing_count",
    "extra_count",
    "invalid_row_count",
    "nonfinite_count",
    "expected_count",
    "observed_count",
    "rejected_node_count",
    "violation_count",
)

#: Removed from the pre-freeze `_WHY_KEYS` allowlist, and named here so a reviewer sees the
#: deletion rather than inferring it from an absence.
REMOVED_DETAIL_KEYS: tuple[str, ...] = ("note", "resolves_after", "exclusion", "traceback")


def public_detail_keys() -> tuple[str, ...]:
    """The shared public-detail allowlist. One function, so consumers cannot each keep a copy."""
    return _PUBLIC_DETAIL_KEYS


def validate_public_detail(detail: Any, *, path: str = "detail") -> dict[str, Any]:
    """Validate a participant-visible `detail` object: closed keys, enum code, integer counts.

    A string value anywhere except `code` is refused. That is the structural form of "no free-form
    strings": `note` cannot be smuggled back in under another name, because *no* key accepts text.
    """
    if not isinstance(detail, Mapping):
        raise ContractError(f"{path} must be an object, got {type(detail).__name__}")
    banned = sorted(set(detail) & set(REMOVED_DETAIL_KEYS))
    if banned:
        raise ContractError(
            f"{path} carries {banned}, which the freeze removed from the public projection. "
            "'note' is participant-influenced free text and 'resolves_after' is how a sealed "
            "target date reaches a public artifact."
        )
    reject_unknown_keys(detail, _PUBLIC_DETAIL_KEYS, path=path)
    out: dict[str, Any] = {}
    for key in detail:
        value = detail[key]
        if key == "code":
            out[key] = parse_failure_code(value, field=f"{path}.code").value
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ContractError(
                f"{path}.{key} must be a non-negative integer; the public detail projection "
                f"carries counts only, got {type(value).__name__} {value!r}"
            )
        out[key] = value
    return out


@dataclass(frozen=True, slots=True)
class JudgeRecord:
    """Track 4's judge sub-record. Missing or mismatched is an organizer failure."""

    judge_mode: str
    model_ids: tuple[str, ...]
    model_revisions: Mapping[str, str]
    tokenizer_digest: str
    local_cache_tree_digest: str

    @property
    def is_rankable(self) -> bool:
        """`judge_mode: smoke` implies `rankable=false`; the production factory refuses smoke."""
        return self.judge_mode == "production"

    @classmethod
    def from_mapping(cls, obj: Any, *, path: str = "judge") -> JudgeRecord:
        if not isinstance(obj, Mapping):
            raise ContractError(f"{path} must be an object")
        reject_unknown_keys(
            obj,
            (
                "judge_mode",
                "model_ids",
                "model_revisions",
                "tokenizer_digest",
                "local_cache_tree_digest",
            ),
            path=path,
        )
        mode = req_str(obj, "judge_mode", path=path)
        if mode not in ("production", "smoke"):
            raise ContractError(f"{path}.judge_mode must be 'production' or 'smoke'")
        raw_ids = req(obj, "model_ids", path=path)
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ContractError(f"{path}.model_ids must be a non-empty array")
        ids: list[str] = []
        for index, value in enumerate(raw_ids):
            if not isinstance(value, str) or not value:
                raise ContractError(f"{path}.model_ids[{index}] must be a non-empty string")
            ids.append(value)
        revisions_raw = req(obj, "model_revisions", path=path)
        if not isinstance(revisions_raw, Mapping):
            raise ContractError(f"{path}.model_revisions must be an object")
        revisions = {}
        for model_id in ids:
            if model_id not in revisions_raw:
                raise ContractError(
                    f"{path}.model_revisions is missing {model_id!r}; a per-model revision is "
                    "required and an absent one is a mismatch, not a default"
                )
            revisions[model_id] = req_str(revisions_raw, model_id, path=f"{path}.model_revisions")
        return cls(
            judge_mode=mode,
            model_ids=tuple(ids),
            model_revisions=revisions,
            tokenizer_digest=parse_digest(
                req(obj, "tokenizer_digest", path=path), field=f"{path}.tokenizer_digest"
            ),
            local_cache_tree_digest=parse_digest(
                req(obj, "local_cache_tree_digest", path=path),
                field=f"{path}.local_cache_tree_digest",
            ),
        )


_RESULT_KEYS = (
    "schema_version",
    "unit_handle",
    "attempt_slot_index",
    "state",
    "score",
    "failure_code",
    "detail",
    "plan_digest",
    "run_record_digest",
    "sanitized_tree_digest",
    "scorer",
    "judge",
)


@dataclass(frozen=True, slots=True)
class UnitResult:
    """One row of the C4 result. `unit_handle` is opaque; a sealed unit id never appears here.

    `attempt_slot_index` is the slot this row scores under `unit_scope: per_unit_attempt`
    (Track 1's `T x n` denominator) and is `null` under `per_unit`. The key is always present:
    an absent slot index on a per-attempt plan would let `n` be derived from observed rows, and
    the frozen C1 says n is fixed by the plan and never derived from observed attempts.
    """

    schema_version: str
    unit_handle: str
    attempt_slot_index: int | None
    state: ResultState
    score: float | None
    failure_code: FailureCode | None
    detail: Mapping[str, Any]
    plan_digest: str
    run_record_digest: str
    sanitized_tree_digest: str
    scorer: Mapping[str, str]
    judge: JudgeRecord | None

    @classmethod
    def from_mapping(cls, raw: Any) -> UnitResult:
        if not isinstance(raw, Mapping):
            raise ContractError("a C4 unit result must be an object")
        reject_unknown_keys(raw, _RESULT_KEYS, path="unit_result")
        version = req_str(raw, "schema_version", path="unit_result")
        if version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise ContractError(f"unsupported C4 schema_version {version!r}")
        state_value = req_str(raw, "state", path="unit_result")
        try:
            state = ResultState(state_value)
        except ValueError:
            raise ContractError(
                f"state={state_value!r} is not a C4 result state; the set is closed: "
                f"{[s.value for s in ResultState]}"
            ) from None

        score = req(raw, "score", path="unit_result", allow_null=True)
        if score is not None:
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise ContractError("score must be a number or null")
            if math.isnan(float(score)) or math.isinf(float(score)):
                raise ParticipantFailure(
                    "a non-finite score is participant data, not a statistic; it never reaches "
                    "aggregation"
                )
            score = float(score)
        raw_code = req(raw, "failure_code", path="unit_result", allow_null=True)
        failure_code = None if raw_code is None else parse_failure_code(raw_code)

        if state is ResultState.PARTICIPANT_SUCCESS:
            if score is None:
                raise ContractError("participant_success requires a finite score")
            if failure_code is not None:
                raise ContractError("participant_success must not carry a failure_code")
        elif state is ResultState.PARTICIPANT_FAILURE:
            if failure_code is None:
                raise ContractError(
                    "participant_failure requires a public failure_code: an uncoded failure is "
                    "how a unit stops being explainable to the participant"
                )
            if score is not None:
                raise ContractError(
                    "participant_failure must not carry its own score. C1 is authoritative for "
                    "failure treatment; the scorer reports the code and nothing else."
                )
        else:
            if score is not None:
                raise ContractError(f"{state.value} must not carry a participant score")

        scorer_raw = req(raw, "scorer", path="unit_result")
        if not isinstance(scorer_raw, Mapping):
            raise ContractError("scorer must be an object")
        reject_unknown_keys(scorer_raw, ("package", "digest", "interface_version"), path="scorer")
        scorer = {
            "package": req_str(scorer_raw, "package", path="scorer"),
            "digest": parse_digest(req(scorer_raw, "digest", path="scorer"), field="scorer.digest"),
            "interface_version": req_str(scorer_raw, "interface_version", path="scorer"),
        }
        judge_raw = req(raw, "judge", path="unit_result", allow_null=True)
        slot = req(raw, "attempt_slot_index", path="unit_result", allow_null=True)
        if slot is not None and (isinstance(slot, bool) or not isinstance(slot, int) or slot < 0):
            raise ContractError("attempt_slot_index must be a non-negative integer or null")
        return cls(
            schema_version=version,
            unit_handle=req_str(raw, "unit_handle", path="unit_result"),
            attempt_slot_index=slot,
            state=state,
            score=score,
            failure_code=failure_code,
            detail=validate_public_detail(req(raw, "detail", path="unit_result")),
            plan_digest=parse_digest(
                req(raw, "plan_digest", path="unit_result"), field="plan_digest"
            ),
            run_record_digest=parse_digest(
                req(raw, "run_record_digest", path="unit_result"), field="run_record_digest"
            ),
            sanitized_tree_digest=parse_digest(
                req(raw, "sanitized_tree_digest", path="unit_result"), field="sanitized_tree_digest"
            ),
            scorer=scorer,
            judge=None if judge_raw is None else JudgeRecord.from_mapping(judge_raw),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "unit_handle": self.unit_handle,
            "attempt_slot_index": self.attempt_slot_index,
            "state": self.state.value,
            "score": self.score,
            "failure_code": None if self.failure_code is None else self.failure_code.value,
            "detail": dict(self.detail),
            "plan_digest": self.plan_digest,
            "run_record_digest": self.run_record_digest,
            "sanitized_tree_digest": self.sanitized_tree_digest,
            "scorer": dict(self.scorer),
            "judge": None
            if self.judge is None
            else {
                "judge_mode": self.judge.judge_mode,
                "model_ids": list(self.judge.model_ids),
                "model_revisions": dict(self.judge.model_revisions),
                "tokenizer_digest": self.judge.tokenizer_digest,
                "local_cache_tree_digest": self.judge.local_cache_tree_digest,
            },
        }


@dataclass(frozen=True, slots=True)
class Aggregate:
    """The submission-level result: the mean over the C1 roster, and the counts that prove it."""

    plan_digest: str
    statistic: str
    value: float
    n_expected: int
    n_scored: int
    n_participant_failure: int
    n_organizer_failure: int

    def __post_init__(self) -> None:
        total = self.n_scored + self.n_participant_failure + self.n_organizer_failure
        if total != self.n_expected:
            raise OrganizerFault(
                f"refusing to emit an aggregate: n_scored({self.n_scored}) + "
                f"n_participant_failure({self.n_participant_failure}) + "
                f"n_organizer_failure({self.n_organizer_failure}) = {total}, but the C1 roster "
                f"commits to {self.n_expected}. A denominator that does not reconcile with the "
                "roster is A01."
            )
        if math.isnan(self.value) or math.isinf(self.value):
            raise OrganizerFault(
                "the aggregate statistic is non-finite. A non-finite intermediate statistic is an "
                "ORGANIZER failure, unlike a non-finite value in participant data."
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "plan_digest": self.plan_digest,
            "statistic": self.statistic,
            "value": self.value,
            "n_expected": self.n_expected,
            "n_scored": self.n_scored,
            "n_participant_failure": self.n_participant_failure,
            "n_organizer_failure": self.n_organizer_failure,
            "denominator": "c1_roster",
        }

    @classmethod
    def from_mapping(cls, raw: Any) -> Aggregate:
        if not isinstance(raw, Mapping):
            raise ContractError("an aggregate must be an object")
        reject_unknown_keys(
            raw,
            (
                "plan_digest",
                "statistic",
                "value",
                "n_expected",
                "n_scored",
                "n_participant_failure",
                "n_organizer_failure",
                "denominator",
            ),
            path="aggregate",
        )
        denominator = req_str(raw, "denominator", path="aggregate")
        if denominator != "c1_roster":
            raise ContractError(
                f"denominator={denominator!r}: the only legal denominator is the complete C1 "
                "roster. If a track needs another, that is a new metric, not a new aggregation "
                "mode."
            )
        statistic = req_str(raw, "statistic", path="aggregate")
        value = req(raw, "value", path="aggregate")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ContractError("aggregate.value must be a number")
        return cls(
            plan_digest=parse_digest(
                req(raw, "plan_digest", path="aggregate"), field="plan_digest"
            ),
            statistic=statistic,
            value=float(value),
            n_expected=req_int(raw, "n_expected", path="aggregate", minimum=1),
            n_scored=req_int(raw, "n_scored", path="aggregate", minimum=0),
            n_participant_failure=req_int(
                raw, "n_participant_failure", path="aggregate", minimum=0
            ),
            n_organizer_failure=req_int(raw, "n_organizer_failure", path="aggregate", minimum=0),
        )

    @classmethod
    def from_results(
        cls,
        plan: EvaluationPlan,
        results: Sequence[UnitResult],
        *,
        organizer_failure_scope: str | None = None,
    ) -> Aggregate:
        """Aggregate C4 rows over the complete C1 roster. **Every expected unit contributes.**

        `organizer_failure_scope` lets a caller declare a whole-evaluation organizer fault (Track
        3's request) without inventing a per-unit row for it; passing anything aborts.

        Refusals, all `OrganizerFault` because none of them is the participant's doing:
        a missing expected unit, an unexpected handle, a duplicate row, a row bound to a different
        plan, any `organizer_failure` row, and any `unrankable` row.
        """
        plan.require_rankable()
        if organizer_failure_scope:
            raise OrganizerFault(
                f"whole-evaluation organizer failure ({organizer_failure_scope}); no partial "
                "leaderboard is published"
            )
        per_attempt = plan.metric.unit_scope == "per_unit_attempt"
        if per_attempt and plan.attempts_per_unit is None:
            raise OrganizerFault(
                "the plan scores per (unit, attempt slot) but declares no attempts_per_unit"
            )
        slots: Sequence[int | None] = (
            list(range(plan.attempts_per_unit))
            if per_attempt and plan.attempts_per_unit
            else [None]
        )
        expected: list[tuple[str, int | None]] = [
            (handle, slot) for handle in plan.expected_handles for slot in slots
        ]
        by_key: dict[tuple[str, int | None], UnitResult] = {}
        for result in results:
            if per_attempt and result.attempt_slot_index is None:
                raise OrganizerFault(
                    f"result for {result.unit_handle!r} carries no attempt_slot_index, but the "
                    "plan scores per (unit, attempt slot). n comes from the plan, never from the "
                    "number of rows that happen to arrive."
                )
            if not per_attempt and result.attempt_slot_index is not None:
                raise OrganizerFault(
                    f"result for {result.unit_handle!r} carries an attempt_slot_index on a "
                    "per_unit plan"
                )
            key = (result.unit_handle, result.attempt_slot_index)
            if key in by_key:
                raise OrganizerFault(f"duplicate result row for {key}")
            if result.plan_digest != plan.plan_digest:
                raise OrganizerFault(
                    f"result for {result.unit_handle!r} is bound to plan {result.plan_digest}, "
                    f"not {plan.plan_digest}"
                )
            by_key[key] = result
        missing = [k for k in expected if k not in by_key]
        extra = sorted(set(by_key) - set(expected), key=lambda k: (k[0], k[1] or 0))
        if missing or extra:
            raise OrganizerFault(
                f"result set does not cover the C1 roster: missing={missing} extra={extra}. A "
                "unit with no row must not silently leave the denominator."
            )

        values: list[float] = []
        n_scored = n_failed = 0
        for key in expected:
            handle = key[0]
            result = by_key[key]
            if result.state is ResultState.ORGANIZER_FAILURE:
                raise OrganizerFault(
                    f"unit {handle!r} is an organizer failure; the evaluation aborts rather than "
                    "publishing a partial leaderboard"
                )
            if result.state is ResultState.UNRANKABLE:
                raise OrganizerFault(
                    f"unit {handle!r} is unrankable; an unrankable unit cannot contribute to a "
                    "published aggregate"
                )
            if result.state is ResultState.PARTICIPANT_SUCCESS:
                assert result.score is not None  # noqa: S101 - guaranteed by UnitResult parsing
                values.append(plan.clip(result.score))
                n_scored += 1
            else:
                assert result.failure_code is not None  # noqa: S101 - guaranteed by parsing
                values.append(plan.failure_score_for(result.failure_code))
                n_failed += 1

        if len(values) != plan.denominator:
            raise OrganizerFault(
                f"produced {len(values)} values for a committed denominator of {plan.denominator}"
            )
        if plan.metric.statistic == "mean":
            value = math.fsum(values) / len(values)
        else:
            ordered = sorted(values)
            middle = len(ordered) // 2
            value = (
                ordered[middle]
                if len(ordered) % 2
                else (ordered[middle - 1] + ordered[middle]) / 2.0
            )
        return cls(
            plan_digest=plan.plan_digest,
            statistic=plan.metric.statistic,
            value=value,
            n_expected=plan.denominator,
            n_scored=n_scored,
            n_participant_failure=n_failed,
            n_organizer_failure=0,
        )
