"""Ed25519 (RFC 8032) in pure Python, used only when no compiled primitive is installed.

## Executive summary (read this first)

The frozen contract set fixes the signature envelope as Ed25519 and requires the Hub to implement
verification now, without waiting for the security owner. The pinned dependency set of
`qfbench2-common` contains no Ed25519 primitive (`cryptography` and `PyNaCl` are both absent), and
adding a compiled dependency to a package four track repos and a scoring image install is a
supply-chain decision that is not a coding agent's to make. So this module implements RFC 8032
from the specification, in the standard library alone, and `signing.py` prefers `cryptography`
whenever it happens to be installed.

**Verification only is security-relevant here, and verification is public-data arithmetic**: there
is no secret to leak through timing, so the usual "never hand-roll crypto" objection about
side channels does not bite. `sign()` exists for one purpose — generating the *synthetic dev*
fixtures shipped in `contracts/fixtures/` and the signatures in the test suite. Production signing
belongs to the Runner's privileged helper with real key custody; see decision D7.

Correctness is pinned by the RFC 8032 §7.1 test vectors in
`common/tests/contracts/test_signing.py`, including the empty message, a one-byte message, a
two-byte message, and a 1023-byte message. A pure-Python implementation that reproduces those
vectors byte-for-byte is the same function as a compiled one.
"""

from __future__ import annotations

import hashlib

__all__ = ["PUBLIC_KEY_BYTES", "SIGNATURE_BYTES", "public_key_from_seed", "sign", "verify"]

PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)

# Extended twisted-Edwards coordinates (X, Y, Z, T) with x = X/Z, y = Y/Z, x*y = T/Z.
_Point = tuple[int, int, int, int]
_IDENTITY: _Point = (0, 1, 1, 0)


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _add(p: _Point, q: _Point) -> _Point:
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = ((y1 - x1) * (y2 - x2)) % _P
    b = ((y1 + x1) * (y2 + x2)) % _P
    c = (2 * t1 * t2 * _D) % _P
    d = (2 * z1 * z2) % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return ((e * f) % _P, (g * h) % _P, (f * g) % _P, (e * h) % _P)


def _double(p: _Point) -> _Point:
    return _add(p, p)


def _scalar_mult(p: _Point, scalar: int) -> _Point:
    result = _IDENTITY
    addend = p
    while scalar > 0:
        if scalar & 1:
            result = _add(result, addend)
        addend = _double(addend)
        scalar >>= 1
    return result


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _SQRT_M1) % _P
    if (x * x - xx) % _P != 0:
        return None
    if x == 0 and sign:
        return None
    if x & 1 != sign:
        x = _P - x
    return x


_BASE_Y = (4 * pow(5, _P - 2, _P)) % _P
_BASE_X = _recover_x(_BASE_Y, 0)
assert _BASE_X is not None  # noqa: S101 - a wrong curve constant must not be a runtime surprise
_BASE: _Point = (_BASE_X, _BASE_Y, 1, (_BASE_X * _BASE_Y) % _P)


def _decode_point(data: bytes) -> _Point | None:
    if len(data) != 32:
        return None
    value = int.from_bytes(data, "little")
    sign = value >> 255
    y = value & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, (x * y) % _P)


def _encode_point(p: _Point) -> bytes:
    x, y, z, _ = p
    z_inv = pow(z, _P - 2, _P)
    x = (x * z_inv) % _P
    y = (y * z_inv) % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _equal(p: _Point, q: _Point) -> bool:
    x1, y1, z1, _ = p
    x2, y2, z2, _ = q
    return (x1 * z2 - x2 * z1) % _P == 0 and (y1 * z2 - y2 * z1) % _P == 0


def _secret_scalar(seed: bytes) -> tuple[int, bytes]:
    h = _sha512(seed)
    clamped = bytearray(h[:32])
    clamped[0] &= 248
    clamped[31] &= 127
    clamped[31] |= 64
    return int.from_bytes(clamped, "little"), h[32:]


def public_key_from_seed(seed: bytes) -> bytes:
    """Derive the 32-byte public key from a 32-byte seed. Test/fixture use only."""
    if len(seed) != 32:
        raise ValueError("an Ed25519 seed is exactly 32 bytes")
    scalar, _ = _secret_scalar(seed)
    return _encode_point(_scalar_mult(_BASE, scalar))


def sign(seed: bytes, message: bytes) -> bytes:
    """Produce a 64-byte Ed25519 signature. **Synthetic fixtures and tests only.**"""
    if len(seed) != 32:
        raise ValueError("an Ed25519 seed is exactly 32 bytes")
    scalar, prefix = _secret_scalar(seed)
    encoded_a = _encode_point(_scalar_mult(_BASE, scalar))
    r = int.from_bytes(_sha512(prefix + message), "little") % _L
    encoded_r = _encode_point(_scalar_mult(_BASE, r))
    k = int.from_bytes(_sha512(encoded_r + encoded_a + message), "little") % _L
    s = (r + k * scalar) % _L
    return encoded_r + s.to_bytes(32, "little")


def verify(public_key: bytes, signature: bytes, message: bytes) -> bool:
    """Return True iff `signature` is a valid Ed25519 signature of `message` under `public_key`.

    Returns False rather than raising for every malformed input: a wrong-length key, a
    non-canonical point, and an out-of-range scalar `S` are all "not a valid signature", and a
    caller that has to distinguish them is a caller that will eventually treat one of them as a
    pass. The non-canonical-`S` check (`S < L`) is what rejects the classic malleability variant.
    """
    if len(public_key) != PUBLIC_KEY_BYTES or len(signature) != SIGNATURE_BYTES:
        return False
    a = _decode_point(public_key)
    if a is None:
        return False
    r_point = _decode_point(signature[:32])
    if r_point is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    k = int.from_bytes(_sha512(signature[:32] + public_key + message), "little") % _L
    return _equal(_scalar_mult(_BASE, s), _add(r_point, _scalar_mult(a, k)))
