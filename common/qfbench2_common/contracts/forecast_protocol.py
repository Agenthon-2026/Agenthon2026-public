"""Candidate two-stage forecasting evidence; importing this module activates no scoring path.

A signed protocol commits policy before any scored outcome is public. A separately signed
receipt binds completed C2 executions and retained C3 forecast bytes before that boundary.
A later resolution links both signatures to a normal C1 and complete finite outcome/scale
snapshots. Verification authenticates claims and their chronology, not an independent clock
measurement; a live privileged signer and durable archive remain deployment requirements.
All inputs are retained immutable bytes, never paths or caller-claimed verified objects.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ._time import parse_rfc3339
from .artifact_tree import SanitizedTree
from .descriptor import SubmissionDescriptor
from .digest import digest_json, normalize_tree_path, sha256_bytes
from .errors import ContractError
from .plan import (
    CONTRACT_SET,
    EvaluationPlan,
    MetricSpec,
    ParticipantFailurePolicy,
    compute_roster_digest,
    validate_unit_handle,
)
from .run_record import RunRecord, derive_unmet_controls
from .signing import SignatureEnvelope, TrustStore, verify_signed_object

VERSION = "candidate-1"
_MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")
_TEMPLATE_KEYS = (
    "schema_version",
    "contract_set",
    "competition_id",
    "track",
    "phase",
    "plan_id",
    "metric",
    "roster",
    "participant_failure",
    "organizer_failure",
    "scorer",
    "required_evidence",
    "normalization",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _closed(value: Any, keys: tuple[str, ...], label: str) -> dict[str, Any]:
    _require(isinstance(value, dict) and set(value) == set(keys), f"{label}: exact keys required")
    return dict(value)


def _text(value: Any, label: str) -> str:
    _require(
        isinstance(value, str) and bool(value) and not any(ord(c) < 32 for c in value),
        f"{label}: nonempty text required",
    )
    return str(value)


def _digest(value: Any) -> str:
    _require(
        isinstance(value, str) and _DIGEST.fullmatch(value) is not None,
        "exact sha256 digest required",
    )
    return str(value)


def _time(value: Any) -> datetime:
    _require(
        isinstance(value, str) and _TIME.fullmatch(value) is not None,
        "canonical UTC timestamp required",
    )
    return parse_rfc3339(value, field="forecast timestamp")


def _number(value: Any) -> float:
    _require(type(value) in (int, float), "finite numeric value required; booleans are forbidden")
    try:
        result = float(value)
    except OverflowError:
        raise ContractError("finite numeric value required") from None
    _require(math.isfinite(result), "finite numeric value required")
    return result


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON keys are forbidden")
        result[key] = value
    return result


def _json(raw: bytes) -> dict[str, Any]:
    _require(
        type(raw) is bytes and len(raw) <= _MAX_DOCUMENT_BYTES,
        "bounded immutable document bytes required",
    )
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        _require(isinstance(value, dict), "document must be an object")
        # Also rejects NaN/Infinity and integers outside JCS's exact range, recursively.
        digest_json(value)
        return dict(value)
    except (ValueError, UnicodeError, RecursionError):
        raise ContractError("invalid finite UTF-8 JSON document") from None


def _snapshot(values: Mapping[str, bytes]) -> dict[str, bytes]:
    _require(isinstance(values, Mapping), "immutable byte mapping required")
    result = dict(values)
    for name, raw in result.items():
        _text(name, "snapshot member")
        _require(type(raw) is bytes, "immutable member bytes required")
    return result


def _commit(values: Mapping[str, bytes]) -> str:
    return digest_json({name: sha256_bytes(raw) for name, raw in values.items()})


def _signed(raw: bytes, trust: TrustStore, now: datetime, production: bool) -> dict[str, Any]:
    obj = _json(raw)
    envelope = SignatureEnvelope.from_mapping(obj.get("signature"))
    _require(
        now.tzinfo is not None and _time(envelope.signed_at) <= now,
        "signed time is later than verifier time",
    )
    verify_signed_object(obj, trust, require_production_trust=production)
    return obj


def _signed_digest(obj: dict[str, Any]) -> str:
    return _digest(obj["signature"]["payload_digest"])


def _template(value: Any) -> tuple[dict[str, Any], dict[str, list[tuple[str, int]]]]:
    plan = _closed(value, _TEMPLATE_KEYS, "resolution template")
    _require(
        plan["schema_version"] in ("1.1.0", "1.2.0", "1.3.0")
        and plan["contract_set"] == CONTRACT_SET
        and plan["track"] == "forecasting"
        and plan["phase"] in ("dev", "final", "verification"),
        "unsupported C1 template",
    )
    for key in ("competition_id", "plan_id"):
        _text(plan[key], key)
    metric = MetricSpec.from_mapping(plan["metric"])
    _require(
        metric.unit_scope == "per_unit",
        "forecasting candidate requires per_unit scoring; no attempt denominator is defined",
    )
    ParticipantFailurePolicy.from_mapping(plan["participant_failure"], metric)
    _require(
        plan["organizer_failure"] == {"policy": "abort_whole_evaluation"},
        "organizer failures must abort",
    )
    _require(
        plan["normalization"] == {"mode": "ref_scale"},
        "pre-outcome template must omit unavailable numeric scales",
    )
    scorer = _closed(plan["scorer"], ("package", "digest", "interface_version"), "scorer")
    _digest(scorer["digest"])
    _text(scorer["package"], "scorer package")
    _text(scorer["interface_version"], "scorer version")
    ev = _closed(plan["required_evidence"], ("c2", "c3", "telemetry", "judge"), "evidence")
    _require(
        all(type(v) is bool for v in ev.values()) and ev["c2"] and ev["c3"],
        "C2 and C3 evidence must be required",
    )
    roster = _closed(plan["roster"], ("count", "digest", "expected_units"), "expanded roster")
    _require(
        type(roster["count"]) is int
        and roster["count"] > 0
        and isinstance(roster["expected_units"], list),
        "nonempty expanded roster required",
    )
    cells: dict[str, list[tuple[str, int]]] = {}
    for value in roster["expected_units"]:
        entry = _closed(value, ("unit_handle", "grid"), "roster entry")
        handle = validate_unit_handle(entry["unit_handle"], phase=plan["phase"])
        _require(handle not in cells, "duplicate roster handle")
        grid = _closed(entry["grid"], ("assets", "horizons", "cell_count", "digest"), "grid")
        assets, horizons = grid["assets"], grid["horizons"]
        _require(
            isinstance(assets, list)
            and bool(assets)
            and isinstance(horizons, list)
            and bool(horizons),
            "nonempty grid arrays required",
        )
        for asset in assets:
            _text(asset, "asset")
        _require(
            all(type(h) is int and h > 0 for h in horizons), "positive integer horizons required"
        )
        _require(
            len(set(assets)) == len(assets) and len(set(horizons)) == len(horizons),
            "duplicate grid coordinates",
        )
        cells[handle] = [(a, h) for a in assets for h in horizons]
        _require(
            type(grid["cell_count"]) is int and grid["cell_count"] == len(cells[handle]),
            "grid size mismatch",
        )
        _require(
            _digest(grid["digest"])
            == digest_json({k: grid[k] for k in ("assets", "horizons", "cell_count")}),
            "candidate grid commitment mismatch",
        )
    _require(
        roster["count"] == len(cells)
        and _digest(roster["digest"]) == compute_roster_digest(list(cells)),
        "ordered roster commitment mismatch",
    )
    if plan["phase"] != "dev":
        _require(len({len(handle) for handle in cells}) == 1, "sealed handle widths differ")
    return plan, cells


def _protocol(raw: bytes, trust: TrustStore, now: datetime, production: bool) -> dict[str, Any]:
    obj = _closed(
        _signed(raw, trust, now, production),
        (
            "schema_version",
            "kind",
            "resolution_template",
            "schedule",
            "scale_recipe",
            "outcome_policy",
            "signature",
        ),
        "protocol",
    )
    _require(
        obj["schema_version"] == VERSION and obj["kind"] == "forecast_protocol",
        "unsupported forecasting protocol",
    )
    _, cells = _template(obj["resolution_template"])
    schedule = _closed(
        obj["schedule"],
        ("information_cutoff", "forecast_deadline", "resolution_deadline"),
        "schedule",
    )
    issued, cutoff, deadline, resolution = map(
        _time,
        (
            obj["signature"]["signed_at"],
            schedule["information_cutoff"],
            schedule["forecast_deadline"],
            schedule["resolution_deadline"],
        ),
    )
    _require(issued <= cutoff < deadline < resolution, "invalid protocol chronology")
    recipe = _closed(
        obj["scale_recipe"],
        ("implementation_digest", "version", "seed_policy", "weights", "joint_statistics"),
        "scale recipe",
    )
    _digest(recipe["implementation_digest"])
    _text(recipe["version"], "recipe version")
    seeds = _closed(recipe["seed_policy"], ("algorithm", "seed"), "seed policy")
    _text(seeds["algorithm"], "seed algorithm")
    _require(
        type(seeds["seed"]) is int and 0 <= seeds["seed"] < 2**53, "fixed integer seed required"
    )
    weights = _closed(recipe["weights"], ("marginal", "joint", "tail"), "weights")
    _require(
        all(_number(v) >= 0 for v in weights.values())
        and abs(sum(weights.values()) - 1.0) <= 1e-12,
        "weights must sum to one",
    )
    joints = recipe["joint_statistics"]
    _require(
        isinstance(joints, dict) and set(joints) == set(cells), "exact joint policy roster required"
    )
    for handle, grid in cells.items():
        _require(
            joints[handle] in ("variogram", "energy")
            and (len(grid) != 1 or joints[handle] == "variogram"),
            "invalid joint policy",
        )
    policy = _closed(obj["outcome_policy"], ("missing", "vintage", "cells"), "outcome policy")
    _require(
        policy["missing"] == "abort_whole_evaluation" and policy["vintage"] == "first_public",
        "candidate requires complete first-public outcomes; no roster reduction",
    )
    _require(
        isinstance(policy["cells"], dict) and set(policy["cells"]) == set(cells),
        "exact outcome-policy roster required",
    )
    for handle, grid in cells.items():
        rows = policy["cells"][handle]
        _require(isinstance(rows, list) and len(rows) == len(grid), "complete cell policy required")
        for row, (asset, horizon) in zip(rows, grid):
            row = _closed(
                row, ("asset", "horizon", "source", "first_public_not_before"), "cell policy"
            )
            _require(
                row["asset"] == asset and type(row["horizon"]) is int and row["horizon"] == horizon,
                "ordered cell policy mismatch",
            )
            _text(row["source"], "first-public source")
            _require(
                deadline < _time(row["first_public_not_before"]) <= resolution,
                "forecast deadline must precede every first-public boundary strictly",
            )
    return obj


@dataclass(frozen=True, slots=True)
class ForecastChainVerification:
    """Digest-only evidence result; no constructor is accepted as verification input."""

    protocol_digest: str
    receipt_digest: str | None = None
    resolution_digest: str | None = None
    plan_digest: str | None = None
    unit_count: int = 0


def verify_forecast_protocol(
    protocol: bytes,
    *,
    organizer_trust: TrustStore,
    now: datetime,
    require_production_trust: bool = True,
) -> ForecastChainVerification:
    """Authenticate and validate an explicit candidate protocol, without activating it."""
    obj = _protocol(protocol, organizer_trust, now, require_production_trust)
    return ForecastChainVerification(
        _signed_digest(obj), unit_count=len(obj["outcome_policy"]["cells"])
    )


def _freeze(
    protocol: dict[str, Any],
    receipt: bytes,
    *,
    descriptor: bytes,
    config: bytes,
    model_dependencies: Mapping[str, bytes],
    records: Mapping[str, bytes],
    trees: Mapping[str, bytes],
    forecasts: Mapping[str, Mapping[str, bytes]],
    runner_trust: TrustStore,
    receipt_trust: TrustStore,
    now: datetime,
    production: bool,
) -> dict[str, Any]:
    obj = _closed(
        _signed(receipt, receipt_trust, now, production),
        (
            "schema_version",
            "kind",
            "protocol_digest",
            "descriptor_digest",
            "image_digest",
            "config_digest",
            "model_dependencies_commitment",
            "records_commitment",
            "trees_commitment",
            "signature",
        ),
        "forecast receipt",
    )
    _require(
        obj["schema_version"] == VERSION
        and obj["kind"] == "forecast_receipt"
        and _digest(obj["protocol_digest"]) == _signed_digest(protocol),
        "receipt protocol mismatch",
    )
    plan, cells = _template(protocol["resolution_template"])
    records, trees = _snapshot(records), _snapshot(trees)
    frozen = {h: _snapshot(v) for h, v in dict(forecasts).items()}
    dependencies = _snapshot(model_dependencies)
    _require(
        set(records) == set(trees) == set(frozen) == set(cells), "exact frozen roster required"
    )
    c5 = SubmissionDescriptor.from_mapping(_json(descriptor))
    c5.matches_plan(competition_id=plan["competition_id"], track="forecasting", phase=plan["phase"])
    _require(
        _digest(obj["descriptor_digest"]) == c5.descriptor_digest
        and _digest(obj["image_digest"]) == c5.image_digest,
        "frozen submission mismatch",
    )
    _require(
        type(config) is bytes and _digest(obj["config_digest"]) == sha256_bytes(config),
        "frozen execution configuration mismatch",
    )
    _require(
        set(dependencies) == {m.name for m in c5.models},
        "complete model dependency roster required",
    )
    _require(
        _digest(obj["model_dependencies_commitment"]) == _commit(dependencies),
        "frozen model bytes mismatch",
    )
    _require(
        _digest(obj["records_commitment"]) == _commit(records)
        and _digest(obj["trees_commitment"]) == _commit(trees),
        "frozen evidence bytes mismatch",
    )
    cutoff = _time(protocol["schedule"]["information_cutoff"])
    deadline = _time(protocol["schedule"]["forecast_deadline"])
    accepted = _time(obj["signature"]["signed_at"])
    _require(cutoff <= accepted <= deadline, "receipt was not signed within forecast window")
    for handle in cells:
        raw = _json(records[handle])
        record = RunRecord.from_mapping(raw)
        record.verify_attestation(runner_trust, require_production_trust=production)
        tree_raw = _json(trees[handle])
        tree = SanitizedTree.from_mapping(tree_raw)
        _require(
            all(row["path"] == entry.path for row, entry in zip(tree_raw["entries"], tree.entries)),
            "noncanonical C3 source path",
        )
        limits = tree.limits_applied
        _require(
            len(tree.entries) <= limits.max_files
            and sum(e.size_bytes for e in tree.entries) <= limits.max_total_bytes
            and all(
                e.size_bytes <= limits.max_file_bytes and e.path.count("/") + 1 <= limits.max_depth
                for e in tree.entries
            ),
            "retained C3 manifest exceeds its signed limits",
        )
        record.verify_bindings(
            plan_digest=_signed_digest(protocol),
            descriptor_digest=c5.descriptor_digest,
            sanitized_tree_digest=tree.root_digest,
        )
        _require(
            record.unit_handle == handle
            and record.attempt_slot_index == 0
            and record.image["resolved_digest"] == c5.image_digest,
            "frozen C2 submission mismatch",
        )
        _require(
            record.is_rankable
            and not derive_unmet_controls(
                record, telemetry_required=plan["required_evidence"]["telemetry"]
            ),
            "unrankable frozen execution",
        )
        _require(
            record.participant_outcome == "success" and not tree.rejections,
            "candidate requires successful complete forecast evidence",
        )
        _require(
            cutoff
            <= _time(raw["timing"]["started_at"])
            <= _time(raw["timing"]["ended_at"])
            <= _time(raw["attestation"]["signature"]["signed_at"])
            <= accepted,
            "execution/attestation must finish before receipt and forecast deadline",
        )
        _require(
            bool(tree.entries) and {e.path for e in tree.entries} == set(frozen[handle]),
            "complete retained C3 members required",
        )
        for entry in tree.entries:
            _require(
                normalize_tree_path(entry.path) == entry.path and entry.mode_bits == 0o644,
                "canonical copied C3 member required",
            )
            data = frozen[handle][entry.path]
            _require(
                len(data) == entry.size_bytes and sha256_bytes(data) == entry.sha256,
                "retained forecast bytes do not match C3",
            )
    return obj


def verify_forecast_freeze(
    protocol: bytes,
    receipt: bytes,
    *,
    organizer_trust: TrustStore,
    runner_trust: TrustStore,
    receipt_trust: TrustStore,
    now: datetime,
    descriptor: bytes,
    config: bytes,
    model_dependencies: Mapping[str, bytes],
    records: Mapping[str, bytes],
    trees: Mapping[str, bytes],
    forecasts: Mapping[str, Mapping[str, bytes]],
    require_production_trust: bool = True,
) -> ForecastChainVerification:
    """Verify retained forecast evidence. This does not authorize later C1/C2 rebinding."""
    obj = _protocol(protocol, organizer_trust, now, require_production_trust)
    frozen = _freeze(
        obj,
        receipt,
        descriptor=descriptor,
        config=config,
        model_dependencies=model_dependencies,
        records=records,
        trees=trees,
        forecasts=forecasts,
        runner_trust=runner_trust,
        receipt_trust=receipt_trust,
        now=now,
        production=require_production_trust,
    )
    return ForecastChainVerification(
        _signed_digest(obj), _signed_digest(frozen), unit_count=len(obj["outcome_policy"]["cells"])
    )


def verify_forecast_resolution(
    protocol: bytes,
    receipt: bytes,
    resolution: bytes,
    *,
    organizer_trust: TrustStore,
    runner_trust: TrustStore,
    receipt_trust: TrustStore,
    now: datetime,
    descriptor: bytes,
    config: bytes,
    model_dependencies: Mapping[str, bytes],
    records: Mapping[str, bytes],
    trees: Mapping[str, bytes],
    forecasts: Mapping[str, Mapping[str, bytes]],
    outcomes: Mapping[str, bytes],
    scales: Mapping[str, bytes],
    require_production_trust: bool = True,
) -> ForecastChainVerification:
    """Verify the complete candidate chain and exact outcome/scale snapshots; never score it."""
    protocol_obj = _protocol(protocol, organizer_trust, now, require_production_trust)
    frozen = _freeze(
        protocol_obj,
        receipt,
        descriptor=descriptor,
        config=config,
        model_dependencies=model_dependencies,
        records=records,
        trees=trees,
        forecasts=forecasts,
        runner_trust=runner_trust,
        receipt_trust=receipt_trust,
        now=now,
        production=require_production_trust,
    )
    obj = _closed(
        _signed(resolution, organizer_trust, now, require_production_trust),
        (
            "schema_version",
            "kind",
            "supersedes",
            "receipt_digest",
            "plan",
            "outcomes_commitment",
            "scales_commitment",
            "signature",
        ),
        "resolution",
    )
    _require(
        obj["schema_version"] == VERSION
        and obj["kind"] == "forecast_resolution"
        and _digest(obj["supersedes"]) == _signed_digest(protocol_obj)
        and _digest(obj["receipt_digest"]) == _signed_digest(frozen),
        "resolution chain mismatch",
    )
    plan_raw = obj["plan"]
    _require(isinstance(plan_raw, dict), "signed resolution C1 required")
    plan = EvaluationPlan.from_mapping(plan_raw)
    plan.verify_signature(organizer_trust, require_production_trust=require_production_trust)
    projection = {k: v for k, v in plan_raw.items() if k != "signature"}
    projection["normalization"] = {"mode": "ref_scale"}
    _require(
        digest_json(projection) == digest_json(protocol_obj["resolution_template"]),
        "resolution changed the precommitted plan",
    )
    outcomes, scales = _snapshot(outcomes), _snapshot(scales)
    _, cells = _template(protocol_obj["resolution_template"])
    _require(set(outcomes) == set(scales) == set(cells), "complete resolution roster required")
    _require(
        _digest(obj["outcomes_commitment"]) == _commit(outcomes)
        and _digest(obj["scales_commitment"]) == _commit(scales)
        and plan.normalization is not None
        and plan.normalization["ref_scale_commitment"] == _commit(scales),
        "resolution byte commitments mismatch",
    )
    signed = _time(obj["signature"]["signed_at"])
    plan_signed = _time(plan_raw["signature"]["signed_at"])
    _require(
        _time(frozen["signature"]["signed_at"])
        < plan_signed
        <= signed
        <= _time(protocol_obj["schedule"]["resolution_deadline"]),
        "invalid resolution chronology",
    )
    for handle, grid in cells.items():
        outcome = _closed(_json(outcomes[handle]), ("cells",), "outcome snapshot")
        rows = outcome["cells"]
        _require(
            isinstance(rows, list) and len(rows) == len(grid),
            "complete finite outcome cells required",
        )
        for row, expected in zip(rows, protocol_obj["outcome_policy"]["cells"][handle]):
            row = _closed(
                row,
                ("asset", "horizon", "value", "source", "first_public_at", "source_content_digest"),
                "resolved cell",
            )
            _require(
                row["asset"] == expected["asset"]
                and type(row["horizon"]) is int
                and row["horizon"] == expected["horizon"]
                and row["source"] == expected["source"],
                "resolution cell/source mismatch",
            )
            _number(row["value"])
            _digest(row["source_content_digest"])
            _require(
                _time(expected["first_public_not_before"])
                <= _time(row["first_public_at"])
                <= plan_signed,
                "outcome was not available when resolution C1 was signed",
            )
        scale = _closed(_json(scales[handle]), ("marginal", "joint", "tail"), "numeric scales")
        _require(
            _number(scale["marginal"]) > 0
            and _number(scale["tail"]) > 0
            and (_number(scale["joint"]) >= 0 if len(grid) == 1 else _number(scale["joint"]) > 0),
            "invalid numeric normalization scales",
        )
    return ForecastChainVerification(
        _signed_digest(protocol_obj),
        _signed_digest(frozen),
        _signed_digest(obj),
        plan.plan_digest,
        len(cells),
    )
