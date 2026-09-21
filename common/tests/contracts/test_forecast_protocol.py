"""Synthetic cryptographic rehearsal for the unactivated two-stage forecast candidate.

Every signature uses the shipped development seed and invented observations. Controls alter
both unsigned bytes and correctly re-signed documents to separate signature authentication
from semantic chain validation. No production signer, private corpus, or external call is used.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

import pytest

from qfbench2_common.contracts import (
    ContractError,
    EvaluationPlan,
    RunRecord,
    attestation_payload,
    digest_json,
    digest_tree,
    sign_payload,
)
from qfbench2_common.contracts.descriptor import seal_descriptor_digest
from qfbench2_common.contracts.digest import sha256_bytes
from qfbench2_common.contracts.fixtures import DEV_KEY_ID, DEV_SEED, dev_trust_store, load_fixture
from qfbench2_common.contracts.forecast_protocol import (
    VERSION,
    verify_forecast_freeze,
    verify_forecast_protocol,
    verify_forecast_resolution,
)


def encoded(obj: Any) -> bytes:
    return json.dumps(obj, allow_nan=False).encode()


def signed(obj: dict[str, Any], at: str) -> dict[str, Any]:
    obj = copy.deepcopy(obj)
    obj.pop("signature", None)
    obj["signature"] = sign_payload(
        obj, seed=DEV_SEED, key_id=DEV_KEY_ID, signed_at=at
    ).to_mapping()
    return obj


def commitment(values: dict[str, bytes]) -> str:
    return digest_json({k: sha256_bytes(v) for k, v in values.items()})


def case() -> dict[str, Any]:
    plan = load_fixture("c1/forecasting_final.expanded.json")
    plan.pop("signature")
    plan["normalization"] = {"mode": "ref_scale"}
    for entry in plan["roster"]["expected_units"]:
        grid = entry["grid"]
        grid["digest"] = digest_json({k: v for k, v in grid.items() if k != "digest"})
    handles = [e["unit_handle"] for e in plan["roster"]["expected_units"]]
    policies = {
        e["unit_handle"]: [
            dict(
                asset=a,
                horizon=h,
                source="synthetic-release",
                first_public_not_before="2026-10-05T12:00:00Z",
            )
            for a in e["grid"]["assets"]
            for h in e["grid"]["horizons"]
        ]
        for e in plan["roster"]["expected_units"]
    }
    protocol = signed(
        dict(
            schema_version=VERSION,
            kind="forecast_protocol",
            resolution_template=plan,
            schedule=dict(
                information_cutoff="2026-10-01T00:00:00Z",
                forecast_deadline="2026-10-02T00:00:00Z",
                resolution_deadline="2026-11-30T23:59:59Z",
            ),
            scale_recipe=dict(
                implementation_digest=digest_json("synthetic-M0"),
                version="synthetic-1",
                seed_policy=dict(algorithm="synthetic-fixed", seed=42),
                weights=dict(marginal=0.5, joint=0.3, tail=0.2),
                joint_statistics={h: "variogram" for h in handles},
            ),
            outcome_policy=dict(
                missing="abort_whole_evaluation", vintage="first_public", cells=policies
            ),
        ),
        "2026-09-30T00:00:00Z",
    )
    descriptor = load_fixture("c5/forecasting_final.json")
    descriptor["models"] = []
    descriptor = seal_descriptor_digest(
        {k: v for k, v in descriptor.items() if k != "descriptor_digest"}
    )
    records, trees, forecasts, outcomes, scales = {}, {}, {}, {}, {}
    for handle in handles:
        data = b"synthetic forecast bytes retained before outcome publication"
        forecasts[handle] = {"forecast.parquet": data}
        tree = load_fixture("c3_artifact_tree.json")
        tree["rejections"] = []
        tree["entries"] = [
            dict(
                path="forecast.parquet",
                size_bytes=len(data),
                sha256=sha256_bytes(data),
                mode_bits=0o644,
                num_rows=6,
            )
        ]
        tree["root_digest"] = digest_tree(tree["entries"])
        trees[handle] = encoded(tree)
        record = load_fixture("c2_run_record.json")
        record["unit_handle"] = handle
        record["run_id"] = "synthetic-" + handle
        record["bindings"].update(
            plan_digest=protocol["signature"]["payload_digest"],
            descriptor_digest=descriptor["descriptor_digest"],
            sanitized_tree_digest=tree["root_digest"],
        )
        record["image"]["resolved_digest"] = descriptor["image"]["digest"]
        record["timing"]["started_at"] = "2026-10-01T01:00:00Z"
        record["timing"]["ended_at"] = "2026-10-01T01:04:12Z"
        record["attestation"]["signature"] = sign_payload(
            attestation_payload(record),
            seed=DEV_SEED,
            key_id=DEV_KEY_ID,
            signed_at="2026-10-01T01:05:00Z",
        ).to_mapping()
        records[handle] = encoded(record)
        outcomes[handle] = encoded(
            dict(
                cells=[
                    dict(
                        asset=c["asset"],
                        horizon=c["horizon"],
                        value=0.75,
                        source=c["source"],
                        first_public_at="2026-10-05T12:00:00Z",
                        source_content_digest=digest_json("synthetic-source-snapshot"),
                    )
                    for c in policies[handle]
                ]
            )
        )
        scales[handle] = encoded(dict(marginal=1.0, joint=2.0, tail=3.0))
    config = b'{"seed": 17}'
    receipt = signed(
        dict(
            schema_version=VERSION,
            kind="forecast_receipt",
            protocol_digest=protocol["signature"]["payload_digest"],
            descriptor_digest=descriptor["descriptor_digest"],
            image_digest=descriptor["image"]["digest"],
            config_digest=sha256_bytes(config),
            model_dependencies_commitment=commitment({}),
            records_commitment=commitment(records),
            trees_commitment=commitment(trees),
        ),
        "2026-10-01T02:00:00Z",
    )
    resolved_plan = copy.deepcopy(plan)
    resolved_plan["normalization"]["ref_scale_commitment"] = commitment(scales)
    resolved_plan = signed(resolved_plan, "2026-10-06T00:00:00Z")
    resolution = signed(
        dict(
            schema_version=VERSION,
            kind="forecast_resolution",
            supersedes=protocol["signature"]["payload_digest"],
            receipt_digest=receipt["signature"]["payload_digest"],
            plan=resolved_plan,
            outcomes_commitment=commitment(outcomes),
            scales_commitment=commitment(scales),
        ),
        "2026-10-06T00:01:00Z",
    )
    return dict(
        protocol=encoded(protocol),
        receipt=encoded(receipt),
        resolution=encoded(resolution),
        descriptor=encoded(descriptor),
        config=config,
        model_dependencies={},
        records=records,
        trees=trees,
        forecasts=forecasts,
        outcomes=outcomes,
        scales=scales,
        organizer_trust=dev_trust_store(),
        runner_trust=dev_trust_store(),
        receipt_trust=dev_trust_store(),
        now=datetime(2026, 10, 7, tzinfo=timezone.utc),
        require_production_trust=False,
    )


def edit_signed(c: dict[str, Any], key: str, change: Any) -> None:
    obj = json.loads(c[key])
    change(obj)
    c[key] = encoded(signed(obj, obj["signature"]["signed_at"]))


def refresh_resolution(c: dict[str, Any]) -> None:
    def change(obj: dict[str, Any]) -> None:
        obj["outcomes_commitment"] = commitment(c["outcomes"])
        obj["scales_commitment"] = commitment(c["scales"])
        obj["plan"]["normalization"]["ref_scale_commitment"] = commitment(c["scales"])
        obj["plan"] = signed(obj["plan"], obj["plan"]["signature"]["signed_at"])

    edit_signed(c, "resolution", change)


def refresh_receipt(c: dict[str, Any]) -> None:
    def change(obj: dict[str, Any]) -> None:
        obj["records_commitment"] = commitment(c["records"])
        obj["trees_commitment"] = commitment(c["trees"])

    edit_signed(c, "receipt", change)
    edit_signed(
        c,
        "resolution",
        lambda obj: obj.update(
            receipt_digest=json.loads(c["receipt"])["signature"]["payload_digest"]
        ),
    )


def test_complete_two_stage_chain_and_legacy_binding_unchanged() -> None:
    c = case()
    p = verify_forecast_protocol(
        c["protocol"],
        organizer_trust=c["organizer_trust"],
        now=c["now"],
        require_production_trust=False,
    )
    frozen = verify_forecast_freeze(
        **{k: v for k, v in c.items() if k not in ("resolution", "outcomes", "scales")}
    )
    resolved = verify_forecast_resolution(**c)
    assert p.protocol_digest == frozen.protocol_digest == resolved.protocol_digest
    assert resolved.unit_count == 3 and resolved.plan_digest != resolved.protocol_digest
    plan = EvaluationPlan.from_mapping(json.loads(c["resolution"])["plan"])
    record = RunRecord.from_mapping(json.loads(next(iter(c["records"].values()))))
    with pytest.raises(ContractError, match="plan_digest"):
        record.verify_bindings(plan_digest=plan.plan_digest)


@pytest.mark.parametrize("stage", ["protocol", "freeze", "resolution"])
def test_forecasting_attempt_scope_is_refused_before_accepting_a_precommit(stage: str) -> None:
    c = case()
    edit_signed(
        c,
        "protocol",
        lambda obj: obj["resolution_template"]["metric"].update(unit_scope="per_unit_attempt"),
    )
    # The generic C1 metric parser supports attempts for coding, but this closed forecasting
    # template has no attempts_per_unit and freezes slot zero only. Reject at the first stage;
    # do not wait for an eventual scoring adapter to discover an undefined denominator.
    with pytest.raises(ContractError, match="requires per_unit scoring"):
        if stage == "protocol":
            verify_forecast_protocol(
                c["protocol"],
                organizer_trust=c["organizer_trust"],
                now=c["now"],
                require_production_trust=False,
            )
        elif stage == "freeze":
            verify_forecast_freeze(
                **{k: v for k, v in c.items() if k not in ("resolution", "outcomes", "scales")}
            )
        else:
            verify_forecast_resolution(**c)


@pytest.mark.parametrize("member", ["protocol", "receipt", "resolution"])
def test_signature_tamper(member: str) -> None:
    c = case()
    obj = json.loads(c[member])
    obj["signature"]["signature"] = "A" * 86 + "=="
    c[member] = encoded(obj)
    with pytest.raises(ContractError):
        verify_forecast_resolution(**c)


@pytest.mark.parametrize("member", ["organizer_trust", "runner_trust", "receipt_trust"])
def test_each_authority_is_required(member: str) -> None:
    from qfbench2_common.contracts import TrustStore

    c = case()
    c[member] = TrustStore({}, profile="production", label="empty")
    with pytest.raises(ContractError):
        verify_forecast_resolution(**c)


def test_production_default_rejects_dev_keys() -> None:
    c = case()
    c.pop("require_production_trust")
    with pytest.raises(ContractError):
        verify_forecast_resolution(**c)


@pytest.mark.parametrize("field", ["config", "forecasts", "records", "trees", "outcomes", "scales"])
def test_exact_bytes_cannot_be_substituted(field: str) -> None:
    c = case()
    if field == "config":
        c[field] += b" "
    elif field == "forecasts":
        c[field][next(iter(c[field]))]["forecast.parquet"] += b" "
    else:
        c[field][next(iter(c[field]))] += b" "
    with pytest.raises(ContractError):
        verify_forecast_resolution(**c)


@pytest.mark.parametrize("field", ["records", "trees", "forecasts", "outcomes", "scales"])
def test_missing_evidence_never_falls_back(field: str) -> None:
    c = case()
    c[field].pop(next(iter(c[field])))
    with pytest.raises(ContractError):
        verify_forecast_resolution(**c)


@pytest.mark.parametrize("value", [True, None, "1", float("nan"), float("inf")])
def test_fully_resigned_invalid_outcomes_refused(value: Any) -> None:
    c = case()
    handle = next(iter(c["outcomes"]))
    outcome = json.loads(c["outcomes"][handle])
    outcome["cells"][0]["value"] = value
    c["outcomes"][handle] = json.dumps(outcome).encode()
    refresh_resolution(c)
    with pytest.raises(ContractError):
        verify_forecast_resolution(**c)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "source", "late", "grid"])
def test_fully_resigned_bad_cells_refused(mutation: str) -> None:
    c = case()
    handle = next(iter(c["outcomes"]))
    outcome = json.loads(c["outcomes"][handle])
    row = outcome["cells"][0]
    if mutation == "missing":
        outcome["cells"].pop()
    elif mutation == "extra":
        row["unexpected"] = 1
    elif mutation == "duplicate":
        outcome["cells"][1] = copy.deepcopy(row)
    elif mutation == "source":
        row["source"] = "another-source"
    elif mutation == "late":
        row["first_public_at"] = "2026-10-07T00:00:00Z"
    else:
        row["horizon"] = True
    c["outcomes"][handle] = encoded(outcome)
    refresh_resolution(c)
    with pytest.raises(ContractError):
        verify_forecast_resolution(**c)


@pytest.mark.parametrize("value", [0, -1, True, None, "1"])
def test_fully_resigned_invalid_scales_refused(value: Any) -> None:
    c = case()
    handle = next(iter(c["scales"]))
    c["scales"][handle] = encoded(dict(marginal=value, joint=1, tail=1))
    refresh_resolution(c)
    with pytest.raises(ContractError):
        verify_forecast_resolution(**c)


def test_resolution_cannot_change_metric_even_with_valid_signatures() -> None:
    c = case()

    def change(obj: dict[str, Any]) -> None:
        obj["plan"]["metric"]["statistic"] = "median"
        obj["plan"] = signed(obj["plan"], obj["plan"]["signature"]["signed_at"])

    edit_signed(c, "resolution", change)
    with pytest.raises(ContractError, match="precommitted plan"):
        verify_forecast_resolution(**c)


@pytest.mark.parametrize("stamp", ["2026-10-02T00:00:01Z", "2026-10-05T12:00:00Z"])
def test_late_receipt_refused(stamp: str) -> None:
    c = case()
    c["receipt"] = encoded(signed(json.loads(c["receipt"]), stamp))
    with pytest.raises(ContractError, match="forecast window"):
        verify_forecast_resolution(**c)


def test_execution_after_receipt_refused_even_if_resigned() -> None:
    c = case()
    handle = next(iter(c["records"]))
    record = json.loads(c["records"][handle])
    record["timing"]["ended_at"] = "2026-10-02T00:00:00Z"
    record["attestation"]["signature"] = sign_payload(
        attestation_payload(record),
        seed=DEV_SEED,
        key_id=DEV_KEY_ID,
        signed_at="2026-10-02T00:00:01Z",
    ).to_mapping()
    c["records"][handle] = encoded(record)
    refresh_receipt(c)
    with pytest.raises(ContractError):
        verify_forecast_resolution(**c)


def test_protocol_boundary_equality_refused() -> None:
    c = case()
    edit_signed(
        c, "protocol", lambda obj: obj["schedule"].update(forecast_deadline="2026-10-05T12:00:00Z")
    )
    with pytest.raises(ContractError, match="strictly"):
        verify_forecast_resolution(**c)


def test_duplicate_json_keys_and_nested_unknown_keys_refused() -> None:
    c = case()
    c["protocol"] = c["protocol"].replace(b'"kind":', b'"kind":"forecast_protocol","kind":', 1)
    with pytest.raises(ContractError, match="duplicate"):
        verify_forecast_resolution(**c)
    c = case()
    edit_signed(c, "protocol", lambda obj: obj["scale_recipe"].update(extra=True))
    with pytest.raises(ContractError, match="exact keys"):
        verify_forecast_resolution(**c)


def test_mapping_order_does_not_change_commitment_and_byte_inputs_are_immutable() -> None:
    c = case()
    first = verify_forecast_resolution(**c)
    c["records"] = dict(reversed(list(c["records"].items())))
    c["scales"] = dict(reversed(list(c["scales"].items())))
    assert verify_forecast_resolution(**c) == first
    c["config"] = bytearray(c["config"])
    with pytest.raises(ContractError, match="configuration"):
        verify_forecast_resolution(**c)


@pytest.mark.parametrize("kind", ["supersedes", "receipt_digest"])
def test_resolution_link_substitution_refused(kind: str) -> None:
    c = case()
    edit_signed(c, "resolution", lambda obj: obj.update({kind: digest_json("unrelated chain")}))
    with pytest.raises(ContractError, match="chain mismatch"):
        verify_forecast_resolution(**c)


@pytest.mark.parametrize(
    "target", ["unit_handle", "plan_digest", "descriptor_digest", "sanitized_tree_digest", "image"]
)
def test_resigned_c2_substitution_refused(target: str) -> None:
    c = case()
    handle = next(iter(c["records"]))
    record = json.loads(c["records"][handle])
    if target == "unit_handle":
        record[target] = list(c["records"])[1]
    elif target == "image":
        record["image"]["resolved_digest"] = digest_json("other-image")
    else:
        record["bindings"][target] = digest_json("other-binding")
    record["attestation"]["signature"] = sign_payload(
        attestation_payload(record),
        seed=DEV_SEED,
        key_id=DEV_KEY_ID,
        signed_at=record["attestation"]["signature"]["signed_at"],
    ).to_mapping()
    c["records"][handle] = encoded(record)
    refresh_receipt(c)
    with pytest.raises(ContractError):
        verify_forecast_resolution(**c)


def test_nested_mapping_mutation_is_reverified_and_old_result_cannot_authorize_it() -> None:
    c = case()
    result = verify_forecast_resolution(**c)
    handle = next(iter(c["forecasts"]))
    nested_alias = c["forecasts"][handle]
    nested_alias["forecast.parquet"] = b"changed after successful verification"
    assert result.unit_count == 3
    with pytest.raises(ContractError, match="retained forecast bytes"):
        verify_forecast_resolution(**c)


@pytest.mark.parametrize("mutation", ["extra-file", "noncanonical-path", "limits"])
def test_signed_c3_manifest_controls(mutation: str) -> None:
    c = case()
    handle = next(iter(c["trees"]))
    if mutation == "extra-file":
        c["forecasts"][handle]["extra.bin"] = b"extra"
    else:
        tree = json.loads(c["trees"][handle])
        if mutation == "noncanonical-path":
            tree["entries"][0]["path"] = "./forecast.parquet"
        else:
            tree["limits_applied"]["max_file_bytes"] = 1
        c["trees"][handle] = encoded(tree)
        refresh_receipt(c)
    with pytest.raises(ContractError):
        verify_forecast_resolution(**c)


@pytest.mark.parametrize(
    "mutation",
    ["boolean-horizon", "duplicate-asset", "boolean-weight", "boolean-seed", "unknown-policy"],
)
def test_protocol_primitive_and_closed_policy_controls(mutation: str) -> None:
    c = case()

    def change(obj: dict[str, Any]) -> None:
        if mutation == "boolean-horizon":
            obj["resolution_template"]["roster"]["expected_units"][0]["grid"]["horizons"][0] = True
        elif mutation == "duplicate-asset":
            obj["resolution_template"]["roster"]["expected_units"][0]["grid"]["assets"][1] = "SYN-A"
        elif mutation == "boolean-weight":
            obj["scale_recipe"]["weights"]["tail"] = True
        elif mutation == "boolean-seed":
            obj["scale_recipe"]["seed_policy"]["seed"] = True
        else:
            obj["outcome_policy"]["missing"] = "drop_missing_units"

    edit_signed(c, "protocol", change)
    with pytest.raises(ContractError):
        verify_forecast_resolution(**c)


def test_model_dependencies_are_exact_and_descriptor_is_bound() -> None:
    c = case()
    c["model_dependencies"]["undeclared"] = b"weights"
    with pytest.raises(ContractError, match="dependency roster"):
        verify_forecast_resolution(**c)
    c = case()
    descriptor = json.loads(c["descriptor"])
    descriptor["image"]["digest"] = digest_json("changed-image")
    c["descriptor"] = encoded(
        seal_descriptor_digest({k: v for k, v in descriptor.items() if k != "descriptor_digest"})
    )
    with pytest.raises(ContractError, match="submission mismatch"):
        verify_forecast_resolution(**c)


def test_future_signatures_and_resolution_deadline_are_refused() -> None:
    c = case()
    c["now"] = datetime(2026, 9, 1, tzinfo=timezone.utc)
    with pytest.raises(ContractError, match="verifier time"):
        verify_forecast_resolution(**c)
    c = case()
    c["now"] = datetime(2026, 12, 2, tzinfo=timezone.utc)
    c["resolution"] = encoded(signed(json.loads(c["resolution"]), "2026-12-01T00:00:00Z"))
    with pytest.raises(ContractError, match="chronology"):
        verify_forecast_resolution(**c)


def test_json_requires_utf8_and_no_digest_or_timestamp_suffix() -> None:
    c = case()
    c["protocol"] = c["protocol"].decode().encode("utf-16")
    with pytest.raises(ContractError, match="UTF-8"):
        verify_forecast_resolution(**c)
    c = case()
    edit_signed(
        c,
        "protocol",
        lambda obj: obj["schedule"].update(forecast_deadline="2026-10-02T00:00:00Z\n"),
    )
    with pytest.raises(ContractError, match="UTC"):
        verify_forecast_resolution(**c)
