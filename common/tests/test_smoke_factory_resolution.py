"""The smoke runner's factory table, in both directions.

The table used to know one preview name, `build_smoke_verifier`. Track 3 exposes its preview path
as `build_developer_verifier`, so the lookup fell through to the PRODUCTION factory, whose
`_g0_integrity` refuses off-platform. Measured against a real unit on 2026-09-01, before the fix:

    $ qfbench2-smoke units/t3-EXAMPLE-vectorized-matching out/ --track simulation
    qfbench2_common.contracts.errors.OrganizerFault: the production Track 3 verifier requires
    the trusted C2 run record and the signed C1 plan in ctx.        # uncaught, exit 1

    $ qfbench2-smoke units/t4-EXAMPLE-eps-beat out/ --track analysis
    [t4-EXAMPLE-eps-beat] factory=build_smoke_verifier admissible=False ...   # the contrast case

Both directions are asserted here, because only one of them is the participant-visible one and the
other is the one that must never move: `--profile production` must reach `build_verifier` and no
preview name, ever. A preview factory silently answering a production request would report an
admissibility the leaderboard does not agree with, which is a worse defect than the one above.

These use synthetic modules with the four real name shapes rather than importing a track package —
the track repos are not installed alongside this one, and the property under test is the toolkit's
lookup, not any track's scoring.
"""

from __future__ import annotations

import types

import pytest

from qfbench2_common import smoke


def _module(name: str, **factories: object) -> types.ModuleType:
    """A stand-in for a track's `scoring` module exposing exactly `factories`."""
    mod = types.ModuleType(name)
    for attr, value in factories.items():
        setattr(mod, attr, value)
    return mod


# The four shapes that exist across the four tracks, keyed by what `--profile smoke` must pick.
_PRODUCTION_ONLY = ("build_verifier",)  # Tracks 1 and 2
_TRACK3 = ("build_verifier", "build_developer_verifier")
_TRACK4 = ("build_verifier", "build_smoke_verifier")
_BOTH_PREVIEWS = ("build_verifier", "build_developer_verifier", "build_smoke_verifier")


@pytest.mark.parametrize(
    ("exposed", "expected"),
    [
        (_PRODUCTION_ONLY, "build_verifier"),
        (_TRACK3, "build_developer_verifier"),
        (_TRACK4, "build_smoke_verifier"),
        # No track ships this today. It is pinned so that the tie-break is a decision on record
        # rather than whatever the tuple happened to be ordered as when someone adds it.
        (_BOTH_PREVIEWS, "build_developer_verifier"),
    ],
    ids=["production-only", "track3-developer", "track4-smoke", "both-preview-names"],
)
def test_smoke_profile_prefers_a_preview_factory_under_either_name(
    exposed: tuple[str, ...], expected: str
) -> None:
    mod = _module("fake.scoring", **{n: (lambda ctx, _n=n: _n) for n in exposed})
    name, factory = smoke.resolve_verifier_factory(mod, "smoke")
    assert name == expected
    assert factory is getattr(mod, expected)


@pytest.mark.parametrize(
    "exposed",
    [_PRODUCTION_ONLY, _TRACK3, _TRACK4, _BOTH_PREVIEWS],
    ids=["production-only", "track3-developer", "track4-smoke", "both-preview-names"],
)
def test_production_profile_reaches_build_verifier_and_no_preview_name(
    exposed: tuple[str, ...],
) -> None:
    """The half of this that must not move. Asserted for every shape, not just the new one."""
    mod = _module("fake.scoring", **{n: (lambda ctx, _n=n: _n) for n in exposed})
    name, factory = smoke.resolve_verifier_factory(mod, "production")
    assert name == smoke.PRODUCTION_FACTORY
    assert factory is mod.build_verifier


def test_production_profile_refuses_a_module_with_only_a_preview_factory() -> None:
    """It must NOT fall back the other way. A track that lost `build_verifier` is broken, and
    refusing is the only correct answer to a production request.

    The assertion is on the list of names the resolver SEARCHED, which the message quotes. An
    earlier draft asserted the preview names appeared nowhere in the message at all; that failed,
    and the test was wrong rather than the code — the message's closing sentence names them on
    purpose, to tell an author what a preview path is called. What must not happen is a preview
    name entering the production search, and that is what is checked here.
    """
    for preview in smoke.PREVIEW_FACTORIES:
        mod = _module("fake.scoring", **{preview: (lambda ctx: None)})
        with pytest.raises(SystemExit) as exc:
            smoke.resolve_verifier_factory(mod, "production")
        searched, _, _ = str(exc.value).partition(". ")
        assert searched.endswith(f"exposes none of {[smoke.PRODUCTION_FACTORY]}")
        assert preview not in searched


def test_a_module_exposing_no_factory_names_the_names_it_needed() -> None:
    mod = _module("fake.scoring")
    with pytest.raises(SystemExit) as exc:
        smoke.resolve_verifier_factory(mod, "smoke")
    message = str(exc.value)
    for expected in (smoke.PRODUCTION_FACTORY, *smoke.PREVIEW_FACTORIES):
        assert expected in message


def test_unknown_profile_is_refused() -> None:
    with pytest.raises(SystemExit):
        smoke.resolve_verifier_factory(
            _module("fake.scoring", build_verifier=lambda ctx: None), "rankable"
        )


def test_preview_table_matches_the_codabench_driver_table() -> None:
    """The second table lives in `scoring_program/score.py` as `_DEVELOPER_FACTORIES` and is not in
    this repository, so this cannot compare the two by import. It pins THIS side's contents and
    order literally, so that changing it is a visible edit to a test that names the other table
    rather than a silent one-word change to a tuple. If you change this, change that."""
    assert smoke.PREVIEW_FACTORIES == ("build_developer_verifier", "build_smoke_verifier")
    assert smoke.PRODUCTION_FACTORY not in smoke.PREVIEW_FACTORIES
    assert smoke.DEVELOPER_FACTORY in smoke.PREVIEW_FACTORIES
    assert smoke.SMOKE_FACTORY in smoke.PREVIEW_FACTORIES
