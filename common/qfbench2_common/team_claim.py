"""Team claim: the participant side of "prove your team inside the submission zip".

## Executive summary (read this first)

There is no registration page. A team proves who it is by putting its website **team number**
and **Team Key** into `team-claim.json` beside `submission.json`, once, from the CodaBench
account it will use for every upload; the organizer's intake reads that file in memory on the
account's first upload and links the account. The C5 `team_id` is not assigned by anyone: it is
**derived** from the same pair,

    team_id = "team-" + sha256(b"agenthon2026-team-alias:" + str(team_number).encode()
                               + b":" + team_key.encode()).hexdigest()[:32]

The organizer's `registered_team_admission.derive_team_alias` is the same function; the two
repositories share a test vector so they cannot drift apart unnoticed. The key is hashed exactly
as issued: no trimming, no case folding, no Unicode normalization. A different key is a different
team id.

What this module guarantees about the key: it enters through a hidden prompt or a file the
participant owns, it is written to exactly one place (the `team-claim.json` member of the zip),
and no function here puts it in a message, an exception, a log line or a return value other than
the claim bytes themselves. `qfbench2 submission pack|alias` in `cli.py` is the entry point.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import re
import stat
import zipfile
from collections.abc import Mapping
from typing import Any

from .contracts.descriptor import SubmissionDescriptor, seal_descriptor_digest
from .contracts.errors import ContractError

__all__ = [
    "ALIAS_RE",
    "CLAIM_SCHEMA_VERSION",
    "MAX_KEY_CHARS",
    "MIN_KEY_CHARS",
    "TEAM_CLAIM_FILE",
    "TeamClaimError",
    "build_team_claim",
    "derive_team_alias",
    "pack_submission",
    "read_team_key_file",
    "seal_for_team",
    "validate_team_key",
    "validate_team_number",
]

TEAM_CLAIM_FILE = "team-claim.json"
CLAIM_SCHEMA_VERSION = "1.0"
ALIAS_RE = re.compile(r"^team-[a-f0-9]{32}$")
MIN_KEY_CHARS = 8
MAX_KEY_CHARS = 256
MAX_CLAIM_BYTES = 1024
MAX_TEAM_NUMBER = 2**63 - 1
_ALIAS_PREFIX = b"agenthon2026-team-alias:"
_KEY_FILE_BYTES = 4096


class TeamClaimError(ValueError):
    """Closed diagnostic. Its message never carries the key or any byte of the key file."""


def validate_team_number(value: Any) -> int:
    """A positive integer, and not a bool (which `isinstance(True, int)` would let through)."""
    if type(value) is not int or not 0 < value <= MAX_TEAM_NUMBER:
        raise TeamClaimError("team number must be a positive integer")
    return value


def validate_team_key(value: Any) -> str:
    """The exact issued key: printable, 8..256 characters, no control characters.

    The same character rule the organizer's fingerprint applies, so a key this accepts is a
    key the intake can check. The value is returned unchanged; nothing is stripped.
    """
    if type(value) is not str:
        raise TeamClaimError("team key must be a string")
    if not MIN_KEY_CHARS <= len(value) <= MAX_KEY_CHARS:
        raise TeamClaimError(f"team key must be {MIN_KEY_CHARS}..{MAX_KEY_CHARS} characters")
    if not value.isprintable() or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
        raise TeamClaimError("team key must be printable, with no control characters")
    return value


def derive_team_alias(team_number: int, team_key: str) -> str:
    """The C5 `team_id`: identical to the organizer's `derive_team_alias`, by construction."""
    number = validate_team_number(team_number)
    key = validate_team_key(team_key)
    material = _ALIAS_PREFIX + str(number).encode("ascii") + b":" + key.encode("utf-8")
    return "team-" + hashlib.sha256(material).hexdigest()[:32]


def build_team_claim(team_number: int, team_key: str) -> bytes:
    """The exact bytes of `team-claim.json`: three keys, compact, UTF-8, at most 1024 bytes."""
    number = validate_team_number(team_number)
    key = validate_team_key(team_key)
    raw = json.dumps(
        {"schema_version": CLAIM_SCHEMA_VERSION, "site_team_id": number, "team_key": key},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(raw) > MAX_CLAIM_BYTES:
        raise TeamClaimError("team claim exceeds the organizer's byte bound")
    return raw


def read_team_key_file(path: str | pathlib.Path) -> str:
    """The key alone in a regular file the caller owns (mode 0600), one trailing newline allowed.

    Refuses a symlink, a group/world-readable file, an empty file and anything over 4 KiB.
    The message on refusal names the rule, never the content.
    """
    p = pathlib.Path(path)
    try:
        info = p.lstat()
    except OSError:
        raise TeamClaimError("team key file cannot be read") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise TeamClaimError("team key file must be a regular file, not a link")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise TeamClaimError("team key file must not be readable by group or others (chmod 600)")
    if not 0 < info.st_size <= _KEY_FILE_BYTES:
        raise TeamClaimError("team key file must hold the key alone")
    try:
        raw = p.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise TeamClaimError("team key file must be UTF-8 text") from None
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    return validate_team_key(text)


def seal_for_team(descriptor: Mapping[str, Any], team_number: int, team_key: str) -> dict[str, Any]:
    """Set `team_id` to the derived alias, reseal, and validate the result as a C5.

    A descriptor that already carries a `team_id` must carry the derived one: a disagreeing
    value is refused rather than silently rewritten, because it means the author believes
    their team id is something else and that belief needs correcting, not overwriting.
    """
    if not isinstance(descriptor, Mapping):
        raise TeamClaimError("descriptor must be a JSON object")
    alias = derive_team_alias(team_number, team_key)
    declared = descriptor.get("team_id")
    if declared is not None and declared != alias:
        raise TeamClaimError(
            "descriptor team_id disagrees with the id derived from this team number and key; "
            "remove team_id from the descriptor or check the number and key"
        )
    body = {k: v for k, v in descriptor.items() if k != "descriptor_digest"}
    body["team_id"] = alias
    sealed = seal_descriptor_digest(body)
    try:
        SubmissionDescriptor.from_mapping(sealed)
    except ContractError as exc:
        raise TeamClaimError(f"descriptor is not a valid C5: {exc}") from None
    return sealed


def pack_submission(
    descriptor: Mapping[str, Any],
    team_number: int,
    team_key: str,
    out: str | pathlib.Path,
) -> str:
    """Write `submission.zip` with exactly `submission.json` and `team-claim.json`; return the id.

    The archive is deterministic for the same inputs (fixed timestamps, stored entries, mode
    0644), so two packs of one descriptor produce byte-identical zips. The output file holds
    the key, so it is mode 0600 from its first byte: a symlink or non-regular path is refused,
    a pre-existing regular file is unlinked rather than reused (whoever already had it open,
    or holds another link to it, never sees the new content), and the file is created with
    `os.open(..., O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)` plus `fchmod` so the umask cannot
    widen it. No byte is written before the mode is in place.
    """
    sealed = seal_for_team(descriptor, team_number, team_key)
    claim = build_team_claim(team_number, team_key)
    descriptor_bytes = (json.dumps(sealed, indent=2, sort_keys=True) + "\n").encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, payload in (("submission.json", descriptor_bytes), (TEAM_CLAIM_FILE, claim)):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            entry.compress_type = zipfile.ZIP_STORED
            archive.writestr(entry, payload)
    _write_private_file(pathlib.Path(out), buffer.getvalue())
    return str(sealed["team_id"])


_CREATE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | os.O_TRUNC
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _write_private_file(path: pathlib.Path, payload: bytes) -> None:
    """Create `path` fresh with mode 0600 and write `payload`; never reuse an existing file."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        info = None
    except OSError:
        raise TeamClaimError("output path cannot be written") from None
    if info is not None:
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise TeamClaimError("output path exists and is not a regular file")
        try:
            path.unlink()
        except OSError:
            raise TeamClaimError("output path cannot be replaced") from None
    try:
        fd = os.open(path, _CREATE_FLAGS, 0o600)
    except OSError:
        raise TeamClaimError("output path cannot be created privately") from None
    try:
        os.fchmod(fd, 0o600)
        handle = os.fdopen(fd, "wb")
    except OSError:
        os.close(fd)
        raise TeamClaimError("output file could not be made private") from None
    try:
        with handle:
            handle.write(payload)
    except OSError:
        raise TeamClaimError("output file could not be written") from None
