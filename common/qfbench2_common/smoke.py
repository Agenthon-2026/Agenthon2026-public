"""Public smoke-test runner.

Ships in every PUBLIC repo. Participants run it locally to confirm their submission is
admissible against a public-dev/validation unit and to see the reference scorer's output
on PUBLIC targets. It exercises the SAME g0/g1 gates and scorer code as the sealed final
scorer, so "passes smoke" is a faithful (if non-binding) preview of admissibility.

## Which factory this runs, and why it is not always `build_verifier` (changed 2026-08-22)

`build_verifier` is now the **rankable** factory. Track 4's constructs the pinned production NLI
judge and *refuses* when there is no such judge on the machine — correctly: a missing judge is an
organizer fault, and the frozen C1 organizer-failure policy is to abort rather than publish a
partial leaderboard. That is the right behaviour for the scoring image and the wrong behaviour for
a participant previewing their submission on a laptop, and until now `qfbench2-smoke` called
`build_verifier` by name and so was simply broken for Track 4. Track 4 shipped a module-level
stopgap; this is the shared fix.

A track that has a non-rankable preview path exposes it as `build_smoke_verifier`, and this runner
prefers it. A track that has only one factory keeps working unchanged — the lookup falls back. The
selection is also explicit: `--profile production` forces `build_verifier` and fails loudly if a
production run was asked for and the factory refuses, which is what a smoke run must never do
silently in the other direction.

The chosen factory is printed with the verdict. "Passes smoke" and "would rank" are different
claims and the participant should be able to see which one they were given.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from types import ModuleType
from typing import Callable

from . import manifest, taskcard
from .verifier import HierarchicalVerifier, Verdict

__all__ = [
    "PROFILES",
    "PRODUCTION_FACTORY",
    "SMOKE_FACTORY",
    "resolve_verifier_factory",
    "run_smoke",
]

#: The rankable factory every track exposes. Names the official, pinned-judge scoring path.
PRODUCTION_FACTORY = "build_verifier"
#: The optional non-rankable factory. Present only where a track has a preview path that is
#: deliberately weaker than production and stamps its artifacts `rankable=False`.
SMOKE_FACTORY = "build_smoke_verifier"
#: Closed, like every other enum in this program.
PROFILES = ("production", "smoke")


def resolve_verifier_factory(
    module: ModuleType, profile: str = "smoke"
) -> tuple[str, Callable[[dict], HierarchicalVerifier]]:
    """`(factory_name, factory)` for `profile`, from a track's `scoring` module.

    `smoke` (the default for this runner) prefers `build_smoke_verifier` and falls back to
    `build_verifier` for a track that has no separate preview path. `production` takes
    `build_verifier` and nothing else: a production request that silently ran the smoke factory
    would report an admissibility that the leaderboard does not agree with.
    """
    if profile not in PROFILES:
        raise SystemExit(f"unknown profile {profile!r}; choose one of {list(PROFILES)}")
    names = (
        (PRODUCTION_FACTORY,) if profile == "production" else (SMOKE_FACTORY, PRODUCTION_FACTORY)
    )
    for name in names:
        factory = getattr(module, name, None)
        if factory is not None:
            return name, factory
    raise SystemExit(
        f"{module.__name__} exposes none of {list(names)}. A track's scoring module is required "
        f"to expose {PRODUCTION_FACTORY}(ctx); a non-rankable preview path is additionally "
        f"exposed as {SMOKE_FACTORY}(ctx)."
    )


def run_smoke(
    unit_dir: str | pathlib.Path,
    output_dir: str | pathlib.Path,
    build_verifier: Callable[[dict], HierarchicalVerifier],
) -> Verdict:
    """Validate the card+manifest, then run the track verifier on a produced output dir.
    `build_verifier(ctx)` is supplied by the track's scoring package."""
    unit_dir, output_dir = pathlib.Path(unit_dir), pathlib.Path(output_dir)
    card, card_errs = taskcard.load_and_validate(unit_dir)
    if card_errs:
        raise SystemExit("card.toml invalid:\n  " + "\n  ".join(card_errs))
    man_errs = manifest.verify_manifest(unit_dir)
    if man_errs:
        raise SystemExit("manifest verification failed:\n  " + "\n  ".join(man_errs))

    ctx = {
        "unit_dir": unit_dir,
        "output_dir": output_dir,
        "card": card,
        "split": card["task"]["split"],
    }
    verdict = build_verifier(ctx).run(ctx)
    factory = getattr(build_verifier, "__name__", "<factory>")
    print(
        f"[{card['task']['id']}] factory={factory} admissible={verdict.admissible} "
        f"score={verdict.score} labels={[lab.value for lab in verdict.labels]}"
    )
    return verdict


def _cli() -> int:
    ap = argparse.ArgumentParser(prog="qfbench2-smoke")
    ap.add_argument("unit_dir")
    ap.add_argument("output_dir")
    ap.add_argument(
        "--track", required=True, choices=["coding", "forecasting", "simulation", "analysis"]
    )
    ap.add_argument(
        "--profile",
        default="smoke",
        choices=list(PROFILES),
        help="smoke (default): the track's non-rankable preview factory if it has one, else the "
        "single factory it exposes. production: the rankable factory, which may refuse "
        "without a pinned production judge.",
    )
    args = ap.parse_args()
    from importlib import import_module

    mod = import_module(f"qfbench2_track_{args.track}.scoring")  # provided by the track repo
    _name, factory = resolve_verifier_factory(mod, args.profile)
    v = run_smoke(args.unit_dir, args.output_dir, factory)
    return 0 if v.admissible else 1


if __name__ == "__main__":
    sys.exit(_cli())
