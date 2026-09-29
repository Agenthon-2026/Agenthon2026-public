"""`analysis.schema.json` bounds `submitted_reasons` at one to three reasons.

The field is optional. When present it must hold 1, 2 or 3 reasons, each with `reason_id`,
`premise`, `mechanism` and `answer_implication`; anything else makes the answer schema-invalid.
"""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest

from qfbench2_common.taskcard import load_schema


def _reason(i: int) -> dict[str, Any]:
    return {
        "reason_id": f"r{i}",
        "premise": f"premise {i}",
        "mechanism": f"mechanism {i}",
        "answer_implication": f"implication {i}",
    }


def _answer(reasons: object = None) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "task_id": "example-task",
        "entity_predictions": [
            {
                "entity_id": "ENTITY-A",
                "point_forecast": 1.0,
                "interval": {"level": 0.90, "lo": 0.5, "hi": 1.5},
                "claims": [
                    {"doc_id": "doc-1", "span_start": 0, "span_end": 10, "claim": "An example."}
                ],
            }
        ],
    }
    if reasons is not None:
        doc["submitted_reasons"] = reasons
    return doc


def _errors(doc: dict[str, Any]) -> list[str]:
    validator = jsonschema.Draft202012Validator(load_schema("analysis.schema.json"))
    return [e.message for e in validator.iter_errors(doc)]


def test_an_answer_without_submitted_reasons_is_valid() -> None:
    assert _errors(_answer()) == []


@pytest.mark.parametrize("count", [1, 2, 3])
def test_one_to_three_reasons_are_accepted(count: int) -> None:
    assert _errors(_answer([_reason(i) for i in range(count)])) == []


@pytest.mark.parametrize("count", [4, 5])
def test_more_than_three_reasons_are_refused(count: int) -> None:
    errors = _errors(_answer([_reason(i) for i in range(count)]))
    assert errors, f"{count} reasons were accepted"
    assert any("too long" in e for e in errors), errors


def test_an_empty_reason_list_is_refused() -> None:
    assert _errors(_answer([]))


@pytest.mark.parametrize("field", ["reason_id", "premise", "mechanism", "answer_implication"])
def test_a_reason_missing_a_required_field_is_refused(field: str) -> None:
    reason = _reason(0)
    del reason[field]
    assert _errors(_answer([reason]))


def test_the_schema_states_the_cap() -> None:
    field = load_schema("analysis.schema.json")["properties"]["submitted_reasons"]
    assert (field["minItems"], field["maxItems"]) == (1, 3)
