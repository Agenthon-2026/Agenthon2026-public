"""One timestamp grammar for every contract: RFC 3339, UTC, explicit `Z`.

This is a module rather than a convention for a measured reason. A bare `YYYY-MM-DD` compared
lexically against a value of another type raised an uncaught `TypeError` on live input, and under
the pre-fix scoring driver an uncaught exception aborted the whole run. Contract timestamps are
therefore parsed into `datetime` objects with a fixed grammar, never compared as strings.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from .errors import ContractError

__all__ = ["RFC3339_RE", "format_rfc3339", "parse_rfc3339"]

RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")


def parse_rfc3339(value: object, *, field: str) -> datetime:
    """Parse `2026-08-21T12:00:00Z`. A local time, a numeric offset, or a bare date is refused.

    Refusing `+00:00` as well as `-04:00` is deliberate: two spellings of the same instant produce
    two different canonical serializations and therefore two different digests.
    """
    if not isinstance(value, str):
        raise ContractError(
            f"{field} must be an RFC 3339 timestamp string, got {type(value).__name__}"
        )
    if not RFC3339_RE.match(value):
        raise ContractError(
            f"{field}={value!r} is not RFC 3339 UTC with a literal 'Z' "
            "(e.g. 2026-08-21T12:00:00Z); bare dates and numeric offsets are refused"
        )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_rfc3339(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
