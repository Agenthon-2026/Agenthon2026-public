"""C3 — the sanitized participant artifact tree: four roots, closed node types, counts-only rejections.

## Executive summary (read this first)

**The architectural ruling is what actually closes A04:** the participant's output directory and
the scoring program's input directory are no longer the same directory. Today `out_dir` is mounted
into the container *and* is `res/<unit>/`, with `ref/` as its sibling — measured to allow a relative
symlink from `res/` into `ref/`, for which `Path.is_file()` returns `True`, so the usual `is_file()`
guard does not protect. Five roots under one validated worker root replace that:

| Root | Written by | Readable by |
|---|---|---|
| `control/` | Runner helper (C2) | scorer (read-only) |
| `raw/` | **participant** | Runner helper only — never the scorer |
| `sanitized/` | Runner helper (copied bytes) | scorer (read-only) |
| `reference/` | organizer | scorer (read-only) |
| `results/` | verifier/checker | Hub C4 assembly |

This module owns the *policy*, not the walk. The OS-level materialization (a directory-FD-relative
no-follow walk, the copy, the deletion of `raw/`) belongs to the Runner; what lives here is the set
of predicates the walk must call, so that five workstreams cannot each invent their own answer to
"what counts as a malicious tree". Feed it `NodeObservation`s built from `os.lstat` and it returns
the verdict.

Frozen requirements encoded here:

* symlinks, hard links (`st_nlink > 1`), FIFOs, sockets, devices and every other non-regular node
  are rejected — *by type*, before anything opens them;
* exact allowed relative paths, normalized components, depth, count, per-file and total size, and
  a sparse-allocation bound;
* setuid/setgid/sticky bits are a **counted** rejection (`mode_unsafe`), not a raise. The copy into
  a fresh 0o644 file drops the bit either way; what the code buys is that the descriptor's
  per-code rows show the refusal happened, which a raise on the way past never did;
* rejection on **NFC collision and on case-insensitive collision** (`digest.digest_tree` enforces
  the same rule on the descriptor, so a tree cannot pass one gate and fail the other);
* hashes are over **copied bytes**, never over a participant path target;
* `rejections` carries **counts only** — the schema has no path field at all, so a careless caller
  cannot echo an attacker-controlled path into an operator log;
* `reference_reachable_from_c3` is recorded as an **asserted test result**, and `True` is an
  organizer fault rather than a note.

> **Binding test-environment caveat.** The case-collision and Unicode-collision cases cannot be
> constructed on macOS — APFS folds both — while the Linux workers do not. Those two must be
> exercised in Linux CI, and A06 may not be closed on a green local run.
"""

from __future__ import annotations

import stat
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .digest import TREE_ENTRY_KEYS, digest_tree, normalize_tree_path, parse_digest
from .errors import (
    ContractError,
    OrganizerFault,
    req,
    req_bool,
    req_float,
    req_int,
    req_list,
    req_mapping,
    req_str,
    reject_unknown_keys,
)

__all__ = [
    "ROOT_ACCESS",
    "NodeObservation",
    "NodeType",
    "RejectionCode",
    "Root",
    "SanitizedTree",
    "TreeEntry",
    "TreeLimits",
    "TreeValidation",
    "assert_root_access",
    "classify_node",
    "validate_listing",
]

SCHEMA_VERSION = "1.0.0"

#: setuid | setgid | sticky. Named here rather than spelled `0o7000` at the call site so the
#: `mode_bits` bound in `TreeEntry` (`0..0o7777`) and this check cannot drift apart.
_UNSAFE_MODE_BITS = stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX


class Root(StrEnum):
    CONTROL = "control"
    RAW = "raw"
    SANITIZED = "sanitized"
    REFERENCE = "reference"
    RESULTS = "results"


#: Who may write and who may read each root. `raw/` is readable by the Runner helper ALONE: the
#: scorer never sees participant bytes, only the validated copy in `sanitized/`.
ROOT_ACCESS: Mapping[Root, Mapping[str, tuple[str, ...]]] = {
    Root.CONTROL: {"writers": ("runner",), "readers": ("scorer", "hub", "runner")},
    Root.RAW: {"writers": ("participant",), "readers": ("runner",)},
    Root.SANITIZED: {"writers": ("runner",), "readers": ("scorer", "hub")},
    Root.REFERENCE: {"writers": ("organizer",), "readers": ("scorer",)},
    Root.RESULTS: {"writers": ("verifier", "checker"), "readers": ("hub",)},
}

ACTORS = ("participant", "runner", "scorer", "organizer", "verifier", "checker", "hub")


def assert_root_access(root: Root | str, actor: str, mode: str) -> None:
    """Raise unless `actor` may `read`/`write` `root`. The matrix above is the only authority."""
    key = Root(root)
    if actor not in ACTORS:
        raise ContractError(f"unknown actor {actor!r}; the set is closed: {list(ACTORS)}")
    if mode not in ("read", "write"):
        raise ContractError("mode must be 'read' or 'write'")
    permitted = ROOT_ACCESS[key]["writers" if mode == "write" else "readers"]
    if actor not in permitted:
        raise ContractError(
            f"{actor!r} may not {mode} {key.value}/ (permitted: {list(permitted)}). This is the "
            "C3 firewall: the scorer reading raw/ is A04."
        )


class NodeType(StrEnum):
    REGULAR = "regular"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    HARDLINK = "hardlink"
    FIFO = "fifo"
    SOCKET = "socket"
    BLOCK_DEVICE = "block_device"
    CHAR_DEVICE = "char_device"
    UNKNOWN = "unknown"


class RejectionCode(StrEnum):
    """Closed. Counts only ever reach a descriptor; the offending path never does."""

    SYMLINK = "symlink"
    HARD_LINK = "hard_link"
    NON_REGULAR = "non_regular"
    UNREADABLE = "unreadable"
    PATH_UNSAFE = "path_unsafe"
    PATH_NOT_ALLOWED = "path_not_allowed"
    DEPTH_EXCEEDED = "depth_exceeded"
    COUNT_EXCEEDED = "count_exceeded"
    FILE_BYTES_EXCEEDED = "file_bytes_exceeded"
    TOTAL_BYTES_EXCEEDED = "total_bytes_exceeded"
    SPARSE_RATIO_EXCEEDED = "sparse_ratio_exceeded"
    NFC_COLLISION = "nfc_collision"
    CASE_COLLISION = "case_collision"
    DUPLICATE_PATH = "duplicate_path"
    #: setuid, setgid or sticky bits on a participant-produced file. The shared corpus ships a
    #: `setuid-bit` case expecting REJECT. Copying the bytes into a fresh 0o644 file already
    #: neutralizes the bit, but "we happened to drop it" is not a defence anybody can point at in
    #: a review — and before this code existed the refusal was a raise, so it never appeared as a
    #: row in the descriptor and an auditor counting rejections could not see it happen.
    MODE_UNSAFE = "mode_unsafe"


def classify_node(st_mode: int, st_nlink: int) -> NodeType:
    """Classify one node from `os.lstat` results. **Never call `stat`; `lstat` is the point.**

    `st_nlink > 1` on a regular file is reported as `HARDLINK`, because a hard link into the
    reference tree leaves no symlink to detect and the link count is the only signal.
    """
    if stat.S_ISLNK(st_mode):
        return NodeType.SYMLINK
    if stat.S_ISDIR(st_mode):
        return NodeType.DIRECTORY
    if stat.S_ISFIFO(st_mode):
        return NodeType.FIFO
    if stat.S_ISSOCK(st_mode):
        return NodeType.SOCKET
    if stat.S_ISBLK(st_mode):
        return NodeType.BLOCK_DEVICE
    if stat.S_ISCHR(st_mode):
        return NodeType.CHAR_DEVICE
    if stat.S_ISREG(st_mode):
        return NodeType.HARDLINK if st_nlink > 1 else NodeType.REGULAR
    return NodeType.UNKNOWN


@dataclass(frozen=True, slots=True)
class TreeLimits:
    """The bounds a sanitized tree is validated against. All are required; none may be disabled."""

    max_files: int = 256
    max_depth: int = 8
    max_file_bytes: int = 64 * 1024 * 1024
    max_total_bytes: int = 256 * 1024 * 1024
    #: apparent size / allocated size. The 8 GiB-apparent sparse case in the shared corpus is
    #: rejected on APPARENT size; recording the ratio makes that choice explicit rather than
    #: incidental.
    max_sparse_ratio: float = 64.0

    def to_mapping(self) -> dict[str, Any]:
        return {
            "max_files": self.max_files,
            "max_depth": self.max_depth,
            "max_file_bytes": self.max_file_bytes,
            "max_total_bytes": self.max_total_bytes,
            "max_sparse_ratio": self.max_sparse_ratio,
        }

    @classmethod
    def from_mapping(cls, obj: Any, *, path: str = "limits_applied") -> TreeLimits:
        mapping = obj if isinstance(obj, Mapping) else None
        if mapping is None:
            raise ContractError(f"{path} must be an object")
        reject_unknown_keys(
            mapping,
            ("max_files", "max_depth", "max_file_bytes", "max_total_bytes", "max_sparse_ratio"),
            path=path,
        )
        return cls(
            max_files=req_int(mapping, "max_files", path=path, minimum=1),
            max_depth=req_int(mapping, "max_depth", path=path, minimum=1),
            max_file_bytes=req_int(mapping, "max_file_bytes", path=path, minimum=1),
            max_total_bytes=req_int(mapping, "max_total_bytes", path=path, minimum=1),
            max_sparse_ratio=req_float(mapping, "max_sparse_ratio", path=path),
        )


@dataclass(frozen=True, slots=True)
class NodeObservation:
    """What a no-follow walk saw at one path. Built from `os.lstat`, never from `os.stat`."""

    path: str
    node_type: NodeType
    size_bytes: int
    allocated_bytes: int
    nlink: int
    mode_bits: int
    readable: bool = True


@dataclass(frozen=True, slots=True)
class TreeValidation:
    accepted: tuple[str, ...]
    rejections: Mapping[RejectionCode, int]

    @property
    def ok(self) -> bool:
        """A tree with any rejection is refused whole. Partial acceptance is not a state."""
        return not self.rejections

    def rejection_rows(self) -> list[dict[str, Any]]:
        return [
            {"code": code.value, "count": count} for code, count in sorted(self.rejections.items())
        ]


def classify_path_collision(previous_raw: str, current_raw: str) -> RejectionCode:
    """Which collision two SOURCE spellings that normalize onto one path represent.

    One implementation, deliberately: `sanitize.walk_nofollow` normalizes as it walks and
    `validate_listing` normalizes on entry, so both destroy the evidence at different moments and
    both must classify before they do. Two hand-written copies of this rule would disagree, and the
    case one of them omits is the case that ships.

    Takes RAW spellings. Normalized ones carry no information: that is what made the NFC_COLLISION
    branch below unreachable for every caller until 2026-08-23.
    """
    if previous_raw == current_raw:
        return RejectionCode.DUPLICATE_PATH
    if unicodedata.normalize("NFC", previous_raw) == unicodedata.normalize("NFC", current_raw):
        return RejectionCode.NFC_COLLISION
    if previous_raw.casefold() == current_raw.casefold():
        return RejectionCode.CASE_COLLISION
    return RejectionCode.DUPLICATE_PATH


def validate_listing(
    observations: Iterable[NodeObservation],
    limits: TreeLimits | None = None,
    *,
    allowed_paths: Sequence[str] | None = None,
) -> TreeValidation:
    """Apply the C3 node-type, path, bound and collision policy to one directory listing.

    `allowed_paths`, when given, is the *exact* set of relative paths the unit may produce: a file
    outside it is `PATH_NOT_ALLOWED`. Directories are not entries and are only checked for depth.

    Returns counts, never paths. That is not politeness — an operator log that echoes an
    attacker-chosen filename is an injection surface, and the descriptor has no field to put one in.
    """
    bounds = limits or TreeLimits()
    rejections: dict[RejectionCode, int] = {}

    def reject(code: RejectionCode) -> None:
        rejections[code] = rejections.get(code, 0) + 1

    accepted: list[str] = []
    # The RAW spelling behind each accepted entry, positionally aligned. `normalize_tree_path`
    # below is lossy for exactly the collisions this function is supposed to name.
    accepted_raw: list[str] = []
    total_bytes = 0
    allowed = set(allowed_paths) if allowed_paths is not None else None

    for observation in observations:
        try:
            path = normalize_tree_path(observation.path)
        except ContractError:
            reject(RejectionCode.PATH_UNSAFE)
            continue
        if path.count("/") + 1 > bounds.max_depth:
            reject(RejectionCode.DEPTH_EXCEEDED)
            continue
        if observation.node_type is NodeType.DIRECTORY:
            continue
        if observation.node_type is NodeType.SYMLINK:
            reject(RejectionCode.SYMLINK)
            continue
        if observation.node_type is NodeType.HARDLINK:
            reject(RejectionCode.HARD_LINK)
            continue
        if observation.node_type is not NodeType.REGULAR:
            reject(RejectionCode.NON_REGULAR)
            continue
        if not observation.readable:
            # Mode 000 must be an explicit failure. Treating it as absent is how a unit silently
            # scores as "no output" when the participant in fact wrote something unreadable.
            reject(RejectionCode.UNREADABLE)
            continue
        if observation.mode_bits & _UNSAFE_MODE_BITS:
            # A MODE defect, counted like every other one. The copy would drop the bit anyway;
            # what a counted code adds is that the descriptor SHOWS it happened.
            reject(RejectionCode.MODE_UNSAFE)
            continue
        if allowed is not None and path not in allowed:
            reject(RejectionCode.PATH_NOT_ALLOWED)
            continue
        if observation.size_bytes > bounds.max_file_bytes:
            reject(RejectionCode.FILE_BYTES_EXCEEDED)
            continue
        if observation.allocated_bytes > 0 and (
            observation.size_bytes / observation.allocated_bytes > bounds.max_sparse_ratio
        ):
            reject(RejectionCode.SPARSE_RATIO_EXCEEDED)
            continue
        total_bytes += observation.size_bytes
        accepted.append(path)
        accepted_raw.append(observation.path)

    if len(accepted) > bounds.max_files:
        reject(RejectionCode.COUNT_EXCEEDED)
    if total_bytes > bounds.max_total_bytes:
        reject(RejectionCode.TOTAL_BYTES_EXCEEDED)

    # A collision is refused AND removed. The previous version counted DUPLICATE_PATH but left the
    # duplicate in `accepted`, so `materialize_tree` opened the same destination twice and died on
    # O_EXCL with an unhandled FileExistsError -- an organizer-shaped crash from an input the
    # participant chooses. `accepted` is the set that will be materialized; a set cannot hold the
    # same path twice.
    first_raw: dict[str, str] = {}
    folded: dict[str, str] = {}
    survivors: list[str] = []
    for path, raw in zip(accepted, accepted_raw):
        previous = first_raw.get(path)
        if previous is not None:
            reject(classify_path_collision(previous, raw))
            continue
        first_raw[path] = raw
        # Distinct normalized paths that fold together under case. Live on Linux, unbuildable on
        # APFS, and a different code path from the same-normalized collisions handled above.
        fold_key = path.casefold()
        if fold_key in folded and folded[fold_key] != path:
            reject(RejectionCode.CASE_COLLISION)
        folded.setdefault(fold_key, path)
        survivors.append(path)

    return TreeValidation(accepted=tuple(survivors), rejections=rejections)


@dataclass(frozen=True, slots=True)
class TreeEntry:
    """One manifest row. `sha256` is over the **copied** bytes in `sanitized/`."""

    path: str
    size_bytes: int
    sha256: str
    mode_bits: int
    num_rows: int | None = None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "mode_bits": self.mode_bits,
            "num_rows": self.num_rows,
        }

    @classmethod
    def from_mapping(cls, obj: Any, *, path: str) -> TreeEntry:
        if not isinstance(obj, Mapping):
            raise ContractError(f"{path} must be an object")
        reject_unknown_keys(obj, TREE_ENTRY_KEYS, path=path)
        rows = req(obj, "num_rows", path=path, allow_null=True)
        if rows is not None and (isinstance(rows, bool) or not isinstance(rows, int) or rows < 0):
            raise ContractError(f"{path}.num_rows must be a non-negative integer or null")
        return cls(
            path=normalize_tree_path(req(obj, "path", path=path), field=f"{path}.path"),
            size_bytes=req_int(obj, "size_bytes", path=path, minimum=0),
            sha256=parse_digest(req(obj, "sha256", path=path), field=f"{path}.sha256"),
            mode_bits=req_int(obj, "mode_bits", path=path, minimum=0),
            num_rows=rows,
        )


_TREE_KEYS = (
    "schema_version",
    "root",
    "root_digest",
    "entries",
    "limits_applied",
    "rejections",
    "reference_reachable_from_c3",
    "staging_root_parent_exclusive",
)


@dataclass(frozen=True, slots=True)
class SanitizedTree:
    """The C3 descriptor: what was copied, under which bounds, and what was refused."""

    schema_version: str
    root: Root
    root_digest: str
    entries: tuple[TreeEntry, ...]
    limits_applied: TreeLimits
    rejections: Mapping[RejectionCode, int]
    reference_reachable_from_c3: bool
    #: True iff the tree was BUILT in a staging directory whose parent held nothing else.
    #:
    #: Named for the staging root, not the published one, because at the published location the
    #: property is unsatisfiable by construction: the platform mounts the ingestion output root as
    #: the scorer's `input/res`, so that directory necessarily holds every other unit and the
    #: organizer control root. Claiming exclusivity there would be false. The published tree earns
    #: its guarantee a different way -- it is re-verified against its own manifest after the move --
    #: and `reference_reachable_from_c3` is the flag that speaks to the published namespace.
    staging_root_parent_exclusive: bool

    @classmethod
    def from_mapping(cls, raw: Any) -> SanitizedTree:
        if not isinstance(raw, Mapping):
            raise ContractError("a C3 descriptor must be an object")
        reject_unknown_keys(raw, _TREE_KEYS, path="sanitized_tree")
        version = req_str(raw, "schema_version", path="sanitized_tree")
        if version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise ContractError(f"unsupported C3 schema_version {version!r}")
        root = Root(req_str(raw, "root", path="sanitized_tree"))
        if root is not Root.SANITIZED:
            raise ContractError(
                f"a C3 descriptor describes the sanitized/ root; got {root.value!r}. The scorer "
                "never receives a descriptor of raw/."
            )
        entries = tuple(
            TreeEntry.from_mapping(entry, path=f"entries[{i}]")
            for i, entry in enumerate(req_list(raw, "entries", path="sanitized_tree"))
        )
        rejections: dict[RejectionCode, int] = {}
        for index, row in enumerate(req_list(raw, "rejections", path="sanitized_tree")):
            path = f"rejections[{index}]"
            if not isinstance(row, Mapping):
                raise ContractError(f"{path} must be an object")
            reject_unknown_keys(row, ("code", "count"), path=path)
            code_value = req_str(row, "code", path=path)
            try:
                code = RejectionCode(code_value)
            except ValueError:
                raise ContractError(
                    f"{path}.code={code_value!r} is not a rejection code; the set is closed"
                ) from None
            if code in rejections:
                raise ContractError(f"{path} repeats code {code_value!r}")
            rejections[code] = req_int(row, "count", path=path, minimum=1)

        reachable = req_bool(raw, "reference_reachable_from_c3", path="sanitized_tree")
        if reachable:
            raise OrganizerFault(
                "reference_reachable_from_c3 is true: the sanitized tree can address the reference "
                "tree. That is A04. This is an organizer fault and the evaluation aborts; it is "
                "not a note on an otherwise valid descriptor."
            )
        exclusive = req_bool(raw, "staging_root_parent_exclusive", path="sanitized_tree")
        if not exclusive:
            raise OrganizerFault(
                "sanitized/ must be rooted in a directory whose parent contains nothing else; a "
                "shared parent is how a relative path escapes into a sibling root"
            )

        tree = cls(
            schema_version=version,
            root=root,
            root_digest=parse_digest(
                req(raw, "root_digest", path="sanitized_tree"), field="root_digest"
            ),
            entries=entries,
            limits_applied=TreeLimits.from_mapping(
                req_mapping(raw, "limits_applied", path="sanitized_tree")
            ),
            rejections=rejections,
            reference_reachable_from_c3=reachable,
            staging_root_parent_exclusive=exclusive,
        )
        tree.verify_digest()
        return tree

    def compute_digest(self) -> str:
        return digest_tree(entry.to_mapping() for entry in self.entries)

    def verify_digest(self) -> None:
        computed = self.compute_digest()
        if computed != self.root_digest:
            raise ContractError(
                f"C3 root_digest {self.root_digest} does not match the manifest ({computed}). C2 "
                "binds this digest, so a mismatch means the scorer would read a tree the Runner "
                "did not attest."
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root": self.root.value,
            "root_digest": self.root_digest,
            "entries": [entry.to_mapping() for entry in self.entries],
            "limits_applied": self.limits_applied.to_mapping(),
            "rejections": [
                {"code": code.value, "count": count}
                for code, count in sorted(self.rejections.items())
            ],
            "reference_reachable_from_c3": self.reference_reachable_from_c3,
            "staging_root_parent_exclusive": self.staging_root_parent_exclusive,
        }

    def num_rows(self, path: str) -> int | None:
        """The parquet row count recorded for `path`, so a row-count bound runs before any parser."""
        for entry in self.entries:
            if entry.path == path:
                return entry.num_rows
        raise ContractError(f"{path!r} is not in the sanitized manifest")
