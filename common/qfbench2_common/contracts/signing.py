"""The frozen signature envelope, the trust store, and fail-closed verification.

## Executive summary (read this first)

Global rule 0.5: *"Signature envelope is fixed now; key custody is not."* Every signed contract
object carries `{alg: "Ed25519", key_id, payload_digest, signed_at, signature}`. The Hub verifies
against a configurable trust store, and **an empty or unconfigured trust store means verification
fails, which means not rankable.** That is the frozen fail-closed default, and it is the single
most important line in this file: there is no code path in which a missing trust store is treated
as "nothing to check".

Three ways verification can be refused, all of them raising `SignatureUnverifiable`:

1. **No verifier configured** — the trust store is empty. Callers treat this as *not rankable*,
   never as *verified*.
2. **Not trusted** — the store has keys but not this `key_id`, or the store is a development
   store and the caller asked for production trust.
3. **Not valid** — the payload digest does not match the payload, the timestamp is outside the
   replay window, or the Ed25519 check fails.

Decision D7 (who holds the attestation key, what the scoring image's trust store contains, how
rotation and revocation reach an offline container, and what the replay window is) belongs to a
named human security owner. Nothing here waits on it: the shape is frozen, the default is closed,
and the value is supplied later.

### Backend

`cryptography` is used when it is installed; otherwise the pure-Python RFC 8032 implementation in
`_ed25519.py` is used. **No dependency was added to `qfbench2-common`** — adding a compiled
dependency that four track repos and the scoring image must install is a supply-chain decision for
the project owner, not a coding agent. `ed25519_backend()` reports which one is live so a C2 or C8
producer can record it.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import _ed25519
from ._time import parse_rfc3339
from .digest import digest_json, jcs_canonical, parse_digest
from .errors import ContractError, req, req_enum, req_str, reject_unknown_keys

__all__ = [
    "SIGNATURE_ALG",
    "SignatureEnvelope",
    "SignatureUnverifiable",
    "TrustStore",
    "VerificationResult",
    "ed25519_backend",
    "sign_payload",
    "verify_signed",
    "verify_signed_object",
]

SIGNATURE_ALG = "Ed25519"
_ENVELOPE_KEYS = ("alg", "key_id", "payload_digest", "signed_at", "signature")
_TRUST_PROFILES = ("production", "development")


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
    """What a successful verification establishes. There is no 'unverified but fine' value."""

    key_id: str
    profile: str
    backend: str
    signed_at: datetime

    @property
    def production_trust(self) -> bool:
        return self.profile == "production"


class TrustStore:
    """key_id -> Ed25519 public key, plus the profile the store speaks for.

    An **empty** store is not an error to construct — an operator legitimately starts with one —
    but it makes every verification fail. That asymmetry is the point: the failure surfaces at the
    moment of verification, where it degrades to "not rankable", rather than at import time where
    somebody would be tempted to skip the call.
    """

    def __init__(
        self,
        keys: Mapping[str, bytes] | None = None,
        *,
        profile: str = "production",
        label: str = "",
    ) -> None:
        if profile not in _TRUST_PROFILES:
            raise ContractError(f"trust store profile must be one of {list(_TRUST_PROFILES)}")
        self._keys: dict[str, bytes] = {}
        self.profile = profile
        self.label = label
        for key_id, material in (keys or {}).items():
            self.add(key_id, material)

    def add(self, key_id: str, public_key: bytes) -> None:
        if not isinstance(key_id, str) or not key_id:
            raise ContractError("key_id must be a non-empty string")
        if not isinstance(public_key, (bytes, bytearray)):
            raise ContractError("public key material must be bytes")
        if len(public_key) != _ed25519.PUBLIC_KEY_BYTES:
            raise ContractError(
                f"Ed25519 public keys are {_ed25519.PUBLIC_KEY_BYTES} bytes, got {len(public_key)}"
            )
        self._keys[key_id] = bytes(public_key)

    @property
    def is_empty(self) -> bool:
        return not self._keys

    def key_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._keys))

    def get(self, key_id: str) -> bytes | None:
        return self._keys.get(key_id)

    @classmethod
    def empty(cls) -> TrustStore:
        """The unconfigured store. Every verification against it fails, by design."""
        return cls({}, profile="production", label="unconfigured")

    @classmethod
    def from_mapping(cls, obj: Any, *, path: str = "trust_store") -> TrustStore:
        """Load `{profile, label, keys: {key_id: base64-32-bytes}}`."""
        if not isinstance(obj, Mapping):
            raise ContractError(f"{path} must be an object")
        reject_unknown_keys(obj, ("profile", "label", "keys"), path=path)
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
        return cls(keys, profile=profile, label=req_str(obj, "label", path=path, allow_empty=True))

    @classmethod
    def load(cls, path: str | Path) -> TrustStore:
        return cls.from_mapping(json.loads(Path(path).read_text(encoding="utf-8")))


def verify_signed(
    payload: Any,
    envelope: SignatureEnvelope | Mapping[str, Any],
    trust_store: TrustStore,
    *,
    now: datetime | None = None,
    max_age: timedelta | None = None,
    require_production_trust: bool = True,
) -> VerificationResult:
    """Verify `envelope` over `payload`, or raise `SignatureUnverifiable`.

    `payload` is the contract object **without** its `signature` member; the digest is taken over
    its RFC 8785 canonical form, so the signature binds the meaning of the object and not one
    producer's whitespace.

    `require_production_trust=True` (the default) refuses a development trust store. The dev store
    shipped in `contracts/fixtures/` exists so the golden fixtures are verifiable in tests; its
    seed is public, so anything it accepts is forgeable, and production must never load it.
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
    contain a digest of itself.
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


def sign_payload(payload: Any, *, seed: bytes, key_id: str, signed_at: str) -> SignatureEnvelope:
    """Sign a payload with a raw 32-byte seed. **Synthetic fixtures and tests only.**

    Production signing happens in the Runner's privileged helper against custodied key material
    (decision D7). This function exists so the golden fixtures shipped in this package carry a real
    envelope that the test suite can verify end to end, rather than a hand-typed placeholder that
    proves nothing.
    """
    digest = digest_json(payload)
    parse_rfc3339(signed_at, field="signed_at")
    signature = _ed25519.sign(seed, _signing_input(SIGNATURE_ALG, key_id, digest, signed_at))
    return SignatureEnvelope(
        alg=SIGNATURE_ALG,
        key_id=key_id,
        payload_digest=digest,
        signed_at=signed_at,
        signature=base64.b64encode(signature).decode("ascii"),
    )
