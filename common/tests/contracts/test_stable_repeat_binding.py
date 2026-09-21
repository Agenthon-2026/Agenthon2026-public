"""Stable repeat evidence preserves C3 binding and refuses omitted required outputs."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from qfbench2_common.contracts import ContractError, RunRecord, stable_output_binding
from qfbench2_common.contracts.digest import digest_member_set
from qfbench2_common.contracts.fixtures import (
    DEV_KEY_ID,
    DEV_SEED,
    dev_trust_store,
    load_fixture,
)
from qfbench2_common.contracts.run_record import attestation_payload
from qfbench2_common.contracts.signing import SignatureUnverifiable, sign_payload

MEMBERS = ("trace.parquet", "message_trace.parquet")


def tree(root, clock=1.0):
    root.mkdir()
    (root / "trace.parquet").write_bytes(b"stable trace")
    (root / "message_trace.parquet").write_bytes(b"stable ledger")
    (root / "events.json").write_text(json.dumps({"wall_clock_sec": clock}))
    return root


def binding(root, members=MEMBERS, required=MEMBERS, policy="t3-stable-output-v1"):
    return stable_output_binding(root, members, required_members=required, policy_id=policy)


def doc(evidence=None):
    d = copy.deepcopy(load_fixture("c2_run_record.json"))
    d["repeats"] = [
        {
            "index": 0,
            "elapsed_sec": 1.0,
            "output_tree_digest": "sha256:" + "a" * 64,
            "event_count": 2,
            "rankability": {"state": "rankable", "unmet_controls": []},
        }
    ]
    if evidence is not None:
        d["repeats"][0]["stable_output_binding"] = evidence
    return d


def test_wall_clock_variation_changes_neither_stable_digest_nor_policy(tmp_path):
    a, b = tree(tmp_path / "a"), tree(tmp_path / "b", 9.0)
    assert binding(a) == binding(b)
    assert binding(a)["content_digest"] == digest_member_set(a, MEMBERS)


@pytest.mark.parametrize("filename", MEMBERS)
def test_changed_semantic_bytes_change_only_content_binding(tmp_path, filename):
    root = tree(tmp_path / "a")
    before = binding(root)
    (root / filename).write_bytes(b"altered")
    after = binding(root)
    assert after["policy_digest"] == before["policy_digest"]
    assert after["content_digest"] != before["content_digest"]


def test_required_presence_is_checked_even_though_digest_helper_accepts_absence(tmp_path):
    root = tree(tmp_path / "a")
    (root / "message_trace.parquet").unlink()
    assert digest_member_set(root, MEMBERS)
    with pytest.raises(ContractError, match="missing required"):
        binding(root)
    optional = binding(root, required=("trace.parquet",))
    (root / "message_trace.parquet").write_bytes(b"optional ledger")
    present = binding(root, required=("trace.parquet",))
    assert optional["policy_digest"] == present["policy_digest"]
    assert optional["content_digest"] != present["content_digest"]


def test_policy_scope_cannot_shrink_without_changing_its_binding(tmp_path):
    root = tree(tmp_path / "a")
    original = binding(root)
    for changed in (
        binding(root, required=("trace.parquet",)),
        binding(root, members=("trace.parquet",), required=("trace.parquet",)),
        binding(root, policy="t3-stable-output-v2"),
    ):
        assert original["policy_digest"] != changed["policy_digest"]
    assert original == binding(root, tuple(reversed(MEMBERS)), tuple(reversed(MEMBERS)))


@pytest.mark.parametrize(
    "members,required",
    [
        ((), ()),
        (MEMBERS, ()),
        (MEMBERS, ("extra.parquet",)),
        (MEMBERS + ("trace.parquet",), MEMBERS),
        (MEMBERS, MEMBERS + ("trace.parquet",)),
        (("../escape",), ("../escape",)),
        (("/absolute",), ("/absolute",)),
    ],
)
def test_invalid_member_policies_are_refused(tmp_path, members, required):
    with pytest.raises(ContractError):
        binding(tree(tmp_path / "a"), members, required)


@pytest.mark.parametrize("policy", ["", "../x", "A", "a" * 81, None])
def test_policy_identifier_is_bounded(tmp_path, policy):
    with pytest.raises(ContractError):
        binding(tree(tmp_path / "a"), policy=policy)


def test_symlinked_root_and_member_are_refused(tmp_path):
    root = tree(tmp_path / "real")
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(ContractError):
        binding(link)
    (root / "trace.parquet").unlink()
    (root / "trace.parquet").symlink_to(root / "message_trace.parquet")
    with pytest.raises(ContractError):
        binding(root)


def test_missing_batch_subtree_is_not_an_optional_member(tmp_path):
    root = tmp_path / "batch"
    root.mkdir()
    tree(root / "sub_00")
    members = tuple(f"{sub}/{f}" for sub in ("sub_00", "sub_01") for f in MEMBERS)
    with pytest.raises(ContractError, match="missing required"):
        binding(root, members, members)


def test_reader_retains_legacy_signed_fixture_without_inventing_evidence():
    original = load_fixture("c2_run_record.json")
    d = copy.deepcopy(original)
    record = RunRecord.from_mapping(d)
    record.verify_attestation(dev_trust_store(), require_production_trust=False)
    assert d == original
    assert all("stable_output_binding" not in r for r in record.repeats)


def test_new_evidence_parses_and_is_covered_by_signature(tmp_path):
    evidence = binding(tree(tmp_path / "a"))
    d = doc(evidence)
    d["attestation"]["signature"] = sign_payload(
        attestation_payload(d),
        seed=DEV_SEED,
        key_id=DEV_KEY_ID,
        signed_at="2026-08-21T10:05:00Z",
    ).to_mapping()
    record = RunRecord.from_mapping(d)
    record.verify_attestation(dev_trust_store(), require_production_trust=False)
    assert record.repeats[0]["stable_output_binding"] == evidence
    assert record.repeats[0]["output_tree_digest"] == "sha256:" + "a" * 64
    assert record.bindings["sanitized_tree_digest"] == d["bindings"]["sanitized_tree_digest"]
    d["repeats"][0]["stable_output_binding"]["policy_digest"] = "sha256:" + "b" * 64
    with pytest.raises(SignatureUnverifiable):
        RunRecord.from_mapping(d).verify_attestation(
            dev_trust_store(),
            require_production_trust=False,
        )


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        {},
        {"content_digest": "sha256:" + "a" * 64},
        {"policy_digest": "bad", "content_digest": "sha256:" + "a" * 64},
        {
            "policy_digest": "sha256:" + "a" * 64,
            "content_digest": "sha256:" + "b" * 64,
            "participant_paths": [],
        },
    ],
)
def test_parser_and_json_schema_both_refuse_bad_evidence(evidence):
    d = doc()
    d["repeats"][0]["stable_output_binding"] = evidence
    schema = json.loads(
        (
            Path(__file__).parents[2] / "qfbench2_common/schemas/c2_run_record.schema.json"
        ).read_text()
    )
    with pytest.raises(ContractError):
        RunRecord.from_mapping(d)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(d, schema)


def test_new_evidence_and_legacy_fixture_pass_json_schema(tmp_path):
    schema = json.loads(
        (
            Path(__file__).parents[2] / "qfbench2_common/schemas/c2_run_record.schema.json"
        ).read_text()
    )
    jsonschema.validate(load_fixture("c2_run_record.json"), schema)
    jsonschema.validate(doc(binding(tree(tmp_path / "a"))), schema)
