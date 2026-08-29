"""C3 materializer primitives: the directory-FD-relative, no-follow walk and copy.

## Executive summary (read this first)

`qfbench2_common.contracts.artifact_tree` owns the C3 **policy** — which node types are refused,
which bounds apply, what a rejection is called. This module owns the **syscalls**: the walk that
produces the observations that policy is applied to, and the copy that turns an accepted listing
into a fresh, scorer-owned tree of ordinary bytes. Splitting them that way is deliberate; five
workstreams must not each invent their own answer to "what counts as a malicious tree", and a
policy module that also does I/O cannot be unit-tested against a synthetic listing.

Three rules run through every function here, and each of them is a measured defect rather than a
precaution:

1. **`Path.is_file()` returns `True` for a symlink to a file.** It is not a defence, it has never
   been a defence, and the audit's `rel-symlink-to-ref` case exists precisely because a guard
   written with it passes an attack. Every stat in this module is `os.lstat`; every open carries
   `O_NOFOLLOW`; every directory is opened with `O_NOFOLLOW | O_DIRECTORY` and every child is
   named *relative to that descriptor* via `dir_fd=`. A symlink is therefore never traversed,
   never opened, and never resolved — it is classified and refused.
2. **A hard link leaves no symlink to detect.** `st_nlink > 1` on a regular file is the only
   signal that the participant's `predictions.json` and the grader's `targets.json` are the same
   inode, so it is refused by link count.
3. **Hashes are over the copied bytes.** `sha256` is computed by the writer, from the buffer that
   was actually written into the destination, never by re-opening a participant path. A digest
   taken by re-reading the source is a digest of whatever the source is at read time.

### What "fresh destination, then atomic promote" buys

`materialize_tree` refuses to write into an existing destination and `promote` moves a completed
staging directory into place with a single `os.rename`. A consumer therefore never observes a
half-built tree, and a build that fails partway leaves the previous state untouched — which is the
property global rule 8 asks for ("built into a fresh destination, checked bidirectionally, and
atomically promoted").

### Bounds, and the one the corpus forces you to be explicit about

`TreeLimits` (from `contracts`) bounds file count, depth, per-file bytes, total bytes and the
sparse-allocation ratio. The shared corpus ships an 8 GiB-apparent / few-blocks-allocated file
specifically because "apparent size" and "allocated size" are both defensible and a limit that
does not say which one it means is not a limit. This module measures **apparent size**
(`st_size`) for the byte bounds and records the ratio separately, so the choice is stated rather
than incidental.

### Deliberate non-goals

* **Content parsing.** A truncated JSON file and a file full of `NaN` are perfectly ordinary
  regular files; C3 accepts them and the track parser reports `malformed_output`. Refusing them
  here would put schema knowledge in the sanitizer and make every track's failure code
  unattributable.
* **Row counting.** The C3 manifest carries parquet `num_rows` so a row-count bound can run before
  a parser does, but reading a footer means running a parquet reader over participant bytes.
  `row_counter` is therefore an injected callback with a default of "record `null`"; a caller that
  wants row counts opts in and owns the reader.

> **Binding test-environment caveat.** The case-collision and Unicode-collision defences cannot be
> exercised on macOS — APFS folds both spellings, so the malicious tree cannot even be built. They
> must be exercised on the Linux workers. A green local run is not evidence for those two.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import secrets
import shutil
import stat
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .contracts.artifact_tree import (
    NodeObservation,
    NodeType,
    RejectionCode,
    Root,
    SanitizedTree,
    TreeLimits,
    TreeValidation,
    classify_node,
    classify_path_collision,
    validate_listing,
)
from .contracts.digest import digest_tree, normalize_tree_path
from .contracts.errors import ContractError, OrganizerFault, ParticipantFailure

__all__ = [
    "DEFAULT_LIMITS",
    "MaterializedFile",
    "Materialization",
    "TreeRefused",
    "WalkResult",
    "fstat_verify",
    "hash_regular_file",
    "materialize_tree",
    "merge_rejections",
    "no_row_counter",
    "open_relative_nofollow",
    "promote",
    "sanitize_participant_tree",
    "staging_sibling",
    "unsafe_mode_bits",
    "verify_destination",
    "walk_nofollow",
]

DEFAULT_LIMITS = TreeLimits()

_CHUNK = 1 << 20
_DIR_MODE = 0o755
_FILE_MODE = 0o644

#: `O_NOFOLLOW`/`O_DIRECTORY` are POSIX-only. This package targets Linux workers and macOS
#: development hosts; on anything else the no-follow guarantee cannot be made and we refuse rather
#: than degrade to a following walk.
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", None)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", None)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class TreeRefused(ParticipantFailure):
    """A participant artifact tree was refused by the C3 policy.

    A `ParticipantFailure`: the unit keeps its slot in the C1 roster and takes the plan's
    committed worst-case score. It is never dropped from the denominator.
    """

    def __init__(self, message: str, rejections: Mapping[RejectionCode, int] | None = None) -> None:
        super().__init__(message)
        #: Counts only. There is deliberately no path here: an operator log that echoes an
        #: attacker-chosen filename is an injection surface, and C3 has no field to put one in.
        self.rejections: Mapping[RejectionCode, int] = dict(rejections or {})


def _require_posix() -> None:
    if _O_NOFOLLOW is None or _O_DIRECTORY is None:
        raise ContractError(
            "os.O_NOFOLLOW / os.O_DIRECTORY are unavailable on this platform, so a no-follow walk "
            "cannot be guaranteed. Refusing rather than falling back to a following walk."
        )


def unsafe_mode_bits(mode: int) -> bool:
    """True for setuid, setgid or sticky bits on a participant-produced file.

    The corpus ships a `setuid-bit` case with an expected verdict of REJECT. Copying the bytes into
    a fresh file at 0o644 already neutralizes the bit, but "we happened to drop it" is not a
    defence anybody can point at in a review, so the tree is refused outright and the reason is
    named.

    Note this has no `RejectionCode` in the frozen C3 enum, so it is raised rather than
    counted.
    """
    return bool(mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX))


# --------------------------------------------------------------------------- the walk
@dataclass(frozen=True, slots=True)
class WalkResult:
    """What a no-follow walk saw, plus the rejections the *walk itself* had to make.

    Depth and total-node bounds cannot be left to the batch policy: a walker that stops descending
    at the depth bound never observes the too-deep files, and a listing that omits them is
    indistinguishable from a listing of a shallow tree. So the walk counts those two itself and the
    caller merges them with `validate_listing`'s counts.
    """

    observations: tuple[NodeObservation, ...]
    rejections: Mapping[RejectionCode, int]
    truncated: bool
    unsafe_modes: int

    @property
    def clean(self) -> bool:
        return not self.rejections and not self.truncated and not self.unsafe_modes


def merge_rejections(*sources: Mapping[RejectionCode, int]) -> dict[RejectionCode, int]:
    merged: dict[RejectionCode, int] = {}
    for source in sources:
        for code, count in source.items():
            merged[code] = merged.get(code, 0) + count
    return merged


def _probe_readable(name: str, dir_fd: int) -> bool:
    """Can this regular file actually be opened for reading, without following a link?

    Mode 000 must be an explicit failure. Treating an unreadable file as absent is how a unit
    silently scores as "no output" when the participant in fact wrote something.
    """
    try:
        fd = os.open(name, os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC, dir_fd=dir_fd)  # type: ignore[operator]
    except PermissionError:
        return False
    except OSError:
        return False
    os.close(fd)
    return True


def walk_nofollow(
    root: str | os.PathLike[str],
    *,
    limits: TreeLimits | None = None,
) -> WalkResult:
    """Enumerate `root` with `lstat` only, never following a link and never opening a special node.

    Returns one `NodeObservation` per node (directories included, so a caller can recreate empty
    directories) with paths relative to `root`, POSIX-separated and NFC-normalized.

    A FIFO is classified and skipped, so the "hang the worker" case never reaches an `open`. A
    symlink — to a file, to a directory, dangling, or the second hop of a chain — is classified
    `SYMLINK` and is never resolved, so chain depth is irrelevant.
    """
    _require_posix()
    bounds = limits or DEFAULT_LIMITS
    root_path = pathlib.Path(root)
    observations: list[NodeObservation] = []
    rejections: dict[RejectionCode, int] = {}
    state = {"truncated": False, "unsafe_modes": 0}
    # Normalized rel path -> the RAW spelling that first produced it. `normalize_tree_path` NFC-
    # folds, so two source names that differ only by Unicode composition collapse to one string
    # here. Without this map that fact is unrecoverable downstream: the pair reaches
    # `validate_tree` as a plain duplicate, the NFC_COLLISION branch there can never fire, and
    # `materialize_tree` opens the same target twice and dies on O_EXCL with an unhandled
    # FileExistsError -- an organizer-looking crash for a participant-controlled input.
    first_raw: dict[str, str] = {}
    # A tree may be adversarially wide as well as adversarially deep. Enumerating is cheap, but not
    # unbounded: stop well past the file bound so COUNT_EXCEEDED is provable without walking a
    # billion entries.
    max_nodes = max(bounds.max_files * 4, 4096)

    def reject(code: RejectionCode, n: int = 1) -> None:
        rejections[code] = rejections.get(code, 0) + n

    try:
        root_fd = os.open(root_path, os.O_RDONLY | _O_NOFOLLOW | _O_DIRECTORY | _O_CLOEXEC)  # type: ignore[operator]
    except NotADirectoryError as exc:
        raise ContractError(f"{root_path} is not a directory") from exc
    except OSError as exc:
        raise ContractError(f"cannot open {root_path} as a no-follow directory: {exc}") from exc

    def descend(dir_fd: int, prefix: str, depth: int) -> None:
        try:
            names = sorted(os.listdir(dir_fd))
        except PermissionError:
            reject(RejectionCode.UNREADABLE)
            return
        for name in names:
            if len(observations) >= max_nodes:
                state["truncated"] = True
                reject(RejectionCode.COUNT_EXCEEDED)
                return
            rel_raw = f"{prefix}{name}"
            try:
                rel = normalize_tree_path(rel_raw)
            except ContractError:
                # A name the digest grammar cannot represent (control characters, a stray
                # backslash). Refused by path, before its type is even considered.
                reject(RejectionCode.PATH_UNSAFE)
                continue
            previous = first_raw.get(rel)
            if previous is not None:
                # Refuse by code, and emit NO second observation: a path that appears twice in
                # `accepted` is a double materialization, not a policy question.
                reject(classify_path_collision(previous, rel_raw))
                continue
            first_raw[rel] = rel_raw
            try:
                st = os.lstat(name, dir_fd=dir_fd)
            except OSError:
                reject(RejectionCode.UNREADABLE)
                continue
            node = classify_node(st.st_mode, st.st_nlink)
            mode_bits = stat.S_IMODE(st.st_mode)
            if node is NodeType.REGULAR and unsafe_mode_bits(mode_bits):
                state["unsafe_modes"] += 1
            readable = True
            if node is NodeType.REGULAR:
                readable = _probe_readable(name, dir_fd)
            observations.append(
                NodeObservation(
                    path=rel,
                    node_type=node,
                    size_bytes=int(st.st_size),
                    # st_blocks is 512-byte units. A file with zero allocated blocks is fully
                    # sparse; report 0 and let the policy decide.
                    allocated_bytes=int(getattr(st, "st_blocks", 0)) * 512,
                    nlink=int(st.st_nlink),
                    mode_bits=mode_bits,
                    readable=readable,
                )
            )
            if node is not NodeType.DIRECTORY:
                continue
            if depth + 1 > bounds.max_depth:
                # Do not descend, but do not pretend the subtree is empty either.
                reject(RejectionCode.DEPTH_EXCEEDED)
                continue
            try:
                child_fd = os.open(
                    name,
                    os.O_RDONLY | _O_NOFOLLOW | _O_DIRECTORY | _O_CLOEXEC,  # type: ignore[operator]
                    dir_fd=dir_fd,
                )
            except OSError:
                reject(RejectionCode.UNREADABLE)
                continue
            try:
                descend(child_fd, f"{rel}/", depth + 1)
            finally:
                os.close(child_fd)

    try:
        descend(root_fd, "", 1)
    finally:
        os.close(root_fd)

    return WalkResult(
        observations=tuple(observations),
        rejections=rejections,
        truncated=bool(state["truncated"]),
        unsafe_modes=int(state["unsafe_modes"]),
    )


# --------------------------------------------------------------------------- opening and hashing
def open_relative_nofollow(root_fd: int, rel_path: str) -> int:
    """Open `rel_path` under `root_fd`, resolving **every** component with `O_NOFOLLOW`.

    `O_NOFOLLOW` alone guards only the final component; a symlinked intermediate directory is the
    other half of the attack. Walking the components against successive directory descriptors is
    what closes it.
    """
    components = rel_path.split("/")
    current = os.dup(root_fd)
    try:
        for component in components[:-1]:
            nxt = os.open(
                component,
                os.O_RDONLY | _O_NOFOLLOW | _O_DIRECTORY | _O_CLOEXEC,  # type: ignore[operator]
                dir_fd=current,
            )
            os.close(current)
            current = nxt
        return os.open(
            components[-1],
            os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC,  # type: ignore[operator]
            dir_fd=current,
        )
    finally:
        os.close(current)


def hash_regular_file(fd: int) -> tuple[str, int]:
    """`(digest, size)` of an already-open regular file, read from the descriptor.

    Takes a descriptor rather than a path on purpose: by the time this runs the caller has already
    proved, with `fstat` on this very descriptor, that it is a regular single-linked file. A
    path-taking hasher would re-resolve and re-open, and re-resolution is the whole attack.
    """
    digest = hashlib.sha256()
    size = 0
    while True:
        block = os.read(fd, _CHUNK)
        if not block:
            break
        size += len(block)
        digest.update(block)
    return "sha256:" + digest.hexdigest(), size


def fstat_verify(fd: int, rel_path: str) -> os.stat_result:
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        raise TreeRefused(
            f"{rel_path!r} changed type between the walk and the copy; refusing the tree",
            {RejectionCode.NON_REGULAR: 1},
        )
    if st.st_nlink > 1:
        raise TreeRefused(
            f"{rel_path!r} is hard-linked ({st.st_nlink} links); a hard link into the reference "
            "tree leaves no symlink to detect and the link count is the only signal",
            {RejectionCode.HARD_LINK: 1},
        )
    return st


# --------------------------------------------------------------------------- materialization
RowCounter = Callable[[str, pathlib.Path], "int | None"]


def no_row_counter(rel_path: str, copied: pathlib.Path) -> int | None:
    """The default: record `null` and run no reader over participant bytes.

    C3 carries parquet `num_rows` so a row-count bound can be enforced before a parser runs — but
    obtaining it means running a parquet footer reader, which is itself a parser over participant
    bytes. Callers that want the number inject their own reader and own that risk explicitly.
    """
    del rel_path, copied
    return None


@dataclass(frozen=True, slots=True)
class MaterializedFile:
    """One accepted file, as it exists **in the destination**."""

    path: str
    size_bytes: int
    sha256: str
    mode_bits: int
    num_rows: int | None

    def to_entry(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "mode_bits": self.mode_bits,
            "num_rows": self.num_rows,
        }


@dataclass(frozen=True, slots=True)
class Materialization:
    """The result of copying an accepted listing into a fresh destination."""

    destination: pathlib.Path
    files: tuple[MaterializedFile, ...]
    validation: TreeValidation
    walk_rejections: Mapping[RejectionCode, int]
    total_bytes: int
    #: Count of source files carrying setuid/setgid/sticky bits. No frozen `RejectionCode` covers
    #: this, so it is reported separately and refused by the caller rather than silently dropped
    #: when the bytes are copied into a fresh 0o644 file.
    unsafe_modes: int = 0

    @property
    def rejections(self) -> dict[RejectionCode, int]:
        return merge_rejections(self.walk_rejections, self.validation.rejections)

    @property
    def ok(self) -> bool:
        return not self.rejections

    def tree_digest(self) -> str:
        return digest_tree(f.to_entry() for f in self.files)

    def paths(self) -> tuple[str, ...]:
        return tuple(f.path for f in self.files)


def staging_sibling(destination: str | os.PathLike[str]) -> pathlib.Path:
    """A fresh, unpredictable sibling of `destination` to build in before promoting.

    A sibling rather than a temp directory elsewhere, because `os.rename` is only atomic within a
    filesystem, and "atomically promoted" is the requirement.
    """
    dst = pathlib.Path(destination)
    return dst.parent / f".{dst.name}.staging-{secrets.token_hex(8)}"


def promote(staging: str | os.PathLike[str], destination: str | os.PathLike[str]) -> pathlib.Path:
    """Move a completed staging tree into place with one `os.rename`.

    Refuses an occupied destination. A consumer therefore never sees a half-built tree, and a build
    that dies partway leaves whatever was already there untouched.
    """
    staging_path, dst = pathlib.Path(staging), pathlib.Path(destination)
    if dst.exists() or dst.is_symlink():
        raise ContractError(
            f"refusing to promote onto an existing path {dst}; a destination is written once"
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.rename(staging_path, dst)
    return dst


def materialize_tree(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    limits: TreeLimits | None = None,
    allowed_paths: Sequence[str] | None = None,
    include: Callable[[str], bool] | None = None,
    row_counter: RowCounter | None = None,
    copy_empty_dirs: bool = True,
) -> Materialization:
    """Walk `source` no-follow, apply the C3 policy, and copy the accepted bytes into `destination`.

    `destination` must not exist; it is created 0o700 and populated with ordinary regular files at
    0o644. `include(rel_path)` filters *before* the policy runs, which is how the dataset splitter
    drops answer directories without them counting as rejections.

    The returned `Materialization` reports the merged rejection counts. **It does not raise on a
    rejection** — the caller decides whether a rejected tree is a participant failure or an
    organizer fault, and the two have different consequences.
    """
    _require_posix()
    bounds = limits or DEFAULT_LIMITS
    src = pathlib.Path(source)
    dst = pathlib.Path(destination)
    counter: RowCounter = row_counter or no_row_counter
    if dst.exists() or dst.is_symlink():
        raise ContractError(
            f"refusing to materialize into an existing path {dst}; C3 builds a FRESH destination "
            "so a stale file from an earlier build can never be scored"
        )

    walk = walk_nofollow(src, limits=bounds)
    selected = list(walk.observations)
    if include is not None:
        selected = [obs for obs in selected if include(obs.path)]

    validation = validate_listing(selected, bounds, allowed_paths=allowed_paths)

    dst.mkdir(parents=True, mode=0o700)
    root_fd = os.open(src, os.O_RDONLY | _O_NOFOLLOW | _O_DIRECTORY | _O_CLOEXEC)  # type: ignore[operator]
    files: list[MaterializedFile] = []
    total = 0
    try:
        if copy_empty_dirs:
            for obs in selected:
                if obs.node_type is NodeType.DIRECTORY:
                    (dst / obs.path).mkdir(parents=True, mode=_DIR_MODE, exist_ok=True)
        for rel in validation.accepted:
            fd = open_relative_nofollow(root_fd, rel)
            try:
                fstat_verify(fd, rel)
                target = dst / rel
                target.parent.mkdir(parents=True, mode=_DIR_MODE, exist_ok=True)
                digest, size = _copy_fd_to_path(fd, target, bounds.max_file_bytes, rel)
            finally:
                os.close(fd)
            total += size
            if total > bounds.max_total_bytes:
                shutil.rmtree(dst, ignore_errors=True)
                raise TreeRefused(
                    "the copied tree exceeded the total-byte bound partway through; the "
                    "destination was removed rather than left half-built",
                    {RejectionCode.TOTAL_BYTES_EXCEEDED: 1},
                )
            files.append(
                MaterializedFile(
                    path=rel,
                    size_bytes=size,
                    sha256=digest,
                    mode_bits=_FILE_MODE,
                    num_rows=counter(rel, target),
                )
            )
    finally:
        os.close(root_fd)

    return Materialization(
        destination=dst,
        files=tuple(files),
        validation=validation,
        walk_rejections=dict(walk.rejections),
        total_bytes=total,
        unsafe_modes=walk.unsafe_modes,
    )


def _copy_fd_to_path(fd: int, target: pathlib.Path, max_bytes: int, rel: str) -> tuple[str, int]:
    """Stream an open source descriptor into a fresh destination file, hashing what is written."""
    digest = hashlib.sha256()
    written = 0
    out_fd = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_CLOEXEC,  # type: ignore[operator]
        _FILE_MODE,
    )
    try:
        while True:
            block = os.read(fd, _CHUNK)
            if not block:
                break
            written += len(block)
            if written > max_bytes:
                raise TreeRefused(
                    f"{rel!r} exceeded the per-file byte bound while copying; a file that grows "
                    "between lstat and read is refused rather than truncated",
                    {RejectionCode.FILE_BYTES_EXCEEDED: 1},
                )
            digest.update(block)
            os.write(out_fd, block)
    finally:
        os.close(out_fd)
    return "sha256:" + digest.hexdigest(), written


# --------------------------------------------------------------------------- bidirectional verify
def verify_destination(
    destination: str | os.PathLike[str],
    expected: Iterable[MaterializedFile],
    *,
    limits: TreeLimits | None = None,
) -> list[str]:
    """Re-read the built tree and check it **both ways** against what we believe we wrote.

    manifest -> disk: every expected file is present, is a regular single-linked file, and hashes
    to the recorded digest. disk -> manifest: nothing else is there.

    This is not belt-and-braces. The copy loop hashes a buffer; this re-reads the file the scorer
    will actually open. Only the second one is evidence about the bytes on disk.
    """
    dst = pathlib.Path(destination)
    bounds = limits or DEFAULT_LIMITS
    errors: list[str] = []
    by_path = {f.path: f for f in expected}

    walk = walk_nofollow(dst, limits=bounds)
    for code, count in walk.rejections.items():
        errors.append(f"built tree holds {count} node(s) rejected as {code.value}")
    on_disk: dict[str, NodeObservation] = {}
    for obs in walk.observations:
        if obs.node_type is NodeType.DIRECTORY:
            continue
        if obs.node_type is not NodeType.REGULAR:
            errors.append(f"built tree holds a {obs.node_type.value} node")
            continue
        on_disk[obs.path] = obs

    for extra in sorted(set(on_disk) - set(by_path)):
        errors.append(f"unmanifested file in the built tree: {extra}")
    for missing in sorted(set(by_path) - set(on_disk)):
        errors.append(f"manifested file absent from the built tree: {missing}")

    root_fd = os.open(dst, os.O_RDONLY | _O_NOFOLLOW | _O_DIRECTORY | _O_CLOEXEC)  # type: ignore[operator]
    try:
        for path in sorted(set(by_path) & set(on_disk)):
            fd = open_relative_nofollow(root_fd, path)
            try:
                fstat_verify(fd, path)
                digest, size = hash_regular_file(fd)
            finally:
                os.close(fd)
            want = by_path[path]
            if digest != want.sha256:
                errors.append(f"checksum mismatch in the built tree: {path}")
            if size != want.size_bytes:
                errors.append(f"size mismatch in the built tree: {path}")
    finally:
        os.close(root_fd)
    return errors


# --------------------------------------------------------------------------- the C3 entry point
def sanitize_participant_tree(
    raw_root: str | os.PathLike[str],
    sanitized_root: str | os.PathLike[str],
    *,
    limits: TreeLimits | None = None,
    allowed_paths: Sequence[str] | None = None,
    row_counter: RowCounter | None = None,
    require_nonempty: bool = True,
) -> SanitizedTree:
    """Turn a raw participant output directory into a signed-shape C3 descriptor + a clean tree.

    The whole architectural point of C3 is that `raw/` and the scorer's input are **not the same
    directory**: this function reads the first and writes the second, and the scorer is never given
    a path into the first. Build order is fresh staging -> policy -> copy -> bidirectional verify ->
    atomic promote, so a refusal never leaves a partially sanitized tree where a scorer could find
    it.

    `require_nonempty=True` (the default) turns "the participant wrote nothing" into an explicit
    `TreeRefused` rather than a valid empty tree. The unit still consumes the C1 participant-failure
    score and stays in the denominator; what it must not do is silently look like a successful run
    that produced no files.

    Raises `TreeRefused` on any rejection. Partial acceptance is not a state: a tree with one
    symlink in it is refused whole, because "we scored the parts we liked" is unauditable.
    """
    bounds = limits or DEFAULT_LIMITS
    final = pathlib.Path(sanitized_root)
    if final.exists() or final.is_symlink():
        raise ContractError(f"refusing to sanitize onto an existing path {final}")
    staging = staging_sibling(final)

    try:
        result = materialize_tree(
            raw_root,
            staging,
            limits=bounds,
            allowed_paths=allowed_paths,
            row_counter=row_counter,
        )
        rejections = result.rejections
        if result.unsafe_modes:
            raise TreeRefused(
                f"{result.unsafe_modes} participant file(s) carry setuid/setgid/sticky mode bits; "
                "the copy would drop them, but 'we happened to drop it' is not a defence"
            )
        if rejections:
            raise TreeRefused(
                "participant artifact tree refused: "
                + ", ".join(f"{code.value}x{count}" for code, count in sorted(rejections.items())),
                rejections,
            )
        if require_nonempty and not result.files:
            raise TreeRefused(
                "participant artifact tree holds no accepted files; this is 'no output', not an "
                "empty success, and it consumes the C1 participant-failure score"
            )
        errors = verify_destination(staging, result.files, limits=bounds)
        if errors:
            raise OrganizerFault(
                "the sanitized tree did not verify against its own manifest, which means the "
                "materializer and the filesystem disagree: " + "; ".join(errors)
            )
        promote(staging, final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    parent_exclusive = _parent_is_exclusive(final)
    descriptor = {
        "schema_version": "1.0.0",
        "root": Root.SANITIZED.value,
        "root_digest": result.tree_digest(),
        "entries": [f.to_entry() for f in result.files],
        "limits_applied": bounds.to_mapping(),
        "rejections": [],
        # An ASSERTED TEST RESULT. Every entry is a regular file this process wrote into a fresh
        # directory, and no link of any kind survived the walk, so there is no path from the
        # sanitized tree into the reference tree. `_parent_is_exclusive` is the second half:
        # a shared parent is how a relative path escapes into a sibling root.
        "reference_reachable_from_c3": False,
        "staging_root_parent_exclusive": parent_exclusive,
    }
    return SanitizedTree.from_mapping(descriptor)


def _parent_is_exclusive(root: pathlib.Path) -> bool:
    """Does `root`'s parent contain nothing but `root`?

    C3 requires it. Reported rather than assumed, because `SanitizedTree.from_mapping` raises an
    `OrganizerFault` on `False` and a fabricated `True` would convert a real layout defect into a
    silently valid descriptor.
    """
    try:
        siblings = os.listdir(root.parent)
    except OSError:
        return False
    return siblings == [root.name]


#: Private aliases kept because two call sites inside this package predate the public spelling.
_fstat_verify = fstat_verify
_open_relative_nofollow = open_relative_nofollow
