"""C2 — the trusted run record, and the rankable/failed distinction that kept being misread.

## Executive summary (read this first)

C2 is what the *organizer's* infrastructure observed while a participant container ran. It exists
because scoring previously read exactly two directories and no authenticated runtime fact,
so a unit whose container never launched was indistinguishable from a unit the participant
chose not to answer.

**The single most misread part of the draft, now structural:** `rankability` replaces the old
`rankable` boolean and describes the *trusted execution profile*, not whether participant code
succeeded. An ordinary participant timeout under a valid production profile is
`rankability.state = "rankable"` **and** `participant_outcome = "failure"`: it consumes the C1
penalty and stays in the denominator. Those are two orthogonal axes and this module refuses to
collapse them.

Other frozen rules encoded here:

* **Fault attribution reads only channels the participant cannot write** — the daemon's
  `State.Status`/`State.Error` and `docker create` stderr, which precedes any participant process.
  Never the exit code alone, never container stderr, never a `docker info` probe.
  `derive_participant_outcome` is the helper; a record whose declared outcome disagrees with it
  cannot be constructed.
* **`leakage` is verdict-only** (R-8). The key set is exact, so a producer physically cannot attach
  the matched canary token to a record: an extra key is a parse error, not an ignored field.
* **GPUs are named by UUID, never by index** (R-5). A bare `"0"` in the applied GPU slot is
  refused.
* **Timing is host-measured.** `elapsed_sec` is cross-checked against `ended_at - started_at`, so a
  participant-reported figure smuggled into the field does not survive parsing.
* **A participant file can never become C2.** This type carries no filesystem loader that reads
  from a participant-writable root; C2 exists only as a Runner-signed artifact in the organizer
  control root.
* **The attestation payload is frozen** (see `attestation_payload`): the signature covers the JCS
  digest of the whole record minus the `attestation` block. Before that was written down, no module
  computed the digest and no test checked it, which made `payload_digest` decorative — a field an
  auditor would read as evidence and a producer could fill with anything.
* **`oom_killed` comes from the daemon's `State.OOMKilled`**, a channel the participant cannot
  write. Without it an out-of-memory kill is byte-indistinguishable from an ordinary nonzero exit,
  so the C4 code `resource_oom` could not be emitted truthfully by anybody.
* **`operator_override` is a first-class applied-source** and is never rankable. The one downgrade
  this system performs — `QFBENCH_ALLOW_NO_EVAL_NETWORK` running a `restricted` card offline — was
  previously recorded as `daemon_default`, which is false: no daemon default was consulted, an
  operator made a choice. A record that lies to an auditor is worse than one that admits a gap.

### New in C2 1.1.0 — two facts that were previously unsayable

Both were requested by the Runner, and both have the same shape: the contract could express the
*good* outcome and not the *honest* one, so a producer facing reality had to choose between lying
and withholding evidence.

* **`observation_contradicted`** joins `rankability.unmet_controls`. A Runner that checks the
  Hub's unsigned `observation` against host facts and finds them disagreeing can now sign a record
  saying exactly that. Parsing enforces the pairing: `observation_verdict = "contradicted"`
  without the control does not parse, so the contradiction cannot be recorded and shrugged off.
* **`applied.gpu.selector`** — `uuid`, `index`, `all`, or `null` for "no device applied" — records
  HOW the device was chosen. C2 1.0.0 refused an index-looking applied value outright, which meant
  a Runner watching the daemon apply a device by index had to stay silent, and silence was
  byte-identical to a CPU-only unit. `index` and `all` each force `gpu_device_unpinned`, so R-5 is
  still enforced; what changed is that the violation is now *recorded* instead of *unrepresentable*.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ._time import parse_rfc3339
from .digest import digest_json, parse_digest
from .errors import (
    ContractError,
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
from .signing import (
    SignatureEnvelope,
    SignatureUnverifiable,
    TrustStore,
    VerificationResult,
    verify_signed,
)

__all__ = [
    "APPLIED_SOURCES",
    "ATTESTATION_SIGNATURE_KEY",
    "GPU_SELECTORS",
    "LIFECYCLE_PHASES",
    "NON_REPRODUCIBLE_GPU_SELECTORS",
    "OPERATOR_OVERRIDE_CONTROLS",
    "RANKABILITY_STATES",
    "UNMET_CONTROLS",
    "AppliedControl",
    "Attestation",
    "Lifecycle",
    "Rankability",
    "RunRecord",
    "attestation_payload",
    "derive_participant_outcome",
    "derive_unmet_controls",
    "telemetry_admissible_for_timing",
]

SCHEMA_VERSION = "1.1.0"
LIFECYCLE_PHASES = ("created", "started", "exited", "killed")
RANKABILITY_STATES = ("rankable", "unrankable", "organizer_failure")

#: How the applied value came to be what it is.
#:
#: * `pinned`            — the organizer asked for it and got it.
#: * `daemon_default`    — nobody asked; the container daemon's own default applied.
#: * `unset`             — the control was never established at all.
#: * `operator_override` — an OPERATOR deliberately applied something other than the requested
#:   value. `QFBENCH_ALLOW_NO_EVAL_NETWORK` running a `restricted` card offline is the one live
#:   instance. It is not a daemon default and recording it as one is a false statement in a signed
#:   artifact; it is not `unset` either, because somebody chose it and that person is accountable.
#:   Every `operator_override` contributes an unmet control (`OPERATOR_OVERRIDE_CONTROLS`), so the
#:   run cannot be rankable by accident.
APPLIED_SOURCES = ("pinned", "daemon_default", "unset", "operator_override")
PARTICIPANT_OUTCOMES = ("success", "failure")
CANARY_VERDICTS = ("clean", "hit")
WORKER_LAYERS = ("worker", "ingestion", "scoring", "unit")
ATTESTATION_VERDICTS = ("confirmed", "contradicted")
ATTESTATION_REASONS = (
    "host_facts_match",
    "host_facts_mismatch",
    "observation_absent",
    "observation_malformed",
    "clock_skew",
)

#: The closed set of trusted controls a run may fail to establish. Frozen in C2.
#:
#: `observation_contradicted` is new in C2 1.1.0, at the Runner's request. Before it, a Runner that
#: checked the Hub's unsigned `observation` against host facts and found them *disagreeing* had no
#: way to say so and still sign: `attestation.observation_verdict = "contradicted"` was expressible
#: but contributed no unmet control, so the record could be signed and still claim
#: `state: "rankable"`. The only honest options left to the producer were to refuse to sign — which
#: destroys the evidence that the contradiction happened — or to write `confirmed`, which is a lie
#: in a signed artifact. Now the contradiction is a first-class, signed, unrankable fact.
UNMET_CONTROLS = (
    "unit_runtime_unpinned",
    "gpu_device_unpinned",
    "tier_unenforced",
    "image_digest_unresolved",
    "egress_unverified",
    "telemetry_absent",
    "cleanup_unconfirmed",
    "hardware_mismatch",
    "signature_invalid",
    "observation_contradicted",
)

#: How the GPU device that was actually applied came to be chosen. New in C2 1.1.0.
#:
#: R-5 freezes the *policy* — the device is named by UUID, never by index, and `all` survives only
#: in a named non-production profile stamping `rankable=false`. What C2 1.0.0 could not express is
#: the *observation*: `_parse_applied` refused an index-looking applied value outright, so a Runner
#: that watched the daemon apply a device by index had no way to record what it saw. Silence and
#: "no GPU was applied" then became the same bytes, and they are different facts — one is a run
#: whose device pinning is not reproducible across hosts, the other is a CPU-only unit.
#:
#: `null` (not a member of this enum) is the fourth state: no device was applied at all. It is
#: required to be written explicitly, and it is required to agree with `applied.gpu.applied`.
GPU_SELECTORS = ("uuid", "index", "all")

#: Selectors that name a device in a way another host cannot reproduce. Each contributes
#: `gpu_device_unpinned`, so recording the truth costs the run its rankability — which is the only
#: arrangement under which the honest label is not the expensive one.
NON_REPRODUCIBLE_GPU_SELECTORS = ("index", "all")

#: The control each `applied` slot fails to establish when its source is `operator_override`.
#:
#: This mapping is what makes the new source safe to add. An operator downgrade is a *downgrade*:
#: it must cost the run its rankability in exactly the way an unpinned control does, or the honest
#: label becomes the cheap one and producers go back to writing `daemon_default`.
OPERATOR_OVERRIDE_CONTROLS: Mapping[str, str] = {
    "runtime": "unit_runtime_unpinned",
    "gpu": "gpu_device_unpinned",
    "network": "egress_unverified",
    "limits": "tier_unenforced",
}

#: Keys the frozen attestation payload excludes. Exactly one: the block carrying the signature,
#: which cannot contain a digest of itself.
#: The ONE thing an attestation payload cannot cover: its own signature. Everything else in the
#: record -- including the rest of the `attestation` block -- is bound. See `attestation_payload`.
ATTESTATION_SIGNATURE_KEY = "signature"

#: NVIDIA GPU UUIDs. A device *index* is not reproducible across hosts and is refused (R-5).
_GPU_UUID_RE = re.compile(r"^GPU-[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
_TIMING_TOLERANCE_SEC = 2.0


def _as_object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{path} must be an object, got {type(value).__name__}")
    return value


@dataclass(frozen=True, slots=True)
class AppliedControl:
    """`{requested, applied, source}` — requested-vs-applied is STRUCTURAL, not a naming habit.

    A downgraded run must not be byte-indistinguishable from a genuine one, which is only possible
    if both values are carried in one object with the provenance of the applied value beside them.
    """

    requested: Any
    applied: Any
    source: str

    @classmethod
    def from_mapping(cls, obj: Any, *, path: str) -> AppliedControl:
        mapping = _as_object(obj, path)
        reject_unknown_keys(mapping, ("requested", "applied", "source"), path=path)
        return cls(
            requested=req(mapping, "requested", path=path, allow_null=True),
            applied=req(mapping, "applied", path=path, allow_null=True),
            source=req_enum(mapping, "source", APPLIED_SOURCES, path=path),
        )

    @property
    def honoured(self) -> bool:
        return self.source == "pinned" and self.requested == self.applied


@dataclass(frozen=True, slots=True)
class Lifecycle:
    """Daemon-observed facts about one container's life. Nothing here is participant-writable.

    `oom_killed` is the daemon's `State.OOMKilled`. It is a separate field rather than an inference
    from `exit_code == 137` because 137 is also what an ordinary `SIGKILL` produces, and a
    participant process can exit 137 on purpose. Without the daemon flag an out-of-memory kill and
    a nonzero exit are the same bytes, and the C4 code `resource_oom` cannot be emitted truthfully
    by anybody — which is why it was, in practice, never emitted at all.
    """

    phase_reached: str
    daemon_status: str
    daemon_error: str
    exit_code: int | None
    signal: str | None
    timed_out: bool
    oom_killed: bool
    cleanup_confirmed: bool

    @classmethod
    def from_mapping(cls, obj: Any, *, path: str = "lifecycle") -> Lifecycle:
        mapping = _as_object(obj, path)
        reject_unknown_keys(
            mapping,
            (
                "phase_reached",
                "daemon_status",
                "daemon_error",
                "exit_code",
                "signal",
                "timed_out",
                "oom_killed",
                "cleanup_confirmed",
            ),
            path=path,
        )
        exit_code = req(mapping, "exit_code", path=path, allow_null=True)
        if exit_code is not None and (
            isinstance(exit_code, bool) or not isinstance(exit_code, int)
        ):
            raise ContractError(f"{path}.exit_code must be an integer or null")
        signal = req(mapping, "signal", path=path, allow_null=True)
        if signal is not None and not isinstance(signal, str):
            raise ContractError(f"{path}.signal must be a string or null")
        return cls(
            phase_reached=req_enum(mapping, "phase_reached", LIFECYCLE_PHASES, path=path),
            daemon_status=req_str(mapping, "daemon_status", path=path),
            daemon_error=req_str(mapping, "daemon_error", path=path, allow_empty=True),
            exit_code=exit_code,
            signal=signal,
            timed_out=req_bool(mapping, "timed_out", path=path),
            oom_killed=req_bool(mapping, "oom_killed", path=path),
            cleanup_confirmed=req_bool(mapping, "cleanup_confirmed", path=path),
        )


def derive_participant_outcome(lifecycle: Lifecycle) -> str:
    """Derive `success`/`failure` from daemon facts only.

    Reads `phase_reached`, `daemon_status`, `timed_out` and `oom_killed` — channels the participant
    cannot write — and uses `exit_code` only *after* the daemon has confirmed a clean exit. The exit
    code alone is never an attribution: `ingest.py` learned that the hard way, because a container's
    stderr is attached to the same stream the daemon writes to.
    """
    if lifecycle.oom_killed:
        # An OOM kill is a failure even if the daemon also reports a zero exit code. The kernel
        # ended the process; whatever the container wrote on the way out is not a completed run.
        return "failure"
    if lifecycle.timed_out:
        return "failure"
    if lifecycle.phase_reached != "exited" or lifecycle.daemon_status != "exited":
        return "failure"
    if lifecycle.exit_code != 0:
        return "failure"
    return "success"


@dataclass(frozen=True, slots=True)
class Rankability:
    """The trusted execution profile. `state == rankable` iff no control is unmet."""

    state: str
    unmet_controls: tuple[str, ...]

    def __post_init__(self) -> None:
        unknown = sorted(set(self.unmet_controls) - set(UNMET_CONTROLS))
        if unknown:
            raise ContractError(
                f"unknown unmet control(s) {unknown}; the set is closed: {list(UNMET_CONTROLS)}"
            )
        if len(set(self.unmet_controls)) != len(self.unmet_controls):
            raise ContractError("unmet_controls contains a duplicate")
        if self.state == "rankable" and self.unmet_controls:
            raise ContractError(
                f"state='rankable' with unmet controls {list(self.unmet_controls)}. A run with an "
                "unestablished control is not rankable; this is exactly the fail-open shape the "
                "contract set removes."
            )
        if self.state != "rankable" and not self.unmet_controls:
            raise ContractError(
                f"state={self.state!r} with no unmet_controls: an unrankable run must say which "
                "control it failed to establish"
            )

    @property
    def is_rankable(self) -> bool:
        return self.state == "rankable"

    @classmethod
    def from_mapping(cls, obj: Any, *, path: str = "rankability") -> Rankability:
        mapping = _as_object(obj, path)
        reject_unknown_keys(mapping, ("state", "unmet_controls"), path=path)
        controls = req_list(mapping, "unmet_controls", path=path)
        for index, value in enumerate(controls):
            if not isinstance(value, str):
                raise ContractError(f"{path}.unmet_controls[{index}] must be a string")
        return cls(
            state=req_enum(mapping, "state", RANKABILITY_STATES, path=path),
            unmet_controls=tuple(controls),
        )


@dataclass(frozen=True, slots=True)
class Attestation:
    """The Runner's signed verdict on the Hub's observation.

    `signature.payload_digest` covers the payload frozen by `attestation_payload` — the record
    minus this block. Verify it with `RunRecord.verify_attestation`; there is no other supported
    reading of the digest, and a producer that signs a payload of its own choosing produces a
    record that fails verification rather than one that quietly passes.
    """

    observation_verdict: str
    reason: str
    signature: SignatureEnvelope

    @classmethod
    def from_mapping(cls, obj: Any, *, path: str = "attestation") -> Attestation:
        mapping = _as_object(obj, path)
        reject_unknown_keys(mapping, ("observation_verdict", "reason", "signature"), path=path)
        return cls(
            observation_verdict=req_enum(
                mapping, "observation_verdict", ATTESTATION_VERDICTS, path=path
            ),
            reason=req_enum(mapping, "reason", ATTESTATION_REASONS, path=path),
            signature=SignatureEnvelope.from_mapping(
                req(mapping, "signature", path=path), path=f"{path}.signature"
            ),
        )


def _operator_override_controls(applied: Mapping[str, Any]) -> set[str]:
    """The `applied` slot names an operator overrode. Keys of `OPERATOR_OVERRIDE_CONTROLS`."""
    names: set[str] = set()
    for name in ("runtime", "gpu", "network"):
        if applied[name].source == "operator_override":
            names.add(name)
    if any(control.source == "operator_override" for control in applied["limits"].values()):
        names.add("limits")
    return names


def attestation_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    """The FROZEN payload a C2 attestation signature covers: the record minus `attestation.signature`.

    Frozen because it was previously undefined. `attestation.signature.payload_digest` shipped in
    the contract with no module computing it and no test checking it, so an auditor reading the
    field saw a cryptographic commitment where there was only a well-formed string. A signature
    over an unspecified payload is decorative, and a decorative signature is worse than none: it
    invites exactly the reliance it cannot support.

    The excluded set is exactly one field. An earlier version of this contract excluded the whole
    `attestation` block, which left `observation_verdict` and `reason` OUTSIDE the signature --
    so anyone able to edit the JSON could flip a Runner verdict of `contradicted` to `confirmed`
    and the signature would still verify. That is the one claim the attestation exists to make, so
    leaving it unbound defeated the mechanism. Now the block is bound and only the signature itself
    is removed, for the single unavoidable reason that no structure can contain a digest of itself.

    Bound, therefore: every binding, the lifecycle, the applied controls, the timing, the telemetry,
    the leakage verdict, the Hub's unsigned `observation`, AND the Runner's `observation_verdict`
    and `reason`. Mutating any of them invalidates the signature.
    """
    if not isinstance(record, Mapping):
        raise ContractError("an attestation payload is computed over a JSON object")
    payload = dict(record)
    attestation = payload.get("attestation")
    if isinstance(attestation, Mapping):
        payload["attestation"] = {
            k: v for k, v in attestation.items() if k != ATTESTATION_SIGNATURE_KEY
        }
    return payload


_LEAKAGE_KEYS = ("canary_verdict", "hit_count", "scanned_file_count", "scanned_bytes")
_TELEMETRY_KEYS = (
    "sampling_interval_ms",
    "samples_taken",
    "samples_expected",
    "samples_missed",
    "coverage_fraction",
    "gpu_uuid",
    "participant_cgroup_id",
    "exclusive",
    "contender_process_count",
    "throttled",
)
_TOP_KEYS = (
    "schema_version",
    "run_id",
    "unit_handle",
    "attempt_slot_index",
    "bindings",
    "image",
    "lifecycle",
    "participant_outcome",
    "rankability",
    "timing",
    "applied",
    "telemetry",
    "output_row_counts",
    "repeats",
    "leakage",
    "worker_layer_view",
    "observation",
    "attestation",
)


@dataclass(slots=True)
class RunRecord:
    """A parsed, validated C2."""

    schema_version: str
    run_id: str
    unit_handle: str
    attempt_slot_index: int
    bindings: Mapping[str, str]
    image: Mapping[str, str]
    lifecycle: Lifecycle
    participant_outcome: str
    rankability: Rankability
    timing: Mapping[str, float | str]
    applied: Mapping[str, Any]
    telemetry: Mapping[str, Any] | None
    output_row_counts: Mapping[str, int]
    repeats: tuple[Mapping[str, Any], ...]
    leakage: Mapping[str, Any]
    worker_layer_view: tuple[Mapping[str, Any], ...]
    observation: Mapping[str, Any]
    attestation: Attestation | None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ parsing
    @classmethod
    def from_mapping(cls, raw: Any) -> RunRecord:
        _as_object(raw, "run_record")
        reject_unknown_keys(raw, _TOP_KEYS, path="run_record")
        schema_version = req_str(raw, "schema_version", path="run_record")
        if schema_version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise ContractError(f"unsupported C2 schema_version {schema_version!r}")

        bindings_raw = req_mapping(raw, "bindings", path="run_record")
        reject_unknown_keys(
            bindings_raw,
            ("plan_digest", "descriptor_digest", "c7_instance_digest", "sanitized_tree_digest"),
            path="bindings",
        )
        bindings = {
            name: parse_digest(req(bindings_raw, name, path="bindings"), field=f"bindings.{name}")
            for name in (
                "plan_digest",
                "descriptor_digest",
                "c7_instance_digest",
                "sanitized_tree_digest",
            )
        }

        image_raw = req_mapping(raw, "image", path="run_record")
        reject_unknown_keys(
            image_raw, ("requested", "resolved_digest", "interface_label"), path="image"
        )
        image = {
            "requested": req_str(image_raw, "requested", path="image"),
            # `image_digest()` used to fail OPEN to the empty string. `parse_digest`
            # refuses "" outright, so an unresolved digest can no longer be recorded as resolved.
            "resolved_digest": parse_digest(
                req(image_raw, "resolved_digest", path="image"), field="image.resolved_digest"
            ),
            "interface_label": req_str(image_raw, "interface_label", path="image"),
        }

        lifecycle = Lifecycle.from_mapping(req(raw, "lifecycle", path="run_record"))
        outcome = req_enum(raw, "participant_outcome", PARTICIPANT_OUTCOMES, path="run_record")
        derived = derive_participant_outcome(lifecycle)
        if outcome != derived:
            raise ContractError(
                f"participant_outcome={outcome!r} but the daemon facts derive {derived!r} "
                f"(phase_reached={lifecycle.phase_reached}, daemon_status="
                f"{lifecycle.daemon_status}, exit_code={lifecycle.exit_code}, "
                f"timed_out={lifecycle.timed_out}, oom_killed={lifecycle.oom_killed}). The "
                "outcome is derived from channels the "
                "participant cannot write, never asserted independently."
            )
        rankability = Rankability.from_mapping(req(raw, "rankability", path="run_record"))

        timing_raw = req_mapping(raw, "timing", path="run_record")
        reject_unknown_keys(
            timing_raw,
            ("started_at", "ended_at", "elapsed_sec", "applied_timeout_sec"),
            path="timing",
        )
        started = parse_rfc3339(
            req(timing_raw, "started_at", path="timing"), field="timing.started_at"
        )
        ended = parse_rfc3339(req(timing_raw, "ended_at", path="timing"), field="timing.ended_at")
        elapsed = req_float(timing_raw, "elapsed_sec", path="timing")
        applied_timeout = req_float(timing_raw, "applied_timeout_sec", path="timing")
        if ended < started:
            raise ContractError("timing.ended_at precedes timing.started_at")
        if elapsed < 0 or applied_timeout <= 0:
            raise ContractError("timing.elapsed_sec must be >= 0 and applied_timeout_sec > 0")
        wall = (ended - started).total_seconds()
        if abs(wall - elapsed) > _TIMING_TOLERANCE_SEC:
            raise ContractError(
                f"timing.elapsed_sec={elapsed} disagrees with ended_at-started_at={wall:.3f} by "
                f"more than {_TIMING_TOLERANCE_SEC}s. Timing is HOST-measured; a participant-"
                "reported figure does not survive this check."
            )
        timing = {
            "started_at": timing_raw["started_at"],
            "ended_at": timing_raw["ended_at"],
            "elapsed_sec": elapsed,
            "applied_timeout_sec": applied_timeout,
        }

        applied = cls._parse_applied(req(raw, "applied", path="run_record"))
        overridden = _operator_override_controls(applied)
        if overridden and rankability.is_rankable:
            raise ContractError(
                f"applied controls {sorted(overridden)} carry source='operator_override' but the "
                f"record declares state='rankable'. An operator downgrade must cost the run its "
                f"rankability — declare the unmet control(s) "
                f"{sorted(OPERATOR_OVERRIDE_CONTROLS[name] for name in overridden)}. Otherwise the "
                "honest label is cheaper than the false one and producers go back to writing "
                "'daemon_default'."
            )
        missing = sorted(
            control
            for name in overridden
            if (control := OPERATOR_OVERRIDE_CONTROLS[name]) not in rankability.unmet_controls
        )
        if missing:
            raise ContractError(
                f"operator_override on {sorted(overridden)} without the matching unmet control(s) "
                f"{missing}. The declared set must be a superset of the derivable one."
            )
        telemetry = cls._parse_telemetry(req(raw, "telemetry", path="run_record", allow_null=True))

        counts_raw = req_mapping(raw, "output_row_counts", path="run_record")
        counts: dict[str, int] = {}
        for name in counts_raw:
            value = counts_raw[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractError(f"output_row_counts[{name!r}] must be a non-negative integer")
            counts[name] = value

        repeats = tuple(
            cls._parse_repeat(entry, index)
            for index, entry in enumerate(req_list(raw, "repeats", path="run_record"))
        )
        leakage = cls._parse_leakage(req(raw, "leakage", path="run_record"))
        layers = tuple(
            cls._parse_layer(entry, index)
            for index, entry in enumerate(req_list(raw, "worker_layer_view", path="run_record"))
        )

        observation = req_mapping(raw, "observation", path="run_record")
        if "signature" in observation:
            raise ContractError(
                "observation is Hub-authored and UNSIGNED; a signature inside it would let an "
                "observation impersonate the Runner's attestation"
            )
        attestation_raw = req(raw, "attestation", path="run_record", allow_null=True)
        attestation = None if attestation_raw is None else Attestation.from_mapping(attestation_raw)
        if attestation is None and rankability.is_rankable:
            raise ContractError(
                "a rankable run record must carry the Runner attestation; without it the record "
                "is Hub-authored observation only"
            )
        if (
            attestation is not None
            and attestation.observation_verdict == "contradicted"
            and ("observation_contradicted" not in rankability.unmet_controls)
        ):
            raise ContractError(
                "attestation.observation_verdict='contradicted' without the "
                "'observation_contradicted' unmet control. The Runner is signing a statement that "
                "the Hub's observation did NOT match host facts; a record that says that and "
                "still claims its controls were established is the fail-open shape this contract "
                "set removes. Declaring the control is what lets the contradiction be SIGNED "
                "rather than forcing the producer to withhold the signature."
            )
        if applied["gpu_selector"] in NON_REPRODUCIBLE_GPU_SELECTORS and (
            "gpu_device_unpinned" not in rankability.unmet_controls
        ):
            raise ContractError(
                f"applied.gpu.selector={applied['gpu_selector']!r} without the "
                "'gpu_device_unpinned' unmet control. R-5: an index is not reproducible across "
                "hosts and 'all' survives only in a non-production profile stamping "
                "rankable=false. The selector exists so the fact is SAYABLE, not so it is free."
            )

        return cls(
            schema_version=schema_version,
            run_id=req_str(raw, "run_id", path="run_record"),
            unit_handle=req_str(raw, "unit_handle", path="run_record"),
            attempt_slot_index=req_int(raw, "attempt_slot_index", path="run_record", minimum=0),
            bindings=bindings,
            image=image,
            lifecycle=lifecycle,
            participant_outcome=outcome,
            rankability=rankability,
            timing=timing,
            applied=applied,
            telemetry=telemetry,
            output_row_counts=counts,
            repeats=repeats,
            leakage=leakage,
            worker_layer_view=layers,
            observation=dict(observation),
            attestation=attestation,
            raw=dict(raw),
        )

    @staticmethod
    def _parse_applied(raw: Any) -> dict[str, Any]:
        mapping = _as_object(raw, "applied")
        reject_unknown_keys(mapping, ("runtime", "gpu", "network", "limits"), path="applied")
        out: dict[str, Any] = {}
        for name in ("runtime", "network"):
            out[name] = AppliedControl.from_mapping(
                req(mapping, name, path="applied"), path=f"applied.{name}"
            )
        gpu_raw = _as_object(req(mapping, "gpu", path="applied"), "applied.gpu")
        reject_unknown_keys(
            gpu_raw, ("requested", "applied", "source", "uuid", "selector"), path="applied.gpu"
        )
        gpu = AppliedControl.from_mapping(
            {k: gpu_raw[k] for k in ("requested", "applied", "source")}, path="applied.gpu"
        )
        uuid = req(gpu_raw, "uuid", path="applied.gpu", allow_null=True)
        if uuid is not None:
            if not isinstance(uuid, str) or not _GPU_UUID_RE.match(uuid):
                raise ContractError(
                    f"applied.gpu.uuid={uuid!r} is not a GPU UUID. R-5: the device is named by "
                    "UUID, never by index; an index is not reproducible across hosts."
                )
        if "selector" not in gpu_raw:
            raise ContractError(
                "applied.gpu.selector is absent. It is REQUIRED from C2 1.1.0: a record must say "
                f"HOW the applied device was chosen ({list(GPU_SELECTORS)}) or state null for "
                "'no device was applied'. Staying silent made those two different facts one set "
                "of bytes. The closed set is run_record.GPU_SELECTORS and this rule is enforced "
                "in run_record.RunRecord._parse_applied."
            )
        selector = gpu_raw["selector"]
        if selector is not None and selector not in GPU_SELECTORS:
            raise ContractError(
                f"applied.gpu.selector={selector!r} is not one of {list(GPU_SELECTORS)} or null; "
                "the enum is closed"
            )
        if (gpu.applied is None) != (selector is None):
            raise ContractError(
                f"applied.gpu.selector={selector!r} disagrees with applied.gpu.applied="
                f"{gpu.applied!r}. selector is null exactly when no device was applied; a device "
                "that was applied must say how it was chosen, and a selector without a device "
                "describes a selection that did not happen."
            )
        if selector == "uuid" and uuid is None:
            raise ContractError(
                "applied.gpu.selector='uuid' with uuid=null: the record claims UUID selection and "
                "then does not name the UUID. R-5 selection is by UUID or it is not by UUID."
            )
        if selector != "index" and isinstance(gpu.applied, str) and gpu.applied.strip().isdigit():
            raise ContractError(
                f"applied.gpu.applied={gpu.applied!r} looks like a device index but "
                f"selector={selector!r}. R-5 forbids index-based selection in a rankable record; "
                "a run that really was index-selected records selector='index' and carries the "
                "'gpu_device_unpinned' unmet control, rather than disguising itself."
            )
        out["gpu"] = gpu
        out["gpu_uuid"] = uuid
        out["gpu_selector"] = selector
        limits_raw = _as_object(req(mapping, "limits", path="applied"), "applied.limits")
        reject_unknown_keys(
            limits_raw, ("cpus", "memory_bytes", "pids", "storage_bytes"), path="applied.limits"
        )
        out["limits"] = {
            name: AppliedControl.from_mapping(
                req(limits_raw, name, path="applied.limits"), path=f"applied.limits.{name}"
            )
            for name in ("cpus", "memory_bytes", "pids", "storage_bytes")
        }
        return out

    @staticmethod
    def _parse_telemetry(raw: Any) -> dict[str, Any] | None:
        if raw is None:
            return None
        mapping = _as_object(raw, "telemetry")
        reject_unknown_keys(mapping, _TELEMETRY_KEYS, path="telemetry")
        taken = req_int(mapping, "samples_taken", path="telemetry", minimum=0)
        expected = req_int(mapping, "samples_expected", path="telemetry", minimum=1)
        missed = req_int(mapping, "samples_missed", path="telemetry", minimum=0)
        coverage = req_float(mapping, "coverage_fraction", path="telemetry")
        if not 0.0 <= coverage <= 1.0:
            raise ContractError("telemetry.coverage_fraction must lie in [0, 1]")
        if taken + missed != expected:
            raise ContractError(
                f"telemetry samples do not reconcile: taken={taken} + missed={missed} != "
                f"expected={expected}"
            )
        gpu_uuid = req(mapping, "gpu_uuid", path="telemetry", allow_null=True)
        if gpu_uuid is not None and not (
            isinstance(gpu_uuid, str) and _GPU_UUID_RE.match(gpu_uuid)
        ):
            raise ContractError(
                "telemetry.gpu_uuid must be a GPU UUID; device-index-only telemetry is "
                "inadmissible for ranked timing"
            )
        return {
            "sampling_interval_ms": req_int(
                mapping, "sampling_interval_ms", path="telemetry", minimum=1
            ),
            "samples_taken": taken,
            "samples_expected": expected,
            "samples_missed": missed,
            "coverage_fraction": coverage,
            "gpu_uuid": gpu_uuid,
            "participant_cgroup_id": req_str(mapping, "participant_cgroup_id", path="telemetry"),
            "exclusive": req_bool(mapping, "exclusive", path="telemetry"),
            "contender_process_count": req_int(
                mapping, "contender_process_count", path="telemetry", minimum=0
            ),
            "throttled": req_bool(mapping, "throttled", path="telemetry"),
        }

    @staticmethod
    def _parse_repeat(raw: Any, index: int) -> dict[str, Any]:
        path = f"repeats[{index}]"
        mapping = _as_object(raw, path)
        reject_unknown_keys(
            mapping,
            ("index", "elapsed_sec", "output_tree_digest", "event_count", "rankability"),
            path=path,
        )
        declared = req_int(mapping, "index", path=path, minimum=0)
        if declared != index:
            raise ContractError(f"{path}.index={declared} is out of order")
        return {
            "index": declared,
            "elapsed_sec": req_float(mapping, "elapsed_sec", path=path),
            "output_tree_digest": parse_digest(
                req(mapping, "output_tree_digest", path=path), field=f"{path}.output_tree_digest"
            ),
            "event_count": req_int(mapping, "event_count", path=path, minimum=0),
            "rankability": Rankability.from_mapping(
                req(mapping, "rankability", path=path), path=f"{path}.rankability"
            ),
        }

    @staticmethod
    def _parse_leakage(raw: Any) -> dict[str, Any]:
        mapping = _as_object(raw, "leakage")
        # R-8 made structural: the key set is EXACT, so a token-bearing field cannot be attached.
        reject_unknown_keys(mapping, _LEAKAGE_KEYS, path="leakage")
        verdict = req_enum(mapping, "canary_verdict", CANARY_VERDICTS, path="leakage")
        hits = req_int(mapping, "hit_count", path="leakage", minimum=0)
        if (verdict == "hit") != (hits > 0):
            raise ContractError(
                f"leakage.canary_verdict={verdict!r} disagrees with hit_count={hits}"
            )
        return {
            "canary_verdict": verdict,
            "hit_count": hits,
            "scanned_file_count": req_int(mapping, "scanned_file_count", path="leakage", minimum=0),
            "scanned_bytes": req_int(mapping, "scanned_bytes", path="leakage", minimum=0),
        }

    @staticmethod
    def _parse_layer(raw: Any, index: int) -> dict[str, Any]:
        path = f"worker_layer_view[{index}]"
        mapping = _as_object(raw, path)
        reject_unknown_keys(
            mapping, ("layer", "runtime", "docker_socket_present", "mount_roots"), path=path
        )
        roots = req_list(mapping, "mount_roots", path=path)
        for i, root in enumerate(roots):
            if not isinstance(root, str) or not root:
                raise ContractError(f"{path}.mount_roots[{i}] must be a non-empty string")
        return {
            "layer": req_enum(mapping, "layer", WORKER_LAYERS, path=path),
            "runtime": req_str(mapping, "runtime", path=path),
            "docker_socket_present": req_bool(mapping, "docker_socket_present", path=path),
            "mount_roots": tuple(roots),
        }

    # ------------------------------------------------------------------ behaviour
    @property
    def is_rankable(self) -> bool:
        """The trusted execution profile only. Says nothing about participant success."""
        return self.rankability.is_rankable

    @property
    def oom_killed(self) -> bool:
        """The daemon's `State.OOMKilled`. The only truthful basis for the C4 `resource_oom` code."""
        return self.lifecycle.oom_killed

    @property
    def gpu_selector(self) -> str | None:
        """How the applied GPU was chosen — `uuid`, `index`, `all`, or `None` for no device."""
        selector: str | None = self.applied["gpu_selector"]
        return selector

    @property
    def observation_contradicted(self) -> bool:
        """True when the Runner signed a verdict that the Hub's observation did not hold."""
        return self.attestation is not None and (
            self.attestation.observation_verdict == "contradicted"
        )

    def attestation_payload(self) -> dict[str, Any]:
        """This record's frozen attestation payload. See the module-level `attestation_payload`."""
        if not self.raw:
            raise ContractError(
                "this RunRecord was constructed in memory rather than parsed, so it has no "
                "document to sign or verify. Attestation is computed over the record as it was "
                "written, never over a reconstruction of it."
            )
        return attestation_payload(self.raw)

    def attestation_payload_digest(self) -> str:
        """`sha256:` over the JCS form of `attestation_payload()` (global rule 0.2)."""
        return digest_json(self.attestation_payload())

    def verify_attestation(
        self,
        trust_store: TrustStore,
        *,
        require_production_trust: bool = True,
        now: datetime | None = None,
        max_age: timedelta | None = None,
    ) -> VerificationResult:
        """Verify the Runner attestation, or raise `SignatureUnverifiable`.

        Checks both halves that were previously unchecked: that `payload_digest` really is the
        digest of the frozen payload, and that the Ed25519 signature over the envelope verifies
        under a configured trust store. A caller treats any failure as the unmet control
        `signature_invalid` — never as "no signature to check" (frozen rule 0.5).
        """
        if self.attestation is None:
            raise SignatureUnverifiable(
                "this record carries no Runner attestation, so there is nothing to verify. An "
                "unattested record is not rankable; it is Hub observation only."
            )
        return verify_signed(
            self.attestation_payload(),
            self.attestation.signature,
            trust_store,
            now=now,
            max_age=max_age,
            require_production_trust=require_production_trust,
        )

    def verify_bindings(self, **expected: str) -> None:
        """Check `plan_digest`, `descriptor_digest`, `c7_instance_digest`, `sanitized_tree_digest`.

        A mismatch is an organizer fault surfaced as a `ContractError`: the record does not belong
        to the evaluation the caller is scoring, and scoring it anyway would attribute one
        submission's evidence to another.
        """
        for name, value in expected.items():
            if name not in self.bindings:
                raise ContractError(f"{name!r} is not a C2 binding")
            if self.bindings[name] != value:
                raise ContractError(
                    f"bindings.{name} is {self.bindings[name]}, caller expected {value}"
                )


def derive_unmet_controls(
    record: RunRecord, *, telemetry_required: bool = False, gpu_required: bool = False
) -> tuple[str, ...]:
    """The unmet controls derivable from the record alone.

    Deliberately partial: `tier_unenforced`, `egress_unverified` and `hardware_mismatch` depend on
    the C7 instance the queue served and are supplied by the caller that holds it. The rule a
    consumer enforces is one-directional — the declared set must be a **superset** of this one.
    A producer may know about a control this function cannot see; it may never know about fewer.

    An `operator_override` on any applied slot always contributes its control from
    `OPERATOR_OVERRIDE_CONTROLS`, including on the GPU slot when `gpu_required` is false: whether
    the card needs a GPU is a question about the *unit*, while an operator having overridden the
    pinning is a fact about the *run*.
    """
    controls: list[str] = []
    runtime = record.applied["runtime"]
    if runtime.source == "unset":
        controls.append("unit_runtime_unpinned")
    gpu = record.applied["gpu"]
    if gpu_required and (gpu.source == "unset" or record.applied["gpu_uuid"] is None):
        controls.append("gpu_device_unpinned")
    if record.applied["gpu_selector"] in NON_REPRODUCIBLE_GPU_SELECTORS and (
        "gpu_device_unpinned" not in controls
    ):
        # Unconditional, exactly like operator_override and for the same reason: whether the CARD
        # needs a GPU is a question about the unit, while "the device that ran was chosen by index"
        # is a fact about the RUN. A non-reproducible selection does not become reproducible
        # because the organizer did not require a GPU.
        controls.append("gpu_device_unpinned")
    for name in sorted(_operator_override_controls(record.applied)):
        control = OPERATOR_OVERRIDE_CONTROLS[name]
        if control not in controls:
            controls.append(control)
    if not record.lifecycle.cleanup_confirmed:
        controls.append("cleanup_unconfirmed")
    if telemetry_required and record.telemetry is None:
        controls.append("telemetry_absent")
    if record.attestation is None:
        controls.append("signature_invalid")
    elif record.attestation.observation_verdict == "contradicted":
        controls.append("observation_contradicted")
    return tuple(controls)


def telemetry_admissible_for_timing(
    record: RunRecord,
    *,
    min_coverage: float = 0.95,
    sampling_interval_ms: int = 50,
    max_consecutive_missed: int = 5,
    observed_consecutive_missed: int | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """Track 3's ranked-timing gate. Returns `(admissible, reasons)`.

    The frozen requirements: `coverage_fraction >= 0.95`, `sampling_interval_ms == 50`, at most 5
    consecutive missed samples, and GPU attribution resolved by **UUID and participant cgroup**.
    Device-index-only telemetry is inadmissible, which `_parse_telemetry` already refuses outright.
    """
    reasons: list[str] = []
    telemetry = record.telemetry
    if telemetry is None:
        return False, ("telemetry_absent",)
    if telemetry["coverage_fraction"] < min_coverage:
        reasons.append(f"coverage_fraction {telemetry['coverage_fraction']} < {min_coverage}")
    if telemetry["sampling_interval_ms"] != sampling_interval_ms:
        reasons.append(
            f"sampling_interval_ms {telemetry['sampling_interval_ms']} != {sampling_interval_ms}"
        )
    if telemetry["gpu_uuid"] is None:
        reasons.append("gpu attribution not resolved by UUID")
    if not telemetry["participant_cgroup_id"]:
        reasons.append("gpu attribution not resolved by participant cgroup")
    if observed_consecutive_missed is not None and (
        observed_consecutive_missed > max_consecutive_missed
    ):
        reasons.append(
            f"{observed_consecutive_missed} consecutive missed samples > {max_consecutive_missed}"
        )
    return (not reasons), tuple(reasons)
