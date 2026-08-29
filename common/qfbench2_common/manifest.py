"""Per-file data manifest: EXACT bidirectional verification + public-safety enforcement.

## Executive summary (read this first)

`verify_manifest` used to iterate the manifest and nothing else. A probe tree was built carrying
five separate defects — an absolute `path` that replaced the unit directory outright, a `../`
traversal, a duplicate entry, a symlink whose *target* got hashed, and an unmanifested file planted
on disk — and the old implementation returned **zero errors**. Every one of those is now an error,
and the reason the set is closed rather than "the five we thought of" is that verification runs in
both directions:

* **manifest -> disk.** Every entry's path is validated as a relative, NFC-normalized, traversal-free
  path *before* it is joined to anything, then resolved one component at a time against a directory
  descriptor with `O_NOFOLLOW`. A symlink is refused, not followed; a hard link (`st_nlink > 1`) is
  refused, because it is the same inode as whatever it was linked from and no symlink exists to
  detect; a FIFO, socket or device is refused as an unsupported node type; a mode-000 file is an
  explicit error and never "absent".
* **disk -> manifest.** The covered subtrees are walked with the same no-follow walk, and any
  regular file that is not in the manifest is an error. This is the direction that did not exist,
  and it is the one that catches a planted file.

Plus, across the whole entry set: no duplicate path, no case-insensitive collision, and no NFC/NFD
collision. The last two matter because the development hosts are macOS (APFS folds both) and the
workers are Linux (which does not) — a tree that verifies on one and means something different on
the other is exactly the shape this check exists to refuse.

### `coverage`: which subtrees the manifest claims to be exact over

A unit directory legitimately holds files that are not data — `card.toml`, `task.toml`,
`instruction.md`, `manifest.json` itself. Declaring the manifest exact over the whole unit would
make every real unit fail, so the manifest says what it covers:

```json
{"manifest_version": "2.0", "coverage": ["environment/data"], "files": [...]}
```

Each entry is a relative directory (or `"."` for the whole unit), covered **recursively**. When
`coverage` is absent it is *derived*, and the derivation is stated here rather than left implicit:

* the **immediate parent directory** of every entry that has one, covered recursively — so a
  manifest listing `environment/data/input.txt` is exact over all of `environment/data/`;
* plus the unit root, **non-recursively, always**.

The parent, not the first component, and the difference is load-bearing: a real Track 1 unit keeps
`environment/Dockerfile` (build input, not released data) beside `environment/data/` (released
data, manifested). Deriving `environment/` would refuse every such unit, which would make the check
something people turn off.

"Always" for the unit root is a change from "if any entry is a root-level file", and it is a fix
rather than a tightening. Under the old rule whether the root was policed at all was decided by an
accident of the manifest's contents: a unit whose manifest listed only `environment/data/input.txt`
had NO root coverage, so an `answers.json` planted beside `card.toml` produced zero errors, while
the identical file one level down inside `environment/data/` was refused. Measured over the 274
staged units of all four tracks, making it unconditional produces exactly one new error, and that
error is true — `t4-EXAMPLE-eps-beat` does not manifest its `task.json`, which its ten sibling
units all manifest.

The residual gap is real and is named on purpose: a manifest with no entry under `docs/` does not
police `docs/`, and neither does it police `environment/` in the example above. Declaring
`coverage` is how a unit closes it, and a unit that wants no gap declares `["."]`. `manifest.json`
is never an extra — a checksum manifest cannot contain its own checksum — and neither are the three
non-data unit-root files named above, which is what makes `["."]` a declaration a real unit can
actually adopt.
"""

from __future__ import annotations

import fnmatch
import json
import os
import pathlib
import stat
import unicodedata
from typing import Any

from .contracts.artifact_tree import NodeType
from .contracts.digest import normalize_tree_path
from .contracts.errors import ContractError
from .sanitize import (
    fstat_verify,
    hash_regular_file,
    open_relative_nofollow,
    walk_nofollow,
)

# The oracle SOLUTION and authoring scratch must never appear in a public repo.
# Note: practice tasks (split = public-dev) MAY ship their tests and reference VALUES (e.g.
# checks/reference_data/expected.json) so participants can self-grade — that is the point of a
# practice pool. What we hide in public is:
#   (a) the reference IMPLEMENTATION / oracle (solution/, reference/solve.sh, solution.py, *oracle*)
#       and explicit answer keys (answer_key*) — NEVER legitimate in a public repo, any split;
#   (b) authoring scratch (dev/);
#   (c) for any NON public-dev unit (held-out / validation / mis-tagged): also the answer-bearing
#       dirs and files (reference/, references/, reference_data/, adversarial_variants/, expected*,
#       outcome*.json, checkpoints.json).
# Held-out (private-test) answer keys live only in the private repo.
#
# Two tiers so the check matches the practice-pool design AND the firewall promise in the docs.
#
# Both vocabularies are SPELLING-COMPLETE on purpose. A guard that knows `solution/` but not
# `solutions/`, or `reference/` but not `references/`, is not a weaker guard — it is a guard with a
# published bypass, and the bypass is a plural `s`. Measured on this tree 2026-08-29: a planted
# `solutions/ref.py` and a planted `solve.py` both returned zero errors, and so did a
# `references/trace.parquet` on a `validation` unit, while their singular spellings were refused.
#
# `reference_data` joins them for the same reason, and it is the spelling that got away. Track 3's
# batched reference material was moved out of `references/` into `checks/reference_data/` so it
# would comply with rule (4) rather than trip it — and `checks/reference_data/` was a name this set
# did not know, so it stopped being answer material by being renamed. Measured 2026-08-29 on a
# private copy of `t3-gbatch-homog-4`: with the split flipped to `validation`, reference material
# under `checks/reference_data/` returned ZERO errors, and on a practice unit so did an answer key
# at `checks/reference_data/reference_data/outcome.json` — the blocked layout rebuilt one directory
# inside the exemption, which is the bypass `_self_grading_path` already refuses for `reference/`.
# The practice pool's own `checks/reference_data/` root stays exempt; see `_self_grading_path`,
# which now has to say so out loud because the root's own name is answer vocabulary.
_ORACLE_DIRS = {
    "solution",
    "solutions",
    "oracle_output",
    "oracle_logs",
    "dev",
}  # oracle/scratch — block always
_ORACLE_GLOBS = (
    "*oracle*",
    "answer_key*",
    "solve.sh",
    "solve.py",
    "solution.py",
)  # oracle impl / key — block always
_ANSWER_DIRS = {
    "reference",
    "references",
    "reference_data",
    "adversarial_variants",
}  # answer material — block unless public-dev
_ANSWER_GLOBS = (
    "expected*",
    "outcome*.json",
    "checkpoints.json",
)  # resolved outcomes — block unless public-dev

#: Files a unit legitimately holds at its ROOT that are not released data, so they are never
#: "unmanifested extras". `manifest.json` is here because a checksum manifest cannot carry its own
#: checksum; the other three are the non-data unit metadata this module's own header names
#: (`card.toml`, `task.toml`, `instruction.md`). Membership is tested against the whole relative
#: path, not the basename, so this exempts them only at the unit root — a `checks/card.toml` is
#: still an extra. Without these three, the unit root cannot be covered (see `_derive_coverage`)
#: and neither can a unit adopt the `"coverage": ["."]` that the module header offers as the way
#: to close the residual gap: declaring it would refuse every real unit on its own card.
_NEVER_AN_EXTRA = frozenset({"manifest.json", "card.toml", "task.toml", "instruction.md"})

#: Byte-code caches are not released data and `cli.py`'s manifest builder already skips them. If
#: verification flagged them, every unit built by the shipped builder would fail its own check.
_IGNORED_COMPONENTS = frozenset({"__pycache__"})

#: Bounds for the verification walk. Deliberately far looser than the C3 participant bounds: this
#: walks an ORGANIZER-authored unit tree, where a legitimate corpus can be large. The point of the
#: bound is that a pathological tree terminates the check, not that it shapes the dataset.
_WALK_LIMITS_DEPTH = 32
_WALK_LIMITS_FILES = 200_000


def _unit_walk_limits() -> Any:
    from .contracts.artifact_tree import TreeLimits

    return TreeLimits(
        max_files=_WALK_LIMITS_FILES,
        max_depth=_WALK_LIMITS_DEPTH,
        max_file_bytes=1 << 40,
        max_total_bytes=1 << 42,
        max_sparse_ratio=float("inf"),
    )


def sha256_file(path: str | pathlib.Path, chunk: int = 1 << 20) -> str:
    """sha256 of a regular file, refusing a symlink or any non-regular node.

    Returns bare hex (not `sha256:<hex>`) because that is what `manifest.json` has always stored
    and what `cli.py`'s manifest builder writes. The change from the previous implementation is
    that `open()` no longer follows a link: hashing a symlink used to record the digest of the
    *target*, which is how a manifest entry could certify a file living outside the unit.
    """
    del chunk  # the read size is fixed by hash_regular_file; kept for call-site compatibility
    p = pathlib.Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(p, flags)
    try:
        fstat_verify(fd, str(p))
        digest, _size = hash_regular_file(fd)
    finally:
        os.close(fd)
    return digest.removeprefix("sha256:")


def load_manifest(unit_dir: str | pathlib.Path) -> dict[str, Any]:
    return json.loads((pathlib.Path(unit_dir) / "manifest.json").read_text())


# --------------------------------------------------------------------------- entry validation
def _entry_paths(
    manifest: dict[str, Any],
) -> tuple[list[tuple[int, str, dict[str, Any]]], list[str]]:
    """Validate every entry's shape and path. Returns `[(index, normalized_path, entry)], errors`."""
    rows: list[tuple[int, str, dict[str, Any]]] = []
    errs: list[str] = []
    for index, entry in enumerate(manifest["files"]):
        if not isinstance(entry, dict):
            errs.append(f"files[{index}] is not an object")
            continue
        if "path" not in entry:
            errs.append(f"files[{index}] has no 'path'")
            continue
        if "sha256" not in entry:
            errs.append(f"files[{index}] ({entry['path']!r}) has no 'sha256'")
            continue
        try:
            # Absolute paths, `..`, `.`, empty components, backslash separators, drive letters and
            # control characters all die here — BEFORE the path is joined to the unit directory.
            # The old code did `unit_dir / entry["path"]`, and pathlib's `/` lets an absolute
            # right-hand side replace the left one outright.
            path = normalize_tree_path(entry["path"], field=f"files[{index}].path")
        except ContractError as exc:
            errs.append(f"unsafe manifest path in files[{index}]: {exc}")
            continue
        rows.append((index, path, entry))
    return rows, errs


def _collision_errors(rows: list[tuple[int, str, dict[str, Any]]]) -> list[str]:
    """Duplicate, case-insensitive and NFC/NFD collisions across the entry set."""
    errs: list[str] = []
    seen: dict[str, int] = {}
    folded: dict[str, str] = {}
    decomposed: dict[str, str] = {}
    for index, path, _entry in rows:
        if path in seen:
            errs.append(
                f"duplicate manifest entry for {path!r} (files[{seen[path]}] and files[{index}])"
            )
        else:
            seen[path] = index
        key = path.casefold()
        if key in folded and folded[key] != path:
            errs.append(
                f"case-insensitive collision between {folded[key]!r} and {path!r}: the Linux "
                "workers keep both files and this macOS host folds them into one"
            )
        folded.setdefault(key, path)
        nfd = unicodedata.normalize("NFD", path)
        if nfd in decomposed and decomposed[nfd] != path:
            errs.append(f"unicode normalization collision between {decomposed[nfd]!r} and {path!r}")
        decomposed.setdefault(nfd, path)
    return errs


# --------------------------------------------------------------------------- coverage
def _declared_coverage(manifest: dict[str, Any]) -> list[str] | None:
    if "coverage" not in manifest:
        return None
    raw = manifest["coverage"]
    if not isinstance(raw, list):
        raise ContractError("'coverage' must be an array of relative directory paths")
    out: list[str] = []
    for item in raw:
        if item == ".":
            return ["."]
        out.append(normalize_tree_path(item, field="coverage[]"))
    return out


def _derive_coverage(paths: list[str]) -> tuple[set[str], bool]:
    """`(recursive_roots, cover_unit_root_nonrecursively)` — see the module docstring.

    The unit root is covered **unconditionally**. It used to be covered only when the manifest
    happened to list a root-level file, which made the root a blind spot whose existence depended
    on an accident of the manifest's contents rather than on any policy: measured on this tree
    2026-08-29, an `answers.json` planted at the root of a unit whose manifest listed only
    `environment/data/input.txt` produced **zero** errors, while the same file planted one level
    down inside `environment/data/` was refused. A gate that sees a planted answer key at depth 1
    and not at depth 0 is not enforcing anything at depth 0.

    Making it unconditional costs nothing on honest units because the four non-data unit-root
    files are in `_NEVER_AN_EXTRA`: over the 274 staged units of all four tracks, the change
    produces exactly ONE new error, and it is a true one (`t4-EXAMPLE-eps-beat` does not manifest
    its `task.json`; its ten sibling units all manifest theirs).

    The residual gap this does NOT close is named here rather than left to be rediscovered: a
    brand-new TOP-LEVEL DIRECTORY holding no manifested file is still outside derived coverage.
    Claiming every such directory recursively was measured on the same corpus and would refuse 388
    legitimate files — 301 under Track 1's `checks/` and 87 `environment/Dockerfile` — i.e. it
    would refuse every Track 1 unit for shipping its own graders and its own build input. A unit
    that wants no gap at all declares `"coverage": ["."]`, which `_NEVER_AN_EXTRA` now makes
    usable.
    """
    roots: set[str] = set()
    for path in paths:
        parent, sep, _name = path.rpartition("/")
        if sep:
            roots.add(parent)
    return roots, True


def coverage_of(manifest: dict[str, Any], paths: list[str]) -> tuple[set[str], bool]:
    """Resolve the exactness scope: `(recursive roots, whether the unit root is covered flat)`.

    `["."]` means the whole unit recursively and is expressed as the recursive root `""`.
    """
    declared = _declared_coverage(manifest)
    if declared is None:
        return _derive_coverage(paths)
    if declared == ["."]:
        return {""}, True
    return set(declared), False


def _covered(path: str, roots: set[str], root_flat: bool) -> bool:
    if "" in roots:
        return True
    if "/" not in path:
        return root_flat
    return any(path == r or path.startswith(f"{r}/") for r in roots)


# --------------------------------------------------------------------------- verification
def verify_manifest(
    unit_dir: str | pathlib.Path,
    manifest: dict[str, Any] | None = None,
) -> list[str]:
    """Verify a unit's checksum manifest EXACTLY, in both directions. Returns a list of errors.

    manifest -> disk: every committed entry exists, is a plain single-linked readable regular file,
    and hashes to the recorded digest. Non-redistributable entries (`redistributable: false`) are
    referenced by hash only and may be absent — but if such a file *is* present it is still
    checksummed, because "we said it might not be here" is not licence to ship a different one.

    disk -> manifest: every regular file inside the covered subtrees appears in the manifest.

    Returns `[]` for a clean unit. The list-of-strings shape is preserved because `cli.py`,
    `smoke.py` and every track's CI print it.
    """
    unit_dir = pathlib.Path(unit_dir)
    manifest = manifest or load_manifest(unit_dir)
    if "files" not in manifest:
        # The canonical manifest.json is the per-file CHECKSUM manifest (manifest_version 2.0,
        # files[]). A track data-spec / corpus-index must use a different filename, not manifest.json.
        return [
            "manifest.json has no 'files' array (not a valid checksum manifest); "
            "rename any data-spec/corpus-index to a non-'manifest.json' filename"
        ]
    if not isinstance(manifest["files"], list):
        return ["manifest.json 'files' is not an array"]

    rows, errs = _entry_paths(manifest)
    errs.extend(_collision_errors(rows))

    manifested = {path for _i, path, _e in rows}
    errs.extend(_check_manifest_to_disk(unit_dir, rows))
    errs.extend(_check_disk_to_manifest(unit_dir, manifest, sorted(manifested)))
    return errs


def _check_manifest_to_disk(
    unit_dir: pathlib.Path, rows: list[tuple[int, str, dict[str, Any]]]
) -> list[str]:
    errs: list[str] = []
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0)
    try:
        root_fd = os.open(unit_dir, flags | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        return [f"cannot open unit directory {unit_dir}: {exc}"]
    try:
        for _index, path, entry in rows:
            required = entry.get("redistributable", True) is not False
            try:
                st = _lstat_relative_nofollow(root_fd, path)
            except FileNotFoundError:
                if required:
                    errs.append(f"missing committed file: {path}")
                continue
            except OSError as exc:
                # An intermediate component that is a symlink lands here (ELOOP), which is the
                # point: the escape is refused at resolution time, not diagnosed afterwards.
                errs.append(f"cannot resolve {path} without following a link: {exc.strerror}")
                continue
            node = _classify(st)
            if node is not NodeType.REGULAR:
                errs.append(
                    f"{path} is a {node.value}, not a plain file; manifest entries are checksummed "
                    "by content and a link is a reference to content that lives somewhere else"
                )
                continue
            try:
                fd = open_relative_nofollow(root_fd, path)
            except PermissionError:
                errs.append(f"{path} is not readable; an unreadable file is an error, not 'absent'")
                continue
            except OSError as exc:
                errs.append(f"cannot open {path}: {exc.strerror}")
                continue
            try:
                digest, _size = hash_regular_file(fd)
            finally:
                os.close(fd)
            actual = digest.removeprefix("sha256:")
            expected = entry["sha256"]
            if not isinstance(expected, str) or actual != expected:
                shown = expected[:12] if isinstance(expected, str) else repr(expected)
                errs.append(f"checksum mismatch {path}: {actual[:12]}!={shown}")
    finally:
        os.close(root_fd)
    return errs


def _lstat_relative_nofollow(root_fd: int, rel: str) -> os.stat_result:
    """`lstat` `rel` under `root_fd`, refusing to traverse a symlinked intermediate directory."""
    components = rel.split("/")
    current = os.dup(root_fd)
    try:
        for component in components[:-1]:
            nxt = os.open(
                component,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=current,
            )
            os.close(current)
            current = nxt
        return os.lstat(components[-1], dir_fd=current)
    finally:
        os.close(current)


def _classify(st: os.stat_result) -> NodeType:
    from .contracts.artifact_tree import classify_node

    return classify_node(st.st_mode, st.st_nlink)


def _check_disk_to_manifest(
    unit_dir: pathlib.Path, manifest: dict[str, Any], manifested: list[str]
) -> list[str]:
    """The direction that did not exist. Walk the covered subtrees and refuse anything unlisted."""
    errs: list[str] = []
    try:
        roots, root_flat = coverage_of(manifest, manifested)
    except ContractError as exc:
        return [f"invalid 'coverage' declaration: {exc}"]
    if not roots and not root_flat:
        return errs

    try:
        walk = walk_nofollow(unit_dir, limits=_unit_walk_limits())
    except ContractError as exc:
        return [f"cannot walk {unit_dir}: {exc}"]

    listed = set(manifested)
    for code, count in sorted(walk.rejections.items()):
        errs.append(f"unit tree holds {count} node(s) the walk refused as {code.value}")
    for obs in walk.observations:
        if obs.node_type is NodeType.DIRECTORY:
            continue
        if not _covered(obs.path, roots, root_flat):
            continue
        if obs.path in _NEVER_AN_EXTRA:
            continue
        if _IGNORED_COMPONENTS.intersection(obs.path.split("/")):
            continue
        if obs.node_type is not NodeType.REGULAR:
            errs.append(
                f"{obs.path} is a {obs.node_type.value} inside a manifest-covered directory; "
                "only plain files may be released"
            )
            continue
        if obs.path not in listed:
            errs.append(
                f"unmanifested file on disk: {obs.path} (inside a covered directory). Every "
                "released file needs a manifest entry; add it or narrow 'coverage'."
            )
    return errs


# --------------------------------------------------------------------------- public safety
def _split_of(unit_dir: pathlib.Path) -> str | None:
    """Read task.split from card.toml, or None if there is no card."""
    cp = unit_dir / "card.toml"
    if not cp.exists():
        return None
    try:
        import tomllib as _toml  # Python 3.11+
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as _toml  # type: ignore
    with cp.open("rb") as fh:
        return _toml.load(fh).get("task", {}).get("split")


def _observations(unit_dir: pathlib.Path) -> Any:
    return walk_nofollow(unit_dir, limits=_unit_walk_limits())


def _dirs_anywhere(observations: Any, names: set[str]) -> list[str]:
    """Every directory at OR below the unit whose name is in `names`.

    Was `rglob`, which **follows directory symlinks** — so a link named `data -> ../../private`
    made the scan enumerate somebody else's tree, and a link cycle made it loop. The no-follow walk
    classifies a symlinked directory as a link and never descends it.
    """
    return sorted(
        obs.path
        for obs in observations.observations
        if obs.node_type is NodeType.DIRECTORY and obs.path.rsplit("/", 1)[-1] in names
    )


def _glob_hits(observations: Any, pattern: str) -> list[str]:
    return sorted(
        obs.path
        for obs in observations.observations
        if fnmatch.fnmatch(obs.path.rsplit("/", 1)[-1], pattern)
    )


#: The single location a practice unit may keep reference values: what a participant self-grades
#: against. Anything answer-bearing outside it is a leak whatever the split says. Held as PATH
#: COMPONENTS, not as a string prefix, because the exemption is about a place in the tree and
#: `str.startswith` cannot express one.
_SELF_GRADING_ROOT: tuple[str, ...] = ("checks", "reference_data")


def _self_grading_path(split: str | None, path: str) -> bool:
    """True only for the documented self-grading location on a practice unit.

    Two conditions, and the second is the one that was missing. The path must live under
    `checks/reference_data/` **by component** — and nothing beneath that root may itself be named
    with the answer or oracle vocabulary. Since 2026-08-29 that vocabulary includes `reference_data`
    itself, so the root is exempt (the `not below` branch) while a `reference_data/` anywhere else,
    or nested inside the exemption, is not.

    The exemption used to be the bare prefix test `path.startswith("checks/reference_data/")`,
    which grants the whole subtree unconditionally. Measured on this tree 2026-08-29: a practice
    unit carrying `checks/reference_data/reference/outcome.json` — a resolved answer key, in a
    directory named exactly what the scorer reads — returned **no errors at all**, while the same
    file at `reference/outcome.json` was refused twice over. Re-creating the blocked layout one
    level inside the exemption is not a corner case; it is the shortest path around the rule, and a
    prefix test cannot tell the two apart because to a prefix test they are the same string with
    something in front.

    What stays exempt is what the exemption is for: reference VALUES a participant self-grades
    against, at any depth of the practice pool's own batched layout — `expected.json`,
    `checkpoints.json`, `sub_01/expected.json`. What is refused is answer material that has been
    given an answer-material name underneath it.
    """
    if split != "public-dev":
        return False
    parts = [p for p in path.split("/") if p]
    depth = len(_SELF_GRADING_ROOT)
    if tuple(parts[:depth]) != _SELF_GRADING_ROOT:
        return False
    below = parts[depth:]
    if not below:
        # The self-grading ROOT itself, on a practice unit. This branch used to return False and
        # was documented as unreachable, which was true only while `reference_data` was absent from
        # `_ANSWER_DIRS`: nothing named the root, so nothing asked about it. Now that the root's own
        # basename is answer vocabulary, `_dirs_anywhere` reports `checks/reference_data` on every
        # practice unit that has one, and returning False here would refuse all 24 of them (18 in
        # Track 1, 6 in Track 3, all `public-dev`, measured 2026-08-29) over the one directory the
        # exemption exists to permit. `split != "public-dev"` was already checked above, so a
        # held-out or validation unit never reaches this line — which is the whole point of adding
        # the name: outside the practice pool, `checks/reference_data/` is now refused like
        # `references/` always was.
        return True
    return not any(p in _ANSWER_DIRS or p in _ORACLE_DIRS for p in below)


def assert_public_safe(unit_dir: str | pathlib.Path) -> list[str]:
    """Fail if a public-repo unit leaks answers. Wired into public-repo CI.

    Enforced:
      1. The unit must carry a card.toml with a known split (a unit with no card cannot be
         confirmed public-safe — an answer-key-only directory would otherwise pass silently).
      2. A held-out (split == "private-test") unit must never appear in a public repo.
      3. The oracle implementation / scratch (solution/, solutions/, *oracle*, solve.sh, solve.py,
         solution.py, answer_key*, dev/) is blocked for EVERY split — it is never legitimate in
         public. Both spellings of each name are listed; see `_ORACLE_DIRS` on why a missing plural
         is a bypass rather than a gap.
      4. For any non public-dev unit, answer-bearing material (reference/, references/,
         reference_data/, adversarial_variants/, expected*, outcome*.json, checkpoints.json) is
         also blocked.
         Practice (public-dev) units MAY keep tests + reference VALUES under
         checks/reference_data/ for self-grading — but that exemption does not extend to material
         RE-NAMED with the answer or oracle vocabulary inside it (see `_self_grading_path`).
      5. No manifest entry may reference a non-redistributable file.
      6. No symlink, hard link or special node anywhere in the unit. A link is a name for content
         that lives somewhere this check cannot see, so a link is a hole in every rule above it.
    """
    unit_dir = pathlib.Path(unit_dir)
    errs: list[str] = []

    split = _split_of(unit_dir)
    if split is None:
        errs.append("unit has no card.toml with [task].split; cannot confirm public-safety")
    elif split == "private-test":
        errs.append("held-out (private-test) unit must not appear in a public repo")

    try:
        observations = _observations(unit_dir)
    except ContractError as exc:
        return [*errs, f"cannot walk {unit_dir}: {exc}"]

    # (6) links and special nodes — a released tree is plain files and directories, full stop.
    for obs in observations.observations:
        if obs.node_type in (NodeType.DIRECTORY, NodeType.REGULAR):
            continue
        errs.append(
            f"public unit must not contain '{obs.path}' (a {obs.node_type.value}); a released "
            "tree is plain files only, because a link names content this check cannot inspect"
        )

    # (3) oracle / scratch — blocked for every split, recursively.
    for d in _dirs_anywhere(observations, _ORACLE_DIRS):
        errs.append(f"public unit must not contain '{d}/' (oracle/answer material)")
    for pattern in _ORACLE_GLOBS:
        for hit in _glob_hits(observations, pattern):
            errs.append(f"public unit must not contain '{hit}' (oracle implementation/key)")

    # (4) answer-bearing material.
    #
    # A practice (public-dev) unit gets ONE narrow exemption: reference VALUES under
    # `checks/reference_data/`, which is what lets a participant self-grade. That exemption used to
    # be applied to the WHOLE unit, which is a far larger permission than the one it documents: a
    # practice unit could carry `reference/outcome.json` -- the answer key, at the exact path the
    # scorer reads -- and this function returned no errors at all. Measured 2026-08-28 by planting a
    # genuine private outcome.json into a public practice unit: the caller exited 0 and printed
    # "answer-safe". The exemption is now scoped to the path that justifies it.
    #
    # Scoped, and scoped BY COMPONENT. The first attempt at that scoping was the string prefix
    # `path.startswith("checks/reference_data/")`, which hands the entire subtree over: measured
    # again on 2026-08-29, `checks/reference_data/reference/outcome.json` returned zero errors on a
    # practice unit. Rebuilding the blocked layout one directory inside the exemption is the
    # cheapest bypass there is, and a prefix test is structurally unable to see it.
    for d in _dirs_anywhere(observations, _ANSWER_DIRS):
        if _self_grading_path(split, f"{d}/"):
            continue
        errs.append(f"public unit must not contain '{d}/' (answer material)")
    for pattern in _ANSWER_GLOBS:
        for hit in _glob_hits(observations, pattern):
            if _self_grading_path(split, hit):
                continue
            errs.append(f"public unit must not contain '{hit}' (resolved outcome)")

    # (5) non-redistributable references.
    try:
        for entry in load_manifest(unit_dir).get("files", []):
            if not entry.get("redistributable", True):
                errs.append(f"public unit references non-redistributable file '{entry['path']}'")
    except FileNotFoundError:
        errs.append("missing manifest.json")
    return errs


# Re-exported for callers that want the raw predicate without importing `stat`.
def is_plain_file(path: str | pathlib.Path) -> bool:
    """True only for a single-linked regular file. `Path.is_file()` is True for a symlink to one."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_nlink == 1
