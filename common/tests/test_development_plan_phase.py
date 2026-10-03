"""`development_plan(phase=...)`: a plan for another phase is the Development plan in that phase.

A plan built for phase `final` must be the Development plan in every byte but `phase` and the
identifiers the caller passes, and a sealed phase must still hold its roster to the opaque handle
grammar. Each claim is pinned against the Development default, so a template or entry change made
for one phase cannot silently diverge from the other.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from qfbench2_common.contracts import ContractError, EvaluationPlan, OrganizerFault
from qfbench2_common.contracts.devattest import development_plan
from qfbench2_common.contracts.fixtures import dev_trust_store
from qfbench2_common.contracts.plan import derive_opaque_roster
from qfbench2_common.contracts.signing import SignatureUnverifiable

SIGNED_AT = "2026-10-01T00:00:00Z"
TRACKS = ("coding", "forecasting", "simulation", "analysis")
#: Synthetic, never a real phase salt.
SALT = "synthetic-test-salt-" + "0" * 40
HANDLES = list(derive_opaque_roster(["unit-a", "unit-b", "unit-c"], phase_salt=SALT))


def _plan(track: str, **kwargs) -> dict:
    return development_plan(
        track=track, handles=HANDLES, competition_id="c", plan_id="p", signed_at=SIGNED_AT, **kwargs
    )


def _bytes(body: dict) -> bytes:
    return (json.dumps(body, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


@pytest.mark.parametrize("track", TRACKS)
def test_naming_the_development_phase_changes_no_byte(track: str) -> None:
    assert _bytes(_plan(track, phase="dev")) == _bytes(_plan(track))


@pytest.mark.parametrize("track", TRACKS)
def test_a_final_plan_differs_from_the_development_plan_only_in_its_phase(track: str) -> None:
    dev, final = _plan(track), _plan(track, phase="final")
    assert final["phase"] == "final" and dev["phase"] == "dev"
    unsigned = {k: v for k, v in final.items() if k not in ("phase", "signature")}
    assert unsigned == {k: v for k, v in dev.items() if k not in ("phase", "signature")}
    plan = EvaluationPlan.from_mapping(final)
    assert plan.phase == "final" and list(plan.expected_handles) == HANDLES
    # Signed with the published development key: verifiable as development, never as production.
    assert not plan.verify_signature(
        dev_trust_store(), require_production_trust=False
    ).production_trust
    with pytest.raises(SignatureUnverifiable):
        plan.verify_signature(dev_trust_store())
    # Presence control: the phase is part of the signed body, so the two plans differ in digest.
    assert hashlib.sha256(_bytes(final)).digest() != hashlib.sha256(_bytes(dev)).digest()
    assert plan.plan_digest != EvaluationPlan.from_mapping(dev).plan_digest


def test_a_sealed_phase_still_refuses_readable_handles() -> None:
    readable = ["unit-a", "unit-b"]
    development_plan(
        track="coding", handles=readable, competition_id="c", plan_id="p", signed_at=SIGNED_AT
    )  # control: Development keeps readable handles
    with pytest.raises(OrganizerFault, match="SEALED"):
        development_plan(
            track="coding",
            handles=readable,
            competition_id="c",
            plan_id="p",
            signed_at=SIGNED_AT,
            phase="final",
        )


@pytest.mark.parametrize("phase", ["development", "Final", "", "sealed"])
def test_an_unknown_phase_is_refused(phase: str) -> None:
    with pytest.raises(ContractError, match="is not one of"):
        _plan("coding", phase=phase)
