"""qfbench2 — unified command-line interface for the shared toolkit.

This is the single ``qfbench2`` entry point the track docs/AGENTS guides reference. It wraps the
library functions so authors and CI run identical code.

    qfbench2 smoke    <unit_dir> <output_dir> --track <track> [--profile smoke|production]
    qfbench2 card     validate <unit_dir>                       # schema-validate card.toml
    qfbench2 manifest assert-public-safe <unit_dir>            # firewall check (public repos)
    qfbench2 manifest verify <unit_dir>                        # checksum the manifested files
    qfbench2 manifest build  <unit_dir> [--data-subdir environment/data]
    qfbench2 eval     --track <track> --units <units_dir>      # lint every unit in a tree
    qfbench2 track1   score-harbor-job --job-dir <job_dir>     # score a Harbor job
    qfbench2 track4   score-exec-job --job-dir <job_dir>       # score a T4 exec Harbor job

``qfbench2-smoke`` remains as a thin alias for ``qfbench2 smoke`` (back-compat).

``smoke`` runs the track's NON-RANKABLE preview factory by default. `build_verifier` is the
rankable one and refuses without a pinned production judge, which is correct for the scoring image
and useless on a participant's laptop; `--profile production` asks for it explicitly. See
`qfbench2_common.smoke.resolve_verifier_factory`.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any, Callable

from . import manifest as M
from . import taskcard as T

#: Imported rather than restated: two spellings of one closed set is how they drift apart.
from .smoke import PROFILES as _PROFILES

_TRACKS = ["coding", "forecasting", "simulation", "analysis"]

#: Exit code for a *usage/organizer* error — a wrong track, an unreadable units tree, a units tree
#: with nothing in it. Kept distinct from 1 ("units were linted and some are bad") so a caller can
#: tell "the tree is wrong" from "the tree is fine and its contents are not".
EXIT_USAGE = 2


def _print_errs(label: str, errs: list[str]) -> bool:
    if errs:
        print(f"FAIL {label}:")
        for e in errs:
            print(f"  - {e}")
        return False
    print(f"OK   {label}")
    return True


def _cmd_smoke(args: argparse.Namespace) -> int:
    from importlib import import_module
    from .smoke import resolve_verifier_factory, run_smoke

    mod = import_module(f"qfbench2_track_{args.track}.scoring")
    _name, factory = resolve_verifier_factory(mod, getattr(args, "profile", "smoke"))
    v = run_smoke(args.unit_dir, args.output_dir, factory)
    return 0 if v.admissible else 1


def _cmd_card(args: argparse.Namespace) -> int:
    _card, errs = T.load_and_validate(args.unit_dir)
    return 0 if _print_errs(f"card {args.unit_dir}", errs) else 1


def _cmd_manifest(args: argparse.Namespace) -> int:
    unit = pathlib.Path(args.unit_dir)
    if args.action == "assert-public-safe":
        return 0 if _print_errs(f"public-safe {unit}", M.assert_public_safe(unit)) else 1
    if args.action == "verify":
        return 0 if _print_errs(f"manifest {unit}", M.verify_manifest(unit)) else 1
    if args.action == "build":
        man = _build_manifest(unit, args.data_subdir)
        (unit / "manifest.json").write_text(json.dumps(man, indent=2) + "\n")
        print(f"wrote {unit / 'manifest.json'} ({len(man['files'])} files)")
        return 0
    print(f"unknown manifest action {args.action!r}", file=sys.stderr)
    return 2


def _build_manifest(unit: pathlib.Path, data_subdir: str) -> dict[str, Any]:
    """Generate a checksum manifest (manifest_version 2.0) over the unit's data files."""
    unit_id = unit.name
    files = []
    data_dir = unit / data_subdir
    if data_dir.is_dir():
        for fp in sorted(data_dir.rglob("*")):
            if fp.is_file() and "__pycache__" not in fp.parts:
                files.append(
                    {
                        "path": str(fp.relative_to(unit)),
                        "role": "input",
                        "license": "CC-BY-NC-4.0",
                        "sha256": M.sha256_file(fp),
                        "bytes": fp.stat().st_size,
                        "split": "public-dev",
                        "redistributable": True,
                    }
                )
    return {
        "manifest_version": "2.0",
        "unit_id": unit_id,
        "generated_by": "qfbench2 manifest build",
        "files": files,
    }


def _card_track(unit: pathlib.Path) -> tuple[str | None, list[str]]:
    """`card.toml`'s declared `[task] track`, or `(None, errors)`.

    Reads the card defensively: a missing, unreadable or malformed `card.toml` must be reported as
    a unit-level error, never as an uncaught `FileNotFoundError` / `TOMLDecodeError` traceback out
    of the CLI. The exception text is not echoed verbatim — a parser message can quote the file's
    own bytes, and a unit tree is not always public.
    """
    try:
        card = T.load_card(unit)
    except FileNotFoundError:
        return None, ["no card.toml in this directory"]
    except OSError:
        return None, ["card.toml could not be read"]
    except Exception as exc:  # noqa: BLE001 - report, never crash
        return None, [f"card.toml is not parseable TOML ({type(exc).__name__})"]
    task = card.get("task")
    if not isinstance(task, dict) or "track" not in task:
        return None, ["card.toml declares no [task] track"]
    track = task["track"]
    if not isinstance(track, str):
        return None, ["card.toml [task] track is not a string"]
    return track, []


def _check(label: str, fn: Callable[[], list[str]]) -> bool:
    """Run one unit check, turning any exception into a reported error for that unit.

    A lint run must produce a verdict for every unit it discovered. Pre-fix, a unit with no
    `manifest.json` raised `FileNotFoundError` straight out of `verify_manifest`, aborting the
    run and leaving every later unit — including the ones with real leaks — unexamined. The
    exception's text is not echoed: a parser or path message can quote bytes from the tree.
    """
    try:
        return _print_errs(label, fn())
    except Exception as exc:  # noqa: BLE001 - report, never crash
        return _print_errs(label, [f"check raised {type(exc).__name__}"])


def _cmd_eval(args: argparse.Namespace) -> int:
    """Lint every unit in a units/ tree: track equality + card schema + manifest + public-safety.

    Three things used to be silently fine here and are now always errors, each confirmed by
    execution:

    * **`--track` was accepted and then never read.** `qfbench2 eval --track simulation` and
      `qfbench2 eval` produced byte-identical output on a Track 1 tree. Nothing anywhere compared
      the requested track to the cards, so a lint run "for simulation" proved nothing about
      simulation. `--track` is now required and every card must declare the same track.
    * **Zero units exited 0 with `ALL OK — 0 units`.** An empty or mistyped path was a green run.
      A lint that discovers nothing has verified nothing; it is now a usage error.
    * **A missing or malformed `card.toml` raised out of the CLI**, so one bad unit aborted the
      run and the remaining units went unlinted.

    Note the asymmetry this fixes on the CLI side: the scoring
    program defaults `QFBENCH_TRACK` to `"coding"` while the ingestion program does
    `os.environ["QFBENCH_TRACK"]` and raises. Same bundle, opposite behaviour on the same absent
    variable. Those two files are owned elsewhere; a cross-request carries the same rule to them.
    """
    units_dir = pathlib.Path(args.units)
    if not units_dir.is_dir():
        print(f"FAIL units tree {units_dir}: not a directory", file=sys.stderr)
        return EXIT_USAGE

    try:
        candidates = sorted(p for p in units_dir.iterdir() if p.is_dir() and not p.is_symlink())
    except OSError:
        print(f"FAIL units tree {units_dir}: could not be listed", file=sys.stderr)
        return EXIT_USAGE

    units = [p for p in candidates if p.name not in ("__pycache__",)]
    if not units:
        print(
            f"FAIL units tree {units_dir}: discovered 0 units.\n"
            f"  A lint run that finds nothing has verified nothing, so this is an error and not "
            f"'ALL OK — 0 units'. Check the path, and that the units are directories rather than "
            f"symlinks to directories (symlinked units are skipped deliberately).",
            file=sys.stderr,
        )
        return EXIT_USAGE

    ok = True
    for unit in units:
        track, terrs = _card_track(unit)
        if track is None:
            # The card is unreadable/unparseable/trackless. Report it once, under `track`, and
            # skip the schema check that would only restate it. The manifest and public-safety
            # checks do not depend on the card, so they still run: one broken card must not hide
            # a leak in the same unit.
            ok &= _print_errs(f"track {unit.name}", terrs)
        else:
            ok &= _print_errs(
                f"track {unit.name}",
                []
                if track == args.track
                else [
                    f"card declares track {track!r}, this run was invoked with "
                    f"--track {args.track!r}"
                ],
            )
            # The lambdas are invoked inside `_check` before the next iteration, so capturing
            # `unit` by closure rather than by default argument is safe and keeps them typed.
            ok &= _check(f"card {unit.name}", lambda: T.load_and_validate(unit)[1])
        ok &= _check(f"manifest {unit.name}", lambda: M.verify_manifest(unit))
        ok &= _check(f"public-safe {unit.name}", lambda: M.assert_public_safe(unit))
    print(
        f"\n{'ALL OK' if ok else 'PROBLEMS FOUND'} — {len(units)} units in {units_dir} "
        f"(track {args.track})"
    )
    return 0 if ok else 1


def _cmd_track1_score_harbor_job(args: argparse.Namespace) -> int:
    from .track1.harbor import score_harbor_job, write_harbor_score

    score = score_harbor_job(
        args.job_dir,
        units_dir=args.units_dir,
        n_attempts=args.n_attempts,
        n_boot=args.n_boot,
        seed=args.seed,
    )
    if args.out:
        write_harbor_score(score, args.out)
        print(f"wrote {args.out}")
    else:
        print(json.dumps(score, indent=2))
    return 0


def _cmd_track1_harbor_run(args: argparse.Namespace) -> int:
    from .track1.harbor import run_harbor, score_harbor_job, write_harbor_score

    proc = run_harbor(
        args.units_dir,
        jobs_dir=args.jobs_dir,
        job_name=args.job_name,
        n_attempts=args.n_attempts,
        agent=args.agent,
        n_concurrent=args.n_concurrent,
        harbor_executable=args.harbor_executable,
        task_names=args.task_name,
        extra_args=args.harbor_arg,
    )
    if proc.returncode != 0:
        return int(proc.returncode)

    if args.no_score:
        return 0
    job_dir = pathlib.Path(args.jobs_dir) / args.job_name
    score = score_harbor_job(
        job_dir,
        units_dir=args.units_dir,
        n_attempts=args.n_attempts,
        n_boot=args.n_boot,
        seed=args.seed,
    )
    if args.out:
        write_harbor_score(score, args.out)
        print(f"wrote {args.out}")
    else:
        print(json.dumps(score, indent=2))
    return 0


def _cmd_track4_score_exec_job(args: argparse.Namespace) -> int:
    from .track4.harbor_exec import score_exec_job, write_exec_score

    score = score_exec_job(
        args.job_dir,
        units_dir=args.units_dir,
        n_attempts=args.n_attempts,
        n_boot=args.n_boot,
        seed=args.seed,
    )
    if args.out:
        write_exec_score(score, args.out)
        print(f"wrote {args.out}")
    else:
        print(json.dumps(score, indent=2))
    return 0


def _cmd_track4_harbor_run(args: argparse.Namespace) -> int:
    from .track4.harbor_exec import run_harbor, score_exec_job, write_exec_score

    proc = run_harbor(
        args.units_dir,
        jobs_dir=args.jobs_dir,
        job_name=args.job_name,
        n_attempts=args.n_attempts,
        agent=args.agent,
        n_concurrent=args.n_concurrent,
        harbor_executable=args.harbor_executable,
        task_names=args.task_name,
        extra_args=args.harbor_arg,
    )
    if proc.returncode != 0:
        return int(proc.returncode)

    if args.no_score:
        return 0
    job_dir = pathlib.Path(args.jobs_dir) / args.job_name
    score = score_exec_job(
        job_dir,
        units_dir=args.units_dir,
        n_attempts=args.n_attempts,
        n_boot=args.n_boot,
        seed=args.seed,
    )
    if args.out:
        write_exec_score(score, args.out)
        print(f"wrote {args.out}")
    else:
        print(json.dumps(score, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qfbench2", description="QFBench 2.0 shared toolkit CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_smoke = sub.add_parser("smoke", help="run the track verifier on a produced output dir")
    p_smoke.add_argument("unit_dir")
    p_smoke.add_argument("output_dir")
    p_smoke.add_argument("--track", required=True, choices=_TRACKS)
    p_smoke.add_argument(
        "--profile",
        default="smoke",
        choices=list(_PROFILES),
        help="smoke (default): the track's non-rankable preview factory if it has one. "
        "production: the rankable factory, which may refuse without a pinned judge.",
    )
    p_smoke.set_defaults(func=_cmd_smoke)

    p_card = sub.add_parser("card", help="card.toml operations")
    card_sub = p_card.add_subparsers(dest="action", required=True)
    p_cv = card_sub.add_parser("validate", help="schema-validate card.toml")
    p_cv.add_argument("unit_dir")
    p_cv.set_defaults(func=_cmd_card)

    p_man = sub.add_parser("manifest", help="manifest operations")
    p_man.add_argument("action", choices=["assert-public-safe", "verify", "build"])
    p_man.add_argument("unit_dir")
    p_man.add_argument("--data-subdir", default="environment/data")
    p_man.set_defaults(func=_cmd_manifest)

    p_eval = sub.add_parser("eval", help="lint every unit in a units/ tree")
    # required=True is the fix. The flag was declared, accepted, and never read: the
    # command produced identical output with it, without it, and with the wrong value.
    p_eval.add_argument(
        "--track",
        required=True,
        choices=_TRACKS,
        help="the track every card in the tree must declare",
    )
    p_eval.add_argument("--units", required=True)
    p_eval.set_defaults(func=_cmd_eval)

    p_t1 = sub.add_parser("track1", help="Track 1 runner adapters")
    t1_sub = p_t1.add_subparsers(dest="action", required=True)

    p_t1_score = t1_sub.add_parser("score-harbor-job", help="score a completed Harbor job")
    p_t1_score.add_argument("--job-dir", required=True)
    p_t1_score.add_argument("--units-dir")
    p_t1_score.add_argument("--n-attempts", type=int, default=3)
    p_t1_score.add_argument("--n-boot", type=int, default=10_000)
    p_t1_score.add_argument("--seed", type=int, default=0)
    p_t1_score.add_argument("--out")
    p_t1_score.set_defaults(func=_cmd_track1_score_harbor_job)

    p_t1_run = t1_sub.add_parser("harbor-run", help="run Harbor and score the resulting job")
    p_t1_run.add_argument("--units-dir", required=True)
    p_t1_run.add_argument("--jobs-dir", required=True)
    p_t1_run.add_argument("--job-name", required=True)
    p_t1_run.add_argument("--n-attempts", type=int, default=3)
    p_t1_run.add_argument("--agent", default="oracle")
    p_t1_run.add_argument("--n-concurrent", type=int, default=1)
    p_t1_run.add_argument("--harbor-executable", default="harbor")
    p_t1_run.add_argument("--task-name", action="append")
    p_t1_run.add_argument("--harbor-arg", action="append", default=[])
    p_t1_run.add_argument("--n-boot", type=int, default=10_000)
    p_t1_run.add_argument("--seed", type=int, default=0)
    p_t1_run.add_argument("--out")
    p_t1_run.add_argument("--no-score", action="store_true")
    p_t1_run.set_defaults(func=_cmd_track1_harbor_run)

    p_t4 = sub.add_parser("track4", help="Track 4 exec-unit runner adapters")
    t4_sub = p_t4.add_subparsers(dest="action", required=True)

    p_t4_score = t4_sub.add_parser("score-exec-job", help="score a completed T4 exec Harbor job")
    p_t4_score.add_argument("--job-dir", required=True)
    p_t4_score.add_argument("--units-dir")
    p_t4_score.add_argument("--n-attempts", type=int, default=3)
    p_t4_score.add_argument("--n-boot", type=int, default=10_000)
    p_t4_score.add_argument("--seed", type=int, default=0)
    p_t4_score.add_argument("--out")
    p_t4_score.set_defaults(func=_cmd_track4_score_exec_job)

    p_t4_run = t4_sub.add_parser("harbor-run", help="run Harbor on T4 exec units and score")
    p_t4_run.add_argument("--units-dir", required=True)
    p_t4_run.add_argument("--jobs-dir", required=True)
    p_t4_run.add_argument("--job-name", required=True)
    p_t4_run.add_argument("--n-attempts", type=int, default=3)
    p_t4_run.add_argument("--agent", default="oracle")
    p_t4_run.add_argument("--n-concurrent", type=int, default=1)
    p_t4_run.add_argument("--harbor-executable", default="harbor")
    p_t4_run.add_argument("--task-name", action="append")
    p_t4_run.add_argument("--harbor-arg", action="append", default=[])
    p_t4_run.add_argument("--n-boot", type=int, default=10_000)
    p_t4_run.add_argument("--seed", type=int, default=0)
    p_t4_run.add_argument("--out")
    p_t4_run.add_argument("--no-score", action="store_true")
    p_t4_run.set_defaults(func=_cmd_track4_harbor_run)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
