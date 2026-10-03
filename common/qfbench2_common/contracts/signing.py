"""The frozen signature envelope, the trust store, and fail-closed verification.

## Executive summary (read this first)

Global rule 0.5: *"Signature envelope is fixed now; key custody is not."* Every signed contract
object carries `{alg: "Ed25519", key_id, payload_digest, signed_at, signature}`. The Hub verifies
against a configurable trust store, and **an empty or unconfigured trust store means verification
fails, which means not rankable.** That is the frozen fail-closed default, and it is the single
most important line in this file: there is no code path in which a missing trust store is treated
as "nothing to check".

Four ways verification can be refused, all of them raising `SignatureUnverifiable`:

1. **No verifier configured** — the trust store is empty. Callers treat this as *not rankable*,
   never as *verified*.
2. **Not trusted** — the store has keys but not this `key_id`, or the store is a development
   store and the caller asked for production trust.
3. **Not trusted for this purpose** — the store binds the key to purposes, and the document being
   verified is not one of them (see "Key purposes" below).
4. **Not valid** — the payload digest does not match the payload, the timestamp is outside the
   replay window, or the Ed25519 check fails.

Decision D7 (who holds the attestation key, what the scoring image's trust store contains, how
rotation and revocation reach an offline container, and what the replay window is) belongs to a
named human security owner. Nothing here waits on it: the shape is frozen, the default is closed,
and the value is supplied later.

### Key purposes

A trust store maps `key_id` to a public key. Without more, every key in it verifies every kind of
signed document: a run-record key on a fleet host could sign an evaluation plan, and the scorer
would accept it. So a store may bind each key to the purposes it is trusted for, and every
verification names the purpose it verifies for:

| Purpose | Verifies |
|---|---|
| `c1` | C1 evaluation plans, the Track 2 forecast protocol, the stage-budget policy |
| `c2` | C2 run records, and the run-time receipts that bind them |
| `c6` | C6 sealed-dataset resolver descriptors |
| `c7` | C7 hardware instances |
| `c8` | C8 release evidence |
| `heartbeat` | worker heartbeats |
| `archive` | the Track 2 close archive manifest |

* **A production store must bind every key.** `purposes` is required when `profile` is
  `production` and the store holds any key, and a production verification names its purpose or
  is refused.
* **A development store may bind none,** and then every key verifies every document, exactly as
  before. That keeps every Development artifact, and the trust store every Development bundle
  ships, byte-identical. A development store that does bind purposes is held to them.
* **Host keys sign only host evidence.** `c2` and `heartbeat` are signed by keys that live on fleet
  hosts. A key holding either may hold no other purpose, so no host key can sign a plan, a hardware
  instance, a release or an archive.

The purpose is a property of the trust store and of the verifier, not of the signature: the frozen
envelope is unchanged, and so is every signature already made.

### Backend

`cryptography` is used when it is installed, for verification and for signing; otherwise the
pure-Python RFC 8032 implementation in `_ed25519.py` is used. Ed25519 is deterministic, so both
backends produce the same signature for the same seed and message. **No dependency was added to
`qfbench2-common`** — adding a compiled dependency that four track repos and the scoring image must
install is a supply-chain decision for the project owner. A production signer
that holds a real key passes `require_constant_time=True` to refuse the pure-Python fallback, whose
scalar multiplication branches on the secret. `ed25519_backend()` reports which
backend is live so a C2 or C8 producer can record it.
"""

from __future__ import annotations

import base64
import importlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any

from . import _ed25519
from ._time import parse_rfc3339
from .digest import digest_json, jcs_canonical, parse_digest
from .errors import ContractError, req, req_enum, req_str, reject_unknown_keys

__all__ = [
    "HOST_PURPOSES",
    "SIGNATURE_ALG",
    "TRUST_PURPOSES",
    "SignatureEnvelope",
    "SignatureUnverifiable",
    "TrustStore",
    "VerificationResult",
    "derive_public_key",
    "ed25519_backend",
    "sign_payload",
    "verify_signed",
    "verify_signed_object",
]

SIGNATURE_ALG = "Ed25519"
_ENVELOPE_KEYS = ("alg", "key_id", "payload_digest", "signed_at", "signature")
_TRUST_PROFILES = ("production", "development")
_TRUST_STORE_KEYS = ("profile", "label", "keys", "purposes")

#: The closed set of purposes a trust-store key may hold, and the documents each one verifies.
#: A verifier names exactly one of these; a store that binds purposes refuses a verification that
#: names none, and a name outside this set is refused rather than read as "any".
TRUST_PURPOSES: Mapping[str, str] = MappingProxyType(
    {
        "c1": "C1 evaluation plans, the Track 2 forecast protocol and the stage-budget policy",
        "c2": "C2 run records and the run-time receipts that bind them",
        "c6": "C6 sealed-dataset resolver descriptors",
        "c7": "C7 hardware instances",
        "c8": "C8 release evidence",
        "heartbeat": "worker heartbeats",
        "archive": "the Track 2 close archive manifest",
    }
)

#: Purposes signed by keys that live on fleet hosts, inside the reach of anything that drives the
#: host's Docker daemon. A key holding one of these may hold no purpose outside this set, so a
#: compromised host can forge its own run-time evidence and nothing else.
HOST_PURPOSES = frozenset({"c2", "heartbeat"})

_CONSTANT_TIME_REQUIRED = (
    "this caller requires the compiled Ed25519 primitive from `cryptography`, and it is not "
    "installed. The pure-Python fallback is not constant time -- its scalar multiplication "
    "branches on the bits of the secret scalar -- so it is refused for a key that must stay secret "
    "on a shared host. Install `cryptography` where this key is used."
)


class SignatureUnverifiable(ContractError):
    """Verification did not succeed, for any reason. Callers treat this as *not rankable*.

    Deliberately one type. A caller that branches on "unknown key" versus "bad signature" versus
    "no trust store" is a caller that will eventually let one of the three through; the reason is
    carried in the message for operators, not in the type for control flow.
    """


def ed25519_backend() -> str:
    """`"cryptography"` when the compiled primitive is installed, else `"pure-python-rfc8032"`."""
    try:  # pragma: no cover - depends on what the host happens to have installed
        import cryptography  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return "pure-python-rfc8032"
    return "cryptography"


def _signing_input(alg: str, key_id: str, payload_digest: str, signed_at: str) -> bytes:
    """The exact bytes an Ed25519 signature covers: the envelope minus the signature itself.

    Signing only `payload_digest` would leave `signed_at` and `key_id` unauthenticated, and a
    replay window enforced on an attacker-editable timestamp is not a replay window. Canonicalizing
    the four fields with JCS keeps the preimage identical across implementations.
    """
    return jcs_canonical(
        {"alg": alg, "key_id": key_id, "payload_digest": payload_digest, "signed_at": signed_at}
    )


def _raw_verify(public_key: bytes, signature: bytes, message: bytes) -> bool:
    try:  # pragma: no cover - the compiled path is not exercised on the dev host
        from cryptography.exceptions import (  # type: ignore[import-not-found]
            InvalidSignature,
        )
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore[import-not-found]
            Ed25519PublicKey,
        )
    except ImportError:
        return _ed25519.verify(public_key, signature, message)
    try:  # pragma: no cover
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    except (InvalidSignature, ValueError):
        return False
    return True


def _check_seed(seed: Any) -> bytes:
    if not isinstance(seed, (bytes, bytearray)) or len(seed) != 32:
        raise ValueError("an Ed25519 seed is exactly 32 bytes")
    return bytes(seed)


class _CompiledKey:
    """A `cryptography` Ed25519 private key, reduced to the two operations this module needs."""

    __slots__ = ("_key", "_serialization")

    def __init__(self, key: Any, serialization: Any) -> None:  # pragma: no cover
        self._key, self._serialization = key, serialization

    def sign(self, message: bytes) -> bytes:  # pragma: no cover
        return bytes(self._key.sign(message))

    def public_bytes(self) -> bytes:  # pragma: no cover
        return bytes(
            self._key.public_key().public_bytes(
                self._serialization.Encoding.Raw, self._serialization.PublicFormat.Raw
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - never shows the key
        return "<compiled Ed25519 key>"


def _compiled_private_key(seed: bytes) -> Any | None:
    """`cryptography`'s Ed25519 private key for `seed`, or `None` when it is not installed.

    The one place a secret-key operation chooses its backend, so the choice can be tested without
    the compiled package present. The result has `sign(message)` and `public_bytes()`.
    """
    try:  # pragma: no cover - depends on what the host happens to have installed
        ed25519 = importlib.import_module("cryptography.hazmat.primitives.asymmetric.ed25519")
        serialization = importlib.import_module("cryptography.hazmat.primitives.serialization")
    except ImportError:
        return None
    return _CompiledKey(
        ed25519.Ed25519PrivateKey.from_private_bytes(seed),  # pragma: no cover
        serialization,
    )


def derive_public_key(seed: bytes, *, require_constant_time: bool = False) -> bytes:
    """The 32-byte Ed25519 public key for a 32-byte seed.

    Deriving it multiplies the base point by the secret scalar, so it is a secret-key operation
    like signing: `cryptography` is used when installed, and `require_constant_time=True` refuses
    the pure-Python fallback.
    """
    seed = _check_seed(seed)
    private = _compiled_private_key(seed)
    if private is None:
        if require_constant_time:
            raise ContractError(_CONSTANT_TIME_REQUIRED)
        return _ed25519.public_key_from_seed(seed)
    return bytes(private.public_bytes())


def _raw_sign(seed: bytes, message: bytes, *, require_constant_time: bool) -> bytes:
    seed = _check_seed(seed)
    private = _compiled_private_key(seed)
    if private is None:
        if require_constant_time:
            raise ContractError(_CONSTANT_TIME_REQUIRED)
        return _ed25519.sign(seed, message)
    return bytes(private.sign(message))


@dataclass(frozen=True, slots=True)
class SignatureEnvelope:
    """`{alg, key_id, payload_digest, signed_at, signature}` — the frozen §0.5 envelope."""

    alg: str
    key_id: str
    payload_digest: str
    signed_at: str
    signature: str

    @classmethod
    def from_mapping(cls, obj: Any, *, path: str = "signature") -> SignatureEnvelope:
        if not isinstance(obj, Mapping):
            raise ContractError(f"{path} must be an object, got {type(obj).__name__}")
        reject_unknown_keys(obj, _ENVELOPE_KEYS, path=path)
        alg = req_enum(obj, "alg", (SIGNATURE_ALG,), path=path)
        signature = req_str(obj, "signature", path=path)
        try:
            raw = base64.b64decode(signature, validate=True)
        except (ValueError, TypeError) as exc:
            raise ContractError(f"{path}.signature is not valid base64: {exc}") from exc
        if len(raw) != _ed25519.SIGNATURE_BYTES:
            raise ContractError(
                f"{path}.signature decodes to {len(raw)} bytes; Ed25519 signatures are 64"
            )
        envelope = cls(
            alg=alg,
            key_id=req_str(obj, "key_id", path=path),
            payload_digest=parse_digest(
                req(obj, "payload_digest", path=path), field=f"{path}.payload_digest"
            ),
            signed_at=req_str(obj, "signed_at", path=path),
            signature=signature,
        )
        parse_rfc3339(envelope.signed_at, field=f"{path}.signed_at")
        return envelope

    def to_mapping(self) -> dict[str, str]:
        return {
            "alg": self.alg,
            "key_id": self.key_id,
            "payload_digest": self.payload_digest,
            "signed_at": self.signed_at,
            "signature": self.signature,
        }

    @property
    def signature_bytes(self) -> bytes:
        return base64.b64decode(self.signature, validate=True)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """What a successful verification establishes. There is no 'unverified but fine' value.

    `purpose` is the purpose the verifier named, or `None` for a verification that named none
    against a development store that binds no purposes.
    """

    key_id: str
    profile: str
    backend: str
    signed_at: datetime
    purpose: str | None = None

    @property
    def production_trust(self) -> bool:
        return self.profile == "production"


def _parse_purposes(value: Any, *, key_id: str, path: str) -> frozenset[str]:
    """One key's purposes: a non-empty list of distinct names from `TRUST_PURPOSES`.

    A string is refused rather than iterated: `"c1"` must never become `{"c", "1"}`.
    """
    if value is None:
        raise ContractError(
            f"{path}: key {key_id!r} names no purposes. A store that binds purposes binds every "
            "key it holds; a key trusted for nothing does not belong in it"
        )
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set, frozenset)):
        raise ContractError(
            f"{path}: the purposes of key {key_id!r} must be a list of names, got "
            f"{type(value).__name__}"
        )
    names = list(value)
    if not names:
        raise ContractError(
            f"{path}: key {key_id!r} names no purposes. A key trusted for nothing does not belong "
            "in the store"
        )
    for name in names:
        if not isinstance(name, str) or name not in TRUST_PURPOSES:
            raise ContractError(
                f"{path}: {name!r} (key {key_id!r}) is not a trust purpose; the purposes are "
                f"{sorted(TRUST_PURPOSES)}"
            )
    if len(set(names)) != len(names):
        raise ContractError(f"{path}: key {key_id!r} names a purpose twice")
    held = frozenset(names)
    host = held & HOST_PURPOSES
    if host and held - HOST_PURPOSES:
        raise ContractError(
            f"{path}: key {key_id!r} holds {sorted(host)} together with "
            f"{sorted(held - HOST_PURPOSES)}. A key that signs run-time evidence on a host "
            f"({sorted(HOST_PURPOSES)}) may hold no other purpose, so a compromised host cannot "
            "sign a plan, a hardware instance, a release or an archive"
        )
    return held


class TrustStore:
    """key_id -> Ed25519 public key, the purposes each key is trusted for, and the store's profile.

    An **empty** store is not an error to construct — an operator legitimately starts with one —
    but it makes every verification fail. That asymmetry is the point: the failure surfaces at the
    moment of verification, where it degrades to "not rankable", rather than at import time where
    somebody would be tempted to skip the call.

    `purposes` maps every key id to the purposes it is trusted for (see the module docstring). It
    is **required** for a production store that holds any key, so a production store that trusts a
    key for everything cannot be built at all; an empty production store binds every key later
    added to it. A development store may omit it; it then binds nothing and every key verifies
    every document, as before purposes existed.
    """

    def __init__(
        self,
        keys: Mapping[str, bytes] | None = None,
        *,
        profile: str = "production",
        label: str = "",
        purposes: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        if profile not in _TRUST_PROFILES:
            raise ContractError(f"trust store profile must be one of {list(_TRUST_PROFILES)}")
        keys = dict(keys or {})
        if purposes is None and profile == "production":
            if keys:
                raise ContractError(
                    "a production trust store must bind every key to the purposes it is trusted "
                    f"for (`purposes`, one or more of {sorted(TRUST_PURPOSES)} per key). Without "
                    "them a run-record key would also verify plans and hardware instances"
                )
            # An empty production store holds no key to bind, and still binds every key added.
            purposes = {}
        if purposes is not None:
            if not isinstance(purposes, Mapping):
                raise ContractError(
                    "purposes must map each key id to the list of purposes it is trusted for"
                )
            unbound = sorted(set(keys) - set(purposes))
            if unbound:
                raise ContractError(f"purposes names no purposes for key(s) {unbound}")
            stray = sorted(str(name) for name in set(purposes) - set(keys))
            if stray:
                raise ContractError(f"purposes names key(s) {stray} that the store does not hold")
        self._keys: dict[str, bytes] = {}
        self._purposes: dict[str, frozenset[str]] | None = None if purposes is None else {}
        self.profile = profile
        self.label = label
        for key_id, material in keys.items():
            self.add(key_id, material, purposes=None if purposes is None else purposes[key_id])

    def add(self, key_id: str, public_key: bytes, *, purposes: Iterable[str] | None = None) -> None:
        """Add one key. A store that binds purposes needs this key's; one that does not, refuses
        them. Nothing is changed when the key is refused.

        A key id is added once: its material and purposes are never changed in place. A store
        that binds purposes also holds each public key under one id only. Under two ids, one key
        would hold the purposes of both, and the rule that a host key holds no organizer purpose
        would not hold: a host's run-record key filed a second time as an organizer key would
        sign plans.
        """
        if not isinstance(key_id, str) or not key_id:
            raise ContractError("key_id must be a non-empty string")
        if not isinstance(public_key, (bytes, bytearray)):
            raise ContractError("public key material must be bytes")
        if len(public_key) != _ed25519.PUBLIC_KEY_BYTES:
            raise ContractError(
                f"Ed25519 public keys are {_ed25519.PUBLIC_KEY_BYTES} bytes, got {len(public_key)}"
            )
        if key_id in self._keys:
            raise ContractError(
                f"key_id {key_id!r} is already in this store. A key's material and purposes are "
                "set once, when it is added; to change them, build a new store"
            )
        material = bytes(public_key)
        if self._purposes is None:
            if purposes is not None:
                raise ContractError(
                    "this store binds no key to a purpose, so purposes cannot be given for one "
                    "key; build the store with `purposes` for every key instead"
                )
        else:
            held = _parse_purposes(purposes, key_id=key_id, path="trust_store.purposes")
            twins = sorted(name for name, known in self._keys.items() if known == material)
            if twins:
                raise ContractError(
                    f"key_id {key_id!r} names the same public key as {twins}. A store that binds "
                    "purposes holds each public key under one id, so that one key cannot hold "
                    "the purposes of two"
                )
            self._purposes[key_id] = held
        self._keys[key_id] = material

    @property
    def is_empty(self) -> bool:
        return not self._keys

    @property
    def binds_purposes(self) -> bool:
        """True when every key is bound to its purposes; always True for a production store."""
        return self._purposes is not None

    def key_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._keys))

    def get(self, key_id: str) -> bytes | None:
        return self._keys.get(key_id)

    def purposes_of(self, key_id: str) -> tuple[str, ...] | None:
        """The purposes `key_id` is trusted for, sorted; `()` for a key this store does not hold.

        `None` means this store binds no purposes at all (a development store without them).
        """
        if self._purposes is None:
            return None
        return tuple(sorted(self._purposes.get(key_id, frozenset())))

    def to_mapping(self) -> dict[str, Any]:
        """The `trust_store.json` document for this store; `from_mapping` reads it back."""
        document: dict[str, Any] = {
            "profile": self.profile,
            "label": self.label,
            "keys": {
                key_id: base64.b64encode(material).decode("ascii")
                for key_id, material in sorted(self._keys.items())
            },
        }
        if self._purposes is not None:
            document["purposes"] = {
                key_id: sorted(held) for key_id, held in sorted(self._purposes.items())
            }
        return document

    @classmethod
    def empty(cls) -> TrustStore:
        """The unconfigured store. Every verification against it fails, by design."""
        return cls({}, profile="production", label="unconfigured", purposes={})

    @classmethod
    def from_mapping(cls, obj: Any, *, path: str = "trust_store") -> TrustStore:
        """Load `{profile, label, keys: {key_id: base64-32-bytes}, purposes: {key_id: [...]}}`.

        `purposes` is required when `profile` is `production` and the store holds any key, and
        optional otherwise.
        """
        if not isinstance(obj, Mapping):
            raise ContractError(f"{path} must be an object")
        reject_unknown_keys(obj, _TRUST_STORE_KEYS, path=path)
        profile = req_enum(obj, "profile", _TRUST_PROFILES, path=path)
        raw_keys = obj.get("keys")
        if not isinstance(raw_keys, Mapping):
            raise ContractError(f"{path}.keys must be an object of key_id -> base64 public key")
        keys: dict[str, bytes] = {}
        for key_id, material in raw_keys.items():
            if not isinstance(material, str):
                raise ContractError(f"{path}.keys.{key_id} must be a base64 string")
            try:
                keys[key_id] = base64.b64decode(material, validate=True)
            except (ValueError, TypeError) as exc:
                raise ContractError(f"{path}.keys.{key_id} is not valid base64: {exc}") from exc
        purposes: Mapping[str, Any] | None = None
        if "purposes" in obj:
            purposes = obj["purposes"]
            if not isinstance(purposes, Mapping):
                raise ContractError(
                    f"{path}.purposes must be an object of key_id -> list of purposes"
                )
        elif profile == "production" and keys:
            raise ContractError(
                f"{path} is a production trust store without `purposes`. A production store "
                "binds every key it holds to the purposes it is trusted for, one or more of "
                f"{sorted(TRUST_PURPOSES)}"
            )
        return cls(
            keys,
            profile=profile,
            label=req_str(obj, "label", path=path, allow_empty=True),
            purposes=purposes,
        )

    @classmethod
    def load(cls, path: str | Path) -> TrustStore:
        """Read `trust_store.json`. A document that names one member twice is refused: the JSON
        parser would keep the last, and the store would trust what its reviewer never read."""
        text = Path(path).read_text(encoding="utf-8")
        try:
            document = json.loads(
                text, object_pairs_hook=_unique_members, parse_constant=_no_constant
            )
        except ValueError as exc:
            raise ContractError(f"{path} is not valid JSON: {exc}") from exc
        return cls.from_mapping(document)


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for name, value in pairs:
        if name in document:
            raise ContractError(f"a trust store document names {name!r} twice")
        document[name] = value
    return document


def _no_constant(name: str) -> Any:
    raise ContractError(f"a trust store document carries the non-finite number {name}")


def _require_purpose(trust_store: TrustStore, key_id: str, purpose: str | None) -> None:
    """Refuse a key that the store does not trust for `purpose`. Called once the key is known."""
    if purpose is not None and (not isinstance(purpose, str) or purpose not in TRUST_PURPOSES):
        raise SignatureUnverifiable(
            f"{purpose!r} is not a trust purpose; the purposes are {sorted(TRUST_PURPOSES)}"
        )
    held = trust_store.purposes_of(key_id)
    if held is None:
        if trust_store.profile == "production":
            # Not reachable through the constructor, which refuses a production store without
            # purposes; reachable only by editing a store after it was built.
            raise SignatureUnverifiable(
                "this production trust store binds no key to a purpose, so it cannot say what "
                "any key is trusted for"
            )
        return
    if purpose is None:
        raise SignatureUnverifiable(
            "this trust store binds every key to the purposes it is trusted for, and the caller "
            f"named none. A verification against it names one of {sorted(TRUST_PURPOSES)}; "
            "without one, a run-record key would verify a plan"
        )
    if purpose not in held:
        raise SignatureUnverifiable(
            f"key_id {key_id!r} is trusted for {list(held)} only, not for {purpose!r} "
            f"({TRUST_PURPOSES[purpose]})"
        )


def verify_signed(
    payload: Any,
    envelope: SignatureEnvelope | Mapping[str, Any],
    trust_store: TrustStore,
    *,
    now: datetime | None = None,
    max_age: timedelta | None = None,
    require_production_trust: bool = True,
    purpose: str | None = None,
) -> VerificationResult:
    """Verify `envelope` over `payload`, or raise `SignatureUnverifiable`.

    `payload` is the contract object **without** its `signature` member; the digest is taken over
    its RFC 8785 canonical form, so the signature binds the meaning of the object and not one
    producer's whitespace.

    `require_production_trust=True` (the default) refuses a development trust store. The dev store
    shipped in `contracts/fixtures/` exists so the golden fixtures are verifiable in tests; its
    seed is public, so anything it accepts is forgeable, and production must never load it.

    `purpose` is what the caller verifies for, one of `TRUST_PURPOSES`. A store that binds
    purposes (every production store) refuses a key that does not hold it, and refuses a call that
    names none. The contract objects' own verifiers name theirs: `EvaluationPlan.verify_signature`
    names `c1` and `RunRecord.verify_attestation` names `c2`.
    """
    if isinstance(envelope, Mapping):
        envelope = SignatureEnvelope.from_mapping(envelope)
    if trust_store.is_empty:
        raise SignatureUnverifiable(
            "no verifier configured: the trust store holds no keys, so this signature cannot be "
            "checked. Per frozen rule 0.5 that is a verification FAILURE and the result is not "
            "rankable — it is never a pass."
        )
    if require_production_trust and trust_store.profile != "production":
        raise SignatureUnverifiable(
            f"trust store profile is {trust_store.profile!r}; a development store is forgeable by "
            "anyone and may not establish production trust"
        )
    public_key = trust_store.get(envelope.key_id)
    if public_key is None:
        raise SignatureUnverifiable(
            f"key_id {envelope.key_id!r} is not in the trust store "
            f"(known: {list(trust_store.key_ids())})"
        )
    _require_purpose(trust_store, envelope.key_id, purpose)
    actual = digest_json(payload)
    if actual != envelope.payload_digest:
        raise SignatureUnverifiable(
            f"payload_digest mismatch: envelope says {envelope.payload_digest}, the canonical "
            f"payload hashes to {actual}"
        )
    signed_at = parse_rfc3339(envelope.signed_at, field="signature.signed_at")
    if max_age is not None:
        reference = now or datetime.now(tz=signed_at.tzinfo)
        if reference - signed_at > max_age:
            raise SignatureUnverifiable(
                f"signature is older than the {max_age} replay window (signed at {envelope.signed_at})"
            )
        if signed_at - reference > timedelta(minutes=5):
            raise SignatureUnverifiable(
                f"signature is dated in the future ({envelope.signed_at}); refusing"
            )
    message = _signing_input(
        envelope.alg, envelope.key_id, envelope.payload_digest, envelope.signed_at
    )
    if not _raw_verify(public_key, envelope.signature_bytes, message):
        raise SignatureUnverifiable(f"Ed25519 verification failed for key_id {envelope.key_id!r}")
    return VerificationResult(
        key_id=envelope.key_id,
        profile=trust_store.profile,
        backend=ed25519_backend(),
        signed_at=signed_at,
        purpose=purpose,
    )


def verify_signed_object(
    obj: Mapping[str, Any],
    trust_store: TrustStore,
    *,
    member: str = "signature",
    **kwargs: Any,
) -> VerificationResult:
    """Verify a contract object that carries its own envelope under `member`.

    The signed payload is the object with `member` removed — never the whole object, which cannot
    contain a digest of itself. Every keyword of `verify_signed`, `purpose` included, passes
    through.
    """
    if not isinstance(obj, Mapping):
        raise ContractError("a signed contract object must be a JSON object")
    if member not in obj:
        raise SignatureUnverifiable(
            f"the object carries no {member!r} member; an unsigned contract object is not "
            "rankable (frozen rule 0.1: absent is never satisfied)"
        )
    payload = {k: v for k, v in obj.items() if k != member}
    return verify_signed(payload, obj[member], trust_store, **kwargs)


def sign_payload(
    payload: Any, *, seed: bytes, key_id: str, signed_at: str, require_constant_time: bool = False
) -> SignatureEnvelope:
    """Sign a payload with a raw 32-byte seed.

    The golden fixtures shipped in this package are signed here, so they carry a real envelope the
    test suite verifies end to end, and so are the Runner's records, through its custodied key
    sources. `cryptography` signs when it is installed. A production signer passes
    `require_constant_time=True`, which refuses the pure-Python fallback. The
    signature is the same either way: Ed25519 is deterministic.
    """
    digest = digest_json(payload)
    parse_rfc3339(signed_at, field="signed_at")
    signature = _raw_sign(
        seed,
        _signing_input(SIGNATURE_ALG, key_id, digest, signed_at),
        require_constant_time=require_constant_time,
    )
    return SignatureEnvelope(
        alg=SIGNATURE_ALG,
        key_id=key_id,
        payload_digest=digest,
        signed_at=signed_at,
        signature=base64.b64encode(signature).decode("ascii"),
    )
