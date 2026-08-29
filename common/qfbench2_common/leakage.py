"""Leakage / cutoff / embargo / contamination controls.

## Executive summary (read this first)

Closed-resource evaluation: data is sealed in both network modes — `none` is fully offline,
`restricted` allows model-API calls only, through the audited egress proxy.

**Frozen ruling R-8 (contract set 1.0.0): canary handling is verdict-only across every boundary.**
This module exposes exactly

    {"canary_verdict": "clean" | "hit", "hit_count": int,
     "scanned_file_count": int, "scanned_bytes": int}

and nothing else. The previous `scan_canary(text, registry) -> list[str]` returned the *matched
GUIDs*, i.e. the secret itself, from shared code that every track and the scoring container import.
That API is **withdrawn**, not deprecated: a token-returning function in shared code guarantees the
token reaches a log eventually — somebody prints the return value, or wraps it in an exception
message, or puts it in a `detail` dict that `failure_labels` serializes into a persistent CodaBench
artifact. The raw matched form now lives only inside the security-owned scanner, which is
not this package.

Three properties this module maintains, and which its tests assert directly:

1. **No return value, exception message, log line or `repr` contains a matched token, a registry
   entry, or a scanned path.** Counts and a two-valued verdict are the entire output vocabulary.
2. **Fail closed.** A tree the scanner cannot fully read is never reported `clean`. Anything that
   would leave bytes unexamined — a non-regular node, an unreadable file, a bound exceeded — raises
   `LeakageScanIncomplete` instead of returning a verdict.
3. **All bounded regular bytes are scanned**, at any nesting depth, whatever the filename. There is
   no extension allowlist: the interesting file is the one called `notes`, `.hidden`, or
   `output.bin`. Matching is over raw bytes, so a canary in a parquet footer or a pickled blob is
   found exactly as one in JSON is.

`LeakageScanIncomplete` is an `OrganizerFault` on purpose. The scanner is meant to run over the C3
`sanitized/` root, where the sanitizer has already refused every non-regular node and enforced the
size bounds; if the scanner meets one anyway, the wiring is wrong, not the participant. Per the
frozen C1 `organizer_failure` policy that aborts the evaluation rather than producing a
participant score.
"""

from __future__ import annotations

import os
import pathlib
import re
import stat
from dataclasses import dataclass
from typing import Final, Iterable, Literal

from .contracts.errors import OrganizerFault

# ISO 'YYYY-MM-DD' compares chronologically under lexical ordering.
_GUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

#: The exact key set of the frozen verdict. Consumers may assert against this rather than
#: hand-copying the four names. Adding a key is a contract change, not an implementation detail.
CANARY_VERDICT_KEYS: Final[tuple[str, ...]] = (
    "canary_verdict",
    "hit_count",
    "scanned_file_count",
    "scanned_bytes",
)

CanaryVerdictLiteral = Literal["clean", "hit"]


def cutoff_ok(asof: str, target_dates: Iterable[str]) -> bool:
    """True iff every forecast target strictly post-dates the as-of (no look-ahead).
    Applies to T2 (asof vs target window) and is reused by T4's question cutoff."""
    return all(asof < t for t in target_dates)


def embargo_ok(cited_dates: Iterable[str], cutoff: str) -> bool:
    """True iff no cited evidence post-dates the question cutoff (T4 stale-filing guard)."""
    return all(d <= cutoff for d in cited_dates)


class LeakageScanIncomplete(OrganizerFault):
    """The scan could not examine every byte it was asked to, so it refuses to return a verdict.

    Carries counts and a node-type or bound name — **never** a path, a filename, a byte of file
    content, or a registry entry. A path under the participant tree is participant-authored text
    and belongs in a public artifact no more than a canary does.
    """


@dataclass(frozen=True, slots=True)
class ScanLimits:
    """Bounds the scan refuses to exceed. Exceeding one is `LeakageScanIncomplete`, not truncation.

    Truncating at a bound would be the worst of both worlds: the scan reports `clean` while the
    canary sits in the unread tail. A bound that is too small for a legitimate tree is an
    organizer configuration error and should be loud.
    """

    max_files: int = 10_000
    max_file_bytes: int = 64 * 1024 * 1024
    max_total_bytes: int = 512 * 1024 * 1024
    max_depth: int = 32
    #: Bytes re-examined at each chunk boundary so a token straddling two reads is still found.
    #: Must exceed the longest registry entry; `scan_tree` raises if it does not.
    chunk_overlap_bytes: int = 256
    read_chunk_bytes: int = 1024 * 1024


DEFAULT_LIMITS: Final[ScanLimits] = ScanLimits()


@dataclass(frozen=True, slots=True)
class CanaryVerdict:
    """The whole public surface of a contamination scan.

    `hit_count` is the number of **distinct registry entries observed**, not the number of
    occurrences: an adversary who repeats one canary a thousand times must not be able to read a
    different number out of the verdict than one who wrote it once.

    The `repr` is the dataclass default over exactly these four fields, so it cannot contain a
    token. That is asserted by `test_leakage_verdict.py` rather than left to inspection.
    """

    canary_verdict: CanaryVerdictLiteral
    hit_count: int
    scanned_file_count: int
    scanned_bytes: int

    def __post_init__(self) -> None:
        if self.canary_verdict not in ("clean", "hit"):
            raise ValueError("canary_verdict must be 'clean' or 'hit'")
        if (self.hit_count > 0) != (self.canary_verdict == "hit"):
            raise ValueError("canary_verdict and hit_count disagree")

    def as_dict(self) -> dict[str, object]:
        """The C2 `leakage` block, exactly the four frozen keys, JSON-ready."""
        return {
            "canary_verdict": self.canary_verdict,
            "hit_count": self.hit_count,
            "scanned_file_count": self.scanned_file_count,
            "scanned_bytes": self.scanned_bytes,
        }


def is_canary_shaped(token: str) -> bool:
    """True iff `token` is a well-formed lowercase UUIDv4, the registry's canonical canary form."""
    return bool(_GUID_RE.fullmatch(token.strip().lower()))


def _needles(registry: Iterable[str], limits: ScanLimits) -> list[bytes]:
    """Normalize the registry to lowercase byte needles. Never echoes an entry in any error."""
    seen: set[bytes] = set()
    for raw in registry:
        if not isinstance(raw, str):
            raise LeakageScanIncomplete(
                "canary registry contains a non-string entry; the registry is a set of strings"
            )
        token = raw.strip().lower()
        if not token:
            raise LeakageScanIncomplete(
                "canary registry contains an empty entry; an empty needle matches everything"
            )
        if len(token) > limits.chunk_overlap_bytes:
            raise LeakageScanIncomplete(
                f"a canary registry entry is longer than chunk_overlap_bytes="
                f"{limits.chunk_overlap_bytes}; a token that long can straddle a chunk boundary "
                f"unseen, so the scan cannot certify the tree"
            )
        seen.add(token.encode("utf-8"))
    return sorted(seen)


def scan_text(
    text: str, registry: Iterable[str], *, limits: ScanLimits = DEFAULT_LIMITS
) -> CanaryVerdict:
    """Verdict for a single in-memory string (a log line, a rationale, a model transcript).

    `scanned_file_count` is 0 — there was no file — and `scanned_bytes` is the UTF-8 length of
    `text`, so the two counters mean the same thing here as they do for a tree.
    """
    needles = _needles(registry, limits)
    blob = text.encode("utf-8", errors="surrogatepass").lower()
    hits = sum(1 for n in needles if n in blob)
    return CanaryVerdict(
        canary_verdict="hit" if hits else "clean",
        hit_count=hits,
        scanned_file_count=0,
        scanned_bytes=len(blob),
    )


def _walk_regular_files(root: pathlib.Path, limits: ScanLimits) -> list[pathlib.Path]:
    """No-follow depth-first listing of regular files. Any other node type is fatal.

    Uses `os.scandir` with `follow_symlinks=False` throughout, so a directory symlink is *seen*
    and refused rather than descended into — the `nested-dir-symlink` case of the shared corpus,
    where a walker that descends enumerates the whole reference tree.
    """
    if not root.is_dir():
        raise LeakageScanIncomplete("scan root is not a directory")
    found: list[pathlib.Path] = []
    total_bytes = 0
    stack: list[tuple[pathlib.Path, int]] = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        if depth > limits.max_depth:
            raise LeakageScanIncomplete(
                f"tree exceeds max_depth={limits.max_depth}; the scan cannot certify it"
            )
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            raise LeakageScanIncomplete(
                "a directory in the scan root could not be listed; refusing to report a verdict "
                "over a tree that was only partly readable"
            ) from None
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                raise LeakageScanIncomplete(
                    "a node in the scan root could not be stat'd without following it"
                ) from None
            mode = st.st_mode
            if stat.S_ISDIR(mode):
                stack.append((pathlib.Path(entry.path), depth + 1))
                continue
            if not stat.S_ISREG(mode):
                raise LeakageScanIncomplete(
                    f"scan root contains a non-regular node (type bits 0o{stat.S_IFMT(mode):o}); "
                    f"the sanitized tree must contain regular files only, so this is an "
                    f"organizer wiring fault, not a participant one"
                )
            if st.st_nlink > 1:
                raise LeakageScanIncomplete(
                    "scan root contains a hard link (st_nlink > 1); its bytes may be shared with "
                    "a file outside the tree, so the tree's contents are not what they appear"
                )
            if st.st_size > limits.max_file_bytes:
                raise LeakageScanIncomplete(
                    f"a file exceeds max_file_bytes={limits.max_file_bytes}; refusing to scan a "
                    f"prefix and call the tree clean"
                )
            total_bytes += st.st_size
            if total_bytes > limits.max_total_bytes:
                raise LeakageScanIncomplete(
                    f"tree exceeds max_total_bytes={limits.max_total_bytes}"
                )
            found.append(pathlib.Path(entry.path))
            if len(found) > limits.max_files:
                raise LeakageScanIncomplete(f"tree exceeds max_files={limits.max_files}")
    return found


def scan_tree(
    root: str | os.PathLike[str], registry: Iterable[str], *, limits: ScanLimits = DEFAULT_LIMITS
) -> CanaryVerdict:
    """Scan every bounded regular file under `root` and return the frozen verdict.

    Every regular file is read, at any depth, regardless of name or extension — there is no
    extension allowlist, because the file a contaminated agent writes its training memory into is
    not called `.json`. Matching is byte-wise and case-folded over ASCII, so the canary is found in
    binary output as readily as in text.

    Raises `LeakageScanIncomplete` (an `OrganizerFault`) rather than returning `clean` for any
    tree it could not fully read.
    """
    needles = _needles(registry, limits)
    files = _walk_regular_files(pathlib.Path(root), limits)
    seen: set[bytes] = set()
    scanned_bytes = 0
    overlap = limits.chunk_overlap_bytes
    for path in files:
        try:
            with open(path, "rb") as fh:
                tail = b""
                while True:
                    chunk = fh.read(limits.read_chunk_bytes)
                    if not chunk:
                        break
                    scanned_bytes += len(chunk)
                    window = (tail + chunk).lower()
                    for needle in needles:
                        if needle not in seen and needle in window:
                            seen.add(needle)
                    tail = chunk[-overlap:] if overlap else b""
        except OSError:
            raise LeakageScanIncomplete(
                "a regular file in the scan root could not be read; an unreadable file is an "
                "explicit failure, never silently treated as absent"
            ) from None
    return CanaryVerdict(
        canary_verdict="hit" if seen else "clean",
        hit_count=len(seen),
        scanned_file_count=len(files),
        scanned_bytes=scanned_bytes,
    )


def scan_canary(text: str, registry: set[str]) -> list[str]:
    """**WITHDRAWN** by frozen ruling R-8. Use `scan_text` / `scan_tree`, which return a verdict.

    This used to return the matched canary GUIDs. It is kept as a raising stub rather than deleted
    so that a consumer still on the old API gets one loud, greppable error naming the replacement,
    instead of an `AttributeError` that reads like a packaging problem — and so that nobody
    reintroduces the name with the old semantics.
    """
    raise NotImplementedError(
        "scan_canary is withdrawn (frozen ruling R-8): it returned the matched canary tokens from "
        "shared code, which guarantees the token reaches a log. Use "
        "qfbench2_common.leakage.scan_tree(root, registry) or scan_text(text, registry); both "
        "return a verdict-only CanaryVerdict {canary_verdict, hit_count, scanned_file_count, "
        "scanned_bytes}. The raw matched form lives only in the security-owned scanner."
    )


def assert_network_isolated(env: dict[str, str] | None = None) -> None:
    """Best-effort assertion that the run is under a sanctioned network mode. The real
    guarantee is set by the harness at `docker run`: `--network=none` (simulation, fully
    offline) or the internal eval network whose only egress is the audited proxy to the
    model-API allowlist (`restricted`, agent tracks). This documents intent and fails fast
    in local dev if QFBENCH_NETWORK is neither 'none' nor 'restricted' — i.e. open internet."""
    import os

    env = env or dict(os.environ)
    if env.get("QFBENCH_NETWORK", "none") not in ("none", "restricted"):
        raise RuntimeError(
            "network-contract violation: QFBENCH_NETWORK must be 'none' or 'restricted'"
        )
