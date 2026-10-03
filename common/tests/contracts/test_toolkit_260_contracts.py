"""Toolkit 2.6.0: the `not_reached` failure code, the Development leakage scan's inputs, and the
participant image that could not be pulled.

* `not_reached` (registry 1.2.0): a unit the run's total wall-clock allowance ended before it was
  started. Scored at `W`, like a missing output, and not described as a container that ran.
* `LeakageScan`: what a Development self-attestation scans each published tree against. It refuses
  an empty or malformed registry and never shows an entry.
* `_unpullable_participant_image`: the one shape in which a missing image digest is the
  participant's -- the daemon refused `docker create` because the submitted image could not be
  pulled. Every other shape files no record, as before.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from qfbench2_common.contracts import LeakageScan, OrganizerFault
from qfbench2_common.contracts.codes import (
    FAILURE_CODE_REGISTRY_VERSION,
    FailureCode,
    failure_code_registry,
)
from qfbench2_common.contracts.devattest import _unpullable_participant_image
from qfbench2_common.taskcard import load_schema

#: Synthetic canaries in the registry's canonical form (lowercase UUIDv4). Not real ones.
CANARIES = ("0b4f6c1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b", "9e8d7c6b-5a49-4382-a716-05f4e3d2c1b0")


def test_not_reached_is_a_thirteenth_scored_ingestion_code():
    registry = failure_code_registry()
    assert FAILURE_CODE_REGISTRY_VERSION == "1.2.0"
    assert set(registry) == set(FailureCode) and len(registry) == 13
    row = registry[FailureCode.NOT_REACHED]
    assert row.scored is True and row.phase_scope == "ingestion"
    gloss = row.one_line_participant_gloss.lower()
    assert "container" not in gloss and "finish" not in gloss
    assert registry[FailureCode.RESOURCE_TIMEOUT].one_line_participant_gloss.lower() != gloss


@pytest.mark.parametrize("schema", ["c1_evaluation_plan.schema.json", "c4_result.schema.json"])
def test_the_schemas_list_not_reached_wherever_they_list_failure_codes(schema):
    text = json.dumps(load_schema(schema))
    assert text.count('"domain_gate_failed"') == text.count('"not_reached"') > 0


def test_a_leakage_scan_takes_a_registry_of_canaries_and_shows_none(tmp_path):
    scan = LeakageScan(tuple(c.upper() for c in reversed(CANARIES)), tmp_path)
    assert scan.registry == tuple(sorted(CANARIES))  # canonical form, sorted
    assert scan.unit_inputs == tmp_path
    assert all(c not in repr(scan) for c in CANARIES)


@pytest.mark.parametrize(
    "registry, inputs, needle",
    [
        ("0b4f6c1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b", None, "not a single string"),
        ((), None, "empty"),
        (("not-a-canary-but-planted-text",), None, "not a canary"),
        (CANARIES, "missing", "not a directory"),
    ],
)
def test_a_leakage_scan_refuses_what_it_cannot_scan_with(tmp_path, registry, inputs, needle):
    root = tmp_path / "absent" if inputs == "missing" else tmp_path
    with pytest.raises(OrganizerFault, match=needle) as refused:
        LeakageScan(registry, root)
    assert "planted-text" not in str(refused.value)  # an entry is never echoed


def _unpullable() -> dict:
    """The observation the Hub files when the daemon refused `docker create` for the image."""
    return {
        "fault": "submission",
        "docker_fault": "submission",
        "docker_error_reason": "image_unavailable",
        "image": {"requested": "ghcr.io/example/agent@sha256:" + "0" * 64, "resolved_digest": None},
        "lifecycle": {
            "phase_reached": "created",
            "daemon_status": "",
            "exit_code": None,
            "timed_out": False,
            "oom_killed": False,
            "cleanup_confirmed": True,
        },
    }


def test_an_image_the_daemon_could_not_pull_is_the_participants():
    assert _unpullable_participant_image(_unpullable()) is True


@pytest.mark.parametrize(
    "path, value",
    [
        (("image", "resolved_digest"), "sha256:" + "1" * 64),
        (("image", "requested"), " "),
        (("fault",), "organizer"),
        (("docker_fault",), "infrastructure"),
        (("docker_error_reason",), "timeout"),
        (("lifecycle", "phase_reached"), "started"),
        (("lifecycle", "daemon_status"), "exited"),
        (("lifecycle", "exit_code"), 0),
        (("lifecycle", "timed_out"), True),
        (("lifecycle", "oom_killed"), True),
        (("lifecycle", "cleanup_confirmed"), False),
    ],
)
def test_any_other_shape_is_not(path, value):
    """Each clause on its own: change one field and the unit is not an unpulled image."""
    observation = _unpullable()
    target = observation
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert _unpullable_participant_image(observation) is False


def test_metadata_difficulty_is_optional_in_the_task_card_schema():
    metadata = load_schema("taskcard.schema.json")["properties"]["metadata"]
    assert "difficulty" not in metadata["required"]
    assert {"author_name", "category", "tags"} <= set(metadata["required"])
    assert "difficulty" in metadata["properties"]  # still described when a card carries it


def test_the_fixture_registry_file_is_the_one_the_code_reads():
    from qfbench2_common.contracts import codes

    raw = json.loads(pathlib.Path(codes._registry_path()).read_text(encoding="utf-8"))
    assert raw["schema_version"] == FAILURE_CODE_REGISTRY_VERSION
