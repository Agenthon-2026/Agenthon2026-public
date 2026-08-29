"""RFC 8785 (JCS) canonicalization and the one way a digest is computed.

## Executive summary (read this first)

Global rule 0.2 of the frozen contract set: **digests are computed one way** — `sha256` over the
RFC 8785 JSON Canonicalization Scheme serialization of the named structure, with paths inside any
digested structure NFC-normalized and sorted code-point ascending. "Whatever `json.dumps` did" is
explicitly ruled out, because two independent implementations must agree byte-for-byte or every
sealed phase becomes an organizer fault.

Three public entry points:

* `jcs_canonical(obj) -> bytes`      the canonical serialization itself
* `digest_json(obj) -> "sha256:..."` sha256 of that serialization
* `digest_tree(entries) -> "sha256:..."` the C3 sanitized-tree digest

### What JCS actually requires, and where the traps are

1. **Object keys sort by UTF-16 code unit**, not by code point. For everything in the Basic
   Multilingual Plane the two agree; they disagree for astral characters (U+1F600 sorts *before*
   U+FF01 by code unit and *after* it by code point). Implemented by sorting on
   `key.encode("utf-16-be")`.
2. **Strings are emitted as UTF-8, not `\\u`-escaped.** Only `"`, `\\` and C0 controls are escaped,
   using the short forms `\\b \\f \\n \\r \\t` where they exist and `\\u00xx` otherwise. Python's
   `json.dumps` defaults to `ensure_ascii=True`, which is wrong here.
3. **Numbers use the ECMAScript `Number::toString` grammar**, which is *not* Python's `repr`.
   Python writes `1e+16` where ECMAScript writes `10000000000000000`, and Python writes `1e-05`
   where ECMAScript writes `0.00001`. `_es_number` implements the ES algorithm on top of Python's
   shortest round-trip digits.
4. **NaN and infinity are not JSON numbers** and are refused rather than emitted as literals.
5. `1` and `1.0` are the *same* number and serialize identically to `1`. That is what makes the
   round-trip property tests meaningful: differently shaped inputs must produce one digest.

### The tree digest preimage is fixed, deliberately

`digest_tree` refuses an entry that does not carry exactly
`{path, size_bytes, sha256, mode_bits, num_rows}`. A digest whose preimage depends on which
optional keys a producer happened to include is not a digest two implementations can agree on, so
`num_rows` is required-and-nullable (`null` for anything that is not parquet) rather than optional.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .errors import ContractError

__all__ = [
    "DIGEST_RE",
    "TREE_ENTRY_KEYS",
    "digest_json",
    "digest_tree",
    "is_digest",
    "jcs_canonical",
    "normalize_tree_path",
    "parse_digest",
    "sha256_bytes",
]

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

#: The exact key set of a digested C3 tree entry. Fixed so the preimage cannot drift.
TREE_ENTRY_KEYS = ("path", "size_bytes", "sha256", "mode_bits", "num_rows")

_MAX_EXACT_INT = 2**53 - 1

_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


# --------------------------------------------------------------------------- numbers
def _shortest_digits(x: float) -> tuple[str, int]:
    """Return `(digits, n)` with `x == 0.<digits> * 10**n`, `digits` free of leading/trailing zeros.

    Python's `repr` already produces the shortest string that round-trips, which is exactly the
    `k`/`s` pair the ECMAScript algorithm asks for; this only reshapes it.
    """
    r = repr(x)
    if "e" in r or "E" in r:
        mantissa, _, exponent = r.replace("E", "e").partition("e")
        exp = int(exponent)
    else:
        mantissa, exp = r, 0
    int_part, _, frac_part = mantissa.partition(".")
    raw = int_part + frac_part
    stripped = raw.lstrip("0")
    leading_zeros = len(raw) - len(stripped)
    n = len(int_part) + exp - leading_zeros
    digits = stripped.rstrip("0")
    if not digits:  # pragma: no cover - only reachable for zero, handled by the caller
        return "0", 1
    return digits, n


def _es_number(x: float) -> str:
    """ECMAScript `Number::toString(x)` for a finite double, as RFC 8785 §3.2.2.3 requires."""
    if math.isnan(x) or math.isinf(x):
        raise ContractError(f"{x!r} is not a JSON number; NaN and infinity cannot be canonicalized")
    if x == 0:
        return "0"  # ECMAScript renders -0 as "0" too
    if x < 0:
        return "-" + _es_number(-x)
    digits, n = _shortest_digits(x)
    k = len(digits)
    if k <= n <= 21:
        return digits + "0" * (n - k)
    if 0 < n <= 21:
        return digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return "0." + "0" * (-n) + digits
    exponent = n - 1
    sign = "+" if exponent >= 0 else "-"
    head = digits if k == 1 else digits[0] + "." + digits[1:]
    return f"{head}e{sign}{abs(exponent)}"


def _number(value: int | float) -> str:
    if isinstance(value, int):
        if abs(value) > _MAX_EXACT_INT:
            raise ContractError(
                f"integer {value} exceeds the IEEE-754 exact range; RFC 8785 numbers are doubles, "
                "so this value cannot be canonicalized without loss. Carry it as a string."
            )
        return str(value)
    return _es_number(float(value))


# --------------------------------------------------------------------------- strings
def _string(value: str) -> str:
    out = ['"']
    for ch in value:
        escape = _ESCAPES.get(ch)
        if escape is not None:
            out.append(escape)
        elif ch < "\x20":
            out.append(f"\\u{ord(ch):04x}")
        elif "\ud800" <= ch <= "\udfff":
            raise ContractError(
                "lone surrogate in a string; the value is not valid Unicode and has no "
                "canonical UTF-8 form"
            )
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _utf16_sort_key(key: str) -> bytes:
    """RFC 8785 sorts object members by UTF-16 code unit, which big-endian bytes reproduce."""
    return key.encode("utf-16-be", errors="strict")


# --------------------------------------------------------------------------- serializer
def _serialize(value: Any, *, path: str) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, Mapping):
        members = []
        for key in sorted(value, key=_utf16_sort_key):
            if not isinstance(key, str):
                raise ContractError(f"object key {key!r} at {path} is not a string")
            members.append(_string(key) + ":" + _serialize(value[key], path=f"{path}.{key}"))
        return "{" + ",".join(members) + "}"
    if isinstance(value, (list, tuple)):
        return (
            "["
            + ",".join(_serialize(item, path=f"{path}[{i}]") for i, item in enumerate(value))
            + "]"
        )
    raise ContractError(
        f"{type(value).__name__} at {path} has no JSON form; canonicalize plain JSON types only"
    )


def jcs_canonical(obj: Any) -> bytes:
    """Serialize `obj` to its RFC 8785 canonical UTF-8 form."""
    return _serialize(obj, path="$").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def digest_json(obj: Any) -> str:
    """`sha256:` digest of the RFC 8785 canonical form of `obj`."""
    return sha256_bytes(jcs_canonical(obj))


def is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(DIGEST_RE.match(value))


def parse_digest(value: Any, *, field: str) -> str:
    """Validate a `sha256:<64 lowercase hex>` string. Empty and null are refused (C6)."""
    if not isinstance(value, str):
        raise ContractError(f"{field} must be a digest string, got {type(value).__name__}")
    if not DIGEST_RE.match(value):
        raise ContractError(
            f"{field}={value!r} is not 'sha256:<64 lowercase hex>'; bare hex, uppercase hex, "
            "other algorithms and the empty string are all refused"
        )
    return value


# --------------------------------------------------------------------------- paths and trees
_FORBIDDEN_COMPONENTS = {"", ".", ".."}


def normalize_tree_path(raw: Any, *, field: str = "path") -> str:
    """NFC-normalize and validate one relative path inside a digested structure.

    Refuses: a non-string, an absolute path, a Windows drive or backslash separator, `.`/`..`/empty
    components, a trailing slash, and any C0/C1 control character. The returned string is the NFC
    form joined with `/`, which is the only spelling that enters a digest.
    """
    if not isinstance(raw, str):
        raise ContractError(f"{field} must be a string, got {type(raw).__name__}")
    if not raw:
        raise ContractError(f"{field} must not be empty")
    if "\\" in raw:
        raise ContractError(f"{field}={raw!r} contains a backslash; separators are '/' only")
    if raw.startswith("/"):
        raise ContractError(f"{field}={raw!r} is absolute; digested paths are relative to the root")
    if re.match(r"^[A-Za-z]:", raw):
        raise ContractError(f"{field}={raw!r} carries a drive letter")
    normalized = unicodedata.normalize("NFC", raw)
    components = normalized.split("/")
    for component in components:
        if component in _FORBIDDEN_COMPONENTS:
            raise ContractError(
                f"{field}={raw!r} has an empty, '.' or '..' component; paths must be normalized "
                "before they are digested, never normalized by the consumer"
            )
        if any(ch < "\x20" or "\x7f" <= ch <= "\x9f" for ch in component):
            raise ContractError(f"{field}={raw!r} contains a control character")
    return "/".join(components)


def _collision_check(paths: Sequence[str]) -> None:
    """Reject NFC collisions and case-insensitive collisions (frozen C3 requirement).

    Both directions matter. A macOS-built fixture folds `A.txt`/`a.txt` together while the Linux
    workers do not, so a tree that a case-insensitive host cannot even represent must not be the
    tree that scores on a case-sensitive one.
    """
    seen: dict[str, str] = {}
    for path in paths:
        if path in seen:
            raise ContractError(f"duplicate path {path!r} in a digested tree")
        seen[path] = path
    folded: dict[str, str] = {}
    for path in paths:
        key = path.casefold()
        if key in folded and folded[key] != path:
            raise ContractError(
                f"case-insensitive collision between {folded[key]!r} and {path!r}; refused so a "
                "tree cannot score on Linux and vanish on macOS"
            )
        folded.setdefault(key, path)
    decomposed: dict[str, str] = {}
    for path in paths:
        key = unicodedata.normalize("NFD", path)
        if key in decomposed and decomposed[key] != path:
            raise ContractError(
                f"unicode collision between {decomposed[key]!r} and {path!r} after normalization"
            )
        decomposed.setdefault(key, path)


def digest_tree(entries: Iterable[Mapping[str, Any]]) -> str:
    """C3 tree digest: sha256 over the JCS form of the entries, sorted by NFC path.

    Each entry must carry exactly `TREE_ENTRY_KEYS`. Paths are NFC-normalized, validated, checked
    for NFC and case-insensitive collisions, then sorted **code-point ascending** — note that this
    is the path sort from global rule 0.2, and it is a different rule from the UTF-16 member sort
    RFC 8785 applies to object keys. Both are implemented; do not conflate them.
    """
    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ContractError(f"tree entry {index} is not an object")
        missing = [k for k in TREE_ENTRY_KEYS if k not in entry]
        extra = sorted(set(entry) - set(TREE_ENTRY_KEYS))
        if missing or extra:
            raise ContractError(
                f"tree entry {index} must carry exactly {list(TREE_ENTRY_KEYS)}; "
                f"missing={missing} unexpected={extra}. The digest preimage is fixed: an optional "
                "key would make two implementations disagree."
            )
        path = normalize_tree_path(entry["path"], field=f"entries[{index}].path")
        size = entry["size_bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ContractError(f"entries[{index}].size_bytes must be a non-negative integer")
        mode = entry["mode_bits"]
        if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o7777:
            raise ContractError(f"entries[{index}].mode_bits must be an integer in [0, 0o7777]")
        rows = entry["num_rows"]
        if rows is not None and (isinstance(rows, bool) or not isinstance(rows, int) or rows < 0):
            raise ContractError(f"entries[{index}].num_rows must be a non-negative integer or null")
        normalized.append(
            {
                "path": path,
                "size_bytes": size,
                "sha256": parse_digest(entry["sha256"], field=f"entries[{index}].sha256"),
                "mode_bits": mode,
                "num_rows": rows,
            }
        )
    _collision_check([e["path"] for e in normalized])
    normalized.sort(key=lambda e: e["path"])
    return digest_json(normalized)
