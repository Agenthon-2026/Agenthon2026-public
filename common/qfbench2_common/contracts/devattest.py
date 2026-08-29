"""C2 for the **Development phase**, produced by the Hub attesting its own observation.

## Why this module exists

The frozen topology puts a third program between ingestion and scoring: the Runner helper reads the
Hub's unsigned observation, checks it against host facts it gathered itself, signs it, and files C2
in `_control/run_records/`. `score.py` requires that file for every unit on the C1 roster and treats
its absence as an organizer fault.

**CodaBench has no third program slot.** A competition bundle names an ingestion program and a
scoring program, and the platform runs exactly those two. The Runner helper
(`runner.attest.produce_run_record`) is a library with no production caller
and no entry point, and it could not be given one from inside either stage: it builds C2 from
`HostFacts` — `docker inspect` of the unit container — and the ingestion program removes that
container before it returns. So on the Development phase the choice is between an evidence chain
nobody can produce and an honest, weaker one that says so.

This module is the honest weaker one. It is NOT a stand-in for the Runner and does not pretend to
be:

* **It is signed by a different key.** `DEV_SELFATTEST_KEY_ID`, not `DEV_KEY_ID`. A reader can tell
  a Hub self-attestation from a Runner attestation by looking at one field, and a trust store that
  does not carry the key rejects the record through the check that already exists.
* **It never declares a run rankable.** `rankability.state` is always `unrankable`; the only
  question is which controls it names. `_assert_never_rankable` runs on the finished document, so
  the guarantee is a property of the bytes rather than of the code path that produced them.
* **It refuses outside the Development profile.** A production trust store, a production execution
  profile, or any signing key that is not the published self-attestation key is a refusal, not a
  warning.

## What it actually checks, and why the verdict is honest

An attestation whose only source is the document it attests confirms nothing. So this does perform
one real, independent comparison: it re-reads the **published sanitized tree** from the scoring
namespace and re-verifies it against the persisted C3 descriptor, both ways —
`SanitizedTree.verify_digest()` re-derives the root digest from the entries, and
`verify_destination()` re-reads every entry off disk. That is a host fact, gathered after the
observation was written, about the exact bytes the scorer is about to open, and it is the fact that
matters most: it catches a tree that changed between publication and scoring.

`observation_verdict` is therefore `confirmed`/`host_facts_match` only when that comparison
succeeds, and `contradicted`/`host_facts_mismatch` when it does not — which `score.py` refuses, as
it should. There is no path here that reports agreement without having compared anything.

## The published seed

`DEV_SELFATTEST_SEED` is a constant in this repository. That is not a leak and not an oversight:
anything the development trust store accepts is forgeable by anyone who can read it, which is
exactly why `verify_signed(..., require_production_trust=True)` — the default — refuses it, why
`score.py` stamps `rankable=false` and `trust_profile="development"` on every board it produces,
and why a production bundle carries neither this module's output nor the key that verifies it.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .artifact_tree import SanitizedTree, TreeLimits
from .digest import digest_json, parse_digest
from .errors import ContractError, OrganizerFault
from .fixtures import (
    DEV_KEY_ID,
    DEV_SEED,
    DEV_SELFATTEST_KEY_ID,
    DEV_SELFATTEST_SEED,
    dev_public_key,
    dev_selfattest_public_key,
    load_fixture,
)
from .plan import EvaluationPlan, compute_roster_digest
from .run_record import (
    SCHEMA_VERSION,
    Lifecycle,
    RunRecord,
    attestation_payload,
    derive_participant_outcome,
    derive_unmet_controls,
)
from .signing import TrustStore, sign_payload

__all__ = [
    "CONTROL_DIRNAME",
    "DevelopmentAttestationRefused",
    "OBSERVATION_DIRNAME",
    "PLAN_FILENAME",
    "RUN_RECORD_DIRNAME",
    "TRUST_STORE_FILENAME",
    "attest_development_run_records",
    "development_plan",
    "development_trust_store_document",
    "write_development_evidence_anchor",
]

CONTROL_DIRNAME = "_control"
PLAN_FILENAME = "evaluation_plan.json"
TRUST_STORE_FILENAME = "trust_store.json"
OBSERVATION_DIRNAME = "observations"
RUN_RECORD_DIRNAME = "run_records"
ARTIFACT_TREE_DIRNAME = "artifact_trees"

#: The execution profiles this producer will run under. `production` is absent by construction, not
#: by a branch: a production run has a Runner, and if it does not, the correct outcome is the
#: organizer fault `score.py` already raises — not a weaker record that lets the board publish.
DEVELOPMENT_PROFILES = ("smoke",)

_MEMORY_UNITS = {
    "": 1,
    "b": 1,
    "k": 10**3,
    "kb": 10**3,
    "ki": 1 << 10,
    "kib": 1 << 10,
    "m": 10**6,
    "mb": 10**6,
    "mi": 1 << 20,
    "mib": 1 << 20,
    "g": 10**9,
    "gb": 10**9,
    "gi": 1 << 30,
    "gib": 1 << 30,
    "t": 10**12,
    "tb": 10**12,
    "ti": 1 << 40,
    "tib": 1 << 40,
}
_MEMORY_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]*)\s*$")


class DevelopmentAttestationRefused(OrganizerFault):
    """This producer was asked to do something only the Runner may do. Never a warning."""


def _memory_bytes(value: Any) -> int | None:
    """`"4G"` -> 4_000_000_000. `None` when the value is not a memory quantity at all.

    Returned rather than raised: C2's `applied.limits.memory_bytes` accepts any JSON value, so an
    unparseable card value is recorded as-is with its own provenance rather than turned into a
    fabricated integer. A wrong number in a field named `_bytes` is worse than a string.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    match = _MEMORY_RE.match(value)
    if not match:
        return None
    scale = _MEMORY_UNITS.get(match.group(2).lower())
    if scale is None:
        return None
    return int(float(match.group(1)) * scale)


def _require_development(*, profile: str, trust_store: TrustStore, key_id: str) -> None:
    """The three refusals. Each names a way this producer could have been misused."""
    if profile not in DEVELOPMENT_PROFILES:
        raise DevelopmentAttestationRefused(
            f"profile={profile!r} is not one of {list(DEVELOPMENT_PROFILES)}. The Hub does not "
            "attest its own observation on a ranked phase: an evidence chain whose only witness "
            "is the thing being witnessed is not evidence, and a missing C2 in production is an "
            "infrastructure failure that must surface as one."
        )
    if trust_store.profile != "development":
        raise DevelopmentAttestationRefused(
            f"the trust store's profile is {trust_store.profile!r}. A self-attested C2 is only "
            "meaningful inside a chain that announces itself as forgeable; anchoring one to a "
            "production trust store would give it exactly the weight it does not have."
        )
    if key_id != DEV_SELFATTEST_KEY_ID:
        raise DevelopmentAttestationRefused(
            f"key_id={key_id!r}: this producer signs with {DEV_SELFATTEST_KEY_ID!r} and nothing "
            "else. Signing a self-attestation with the Runner's key would make the two "
            "indistinguishable in the artifact, which is the one thing the key id is for."
        )
    if trust_store.get(DEV_SELFATTEST_KEY_ID) != dev_selfattest_public_key():
        raise DevelopmentAttestationRefused(
            f"the trust store does not carry {DEV_SELFATTEST_KEY_ID!r}, or carries a different "
            "key under that id. The record would be written and then rejected by the scorer as an "
            "unknown signer, which is a silent empty leaderboard rather than a stated refusal."
        )


def _verify_published_tree(
    sanitized_root: pathlib.Path, control: pathlib.Path, unit: str, observation: Mapping[str, Any]
) -> tuple[str, str | None, str | None]:
    """Re-read the published tree and check it against the persisted C3 descriptor.

    Returns `(sanitized_tree_digest, verdict, reason)` where `verdict` is `None` when the tree
    verified. This is the ONE independent host fact this producer establishes, so it is also the
    only thing entitling it to write `confirmed`.
    """
    sanitized = observation.get("sanitized")
    if not isinstance(sanitized, Mapping) or not sanitized.get("tree_digest"):
        # No published tree: the sanitizer refused it, or the container never produced one. There
        # is nothing to compare and nothing to disagree with, so the verdict is not `contradicted`
        # -- `score.py` resolves this unit from the lifecycle and the absent `res/<handle>/`.
        return "", None, None
    claimed = str(sanitized["tree_digest"])
    path = control / ARTIFACT_TREE_DIRNAME / f"{unit}.json"
    if not path.is_file():
        return claimed, "contradicted", "observation_malformed"
    try:
        tree = SanitizedTree.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ContractError):
        return claimed, "contradicted", "observation_malformed"
    if tree.root_digest != claimed:
        return claimed, "contradicted", "host_facts_mismatch"
    try:
        # Both ways: the entries re-derive the digest, and the digest is over bytes that are still
        # on disk in the scoring namespace.
        tree.verify_digest()
    except ContractError:
        return claimed, "contradicted", "host_facts_mismatch"
    from ..sanitize import MaterializedFile, verify_destination

    published = sanitized_root / str(sanitized.get("published_as") or unit)
    expected = [
        MaterializedFile(
            path=entry.path,
            size_bytes=entry.size_bytes,
            sha256=entry.sha256,
            mode_bits=entry.mode_bits,
            num_rows=entry.num_rows,
        )
        for entry in tree.entries
    ]
    if verify_destination(published, expected, limits=TreeLimits()):
        return claimed, "contradicted", "host_facts_mismatch"
    return claimed, None, None


def _applied(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Project the observation's `applied` block onto C2's narrower one.

    A projection and not a copy: the observation records ten limit slots this program applies, C2
    freezes four, and the memory slot is a card string on one side and a byte count on the other.
    Every value here comes from the observation; nothing is invented and nothing is upgraded.
    """
    applied = observation.get("applied") or {}
    limits = applied.get("limits") or {}

    def slot(name: str) -> dict[str, Any]:
        raw = limits.get(name) or {}
        return {
            "requested": raw.get("requested"),
            "applied": raw.get("applied"),
            "source": raw.get("source", "unset"),
        }

    memory = slot("memory")
    requested_bytes = _memory_bytes(memory["requested"])
    applied_bytes = _memory_bytes(memory["applied"])
    gpu = applied.get("gpu") or {}
    gpu_applied = gpu.get("applied")
    # R-5: a device is named by UUID or the selection is not by UUID. The Hub records what it
    # applied; if that is not a UUID the selector says so and `derive_unmet_controls` charges the
    # `gpu_device_unpinned` control for it.
    uuid = gpu_applied if isinstance(gpu_applied, str) and gpu_applied.startswith("GPU-") else None
    if gpu_applied is None:
        selector = None
    elif uuid is not None:
        selector = "uuid"
    elif isinstance(gpu_applied, str) and gpu_applied.strip().isdigit():
        selector = "index"
    else:
        selector = "all"
    return {
        "runtime": {
            "requested": (applied.get("runtime") or {}).get("requested"),
            "applied": (applied.get("runtime") or {}).get("applied"),
            "source": (applied.get("runtime") or {}).get("source", "unset"),
        },
        "gpu": {
            "requested": gpu.get("requested"),
            "applied": gpu_applied,
            "source": gpu.get("source", "unset"),
            "uuid": uuid,
            "selector": selector,
        },
        "network": {
            "requested": (applied.get("network") or {}).get("requested"),
            "applied": (applied.get("network") or {}).get("applied"),
            "source": (applied.get("network") or {}).get("source", "unset"),
        },
        "limits": {
            "cpus": slot("cpus"),
            "memory_bytes": {
                "requested": requested_bytes,
                "applied": applied_bytes,
                "source": memory["source"] if requested_bytes is not None else "unset",
            },
            "pids": slot("pids"),
            "storage_bytes": slot("storage_bytes"),
        },
    }


def _assert_never_rankable(document: Mapping[str, Any]) -> None:
    """The guarantee, asserted on the finished bytes rather than trusted to the code above."""
    state = (document.get("rankability") or {}).get("state")
    if state == "rankable":  # noqa: SIM102 - the message is the point
        raise DevelopmentAttestationRefused(
            "a development self-attestation declared state='rankable'. No control this producer "
            "can establish makes a run rankable, so this is a defect in this module and not a "
            "condition to report; refusing to write the record."
        )


def attest_development_run_records(
    *,
    output_root: str | os.PathLike[str],
    plan_digest: str,
    descriptor_digest: str,
    signed_at: str,
    profile: str,
    trust_store: TrustStore,
    key_id: str = DEV_SELFATTEST_KEY_ID,
    seed: bytes = DEV_SELFATTEST_SEED,
) -> dict[str, str]:
    """File one self-attested C2 per observation. Returns `{unit: outcome}` for the operator log.

    `outcome` is `"written"`, or a short reason the unit produced no record. A unit with no record
    is resolved by `score.py` as a missing C2, which is an organizer fault — correctly, because a
    run whose evidence we could not assemble is one we cannot attribute.
    """
    _require_development(profile=profile, trust_store=trust_store, key_id=key_id)
    root = pathlib.Path(output_root)
    control = root / CONTROL_DIRNAME
    observations = control / OBSERVATION_DIRNAME
    records = control / RUN_RECORD_DIRNAME
    records.mkdir(parents=True, exist_ok=True)

    plan_digest = parse_digest(plan_digest, field="plan_digest")
    descriptor_digest = parse_digest(descriptor_digest, field="descriptor_digest")
    # There is no C7 instance on a Development queue, and `bindings.c7_instance_digest` has no null.
    # So it binds a digest of the STATEMENT that there was none -- a real digest of a real document,
    # rather than a borrowed one that would claim hardware nobody measured. The matching
    # `tier_unenforced` control is declared on every record below.
    c7_digest = digest_json(
        {
            "c7_instance": None,
            "profile": profile,
            "reason": "development phase serves no signed C7 instance",
        }
    )

    outcomes: dict[str, str] = {}
    for path in sorted(observations.glob("*.json")) if observations.is_dir() else []:
        unit = path.stem
        try:
            observation = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            outcomes[unit] = "observation_unreadable"
            continue
        if not isinstance(observation, Mapping):
            outcomes[unit] = "observation_malformed"
            continue
        image = observation.get("image") or {}
        if not image.get("resolved_digest"):
            # C2 has no null `image.resolved_digest`, so a run whose image the daemon could not
            # identify cannot be described by a run record at all. `ingest.py` already calls this
            # an infrastructure failure in production ("no provable identity"); the same reading
            # applies here, and the unit surfaces as a missing C2 rather than as a participant zero.
            outcomes[unit] = "image_digest_unresolved"
            continue
        lifecycle = dict(observation.get("lifecycle") or {})
        lifecycle.setdefault("signal", None)
        lifecycle.setdefault("oom_killed", False)
        tree_digest, verdict, reason = _verify_published_tree(root, control, unit, observation)
        hint = (observation.get("rankability_hint") or {}).get("unmet_controls") or []
        document: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": f"dev-selfattest-{unit}",
            "unit_handle": unit,
            "attempt_slot_index": 0,
            "bindings": {
                "plan_digest": plan_digest,
                "descriptor_digest": descriptor_digest,
                "c7_instance_digest": c7_digest,
                # The digest this producer RE-DERIVED above, not the one the observation claimed,
                # on the two occasions they could differ.
                "sanitized_tree_digest": tree_digest or c7_digest,
            },
            "image": {
                "requested": image.get("requested") or "",
                "resolved_digest": image["resolved_digest"],
                "interface_label": image.get("interface_label") or "",
            },
            "lifecycle": lifecycle,
            "participant_outcome": "success",
            "rankability": {"state": "unrankable", "unmet_controls": []},
            "timing": observation.get("timing") or {},
            "applied": _applied(observation),
            "telemetry": None,
            "output_row_counts": {},
            "repeats": [],
            "leakage": {
                "canary_verdict": "clean",
                "hit_count": 0,
                "scanned_file_count": 0,
                "scanned_bytes": 0,
            },
            "worker_layer_view": [],
            "observation": {"observed_by": "qfbench2-hub", "notes_count": 0},
            "attestation": {
                "observation_verdict": verdict or "confirmed",
                "reason": reason or "host_facts_match",
            },
        }
        try:
            # Derived from the daemon facts by the contract's own function. NOT parsed out of a
            # provisional RunRecord first: `RunRecord.from_mapping` refuses a document whose
            # declared `participant_outcome` disagrees with the derivation, so asking it to tell us
            # the answer requires already knowing it -- and every crashed container came back as
            # "observation_not_a_valid_c2" instead of as a participant failure.
            document["participant_outcome"] = derive_participant_outcome(
                Lifecycle.from_mapping(lifecycle)
            )
        except ContractError as exc:
            outcomes[unit] = f"observation_not_a_valid_c2 ({exc})"
            continue

        # The declared set must be a SUPERSET of what a reader can derive. The Hub's own hint is
        # the floor; `signature_invalid` leaves it because this record IS signed; `telemetry_absent`
        # and `tier_unenforced` are added unconditionally because no Development run has host
        # telemetry or a signed C7 instance, and neither is derivable from the record alone.
        unmet = (set(hint) - {"signature_invalid"}) | {"telemetry_absent", "tier_unenforced"}
        if verdict == "contradicted":
            unmet.add("observation_contradicted")
        # THE HUB'S OWN BLAME VERDICT, CARRIED. `ingest.py` classifies the daemon's refusal and
        # writes `fault`/`docker_fault: "infrastructure"` when the run failed for a reason the
        # participant did not cause -- a missing GPU device driver, an unreachable daemon, a
        # rejected mount. Dropping that field and letting the lifecycle speak for itself converts
        # every one of those into a participant zero, because `_code_from_lifecycle` reads only
        # `timed_out`, `oom_killed` and `phase_reached` and has no branch for "the daemon refused".
        #
        # Measured 2026-08-24 on a host with no GPU driver: the observation said
        # `docker_error_reason: device_unavailable`, `fault: infrastructure` -- and the C2 built
        # from it scored the unit `container_crashed`, a PARTICIPANT failure. That is exactly the
        # attribution mistake the contract set exists to remove, reintroduced one layer down.
        state = "unrankable"
        if "infrastructure" in (observation.get("fault"), observation.get("docker_fault")):
            state = "organizer_failure"
        document["rankability"] = {"state": state, "unmet_controls": sorted(unmet)}
        try:
            probe = RunRecord.from_mapping({**document, "attestation": None})
            unmet |= set(derive_unmet_controls(probe, telemetry_required=True)) - {
                "signature_invalid"
            }
            document["rankability"] = {"state": state, "unmet_controls": sorted(unmet)}
            _assert_never_rankable(document)
            envelope = sign_payload(
                attestation_payload(document), seed=seed, key_id=key_id, signed_at=signed_at
            )
            document["attestation"]["signature"] = envelope.to_mapping()
            record = RunRecord.from_mapping(document)
            record.verify_attestation(trust_store, require_production_trust=False)
        except ContractError as exc:
            outcomes[unit] = f"refused ({exc})"
            continue
        (records / f"{unit}.json").write_text(
            json.dumps(document, indent=2, sort_keys=True, allow_nan=False)
        )
        outcomes[unit] = "written"
    return outcomes


# --------------------------------------------------------------------------- the C1 side
#: The Development phase runs ONE attempt per unit. The Final phase's coding plan is
#: `per_unit_attempt` with `attempts_per_unit = 3`, which the shared CodaBench driver refuses
#: outright (`score.py`: "metric.unit_scope=... is not supported"). That refusal is correct and the
#: gap is real -- repeated-attempt scoring is what hub #54 and codabench #33 are for -- but it is
#: not a Development-phase problem to solve. A dev plan that declares one attempt per unit is a
#: true statement about the dev phase; a dev plan that declared three would be a false one that
#: also could not be scored.
_DEV_ATTEMPTS_PER_UNIT = 1


def development_plan(
    *,
    track: str,
    handles: Sequence[str],
    competition_id: str,
    plan_id: str,
    signed_at: str,
    seed: bytes = DEV_SEED,
    key_id: str = DEV_KEY_ID,
) -> dict[str, Any]:
    """A signed, expanded C1 over `handles`, for the Development phase.

    DERIVED from the hub's own golden fixture rather than written out here. Each track's fixture
    already carries every track-specific key the C1 parser requires -- T2's grid and normalization,
    T3's repeat policy and aggregation, T4's scoring params and entity roster -- and a plan
    assembled from scratch in a bundle generator would be a second copy of a hub-owned document,
    drifting from the first the moment either changed. What varies here is the roster, the phase,
    the identifiers, and the coding track's attempt shape.

    The signature is the published DEVELOPMENT organizer key, so `verify_signature(...,
    require_production_trust=True)` -- the default everywhere else -- refuses it, and `score.py`
    stamps `rankable=false` / `trust_profile="development"` on any board it produces.
    """
    handles = [str(h) for h in handles]
    if not handles:
        raise ContractError(
            "a development plan needs at least one expected unit; a zero-unit roster is the "
            "A01 defect this document exists to close"
        )
    body: dict[str, Any] = json.loads(json.dumps(load_fixture(f"c1/{track}_final.expanded.json")))
    body["phase"] = "dev"
    body["competition_id"] = competition_id
    body["plan_id"] = plan_id
    if track == "coding":
        body["metric"]["unit_scope"] = "per_unit"
        body["attempts_per_unit"] = _DEV_ATTEMPTS_PER_UNIT
        body["k_values"] = [_DEV_ATTEMPTS_PER_UNIT]
    template = json.loads(json.dumps(body["roster"]["expected_units"][0]))
    body["roster"] = {
        "count": len(handles),
        "digest": compute_roster_digest(handles),
        "expected_units": [{**template, "unit_handle": handle} for handle in handles],
    }
    body.pop("signature", None)
    body["signature"] = sign_payload(
        body, seed=seed, key_id=key_id, signed_at=signed_at
    ).to_mapping()
    # Parsed before it is returned: a plan this function emits and the scorer then refuses is a
    # bundle that builds cleanly and fails in production, which is the failure mode the whole
    # contract set exists to remove.
    plan = EvaluationPlan.from_mapping(body)
    plan.require_rankable()
    if plan.metric.unit_scope != "per_unit":
        raise ContractError(
            f"the {track} development plan has unit_scope={plan.metric.unit_scope!r}, which the "
            "shared CodaBench scoring driver refuses. Emitting it would produce a bundle whose "
            "every submission is an organizer fault."
        )
    if not plan.required_evidence["c2"]:
        raise ContractError(
            "a development plan must still require C2. The driver always consumes the run record; "
            "a plan that says otherwise describes a scorer that does not exist."
        )
    return body


def development_trust_store_document(label: str) -> dict[str, Any]:
    """The DEVELOPMENT trust anchor: both published dev keys, and the profile that says so.

    `profile: "development"` is the whole point. `score.py` reads it, refuses to call the board
    official, and prints the forgeability warning; `_require_development` above refuses to sign
    against anything else. A production trust store carries neither of these key ids, so a
    self-attested C2 is rejected there by the unknown-signer check that already exists.
    """
    return {
        "profile": "development",
        "label": label,
        "keys": {
            DEV_KEY_ID: base64.b64encode(dev_public_key()).decode("ascii"),
            DEV_SELFATTEST_KEY_ID: base64.b64encode(dev_selfattest_public_key()).decode("ascii"),
        },
    }


def write_development_evidence_anchor(
    reference_root: str | os.PathLike[str],
    *,
    track: str,
    handles: Sequence[str],
    competition_id: str,
    plan_id: str,
    signed_at: str,
    label: str,
) -> dict[str, str]:
    """Write `evaluation_plan.json` and `trust_store.json` into a phase's reference_data.

    The ORGANIZER side, deliberately: `score.py` reads both out of `input/ref`, which is the
    phase's reference_data and the one tree the participant-handling stage never writes. A trust
    anchor read from the tree whose integrity it establishes establishes nothing.
    """
    root = pathlib.Path(reference_root)
    root.mkdir(parents=True, exist_ok=True)
    plan = development_plan(
        track=track,
        handles=handles,
        competition_id=competition_id,
        plan_id=plan_id,
        signed_at=signed_at,
    )
    (root / PLAN_FILENAME).write_text(
        json.dumps(plan, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    (root / TRUST_STORE_FILENAME).write_text(
        json.dumps(development_trust_store_document(label), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"plan_digest": digest_json({k: v for k, v in plan.items() if k != "signature"})}
