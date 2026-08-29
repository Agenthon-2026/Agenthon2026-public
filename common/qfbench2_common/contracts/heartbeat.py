"""The worker heartbeat — a signed preflight report bound to one C7 instance.

## Executive summary (read this first)

A queue that exists and has no worker accepts submissions and never runs them. A queue that has a
worker running the *wrong* image, the wrong runtime, or with no scratch root accepts submissions
and runs them wrongly. Neither state is visible from the platform's own view of the queue, so the
C8 publish gate needs evidence from the other end of it: a document the worker itself produced,
signed, saying what it found when it looked at its own host.

That document is `WorkerHeartbeat`, and this module is where it lives.

### Why the shape lives here

The Runner produces this document and the CodaBench publish gate consumes it, which makes it an
interface between two programs rather than a local evidence object belonging to either. A shape
defined in the consumer is a shape the producer has to reverse-engineer from the consumer's parser,
so it is defined here, once, for both.

Three things follow from defining it here, each for a stated reason:

* the version field is `schema_version` (`"1.0.0"`), matching every other contract document,
  rather than a bespoke `schema: "agenthon2026.worker_heartbeat/1"` string;
* `worker_image_digest` and `c7_instance_digest` go through `parse_digest`, so a non-digest cannot
  be recorded in a field whose entire job is to be compared to a digest;
* the *compatibility* rules — does this heartbeat describe the instance it claims to describe? —
  moved onto the object as `compatibility_objections()`, so the Runner can check its own report
  before signing it instead of discovering the mismatch in someone else's publish gate.

### What binds it

`c7_instance_digest` is `HardwareInstance.instance_digest` — the JCS digest of the C7 body without
its signature, the same value C2 binds in `bindings.c7_instance_digest`. That is the whole point of
the binding: a heartbeat is not evidence about "a worker on queue X", it is evidence about *the
host described by this exact C7 document*. Edit one provenance field in C7 and every heartbeat
bound to the old body stops matching, which is the correct outcome — the operator changed what they
were claiming about the hardware and the worker has not re-attested to the new claim.

Verification is the frozen §0.5 envelope over the document minus `signature`, so
`verify_signed_object(doc, trust_store)` is the whole of it. An empty trust store fails closed,
exactly as everywhere else.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ._time import parse_rfc3339
from .digest import parse_digest
from .errors import ContractError, req, req_str, reject_unknown_keys, strict_bool
from .hardware import EGRESS_MODES, HardwareInstance
from .signing import SignatureEnvelope

__all__ = [
    "HEARTBEAT_PREFLIGHT_KEYS",
    "HEARTBEAT_SCHEMA_VERSION",
    "WorkerHeartbeat",
]

HEARTBEAT_SCHEMA_VERSION = "1.0.0"

#: The exact preflight key set. Closed, like every other contract vocabulary: a worker that has
#: something extra to report needs a contract version, not an extra key nobody validates.
HEARTBEAT_PREFLIGHT_KEYS = (
    "runtime",
    "gpu_device_pinned",
    "scratch_root_present",
    "egress_mode",
    "docker_server_version",
)

_TOP_KEYS = (
    "schema_version",
    "queue_id",
    "worker_id",
    "worker_image_digest",
    "c7_instance_digest",
    "preflight",
    "observed_at",
    "signature",
)


@dataclass(frozen=True, slots=True)
class WorkerHeartbeat:
    """One worker's signed statement about its own host, bound to one C7 instance."""

    schema_version: str
    queue_id: str
    worker_id: str
    worker_image_digest: str
    c7_instance_digest: str
    preflight: Mapping[str, Any]
    observed_at: datetime
    signature: SignatureEnvelope
    raw: Mapping[str, Any]

    # ------------------------------------------------------------------ parsing
    @classmethod
    def from_mapping(cls, raw: Any) -> WorkerHeartbeat:
        if not isinstance(raw, Mapping):
            raise ContractError("a worker heartbeat must be an object")
        reject_unknown_keys(raw, _TOP_KEYS, path="heartbeat")
        version = req_str(raw, "schema_version", path="heartbeat")
        if version.split(".")[0] != HEARTBEAT_SCHEMA_VERSION.split(".")[0]:
            raise ContractError(
                f"unsupported worker-heartbeat schema_version {version!r}; this build implements "
                f"{HEARTBEAT_SCHEMA_VERSION}"
            )

        pre_raw = req(raw, "preflight", path="heartbeat")
        if not isinstance(pre_raw, Mapping):
            raise ContractError("heartbeat.preflight must be an object")
        reject_unknown_keys(pre_raw, HEARTBEAT_PREFLIGHT_KEYS, path="heartbeat.preflight")
        preflight = {
            "runtime": req_str(pre_raw, "runtime", path="heartbeat.preflight"),
            # `strict_bool`, not truthiness. A worker reporting "true" as a *string* is a worker
            # whose report was hand-assembled, and the entire value of a preflight is that it was
            # not: it is supposed to be what a program observed, not what a person typed.
            "gpu_device_pinned": strict_bool(
                req(pre_raw, "gpu_device_pinned", path="heartbeat.preflight"),
                field="heartbeat.preflight.gpu_device_pinned",
            ),
            "scratch_root_present": strict_bool(
                req(pre_raw, "scratch_root_present", path="heartbeat.preflight"),
                field="heartbeat.preflight.scratch_root_present",
            ),
            "egress_mode": req_str(pre_raw, "egress_mode", path="heartbeat.preflight"),
            "docker_server_version": req_str(
                pre_raw, "docker_server_version", path="heartbeat.preflight"
            ),
        }
        if preflight["egress_mode"] not in EGRESS_MODES:
            raise ContractError(
                f"heartbeat.preflight.egress_mode={preflight['egress_mode']!r} is not a C7 egress "
                f"mode {list(EGRESS_MODES)}; the enum is closed and is shared with C7 so the two "
                "can be compared at all"
            )

        observed_at = req_str(raw, "observed_at", path="heartbeat")
        return cls(
            schema_version=version,
            queue_id=req_str(raw, "queue_id", path="heartbeat"),
            worker_id=req_str(raw, "worker_id", path="heartbeat"),
            worker_image_digest=parse_digest(
                req(raw, "worker_image_digest", path="heartbeat"),
                field="heartbeat.worker_image_digest",
            ),
            c7_instance_digest=parse_digest(
                req(raw, "c7_instance_digest", path="heartbeat"),
                field="heartbeat.c7_instance_digest",
            ),
            preflight=preflight,
            observed_at=parse_rfc3339(observed_at, field="heartbeat.observed_at"),
            signature=SignatureEnvelope.from_mapping(req(raw, "signature", path="heartbeat")),
            raw=dict(raw),
        )

    # ------------------------------------------------------------------ behaviour
    def compatibility_objections(
        self,
        instance: HardwareInstance,
        *,
        now: datetime | None = None,
        max_age: timedelta | None = None,
    ) -> tuple[str, ...]:
        """Every reason this heartbeat is not evidence for `instance`. Empty means it is.

        A list rather than a first-failure raise, so an operator staring at a refused publication
        sees all of it at once instead of fixing one thing per run.

        Signature verification is **not** here, deliberately. It needs a trust store, it is the
        same call for every signed contract object (`verify_signed_object`), and folding it in
        would let a caller believe a heartbeat that returned `()` had been authenticated when the
        caller never supplied a store. These are the *content* checks; the signature is the
        caller's separate, unavoidable step.
        """
        reasons: list[str] = []
        if self.queue_id != instance.queue_id:
            reasons.append(
                f"heartbeat serves queue {self.queue_id!r}, the instance serves "
                f"{instance.queue_id!r}"
            )
        if self.c7_instance_digest != instance.instance_digest:
            reasons.append(
                f"heartbeat is bound to C7 instance {self.c7_instance_digest}, but the supplied "
                f"instance digests to {instance.instance_digest}. The worker attested to a "
                "different description of this hardware than the one being published."
            )
        if max_age is not None:
            reference = now or datetime.now(tz=self.observed_at.tzinfo)
            if reference - self.observed_at > max_age:
                reasons.append(
                    f"heartbeat was observed at {self.raw['observed_at']}, outside the {max_age} "
                    "window; a stale preflight describes a host that may no longer exist"
                )
        if not self.preflight["scratch_root_present"]:
            reasons.append(
                "the worker reports no scratch root. Raw participant output would have nowhere "
                "outside the ingestion output root to live, and unsanitized bytes inside that "
                "root are mounted into the scoring stage as input/res."
            )
        expected_runtime = instance.runtime["unit"].value
        if expected_runtime is None:
            reasons.append(
                "the C7 instance has not measured runtime.unit, so there is nothing for the "
                "worker's reported unit runtime to agree with"
            )
        elif self.preflight["runtime"] != expected_runtime:
            reasons.append(
                f"the worker runs units under {self.preflight['runtime']!r}; the C7 instance "
                f"declares {expected_runtime!r}"
            )
        if self.preflight["egress_mode"] != instance.egress.mode:
            reasons.append(
                f"the worker reports egress {self.preflight['egress_mode']!r}; the C7 instance "
                f"declares {instance.egress.mode!r}"
            )
        gpu_uuid = instance.hardware["gpu_uuid"]
        if gpu_uuid.measured and not self.preflight["gpu_device_pinned"]:
            reasons.append(
                "the C7 instance pins a GPU by UUID but the worker reports no pinned device; "
                "R-5 selection by UUID is not something the worker can be assumed into"
            )
        return tuple(reasons)

    def assert_compatible(self, instance: HardwareInstance, **kwargs: Any) -> None:
        reasons = self.compatibility_objections(instance, **kwargs)
        if reasons:
            raise ContractError(
                f"worker heartbeat {self.worker_id!r} is not evidence for C7 instance "
                f"{instance.instance_id!r}: " + "; ".join(reasons)
            )

    def signed_payload(self) -> dict[str, Any]:
        """The §0.5 payload: the document without its `signature` member."""
        return {k: v for k, v in self.raw.items() if k != "signature"}

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return (
            f"<WorkerHeartbeat {self.worker_id!r} queue={self.queue_id!r} "
            f"observed_at={self.raw.get('observed_at')}>"
        )
