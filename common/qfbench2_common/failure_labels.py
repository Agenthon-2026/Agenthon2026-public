"""Cross-track failure-mode taxonomy, the public projection, and the reporter.

Every gate failure and every scored-but-wrong outcome emits a label. Aggregated across
tracks these labels form the unified failure-mode map that is the competition's headline
scientific artifact. Labels are stable identifiers so the post-competition paper can be
regenerated from the released JSONL.

## What changed on 2026-08-21, and why (frozen C4)

`report()` used to serialize an **arbitrary** `detail` dict and a raw `unit_id` verbatim into
JSONL, with no allowlist, no size bound and no `allow_nan=False`; `score.py` pointed that file at
the CodaBench *output* directory. A synthetic sentinel planted in a track scorer's diagnostics was
measured surviving into `failure_map.jsonl` through both channels.

Three things close it, and they are all in this module:

1. **`public_detail(detail)`** — the one shared redactor. It filters an arbitrary producer dict down
   to the frozen C4 public projection: *enum code plus integer counts only*, no free-form strings.
   Track 2 asked for exactly this function so the private final scorer and every future entrypoint
   call the same code instead of each keeping a copy of an allowlist. The allowlist itself lives in
   `qfbench2_common.contracts.result.public_detail_keys()`; this is the filtering front end.
2. **`report(..., sink="public")` is the default and redacts.** Raw diagnostics require an explicit
   `sink="operator"` and a caller that has chosen an operator-only path. Absent that choice nothing
   sensitive is written anywhere, which is the fail-closed direction.
3. **`public_failure_code(labels)`** — the label -> frozen-C4-code mapping, so a track's rich
   internal label becomes one of twelve bounded public codes rather than a string somebody invents
   at a call site.

`unit_id` was renamed to `unit_handle` in `report()`. The rename is the point: C1 commits opaque
handles and a sealed unit id must never reach a persistent leaderboard artifact. Positional callers
are unaffected; a caller passing `unit_id=` by keyword must update.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Any

from .contracts.codes import FailureCode
from .contracts.result import public_detail_keys

__all__ = [
    "DEFAULT_ADMISSIBILITY_CODE",
    "ORGANIZER_FAULT_LABELS",
    "FailureLabel",
    "public_detail",
    "public_failure_code",
    "report",
]


class FailureLabel(str, Enum):
    # --- shared (any track) -------------------------------------------------
    INTEGRITY_BAD_MANIFEST = "shared.integrity.bad_manifest"
    INTEGRITY_BAD_IMAGE_HASH = "shared.integrity.bad_image_hash"
    SCHEMA_INVALID_OUTPUT = "shared.schema.invalid_output"
    RESOURCE_TIMEOUT = "shared.resource.timeout"
    RESOURCE_OOM = "shared.resource.oom"
    LEAKAGE_NETWORK = "shared.leakage.network_access"
    LEAKAGE_CUTOFF = "shared.leakage.cutoff_violation"
    CONTAMINATION_CANARY = "shared.contamination.canary_emitted"
    NONDETERMINISM = "shared.repro.nondeterministic_rerun"
    # --- T1 coding ----------------------------------------------------------
    T1_INVARIANT_VIOLATION = "t1.invariant_violation"  # parity / no-arbitrage / PDE residual
    T1_WRONG_NUMERIC = "t1.wrong_numeric"
    T1_CONVENTION_ERROR = "t1.convention_error"  # from the DI verifier (sign/compounding)
    T1_MISLABELING = "t1.mislabeling"
    # --- T2 forecasting -----------------------------------------------------
    T2_UNCALIBRATED_MARGINAL = "t2.uncalibrated_marginal"
    T2_BAD_DEPENDENCE = "t2.bad_cross_asset_dependence"
    T2_TAIL_MISCALIBRATION = "t2.tail_miscalibration"
    T2_REGIME_SHIFT_FAILURE = "t2.regime_shift_failure"
    # --- T3 simulation ------------------------------------------------------
    T3_SEMANTIC_REGRESSION = "t3.semantic_regression_fail"  # matching-engine / trace mismatch
    T3_LATENCY_CAUSALITY_VIOLATION = "t3.latency_causality_violation"  # message-ledger latency/causal/wakeup breach or empty ledger
    T3_STYLIZED_FACT_BREACH = "t3.stylized_fact_breach"
    T3_THROUGHPUT_NONIMPROVING = "t3.throughput_nonimproving"
    T3_PARSE_ERROR = "t3.parse_error"  # trace/events.json unreadable or malformed
    T3_REFERENCE_INTEGRITY_ERROR = (
        "t3.reference_integrity_error"  # sealed reference trace missing/corrupt
    )
    # --- T4 analysis --------------------------------------------------------
    T4_UNFAITHFUL_CITATION = "t4.unfaithful_citation"
    T4_STALE_EVIDENCE = "t4.stale_evidence"  # embargo / counterfactual probe
    T4_MISCALIBRATED_INTERVAL = "t4.miscalibrated_interval"
    T4_WRONG_DIRECTION = "t4.wrong_direction"


#: Labels that describe a fault in ORGANIZER material. A unit carrying one of these is never
#: charged to the participant: the frozen C1 `organizer_failure` policy is `abort_whole_evaluation`,
#: so the driver stops instead of scoring the unit. `T3_REFERENCE_INTEGRITY_ERROR` means the sealed
#: reference trace is missing or corrupt, which no submission can cause or fix.
ORGANIZER_FAULT_LABELS: frozenset[FailureLabel] = frozenset(
    {
        FailureLabel.T3_REFERENCE_INTEGRITY_ERROR,
    }
)

#: An inadmissible verdict whose labels carry no exact public counterpart reports this.
#:
#: **Was `SCHEMA_INVALID` until failure-code registry 1.1.0**, under a comment in this file calling
#: it "the least-wrong of eleven". It was the wrong sentence to show a participant: a stylized-fact
#: breach, a calibration gate, a citation-faithfulness threshold, an entity-roster mismatch, an
#: invalid interval and a nonfinite value in participant data were all reported as "your output
#: parsed but did not match the published output schema" — false for all but the first reading of
#: it, and it sends the participant hunting for a schema defect that is not there.
#:
#: `domain_gate_failed` says the true thing: the output was well-formed and then failed a rule the
#: unit published separately from its schema. Two agents asked for it independently; adding it was
#: a registry version bump (see `contracts/MIGRATIONS.md`), which is the supported way to grow a
#: closed enum and the reason this is not a free-form string at a call site.
#:
#: A track that means *schema* still says so: `SCHEMA_INVALID_OUTPUT` maps to `SCHEMA_INVALID`
#: exactly, below, and is unaffected.
DEFAULT_ADMISSIBILITY_CODE = FailureCode.DOMAIN_GATE_FAILED

#: Label -> frozen public C4 code, for labels whose correspondence is exact. Everything absent from
#: this table falls to `DEFAULT_ADMISSIBILITY_CODE`; the scored-but-wrong labels (T1_WRONG_NUMERIC,
#: T2_TAIL_MISCALIBRATION, ...) are deliberately absent because they describe a low score, not an
#: inadmissible unit, and a low score carries no failure code at all.
_PUBLIC_CODE_FOR_LABEL: dict[FailureLabel, FailureCode] = {
    FailureLabel.INTEGRITY_BAD_MANIFEST: FailureCode.MALFORMED_OUTPUT,
    FailureLabel.INTEGRITY_BAD_IMAGE_HASH: FailureCode.IMAGE_UNUSABLE,
    FailureLabel.SCHEMA_INVALID_OUTPUT: FailureCode.SCHEMA_INVALID,
    FailureLabel.RESOURCE_TIMEOUT: FailureCode.RESOURCE_TIMEOUT,
    FailureLabel.RESOURCE_OOM: FailureCode.RESOURCE_OOM,
    FailureLabel.LEAKAGE_NETWORK: FailureCode.NETWORK_VIOLATION,
    FailureLabel.LEAKAGE_CUTOFF: FailureCode.CUTOFF_VIOLATION,
    FailureLabel.CONTAMINATION_CANARY: FailureCode.CONTAMINATION_DETECTED,
    FailureLabel.NONDETERMINISM: FailureCode.INCOMPLETE_OUTPUT,
    FailureLabel.T3_PARSE_ERROR: FailureCode.MALFORMED_OUTPUT,
}


def public_failure_code(labels: Iterable[FailureLabel | str]) -> FailureCode:
    """Map a verdict's labels onto exactly one bounded public C4 code.

    The first label with an exact counterpart wins, so a track that emits
    `[LEAKAGE_CUTOFF, T2_TAIL_MISCALIBRATION]` reports the cutoff violation rather than the
    calibration diagnostic. An unrecognized string is ignored rather than propagated: the public
    code set is closed, and echoing an unknown label into a public artifact is the leak this
    module exists to prevent.

    Organizer-fault labels are **not** handled here. Check `ORGANIZER_FAULT_LABELS` first; a caller
    that maps one of those to a participant code has turned an organizer fault into a participant
    zero, which the global rules forbid.
    """
    for label in labels:
        try:
            resolved = FailureLabel(label)
        except ValueError:
            continue
        code = _PUBLIC_CODE_FOR_LABEL.get(resolved)
        if code is not None:
            return code
    return DEFAULT_ADMISSIBILITY_CODE


def public_detail(detail: object) -> dict[str, Any]:
    """Filter an arbitrary producer dict down to the frozen C4 public projection.

    Enum code plus non-negative integer counts, and nothing else. Every other key is dropped and
    every non-conforming value is dropped, including a conforming key holding a string: the
    projection carries **no** free-form text anywhere, which is what makes it impossible to smuggle
    `note` back in under an allowlisted name.

    Returns a fresh dict; the input is never mutated. A non-mapping input yields `{}` rather than
    raising, because this is the last line of defence on a serialization path and a redactor that
    raises is a redactor somebody wraps in `except: pass`.
    """
    if not isinstance(detail, Mapping):
        return {}
    allowed = public_detail_keys()
    out: dict[str, Any] = {}
    for key in allowed:
        if key not in detail:
            continue
        value = detail[key]
        if key == "code":
            # Only a value that is already one of the frozen codes survives.
            try:
                out[key] = FailureCode(value).value
            except (ValueError, TypeError):
                continue
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            continue
        out[key] = value
    return out


#: A single JSONL record is bounded so a pathological producer cannot fill the output volume.
MAX_RECORD_BYTES = 4096

_SINKS = ("public", "operator")


def report(
    path: str | pathlib.Path,
    unit_handle: str,
    track: str,
    labels: list[FailureLabel],
    detail: dict | None = None,
    *,
    sink: str = "public",
) -> None:
    """Append one JSONL record to a failure-mode map.

    `sink="public"` (the default) writes a record fit for a persistent leaderboard artifact:
    `detail` is passed through `public_detail`, so only an enum code and integer counts survive.
    `sink="operator"` keeps the producer's `detail` verbatim and is only legitimate when `path`
    is an operator-only location the participant has no read path to; the caller owns that
    guarantee, this function merely refuses to make it silently by defaulting to it.

    `unit_handle` must be the opaque C1 handle. Non-finite numbers are refused outright
    (`allow_nan=False`): `NaN` is not valid JSON, and a file the platform silently discards is how
    a real submission was reported as `Failed` with no log that explained it.
    """
    if sink not in _SINKS:
        raise ValueError(f"sink must be one of {list(_SINKS)}, got {sink!r}")
    if not isinstance(unit_handle, str) or not unit_handle:
        raise ValueError("unit_handle must be a non-empty opaque C1 unit handle")
    payload = dict(detail or {}) if sink == "operator" else public_detail(detail)
    rec = {
        "unit_handle": unit_handle,
        "track": track,
        "labels": [FailureLabel(lab).value for lab in labels],
        "detail": payload,
    }
    line = json.dumps(rec, allow_nan=False, sort_keys=True)
    if len(line.encode("utf-8")) > MAX_RECORD_BYTES:
        # Truncating the detail is safe; truncating the record would emit unparseable JSONL.
        rec["detail"] = {"truncated": 1} if sink == "operator" else {}
        line = json.dumps(rec, allow_nan=False, sort_keys=True)
    with open(path, "a") as fh:
        fh.write(line + "\n")
