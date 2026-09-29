"""C1 1.3.0 accepts both Track 4 roster keys: `labels` and `interval_leg`.

`scoring_params.labels` is a classification unit's own label vocabulary. It is required on a
classification unit from C1 1.3.0, tolerated absent below 1.3.0, validated whenever present, and
refused on regression and ranking units at every version. `scoring_params.interval_leg` is an
optional boolean; `false` is allowed only on a classification unit. A plan may carry either key or
both. The bundled JSON Schema agrees with the parser on each key's shape and type.
"""

from __future__ import annotations

import copy
from typing import Any

import jsonschema
import pytest

from qfbench2_common.contracts import (
    LABELLED_TARGET_TYPES,
    LABELS_REQUIRED_FROM,
    ContractError,
    EvaluationPlan,
    sign_payload,
)
from qfbench2_common.contracts.fixtures import DEV_KEY_ID, DEV_SEED, load_fixture
from qfbench2_common.taskcard import load_schema

FIXTURE = "c1/analysis_final.scorer-5.1.0.expanded.json"
CLASSIFICATION, REGRESSION = 0, 1


def _resign(raw: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in raw.items() if k != "signature"}
    env = sign_payload(
        body, seed=DEV_SEED, key_id=DEV_KEY_ID, signed_at=raw["signature"]["signed_at"]
    )
    raw["signature"] = env.to_mapping()
    return raw


def _plan(*, version: str = "1.3.0", unit: int = CLASSIFICATION, **params: Any) -> dict[str, Any]:
    """The 1.3.0 fixture with `params` applied to one unit's scoring_params.

    A value of `...` removes the key.
    """
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["schema_version"] = version
    sp = raw["roster"]["expected_units"][unit]["scoring_params"]
    for key, value in params.items():
        if value is ...:
            sp.pop(key, None)
        else:
            sp[key] = value
    return _resign(raw)


def _sp(plan: EvaluationPlan, unit: int) -> Any:
    return plan.expected_units[unit].scoring_params


def test_the_fixture_is_classification_then_regression() -> None:
    """Baseline for every index used below."""
    units = load_fixture(FIXTURE)["roster"]["expected_units"]
    assert units[CLASSIFICATION]["scoring_params"]["target_type"] == "classification"
    assert units[REGRESSION]["scoring_params"]["target_type"] == "regression"


def test_the_public_names() -> None:
    assert LABELS_REQUIRED_FROM == (1, 3)
    assert LABELLED_TARGET_TYPES == ("classification",)


# ------------------------------------------------------------------ accepted


def test_a_plan_with_labels_and_no_interval_leg_is_accepted() -> None:
    plan = EvaluationPlan(_plan(interval_leg=..., labels=["beat", "miss", "inline"]))
    assert _sp(plan, CLASSIFICATION)["labels"] == ["beat", "miss", "inline"]
    assert "interval_leg" not in _sp(plan, CLASSIFICATION)


def test_a_plan_with_interval_leg_and_labels_is_accepted() -> None:
    plan = EvaluationPlan(_plan(interval_leg=False, labels=["up", "down"]))
    assert _sp(plan, CLASSIFICATION)["interval_leg"] is False
    assert _sp(plan, CLASSIFICATION)["labels"] == ["up", "down"]


def test_a_1_2_0_plan_with_interval_leg_and_no_labels_is_accepted() -> None:
    plan = EvaluationPlan(_plan(version="1.2.0", interval_leg=True, labels=...))
    assert _sp(plan, CLASSIFICATION)["interval_leg"] is True


def test_a_classification_unit_without_labels_is_tolerated_below_1_3_0() -> None:
    EvaluationPlan(_plan(version="1.2.0", labels=...))


@pytest.mark.parametrize(
    "labels",
    [
        ["credit_event", "no_event"],
        ["beat", "miss", "inline"],
        ["raised", "maintained", "lowered", "withdrawn"],
    ],
)
def test_real_shaped_vocabularies_parse(labels: list[str]) -> None:
    EvaluationPlan(_plan(labels=labels))


# ------------------------------------------------------------------ refused


def test_a_classification_unit_without_labels_is_refused_from_1_3_0() -> None:
    with pytest.raises(ContractError, match=r"labels is required"):
        EvaluationPlan(_plan(labels=...))


@pytest.mark.parametrize("version", ["1.1.0", "1.2.0", "1.3.0"])
def test_labels_on_a_regression_unit_are_refused_at_every_version(version: str) -> None:
    with pytest.raises(ContractError, match=r"labels is not allowed"):
        EvaluationPlan(_plan(version=version, unit=REGRESSION, labels=["up", "down"]))


@pytest.mark.parametrize(
    "bad",
    [
        "up",  # not a list
        [],  # empty
        ["up"],  # fewer than two
        ["up", "up"],  # repeated
        ["up", ""],  # empty string
        ["up", " down"],  # surrounding whitespace
        ["up", "down "],
        ["up", 1],  # not a string
        ["up", None],
    ],
)
@pytest.mark.parametrize("version", ["1.2.0", "1.3.0"])
def test_malformed_labels_are_refused_at_any_version(bad: object, version: str) -> None:
    with pytest.raises(ContractError, match=r"labels"):
        EvaluationPlan(_plan(version=version, labels=bad))


@pytest.mark.parametrize("bad", ["false", "true", 0, 1, None, [False]])
def test_a_non_boolean_interval_leg_is_refused(bad: object) -> None:
    with pytest.raises(ContractError, match=r"interval_leg"):
        EvaluationPlan(_plan(interval_leg=bad))


def test_interval_leg_false_on_a_regression_unit_is_refused() -> None:
    with pytest.raises(ContractError, match=r"interval_leg"):
        EvaluationPlan(_plan(unit=REGRESSION, interval_leg=False))


def test_an_unknown_scoring_params_key_is_still_refused() -> None:
    with pytest.raises(ContractError, match=r"label_set"):
        EvaluationPlan(_plan(label_set=["up", "down"]))


# ------------------------------------------------------------------ JSON Schema


def _schema_errors(doc: dict[str, Any]) -> list[str]:
    validator = jsonschema.Draft202012Validator(load_schema("c1_evaluation_plan.schema.json"))
    return [e.message for e in validator.iter_errors(doc)]


def test_the_schema_accepts_the_fixture_and_both_keys() -> None:
    assert _schema_errors(load_fixture(FIXTURE)) == []
    assert _schema_errors(_plan(interval_leg=False, labels=["beat", "miss", "inline"])) == []


@pytest.mark.parametrize("bad", ["false", 0, 1, None, [True]])
def test_the_schema_types_interval_leg_as_a_boolean(bad: object) -> None:
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["roster"]["expected_units"][CLASSIFICATION]["scoring_params"]["interval_leg"] = bad
    assert _schema_errors(raw), f"the schema accepted interval_leg={bad!r}"


@pytest.mark.parametrize(
    "bad", ["up", [], ["up"], ["up", "up"], ["up", ""], ["up", " down"], ["up", 1]]
)
def test_the_schema_refuses_malformed_labels(bad: object) -> None:
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["roster"]["expected_units"][CLASSIFICATION]["scoring_params"]["labels"] = bad
    assert _schema_errors(raw), f"the schema accepted labels={bad!r}"
