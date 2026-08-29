"""C7 — hardware, queue, runtime and egress, with the provenance ruling behind them.

## Executive summary (read this first)

**Every field is `{value, provenance: "measured" | "unmeasured"}`, and any `unmeasured` field forces
`rankable = false` for the queues that instance serves.** That single rule is what lets the code be
written before the GPU box exists: an honest incomplete C7 is representable, a plausible invented
value is not. "We do not yet have the hardware" becomes a recorded, fail-closed state instead of a
blocker.

The enforcement that makes it honest rather than decorative: **`provenance: "unmeasured"` requires
`value: null`.** A field cannot claim to be unmeasured while carrying a number somebody typed in,
and it cannot carry a number without claiming to have measured it. There is no third option.

Egress, frozen:

* `mode: "single_endpoint"` with `endpoint: null` is **invalid by schema** — and so is the mirror
  case, `deny_all` with an endpoint attached, because a "disabled" allowlist that still names a
  host is the configuration that gets accidentally enabled.
* The proxy ships in `deny_all` by default and **refuses to start on an empty allowlist** unless
  `mode: deny_all` is explicit. `egress_allowlist()` returns the generated allowlist and raises
  when that invariant is broken, so provisioning cannot silently produce an empty one.

`public_projection` names the **only** fields the website may publish; `public_view()` returns
exactly those and nothing else, so a website cannot publish a field by reading the instance
directly.

### New in C7 1.1.0

`worker_env` now has a **required role set** (`WORKER_ENV_REQUIRED_ROLES`), and `scratch_root` is
in it. That variable names the bind-mounted, daemon-visible directory where raw participant output
lives — the one place it must be, because the frozen topology puts raw bytes *outside* the
ingestion output root that becomes the scorer's `input/res`. It was the only worker variable a
consumer had to hard-code, and the consumer that hard-coded it said so in a comment.

`heartbeat.WorkerHeartbeat` is the companion document: a worker's signed preflight report, bound
to a specific instance by `c7_instance_digest`, which is what lets a publish gate demand evidence
that the box on the other end of the queue is the box this C7 describes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .digest import digest_json
from .errors import (
    ContractError,
    req,
    req_bool,
    req_enum,
    req_int,
    req_list,
    req_str,
    reject_unknown_keys,
)
from .signing import SignatureEnvelope

__all__ = [
    "EGRESS_MODES",
    "PROVENANCE",
    "SERVED_CATEGORIES",
    "WORKER_ENV_REQUIRED_ROLES",
    "Egress",
    "HardwareInstance",
    "Provenanced",
]

SCHEMA_VERSION = "1.1.0"
PROVENANCE = ("measured", "unmeasured")
EGRESS_MODES = ("deny_all", "single_endpoint")
SERVED_CATEGORIES = ("api", "byo-large", "byo-small", "simulator")

#: Worker-environment roles a C7 instance MUST name. The map is role -> variable NAME; C7 never
#: carries a value. Extra roles are allowed — a deployment that needs `QFBENCH_SCORING_RUNTIME`
#: names it here too — but these nine may not be absent, because a consumer generating a worker
#: environment reads the name from C7 and has nowhere else to get it.
#:
#: `scratch_root` is new in C7 1.1.0 and was the one variable a consumer had to hard-code. The
#: CodaBench operator held `SCRATCH_ROOT_VAR = "QFBENCH_SCRATCH_ROOT"` as a local constant with a
#: comment saying so, which is precisely the "one repo keeps its own copy" shape the contract set
#: exists to remove: the variable that decides whether raw participant bytes land OUTSIDE the
#: ingestion output root was the only one not sourced from the contract.
WORKER_ENV_REQUIRED_ROLES = (
    "gpu_device",
    "model_endpoint",
    "model_name",
    "proxy_policy",
    "resolver",
    "scratch_root",
    "seed",
    "served_categories",
    "unit_runtime",
)

_HARDWARE_FIELDS = (
    "model",
    "gpu_uuid",
    "driver",
    "cuda",
    "architecture",
    "node_fingerprint",
    "exclusive_use",
    "max_contender_processes",
    "thermal_bounds",
)
_LIMIT_FIELDS = (
    "cpus",
    "memory_bytes",
    "pids",
    "storage_bytes",
    "output_bytes",
    "wall_time_sec",
)
_RUNTIME_FIELDS = ("worker", "ingestion", "scoring", "unit")
_TOP_KEYS = (
    "schema_version",
    "instance_id",
    "queue_id",
    "served_categories",
    "hardware",
    "limits",
    "runtime",
    "egress",
    "telemetry",
    "worker_env",
    "unit_resource_profiles",
    "verifier_sandbox_profile",
    "model_cache",
    "public_projection",
    "signature",
)


@dataclass(frozen=True, slots=True)
class Provenanced:
    """`{value, provenance}`. `unmeasured` implies `value is None`; the pair cannot lie."""

    value: Any
    provenance: str

    @property
    def measured(self) -> bool:
        return self.provenance == "measured"

    @classmethod
    def from_mapping(cls, obj: Any, *, path: str) -> Provenanced:
        if not isinstance(obj, Mapping):
            raise ContractError(
                f"{path} must be a {{value, provenance}} object. Every C7 field carries its own "
                "provenance; a bare value has none and is refused."
            )
        reject_unknown_keys(obj, ("value", "provenance"), path=path)
        provenance = req_enum(obj, "provenance", PROVENANCE, path=path)
        if "value" not in obj:
            raise ContractError(f"{path}.value is absent; write null for an unmeasured field")
        value = obj["value"]
        if provenance == "unmeasured" and value is not None:
            raise ContractError(
                f"{path} is marked unmeasured but carries the value {value!r}. An honest "
                "incomplete C7 is representable; a plausible invented value is not."
            )
        if provenance == "measured" and value is None:
            raise ContractError(
                f"{path} claims to be measured but its value is null. A null measurement is an "
                "unmeasured field wearing a costume."
            )
        return cls(value=value, provenance=provenance)

    def to_mapping(self) -> dict[str, Any]:
        return {"value": self.value, "provenance": self.provenance}


@dataclass(frozen=True, slots=True)
class Egress:
    mode: str
    endpoint: Mapping[str, Any] | None

    @classmethod
    def from_mapping(cls, obj: Any, *, path: str = "egress") -> Egress:
        if not isinstance(obj, Mapping):
            raise ContractError(f"{path} must be an object")
        reject_unknown_keys(obj, ("mode", "endpoint"), path=path)
        mode = req_enum(obj, "mode", EGRESS_MODES, path=path)
        endpoint = req(obj, "endpoint", path=path, allow_null=True)
        if mode == "single_endpoint":
            if endpoint is None:
                raise ContractError(
                    f"{path}: mode='single_endpoint' with endpoint=null is invalid by schema"
                )
            if not isinstance(endpoint, Mapping):
                raise ContractError(f"{path}.endpoint must be an object")
            reject_unknown_keys(
                endpoint,
                ("host", "port", "sni", "pinned_cert_spki", "allowed_methods", "allowed_paths"),
                path=f"{path}.endpoint",
            )
            req_str(endpoint, "host", path=f"{path}.endpoint")
            port = req_int(endpoint, "port", path=f"{path}.endpoint", minimum=1)
            if port > 65535:
                raise ContractError(f"{path}.endpoint.port out of range")
            req_str(endpoint, "sni", path=f"{path}.endpoint")
            req_str(endpoint, "pinned_cert_spki", path=f"{path}.endpoint")
            for name in ("allowed_methods", "allowed_paths"):
                values = req_list(endpoint, name, path=f"{path}.endpoint", min_items=1)
                for index, value in enumerate(values):
                    if not isinstance(value, str) or not value:
                        raise ContractError(f"{path}.endpoint.{name}[{index}] must be a string")
        elif endpoint is not None:
            raise ContractError(
                f"{path}: mode='deny_all' must carry endpoint=null. A disabled allowlist that "
                "still names a host is the configuration that gets accidentally enabled."
            )
        return cls(mode=mode, endpoint=None if endpoint is None else dict(endpoint))

    def allowlist(self) -> tuple[str, ...]:
        """The generated proxy allowlist. Empty is legal **only** under an explicit `deny_all`.

        The two broad `.api.nvidia.com` / `.build.nvidia.com` ACLs are deleted; the allowlist is
        generated from `egress.endpoint` at provisioning time and from nothing else.
        """
        if self.mode == "deny_all":
            return ()
        assert self.endpoint is not None  # noqa: S101 - guaranteed by from_mapping
        host = str(self.endpoint["host"])
        if not host:
            raise ContractError(
                "the proxy refuses to start on an empty allowlist unless mode='deny_all' is "
                "explicit"
            )
        return (f"{host}:{self.endpoint['port']}",)


@dataclass(slots=True)
class HardwareInstance:
    schema_version: str
    instance_id: str
    queue_id: str
    served_categories: tuple[str, ...]
    hardware: Mapping[str, Provenanced]
    limits: Mapping[str, Provenanced]
    runtime: Mapping[str, Provenanced]
    egress: Egress
    telemetry: Mapping[str, Any]
    worker_env: Mapping[str, str]
    unit_resource_profiles: Mapping[str, Mapping[str, Any]]
    verifier_sandbox_profile: Mapping[str, Any]
    model_cache: Mapping[str, str] | None
    public_projection: tuple[str, ...]
    signature: SignatureEnvelope
    raw: Mapping[str, Any]

    # ------------------------------------------------------------------ parsing
    @classmethod
    def from_mapping(cls, raw: Any) -> HardwareInstance:
        if not isinstance(raw, Mapping):
            raise ContractError("a C7 instance must be an object")
        reject_unknown_keys(raw, _TOP_KEYS, path="c7")
        version = req_str(raw, "schema_version", path="c7")
        if version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise ContractError(f"unsupported C7 schema_version {version!r}")

        categories = req_list(raw, "served_categories", path="c7", min_items=1)
        for index, value in enumerate(categories):
            if value not in SERVED_CATEGORIES:
                raise ContractError(
                    f"c7.served_categories[{index}]={value!r} is not a submission category"
                )
        if len(set(categories)) != len(categories):
            raise ContractError("c7.served_categories repeats a category")

        hardware = cls._provenanced_block(
            req(raw, "hardware", path="c7"), _HARDWARE_FIELDS, "hardware"
        )
        limits = cls._provenanced_block(req(raw, "limits", path="c7"), _LIMIT_FIELDS, "limits")
        runtime = cls._provenanced_block(req(raw, "runtime", path="c7"), _RUNTIME_FIELDS, "runtime")

        telemetry_raw = req(raw, "telemetry", path="c7")
        if not isinstance(telemetry_raw, Mapping):
            raise ContractError("c7.telemetry must be an object")
        reject_unknown_keys(
            telemetry_raw,
            (
                "min_coverage_fraction",
                "max_missed_samples",
                "sampling_interval_ms",
                "signature_required",
            ),
            path="c7.telemetry",
        )
        telemetry = {
            "min_coverage_fraction": float(
                req(telemetry_raw, "min_coverage_fraction", path="c7.telemetry")
            ),
            "max_missed_samples": req_int(
                telemetry_raw, "max_missed_samples", path="c7.telemetry", minimum=0
            ),
            "sampling_interval_ms": req_int(
                telemetry_raw, "sampling_interval_ms", path="c7.telemetry", minimum=1
            ),
            "signature_required": req_bool(
                telemetry_raw, "signature_required", path="c7.telemetry"
            ),
        }

        env_raw = req(raw, "worker_env", path="c7")
        if not isinstance(env_raw, Mapping):
            raise ContractError("c7.worker_env must be an object of role -> VARIABLE_NAME")
        worker_env: dict[str, str] = {}
        for role in sorted(env_raw):
            name = req_str(env_raw, role, path="c7.worker_env")
            if not name.isupper() or " " in name:
                raise ContractError(
                    f"c7.worker_env.{role}={name!r} must be an environment variable NAME, not a "
                    "value. C7 names the variables; it never carries their contents."
                )
            worker_env[role] = name
        missing_roles = sorted(set(WORKER_ENV_REQUIRED_ROLES) - set(worker_env))
        if missing_roles:
            raise ContractError(
                f"c7.worker_env does not name {missing_roles}. Every worker variable comes from "
                "the contract; a role C7 leaves out is a role some consumer hard-codes, and a "
                "hard-coded name is a name that drifts. (Required: "
                f"{list(WORKER_ENV_REQUIRED_ROLES)}; extra roles are allowed.) The required set "
                "is hardware.WORKER_ENV_REQUIRED_ROLES and this rule is enforced in "
                "hardware.HardwareInstance.from_mapping."
            )

        profiles_raw = req(raw, "unit_resource_profiles", path="c7")
        if not isinstance(profiles_raw, Mapping) or not profiles_raw:
            raise ContractError("c7.unit_resource_profiles must be a non-empty object")
        profiles = {}
        for profile_id in sorted(profiles_raw):
            body = profiles_raw[profile_id]
            if not isinstance(body, Mapping):
                raise ContractError(f"c7.unit_resource_profiles.{profile_id} must be an object")
            profiles[profile_id] = dict(body)

        sandbox_raw = req(raw, "verifier_sandbox_profile", path="c7")
        if not isinstance(sandbox_raw, Mapping):
            raise ContractError("c7.verifier_sandbox_profile must be an object")
        reject_unknown_keys(
            sandbox_raw,
            ("network", "docker_socket", "credentials", "pids", "output_bytes", "wall_time_sec"),
            path="c7.verifier_sandbox_profile",
        )
        sandbox = {
            "network": req_enum(
                sandbox_raw, "network", ("none",), path="c7.verifier_sandbox_profile"
            ),
            "docker_socket": req_bool(
                sandbox_raw, "docker_socket", path="c7.verifier_sandbox_profile"
            ),
            "credentials": req_bool(sandbox_raw, "credentials", path="c7.verifier_sandbox_profile"),
            "pids": req_int(sandbox_raw, "pids", path="c7.verifier_sandbox_profile", minimum=1),
            "output_bytes": req_int(
                sandbox_raw, "output_bytes", path="c7.verifier_sandbox_profile", minimum=1
            ),
            "wall_time_sec": req_int(
                sandbox_raw, "wall_time_sec", path="c7.verifier_sandbox_profile", minimum=1
            ),
        }
        if sandbox["docker_socket"] or sandbox["credentials"]:
            raise ContractError(
                "the verifier sandbox may not be granted the docker socket or credentials; its "
                "budget is independent of the agent's"
            )

        cache_raw = req(raw, "model_cache", path="c7", allow_null=True)
        model_cache = None
        if cache_raw is not None:
            if not isinstance(cache_raw, Mapping):
                raise ContractError("c7.model_cache must be an object or null")
            reject_unknown_keys(cache_raw, ("mount", "tree_digest"), path="c7.model_cache")
            from .digest import parse_digest  # local import keeps the module import graph flat

            model_cache = {
                "mount": req_str(cache_raw, "mount", path="c7.model_cache"),
                "tree_digest": parse_digest(
                    req(cache_raw, "tree_digest", path="c7.model_cache"),
                    field="c7.model_cache.tree_digest",
                ),
            }

        projection = req_list(raw, "public_projection", path="c7", min_items=1)
        for index, value in enumerate(projection):
            if not isinstance(value, str) or not value:
                raise ContractError(f"c7.public_projection[{index}] must be a dotted path string")

        instance = cls(
            schema_version=version,
            instance_id=req_str(raw, "instance_id", path="c7"),
            queue_id=req_str(raw, "queue_id", path="c7"),
            served_categories=tuple(categories),
            hardware=hardware,
            limits=limits,
            runtime=runtime,
            egress=Egress.from_mapping(req(raw, "egress", path="c7")),
            telemetry=telemetry,
            worker_env=worker_env,
            unit_resource_profiles=profiles,
            verifier_sandbox_profile=sandbox,
            model_cache=model_cache,
            public_projection=tuple(projection),
            signature=SignatureEnvelope.from_mapping(req(raw, "signature", path="c7")),
            raw=dict(raw),
        )
        for dotted in instance.public_projection:
            instance._resolve(dotted)  # a projection naming a nonexistent field is a defect
        return instance

    @staticmethod
    def _provenanced_block(raw: Any, fields: Sequence[str], name: str) -> dict[str, Provenanced]:
        if not isinstance(raw, Mapping):
            raise ContractError(f"c7.{name} must be an object")
        reject_unknown_keys(raw, fields, path=f"c7.{name}")
        out: dict[str, Provenanced] = {}
        for field_name in fields:
            out[field_name] = Provenanced.from_mapping(
                req(raw, field_name, path=f"c7.{name}"), path=f"c7.{name}.{field_name}"
            )
        return out

    # ------------------------------------------------------------------ behaviour
    @property
    def unmeasured_fields(self) -> tuple[str, ...]:
        """Dotted paths of every field this instance has not measured."""
        out: list[str] = []
        for block_name, block in (
            ("hardware", self.hardware),
            ("limits", self.limits),
            ("runtime", self.runtime),
        ):
            for field_name, entry in block.items():
                if not entry.measured:
                    out.append(f"{block_name}.{field_name}")
        return tuple(sorted(out))

    @property
    def rankable(self) -> bool:
        """False whenever any field is unmeasured — for **every** queue this instance serves."""
        return not self.unmeasured_fields

    def rankability_for_queue(self, queue_id: str) -> bool:
        """The frozen wording: an unmeasured field forces `rankable=false` for the queues served."""
        if queue_id != self.queue_id:
            raise ContractError(
                f"instance {self.instance_id!r} serves queue {self.queue_id!r}, not {queue_id!r}"
            )
        return self.rankable

    def serves(self, category: str) -> bool:
        return category in self.served_categories

    @property
    def instance_digest(self) -> str:
        """The digest C2 binds in `bindings.c7_instance_digest` (body without the signature)."""
        return digest_json({k: v for k, v in self.raw.items() if k != "signature"})

    def _resolve(self, dotted: str) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, Mapping) or part not in node:
                raise ContractError(
                    f"public_projection names {dotted!r}, which this instance does not carry"
                )
            node = node[part]
        return node

    def public_view(self) -> dict[str, Any]:
        """Exactly the fields `public_projection` names. The website may publish nothing else."""
        return {dotted: self._resolve(dotted) for dotted in self.public_projection}
