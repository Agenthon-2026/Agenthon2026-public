"""`digest_member_set`: the digest a repeat has to reproduce, computed one way (Agenthon2026#116).

The whole-tree byte digest cannot be reproduced by an honest Track 3 run because the telemetry
sidecar carries a real wall clock. The repeat digest is therefore taken over the deterministic
members only, and it has to be the SAME function on the producer (the Runner, per repeat) and the
consumer (the scorer, over the retained tree) -- which is why it lives here and not in a track.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from qfbench2_common.contracts import ContractError, digest_json
from qfbench2_common.contracts.digest import digest_member_set, digest_members

MEMBERS = ("trace.parquet", "message_trace.parquet")


def _tree(root: pathlib.Path, wall_clock: float, *, message_trace: bool = True) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "trace.parquet").write_bytes(b"PAR1" + b"\x00" * 64 + b"PAR1")
    if message_trace:
        (root / "message_trace.parquet").write_bytes(b"PAR1" + b"\x01" * 16 + b"PAR1")
    (root / "events.json").write_text(
        '{"scenario_id": "s", "n_events": 3, "seed": 1, "wall_clock_sec": %r}' % wall_clock
    )
    return root


def test_two_honest_repeats_that_differ_only_in_wall_clock_digest_alike(tmp_path):
    """THE property: one microsecond of honest measurement must not change the digest."""
    a = _tree(tmp_path / "a", 1.000000)
    b = _tree(tmp_path / "b", 1.000001)
    assert (a / "events.json").read_bytes() != (b / "events.json").read_bytes()
    assert digest_member_set(a, MEMBERS) == digest_member_set(b, MEMBERS)


def test_a_different_trace_digests_differently(tmp_path):
    """POSITIVE CONTROL: the digest still sees the output -- the alternating fast-invalid /
    slow-valid attack is what the repeat check exists to close."""
    a = _tree(tmp_path / "a", 1.0)
    b = _tree(tmp_path / "b", 1.0)
    (b / "trace.parquet").write_bytes(b"PAR1" + b"\x00" * 63 + b"\xff" + b"PAR1")
    assert digest_member_set(a, MEMBERS) != digest_member_set(b, MEMBERS)


def test_the_preimage_is_rule_0_2_not_a_private_scheme(tmp_path):
    """An independent implementation must be able to reproduce it from the rule alone."""
    root = _tree(tmp_path / "t", 1.0)
    found = digest_members(root, MEMBERS)
    expected = digest_json([{"path": rel, "sha256": hexd} for rel, hexd in sorted(found.items())])
    assert digest_member_set(root, MEMBERS) == expected
    assert set(found) == set(MEMBERS)


def test_an_optional_member_absent_is_a_different_set_not_an_error(tmp_path):
    with_mt = _tree(tmp_path / "a", 1.0)
    without = _tree(tmp_path / "b", 1.0, message_trace=False)
    assert digest_members(without, MEMBERS).keys() == {"trace.parquet"}
    assert digest_member_set(with_mt, MEMBERS) != digest_member_set(without, MEMBERS)


def test_a_tree_with_no_member_present_is_refused(tmp_path):
    """An empty set would let one empty tree 'reproduce' another."""
    root = tmp_path / "empty"
    root.mkdir()
    (root / "events.json").write_text("{}")
    with pytest.raises(ContractError, match="no member of the digest set"):
        digest_member_set(root, MEMBERS)


def test_a_symlinked_member_is_refused_not_followed(tmp_path):
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"PAR1 elsewhere PAR1")
    root = _tree(tmp_path / "t", 1.0)
    (root / "trace.parquet").unlink()
    os.symlink(outside, root / "trace.parquet")
    with pytest.raises(ContractError, match="symlink"):
        digest_members(root, MEMBERS)


def test_a_symlinked_directory_on_the_path_is_refused(tmp_path):
    real = _tree(tmp_path / "real", 1.0)
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(real, root / "sub")
    with pytest.raises(ContractError, match="symlink"):
        digest_members(root, ("sub/trace.parquet",))


def test_a_directory_where_a_file_is_expected_is_refused(tmp_path):
    root = tmp_path / "t"
    (root / "trace.parquet").mkdir(parents=True)
    with pytest.raises(ContractError, match="not a regular file"):
        digest_members(root, MEMBERS)


@pytest.mark.parametrize("bad", ["/abs/trace.parquet", "../trace.parquet", "a\\b", ""])
def test_member_paths_follow_the_tree_path_grammar(tmp_path, bad):
    root = _tree(tmp_path / "t", 1.0)
    with pytest.raises(ContractError):
        digest_members(root, (bad,))


def test_batch_layout_is_just_more_members(tmp_path):
    """A batch unit names its members under each sub; the same function, the same rule."""
    root = tmp_path / "batch"
    _tree(root / "sub_00", 1.0)
    _tree(root / "sub_01", 2.0)
    members = tuple(f"{sub}/{m}" for sub in ("sub_00", "sub_01") for m in MEMBERS)
    found = digest_members(root, members)
    assert set(found) == set(members)
    again = tmp_path / "batch2"
    _tree(again / "sub_00", 9.0)
    _tree(again / "sub_01", 8.0)
    assert digest_member_set(root, members) == digest_member_set(again, members)
