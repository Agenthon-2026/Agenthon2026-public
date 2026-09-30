"""C2 1.3.0 `participant_refusal`: the closed code set, its consistency rules, and the signature.

What this file pins:

* every code in the closed set parses from its shipped fixture, verifies under the published
  development key, and makes the run a `failure`; `null` leaves the daemon facts to decide;
* the table of public failure codes is the Track 3 ruling, restated here rather than read from the
  module (a check that read the table it verifies would pass on a wrong table), and every target
  is an existing, scored code of the shipped registry;
* a value outside the closed set, the member on 1.1.0 or 1.2.0, a 1.3.0 record without it, a
  refusal beside an organizer fault (an infrastructure `execution_fault` or `organizer_failure`),
  a refusal on a lifecycle that already derives a failure, and an outcome that disagrees with the
  refusal are refused, by the parser and by the JSON Schema;
* the member is inside the attestation payload: adding, removing or changing it after signing
  breaks verification;
* 1.1.0 and 1.2.0 records read exactly as before, and `derive_participant_outcome` keeps its
  one-argument form;
* the committed fixtures are exactly what `fixture_documents()` produces. Regenerate them, a
  deliberate act, with `python common/tests/contracts/test_c2_participant_refusal.py
  --write-fixtures`.

The last section plants each defect the checks exist to catch into a copy of `run_record.py`,
loads the copy as a module of this package, and runs the SAME check against it: each must fail
with an AssertionError. Every needle is asserted present exactly once first (an absent needle is a
silent no-op), and every check also passes against an unplanted copy loaded the same way.

Everything is synthetic: the shipped Track 3 plan's opaque handles, synthetic digests, and the
published development key.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import re
import sys
from collections.abc import Callable
from types import ModuleType
from typing import Any

import jsonschema
import pytest

from qfbench2_common.contracts import run_record
from qfbench2_common.contracts.codes import FailureCode, failure_code_registry
from qfbench2_common.contracts.digest import digest_json
from qfbench2_common.contracts.errors import ContractError
from qfbench2_common.contracts.fixtures import (
    DEV_KEY_ID,
    DEV_SEED,
    FIXTURE_DIR,
    dev_trust_store,
    load_fixture,
)
from qfbench2_common.contracts.signing import SignatureUnverifiable, sign_payload

#: The Track 3 ruling of 29 Sep 2026, in its order: refusal code -> public failure code.
RULING = {
    "no_stable_output": "no_output",
    "trace_missing": "malformed_output",
    "sidecar_invalid": "schema_invalid",
    "repeats_differ": "incomplete_output",
    "output_refused": "malformed_output",
}

SUBDIR = "c2_participant_refusal"
SIGNED_AT = "2026-09-30T10:01:00Z"
SCHEMA_PATH = (
    pathlib.Path(run_record.__file__).resolve().parents[1] / "schemas" / "c2_run_record.schema.json"
)
SOURCE_FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "qfbench2_common/contracts/fixtures"

#: Lifecycles a refusal may not accompany: each already derives a failure with its own code. The
#: last two keep exit code 0, so a rule that read the exit code alone would let them through.
FAILED_LIFECYCLES = {
    "timeout": dict(phase_reached="killed", exit_code=137, signal="SIGKILL", timed_out=True),
    "oom": dict(phase_reached="killed", exit_code=137, signal="SIGKILL", oom_killed=True),
    "nonzero_exit": dict(exit_code=1),
    "not_started": dict(phase_reached="created", daemon_status="not_started", exit_code=None),
    "oom_exit_0": dict(oom_killed=True),
    "timeout_exit_0": dict(timed_out=True),
}

#: Values outside the closed set. Case, whitespace and type are not normalized.
UNKNOWN_VALUES = ["", "other", "REPEATS_DIFFER", " repeats_differ", 1, True, {}, ["trace_missing"]]


# --------------------------------------------------------------------------- the fixtures
def _plan() -> dict[str, Any]:
    return load_fixture("c1/simulation_final.expanded.json")


def refusal_document(refusal: str | None) -> dict[str, Any]:
    """A signed Track 3 Final C2 1.3.0 record for the shipped plan's first unit.

    Representation A: the failing run's own record, so no repeats. Bound to the shipped Track 3
    plan and C3 tree; the descriptor, C7 and image digests are synthetic. Every fixture differs
    only in `run_id`, `participant_refusal` and `participant_outcome`.
    """
    plan = _plan()
    handle = plan["roster"]["expected_units"][0]["unit_handle"]
    image = digest_json("synthetic:c2-participant-refusal:image")
    gpu = "GPU-4c1d2e3f-a1b2-c3d4-e5f6-0a1b2c3d4e5f"
    document: dict[str, Any] = {
        "schema_version": "1.3.0",
        "run_id": f"run-t3-final-{handle}-refusal-{refusal or 'null'}",
        "unit_handle": handle,
        "attempt_slot_index": 0,
        "bindings": {
            "plan_digest": digest_json({k: v for k, v in plan.items() if k != "signature"}),
            "descriptor_digest": digest_json("synthetic:c2-participant-refusal:descriptor"),
            "c7_instance_digest": digest_json("synthetic:c2-participant-refusal:c7-instance"),
            "sanitized_tree_digest": load_fixture("c3_artifact_tree.json")["root_digest"],
        },
        "image": {
            "requested": f"docker.io/team-example/qfb2-simulator@{image}",
            "resolved_digest": image,
            "interface_label": "qfbench2.interface=2.0",
        },
        "lifecycle": {
            "phase_reached": "exited",
            "daemon_status": "exited",
            "daemon_error": "",
            "exit_code": 0,
            "signal": None,
            "timed_out": False,
            "oom_killed": False,
            "cleanup_confirmed": True,
        },
        "participant_outcome": "success" if refusal is None else "failure",
        "participant_refusal": refusal,
        "execution_fault": {"attribution": "none", "reason": "none", "evidence": "host_lifecycle"},
        "rankability": {"state": "rankable", "unmet_controls": []},
        "timing": {
            "started_at": "2026-09-30T10:00:00Z",
            "ended_at": "2026-09-30T10:00:42Z",
            "elapsed_sec": 42.0,
            "applied_timeout_sec": 300.0,
        },
        "applied": {
            "runtime": {"requested": "runsc", "applied": "runsc", "source": "pinned"},
            "gpu": {
                "requested": gpu,
                "applied": gpu,
                "source": "pinned",
                "uuid": gpu,
                "selector": "uuid",
            },
            "network": {"requested": "none", "applied": "none", "source": "pinned"},
            "limits": {
                "cpus": {"requested": 4, "applied": 4, "source": "pinned"},
                "memory_bytes": {
                    "requested": 17179869184,
                    "applied": 17179869184,
                    "source": "pinned",
                },
                "pids": {"requested": 512, "applied": 512, "source": "pinned"},
                "storage_bytes": {
                    "requested": 10737418240,
                    "applied": 10737418240,
                    "source": "pinned",
                },
            },
        },
        "telemetry": {
            "sampling_interval_ms": 50,
            "samples_taken": 836,
            "samples_expected": 840,
            "samples_missed": 4,
            "coverage_fraction": 0.9952,
            "gpu_uuid": gpu,
            "participant_cgroup_id": "qfb2-unit-0001",
            "exclusive": True,
            "contender_process_count": 0,
            "throttled": False,
        },
        "output_row_counts": {},
        "repeats": [],
        "leakage": {
            "canary_verdict": "clean",
            "hit_count": 0,
            "scanned_file_count": 3,
            "scanned_bytes": 43520,
        },
        "worker_layer_view": [
            {
                "layer": "worker",
                "runtime": "runc",
                "docker_socket_present": True,
                "mount_roots": ["/var/lib/codabench"],
            },
            {
                "layer": "unit",
                "runtime": "runsc",
                "docker_socket_present": False,
                "mount_roots": ["/input", "/output"],
            },
        ],
        "observation": {"observed_by": "qfbench2-hub", "notes_count": 0},
        "attestation": {"observation_verdict": "confirmed", "reason": "host_facts_match"},
    }
    return sign(document)


def refused_combination_document() -> dict[str, Any]:
    """The combination the parser refuses: a refusal beside an infrastructure execution fault.

    Cleanup was not confirmed, so the host diagnosis is `cleanup_unconfirmed` and the record is an
    `organizer_failure`, while the run itself exited 0. Signed, so the refusal comes from the
    consistency rule and not from the signature.
    """
    document = refusal_document("output_refused")
    document["run_id"] = document["run_id"].replace("-refusal-", "-refused-combination-")
    document["lifecycle"]["cleanup_confirmed"] = False
    document["execution_fault"] = {
        "attribution": "infrastructure",
        "reason": "cleanup_unconfirmed",
        "evidence": "host_lifecycle",
    }
    document["rankability"] = {
        "state": "organizer_failure",
        "unmet_controls": ["cleanup_unconfirmed"],
    }
    return sign(document)


def fixture_documents() -> dict[str, dict[str, Any]]:
    """Every committed fixture under `c2_participant_refusal/`, by its path there."""
    documents = {f"{code}.json": refusal_document(code) for code in RULING}
    documents["null.json"] = refusal_document(None)
    documents["invalid/refusal_with_execution_fault.json"] = refused_combination_document()
    return documents


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def write_fixtures() -> None:
    target = SOURCE_FIXTURES / SUBDIR
    for name, document in fixture_documents().items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(document), encoding="utf-8")


# --------------------------------------------------------------------------- helpers
def sign(document: dict[str, Any], rr: ModuleType = run_record) -> dict[str, Any]:
    """Sign the frozen attestation payload of `document` in place, with `rr`'s payload."""
    document["attestation"]["signature"] = sign_payload(
        rr.attestation_payload(document), seed=DEV_SEED, key_id=DEV_KEY_ID, signed_at=SIGNED_AT
    ).to_mapping()
    return document


def shipped(name: str) -> dict[str, Any]:
    return load_fixture(f"{SUBDIR}/{name}")


def parses(rr: ModuleType, document: dict[str, Any]) -> Any:
    """Parse a record that must be valid. A refusal is the check failing, not a crash."""
    try:
        return rr.RunRecord.from_mapping(document)
    except ContractError as exc:
        raise AssertionError(f"a valid record was refused: {exc}") from exc


def refused(fn: Callable[[], object], *, match: str) -> ContractError:
    """`fn` must raise a ContractError whose message matches `match`."""
    try:
        fn()
    except ContractError as exc:
        assert re.search(match, str(exc)), f"refused, but not for {match!r}: {exc}"
        return exc
    raise AssertionError(f"expected a refusal matching {match!r}; the record was accepted")


def at_version(document: dict[str, Any], version: str) -> dict[str, Any]:
    """`document` relabelled to an older version, with the member that version carries."""
    document["schema_version"] = version
    if version == "1.1.0":
        del document["execution_fault"]
    return document


def schema_errors(document: dict[str, Any]) -> list[str]:
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text("utf-8")))
    return [error.message for error in validator.iter_errors(document)]


# --------------------------------------------------------------------------- the checks
def check_every_code_parses_verifies_and_fails_the_run(rr: ModuleType) -> None:
    for code in RULING:
        document = shipped(f"{code}.json")
        record = parses(rr, document)
        assert record.participant_refusal == code, (code, record.participant_refusal)
        assert record.participant_outcome == "failure", code
        assert record.is_rankable and record.execution_fault.reason == "none", code
        try:
            record.verify_attestation(dev_trust_store(), require_production_trust=False)
        except SignatureUnverifiable as exc:
            raise AssertionError(f"{code}: the shipped fixture does not verify: {exc}") from exc
        assert rr.attestation_payload(document)["participant_refusal"] == code
    record = parses(rr, shipped("null.json"))
    assert record.participant_refusal is None
    assert record.participant_outcome == "success"


def check_the_table_is_the_ruling(rr: ModuleType) -> None:
    assert tuple(rr.PARTICIPANT_REFUSAL_CODES) == tuple(RULING)
    table = {code: public.value for code, public in rr.PARTICIPANT_REFUSAL_FAILURE_CODES.items()}
    assert table == RULING, table
    registry = failure_code_registry()
    for public in RULING.values():
        row = registry[FailureCode(public)]
        assert row.scored, f"{public} is not a scored code"


def check_unknown_codes_are_refused(rr: ModuleType) -> None:
    lifecycle = rr.Lifecycle.from_mapping(shipped("null.json")["lifecycle"])
    for value in UNKNOWN_VALUES:
        document = shipped("repeats_differ.json")
        document["participant_refusal"] = value
        refused(lambda: rr.RunRecord.from_mapping(document), match="the set is closed")
        refused(
            lambda: rr.derive_participant_outcome(lifecycle, participant_refusal=value),
            match="the set is closed",
        )


def check_a_refusal_beside_an_infrastructure_fault_is_refused(rr: ModuleType) -> None:
    match = "execution_fault attributes the run to infrastructure"
    refused(
        lambda: rr.RunRecord.from_mapping(shipped("invalid/refusal_with_execution_fault.json")),
        match=match,
    )
    # The other infrastructure diagnosis: a container that timed out before it started.
    document = shipped("sidecar_invalid.json")
    document["lifecycle"].update(
        phase_reached="created", daemon_status="created", exit_code=None, timed_out=True
    )
    document["execution_fault"].update(attribution="infrastructure", reason="create_timeout")
    document["rankability"] = {"state": "organizer_failure", "unmet_controls": []}
    refused(lambda: rr.RunRecord.from_mapping(document), match=match)


def check_a_refusal_beside_organizer_failure_is_refused(rr: ModuleType) -> None:
    for code in RULING:
        document = shipped(f"{code}.json")
        document["rankability"] = {
            "state": "organizer_failure",
            "unmet_controls": ["tier_unenforced"],
        }
        refused(lambda: rr.RunRecord.from_mapping(document), match="declares organizer_failure")
    # Presence control: the same record without the refusal is a valid organizer failure.
    document = shipped("null.json")
    document["rankability"] = {"state": "organizer_failure", "unmet_controls": ["tier_unenforced"]}
    assert parses(rr, document).rankability.state == "organizer_failure"


def check_a_refusal_on_a_failed_lifecycle_is_refused(rr: ModuleType) -> None:
    for name, facts in FAILED_LIFECYCLES.items():
        document = shipped("trace_missing.json")
        document["lifecycle"].update(facts)
        refused(lambda: rr.RunRecord.from_mapping(document), match="already derive as a failure")
        # Presence control: without the refusal the same lifecycle is an ordinary failed run.
        document["participant_refusal"] = None
        assert parses(rr, document).participant_outcome == "failure", name


def check_the_member_belongs_to_1_3_0(rr: ModuleType) -> None:
    for version in ("1.1.0", "1.2.0"):
        refused(
            lambda: rr.RunRecord.from_mapping(at_version(shipped("repeats_differ.json"), version)),
            match="participant_refusal requires C2 schema_version 1.3.0",
        )
        # Even a null member is a 1.3.0 member.
        refused(
            lambda: rr.RunRecord.from_mapping(at_version(shipped("null.json"), version)),
            match="participant_refusal requires C2 schema_version 1.3.0",
        )
    for name in ("null.json", "repeats_differ.json"):
        document = shipped(name)
        del document["participant_refusal"]
        refused(
            lambda: rr.RunRecord.from_mapping(document),
            match="required field 'participant_refusal' is absent",
        )


def check_the_outcome_follows_the_refusal(rr: ModuleType) -> None:
    document = shipped("output_refused.json")
    document["participant_outcome"] = "success"
    refused(lambda: rr.RunRecord.from_mapping(document), match="participant_refusal=output_refused")
    document = shipped("null.json")
    document["participant_outcome"] = "failure"
    refused(lambda: rr.RunRecord.from_mapping(document), match="the daemon facts derive 'success'")
    lifecycle = rr.Lifecycle.from_mapping(shipped("null.json")["lifecycle"])
    assert rr.derive_participant_outcome(lifecycle) == "success"
    assert rr.derive_participant_outcome(lifecycle, participant_refusal=None) == "success"
    for code in RULING:
        assert rr.derive_participant_outcome(lifecycle, participant_refusal=code) == "failure"


def check_a_tampered_refusal_breaks_the_signature(rr: ModuleType) -> None:
    trust = dev_trust_store()
    edits = {
        "added": ("null.json", "repeats_differ", "failure"),
        "removed": ("repeats_differ.json", None, "success"),
        "changed": ("trace_missing.json", "output_refused", "failure"),
    }
    for name, (source, refusal, outcome) in edits.items():
        document = sign(shipped(source), rr)
        parses(rr, document).verify_attestation(trust, require_production_trust=False)
        document["participant_refusal"] = refusal
        document["participant_outcome"] = outcome
        record = parses(rr, document)  # structurally valid: the signature is the only defence
        refused(
            lambda: record.verify_attestation(trust, require_production_trust=False),
            match="payload",
        )


def check_legacy_records_read_as_before(rr: ModuleType) -> None:
    legacy = load_fixture("c2_run_record.json")
    original = copy.deepcopy(legacy)
    record = parses(rr, legacy)
    assert (record.schema_version, record.participant_refusal) == ("1.1.0", None)
    assert record.execution_fault is None
    record.verify_attestation(dev_trust_store(), require_production_trust=False)
    assert legacy == original and dict(record.raw) == original, "a legacy record was rewritten"
    document = load_fixture("c2_run_record.json")
    document["schema_version"] = "1.2.0"
    document["execution_fault"] = {
        "attribution": "none",
        "reason": "none",
        "evidence": "host_lifecycle",
    }
    record = parses(rr, sign(document, rr))
    assert (record.schema_version, record.participant_refusal) == ("1.2.0", None)
    assert "participant_refusal" not in record.raw
    record.verify_attestation(dev_trust_store(), require_production_trust=False)


CHECKS = [
    check_every_code_parses_verifies_and_fails_the_run,
    check_the_table_is_the_ruling,
    check_unknown_codes_are_refused,
    check_a_refusal_beside_an_infrastructure_fault_is_refused,
    check_a_refusal_beside_organizer_failure_is_refused,
    check_a_refusal_on_a_failed_lifecycle_is_refused,
    check_the_member_belongs_to_1_3_0,
    check_the_outcome_follows_the_refusal,
    check_a_tampered_refusal_breaks_the_signature,
    check_legacy_records_read_as_before,
]


# --------------------------------------------------------------------------- the tests
@pytest.mark.parametrize("check", CHECKS, ids=[check.__name__ for check in CHECKS])
def test_the_contract(check: Callable[[ModuleType], None]) -> None:
    check(run_record)


def test_the_committed_fixtures_are_what_the_recipe_produces() -> None:
    directory = FIXTURE_DIR / SUBDIR
    expected = fixture_documents()
    committed = sorted(p.relative_to(directory).as_posix() for p in directory.rglob("*.json"))
    # Presence control: nothing missing and nothing extra, so a deleted fixture cannot pass.
    assert committed == sorted(expected)
    for name, document in expected.items():
        assert (directory / name).read_text(encoding="utf-8") == render(document), (
            f"{SUBDIR}/{name} is not what the recipe produces; regenerate with --write-fixtures"
        )


def test_the_fixtures_are_bound_to_the_shipped_track3_plan_and_tree() -> None:
    plan = _plan()
    handles = [entry["unit_handle"] for entry in plan["roster"]["expected_units"]]
    for name in fixture_documents():
        document = shipped(name)
        assert document["unit_handle"] == handles[0]
        assert document["bindings"]["plan_digest"] == digest_json(
            {k: v for k, v in plan.items() if k != "signature"}
        )
        assert (
            document["bindings"]["sanitized_tree_digest"]
            == (load_fixture("c3_artifact_tree.json")["root_digest"])
        )


def test_the_json_schema_agrees_with_the_parser() -> None:
    for code in [*RULING, "null"]:
        assert schema_errors(shipped(f"{code}.json")) == [], code
    assert schema_errors(shipped("invalid/refusal_with_execution_fault.json"))
    refusals: dict[str, dict[str, Any]] = {}
    for version in ("1.1.0", "1.2.0"):
        refusals[f"member_on_{version}"] = at_version(shipped("repeats_differ.json"), version)
        refusals[f"null_member_on_{version}"] = at_version(shipped("null.json"), version)
    document = shipped("null.json")
    del document["participant_refusal"]
    refusals["member_absent_on_1_3_0"] = document
    for index, value in enumerate(UNKNOWN_VALUES):
        document = shipped("repeats_differ.json")
        document["participant_refusal"] = value
        refusals[f"unknown_value_{index}"] = document
    document = shipped("repeats_differ.json")
    document["rankability"] = {"state": "organizer_failure", "unmet_controls": ["tier_unenforced"]}
    refusals["organizer_failure"] = document
    for name, facts in FAILED_LIFECYCLES.items():
        document = shipped("repeats_differ.json")
        document["lifecycle"].update(facts)
        refusals[f"failed_lifecycle_{name}"] = document
    document = shipped("repeats_differ.json")
    document["participant_outcome"] = "success"
    refusals["declared_success"] = document
    for name, document in refusals.items():
        assert schema_errors(document), f"the JSON Schema accepted {name}"
        with pytest.raises(ContractError):
            run_record.RunRecord.from_mapping(document)


def test_the_member_is_signed_like_every_other_field() -> None:
    document = shipped("sidecar_invalid.json")
    payload = run_record.attestation_payload(document)
    assert payload["participant_refusal"] == "sidecar_invalid"
    assert set(payload) == set(document)


def test_the_new_writer_version_is_1_3_0_and_the_development_attester_stays_on_1_1_0() -> None:
    from qfbench2_common.contracts import devattest

    assert run_record.SCHEMA_VERSION == "1.3.0"
    assert run_record.SUPPORTED_SCHEMA_VERSIONS == ("1.1.0", "1.2.0", "1.3.0")
    assert devattest.SCHEMA_VERSION == run_record.LEGACY_SCHEMA_VERSION == "1.1.0"


# --------------------------------------------------------------------------- planted defects
#: (name, [(needle, replacement), ...], the check that must catch it). Each needle must occur in
#: `run_record.py` exactly once; the planted copy is loaded as a module of this package.
PLANTS = [
    (
        "a_refusal_does_not_fail_the_run",
        [
            (
                '        _require_refusal_code(participant_refusal)\n        return "failure"\n',
                "        _require_refusal_code(participant_refusal)\n",
            )
        ],
        check_every_code_parses_verifies_and_fails_the_run,
    ),
    (
        "any_string_is_a_code",
        [
            (
                "    if not isinstance(value, str) or value not in PARTICIPANT_REFUSAL_CODES:\n",
                "    if not isinstance(value, str):\n",
            )
        ],
        check_unknown_codes_are_refused,
    ),
    (
        "a_refusal_beside_an_infrastructure_fault",
        [
            (
                "    if execution_fault is not None and execution_fault.infrastructure:\n"
                "        raise ContractError(\n"
                '            f"participant_refusal=',
                '    if False:\n        raise ContractError(\n            f"participant_refusal=',
            )
        ],
        check_a_refusal_beside_an_infrastructure_fault_is_refused,
    ),
    (
        "a_refusal_beside_organizer_failure",
        [
            (
                '        if participant_refusal is not None and rankability.state == "organizer_failure":\n',
                "        if False:\n",
            )
        ],
        check_a_refusal_beside_organizer_failure_is_refused,
    ),
    (
        "a_refusal_on_a_failed_lifecycle",
        [('    if derive_participant_outcome(lifecycle) != "success":\n', "    if False:\n")],
        check_a_refusal_on_a_failed_lifecycle_is_refused,
    ),
    (
        "a_failed_lifecycle_read_from_the_exit_code_alone",
        [
            (
                '    if derive_participant_outcome(lifecycle) != "success":\n',
                "    if lifecycle.exit_code != 0:\n",
            )
        ],
        check_a_refusal_on_a_failed_lifecycle_is_refused,
    ),
    (
        "the_member_on_an_older_version",
        [('        elif "participant_refusal" in raw:\n', "        elif False:\n")],
        check_the_member_belongs_to_1_3_0,
    ),
    (
        "the_member_optional_on_1_3_0",
        [
            (
                'req(raw, "participant_refusal", path="run_record", allow_null=True)',
                'raw.get("participant_refusal")',
            )
        ],
        check_the_member_belongs_to_1_3_0,
    ),
    (
        "the_outcome_ignores_the_refusal",
        [
            (
                "        derived = derive_participant_outcome(lifecycle, participant_refusal=participant_refusal)\n",
                "        derived = outcome\n",
            )
        ],
        check_the_outcome_follows_the_refusal,
    ),
    (
        "the_member_outside_the_signature",
        [
            (
                "    payload = dict(record)\n",
                '    payload = {k: v for k, v in record.items() if k != "participant_refusal"}\n',
            )
        ],
        check_a_tampered_refusal_breaks_the_signature,
    ),
    (
        "a_code_mapped_to_another_public_code",
        [
            (
                '    "trace_missing": FailureCode.MALFORMED_OUTPUT,\n',
                '    "trace_missing": FailureCode.NO_OUTPUT,\n',
            )
        ],
        check_the_table_is_the_ruling,
    ),
    (
        "a_code_added_to_the_closed_set",
        [('    "output_refused",\n)\n', '    "output_refused",\n    "other",\n)\n')],
        check_the_table_is_the_ruling,
    ),
    (
        "a_legacy_record_read_as_1_3_0",
        [("    return order.index(schema_version) >= order.index(since)\n", "    return True\n")],
        check_legacy_records_read_as_before,
    ),
]


def load_as_module(path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load `path` as a module of `qfbench2_common.contracts`, so its relative imports resolve."""
    name = "qfbench2_common.contracts._planted_run_record"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def plant(tmp_path: pathlib.Path, replacements: list[tuple[str, str]]) -> pathlib.Path:
    source = pathlib.Path(run_record.__file__).read_text(encoding="utf-8")
    planted = source
    for needle, replacement in replacements:
        # Presence control: an absent needle makes `replace` a silent no-op.
        assert planted.count(needle) == 1, f"needle not found exactly once: {needle!r}"
        planted = planted.replace(needle, replacement)
    assert planted != source
    path = tmp_path / "planted_run_record.py"
    path.write_text(planted, encoding="utf-8")
    return path


@pytest.mark.parametrize("name, replacements, check", PLANTS, ids=[p[0] for p in PLANTS])
def test_each_check_catches_its_planted_defect(
    name: str,
    replacements: list[tuple[str, str]],
    check: Callable[[ModuleType], None],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    module = load_as_module(plant(tmp_path, replacements), monkeypatch)
    with pytest.raises(AssertionError):
        check(module)


@pytest.mark.parametrize("check", CHECKS, ids=[check.__name__ for check in CHECKS])
def test_positive_control_each_check_passes_on_an_unplanted_copy(
    check: Callable[[ModuleType], None],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """The same loader, a byte copy of the real module: the planted runs fail for the plant."""
    copied = tmp_path / "copied_run_record.py"
    copied.write_bytes(pathlib.Path(run_record.__file__).read_bytes())
    module = load_as_module(copied, monkeypatch)
    assert module is not run_record and module.RunRecord is not run_record.RunRecord
    check(module)


def test_every_check_has_a_plant() -> None:
    """A check no plant exercises is a check nobody has shown can fail."""
    planted = {plant_check.__name__ for _, _, plant_check in PLANTS}
    assert planted == {check.__name__ for check in CHECKS}


if __name__ == "__main__":
    if sys.argv[1:] != ["--write-fixtures"]:
        sys.exit(f"usage: {sys.argv[0]} --write-fixtures")
    write_fixtures()
    print(f"fixtures written to {SOURCE_FIXTURES / SUBDIR}")
