"""qfbench2-common — the shared evaluation harness for Agenthon 2026 / QFBench 2.0.

The SAME package is pip-installed (pinned at a tagged release of the main repo) by every
track repo, public and private, so dev-phase smoke tests and final-phase sealed scoring
run identical code.

Modules:
    contracts       the frozen C1-C8 interface (contract set 1.1.0) — start here
    taskcard        parse + validate card.toml (task-card v2)
    manifest        per-file checksum / license / public-safety checks
    leakage         cutoff, embargo, network-isolation, verdict-only canary scanning
    verifier        hierarchical admissibility gates -> score
    failure_labels  cross-track failure-mode taxonomy + JSONL reporter
    smoke           public smoke-test runner
    scoring/        per-track metrics (passk, crps, stylized_facts, faithfulness, bootstrap)

## Build identity (frozen decision D5) — read this before recording provenance

`__version__` is a **human label**. It is not, and cannot be made into, an identity for the
running code. `importlib.metadata` resolves the *distribution* installed in the environment, not
the module that was actually imported, so a modified vendored copy of `qfbench2_common` on
`PYTHONPATH` reports whatever version an unrelated `site-packages` distribution happens to carry.
That is not hypothetical: it was executed, and a forked copy reported `2.1.0`. Three further
disagreements were live on the development machine at the same time — an editable install frozen
at `2.1.0` against a `pyproject.toml` saying `2.3.0`, a HEAD 465 insertions past its own tag still
reporting that tag's version, and a historical `v2.1.0` tag shipping version `2.0.0`.

So: **never populate a C2 or C8 provenance field from `__version__`.** Use `build_identity()`,
which reports a `source_tree_digest` stamped into the package at build time, and
`verify_build_identity()`, which recomputes that digest from the bytes on disk. A version string
is unfalsifiable by construction; a digest over the shipped tree is exactly what a vendored fork
cannot forge, which is why C8 records a digest and not a version.

### `source_tree_digest` vs the C8 `distribution_digest` — two names now, deliberately

These are two different digests and they were briefly both called `distribution_digest`, in two
contracts, meaning two things. They are not interchangeable and neither can be computed from the
other:

| Name | Covers | Computed by |
|---|---|---|
| `source_tree_digest` (here) | the shipped **package tree** — the bytes actually imported | code inside the wheel, about itself |
| `distribution_digest` (C8) | the built **wheel file**'s sha256 | the release job, from outside the wheel |

No code inside a wheel can compute its own wheel's sha256 — the value would have to be a member of
the bytes it hashes. That is why the running code attests to its source tree and the release job
records the artifact digest, and why one name for both was a bug waiting for the first auditor who
compared them and found they disagreed.
"""

from __future__ import annotations

import importlib.metadata as _im
import json as _json
import pathlib as _pathlib
import warnings as _warnings
from typing import Any as _Any

from . import contracts, failure_labels, leakage, manifest, scoring, taskcard, verifier

# Derived, never written twice. This was a hardcoded literal, and it drifted from
# pyproject.toml -- the same failure that produced a `v2.1.0` git tag shipping version 2.0.0.
# A version declared in two places is a version that will eventually disagree with itself.
#
# Deriving it removed the *drift within one install*. It did not, and could not, make it an
# identity: see the module docstring, and use build_identity() for anything that must be trusted.
try:  # installed (the normal case, incl. editable installs)
    __version__ = _im.version("qfbench2-common")
except _im.PackageNotFoundError:  # a bare source checkout that was never installed
    __version__ = "0+unknown"

# --------------------------------------------------------------------------- build identity (D5)

#: Filename of the build stamp, written into the package directory by the release job and shipped
#: inside the wheel. A JSON data file rather than a generated module: it needs no import machinery,
#: it is trivially inspectable in an installed tree, and it cannot execute.
_BUILD_STAMP_FILE = "_build_stamp.json"

#: Version of the stamp format itself, so a future field addition is a detectable change rather
#: than a silently-ignored key.
BUILD_STAMP_VERSION = "1.0.0"

_STAMP_KEYS = ("stamp_version", "version", "source_tree_digest", "source_sha", "stamped_at")

#: Anything under the package directory that is not part of its shipped identity. `__pycache__`
#: contents differ between two installs of identical source, and the stamp cannot contain a digest
#: of itself.
_DIGEST_EXCLUDED_DIRS = frozenset({"__pycache__"})
_DIGEST_EXCLUDED_SUFFIXES = (".pyc", ".pyo")


class BuildIdentityError(RuntimeError):
    """The build stamp is absent, malformed, or does not describe the bytes on disk."""


def _package_dir() -> _pathlib.Path:
    return _pathlib.Path(__file__).resolve().parent


def package_tree_digest(pkg_dir: str | _pathlib.Path | None = None) -> str:
    """`sha256:...` over the shipped bytes of the package directory.

    Computed exactly as global rule 0.2 requires — sha256 over the RFC 8785 (JCS) canonical JSON
    of the NFC-normalized, code-point-sorted `[{path, sha256}]` list — using the one shared
    implementation in `contracts.digest`, so an independent reimplementation must agree byte for
    byte.

    Deliberately **not** `contracts.digest_tree`: that preimage carries `mode_bits` and `num_rows`,
    which are properties of a C3 participant tree. Mode bits differ between a git checkout, an
    unpacked wheel and an installed tree under a restrictive umask, so including them would make
    the build identity unreproducible for exactly the comparison it exists to support.

    `__pycache__` and compiled bytecode are excluded (they differ between two installs of identical
    source), as is the stamp file itself (it cannot contain its own digest).
    """
    from .contracts.digest import digest_json, normalize_tree_path
    from .contracts.errors import ContractError
    from .manifest import sha256_file

    root = _pathlib.Path(pkg_dir) if pkg_dir is not None else _package_dir()
    entries: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if any(part in _DIGEST_EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix in _DIGEST_EXCLUDED_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        if rel == _BUILD_STAMP_FILE:
            continue
        entries.append({"path": normalize_tree_path(rel), "sha256": f"sha256:{sha256_file(path)}"})
    if not entries:
        raise BuildIdentityError(f"no packaged files found under {root}")
    seen = {e["path"] for e in entries}
    if len(seen) != len(entries):
        raise ContractError("duplicate path in the package tree digest preimage")
    entries.sort(key=lambda e: e["path"])
    return digest_json(entries)


def read_build_stamp(pkg_dir: str | _pathlib.Path | None = None) -> dict[str, _Any] | None:
    """The parsed build stamp, or `None` when this is an unstamped source/editable checkout.

    Strict: a stamp that is not an object, carries an unexpected or missing key, a non-string
    value, a `source_tree_digest` that is not `sha256:<64 lowercase hex>`, or a `source_sha` that
    is neither null nor a 40-character lowercase hex sha is a `BuildIdentityError`, never a
    partially-trusted dict. An absent field is an error, never a satisfied constraint
    (global rule 0.1).
    """
    root = _pathlib.Path(pkg_dir) if pkg_dir is not None else _package_dir()
    stamp_path = root / _BUILD_STAMP_FILE
    if not stamp_path.is_file():
        return None
    if stamp_path.stat().st_size > 64 * 1024:
        raise BuildIdentityError("build stamp is implausibly large; refusing to parse it")
    try:
        raw = _json.loads(stamp_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, _json.JSONDecodeError) as exc:
        raise BuildIdentityError(
            f"build stamp is not readable JSON ({type(exc).__name__})"
        ) from None
    if not isinstance(raw, dict):
        raise BuildIdentityError("build stamp is not a JSON object")
    missing = [k for k in _STAMP_KEYS if k not in raw]
    extra = sorted(set(raw) - set(_STAMP_KEYS))
    if missing or extra:
        raise BuildIdentityError(
            f"build stamp must carry exactly {list(_STAMP_KEYS)}; missing={missing} "
            f"unexpected={extra}"
        )
    if raw["stamp_version"] != BUILD_STAMP_VERSION:
        raise BuildIdentityError(
            f"unsupported build-stamp version {raw['stamp_version']!r}; this build of "
            f"qfbench2-common understands {BUILD_STAMP_VERSION!r} only"
        )
    for key in ("version", "stamped_at"):
        if not isinstance(raw[key], str) or not raw[key]:
            raise BuildIdentityError(f"build stamp field {key!r} must be a non-empty string")
    from .contracts.digest import parse_digest
    from .contracts.errors import ContractError

    try:
        parse_digest(raw["source_tree_digest"], field="source_tree_digest")
    except ContractError as exc:
        raise BuildIdentityError(str(exc)) from None
    sha = raw["source_sha"]
    if sha is not None and not (
        isinstance(sha, str) and len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)
    ):
        raise BuildIdentityError(
            "build stamp source_sha must be null or a 40-character lowercase git sha"
        )
    return dict(raw)


def build_identity(pkg_dir: str | _pathlib.Path | None = None) -> dict[str, str | None]:
    """C8-grade identity of the code that is actually running (frozen decision D5).

        {"version": str, "source_tree_digest": "sha256:..." | None, "source_sha": str | None}

    `source_tree_digest` is **stamped at build time and read from the shipped tree**, never
    looked up at import from installed distribution metadata. On an unstamped source or editable
    checkout the digest is `None`, which is the honest answer: that tree is not a distributable
    build. A consumer that requires an identity must call `require_build_identity()` and fail
    closed on `None` — a null digest means *not rankable*, exactly as an unmeasured C7 field does.
    It must never be back-filled from `__version__`.

    **Note for C8 authors: this key is `source_tree_digest`, and it is NOT the C8
    `distribution_digest`.** This one covers the package tree — what running code can attest to
    about itself. C8's covers the built wheel's sha256, which no code inside that wheel can
    compute, and which the release job records from outside. The two answer different questions,
    both are worth having, and until this rename they shared one name across two contracts.
    """
    stamp = read_build_stamp(pkg_dir)
    if stamp is None:
        return {"version": __version__, "source_tree_digest": None, "source_sha": None}
    return {
        "version": str(stamp["version"]),
        "source_tree_digest": str(stamp["source_tree_digest"]),
        "source_sha": None if stamp["source_sha"] is None else str(stamp["source_sha"]),
    }


def verify_build_identity(pkg_dir: str | _pathlib.Path | None = None) -> bool:
    """True iff a stamp exists **and** the bytes on disk still hash to its `source_tree_digest`.

    This is the falsifiability property `__version__` lacks and the whole reason D5 exists: a
    modified vendored fork either carries no stamp at all, or carries a stamp whose digest no
    longer matches its own source. Either way this returns False, where `__version__` cheerfully
    reported the version of an unrelated distribution.
    """
    stamp = read_build_stamp(pkg_dir)
    if stamp is None:
        return False
    return package_tree_digest(pkg_dir) == str(stamp["source_tree_digest"])


def require_build_identity(pkg_dir: str | _pathlib.Path | None = None) -> dict[str, str | None]:
    """`build_identity()` for provenance paths, refusing anything it cannot vouch for.

    Raises `BuildIdentityError` on an unstamped tree or on a stamp that does not describe the
    bytes on disk. Call this from any path that writes a C2 or C8 provenance field.
    """
    stamp = read_build_stamp(pkg_dir)
    if stamp is None:
        raise BuildIdentityError(
            "this qfbench2-common is an unstamped source/editable checkout, so it has no build "
            "identity. Provenance must not fall back to __version__: install a stamped wheel "
            "built by the release job."
        )
    actual = package_tree_digest(pkg_dir)
    if actual != stamp["source_tree_digest"]:
        raise BuildIdentityError(
            "build stamp does not describe the bytes on disk: the package tree has been modified "
            "since it was built, or this is a vendored fork carrying somebody else's stamp"
        )
    return build_identity(pkg_dir)


def stamp_build(
    pkg_dir: str | _pathlib.Path | None = None,
    *,
    source_sha: str | None = None,
    version: str | None = None,
    stamped_at: str | None = None,
) -> dict[str, _Any]:
    """Write the build stamp. Called by the release job **before** the wheel is built.

    Lives here, next to the verifier, rather than as shell in a workflow file: the digest
    algorithm has one implementation (global rule 3), and a stamp written by a second, subtly
    different one would verify as tampering.
    """
    import datetime as _dt

    from .contracts._time import format_rfc3339

    root = _pathlib.Path(pkg_dir) if pkg_dir is not None else _package_dir()
    if source_sha is not None:
        source_sha = source_sha.strip().lower()
    stamp = {
        "stamp_version": BUILD_STAMP_VERSION,
        "version": version if version is not None else __version__,
        "source_tree_digest": package_tree_digest(root),
        "source_sha": source_sha,
        "stamped_at": (
            stamped_at
            if stamped_at is not None
            else format_rfc3339(_dt.datetime.now(_dt.timezone.utc))
        ),
    }
    (root / _BUILD_STAMP_FILE).write_text(
        _json.dumps(stamp, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # Round-trip through the strict reader so a malformed stamp is caught by the writer, not by a
    # scoring container six weeks later.
    verified = read_build_stamp(root)
    assert verified is not None
    return verified


# ------------------------------------------------------------- INTERFACE_VERSION (frozen rule 4)

#: Value the retired global constant used to hold, kept for the deprecated alias below.
_RETIRED_INTERFACE_VERSION = "2.0"

_DEPRECATED_ATTRS = {
    "INTERFACE_VERSION": (
        _RETIRED_INTERFACE_VERSION,
        "qfbench2_common.INTERFACE_VERSION is retired (frozen contract rule 0.4): one global "
        "constant cannot version eight independently-evolving contracts, and "
        "submission.schema.json pins it as a `const`, which makes it un-bumpable. Read the "
        "per-contract `schema_version` instead — e.g. "
        "qfbench2_common.contracts.plan.EvaluationPlan.schema_version — or, for the C5 descriptor "
        "field specifically, qfbench2_common.contracts.descriptor.INTERFACE_VERSION. This alias "
        "is kept for one minor version so no consumer breaks on import, and is then removed.",
    ),
}


def __getattr__(name: str) -> _Any:
    """PEP 562 module `__getattr__`, used only for the deprecated `INTERFACE_VERSION` alias.

    An alias implemented this way still satisfies `from qfbench2_common import INTERFACE_VERSION`
    and `qfbench2_common.INTERFACE_VERSION`, so nothing breaks on import — but every read emits a
    `DeprecationWarning` naming its replacement, which a plain module constant cannot do.
    """
    entry = _DEPRECATED_ATTRS.get(name)
    if entry is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value, message = entry
    _warnings.warn(message, DeprecationWarning, stacklevel=2)
    return value


__all__ = [
    "BUILD_STAMP_VERSION",
    "BuildIdentityError",
    "INTERFACE_VERSION",
    "__version__",
    "build_identity",
    "contracts",
    "failure_labels",
    "leakage",
    "manifest",
    "package_tree_digest",
    "read_build_stamp",
    "require_build_identity",
    "scoring",
    "stamp_build",
    "taskcard",
    "verifier",
    "verify_build_identity",
]
