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

A track that has a non-rankable preview path exposes it under one of the names in
`PREVIEW_FACTORIES`, and this runner prefers those. A track that has only one factory keeps working
unchanged — the lookup falls back. The selection is also explicit: `--profile production` forces
`build_verifier` and fails loudly if a production run was asked for and the factory refuses, which
is what a smoke run must never do silently in the other direction.

## Why `PREVIEW_FACTORIES` has two names in it (added 2026-09-01)

The preview name is not spelled the same in every track. Track 4 calls its non-rankable factory
`build_smoke_verifier`; Track 3 calls its `build_developer_verifier`, because Track 3's preview
path differs from production in *what quantity it scores* — production reads an events/sec rate the
organizer MEASURED from Runner telemetry, the preview reads one the participant REPORTED — and
"developer" is the word its `rankable=False` artifacts already carry.

This table knew only `build_smoke_verifier`, so for Track 3 the lookup fell through to the
PRODUCTION factory, whose `_g0_integrity` requires the trusted C1 plan and C2 run record that no
laptop has. Measured before this change, on the documented command against a real unit:

    $ qfbench2-smoke units/t3-EXAMPLE-vectorized-matching out/ --track simulation
    Traceback (most recent call last):
      ...
      File ".../qfbench2_track_simulation/scoring.py", line 264, in _g0_integrity
    qfbench2_common.contracts.errors.OrganizerFault: the production Track 3 verifier requires
    the trusted C2 run record and the signed C1 plan in ctx.

An uncaught `OrganizerFault` is the worst available outcome here: it is the fault domain that means
"the organizers broke something", raised at a participant who did nothing wrong, with no verdict.
`--track simulation` is one of the four choices the CLI advertises and every toolkit README
documents, so this was a documented command that could not work.

TWO TABLES EXIST AND THEY MUST AGREE. The CodaBench scoring driver
(`scoring_program/score.py` in the competition bundles) carries its own
`_DEVELOPER_FACTORIES = ("build_developer_verifier", "build_smoke_verifier")`, added in hub PR #81,
which already resolves the preview names correctly for the scoring driver. That file is not in this
repository and this one is not in that bundle, so neither can import the other's table today; the
duplication is real and is not resolved here. What is enforced instead is that the two lists carry
the same names in the SAME ORDER, so that a track exposing both names cannot be scored by one
factory on the board and previewed by the other on a laptop. No track exposes both today — Track 3
has `build_verifier` + `build_developer_verifier`, Track 4 has `build_verifier` +
`build_smoke_verifier` — which is exactly the condition under which the order could drift with
nothing failing. If you add a name here, add it there.

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
    "DEVELOPER_FACTORY",
    "PREVIEW_FACTORIES",
    "PROFILES",
    "PRODUCTION_FACTORY",
    "SMOKE_FACTORY",
    "resolve_verifier_factory",
    "run_smoke",
]

#: The rankable factory every track exposes. Names the official, pinned-judge scoring path.
PRODUCTION_FACTORY = "build_verifier"
#: Track 4's spelling of the optional non-rankable factory.
SMOKE_FACTORY = "build_smoke_verifier"
#: Track 3's spelling of it. Its preview scores a participant-REPORTED rate where production scores
#: an organizer-MEASURED one, so the track names the factory for the audience rather than for the
#: runner that calls it.
DEVELOPER_FACTORY = "build_developer_verifier"
#: Every name a non-rankable preview path may be exposed under. Present only where a track has a
#: preview path that is deliberately weaker than production and stamps its artifacts
#: `rankable=False`. MUST stay in the same order as `_DEVELOPER_FACTORIES` in the
#: CodaBench driver's `scoring_program/score.py` — see the module docstring for why there are two
#: tables and what goes wrong if they drift.
PREVIEW_FACTORIES = (DEVELOPER_FACTORY, SMOKE_FACTORY)
#: Closed, like every other enum in this program.
PROFILES = ("production", "smoke")


def resolve_verifier_factory(
    module: ModuleType, profile: str = "smoke"
) -> tuple[str, Callable[[dict], HierarchicalVerifier]]:
    """`(factory_name, factory)` for `profile`, from a track's `scoring` module.

    `smoke` (the default for this runner) prefers a preview factory under any name in
    `PREVIEW_FACTORIES` and falls back to `build_verifier` for a track that has no separate preview
    path. `production` takes `build_verifier` and nothing else: a production request that silently
    ran a preview factory would report an admissibility that the leaderboard does not agree with,
    so no preview name is reachable from that profile at all.
    """
    if profile not in PROFILES:
        raise SystemExit(f"unknown profile {profile!r}; choose one of {list(PROFILES)}")
    names = (
        (PRODUCTION_FACTORY,)
        if profile == "production"
        else (*PREVIEW_FACTORIES, PRODUCTION_FACTORY)
    )
    for name in names:
        factory = getattr(module, name, None)
        if factory is not None:
            return name, factory
    raise SystemExit(
        f"{module.__name__} exposes none of {list(names)}. A track's scoring module is required "
        f"to expose {PRODUCTION_FACTORY}(ctx). A non-rankable preview path is additionally "
        f"exposed under one of these names, which is what --profile smoke looks for first: "
        f"{list(PREVIEW_FACTORIES)}."
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
