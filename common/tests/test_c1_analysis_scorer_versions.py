"""Track 4's C1 fixtures, one per scorer era, and the C1 1.3.0 `interval_leg` and `labels` keys.

Track 4 scorer 5.1.0 replaced the calibration leg with an
interval-score ratio, so both composite legs lie in [0, 1] and the worst case W moved from -0.27 to
0.0. The frozen fixture `c1/analysis_final.expanded.json` is kept byte-for-byte as the record of the
<= 5.0.0 plan; `c1/analysis_final.scorer-5.1.0.expanded.json` is a TEST FIXTURE (not a signature:
its envelope is the published, forgeable dev key) for 5.1.0, and the Development-phase plan for
the analysis track is derived from it.
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from qfbench2_common.contracts import ContractError, EvaluationPlan, sign_payload
from qfbench2_common.contracts.devattest import development_plan
from qfbench2_common.contracts.fixtures import (
    DEV_KEY_ID,
    DEV_SEED,
    fixture_path,
    load_fixture,
)

OLD = "c1/analysis_final.expanded.json"
NEW = "c1/analysis_final.scorer-5.1.0.expanded.json"
#: sha256 of the frozen <= 5.0.0 fixture's bytes.
OLD_SHA256 = "bd3631ad96edf32ff31cab0638a6d562714ff75bdac6d9b7e8b15e5eb5ea022e"


def _resign(raw: dict) -> dict:
    body = {k: v for k, v in raw.items() if k != "signature"}
    env = sign_payload(
        body, seed=DEV_SEED, key_id=DEV_KEY_ID, signed_at=raw["signature"]["signed_at"]
    )
    raw["signature"] = {
        "alg": env.alg,
        "key_id": env.key_id,
        "payload_digest": env.payload_digest,
        "signed_at": env.signed_at,
        "signature": env.signature,
    }
    return raw


def test_the_frozen_pre_5_1_fixture_is_byte_for_byte_unchanged() -> None:
    """Baseline: the <= 5.0.0 record is not edited in place, ever."""
    assert hashlib.sha256(fixture_path(OLD).read_bytes()).hexdigest() == OLD_SHA256


def test_the_frozen_fixture_still_parses_and_still_says_minus_0_27() -> None:
    plan = EvaluationPlan(load_fixture(OLD))
    assert plan.failure_score_for("schema_invalid") == pytest.approx(-0.27)
    assert plan.clip(-9.0) == pytest.approx(-0.27)


def test_the_5_1_0_fixture_commits_w_zero_on_the_domain_zero_to_one() -> None:
    raw = load_fixture(NEW)
    plan = EvaluationPlan(raw)
    assert raw["schema_version"] == "1.3.0"
    assert "TEST-FIXTURE-not-a-signature" in raw["plan_id"]
    assert raw["metric"]["domain"] == {"min": 0.0, "max": 1.0}
    for code in ("no_output", "schema_invalid", "incomplete_output", "domain_gate_failed"):
        assert plan.failure_score_for(code) == 0.0
    assert plan.clip(-9.0) == 0.0
    assert plan.clip(9.0) == 1.0


def test_the_5_1_0_fixture_differs_from_the_old_one_only_where_intended() -> None:
    old, new = load_fixture(OLD), load_fixture(NEW)
    for doc in (old, new):
        doc.pop("signature")
    assert new["metric"]["domain"]["min"] == 0.0 and old["metric"]["domain"]["min"] == -0.27
    assert new["participant_failure"]["score"] == 0.0
    assert new["roster"]["expected_units"][0]["scoring_params"].pop("interval_leg") is True
    assert new["roster"]["expected_units"][0]["scoring_params"].pop("labels") == ["up", "down"]
    for doc in (old, new):
        doc.pop("schema_version")
        doc.pop("plan_id")
        doc["metric"]["domain"].pop("min")
        doc["participant_failure"].pop("score")
    assert old == new


def _with_leg(value: object, *, unit: int = 0) -> dict:
    raw = copy.deepcopy(load_fixture(NEW))
    raw["roster"]["expected_units"][unit]["scoring_params"]["interval_leg"] = value
    return _resign(raw)


def test_interval_leg_false_is_accepted_on_a_classification_unit() -> None:
    plan = EvaluationPlan(_with_leg(False, unit=0))
    entry = plan.expected_units[0]
    assert entry.scoring_params["interval_leg"] is False


def test_interval_leg_is_optional() -> None:
    raw = copy.deepcopy(load_fixture(NEW))
    raw["roster"]["expected_units"][0]["scoring_params"].pop("interval_leg")
    EvaluationPlan(_resign(raw))


def test_interval_leg_false_is_refused_off_classification() -> None:
    with pytest.raises(ContractError, match="interval_leg"):
        EvaluationPlan(_with_leg(False, unit=1))  # unit 1 is regression


@pytest.mark.parametrize("bad", ["false", 0, None])
def test_a_non_boolean_interval_leg_is_refused(bad: object) -> None:
    with pytest.raises(ContractError, match="interval_leg"):
        EvaluationPlan(_with_leg(bad))


def test_the_analysis_development_plan_derives_from_the_5_1_0_fixture() -> None:
    body = development_plan(
        track="analysis",
        handles=["u-0123456789abcdef"],
        competition_id="dev-test",
        plan_id="plan-dev-test",
        signed_at="2026-09-24T12:00:00Z",
    )
    plan = EvaluationPlan(body)
    assert plan.failure_score_for("schema_invalid") == 0.0
    assert body["roster"]["expected_units"][0]["scoring_params"]["interval_leg"] is True
    assert body["roster"]["expected_units"][0]["scoring_params"]["labels"] == ["up", "down"]


def test_the_schema_file_names_the_flag_and_the_version() -> None:
    from qfbench2_common.contracts import plan as plan_module

    assert plan_module.SCHEMA_VERSION == "1.3.0"
    schema_path = fixture_path(OLD).parents[2].parent / "schemas" / "c1_evaluation_plan.schema.json"
    schema = json.loads(schema_path.read_text())
    assert "1.3.0" in schema["properties"]["schema_version"]["enum"]
    assert "interval_leg" in json.dumps(schema)
