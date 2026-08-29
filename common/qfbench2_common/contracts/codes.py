"""The closed C4 public failure-code enum and its versioned registry.

## Executive summary (read this first)

Twelve codes. The set is closed (global rule 0.3): an unrecognized value is an error, never an
"unknown/other" bucket, and a track cannot add a thirteenth without a registry version bump. The
first eleven were adopted verbatim in §5 of the contract freeze.

### Registry 1.1.0 adds `domain_gate_failed`

The frozen eleven had no code for *"the output was well-formed and then failed a published
domain-admissibility gate"* — a stylized-fact ceiling, a calibration check, a citation-faithfulness
threshold, an entity-roster mismatch, an invalid interval, a nonfinite value in participant data,
evidence of an unsupported kind. Every one of those was reported as `schema_invalid`, whose gloss
tells the participant their output "did not match the published output schema". For most of them
that sentence is simply false, and a participant reading it goes looking for a schema defect that
does not exist. Two tracks asked for the code independently, and this module's own consumer
(`failure_labels.DEFAULT_ADMISSIBILITY_CODE`) carried a comment calling `schema_invalid` "the
least-wrong of eleven".

Adding a row is a registry version bump and nothing else: the C4 *document* shape is unchanged, so
a 1.0.0 result document is still valid. What changes is that a consumer with a hard-coded copy of
the enum will refuse a result carrying the new value — which is the closed-enum rule working, and
the reason the version moved. See `contracts/MIGRATIONS.md`.

The registry ships as a **fixture**, not as prose, so the website generates participant-facing
wording from the same bytes the scorer uses instead of paraphrasing it. Each row is exactly
`{code, phase_scope, one_line_participant_gloss, scored}`:

* `code` — the enum value. Participant-visible.
* `phase_scope` — **the PIPELINE stage, ratified.** The value set is `ingestion | execution |
  scoring`: the stage of the evaluation pipeline that may emit the code. It is **not** the
  competition phase (`dev | final | verification`), and the name's resemblance to `phase` is the
  only reason anybody reads it that way.

  The reading is settled, not inferred, and the reason is drift: the competition phase already
  lives in C1 (`plan.phase`), which is signed and covers the whole evaluation. A per-code copy of
  it would be a second place to write the same fact, and two places eventually disagree — a
  registry row still saying `final` while the plan it is scored against says `verification` is a
  contradiction nothing in the system can adjudicate. There is exactly one competition phase per
  evaluation and it is not a property of a failure code.

  A code emitted outside its pipeline scope is an organizer fault, because it means the stage that
  produced it was not the stage that observed the fact.
* `one_line_participant_gloss` — the exact sentence a participant reads. No sealed identifiers, no
  free-form detail, no path.
* `scored` — whether the unit still occupies its slot in the C1 denominator and receives the
  committed worst-case score `W`.

**Every public code has `scored = true`, and `test_codes.py` asserts it.** That is A01 stated as
data: a `scored: false` public code would be a supported way to drop a unit from the denominator,
which is the exploit this program exists to remove. An organizer fault is not in this enum at all —
it aborts the evaluation instead of scoring a unit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from .errors import ContractError, req_bool, req_enum, req_str, reject_unknown_keys

__all__ = [
    "FAILURE_CODE_REGISTRY_VERSION",
    "PHASE_SCOPES",
    "FailureCode",
    "FailureCodeRow",
    "failure_code_registry",
    "parse_failure_code",
]

#: Bumped whenever a row is added, removed, or its `scored` value changes. Consumers pin it.
#: 1.0.0 -> 1.1.0: `domain_gate_failed` added.
FAILURE_CODE_REGISTRY_VERSION = "1.1.0"

#: The PIPELINE stage that may emit a code. Closed.
#:
#: Ratified reading, not an inference: this is the evaluation-pipeline stage, **never** the
#: competition phase (`dev | final | verification`), which lives in C1 and must not be copied
#: per-code where it would drift out of agreement with the signed plan.
PHASE_SCOPES = ("ingestion", "execution", "scoring")


class FailureCode(StrEnum):
    """The twelve public participant-failure codes. Frozen; the set is closed."""

    NO_OUTPUT = "no_output"
    MALFORMED_OUTPUT = "malformed_output"
    SCHEMA_INVALID = "schema_invalid"
    INCOMPLETE_OUTPUT = "incomplete_output"
    RESOURCE_TIMEOUT = "resource_timeout"
    RESOURCE_OOM = "resource_oom"
    CONTAINER_CRASHED = "container_crashed"
    IMAGE_UNUSABLE = "image_unusable"
    NETWORK_VIOLATION = "network_violation"
    CUTOFF_VIOLATION = "cutoff_violation"
    CONTAMINATION_DETECTED = "contamination_detected"
    #: Well-formed output that failed a PUBLISHED domain-admissibility gate. Registry 1.1.0.
    #: This is the honest home for a faithfulness threshold, a calibration or stylized-fact
    #: ceiling, an entity-roster mismatch, an invalid interval, a nonfinite value in participant
    #: data, or evidence of a kind the unit does not accept. It is NOT a second `schema_invalid`:
    #: the output parsed and satisfied the schema, and then failed a rule the unit published
    #: separately from it.
    DOMAIN_GATE_FAILED = "domain_gate_failed"


def parse_failure_code(value: Any, *, field: str = "failure_code") -> FailureCode:
    """Strictly parse a public failure code. An unknown string is an error, not an 'other'."""
    if isinstance(value, FailureCode):
        return value
    if not isinstance(value, str):
        raise ContractError(f"{field} must be a string, got {type(value).__name__}")
    try:
        return FailureCode(value)
    except ValueError:
        raise ContractError(
            f"{field}={value!r} is not a public failure code. The enum is closed: "
            f"{[c.value for c in FailureCode]}. Adding a code is a registry version bump, not a "
            "new string at a call site."
        ) from None


@dataclass(frozen=True, slots=True)
class FailureCodeRow:
    """One registry row: `{code, phase_scope, one_line_participant_gloss, scored}`."""

    code: FailureCode
    #: PIPELINE stage (`ingestion | execution | scoring`), never the competition phase.
    phase_scope: str
    one_line_participant_gloss: str
    scored: bool


_ROW_KEYS = ("code", "phase_scope", "one_line_participant_gloss", "scored")


def _registry_path() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "c4_failure_code_registry.json"


@lru_cache(maxsize=1)
def failure_code_registry() -> dict[FailureCode, FailureCodeRow]:
    """Load and validate the shipped registry fixture.

    Validation is total on purpose: the registry must cover the enum **exactly** — no missing row,
    no row for a code that does not exist. A registry that silently omits a code is a code whose
    participant-facing wording somebody will invent at a call site.
    """
    document = json.loads(_registry_path().read_text(encoding="utf-8"))
    reject_unknown_keys(document, ("schema_version", "contract_set", "codes"), path="registry")
    version = req_str(document, "schema_version", path="registry")
    if version != FAILURE_CODE_REGISTRY_VERSION:
        raise ContractError(
            f"failure-code registry fixture is version {version!r} but this build expects "
            f"{FAILURE_CODE_REGISTRY_VERSION!r}"
        )
    rows: dict[FailureCode, FailureCodeRow] = {}
    raw_rows = document.get("codes")
    if not isinstance(raw_rows, list):
        raise ContractError("registry.codes must be an array")
    for index, raw in enumerate(raw_rows):
        path = f"registry.codes[{index}]"
        reject_unknown_keys(raw, _ROW_KEYS, path=path)
        code = parse_failure_code(req_str(raw, "code", path=path), field=f"{path}.code")
        if code in rows:
            raise ContractError(f"duplicate registry row for {code.value!r}")
        gloss = req_str(raw, "one_line_participant_gloss", path=path)
        if len(gloss) > 200 or "\n" in gloss:
            raise ContractError(f"{path}.one_line_participant_gloss must be one short line")
        rows[code] = FailureCodeRow(
            code=code,
            phase_scope=req_enum(raw, "phase_scope", PHASE_SCOPES, path=path),
            one_line_participant_gloss=gloss,
            scored=req_bool(raw, "scored", path=path),
        )
    missing = sorted(c.value for c in FailureCode if c not in rows)
    if missing:
        raise ContractError(f"failure-code registry is missing rows for {missing}")
    return rows
