"""`qfbench2_common.contracts` — the frozen C1-C8 interface, contract set 1.1.0.

## Executive summary (read this first)

This subpackage is the single implementation of the eight shared contracts frozen on 2026-08-21.
Runner, CodaBench, the website and all four tracks are **consumers** of these definitions; nobody
keeps a local copy (global rule 3).

| Contract | Module | What it is |
|---|---|---|
| C1 | `plan` | Evaluation plan: roster commitment, metric domain, failure policy |
| C2 | `run_record` | Trusted run record: what the organizer's infrastructure observed |
| C3 | `artifact_tree` | Sanitized participant artifact tree: roots, node policy, manifest |
| C4 | `result` | Scorer result and the fixed-denominator aggregate |
| C5 | `descriptor` | Canonical submission descriptor |
| C6 | `sealed` | Sealed pointer: public handle + signed resolver descriptor |
| C7 | `hardware` | Hardware/queue/runtime/egress, provenance-aware |
| C8 | `release` | Release evidence manifest |
| —  | `heartbeat` | Worker preflight report, bound to a C7 instance by digest |

Cross-cutting: `errors` (the strict accessor `req`), `digest` (RFC 8785 canonicalization),
`signing` (the Ed25519 envelope and the fail-closed trust store), `codes` (the closed C4 enum).

Four rules bind every one of them, and they are why this package exists:

1. **An absent field is an error, never a satisfied constraint.** Read contract fields with `req`.
2. **Digests are computed one way** — sha256 over RFC 8785 canonical JSON, NFC paths.
3. **Enums are closed.** No "unknown/other" bucket anywhere.
4. **Unknown means not rankable.** An empty trust store, an unmeasured C7 field and an absent
   attestation all degrade to "not rankable", never to "silently permitted".

Golden fixtures ship **inside the package** (`contracts/fixtures/`) so CodaBench and the website
consume the same bytes the tests verify, rather than each maintaining a hand-written example.

## Contract set 1.1.0

Per-contract versioning is what makes a bump cheap: only the documents that actually changed moved.

| Contract | Version | What changed |
|---|---|---|
| C1 `plan` | **1.2.0** | Sealed-phase handles must be opaque; a handle grammar and a derivation helper. 1.2.0 closes `scoring_params.target_type` and `scoring_params.composite_weights`; `contract_set` deliberately did not move with it (see `plan.py`) |
| C2 `run_record` | **1.1.0** | `observation_contradicted`; required `applied.gpu.selector` |
| C7 `hardware` | **1.1.0** | `worker_env` has a required role set, including `scratch_root` |
| C8 `release` | **1.1.0** | Required `phase_visibility`; ratified competition ids; sign-off roles |
| — `heartbeat` | 1.0.0 | New: promoted from the operator repo |
| C5 `descriptor` | **1.1.0** | `models` may be empty: a model-free submission declares `models: []` instead of inventing a row (every declared row still needs all five fields) |
| C3, C4, C6 | 1.0.0 | Unchanged |

`contracts/MIGRATIONS.md` is the participant-facing summary: it lists only the parts of the set
that constrain a submission (C5, C3, C4). 1.1.0 is the first published contract set, so there is
no earlier published version to migrate from; the organizer-side changes above are recorded in
each module's own `SCHEMA_VERSION` comment.
"""

from __future__ import annotations

from .artifact_tree import (
    ROOT_ACCESS,
    NodeObservation,
    NodeType,
    RejectionCode,
    Root,
    SanitizedTree,
    TreeEntry,
    TreeLimits,
    TreeValidation,
    assert_root_access,
    classify_node,
    validate_listing,
)
from .codes import (
    FAILURE_CODE_REGISTRY_VERSION,
    FailureCode,
    FailureCodeRow,
    failure_code_registry,
    parse_failure_code,
)
from .descriptor import CATEGORIES, IMAGE_ACCESS, ModelDisclosure, SubmissionDescriptor
from .devattest import (
    DevelopmentAttestationRefused,
    attest_development_run_records,
)
from .digest import digest_json, digest_tree, jcs_canonical, normalize_tree_path, parse_digest
from .errors import (
    ContractError,
    OrganizerFault,
    ParticipantFailure,
    reject_unknown_keys,
    req,
    req_bool,
    req_enum,
    req_float,
    req_int,
    req_list,
    req_mapping,
    req_str,
    strict_bool,
)
from .hardware import (
    EGRESS_MODES,
    PROVENANCE,
    SERVED_CATEGORIES,
    WORKER_ENV_REQUIRED_ROLES,
    Egress,
    HardwareInstance,
    Provenanced,
)
from .heartbeat import (
    HEARTBEAT_PREFLIGHT_KEYS,
    HEARTBEAT_SCHEMA_VERSION,
    WorkerHeartbeat,
)
from .plan import (
    COMPOSITE_WEIGHT_KEYS,
    CONTRACT_SET,
    DIRECTIONS,
    HANDLE_RE,
    MAX_HANDLE_LENGTH,
    MIN_HANDLE_SALT_CHARS,
    OPAQUE_HANDLE_HEX_DEFAULT,
    OPAQUE_HANDLE_RE,
    PHASES,
    RESERVED_HANDLES,
    SEALED_PHASES,
    TARGET_TYPES,
    TRACKS,
    UNIT_SCOPES,
    EvaluationPlan,
    MetricSpec,
    ParticipantFailurePolicy,
    RosterEntry,
    compute_roster_digest,
    derive_opaque_handle,
    derive_opaque_roster,
    validate_unit_handle,
)
from .release import (
    COMPETITION_ID_VALUES,
    COMPETITION_IDS,
    PUBLICATION_SIGN_OFF_ROLE,
    SIGN_OFF_ROLES,
    FactRow,
    PhaseVisibility,
    ReleaseEvidence,
)
from .result import (
    Aggregate,
    JudgeRecord,
    ResultState,
    UnitResult,
    public_detail_keys,
    validate_public_detail,
)
from .run_record import (
    APPLIED_SOURCES,
    GPU_SELECTORS,
    NON_REPRODUCIBLE_GPU_SELECTORS,
    OPERATOR_OVERRIDE_CONTROLS,
    UNMET_CONTROLS,
    AppliedControl,
    Attestation,
    Lifecycle,
    Rankability,
    RunRecord,
    attestation_payload,
    derive_participant_outcome,
    derive_unmet_controls,
    telemetry_admissible_for_timing,
)
from ._time import RFC3339_RE, format_rfc3339, parse_rfc3339
from .sealed import ArtifactRole, CorpusEntry, ResolverDescriptor, SealedArtifact, SealedHandle
from .signing import (
    SIGNATURE_ALG,
    SignatureEnvelope,
    SignatureUnverifiable,
    TrustStore,
    VerificationResult,
    ed25519_backend,
    sign_payload,
    verify_signed,
    verify_signed_object,
)

__all__ = [
    "APPLIED_SOURCES",
    "CATEGORIES",
    "COMPETITION_IDS",
    "COMPETITION_ID_VALUES",
    "COMPOSITE_WEIGHT_KEYS",
    "CONTRACT_SET",
    "DIRECTIONS",
    "EGRESS_MODES",
    "FAILURE_CODE_REGISTRY_VERSION",
    "GPU_SELECTORS",
    "HANDLE_RE",
    "HEARTBEAT_PREFLIGHT_KEYS",
    "HEARTBEAT_SCHEMA_VERSION",
    "IMAGE_ACCESS",
    "MAX_HANDLE_LENGTH",
    "MIN_HANDLE_SALT_CHARS",
    "NON_REPRODUCIBLE_GPU_SELECTORS",
    "OPAQUE_HANDLE_HEX_DEFAULT",
    "OPAQUE_HANDLE_RE",
    "OPERATOR_OVERRIDE_CONTROLS",
    "PHASES",
    "PROVENANCE",
    "PUBLICATION_SIGN_OFF_ROLE",
    "RESERVED_HANDLES",
    "RFC3339_RE",
    "ROOT_ACCESS",
    "SEALED_PHASES",
    "SERVED_CATEGORIES",
    "SIGNATURE_ALG",
    "SIGN_OFF_ROLES",
    "TARGET_TYPES",
    "TRACKS",
    "UNIT_SCOPES",
    "UNMET_CONTROLS",
    "WORKER_ENV_REQUIRED_ROLES",
    "Aggregate",
    "AppliedControl",
    "ArtifactRole",
    "Attestation",
    "ContractError",
    "CorpusEntry",
    "Egress",
    "EvaluationPlan",
    "FactRow",
    "FailureCode",
    "FailureCodeRow",
    "HardwareInstance",
    "JudgeRecord",
    "Lifecycle",
    "MetricSpec",
    "ModelDisclosure",
    "NodeObservation",
    "NodeType",
    "DevelopmentAttestationRefused",
    "attest_development_run_records",
    "OrganizerFault",
    "ParticipantFailure",
    "ParticipantFailurePolicy",
    "PhaseVisibility",
    "Provenanced",
    "Rankability",
    "RejectionCode",
    "ReleaseEvidence",
    "ResolverDescriptor",
    "ResultState",
    "Root",
    "RosterEntry",
    "RunRecord",
    "SanitizedTree",
    "SealedArtifact",
    "SealedHandle",
    "SignatureEnvelope",
    "SignatureUnverifiable",
    "SubmissionDescriptor",
    "TreeEntry",
    "TreeLimits",
    "TreeValidation",
    "TrustStore",
    "UnitResult",
    "VerificationResult",
    "WorkerHeartbeat",
    "assert_root_access",
    "attestation_payload",
    "classify_node",
    "compute_roster_digest",
    "derive_opaque_handle",
    "derive_opaque_roster",
    "derive_participant_outcome",
    "derive_unmet_controls",
    "digest_json",
    "digest_tree",
    "ed25519_backend",
    "failure_code_registry",
    "format_rfc3339",
    "jcs_canonical",
    "normalize_tree_path",
    "parse_digest",
    "parse_failure_code",
    "parse_rfc3339",
    "public_detail_keys",
    "reject_unknown_keys",
    "req",
    "req_bool",
    "req_enum",
    "req_float",
    "req_int",
    "req_list",
    "req_mapping",
    "req_str",
    "sign_payload",
    "strict_bool",
    "telemetry_admissible_for_timing",
    "validate_listing",
    "validate_public_detail",
    "validate_unit_handle",
    "verify_signed",
    "verify_signed_object",
]

#: The frozen contract-set version every module in this package implements.
CONTRACT_SET_VERSION = CONTRACT_SET
