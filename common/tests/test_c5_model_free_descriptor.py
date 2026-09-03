"""C5 1.1.0: a model-free descriptor is valid; every 1.0.0 vector still validates unchanged."""
from __future__ import annotations

import glob
import json
import pathlib

import pytest

from qfbench2_common.contracts import SubmissionDescriptor
from qfbench2_common.contracts.descriptor import SCHEMA_VERSION, seal_descriptor_digest

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "qfbench2_common" / "contracts" / "fixtures" / "c5"


def _body(schema_version: str) -> dict:
    return {
        "schema_version": schema_version, "interface_version": "2.0",
        "competition_id": "agenthon2026-simulation-dev", "team_id": "team", "track": "simulation",
        "phase": "dev", "category": "simulator",
        "image": {"registry": "ghcr.io", "repository": "org/image", "digest": "sha256:" + "a" * 64},
        "image_access": "organizer_mirror", "models": [], "license": "MIT",
    }


def test_the_contract_version_is_1_1_0():
    assert SCHEMA_VERSION == "1.1.0"


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0"])
def test_a_model_free_descriptor_seals_and_validates(version):
    sealed = seal_descriptor_digest(_body(version))
    parsed = SubmissionDescriptor.from_mapping(sealed)
    assert parsed.models == ()
    assert parsed.descriptor_digest == sealed["descriptor_digest"]


def test_a_missing_models_key_is_still_refused():
    body = _body("1.1.0")
    del body["models"]
    with pytest.raises(Exception):
        SubmissionDescriptor.from_mapping(seal_descriptor_digest(body))


def test_every_shipped_1_0_0_vector_still_validates_with_its_digest():
    vectors = sorted(glob.glob(str(FIXTURES / "*.json")))
    assert vectors, "no C5 conformance vectors shipped"
    for path in vectors:
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        parsed = SubmissionDescriptor.from_mapping(raw)
        assert parsed.descriptor_digest == raw["descriptor_digest"], path
