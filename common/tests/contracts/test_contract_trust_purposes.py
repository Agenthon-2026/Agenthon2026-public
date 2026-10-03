"""Trust-store key purposes and the signing backend.

## Executive summary (read this first)

Before purposes, a trust store trusted every key it held for every signed document: a key
registered to sign run records could also sign an evaluation plan or a hardware instance, and
both would verify. `test_a_run_record_key_cannot_sign_a_plan` and
`test_a_run_record_key_cannot_sign_a_hardware_instance` pin that it cannot, each beside its
positive control (the same key, bound to the purpose, verifies).

What else is pinned:

* the store format: a production store that holds a key binds it; a development store may bind
  nothing, and then behaves exactly as before (every key, every document), and the development
  trust store document is byte-for-byte what it was;
* a host purpose (`c2`, `heartbeat`) never shares a key with an organizer purpose;
* a store that binds purposes refuses a verification that names none, or names an unknown one;
* a secret-key operation uses `cryptography` when it is installed, and a production signer can
  refuse the pure-Python fallback.

Everything is synthetic: the published development seed stands for an organizer key, and a second
published test seed stands for a host's run-record key.
"""

from __future__ import annotations

import base64
import copy
import importlib.util
import json

import pytest

from qfbench2_common.contracts import _ed25519, signing
from qfbench2_common.contracts.devattest import development_trust_store_document
from qfbench2_common.contracts.errors import ContractError
from qfbench2_common.contracts.fixtures import (
    DEV_KEY_ID,
    DEV_SEED,
    DEV_SELFATTEST_KEY_ID,
    dev_public_key,
    dev_selfattest_public_key,
    dev_trust_store,
    fixture_path,
    load_fixture,
)
from qfbench2_common.contracts.plan import EvaluationPlan
from qfbench2_common.contracts.run_record import RunRecord, attestation_payload
from qfbench2_common.contracts.signing import (
    HOST_PURPOSES,
    TRUST_PURPOSES,
    SignatureUnverifiable,
    TrustStore,
    derive_public_key,
    sign_payload,
    verify_signed,
    verify_signed_object,
)

#: NOT A CREDENTIAL. A published test seed standing for a fleet host's run-record key.
HOST_SEED = b"qfbench2-test-host-key-PUBLIC-00"
HOST_KEY_ID = "test-host-c2"
OWNER_KEY_ID = DEV_KEY_ID  # the published development key, standing for an organizer key
SIGNED_AT = "2026-08-21T09:00:00Z"

# RFC 8032 section 7.1, test vector 2 (public data): seed, public key, message, signature.
RFC8032_SEED = bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
RFC8032_PUBLIC = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
RFC8032_MESSAGE = bytes.fromhex("72")
RFC8032_SIGNATURE = bytes.fromhex(
    "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f361"
    "3d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def host_public_key() -> bytes:
    return _ed25519.public_key_from_seed(HOST_SEED)


_PUBLIC = {OWNER_KEY_ID: dev_public_key, HOST_KEY_ID: host_public_key}
_SEED = {OWNER_KEY_ID: DEV_SEED, HOST_KEY_ID: HOST_SEED}


def store(purposes: dict[str, list[str]], *, profile: str = "production") -> TrustStore:
    """A store holding exactly the keys `purposes` names, each bound to its list."""
    return TrustStore(
        {key_id: _PUBLIC[key_id]() for key_id in purposes},
        profile=profile,
        label="synthetic",
        purposes=purposes,
    )


def document(purposes: dict[str, list[str]] | None, *, profile: str = "production") -> dict:
    keys = [OWNER_KEY_ID, HOST_KEY_ID] if purposes is None else list(purposes)
    body = {
        "profile": profile,
        "label": "synthetic",
        "keys": {key_id: _b64(_PUBLIC[key_id]()) for key_id in keys},
    }
    if purposes is not None:
        body["purposes"] = purposes
    return body


def resigned(obj: dict, key_id: str) -> dict:
    """`obj` with its own envelope replaced by one from `key_id`."""
    obj = copy.deepcopy(obj)
    body = {k: v for k, v in obj.items() if k != "signature"}
    obj["signature"] = sign_payload(
        body, seed=_SEED[key_id], key_id=key_id, signed_at=SIGNED_AT
    ).to_mapping()
    return obj


def resigned_record(key_id: str) -> RunRecord:
    """The shipped golden C2, attested by `key_id`."""
    record = load_fixture("c2_run_record.json")
    record["attestation"]["signature"]["key_id"] = key_id
    record["attestation"]["signature"] = sign_payload(
        attestation_payload(record), seed=_SEED[key_id], key_id=key_id, signed_at=SIGNED_AT
    ).to_mapping()
    return RunRecord.from_mapping(record)


# =========================================================================== the store format
def test_a_production_store_that_holds_a_key_must_bind_it():
    """REGRESSION. Unbound production stores were the hole: every key verified every document."""
    with pytest.raises(ContractError, match="without `purposes`"):
        TrustStore.from_mapping(document(None))
    with pytest.raises(ContractError, match="must bind every key"):
        TrustStore({OWNER_KEY_ID: dev_public_key()}, profile="production")
    # POSITIVE CONTROL: the same keys, bound, load.
    bound = TrustStore.from_mapping(document({OWNER_KEY_ID: ["c1"], HOST_KEY_ID: ["c2"]}))
    assert bound.binds_purposes
    assert bound.purposes_of(HOST_KEY_ID) == ("c2",)


def test_an_empty_production_store_needs_no_purposes_and_binds_every_key_added_later():
    empty = TrustStore.from_mapping({"profile": "production", "label": "", "keys": {}})
    assert empty.is_empty and empty.binds_purposes
    assert TrustStore.empty().binds_purposes
    with pytest.raises(ContractError, match="names no purposes"):
        empty.add(HOST_KEY_ID, host_public_key())
    assert empty.is_empty, "a refused key must not be half-added"
    empty.add(HOST_KEY_ID, host_public_key(), purposes=["c2"])
    assert empty.purposes_of(HOST_KEY_ID) == ("c2",)


def test_a_development_store_may_bind_nothing_and_then_trusts_every_key_for_everything():
    """ABSENCE CONTROL. Development is unchanged: no purposes, no purpose check, any document."""
    dev = TrustStore.from_mapping(document(None, profile="development"))
    assert not dev.binds_purposes
    assert dev.purposes_of(HOST_KEY_ID) is None
    plan = EvaluationPlan.from_mapping(
        resigned(load_fixture("c1/simulation_final.expanded.json"), HOST_KEY_ID)
    )
    assert plan.verify_signature(dev, require_production_trust=False).purpose == "c1"
    record = resigned_record(OWNER_KEY_ID)
    assert record.verify_attestation(dev, require_production_trust=False).purpose == "c2"
    payload = {"anything": True}
    envelope = sign_payload(payload, seed=HOST_SEED, key_id=HOST_KEY_ID, signed_at=SIGNED_AT)
    assert verify_signed(payload, envelope, dev, require_production_trust=False).purpose is None


def test_the_development_trust_store_the_bundles_ship_is_unchanged():
    """The Development anchor binds no purposes, so its bytes, and every bundle's, are as before."""
    assert development_trust_store_document("label") == {
        "profile": "development",
        "label": "label",
        "keys": {
            DEV_KEY_ID: _b64(dev_public_key()),
            DEV_SELFATTEST_KEY_ID: _b64(dev_selfattest_public_key()),
        },
    }
    shipped = json.loads(fixture_path("dev_trust_store.json").read_text(encoding="utf-8"))
    assert "purposes" not in shipped
    assert not TrustStore.from_mapping(shipped).binds_purposes
    assert not dev_trust_store().binds_purposes
    # Round trip without inventing a member.
    assert TrustStore.from_mapping(development_trust_store_document("label")).to_mapping() == (
        development_trust_store_document("label")
    )


@pytest.mark.parametrize(
    ("purposes", "match"),
    [
        ({OWNER_KEY_ID: ["c1"]}, r"no purposes for key\(s\) \['test-host-c2'\]"),
        ({OWNER_KEY_ID: ["c1"], HOST_KEY_ID: ["c2"], "stray": ["c1"]}, "does not hold"),
    ],
)
def test_purposes_name_exactly_the_keys_the_store_holds(purposes, match):
    with pytest.raises(ContractError, match=match):
        TrustStore(
            {OWNER_KEY_ID: dev_public_key(), HOST_KEY_ID: host_public_key()},
            profile="production",
            purposes=purposes,
        )


@pytest.mark.parametrize(
    ("held", "match"),
    [
        ([], "names no purposes"),
        (None, "names no purposes"),
        ("c2", "must be a list"),
        (["c2", "c2"], "names a purpose twice"),
        (["c3"], "is not a trust purpose"),
        (["C2"], "is not a trust purpose"),
        ([2], "is not a trust purpose"),
        ({"c2": True}, "must be a list"),
    ],
)
def test_each_keys_purposes_are_a_list_of_distinct_known_names(held, match):
    with pytest.raises(ContractError, match=match):
        TrustStore.from_mapping(
            {**document({HOST_KEY_ID: ["c2"]}), "purposes": {HOST_KEY_ID: held}}
        )


@pytest.mark.parametrize(
    "held",
    [
        ["c2", "c1"],
        ["c2", "c7"],
        ["c2", "archive"],
        ["c2", "c6"],
        ["c2", "c8"],
        ["heartbeat", "c1"],
        ["heartbeat", "c7"],
        ["c2", "heartbeat", "c1"],
    ],
)
def test_a_host_purpose_never_shares_a_key_with_an_organizer_purpose(held):
    """A run-record key may not also sign plans or hardware instances."""
    with pytest.raises(ContractError, match="may hold no other purpose"):
        store({HOST_KEY_ID: held})
    # The rule holds in a development store that binds purposes as well.
    with pytest.raises(ContractError, match="may hold no other purpose"):
        store({HOST_KEY_ID: held}, profile="development")


@pytest.mark.parametrize(
    "held",
    [
        ["c1", "c7", "archive"],
        ["c1"],
        ["c7"],
        ["archive"],
        ["c6", "c8"],
        ["c2"],
        ["heartbeat"],
        ["c2", "heartbeat"],
        sorted(set(TRUST_PURPOSES) - HOST_PURPOSES),
    ],
)
def test_keys_within_one_class_may_hold_several_purposes(held):
    """POSITIVE CONTROL for the separation rule: the owner's key holds c1, c7 and archive."""
    assert store({OWNER_KEY_ID: held}).purposes_of(OWNER_KEY_ID) == tuple(sorted(held))


def test_the_vocabulary_is_closed_and_the_host_class_is_inside_it():
    assert set(TRUST_PURPOSES) == {"c1", "c2", "c6", "c7", "c8", "heartbeat", "archive"}
    assert HOST_PURPOSES == {"c2", "heartbeat"}
    assert HOST_PURPOSES <= set(TRUST_PURPOSES)


def test_the_document_round_trips_with_sorted_purposes():
    source = document({OWNER_KEY_ID: ["c7", "archive", "c1"], HOST_KEY_ID: ["c2"]})
    loaded = TrustStore.from_mapping(source)
    written = loaded.to_mapping()
    assert written["purposes"] == {OWNER_KEY_ID: ["archive", "c1", "c7"], HOST_KEY_ID: ["c2"]}
    again = TrustStore.from_mapping(json.loads(json.dumps(written)))
    assert again.to_mapping() == written
    assert again.purposes_of("absent") == ()


def test_a_store_that_binds_nothing_refuses_purposes_for_one_key():
    dev = TrustStore.from_mapping(document(None, profile="development"))
    with pytest.raises(ContractError, match="binds no key to a purpose"):
        dev.add("another", host_public_key(), purposes=["c2"])
    assert dev.get("another") is None


def test_a_purposes_member_that_is_not_an_object_is_refused():
    with pytest.raises(ContractError, match="purposes must be an object"):
        TrustStore.from_mapping({**document({HOST_KEY_ID: ["c2"]}), "purposes": None})
    with pytest.raises(ContractError, match="purposes must be an object"):
        TrustStore.from_mapping(
            {**document({HOST_KEY_ID: ["c2"]}), "purposes": [[HOST_KEY_ID, "c2"]]}
        )


# =========================================================================== one key, one id
def _twin_document() -> dict:
    """One public key filed twice: as the owner's (plans, C7) and as a host's (run records)."""
    return {
        "profile": "production",
        "label": "synthetic",
        "keys": {OWNER_KEY_ID: _b64(host_public_key()), HOST_KEY_ID: _b64(host_public_key())},
        "purposes": {OWNER_KEY_ID: ["c1", "c7"], HOST_KEY_ID: ["c2"]},
    }


def test_a_store_that_binds_purposes_holds_each_public_key_under_one_id():
    """REGRESSION. Filed under two ids, a host's key signed a plan with production trust."""
    with pytest.raises(ContractError, match="same public key"):
        TrustStore.from_mapping(_twin_document())
    with pytest.raises(ContractError, match="same public key"):
        TrustStore(
            {OWNER_KEY_ID: host_public_key(), HOST_KEY_ID: host_public_key()},
            profile="production",
            label="synthetic",
            purposes={OWNER_KEY_ID: ["c1", "c7"], HOST_KEY_ID: ["c2"]},
        )
    bound = store({HOST_KEY_ID: ["c2"]})
    with pytest.raises(ContractError, match="same public key"):
        bound.add(OWNER_KEY_ID, host_public_key(), purposes=["c1"])
    assert bound.key_ids() == (HOST_KEY_ID,), "a refused key changed the store"
    # The plan the twin would have let the host's seed sign is refused under the honest store.
    plan = EvaluationPlan.from_mapping(
        resigned(load_fixture("c1/simulation_final.expanded.json"), HOST_KEY_ID)
    )
    with pytest.raises(SignatureUnverifiable, match="not for 'c1'"):
        plan.verify_signature(bound)
    # PRESENCE CONTROL: two different keys, one per id, are the ordinary store.
    assert store({OWNER_KEY_ID: ["c1", "c7"], HOST_KEY_ID: ["c2"]}).key_ids() == tuple(
        sorted((HOST_KEY_ID, OWNER_KEY_ID))
    )


def test_a_store_that_binds_nothing_may_still_file_one_key_twice():
    """ABSENCE CONTROL. Without purposes there is no separation to bypass: as before."""
    document = {**_twin_document(), "profile": "development"}
    del document["purposes"]
    assert set(TrustStore.from_mapping(document).key_ids()) == {OWNER_KEY_ID, HOST_KEY_ID}


@pytest.mark.parametrize("bound", [True, False])
def test_a_key_id_is_added_once(bound):
    """Material and purposes are never changed in place, in a store that binds or one that
    does not."""
    held = (
        store({HOST_KEY_ID: ["c2"]})
        if bound
        else TrustStore({HOST_KEY_ID: host_public_key()}, profile="development", label="d")
    )
    with pytest.raises(ContractError, match="already in this store"):
        held.add(HOST_KEY_ID, dev_public_key(), purposes=["c1"] if bound else None)
    with pytest.raises(ContractError, match="already in this store"):
        held.add(HOST_KEY_ID, host_public_key(), purposes=["c2"] if bound else None)
    assert held.get(HOST_KEY_ID) == host_public_key()
    assert held.purposes_of(HOST_KEY_ID) == (("c2",) if bound else None)


@pytest.mark.parametrize(
    "text",
    [
        '{"profile":"production","label":"p","keys":{"k":"KEY"},"purposes":{"k":["c2"]},'
        '"purposes":{"k":["c1"]}}',
        '{"profile":"production","label":"p","keys":{"k":"KEY","k":"KEY"},"purposes":{"k":["c2"]}}',
        '{"profile":"production","label":"p","keys":{"k":"KEY"},"purposes":{"k":["c2"],"k":["c1"]}}',
        '{"profile":"production","label":NaN,"keys":{"k":"KEY"},"purposes":{"k":["c2"]}}',
    ],
)
def test_loading_a_store_refuses_a_member_named_twice(text, tmp_path):
    """The JSON parser keeps the last of two members: the store would trust what a reviewer of
    the first never read."""
    path = tmp_path / "trust_store.json"
    path.write_text(text.replace("KEY", _b64(host_public_key())), encoding="utf-8")
    with pytest.raises(ContractError):
        TrustStore.load(path)
    # PRESENCE CONTROL: the same store, each member once, loads.
    path.write_text(json.dumps(document({HOST_KEY_ID: ["c2"]})), encoding="utf-8")
    assert TrustStore.load(path).purposes_of(HOST_KEY_ID) == ("c2",)


@pytest.mark.parametrize("purpose", [["c7"], ("c7",), 7, b"c7"])
def test_a_purpose_that_is_not_a_name_is_refused_as_unverifiable(purpose):
    c7 = resigned(load_fixture("c7_hardware.json"), OWNER_KEY_ID)
    with pytest.raises(SignatureUnverifiable, match="is not a trust purpose"):
        verify_signed_object(c7, store({OWNER_KEY_ID: ["c7"]}), purpose=purpose)


# =========================================================================== verification
def test_a_run_record_key_cannot_sign_a_plan():
    """REGRESSION. The shipped Track 3 Final plan re-signed by a host's key."""
    plan = EvaluationPlan.from_mapping(
        resigned(load_fixture("c1/simulation_final.expanded.json"), HOST_KEY_ID)
    )
    final = store({OWNER_KEY_ID: ["c1", "c7"], HOST_KEY_ID: ["c2"]})
    with pytest.raises(SignatureUnverifiable, match=r"trusted for \['c2'\] only, not for 'c1'"):
        plan.verify_signature(final)
    # POSITIVE CONTROL: the identical document and key verify once the key is a plan key.
    assert plan.verify_signature(store({HOST_KEY_ID: ["c1"]})).purpose == "c1"


def test_a_run_record_key_cannot_sign_a_hardware_instance():
    """A C7 signed with the host's run-record key does not verify as a hardware instance."""
    c7 = resigned(load_fixture("c7_hardware.json"), HOST_KEY_ID)
    final = store({OWNER_KEY_ID: ["c1", "c7"], HOST_KEY_ID: ["c2"]})
    with pytest.raises(SignatureUnverifiable, match="not for 'c7'"):
        verify_signed_object(c7, final, purpose="c7")
    # POSITIVE CONTROL: the owner's C7 verifies for c7 under the same store.
    owner_c7 = resigned(load_fixture("c7_hardware.json"), OWNER_KEY_ID)
    assert verify_signed_object(owner_c7, final, purpose="c7").key_id == OWNER_KEY_ID


def test_a_plan_key_cannot_attest_a_run_record():
    final = store({OWNER_KEY_ID: ["c1", "c7", "archive"], HOST_KEY_ID: ["c2"]})
    with pytest.raises(SignatureUnverifiable, match="not for 'c2'"):
        resigned_record(OWNER_KEY_ID).verify_attestation(final)
    assert resigned_record(HOST_KEY_ID).verify_attestation(final).purpose == "c2"


def test_a_store_that_binds_purposes_refuses_a_verification_that_names_none():
    c7 = resigned(load_fixture("c7_hardware.json"), OWNER_KEY_ID)
    final = store({OWNER_KEY_ID: ["c7"]})
    with pytest.raises(SignatureUnverifiable, match="named none"):
        verify_signed_object(c7, final)
    assert verify_signed_object(c7, final, purpose="c7").purpose == "c7"


@pytest.mark.parametrize("purpose", ["c3", "C7", "", "any"])
def test_an_unknown_purpose_is_refused_rather_than_read_as_any(purpose):
    c7 = resigned(load_fixture("c7_hardware.json"), OWNER_KEY_ID)
    with pytest.raises(SignatureUnverifiable, match="is not a trust purpose"):
        verify_signed_object(c7, store({OWNER_KEY_ID: ["c7"]}), purpose=purpose)
    # Refused against a store that binds nothing too: a typo is never a pass.
    with pytest.raises(SignatureUnverifiable, match="is not a trust purpose"):
        verify_signed_object(c7, dev_trust_store(), purpose=purpose, require_production_trust=False)


def test_a_development_store_that_binds_purposes_is_held_to_them():
    bound = store({HOST_KEY_ID: ["c2"]}, profile="development")
    plan = EvaluationPlan.from_mapping(
        resigned(load_fixture("c1/simulation_final.expanded.json"), HOST_KEY_ID)
    )
    with pytest.raises(SignatureUnverifiable, match="not for 'c1'"):
        plan.verify_signature(bound, require_production_trust=False)
    assert (
        resigned_record(HOST_KEY_ID)
        .verify_attestation(bound, require_production_trust=False)
        .purpose
        == "c2"
    )


def test_a_store_edited_into_production_after_it_was_built_is_refused():
    """Defence in depth: a development store whose profile is overwritten binds nothing."""
    edited = TrustStore.from_mapping(document(None, profile="development"))
    edited.profile = "production"
    plan = EvaluationPlan.from_mapping(
        resigned(load_fixture("c1/simulation_final.expanded.json"), OWNER_KEY_ID)
    )
    with pytest.raises(SignatureUnverifiable, match="binds no key to a purpose"):
        plan.verify_signature(edited)


# =========================================================================== signing backend
class _FakeCompiledKey:
    """Stands in for `cryptography`'s private key; computes with the RFC 8032 code and counts."""

    calls: list[str] = []

    def __init__(self, seed: bytes) -> None:
        self._seed = seed

    def sign(self, message: bytes) -> bytes:
        _FakeCompiledKey.calls.append("sign")
        return _ed25519.sign(self._seed, message)

    def public_bytes(self) -> bytes:
        _FakeCompiledKey.calls.append("public_bytes")
        return _ed25519.public_key_from_seed(self._seed)


def test_signing_uses_the_compiled_primitive_when_it_is_installed(monkeypatch):
    """PRESENCE CONTROL: the secret-key operation goes to `cryptography`."""
    _FakeCompiledKey.calls = []
    monkeypatch.setattr(signing, "_compiled_private_key", _FakeCompiledKey)
    envelope = sign_payload(
        {"k": 1}, seed=DEV_SEED, key_id=DEV_KEY_ID, signed_at=SIGNED_AT, require_constant_time=True
    )
    assert _FakeCompiledKey.calls == ["sign"]
    # Same signature either way: Ed25519 is deterministic.
    monkeypatch.setattr(signing, "_compiled_private_key", lambda seed: None)
    assert sign_payload({"k": 1}, seed=DEV_SEED, key_id=DEV_KEY_ID, signed_at=SIGNED_AT) == envelope


def test_a_production_signer_refuses_the_pure_python_fallback(monkeypatch):
    monkeypatch.setattr(signing, "_compiled_private_key", lambda seed: None)
    with pytest.raises(ContractError, match="not constant time"):
        sign_payload(
            {"k": 1},
            seed=DEV_SEED,
            key_id=DEV_KEY_ID,
            signed_at=SIGNED_AT,
            require_constant_time=True,
        )
    with pytest.raises(ContractError, match="not constant time"):
        derive_public_key(DEV_SEED, require_constant_time=True)
    # Without the requirement the fallback still signs, so fixtures and tests are unchanged.
    envelope = sign_payload({"k": 1}, seed=DEV_SEED, key_id=DEV_KEY_ID, signed_at=SIGNED_AT)
    assert (
        verify_signed({"k": 1}, envelope, dev_trust_store(), require_production_trust=False).key_id
        == DEV_KEY_ID
    )


def test_deriving_the_public_key_uses_the_compiled_primitive_when_it_is_installed(monkeypatch):
    _FakeCompiledKey.calls = []
    monkeypatch.setattr(signing, "_compiled_private_key", _FakeCompiledKey)
    assert derive_public_key(RFC8032_SEED, require_constant_time=True) == RFC8032_PUBLIC
    assert _FakeCompiledKey.calls == ["public_bytes"]
    monkeypatch.setattr(signing, "_compiled_private_key", lambda seed: None)
    assert derive_public_key(RFC8032_SEED) == RFC8032_PUBLIC


@pytest.mark.parametrize("seed", [b"", b"short", b"x" * 33, "x" * 32])
def test_a_seed_that_is_not_32_bytes_is_refused_by_both_paths(seed, monkeypatch):
    for compiled in (_FakeCompiledKey, lambda s: None):
        monkeypatch.setattr(signing, "_compiled_private_key", compiled)
        with pytest.raises(ValueError, match="exactly 32 bytes"):
            sign_payload({"k": 1}, seed=seed, key_id=DEV_KEY_ID, signed_at=SIGNED_AT)
        with pytest.raises(ValueError, match="exactly 32 bytes"):
            derive_public_key(seed)


def test_the_installed_backend_reproduces_rfc8032_and_honours_the_requirement():
    """Whatever this host has installed, no stubs: the live backend signs the published vector,
    and `require_constant_time` succeeds exactly when `cryptography` is importable."""
    compiled = importlib.util.find_spec("cryptography") is not None
    assert (
        signing._raw_sign(RFC8032_SEED, RFC8032_MESSAGE, require_constant_time=False)
        == RFC8032_SIGNATURE
    )
    assert derive_public_key(RFC8032_SEED) == RFC8032_PUBLIC
    assert (signing._compiled_private_key(RFC8032_SEED) is not None) is compiled
    if compiled:
        assert (
            signing._raw_sign(RFC8032_SEED, RFC8032_MESSAGE, require_constant_time=True)
            == RFC8032_SIGNATURE
        )
        assert derive_public_key(RFC8032_SEED, require_constant_time=True) == RFC8032_PUBLIC
    else:
        with pytest.raises(ContractError, match="not constant time"):
            signing._raw_sign(RFC8032_SEED, RFC8032_MESSAGE, require_constant_time=True)
