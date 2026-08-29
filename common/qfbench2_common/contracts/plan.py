"""C1 — the Evaluation Plan, and the two functions every track calls.

## Executive summary (read this first)

C1 is the pre-committed, signed statement of *what will be scored and how failure is treated*. It
exists because of A01: before it, the aggregate was a mean over whatever the participant happened
to make admissible, so answering only the two easy units out of four scored `1.0000` while an
honest run over all four scored `0.5000`. C1 fixes the denominator to the committed roster.

Two functions carry the frozen ruling R-2 and are called by all four tracks:

* `plan.failure_score_for(code)` — the pre-committed worst-case value `W` a failed unit contributes.
* `plan.clip(score)` — a real per-unit score clamped into the same domain.

Both halves are required. A bare penalty is still exploitable: if `W` is *better* than an
attainable real score, a participant improves the aggregate by deliberately failing a unit they
would have scored worse on. Clipping is what makes failure never strictly better than any real
outcome. `clip_real_scores_to_domain` must therefore be `true` for a rankable plan, and `clip()`
refuses to run on a plan that disclaims it rather than silently clamping anyway.

### The frozen per-track values

| Track | direction | domain | W |
|---|---|---|---|
| coding | desc | [0.0, 1.0] | 0.0 per (unit, slot); denominator `T x n` |
| forecasting | asc | [0.0, 4.0] normalized composite | 4.0 (M0 baseline = 1.0) |
| simulation | desc | [0.0, published clip max] | 0.0 events/sec |
| analysis | desc | [-0.27, 1.0] | -0.27 = `0*w_a - w_c*interval_level` |

`W` is validated to be the **worst end of the declared domain** for the declared direction — the
minimum for `desc`, the maximum for `asc`. A plan whose `W` sits inside its own domain is refused
at parse time, because such a plan is exactly the exploitable shape R-2 removes.

### Two representations

The **public commitment** ships in bundles and carries counts, digests and policy only. The
**expanded roster** carries unit identities and is resolver/scorer-only. `plan.expected_units`
raises on a public commitment rather than returning an empty tuple — an empty roster read as
"no units expected" is the A01 failure mode in a new costume.

### Sealed-phase handles are opaque, and that is a security property (new in C1 1.1.0)

A `unit_handle` is not just a key. Under the frozen worker/scoring topology it is a **directory
name** directly under the ingestion program's output root — and CodaBench uploads that root as the
submission's `prediction_result` (`compute_worker.py:1758`) and serves it back to the submitter as
a signed download URL unless the phase sets `hide_prediction_output` or `hide_output`, both of
which are `BooleanField(default=False)`. C8 1.1.0 gates the flag; C1 1.1.0 gates the name. They are
independent defences and the seal wants both, because the handle also reaches the participant
through the leaderboard and the C4 result, where no phase flag applies at all.

So for `final` and `verification`, every handle must match `^u-[0-9a-f]{8,32}$`, and the roster
must use one width throughout. `dev` keeps readable handles: nothing there is sealed, and forcing
hex on a development roster would only make organizer debugging worse.

`derive_opaque_roster(sealed_ids, phase_salt=...)` is the supported way to mint them — keyed
HMAC-SHA256, stable across regenerations, and a *different* salt per phase so the same sealed unit
is unrecognisable between the dev board and the final one.

### Track 4's scoring parameters are closed, and that is arithmetic (new in C1 1.2.0)

`expected_units[].scoring_params.target_type` is `classification | regression | ranking`
(`TARGET_TYPES`) and `composite_weights` names exactly `accuracy` and `calibration`
(`COMPOSITE_WEIGHT_KEYS`), each in `[0, 1]`, summing to 1.

Both were free-form in 1.1.0 and both had already gone wrong in the shipped golden fixture, which
declared `target_type: "point_and_interval"`. Track 4 cannot score that value; its plan adapter
refuses the fixture rather than defaulting, because the pre-fix scorer's fallback was *label
accuracy*, so an unrecognized target type silently changed which metric the leaderboard reported.

The weight constraint is not tidiness either. The frozen analysis worst case is
`W = 0*w_accuracy - w_calibration*interval_level`, and `metric.domain.min` is validated to equal
`W` — so a plan whose weights sum to anything but 1 moves the domain every real score is clipped
into while remaining internally consistent everywhere a reader would look.

`contract_set` stays `"1.1.0"`: no key was added or removed, and C1 compares `contract_set`
exactly, so bumping it would refuse every plan every consumer currently produces.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .codes import FailureCode, failure_code_registry, parse_failure_code
from .digest import digest_json, parse_digest
from .errors import (
    ContractError,
    OrganizerFault,
    ParticipantFailure,
    req,
    req_bool,
    req_enum,
    req_float,
    req_int,
    req_list,
    req_mapping,
    req_str,
    reject_unknown_keys,
)
from .signing import SignatureEnvelope, TrustStore, VerificationResult, verify_signed

__all__ = [
    "AGGREGATION_STATISTICS",
    "COMPOSITE_WEIGHT_KEYS",
    "CONTRACT_SET",
    "DIRECTIONS",
    "HANDLE_RE",
    "MAX_HANDLE_LENGTH",
    "MIN_HANDLE_SALT_CHARS",
    "OPAQUE_HANDLE_HEX_DEFAULT",
    "OPAQUE_HANDLE_RE",
    "PHASES",
    "RESERVED_HANDLES",
    "SEALED_PHASES",
    "TARGET_TYPES",
    "TRACKS",
    "UNIT_SCOPES",
    "EvaluationPlan",
    "MetricSpec",
    "ParticipantFailurePolicy",
    "RosterEntry",
    "compute_roster_digest",
    "derive_opaque_handle",
    "derive_opaque_roster",
    "validate_unit_handle",
]

CONTRACT_SET = "1.1.0"
#: C1 1.1.0 -> 1.2.0: `scoring_params.target_type` and `scoring_params.composite_weights` are
#: closed. `contract_set` deliberately did NOT move -- no key was added or removed, and C1
#: compares `contract_set` exactly, so bumping it would refuse every plan every consumer currently
#: produces over a narrowing that costs them nothing. The closed sets are `TARGET_TYPES` and
#: `COMPOSITE_WEIGHT_KEYS` below, and both are enforced in `_parse_roster_entry`.
SCHEMA_VERSION = "1.2.0"
TRACKS = ("coding", "forecasting", "simulation", "analysis")
PHASES = ("dev", "final", "verification")
#: The phases whose roster is SEALED, and therefore the phases whose handles must be opaque.
#: A handle becomes a directory name inside the ingestion output root, and that root is
#: retrievable by the participant unless the phase hides it (see C8 `phase_visibility`). In a
#: sealed phase the set of directory names IS the sealed roster.
SEALED_PHASES = ("final", "verification")
DIRECTIONS = ("asc", "desc")
UNIT_SCOPES = ("per_unit", "per_unit_attempt")
#: R-6 separates the integrity requirement (fixed denominator over the complete roster) from the
#: taste question (mean vs median over that roster), which the project owner may override.
AGGREGATION_STATISTICS = ("mean", "median")
NORMALIZATION_MODES = ("ref_scale",)
#: Track 4's prediction tasks. Closed since C1 1.2.0, per frozen global rule 0.3.
#:
#: `target_type` selects which metric the leaderboard reports, so an unrecognized value is not a
#: cosmetic typo: the pre-fix Track-4 scorer fell back to label accuracy, which means a plan
#: reading `point_and_interval` -- the value the shipped golden fixture carried -- silently scored
#: a regression unit as a classification one. There is no "other" member on purpose.
TARGET_TYPES = ("classification", "regression", "ranking")
#: The exact key set of `scoring_params.composite_weights`, in composite order, and they must sum
#: to 1.
#:
#: This is an arithmetic requirement, not tidiness. The frozen analysis worst case is
#: `W = 0*w_accuracy - w_calibration*interval_level`, and `metric.domain.min` is validated to equal
#: `W`. Weights that do not sum to 1 therefore move the domain the leaderboard is clipped into
#: while every other field still looks self-consistent.
COMPOSITE_WEIGHT_KEYS = ("accuracy", "calibration")

_CORE_KEYS = (
    "schema_version",
    "contract_set",
    "competition_id",
    "track",
    "phase",
    "plan_id",
    "metric",
    "roster",
    "participant_failure",
    "organizer_failure",
    "scorer",
    "required_evidence",
    "signature",
)
_TRACK_KEYS: dict[str, tuple[str, ...]] = {
    "coding": ("attempts_per_unit", "k_values"),
    "forecasting": ("normalization",),
    "simulation": ("aggregation", "repeats", "warmup_discarded", "every_repeat_must_pass"),
    "analysis": (),
}


#: A unit handle becomes three things: a key in the C1 roster, a directory name under the
#: ingestion output root, and a filename under `_control/`. This is the character class every one
#: of those can carry safely, and it is deliberately the same class the Runner's
#: `handles.validate_roster_handle` enforces at the point a handle first becomes a path — two
#: grammars for one identifier means a plan the Hub accepts and the Runner refuses.
HANDLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_HANDLE_LENGTH = 128

#: Names the frozen worker/scoring topology has already spent. `_control/` is underscore-prefixed
#: precisely so it can never collide with a unit handle; `ref` and `res` are the platform's own
#: directory names inside the scoring namespace.
RESERVED_HANDLES = frozenset({"ref", "res", "_control", ".", ".."})

#: The opaque grammar a SEALED-phase handle must match. Hex and nothing else: there is no
#: substring of `u-3f2a91c4bb07de56` that tells a participant which instrument, date, entity or
#: difficulty tier the unit is, which is the whole property being bought.
#:
#: The bound is 8-32 hex characters — 32 bits at the floor, 128 at the ceiling. The floor is low
#: enough for a small dev-shaped roster and high enough that a handle cannot be a counter; the
#: ceiling keeps the directory name short. `derive_opaque_handle` mints 16 (64 bits), which is
#: where the collision probability over a few hundred units is negligible without being unwieldy.
OPAQUE_HANDLE_RE = re.compile(r"^u-[0-9a-f]{8,32}$")
OPAQUE_HANDLE_HEX_DEFAULT = 16

#: The minimum length of a per-phase handle salt. The salt is the ONLY thing between a published
#: handle and a dictionary attack: sealed unit ids are drawn from a small, guessable space
#: (`t2-<ticker>-<date>`), so an unsalted or weakly salted derivation is invertible by anyone
#: willing to enumerate it. HMAC with a high-entropy key is not.
MIN_HANDLE_SALT_CHARS = 32


def validate_unit_handle(handle: Any, *, phase: str, path: str = "unit_handle") -> str:
    """Return `handle` if a plan in `phase` may carry it, else raise `OrganizerFault`.

    Two layers, and they answer two different questions.

    **Every phase** — is this string safe as a directory name and free of the topology's reserved
    names? A handle with a path separator, a leading `_` (which could collide with `_control/`),
    or the value `ref`/`res` is an organizer fault in any phase.

    **Sealed phases only** (`final`, `verification`) — is this string *opaque*? A sealed roster is
    sealed only as long as nothing publishes its membership, and the handle is published three
    times over: as a directory name in the ingestion output root, as a leaderboard row, and in the
    C4 result. `hide_prediction_output` stops a participant downloading that root, but a handle
    like `t2-aapl-2026-09-30` has already told them what the unit is the moment it appears on the
    board. Opacity and output-hiding are two independent defences and the seal wants both.

    `OrganizerFault` rather than `ContractError` because the roster is ours. A handle the topology
    cannot carry is a mistake in the evaluation plan, and charging it to a participant would turn
    an organizer defect into somebody's zero.
    """
    if phase not in PHASES:
        raise ContractError(f"{path}: unknown phase {phase!r}; the set is {list(PHASES)}")
    if not isinstance(handle, str):
        raise OrganizerFault(f"{path} must be a string, got {type(handle).__name__}")
    if not handle:
        raise OrganizerFault(f"{path} may not be empty")
    if len(handle) > MAX_HANDLE_LENGTH:
        raise OrganizerFault(
            f"{path} is {len(handle)} characters; the bound is {MAX_HANDLE_LENGTH}"
        )
    if unicodedata.normalize("NFC", handle) != handle:
        # Frozen rule 0.2: paths inside a digested structure are NFC-normalized. A handle that is
        # not already NFC would hash differently from the directory it names on a filesystem that
        # normalizes, and two spellings of one name cannot both be the key the scorer joins on.
        raise OrganizerFault(
            f"{path}={handle!r} is not NFC-normalized; the roster digest is taken over the "
            "handles and the filesystem may store a different spelling of the same name"
        )
    if handle in RESERVED_HANDLES:
        raise OrganizerFault(
            f"{path}={handle!r} is reserved: the frozen scoring namespace already uses it "
            f"({sorted(RESERVED_HANDLES)})"
        )
    if handle.startswith("_"):
        raise OrganizerFault(
            f"{path}={handle!r} begins with '_', which is reserved for the organizer control "
            "root. `_control/` is underscore-prefixed so it can never collide with a unit "
            "handle; a handle that can collide with it is an organizer fault."
        )
    if handle.startswith("."):
        raise OrganizerFault(
            f"{path}={handle!r} begins with '.'; a dot-prefixed directory is invisible to an "
            "operator listing the scoring namespace"
        )
    if not HANDLE_RE.match(handle):
        raise OrganizerFault(
            f"{path}={handle!r} is outside the permitted character class "
            "[A-Za-z0-9][A-Za-z0-9._-]*. Path separators, NUL, whitespace and shell "
            "metacharacters are refused where the handle is minted, not where it is used."
        )
    if phase in SEALED_PHASES and not OPAQUE_HANDLE_RE.match(handle):
        raise OrganizerFault(
            f"{path}={handle!r} carries semantic content and this is the SEALED {phase!r} phase. "
            f"A sealed-phase handle must match {OPAQUE_HANDLE_RE.pattern}. The handle becomes a "
            "DIRECTORY NAME inside the ingestion program's output root, which the CodaBench "
            "platform uploads as the submission's prediction_result and serves back to the "
            "participant on request; in a sealed phase the set of those directory names is the "
            "sealed roster, and a descriptive name defeats the seal even when the output is "
            "hidden. Mint handles with qfbench2_common.contracts.derive_opaque_roster() rather "
            "than inventing a scheme."
        )
    return handle


def derive_opaque_handle(
    sealed_id: str, *, phase_salt: str, hex_length: int = OPAQUE_HANDLE_HEX_DEFAULT
) -> str:
    """Derive a stable opaque handle from a sealed unit id and a PER-PHASE salt.

    `handle = "u-" + HMAC-SHA256(phase_salt, sealed_id)[:hex_length]`.

    Three properties, each of them load-bearing:

    * **Stable.** The same `(sealed_id, phase_salt)` always yields the same handle, so a plan can
      be regenerated, a roster re-derived, and an evaluation re-run without the roster digest
      moving. A random handle would need a stored mapping, and a stored mapping is a file that
      leaks.
    * **Keyed, not merely hashed.** Sealed ids come from a small guessable space. A bare
      `sha256(unit_id)` is invertible by anyone who can enumerate that space — which is everyone,
      because the space is "tickers times dates". The salt is what makes the handle opaque rather
      than merely unreadable, so it is organizer-held secret material and never ships.
    * **Per phase.** A distinct salt for `dev`, `final` and `verification` means the same sealed
      unit gets three unrelated handles. Sharing one salt would let a participant who saw a unit
      in dev recognise it in the final roster, which is the seal leaking sideways through an
      identifier nobody thought of as sealed.

    Raises `OrganizerFault` on a salt too short to be worth having, because a weak salt fails
    silently: it produces perfectly well-formed handles that happen to be invertible.
    """
    if not isinstance(sealed_id, str) or not sealed_id:
        raise OrganizerFault("a sealed unit id must be a non-empty string")
    if not isinstance(phase_salt, str) or len(phase_salt) < MIN_HANDLE_SALT_CHARS:
        raise OrganizerFault(
            f"the per-phase handle salt must be a string of at least {MIN_HANDLE_SALT_CHARS} "
            "characters. It is the only thing standing between a published handle and a "
            "dictionary attack over the sealed id space; a short salt yields handles that look "
            "opaque and are not."
        )
    if not isinstance(hex_length, int) or isinstance(hex_length, bool) or not 8 <= hex_length <= 32:
        raise OrganizerFault(
            f"hex_length={hex_length!r} must be an integer in [8, 32]; the opaque grammar is "
            f"{OPAQUE_HANDLE_RE.pattern}"
        )
    mac = hmac.new(phase_salt.encode("utf-8"), sealed_id.encode("utf-8"), hashlib.sha256)
    handle = "u-" + mac.hexdigest()[:hex_length]
    # Belt and braces: the derivation cannot produce an invalid handle, and if a future edit makes
    # it possible the failure happens here rather than at plan-parse time in a different repo.
    if not OPAQUE_HANDLE_RE.match(handle):  # pragma: no cover - unreachable by construction
        raise OrganizerFault(f"derived handle {handle!r} does not match the opaque grammar")
    return handle


def derive_opaque_roster(
    sealed_ids: Sequence[str], *, phase_salt: str, hex_length: int = OPAQUE_HANDLE_HEX_DEFAULT
) -> tuple[str, ...]:
    """Derive a whole roster, in order, refusing a truncation collision.

    Order is preserved because the roster digest is taken over the ORDERED array. A collision is
    an `OrganizerFault` rather than a silently deduplicated roster: two sealed units sharing one
    handle means one directory, one leaderboard row and a denominator that no longer matches the
    committed count — the A01 shape, arriving through the back door.
    """
    handles = [
        derive_opaque_handle(i, phase_salt=phase_salt, hex_length=hex_length) for i in sealed_ids
    ]
    seen: dict[str, str] = {}
    for sealed_id, handle in zip(sealed_ids, handles, strict=True):
        if handle in seen:
            raise OrganizerFault(
                f"handle collision: {sealed_id!r} and {seen[handle]!r} both derive {handle!r} at "
                f"hex_length={hex_length}. Raise hex_length rather than dropping a unit; a "
                "shrunken roster is exactly the defect C1 exists to prevent."
            )
        seen[handle] = sealed_id
    return tuple(handles)


def compute_roster_digest(unit_handles: Sequence[str]) -> str:
    """The frozen roster digest: JCS over the **ordered** `[unit_handle]` array.

    Order is part of the commitment. Two consumers that sort differently would otherwise compute
    two digests for one roster, and every sealed phase would become an organizer fault.
    """
    for handle in unit_handles:
        if not isinstance(handle, str) or not handle:
            raise ContractError("every roster entry must be a non-empty unit_handle string")
    return digest_json(list(unit_handles))


@dataclass(frozen=True, slots=True)
class MetricSpec:
    direction: str
    domain_min: float
    domain_max: float
    statistic: str
    unit_scope: str

    @property
    def worst(self) -> float:
        """The worst attainable value: the floor for `desc`, the ceiling for `asc`."""
        return self.domain_min if self.direction == "desc" else self.domain_max

    @property
    def best(self) -> float:
        return self.domain_max if self.direction == "desc" else self.domain_min

    @classmethod
    def from_mapping(cls, obj: Any, *, path: str = "metric") -> MetricSpec:
        mapping = _as_object(obj, path)
        reject_unknown_keys(mapping, ("direction", "domain", "statistic", "unit_scope"), path=path)
        domain = req_mapping(mapping, "domain", path=path)
        reject_unknown_keys(domain, ("min", "max"), path=f"{path}.domain")
        low = req_float(domain, "min", path=f"{path}.domain")
        high = req_float(domain, "max", path=f"{path}.domain")
        if not low < high:
            raise ContractError(
                f"{path}.domain must satisfy min < max; got min={low}, max={high}. An unbounded "
                "domain is not expressible: Track 3 publishes its clip max in the plan."
            )
        return cls(
            direction=req_enum(mapping, "direction", DIRECTIONS, path=path),
            domain_min=low,
            domain_max=high,
            statistic=req_enum(mapping, "statistic", AGGREGATION_STATISTICS, path=path),
            unit_scope=req_enum(mapping, "unit_scope", UNIT_SCOPES, path=path),
        )


@dataclass(frozen=True, slots=True)
class ParticipantFailurePolicy:
    """R-2 `fixed_worst_case`, plus the reserved per-code slot.

    **`by_code` is RESERVED through contract set 1.1.0: required as a key, and required to be empty.**

    It is vacuous as frozen, and that is the whole reason it is nailed shut rather than left to
    look useful. Three frozen rules meet on it: `score` must equal `W`, the worst end of the metric
    domain; an override must lie *within* the domain; and an override may never be *better* than
    `W`. On a domain whose worst end is `W`, the only value satisfying all three is `W` itself — so
    every legal `by_code` entry is a restatement of `score`, and no entry can change any outcome.

    The two obvious alternatives are both worse. Deleting the field forecloses a v1.1 that genuinely
    needs per-code treatment and breaks every plan document that already writes `{}`. Leaving it
    parseable-but-useless ships a field that *looks* like a leniency lever — a reviewer, or an
    organizer under deadline pressure, reads `by_code` and reasonably concludes some failure modes
    can be scored more kindly. A field that looks adjustable but is not is a fail-open invitation,
    so a non-empty `by_code` is refused outright with the reasoning in the message.
    """

    policy: str
    #: `W`, the pre-committed worst value. Always equals the worst end of the metric domain.
    score: float
    #: RESERVED. Always empty through contract set 1.1.0; see the class docstring.
    by_code: Mapping[FailureCode, float]
    clip_real_scores_to_domain: bool

    @classmethod
    def from_mapping(
        cls, obj: Any, metric: MetricSpec, *, path: str = "participant_failure"
    ) -> ParticipantFailurePolicy:
        mapping = _as_object(obj, path)
        reject_unknown_keys(
            mapping, ("policy", "score", "by_code", "clip_real_scores_to_domain"), path=path
        )
        policy = req_enum(mapping, "policy", ("fixed_worst_case",), path=path)
        score = req_float(mapping, "score", path=path)
        if score != metric.worst:
            raise ContractError(
                f"{path}.score={score} must equal the worst end of the metric domain "
                f"({metric.worst}) for direction {metric.direction!r}. R-2: a penalty that sits "
                "inside the domain is better than some attainable real score, which makes "
                "deliberate failure profitable."
            )
        # `by_code` is REQUIRED as a key and REQUIRED to be empty. Frozen rule 0.1 forbids reading
        # a contract field with a default, so "no overrides" is written as `{}`, not omitted — and
        # `{}` is the only legal value so far. See the class docstring for why the field survives
        # at all rather than being deleted.
        raw_overrides = req_mapping(mapping, "by_code", path=path)
        if raw_overrides:
            offered = sorted(str(k) for k in raw_overrides)
            raise ContractError(
                f"{path}.by_code must be empty through contract set 1.1.0; got {offered}. The field is "
                f"RESERVED, not a leniency lever: score must equal W={score} (the worst end of the "
                "metric domain), an override must lie inside that domain, and an override may not "
                "be better than W — so W is the only legal override value and every entry is a "
                "no-op. Per-code treatment needs a new contract version, not a plan that writes "
                "one here and expects it to bite."
            )
        overrides: dict[FailureCode, float] = {}
        return cls(
            policy=policy,
            score=score,
            by_code=overrides,
            clip_real_scores_to_domain=req_bool(mapping, "clip_real_scores_to_domain", path=path),
        )


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """One expanded-roster entry.

    `unit_handle` is the only id ever published, and in a sealed phase it is required to be
    opaque — see `validate_unit_handle`. It is also a directory name, so the character class is
    the one every consumer can carry safely rather than "whatever JSON allows".
    """

    unit_handle: str
    timeout_sec: float | None = None
    resource_profile_id: str | None = None
    grid: Mapping[str, Any] | None = None
    entity_roster: Mapping[str, Any] | None = None
    scoring_params: Mapping[str, Any] | None = None


def _as_object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{path} must be an object, got {type(value).__name__}")
    for key in value:
        if not isinstance(key, str):
            raise ContractError(f"{path} has a non-string key {key!r}")
    return value


def _parse_roster_entry(raw: Any, track: str, phase: str, index: int) -> RosterEntry:
    path = f"roster.expected_units[{index}]"
    entry = _as_object(raw, path)
    allowed = ["unit_handle"]
    if track == "coding":
        allowed += ["timeout_sec", "resource_profile_id"]
    elif track == "forecasting":
        allowed += ["grid"]
    elif track == "analysis":
        allowed += ["entity_roster", "scoring_params"]
    reject_unknown_keys(entry, allowed, path=path)
    handle = validate_unit_handle(
        req_str(entry, "unit_handle", path=path), phase=phase, path=f"{path}.unit_handle"
    )

    timeout = resource_profile = grid = entity_roster = scoring_params = None
    if track == "coding":
        # The global timeout constant is retired: the budget is a per-unit plan field.
        timeout = req_float(entry, "timeout_sec", path=path)
        if timeout <= 0:
            raise ContractError(f"{path}.timeout_sec must be positive")
        resource_profile = req_str(entry, "resource_profile_id", path=path)
    elif track == "forecasting":
        grid = _as_object(req(entry, "grid", path=path), f"{path}.grid")
        reject_unknown_keys(
            grid, ("assets", "horizons", "cell_count", "digest"), path=f"{path}.grid"
        )
        assets = req_list(grid, "assets", path=f"{path}.grid", min_items=1)
        horizons = req_list(grid, "horizons", path=f"{path}.grid", min_items=1)
        cell_count = req_int(grid, "cell_count", path=f"{path}.grid", minimum=1)
        parse_digest(req(grid, "digest", path=f"{path}.grid"), field=f"{path}.grid.digest")
        if cell_count != len(assets) * len(horizons):
            raise ContractError(
                f"{path}.grid.cell_count={cell_count} disagrees with "
                f"{len(assets)}x{len(horizons)}; the scorer validates the participant grid "
                "against C1, so C1 must be internally consistent"
            )
    elif track == "analysis":
        entity_roster = _as_object(req(entry, "entity_roster", path=path), f"{path}.entity_roster")
        reject_unknown_keys(
            entity_roster, ("count", "digest", "entity_ids"), path=f"{path}.entity_roster"
        )
        count = req_int(entity_roster, "count", path=f"{path}.entity_roster", minimum=1)
        parse_digest(
            req(entity_roster, "digest", path=f"{path}.entity_roster"),
            field=f"{path}.entity_roster.digest",
        )
        if "entity_ids" in entity_roster:
            ids = req_list(entity_roster, "entity_ids", path=f"{path}.entity_roster")
            if len(ids) != count:
                raise ContractError(f"{path}.entity_roster.count disagrees with entity_ids")
        scoring_params = _as_object(
            req(entry, "scoring_params", path=path), f"{path}.scoring_params"
        )
        reject_unknown_keys(
            scoring_params,
            (
                "faithfulness_threshold",
                "tau_citation",
                "interval_level",
                "composite_weights",
                "target_type",
            ),
            path=f"{path}.scoring_params",
        )
        req_float(scoring_params, "faithfulness_threshold", path=f"{path}.scoring_params")
        req_float(scoring_params, "tau_citation", path=f"{path}.scoring_params")
        level = req_float(scoring_params, "interval_level", path=f"{path}.scoring_params")
        if not 0.0 < level < 1.0:
            raise ContractError(f"{path}.scoring_params.interval_level must lie in (0, 1)")
        weights = _as_object(
            req(scoring_params, "composite_weights", path=f"{path}.scoring_params"),
            f"{path}.scoring_params.composite_weights",
        )
        # Exactly `accuracy` and `calibration`, summing to 1. An extra weight is not a harmless
        # annotation -- it is a term the scorer will not read, contributed by a document the
        # scorer is required to trust.
        if set(weights) != set(COMPOSITE_WEIGHT_KEYS):
            raise ContractError(
                f"{path}.scoring_params.composite_weights must name exactly "
                f"{list(COMPOSITE_WEIGHT_KEYS)}, got {sorted(weights)}"
            )
        total = 0.0
        for name in COMPOSITE_WEIGHT_KEYS:
            value = req_float(weights, name, path=f"{path}.scoring_params.composite_weights")
            if not 0.0 <= value <= 1.0:
                raise ContractError(
                    f"{path}.scoring_params.composite_weights.{name} must lie in [0, 1]"
                )
            total += value
        if abs(total - 1.0) > 1e-9:
            raise ContractError(
                f"{path}.scoring_params.composite_weights sum to {total!r}, not 1. W is "
                "0*w_accuracy - w_calibration*interval_level and metric.domain.min is validated "
                "against it, so weights that do not sum to 1 move the frozen domain the "
                "leaderboard is clipped into"
            )
        req_enum(scoring_params, "target_type", TARGET_TYPES, path=f"{path}.scoring_params")
    return RosterEntry(
        unit_handle=handle,
        timeout_sec=timeout,
        resource_profile_id=resource_profile,
        grid=grid,
        entity_roster=entity_roster,
        scoring_params=scoring_params,
    )


class EvaluationPlan:
    """A parsed, validated C1. Constructing one is proof it satisfies the frozen invariants."""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = dict(raw)
        path = "plan"
        _as_object(raw, path)
        track = req_enum(raw, "track", TRACKS, path=path)
        reject_unknown_keys(raw, list(_CORE_KEYS) + list(_TRACK_KEYS[track]), path=path)

        self.schema_version = req_str(raw, "schema_version", path=path)
        if self.schema_version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise ContractError(
                f"C1 schema_version {self.schema_version!r} has an unsupported major version; "
                f"this build implements {SCHEMA_VERSION}"
            )
        self.contract_set = req_str(raw, "contract_set", path=path)
        if self.contract_set != CONTRACT_SET:
            raise ContractError(
                f"contract_set {self.contract_set!r} != {CONTRACT_SET!r}; consumers implement one "
                "frozen set and reject the rest"
            )
        self.competition_id = req_str(raw, "competition_id", path=path)
        self.track = track
        self.phase = req_enum(raw, "phase", PHASES, path=path)
        self.plan_id = req_str(raw, "plan_id", path=path)
        self.metric = MetricSpec.from_mapping(req(raw, "metric", path=path))
        self.participant_failure = ParticipantFailurePolicy.from_mapping(
            req(raw, "participant_failure", path=path), self.metric
        )

        organizer = _as_object(req(raw, "organizer_failure", path=path), "organizer_failure")
        reject_unknown_keys(organizer, ("policy",), path="organizer_failure")
        self.organizer_failure_policy = req_enum(
            organizer, "policy", ("abort_whole_evaluation",), path="organizer_failure"
        )

        scorer = _as_object(req(raw, "scorer", path=path), "scorer")
        reject_unknown_keys(scorer, ("package", "digest", "interface_version"), path="scorer")
        self.scorer_package = req_str(scorer, "package", path="scorer")
        self.scorer_digest = parse_digest(
            req(scorer, "digest", path="scorer"), field="scorer.digest"
        )
        self.scorer_interface_version = req_str(scorer, "interface_version", path="scorer")

        evidence = _as_object(req(raw, "required_evidence", path=path), "required_evidence")
        reject_unknown_keys(evidence, ("c2", "c3", "telemetry", "judge"), path="required_evidence")
        self.required_evidence = {
            name: req_bool(evidence, name, path="required_evidence")
            for name in ("c2", "c3", "telemetry", "judge")
        }

        self._parse_roster(req(raw, "roster", path=path))
        self._parse_track_extensions(raw)

        self.signature = SignatureEnvelope.from_mapping(req(raw, "signature", path=path))
        computed = digest_json({k: v for k, v in self._raw.items() if k != "signature"})
        if computed != self.signature.payload_digest:
            raise ContractError(
                f"the plan's signature.payload_digest ({self.signature.payload_digest}) does not "
                f"match the canonical plan body ({computed}); the envelope signs a different "
                "object than the one you are holding"
            )
        self.plan_digest = computed

    # ------------------------------------------------------------------ parsing helpers
    def _parse_roster(self, raw_roster: Any) -> None:
        roster = _as_object(raw_roster, "roster")
        reject_unknown_keys(roster, ("count", "digest", "expected_units"), path="roster")
        self.roster_count = req_int(roster, "count", path="roster", minimum=1)
        self.roster_digest = parse_digest(
            req(roster, "digest", path="roster"), field="roster.digest"
        )
        self._expected: tuple[RosterEntry, ...] | None = None
        if "expected_units" not in roster:
            return  # the public commitment: counts, digests and policy only
        entries = req_list(roster, "expected_units", path="roster", min_items=1)
        parsed = tuple(
            _parse_roster_entry(entry, self.track, self.phase, i) for i, entry in enumerate(entries)
        )
        handles = [e.unit_handle for e in parsed]
        if len(set(handles)) != len(handles):
            raise ContractError("roster.expected_units contains a duplicate unit_handle")
        if self.phase in SEALED_PHASES and len({len(h) for h in handles}) > 1:
            # Length is the one channel the hex grammar leaves open. A roster holding both
            # `u-3f2a91c4` and `u-3f2a91c4bb07de56` says that those two units were minted by
            # different runs of the derivation, which is a fact about the roster the seal did not
            # intend to publish. Uniform width closes it for the cost of one comparison.
            raise OrganizerFault(
                "a sealed-phase roster must use one handle WIDTH for every unit; this one mixes "
                f"{sorted({len(h) for h in handles})}. Handle length is the only content the "
                "opaque grammar cannot strip, and a mixed roster leaks that its units were minted "
                "differently."
            )
        if len(parsed) != self.roster_count:
            raise ContractError(
                f"roster.count={self.roster_count} but expected_units holds {len(parsed)} entries"
            )
        computed = compute_roster_digest(handles)
        if computed != self.roster_digest:
            raise ContractError(
                f"roster.digest {self.roster_digest} does not match the ordered handle array "
                f"({computed}). The digest is JCS over the ORDERED [unit_handle] array; a "
                "consumer that sorts first will disagree here."
            )
        self._expected = parsed

    def _parse_track_extensions(self, raw: Mapping[str, Any]) -> None:
        self.attempts_per_unit: int | None = None
        self.k_values: tuple[int, ...] | None = None
        self.normalization: Mapping[str, Any] | None = None
        self.repeats: int | None = None
        self.warmup_discarded: int | None = None
        self.every_repeat_must_pass: bool | None = None

        if self.track == "coding":
            self.attempts_per_unit = req_int(raw, "attempts_per_unit", path="plan", minimum=1)
            values = req_list(raw, "k_values", path="plan", min_items=1)
            ks: list[int] = []
            for index, value in enumerate(values):
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ContractError(f"k_values[{index}] must be a positive integer")
                ks.append(value)
            if ks != sorted(set(ks)):
                raise ContractError("k_values must be strictly ascending and unique")
            if max(ks) > self.attempts_per_unit:
                raise ContractError(
                    f"k_values max {max(ks)} exceeds attempts_per_unit {self.attempts_per_unit}; "
                    "n is fixed by the plan and is never derived from observed attempts"
                )
            self.k_values = tuple(ks)
        elif self.track == "forecasting":
            normalization = _as_object(req(raw, "normalization", path="plan"), "normalization")
            reject_unknown_keys(
                normalization, ("mode", "ref_scale_commitment"), path="normalization"
            )
            req_enum(normalization, "mode", NORMALIZATION_MODES, path="normalization")
            parse_digest(
                req(normalization, "ref_scale_commitment", path="normalization"),
                field="normalization.ref_scale_commitment",
            )
            self.normalization = dict(normalization)
        elif self.track == "simulation":
            aggregation = _as_object(req(raw, "aggregation", path="plan"), "aggregation")
            reject_unknown_keys(aggregation, ("statistic", "unit_scope"), path="aggregation")
            statistic = req_enum(
                aggregation, "statistic", AGGREGATION_STATISTICS, path="aggregation"
            )
            unit_scope = req_enum(aggregation, "unit_scope", UNIT_SCOPES, path="aggregation")
            if (statistic, unit_scope) != (self.metric.statistic, self.metric.unit_scope):
                raise ContractError(
                    "Track 3's aggregation block disagrees with metric: "
                    f"({statistic}, {unit_scope}) vs "
                    f"({self.metric.statistic}, {self.metric.unit_scope}). Both the Hub driver and "
                    "the private final scorer read these; a disagreement means two aggregates."
                )
            self.repeats = req_int(raw, "repeats", path="plan", minimum=1)
            self.warmup_discarded = req_int(raw, "warmup_discarded", path="plan", minimum=0)
            if self.warmup_discarded >= self.repeats:
                raise ContractError("warmup_discarded must leave at least one measured repeat")
            self.every_repeat_must_pass = req_bool(raw, "every_repeat_must_pass", path="plan")

    # ------------------------------------------------------------------ public surface
    @property
    def is_public_commitment(self) -> bool:
        """True when this is the bundle-visible form that carries no unit identities."""
        return self._expected is None

    @property
    def expected_units(self) -> tuple[RosterEntry, ...]:
        """The expanded roster. Raises on a public commitment — never returns an empty tuple.

        A caller that receives `()` here would compute a mean over zero units, which is A01.
        """
        if self._expected is None:
            raise ContractError(
                "this C1 is the PUBLIC COMMITMENT: it carries counts and digests only, and unit "
                "identities are resolver/scorer-only. Load the expanded plan instead."
            )
        return self._expected

    @property
    def expected_handles(self) -> tuple[str, ...]:
        return tuple(e.unit_handle for e in self.expected_units)

    @property
    def denominator(self) -> int:
        """The fixed denominator: `T` per unit, or `T x n` per (unit, attempt slot)."""
        if self.metric.unit_scope == "per_unit_attempt":
            if self.attempts_per_unit is None:
                raise ContractError(
                    "unit_scope=per_unit_attempt requires attempts_per_unit, which only the "
                    "coding plan declares"
                )
            return self.roster_count * self.attempts_per_unit
        return self.roster_count

    @property
    def rankability_objections(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.participant_failure.clip_real_scores_to_domain:
            reasons.append("clip_real_scores_to_domain is false")
        if self.track == "simulation" and self.every_repeat_must_pass is False:
            reasons.append("every_repeat_must_pass is false")
        return tuple(reasons)

    @property
    def is_rankable(self) -> bool:
        return not self.rankability_objections

    def require_rankable(self) -> None:
        if self.rankability_objections:
            raise ContractError(
                "this plan is not rankable: " + "; ".join(self.rankability_objections)
            )

    def clip(self, score: float) -> float:
        """Clamp a real per-unit score into the committed domain (R-2, the second half).

        A non-finite participant score is a `ParticipantFailure`, per the frozen C4 rule that
        nonfinite values in participant *data* are the participant's problem while nonfinite
        intermediate *statistics* are the organizer's.
        """
        if not self.participant_failure.clip_real_scores_to_domain:
            raise ContractError(
                "this plan sets clip_real_scores_to_domain=false, so it is not rankable and "
                "clip() has no defined meaning. Refusing rather than clamping silently."
            )
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ParticipantFailure(f"a per-unit score must be a number, got {score!r}")
        value = float(score)
        if math.isnan(value) or math.isinf(value):
            raise ParticipantFailure(
                f"non-finite participant score {score!r}; NaN and infinity never reach aggregation"
            )
        return min(max(value, self.metric.domain_min), self.metric.domain_max)

    def failure_score_for(self, code: FailureCode | str) -> float:
        """The committed value `W` a unit contributes when it fails with `code`.

        Through contract set 1.1.0 this is `W` for every code: `by_code` is RESERVED and parsed
        empty. The lookup stays because the *call sites* are what a later version would otherwise
        have to find and change — the consumer already asks "what does this code score", which is
        the right question whether or not the answer currently varies.
        """
        parsed = parse_failure_code(code)
        row = failure_code_registry()[parsed]
        if not row.scored:
            raise ContractError(
                f"{parsed.value!r} is registered as unscored, so it cannot consume a roster slot. "
                "Every expected unit must resolve to a C4 state (A01)."
            )
        return self.participant_failure.by_code.get(parsed, self.participant_failure.score)

    def verify_roster(self, observed: Sequence[str]) -> None:
        """Check an observed roster against the commitment. A mismatch is an ORGANIZER fault.

        A reference unit that failed to mount must never shrink the denominator; it must stop the
        evaluation. That is why this raises `OrganizerFault` and not `ParticipantFailure`.
        """
        handles = list(observed)
        for handle in handles:
            if not isinstance(handle, str) or not handle:
                raise OrganizerFault("observed roster contains a non-string unit handle")
        if len(set(handles)) != len(handles):
            raise OrganizerFault("observed roster contains duplicate unit handles")
        if len(handles) != self.roster_count:
            raise OrganizerFault(
                f"observed {len(handles)} units, the signed plan commits to {self.roster_count}. "
                "Refusing to score a shrunken roster."
            )
        observed_digest = compute_roster_digest(handles)
        if observed_digest == self.roster_digest:
            return
        if not self.is_public_commitment:
            expected = set(self.expected_handles)
            missing = sorted(expected - set(handles))
            extra = sorted(set(handles) - expected)
            if missing or extra:
                raise OrganizerFault(
                    f"observed roster does not match the plan: missing={missing} extra={extra}"
                )
            raise OrganizerFault(
                "observed roster holds the committed units in a different ORDER; roster.digest is "
                "computed over the ordered array, so the order is part of the commitment"
            )
        raise OrganizerFault(
            f"observed roster digest {observed_digest} != committed {self.roster_digest}"
        )

    def verify_signature(self, trust_store: TrustStore, **kwargs: Any) -> VerificationResult:
        """Verify the plan's envelope. An empty trust store fails closed (frozen rule 0.5)."""
        payload = {k: v for k, v in self._raw.items() if k != "signature"}
        return verify_signed(payload, self.signature, trust_store, **kwargs)

    def public_commitment_mapping(self) -> dict[str, Any]:
        """The bundle-visible projection: the same plan with `roster.expected_units` removed.

        The signature is dropped as well, because it signs the expanded body. The public
        commitment is a separately signed artifact; re-sign the returned object before shipping it.
        """
        out = {k: v for k, v in self._raw.items() if k != "signature"}
        roster = dict(out["roster"])
        roster.pop("expected_units", None)
        out["roster"] = roster
        return out

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> EvaluationPlan:
        return cls(raw)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        form = "public" if self.is_public_commitment else "expanded"
        return (
            f"<EvaluationPlan {self.plan_id!r} {self.track}/{self.phase} {form} "
            f"units={self.roster_count} W={self.participant_failure.score}>"
        )
