"""Split a unit tree into what a submission may see and what only the grader may see.

`ingest.py` bind-mounts each unit directory wholesale at `/input`, with no filtering of any kind.
So whatever is in the unit directory of the phase's `input_data` is readable by the submission --
including, if nobody separates them, the answers.

This is NOT the same question `manifest.assert_public_safe` answers. That one is repo hygiene:
what may sit in a public repo. It deliberately PERMITS answer material in `public-dev` units,
because practice units ship their answers so participants can self-grade locally. That is correct
and should stay. The mistake is reusing those same directories as an eval dataset without
splitting them, and no check catches that, because from the repo's point of view nothing is wrong.

CodaBench already provides the two slots this needs: `input_data` is mounted into the submission,
`reference_data` is read by the scoring program. This module builds the two trees that go in them.

Track 3's builder (`build_final_bundle.py`) has done this for the sealed set since before this
module existed; the declarations and the gate are lifted here so T1, T2 and T4 inherit them
instead of each re-deriving what an answer looks like.

## Two things changed on 2026-08-21, and both were measured defects

**1. The copy dereferenced links.** `shutil.copytree` without `symlinks=True` resolves a link and
copies the *target's bytes* as an ordinary file. A single cross-unit link
`unit_a/environment/aux.csv -> unit_b/reference/realized.parquet` therefore put `unit_b`'s answer
into `unit_a`'s mounted tree as a plain CSV, `split_unit` returned success, and no `AnswerLeak` was
raised. The content check could not catch it either, because `answer_blobs` is computed from *this*
unit only. Both copies are now no-follow walks over regular files (`qfbench2_common.sanitize`), and
a link or special node anywhere in the source is `UnsafeSourceTree` — an organizer fault, refused
before either tree is built. `symlinks=True` would have preserved the link instead of resolving it,
which is better but still wrong: a relative link inside a mounted tree is resolved by the *reader*,
and the reader is the submission.

**2. `ANSWER_DIRS` was two lists wearing one name (frozen ruling R-7).** "Strip this from the
mounted tree" and "fingerprint this as an answer" are different questions, and Track 4's
`factor_replication_exec` family is where the conflation bites: `tests/` must be stripped (it holds
`tests/data/thresholds.json` — the pass threshold, the composite weights, `ref_icir`/`ref_spread`
to full precision, and the reward keyword list, a rubric and an answer key at once), but it must
NOT be fingerprinted, because `tests/data/mkt_rf.csv` is byte-identical to the legitimate input
`environment/data/mkt_rf_monthly.csv` and the content check would refuse all six units. Under the
old single list, declaring `tests` closed the leak and broke the build; not declaring it kept the
build green over an open leak. `STRIP_DIRS` and `FINGERPRINT_DIRS` separate the two, and the
invariant `FINGERPRINT ⊆ STRIP` is asserted at import: fingerprinting something you leave mounted
would flag the mounted copy against itself.

R-7 says do both and ship neither alone. This module is the Hub half; Track 4 stopping the
duplicate-filename shipping is the other half, and it is not a substitute for this one.

A caveat for whoever generalises this: a declaration derived FROM the current unit trees recognises
today's layouts by construction and earns nothing against them. The old `ANSWER_DIRS["analysis"]`
would have passed "do all 36 units have reference/?" while this family mounted its own oracle. The
test that matters is whether a family with a DIFFERENT layout gets covered.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
from collections.abc import Iterable
from typing import Any

from .contracts.artifact_tree import NodeType, TreeLimits
from .sanitize import (
    MaterializedFile,
    materialize_tree,
    promote,
    staging_sibling,
    verify_destination,
    walk_nofollow,
)

__all__ = [
    "ANSWER_DIRS",
    "ANSWER_FILES",
    "AnswerLeak",
    "FINGERPRINT_DIRS",
    "FINGERPRINT_FILES",
    "STRIP_DIRS",
    "STRIP_FILES",
    "UnsafeSourceTree",
    "answer_blobs",
    "answer_paths",
    "assert_no_answer_reachable",
    "fingerprint_paths",
    "split_unit",
    "strip_paths",
]


class AnswerLeak(Exception):
    """Answer material is reachable from the tree that will be mounted into a submission."""


class UnsafeSourceTree(AnswerLeak):
    """The SOURCE unit tree holds a link or a special node, so what it contains is unknowable.

    A subclass of `AnswerLeak` on purpose: every existing caller already treats `AnswerLeak` as
    "do not ship this dataset", and a link whose target we refuse to resolve is exactly a possible
    answer leak we decline to prove either way. The distinct type exists so an operator can tell
    "your tree has a symlink in it" from "your tree has the answer in it".
    """


# Measured from the real units in each private repo, 2026-08-19. `reference/` covers three tracks;
# Track 3 is the outlier -- it stores answers FLAT beside the inputs, and batched units keep
# per-sub copies under `references/` (plural).
#
#   coding       reference/solve.sh                  (a runnable oracle)
#   forecasting  reference/realized.parquet          (the forecast target)
#   simulation   trace.parquet, events.json, message_trace.parquet   (flat),
#                checks/reference_data/ (batched; was references/ until the 2026-08 rename)
#   analysis     reference/outcome.json, adversarial_variants/, solution/, tests/ (exec family)
#
# The reference family is spelled THREE ways across the benchmark and all three are declared on
# every track, because the one thing these tables must survive is a rename. Track 3's batched
# reference material moved from `references/` to `checks/reference_data/` so it would satisfy
# `manifest.assert_public_safe` rather than escape it -- and landed on a name neither of these
# tables knew, which is worse than where it started. Measured 2026-08-29 on a private copy of
# `t3-gbatch-homog-4`: a planted `book_snapshot.parquet` (a basename `STRIP_FILES` does not list)
# was stripped under `references/` and SURVIVED INTO THE MOUNTED TREE under
# `checks/reference_data/`, and a byte-identical copy of it at `scenarios/` drew no `AnswerLeak`.
# Today's 90 shipped Track-3 reference files were stripped only because all 90 happen to be named
# `trace.parquet`, `events.json` or `message_trace.parquet`; the directory itself was invisible.
#
# So `reference`, `references` and `reference_data` are declared TOGETHER on every track, for the
# same reason `manifest._ORACLE_DIRS` lists `solution` and `solutions` together: a vocabulary that
# knows one spelling of a name is not a weaker guard than one that knows all three, it is a guard
# with a published bypass, and the bypass is a rename nobody has to justify. `manifest._ANSWER_DIRS`
# already refuses all three names in a public unit on EVERY track, so a track whose strip table
# recognises fewer of them is not being permissive on purpose -- it is out of step with the gate
# that shares its vocabulary. Adding the missing spellings changes nothing on any unit that exists:
# measured across all 274 staged public units, no unit carries a `reference/`, `references/` or
# root-level `reference_data/` directory, and Track 1's `checks/reference_data/` already sat inside
# the `checks` that `coding` strips wholesale.
#
# STRIP_DIRS: removed from the mounted tree. A directory name here is matched at ANY depth.
STRIP_DIRS: dict[str, tuple[str, ...]] = {
    "coding": ("reference", "references", "reference_data", "checks"),
    "forecasting": ("reference", "references", "reference_data"),
    "simulation": ("references", "reference", "reference_data"),
    "analysis": (
        "reference",
        "references",
        "reference_data",
        "adversarial_variants",
        "solution",
        "tests",
    ),
}

# STRIP_FILES: removed from the mounted tree by BASENAME, matched at any depth.
#
# `generation_log.jsonl` is not an answer, and it is here anyway. Four private Track-4 units
# shipped one at the unit root: the organizer's fetch-and-PII-strip provenance, including the
# redactions applied and the `name_hint_flags` that motivated them. Nothing stripped it, so it
# would have been mounted into the participant tree — a per-unit record of what the organizers
# considered sensitive about the unit, handed to the participant. Track 4 relocated its four
# instances, but relocation fixes the four files and not the class: `pii_strip.py` writes the log
# beside whatever it is run against, so the next run from inside a unit directory recreates it.
# A declaration is structural where a relocation is remembered.
#
# It is deliberately NOT fingerprinted (FINGERPRINT ⊆ STRIP, and this is in the difference): the
# log is provenance, not answer bytes, so hashing it would refuse a unit over a legitimate file
# that happened to match rather than catch a renamed answer.
STRIP_FILES: dict[str, tuple[str, ...]] = {
    "coding": (),
    "forecasting": (),
    "simulation": ("trace.parquet", "events.json", "message_trace.parquet"),
    "analysis": ("generation_log.jsonl",),
}

# FINGERPRINT_DIRS: hashed, so a copy of an answer under an innocuous name is caught. A strict
# SUBSET of STRIP_DIRS. Track 4's `tests/` is deliberately absent -- see the module docstring:
# it is stripped, and fingerprinting it would refuse six units over a legitimate shared input.
#
# The reference family is fingerprinted wherever it is stripped, and that is not decoration.
# Stripping `reference_data` alone would still mount a RENAMED copy of what is inside it, which is
# the same hole one level down: measured 2026-08-29, a planted `checks/reference_data/sub_00/
# book_snapshot.parquet` copied byte-for-byte to `scenarios/book_snapshot_input.parquet` reached
# the mounted tree with no `AnswerLeak` raised. Fingerprinting is also the fail-LOUD half of this
# pair -- an over-broad strip silently removes a file from the participant tree, while an
# over-broad fingerprint refuses the build and tells an organizer which two files collided.
FINGERPRINT_DIRS: dict[str, tuple[str, ...]] = {
    "coding": ("reference", "references", "reference_data", "checks"),
    "forecasting": ("reference", "references", "reference_data"),
    "simulation": ("references", "reference", "reference_data"),
    "analysis": ("reference", "references", "reference_data", "adversarial_variants", "solution"),
}

FINGERPRINT_FILES: dict[str, tuple[str, ...]] = {
    "coding": (),
    "forecasting": (),
    "simulation": ("trace.parquet", "events.json", "message_trace.parquet"),
    "analysis": (),
}

#: Deprecated aliases. `ANSWER_DIRS` conflated the two roles; consumers should move to
#: `STRIP_DIRS` / `FINGERPRINT_DIRS`. Kept bound to the STRIP tables because "what is removed from
#: the mounted tree" is the reading every existing caller depends on.
ANSWER_DIRS = STRIP_DIRS
ANSWER_FILES = STRIP_FILES


def _assert_declarations_consistent() -> None:
    """`FINGERPRINT ⊆ STRIP`, on every track, checked at import rather than in a test alone.

    Fingerprinting a directory that stays mounted would compare the mounted copy against itself
    and refuse every unit that has one. A future editor who adds a fingerprint entry without the
    matching strip entry finds out on import, not in production.
    """
    tracks = set(STRIP_DIRS)
    for table, name in (
        (STRIP_FILES, "STRIP_FILES"),
        (FINGERPRINT_DIRS, "FINGERPRINT_DIRS"),
        (FINGERPRINT_FILES, "FINGERPRINT_FILES"),
    ):
        if set(table) != tracks:
            raise AssertionError(f"{name} does not declare exactly {sorted(tracks)}")
    for track in tracks:
        extra_dirs = set(FINGERPRINT_DIRS[track]) - set(STRIP_DIRS[track])
        extra_files = set(FINGERPRINT_FILES[track]) - set(STRIP_FILES[track])
        if extra_dirs or extra_files:
            raise AssertionError(
                f"track {track!r} fingerprints {sorted(extra_dirs | extra_files)} without "
                "stripping it; a fingerprinted path that stays mounted collides with itself"
            )


_assert_declarations_consistent()


# --------------------------------------------------------------------------- declarations
def strip_paths(track: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(dirs, files) removed from the tree mounted into a submission, for `track`."""
    if track not in STRIP_DIRS:
        raise KeyError(f"unknown track {track!r}; known: {sorted(STRIP_DIRS)}")
    return STRIP_DIRS[track], STRIP_FILES[track]


def fingerprint_paths(track: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(dirs, files) whose CONTENT is hashed for the renamed-answer check, for `track`."""
    if track not in FINGERPRINT_DIRS:
        raise KeyError(f"unknown track {track!r}; known: {sorted(FINGERPRINT_DIRS)}")
    return FINGERPRINT_DIRS[track], FINGERPRINT_FILES[track]


def answer_paths(track: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Deprecated alias for `strip_paths`. Kept so existing track builders do not break."""
    return strip_paths(track)


# --------------------------------------------------------------------------- source inspection
def _observe(unit_dir: pathlib.Path) -> tuple[list[str], list[str]]:
    """`(regular file paths, directory paths)` under `unit_dir`, refusing links and special nodes."""
    walk = walk_nofollow(unit_dir, limits=_source_limits())
    if walk.rejections or walk.truncated:
        raise UnsafeSourceTree(
            f"{unit_dir} could not be enumerated safely: "
            + ", ".join(f"{c.value}x{n}" for c, n in sorted(walk.rejections.items()))
        )
    files: list[str] = []
    dirs: list[str] = []
    for obs in walk.observations:
        if obs.node_type is NodeType.DIRECTORY:
            dirs.append(obs.path)
        elif obs.node_type is NodeType.REGULAR:
            files.append(obs.path)
        else:
            raise UnsafeSourceTree(
                f"{unit_dir}/{obs.path} is a {obs.node_type.value}. A dataset build refuses to "
                "resolve it: a link's target is decided by whoever reads the mounted tree, and "
                "that reader is the submission. Replace it with the real file or delete it."
            )
    return files, dirs


def _source_limits() -> TreeLimits:
    # An organizer unit tree, not a participant artifact: bounds exist so a pathological tree
    # terminates the build, not to shape the dataset.
    return TreeLimits(
        max_files=200_000,
        max_depth=32,
        max_file_bytes=1 << 40,
        max_total_bytes=1 << 42,
        max_sparse_ratio=float("inf"),
    )


def _is_stripped(rel: str, dirs: tuple[str, ...], files: tuple[str, ...]) -> bool:
    """Match a declared directory name at ANY depth, or a declared file basename at any depth."""
    components = rel.split("/")
    if any(component in dirs for component in components[:-1]):
        return True
    return components[-1] in files or components[-1] in dirs


def answer_blobs(unit_dir: str | pathlib.Path, track: str) -> list[bytes]:
    """Every FINGERPRINTED file's bytes, for the content check in `assert_no_answer_reachable`.

    Reads the fingerprint tables, not the strip tables. Track 4's `tests/` is stripped and not
    fingerprinted, so its bytes never enter this list and cannot collide with a legitimate input.
    """
    unit_dir = pathlib.Path(unit_dir)
    dirs, files = fingerprint_paths(track)
    present, _dirs = _observe(unit_dir)
    out: list[bytes] = []
    for rel in sorted(present):
        if _is_stripped(rel, dirs, files):
            out.append((unit_dir / rel).read_bytes())
    return out


def assert_no_answer_reachable(
    mounted_unit: str | pathlib.Path, blobs: list[bytes], track: str
) -> None:
    """Raise `AnswerLeak` if anything answer-shaped survives in the tree that gets mounted.

    Checks names AND content. The content check is not paranoia: a copy of the reference trace
    under an innocuous name is still the reference trace, and a rename is the likeliest way for
    one to survive a hand-built staging step.

    Names are checked against `STRIP_*` (everything that must be gone) at any depth; content is
    checked against `blobs`, which `answer_blobs` builds from `FINGERPRINT_*` (the subset whose
    bytes are unambiguously answers).
    """
    mounted_unit = pathlib.Path(mounted_unit)
    dirs, files = strip_paths(track)
    present, directories = _observe(mounted_unit)
    for rel in sorted(directories):
        if rel.rsplit("/", 1)[-1] in dirs:
            raise AnswerLeak(f"{rel}/ present in the mounted tree: {mounted_unit}")
    for rel in sorted(present):
        if _is_stripped(rel, dirs, files):
            raise AnswerLeak(f"{rel} present in the mounted tree: {mounted_unit}")
    if not blobs:
        return
    known = {hashlib.sha256(b).hexdigest() for b in blobs}
    for rel in sorted(present):
        f = mounted_unit / rel
        h = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() in known:
            raise AnswerLeak(f"{f} is byte-identical to an answer file, under a different name")


# --------------------------------------------------------------------------- the split
def split_unit(
    unit_dir: str | pathlib.Path,
    mounted_root: str | pathlib.Path,
    grader_root: str | pathlib.Path,
    track: str,
) -> int:
    """Copy one unit into both trees: complete for the grader, stripped for the submission.

    Returns the number of source paths stripped from the mounted tree. Raises `AnswerLeak` rather
    than producing a tree that would hand a submission its own answer -- failing a dataset build is
    recoverable, and shipping one is not.

    Build order, per global rule 8: both trees are materialized into **fresh staging directories**
    by a no-follow walk that copies regular bytes only, verified **bidirectionally** against their
    own manifests, gated on `assert_no_answer_reachable`, and only then **atomically promoted** with
    `os.rename`. A build that fails at any step leaves no tree behind for someone to publish by
    accident.
    """
    unit_dir = pathlib.Path(unit_dir)
    strip_dirs, strip_files = strip_paths(track)
    source_files, _source_dirs = _observe(unit_dir)
    stripped = [rel for rel in source_files if _is_stripped(rel, strip_dirs, strip_files)]
    blobs = answer_blobs(unit_dir, track)

    grader = pathlib.Path(grader_root) / unit_dir.name
    mounted = pathlib.Path(mounted_root) / unit_dir.name
    grader_staging = staging_sibling(grader)
    mounted_staging = staging_sibling(mounted)

    try:
        grader_build = materialize_tree(unit_dir, grader_staging, limits=_source_limits())
        _require_complete(grader_build.files, source_files, "grader")
        _require_verified(grader_staging, grader_build.files, "grader")

        mounted_build = materialize_tree(
            unit_dir,
            mounted_staging,
            limits=_source_limits(),
            include=lambda rel: not _is_stripped(rel, strip_dirs, strip_files),
        )
        expected_mounted = [rel for rel in source_files if rel not in set(stripped)]
        _require_complete(mounted_build.files, expected_mounted, "mounted")
        _require_verified(mounted_staging, mounted_build.files, "mounted")
        # The one deliberate post-verification mutation: the checksum manifest was copied
        # verbatim, and it INVENTORIES the stripped paths (name + sha256). Rewriting it here,
        # after the bidirectional verify and before the leak gate, keeps the verify honest
        # about the copy while the promoted tree stops enumerating what was removed from it.
        _filter_mounted_manifest(mounted_staging, strip_dirs, strip_files)

        assert_no_answer_reachable(mounted_staging, blobs, track)

        promote(grader_staging, grader)
        promote(mounted_staging, mounted)
    except BaseException:
        shutil.rmtree(grader_staging, ignore_errors=True)
        shutil.rmtree(mounted_staging, ignore_errors=True)
        raise

    return len(stripped)


def _filter_mounted_manifest(
    mounted_staging: pathlib.Path, strip_dirs: tuple[str, ...], strip_files: tuple[str, ...]
) -> None:
    """Drop the stripped paths from the mounted tree's checksum manifest.

    Stripping removes the BYTES, but the copied `manifest.json` still enumerates every removed
    path with its sha256 -- and the filenames are the real cost: `tests/data/thresholds.json`
    tells an agent a rubric exists, and on an ordinary analysis unit the inventory names
    `adversarial_variants/stale_filing_trap.json`, which is a hint by filename alone. The grader
    tree keeps the complete manifest; only the mounted copy is filtered. `verify_manifest`
    accepts the filtered file (it checksums the entries that remain), and a mounted tree whose
    manifest no longer lists absent files verifies clean for EVERY unit, where before that
    depended on each stripped entry carrying `redistributable: false`.

    Fail-closed on a manifest this function cannot read: an inventory we cannot parse is an
    inventory we cannot prove clean, the same reasoning as `UnsafeSourceTree`. A unit with no
    `manifest.json` (fixtures, tracks without one) and a non-checksum file that merely uses the
    name (no `files` array -- the shape `verify_manifest` already rejects with its own message)
    are both left untouched.
    """
    mpath = mounted_staging / "manifest.json"
    if not mpath.is_file():
        return
    try:
        raw: Any = json.loads(mpath.read_text())
    except (OSError, ValueError) as exc:
        raise AnswerLeak(
            f"the mounted tree's manifest.json could not be parsed, so the stripped-path "
            f"inventory it may carry cannot be filtered: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise AnswerLeak(
            "the mounted tree's manifest.json is not a JSON object, so the stripped-path "
            "inventory it may carry cannot be filtered"
        )
    files = raw.get("files")
    if not isinstance(files, list):
        return
    kept: list[Any] = []
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise AnswerLeak(
                "the mounted tree's manifest.json has a files[] entry without a string 'path'; "
                "an inventory entry that cannot be read cannot be proven not to name a "
                f"stripped path: {entry!r}"
            )
        if not _is_stripped(entry["path"], strip_dirs, strip_files):
            kept.append(entry)
    if len(kept) == len(files):
        return
    raw["files"] = kept
    mpath.write_text(json.dumps(raw, indent=2) + "\n")


def _require_complete(
    built: Iterable[MaterializedFile], expected: Iterable[str], which: str
) -> None:
    """manifest -> disk and disk -> manifest, on the SET of paths, before anything is promoted."""
    got = {f.path for f in built}
    want = set(expected)
    missing = sorted(want - got)
    extra = sorted(got - want)
    if missing or extra:
        raise AnswerLeak(
            f"the {which} tree does not match its source exactly: missing={missing} "
            f"unexpected={extra}. A dataset build that cannot account for every file is refused, "
            "because the file it cannot account for is the one that matters."
        )


def _require_verified(staging: pathlib.Path, built: Iterable[MaterializedFile], which: str) -> None:
    errors = verify_destination(staging, built, limits=_source_limits())
    if errors:
        raise AnswerLeak(f"the {which} tree failed its own verification: " + "; ".join(errors))
