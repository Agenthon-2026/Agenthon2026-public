"""Contract errors and the strict accessor.

## Executive summary (read this first)

Global rule 0.1 of the frozen contract set says: **an absent field is an error, never a satisfied
constraint.** This module is the mechanical form of that sentence. `req(obj, key)` reads a field and
raises when it is missing; there is no defaulting accessor anywhere in `qfbench2_common.contracts`,
and `dict.get(key, default)` against a contract object is a defect.

Three exception types, and the distinction between them is the whole fault-attribution model:

* `ContractError`   — the bytes do not form the contract. Neither side is blamed yet.
* `ParticipantFailure` — the participant's own artifact is at fault. Consumes the C1 failure score,
  stays in the C1 denominator.
* `OrganizerFault`  — organizer or infrastructure is at fault. Produces **no** participant score;
  at whole-evaluation scope it aborts rather than publishing a partial leaderboard.

`ParticipantFailure` and `OrganizerFault` both derive from `ContractError` so a caller that only
wants "this did not parse" can catch one type, while a caller that must attribute blame catches the
two subtypes *first*. Order your `except` clauses accordingly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

__all__ = [
    "ContractError",
    "OrganizerFault",
    "ParticipantFailure",
    "req",
    "req_bool",
    "req_enum",
    "req_float",
    "req_int",
    "req_list",
    "req_mapping",
    "req_str",
    "reject_unknown_keys",
    "strict_bool",
]

T = TypeVar("T")


class ContractError(Exception):
    """A contract object is absent, malformed, or violates a frozen invariant."""


class ParticipantFailure(ContractError):
    """The participant's artifact is at fault.

    The unit still occupies its slot in the C1 roster and receives the plan's committed
    worst-case score `W`. It is never dropped from the denominator.
    """


class OrganizerFault(ContractError):
    """Organizer or infrastructure is at fault.

    Produces no participant score. Per the frozen C1 `organizer_failure` policy the scope is
    `abort_whole_evaluation`: a partial leaderboard is never published.
    """


def _where(path: str | None) -> str:
    return f" at {path}" if path else ""


def req(obj: Any, key: str, *, path: str | None = None, allow_null: bool = False) -> Any:
    """Read `obj[key]` strictly. Absent key, non-mapping, or (by default) null -> `ContractError`.

    This is the *only* sanctioned way to read a contract field. It refuses a non-mapping, a
    missing key, and an explicit JSON `null` — a null is an absent value wearing a costume, and
    treating it as "present but empty" is how fail-open defaults get reintroduced.

    `allow_null=True` is how a legitimately nullable field (C2 `lifecycle.exit_code`,
    C7 `egress.endpoint`, a non-parquet `num_rows`) is read: the *key* must still be present,
    only its value may be null.
    """
    if not isinstance(obj, Mapping):
        raise ContractError(
            f"expected a JSON object to read {key!r} from{_where(path)}, got {type(obj).__name__}"
        )
    if key not in obj:
        raise ContractError(f"required field {key!r} is absent{_where(path)}")
    value = obj[key]
    if value is None and not allow_null:
        raise ContractError(f"required field {key!r} is null{_where(path)}")
    return value


def reject_unknown_keys(obj: Mapping[str, Any], allowed: Sequence[str], *, path: str) -> None:
    """Closed vocabulary. Any key outside `allowed` is an error, never an ignored extension.

    `additionalProperties: false` in Python. What its absence cost, measured: an
    unsupported future descriptor was silently accepted.
    """
    extra = sorted(set(obj) - set(allowed))
    if extra:
        raise ContractError(f"unknown field(s) {extra} at {path}; the vocabulary is closed")


def req_str(obj: Any, key: str, *, path: str | None = None, allow_empty: bool = False) -> str:
    value = req(obj, key, path=path)
    if not isinstance(value, str):
        raise ContractError(f"{key!r} must be a string{_where(path)}, got {type(value).__name__}")
    if not allow_empty and not value:
        raise ContractError(f"{key!r} must not be empty{_where(path)}")
    return value


def req_enum(obj: Any, key: str, allowed: Sequence[str], *, path: str | None = None) -> str:
    """Closed enum (global rule 0.3). An unrecognized value is an error, never an 'other' bucket."""
    value = req_str(obj, key, path=path)
    if value not in allowed:
        raise ContractError(
            f"{key!r}={value!r} is not one of {sorted(allowed)}{_where(path)}; the enum is closed"
        )
    return value


def strict_bool(value: Any, *, field: str, path: str | None = None) -> bool:
    """A JSON boolean, and nothing else.

    C8 makes this normative: "every boolean is a JSON boolean, and any string in a boolean
    position is a hard failure — no truthy/falsey strings". `1`, `0`, `"true"`, `"false"` and
    `"no"` are all refused. Note `isinstance(True, int)` is True in Python, so the int branch must
    be checked *after* bool, which is why this helper exists rather than an inline `isinstance`.
    """
    if not isinstance(value, bool):
        raise ContractError(
            f"{field!r} must be a JSON boolean{_where(path)}, got "
            f"{type(value).__name__} {value!r}; truthy strings and 0/1 are refused"
        )
    return value


def req_bool(obj: Any, key: str, *, path: str | None = None) -> bool:
    return strict_bool(req(obj, key, path=path), field=key, path=path)


def req_int(obj: Any, key: str, *, path: str | None = None, minimum: int | None = None) -> int:
    value = req(obj, key, path=path)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{key!r} must be an integer{_where(path)}, got {value!r}")
    if minimum is not None and value < minimum:
        raise ContractError(f"{key!r} must be >= {minimum}{_where(path)}, got {value}")
    return value


def req_float(obj: Any, key: str, *, path: str | None = None) -> float:
    """A finite JSON number. NaN and infinity are refused at the contract boundary."""
    value = req(obj, key, path=path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{key!r} must be a number{_where(path)}, got {value!r}")
    out = float(value)
    if out != out or out in (float("inf"), float("-inf")):
        raise ContractError(f"{key!r} must be finite{_where(path)}, got {value!r}")
    return out


def req_list(obj: Any, key: str, *, path: str | None = None, min_items: int = 0) -> list[Any]:
    value = req(obj, key, path=path)
    if not isinstance(value, list):
        raise ContractError(f"{key!r} must be an array{_where(path)}, got {type(value).__name__}")
    if len(value) < min_items:
        raise ContractError(f"{key!r} must hold at least {min_items} item(s){_where(path)}")
    return value


def req_mapping(obj: Any, key: str, *, path: str | None = None) -> Mapping[str, Any]:
    value = req(obj, key, path=path)
    if not isinstance(value, Mapping):
        raise ContractError(f"{key!r} must be an object{_where(path)}, got {type(value).__name__}")
    for k in value:
        if not isinstance(k, str):
            raise ContractError(f"{key!r} has a non-string key {k!r}{_where(path)}")
    return value
