"""The shipped C1-C8 golden fixtures are checked by nothing else.

Measured 2026-08-29: replacing ``c8_release_evidence.json`` with the literal text
``NOT JSON AT ALL`` left the suite at 31 passed, and the same edit to
``c1/coding_final.expanded.json`` was equally invisible. Every other test builds its
own objects, so a corrupted, truncated or silently re-signed fixture ships green.

These tests close that: every fixture must parse, and every fixture that carries a
signature envelope must still verify under the shipped development trust store.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from qfbench2_common.contracts import signing

FIXTURES = pathlib.Path(signing.__file__).parent / "fixtures"

# The dev store is forgeable by design (its seed is public), so production trust is
# not the property under test here -- integrity of what we ship is.
_DEV_TRUST = dict(require_production_trust=False)


def _fixture_files() -> list[pathlib.Path]:
    return sorted(p for p in FIXTURES.rglob("*.json"))


def _ids(paths: list[pathlib.Path]) -> list[str]:
    return [str(p.relative_to(FIXTURES)) for p in paths]


def test_fixture_directory_is_not_empty() -> None:
    """A glob that silently matches nothing would make every test below vacuous."""
    assert len(_fixture_files()) >= 15


@pytest.mark.parametrize("path", _fixture_files(), ids=_ids(_fixture_files()))
def test_fixture_parses(path: pathlib.Path) -> None:
    json.loads(path.read_text())


def _signed_fixtures() -> list[pathlib.Path]:
    out = []
    for p in _fixture_files():
        try:
            obj = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue  # test_fixture_parses owns that failure
        if isinstance(obj, dict) and isinstance(obj.get("signature"), dict):
            out.append(p)
    return out


def test_some_fixtures_are_signed() -> None:
    assert len(_signed_fixtures()) >= 5


@pytest.mark.parametrize("path", _signed_fixtures(), ids=_ids(_signed_fixtures()))
def test_signed_fixture_still_verifies(path: pathlib.Path) -> None:
    store = signing.TrustStore.load(FIXTURES / "dev_trust_store.json")
    signing.verify_signed_object(json.loads(path.read_text()), trust_store=store, **_DEV_TRUST)


def test_the_signature_check_actually_binds_content() -> None:
    """Positive control: without this, the test above could pass on a no-op verifier."""
    store = signing.TrustStore.load(FIXTURES / "dev_trust_store.json")
    obj = json.loads((FIXTURES / "c7_hardware.json").read_text())
    signing.verify_signed_object(obj, trust_store=store, **_DEV_TRUST)  # sanity

    obj["hardware"]["model"]["value"] = "1x NVIDIA H100 80GB"
    with pytest.raises(signing.SignatureUnverifiable):
        signing.verify_signed_object(obj, trust_store=store, **_DEV_TRUST)


def test_shipped_hardware_fixture_names_the_real_fleet() -> None:
    """The eval fleet is B200/sm_100. An H100 here published a wrong spec as 'measured'."""
    hw = json.loads((FIXTURES / "c7_hardware.json").read_text())["hardware"]
    assert "B200" in hw["model"]["value"]
    assert hw["architecture"]["value"] == "sm_100"
