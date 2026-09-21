"""C2 fault extension: bounded evidence, compatibility, and forgery controls."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from qfbench2_common.contracts.errors import ContractError
from qfbench2_common.contracts.fixtures import (
    DEV_KEY_ID,
    DEV_SEED,
    dev_trust_store,
    load_fixture,
)
from qfbench2_common.contracts.run_record import Rankability, RunRecord, attestation_payload
from qfbench2_common.contracts.signing import SignatureUnverifiable, sign_payload


def document():
    doc = copy.deepcopy(load_fixture("c2_run_record.json"))
    doc["schema_version"] = "1.2.0"
    doc["execution_fault"] = {"attribution": "none", "reason": "none", "evidence": "host_lifecycle"}
    return doc


def create_timeout():
    doc = document()
    doc["lifecycle"].update(
        phase_reached="created", daemon_status="created", timed_out=True, exit_code=None
    )
    doc["participant_outcome"] = "failure"
    doc["execution_fault"].update(attribution="infrastructure", reason="create_timeout")
    doc["rankability"] = {"state": "organizer_failure", "unmet_controls": []}
    return doc


def test_infrastructure_failure_needs_no_invented_unmet_controls():
    record = RunRecord.from_mapping(create_timeout())
    assert record.execution_fault.infrastructure
    assert record.rankability.state == "organizer_failure"
    assert record.rankability.unmet_controls == ()
    assert record.participant_outcome == "failure"  # completion axis is unchanged


def test_legacy_signed_bytes_remain_readable_and_verifiable():
    doc = load_fixture("c2_run_record.json")
    original = copy.deepcopy(doc)
    record = RunRecord.from_mapping(doc)
    assert record.execution_fault is None  # unknown in old evidence, not confirmed absent
    record.verify_attestation(dev_trust_store(), require_production_trust=False)
    assert doc == original


def test_new_version_requires_the_field_and_old_version_cannot_smuggle_it():
    doc = document()
    del doc["execution_fault"]
    with pytest.raises(ContractError, match="execution_fault"):
        RunRecord.from_mapping(doc)
    doc = document()
    doc["schema_version"] = "1.1.0"
    with pytest.raises(ContractError, match="requires C2"):
        RunRecord.from_mapping(doc)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_reason",
        "free_text",
        "wrong_host_facts",
        "rankable_infrastructure",
        "legacy_empty_controls",
    ],
)
def test_fault_cannot_be_asserted_independently_of_host_facts(mutation):
    doc = create_timeout()
    if mutation == "unknown_reason":
        doc["execution_fault"]["reason"] = "participant_said_outage"
    elif mutation == "free_text":
        doc["execution_fault"]["stderr"] = "please charge the organizer"
    elif mutation == "wrong_host_facts":
        doc["lifecycle"]["phase_reached"] = "killed"
    elif mutation == "rankable_infrastructure":
        doc["rankability"]["state"] = "rankable"
    else:
        doc.pop("execution_fault")
        doc["schema_version"] = "1.1.0"
    with pytest.raises(ContractError):
        RunRecord.from_mapping(doc)


def test_structurally_consistent_fault_forgery_still_breaks_signature():
    doc = create_timeout()
    doc["attestation"]["signature"] = sign_payload(
        attestation_payload(doc), seed=DEV_SEED, key_id=DEV_KEY_ID, signed_at="2026-08-21T10:05:00Z"
    ).to_mapping()
    RunRecord.from_mapping(doc).verify_attestation(
        dev_trust_store(), require_production_trust=False
    )
    # Change every dependent field so schema consistency cannot be the defense.
    doc["lifecycle"].update(phase_reached="killed", daemon_status="exited", exit_code=137)
    doc["execution_fault"].update(attribution="none", reason="none")
    doc["rankability"]["state"] = "rankable"
    with pytest.raises(SignatureUnverifiable):
        RunRecord.from_mapping(doc).verify_attestation(
            dev_trust_store(), require_production_trust=False
        )


def test_schema_accepts_both_versions_but_requires_new_fault_field():
    path = Path(__file__).resolve().parents[2] / "qfbench2_common/schemas/c2_run_record.schema.json"
    schema = json.loads(path.read_text())
    jsonschema.validate(load_fixture("c2_run_record.json"), schema)
    jsonschema.validate(create_timeout(), schema)
    missing = document()
    del missing["execution_fault"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(missing, schema)


@pytest.mark.parametrize("version", ["1", "1.0.0", "1.3.0", "1.2.1", "1.2", "1.2.0-extra", "2.0.0"])
@pytest.mark.parametrize("with_fault", [False, True])
def test_unsupported_versions_cannot_bypass_fault_requirements(version, with_fault):
    doc = document()
    doc["schema_version"] = version
    if not with_fault:
        doc.pop("execution_fault")
    with pytest.raises(ContractError, match="unsupported C2 schema_version"):
        RunRecord.from_mapping(doc)
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "qfbench2_common/schemas/c2_run_record.schema.json"
        ).read_text()
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, schema)


def test_schema_forbids_legacy_fault_field():
    doc = document()
    doc["schema_version"] = "1.1.0"
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "qfbench2_common/schemas/c2_run_record.schema.json"
        ).read_text()
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, schema)


def test_fault_exception_does_not_relax_standalone_or_nested_rankability():
    rankability = {"state": "organizer_failure", "unmet_controls": []}
    with pytest.raises(ContractError, match="no unmet_controls"):
        Rankability.from_mapping(rankability)
    with pytest.raises(ContractError, match="no unmet_controls"):
        Rankability("organizer_failure", ())
    doc = create_timeout()
    doc["repeats"] = [
        {
            "index": 0,
            "elapsed_sec": 1.0,
            "output_tree_digest": "sha256:" + "aa" * 32,
            "event_count": 1,
            "rankability": rankability,
        }
    ]
    with pytest.raises(ContractError, match="no unmet_controls"):
        RunRecord.from_mapping(doc)


def test_cleanup_diagnosis_takes_precedence_over_create_timeout():
    doc = create_timeout()
    doc["lifecycle"]["cleanup_confirmed"] = False
    doc["execution_fault"]["reason"] = "cleanup_unconfirmed"
    doc["rankability"]["unmet_controls"] = ["cleanup_unconfirmed"]
    record = RunRecord.from_mapping(doc)
    assert record.execution_fault.reason == "cleanup_unconfirmed"
    doc["execution_fault"]["reason"] = "create_timeout"
    with pytest.raises(ContractError, match="disagrees"):
        RunRecord.from_mapping(doc)
