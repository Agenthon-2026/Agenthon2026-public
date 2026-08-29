#!/usr/bin/env python3
"""Generate the shared malicious-output conformance corpus.

Every workstream in the remediation program needs the same adversarial filesystem cases: Hub (C3
primitives), Runner (materialization), CodaBench (two-stage topology), and Tracks 1-4 (parsers).
Five separately-invented corpora would disagree about what "should fail" means, and a case that one
repo omits is exactly the case that ships. So the corpus is generated from one script, and the
expected verdict for each case is data, not prose.

The trees cannot be committed to git: git stores a symlink but not a FIFO, a socket, a sparse file,
or a case/Unicode collision that the checkout filesystem folds. Generating them makes the corpus
portable and makes each case's construction auditable.

    python make_malicious_trees.py --out /tmp/corpus          # build every buildable case
    python make_malicious_trees.py --out /tmp/corpus --json   # emit the expectation manifest only

Layout mirrors the real scoring namespace, because several cases are only dangerous in that shape:

    <out>/<case>/input/ref/<unit>/    grader reference tree (holds the sentinel)
    <out>/<case>/input/res/<unit>/    participant output tree (holds the attack)

CONTAINS NO SEALED DATA. The only "secret" is the synthetic sentinel below, which exists so a test
can assert that a scorer never read it.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import socket
import stat
import sys
import unicodedata

# Synthetic. If this string appears in a scorer's output, logs, or artifacts, the case failed.
SENTINEL = "SEALED-SENTINEL-DO-NOT-READ-7f3a9c21"
UNIT = "unit-01"

# Verdicts: REJECT = the tree must be refused before a track parser sees it.
#           ACCEPT = positive control; must survive and score normally.
REJECT, ACCEPT = "REJECT", "ACCEPT"


def _mkbase(case_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    ref = case_dir / "input" / "ref" / UNIT
    res = case_dir / "input" / "res" / UNIT
    ref.mkdir(parents=True, exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)
    (ref / "targets.json").write_text(json.dumps({"answer": SENTINEL}) + "\n")
    return ref, res


# Each builder gets (ref, res) and returns None, or a string explaining why it could not build.
def _rel_symlink_to_ref(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    (res / "predictions.json").symlink_to("../../ref/" + UNIT + "/targets.json")
    return None


def _abs_symlink_outside(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    # Points at a synthetic file this generator creates, NOT at /etc/passwd. A real system path
    # makes any permission-restoring cleanup walk (`chmod -R`, or Path.chmod in a loop) follow the
    # link and try to chmod the system file, which blocks on a permission prompt and hangs the
    # caller. Use follow_symlinks=False in cleanup regardless; this just removes the landmine.
    outside = ref.parent.parent.parent / "outside-the-worker-root.txt"
    outside.write_text("synthetic host file the participant must not reach\n")
    (res / "predictions.json").symlink_to(outside)
    return None


def _nested_dir_symlink(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    (res / "sub").symlink_to("../../ref/" + UNIT)
    return None


def _symlink_chain(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    (res / "hop1").symlink_to("hop2")
    (res / "hop2").symlink_to("../../ref/" + UNIT + "/targets.json")
    return None


def _dangling_symlink(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    (res / "predictions.json").symlink_to("./nowhere-at-all")
    return None


def _hardlink_to_ref(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    try:
        os.link(ref / "targets.json", res / "predictions.json")
    except OSError as exc:
        return f"hard link refused by filesystem: {exc}"
    return None


def _fifo(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    try:
        os.mkfifo(res / "predictions.json")
    except (OSError, AttributeError) as exc:
        return f"mkfifo unavailable: {exc}"
    return None


def _unix_socket(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    # AF_UNIX paths are capped near 104 bytes on macOS, and the corpus is often built under a long
    # scratch path, so bind a short relative name from inside the directory rather than the
    # absolute one.
    prev = os.getcwd()
    try:
        os.chdir(res)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind("predictions.sock")
        s.close()
    except OSError as exc:
        return f"socket bind failed: {exc}"
    finally:
        os.chdir(prev)
    return None


def _sparse_file(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    # Apparent size 8 GiB, allocation a few blocks. A limit that measures st_size rejects it; a
    # limit that measures blocks does not. Both behaviours are defensible, so the expectation is
    # REJECT on apparent size and the case exists to force the choice to be explicit.
    p = res / "predictions.json"
    with p.open("wb") as fh:
        fh.truncate(8 * 1024 * 1024 * 1024)
        fh.write(b"{}")
    return None


def _deep_nesting(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    d = res
    for i in range(64):
        d = d / f"d{i}"
    d.mkdir(parents=True)
    (d / "predictions.json").write_text("{}")
    return None


def _many_files(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    for i in range(5000):
        (res / f"f{i:05d}.json").write_text("{}")
    return None


def _case_collision(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    (res / "predictions.json").write_text('{"v": 1}')
    p = res / "PREDICTIONS.JSON"
    if p.exists():  # case-insensitive filesystem folded them
        return "filesystem is case-insensitive; collision cannot be built here"
    p.write_text('{"v": 2}')
    return None


def _unicode_collision(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    nfc = unicodedata.normalize("NFC", "café.json")
    nfd = unicodedata.normalize("NFD", "café.json")
    (res / nfc).write_text('{"v": 1}')
    p = res / nfd
    if p.exists():
        return "filesystem normalises Unicode; collision cannot be built here"
    p.write_text('{"v": 2}')
    return None


def _setuid_bit(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    p = res / "predictions.json"
    p.write_text("{}")
    p.chmod(p.stat().st_mode | stat.S_ISUID | stat.S_IXUSR)
    return None


def _unreadable_file(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    p = res / "predictions.json"
    p.write_text("{}")
    p.chmod(0o000)
    return None


def _malformed_json(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    (res / "predictions.json").write_text('{"forecast": [1, 2, ')
    return None


def _nonfinite_json(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    # Bare NaN/Infinity: Python's json accepts these by default, most other parsers do not.
    (res / "predictions.json").write_text('{"forecast": [NaN, Infinity, -Infinity]}')
    return None


def _empty_output(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    pass  # res/<unit>/ exists but is empty
    return None


def _valid_control(ref: pathlib.Path, res: pathlib.Path) -> str | None:
    (res / "predictions.json").write_text(json.dumps({"forecast": [0.1, 0.2, 0.3]}) + "\n")
    return None


CASES = [
    (
        "rel-symlink-to-ref",
        REJECT,
        _rel_symlink_to_ref,
        "Relative symlink from the participant tree into the sibling reference tree. MEASURED to "
        "succeed against a naive loader today; Path.is_file() returns True for it, so an is_file() "
        "guard does not protect.",
    ),
    (
        "abs-symlink-outside",
        REJECT,
        _abs_symlink_outside,
        "Absolute symlink to a host path outside the worker root.",
    ),
    (
        "nested-dir-symlink",
        REJECT,
        _nested_dir_symlink,
        "Directory symlink: a walker that descends into it enumerates the whole reference tree.",
    ),
    (
        "symlink-chain",
        REJECT,
        _symlink_chain,
        "Two-hop chain. A defence that resolves only one level is defeated.",
    ),
    (
        "dangling-symlink",
        REJECT,
        _dangling_symlink,
        "Link to a nonexistent target. Must be refused as an unsupported node type, not skipped "
        "silently and not crash the run.",
    ),
    (
        "hardlink-to-ref",
        REJECT,
        _hardlink_to_ref,
        "Hard link to a reference file: no symlink to detect, st_nlink > 1 is the only signal.",
    ),
    (
        "fifo",
        REJECT,
        _fifo,
        "FIFO in place of the expected output file. A reader blocks forever; this is the "
        "hang-the-worker case, so a deadline is part of passing it.",
    ),
    ("unix-socket", REJECT, _unix_socket, "Socket node: unsupported type."),
    (
        "sparse-file",
        REJECT,
        _sparse_file,
        "8 GiB apparent, a few blocks allocated. Forces size limits to state whether they measure "
        "apparent size or allocation.",
    ),
    ("deep-nesting", REJECT, _deep_nesting, "64 levels: depth bound."),
    ("many-files", REJECT, _many_files, "5000 files: file-count bound."),
    (
        "case-collision",
        REJECT,
        _case_collision,
        "predictions.json and PREDICTIONS.JSON. Manifest exactness must not depend on filesystem "
        "case folding.",
    ),
    (
        "unicode-collision",
        REJECT,
        _unicode_collision,
        "NFC and NFD spellings of one name. Manifests must compare a normalised form.",
    ),
    ("setuid-bit", REJECT, _setuid_bit, "setuid mode bits on participant output."),
    (
        "unreadable-file",
        REJECT,
        _unreadable_file,
        "Mode 000. Must be an explicit failure, never silently treated as absent.",
    ),
    (
        "malformed-json",
        REJECT,
        _malformed_json,
        "Truncated JSON. Must be a deterministic PARTICIPANT failure, not an organizer fault and not "
        "an uncaught exception.",
    ),
    (
        "nonfinite-json",
        REJECT,
        _nonfinite_json,
        "Bare NaN/Infinity tokens. Must never reach aggregation.",
    ),
    (
        "empty-output",
        REJECT,
        _empty_output,
        "Unit directory present, no files. Must consume the participant-failure policy and stay in "
        "the denominator.",
    ),
    (
        "valid-control",
        ACCEPT,
        _valid_control,
        "POSITIVE CONTROL. An ordinary well-formed output. If this is rejected, the defences are too "
        "strict and every rejection above is uninterpretable.",
    ),
]


def build(out: pathlib.Path) -> list[dict[str, object]]:
    manifest = []
    for name, verdict, fn, why in CASES:
        case_dir = out / name
        entry: dict[str, object] = {
            "case": name,
            "expect": verdict,
            "rationale": why,
            "res_dir": f"{name}/input/res/{UNIT}",
            "ref_dir": f"{name}/input/ref/{UNIT}",
        }
        try:
            ref, res = _mkbase(case_dir)
            skipped = fn(ref, res)
        except Exception as exc:  # noqa: BLE001 - report, do not abort the set
            skipped = f"{type(exc).__name__}: {exc}"
        if skipped:
            entry["built"] = False
            entry["unbuildable_reason"] = skipped
        else:
            entry["built"] = True
        manifest.append(entry)
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # NOT required=True: `--json` builds nothing, so demanding an output directory for it was
    # simply wrong, and the README documented the correct usage against an argparse that refused it.
    ap.add_argument(
        "--out",
        type=pathlib.Path,
        help="directory to build the corpus into (required unless --json)",
    )
    ap.add_argument(
        "--json", action="store_true", help="print the expectation manifest and build nothing"
    )
    args = ap.parse_args()

    if args.json:
        print(
            json.dumps([{"case": c, "expect": v, "rationale": w} for c, v, _, w in CASES], indent=2)
        )
        return 0

    if args.out is None:
        ap.error("--out is required unless --json is given")
    if args.out.exists() and any(args.out.iterdir()):
        print(
            f"refusing: {args.out} is not empty. Some cases chmod 000 or create FIFOs; "
            f"rebuilding over them is how a stale case silently survives.",
            file=sys.stderr,
        )
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = build(args.out)
    (args.out / "expectations.json").write_text(
        json.dumps({"sentinel": SENTINEL, "unit": UNIT, "cases": manifest}, indent=2) + "\n"
    )

    built = sum(1 for m in manifest if m["built"])
    print(f"built {built}/{len(manifest)} cases into {args.out}")
    for m in manifest:
        if not m["built"]:
            print(f"  UNBUILDABLE {m['case']}: {m['unbuildable_reason']}")
    print(f"expectations: {args.out / 'expectations.json'}")
    print(
        "NOTE: some cases are mode 000 or FIFOs. Remove with `chmod -R u+rwX` first, and use\n      follow_symlinks=False in any walk that changes modes - this tree contains symlinks by design."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
