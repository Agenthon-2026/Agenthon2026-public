"""The team claim: derived team_id, the claim file, the zip, and a key that is written nowhere else."""

from __future__ import annotations

import getpass
import hashlib
import io
import json
import os
import sys
import warnings
import zipfile

import pytest

from qfbench2_common import cli, team_claim
from qfbench2_common.contracts import SubmissionDescriptor
from qfbench2_common.contracts.fixtures import load_fixture

TEAM_KEY = "SYNTHETIC-team-password-never-log"
# The organizer repository (agenthon2026-codabench, tests/test_registered_team_admission.py)
# asserts this same value for the same inputs. Change one, and the other test fails.
ALIAS_VECTOR = (
    "team-" + hashlib.sha256(b"agenthon2026-team-alias:11:" + TEAM_KEY.encode()).hexdigest()[:32]
)


def body() -> dict:
    c5 = load_fixture("c5/coding_dev.json")
    return {k: v for k, v in c5.items() if k not in ("team_id", "descriptor_digest")}


def test_alias_is_the_published_formula():
    alias = team_claim.derive_team_alias(11, TEAM_KEY)
    assert alias == ALIAS_VECTOR
    assert team_claim.ALIAS_RE.match(alias)
    assert team_claim.derive_team_alias(11, TEAM_KEY) == alias
    assert team_claim.derive_team_alias(12, TEAM_KEY) != alias
    assert team_claim.derive_team_alias(11, TEAM_KEY + " ") != alias
    assert team_claim.derive_team_alias(11, TEAM_KEY.lower()) != alias
    assert TEAM_KEY not in alias


@pytest.mark.parametrize("number", ["11", 0, -1, True, 2**63, 11.0, None])
def test_alias_refuses_a_bad_team_number(number):
    with pytest.raises(team_claim.TeamClaimError) as caught:
        team_claim.derive_team_alias(number, TEAM_KEY)
    assert TEAM_KEY not in str(caught.value)


@pytest.mark.parametrize(
    "key",
    [11, b"bytes", "", "short", "x" * 257, "tab\tin-key", "new\nline-key", "del\x7fchar-key", None],
)
def test_alias_refuses_a_bad_key_without_echoing_it(key):
    with pytest.raises(team_claim.TeamClaimError) as caught:
        team_claim.derive_team_alias(11, key)
    if isinstance(key, str) and key:
        assert key not in str(caught.value)


def test_claim_bytes_are_the_exact_published_shape():
    raw = team_claim.build_team_claim(11, TEAM_KEY)
    assert json.loads(raw) == {"schema_version": "1.0", "site_team_id": 11, "team_key": TEAM_KEY}
    assert set(json.loads(raw)) == {"schema_version", "site_team_id", "team_key"}
    assert len(raw) <= 1024
    assert len(team_claim.build_team_claim(11, "é" * 256)) <= 1024


def test_seal_for_team_sets_the_alias_and_validates_the_descriptor():
    sealed = team_claim.seal_for_team(body(), 11, TEAM_KEY)
    assert sealed["team_id"] == ALIAS_VECTOR
    assert SubmissionDescriptor.from_mapping(sealed).team_id == ALIAS_VECTOR
    # Resealing an already-sealed descriptor with the right team_id is a no-op.
    assert team_claim.seal_for_team(sealed, 11, TEAM_KEY) == sealed
    # A stale digest is replaced, never trusted.
    stale = dict(sealed, descriptor_digest="sha256:" + "0" * 64)
    assert team_claim.seal_for_team(stale, 11, TEAM_KEY) == sealed


def test_seal_for_team_refuses_a_disagreeing_team_id():
    with pytest.raises(team_claim.TeamClaimError, match="disagrees"):
        team_claim.seal_for_team(dict(body(), team_id="team-example-0001"), 11, TEAM_KEY)
    with pytest.raises(team_claim.TeamClaimError, match="disagrees"):
        team_claim.seal_for_team(dict(body(), team_id=ALIAS_VECTOR), 12, TEAM_KEY)


def test_seal_for_team_refuses_an_invalid_descriptor_without_echoing_the_key():
    broken = body()
    del broken["models"]
    with pytest.raises(team_claim.TeamClaimError) as caught:
        team_claim.seal_for_team(broken, 11, TEAM_KEY)
    assert "C5" in str(caught.value) and TEAM_KEY not in str(caught.value)
    with pytest.raises(team_claim.TeamClaimError):
        team_claim.seal_for_team([], 11, TEAM_KEY)


def test_pack_writes_exactly_two_members_deterministically(tmp_path):
    out = tmp_path / "submission.zip"
    assert team_claim.pack_submission(body(), 11, TEAM_KEY, out) == ALIAS_VECTOR
    assert out.stat().st_mode & 0o777 == 0o600
    with zipfile.ZipFile(out) as archive:
        assert [e.filename for e in archive.infolist()] == ["submission.json", "team-claim.json"]
        descriptor = json.loads(archive.read("submission.json"))
        claim = json.loads(archive.read("team-claim.json"))
        assert all(
            not e.is_dir() and e.compress_type == zipfile.ZIP_STORED for e in archive.infolist()
        )
    assert SubmissionDescriptor.from_mapping(descriptor).team_id == ALIAS_VECTOR
    assert claim == {"schema_version": "1.0", "site_team_id": 11, "team_key": TEAM_KEY}
    first = out.read_bytes()
    team_claim.pack_submission(body(), 11, TEAM_KEY, out)
    assert out.read_bytes() == first
    # The key appears in the zip exactly once, inside the claim member, and nowhere else.
    assert first.count(TEAM_KEY.encode()) == 1
    assert TEAM_KEY.encode() not in json.dumps(descriptor).encode()


def test_pack_refuses_a_symlinked_or_non_regular_output(tmp_path):
    target = tmp_path / "elsewhere.zip"
    target.write_bytes(b"")
    link = tmp_path / "submission.zip"
    link.symlink_to(target)
    with pytest.raises(team_claim.TeamClaimError):
        team_claim.pack_submission(body(), 11, TEAM_KEY, link)
    assert target.read_bytes() == b""


def test_key_file_must_be_private_regular_and_the_key_alone(tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text(TEAM_KEY + "\n")
    key_file.chmod(0o600)
    assert team_claim.read_team_key_file(key_file) == TEAM_KEY
    key_file.write_text(TEAM_KEY + "\r\n")
    assert team_claim.read_team_key_file(key_file) == TEAM_KEY
    key_file.write_text(TEAM_KEY)
    assert team_claim.read_team_key_file(key_file) == TEAM_KEY
    key_file.write_text(" " + TEAM_KEY + " ")
    assert team_claim.read_team_key_file(key_file) == " " + TEAM_KEY + " "
    key_file.write_text(TEAM_KEY + "\n\n")
    with pytest.raises(team_claim.TeamClaimError):
        team_claim.read_team_key_file(key_file)
    key_file.write_text(TEAM_KEY)
    key_file.chmod(0o640)
    with pytest.raises(team_claim.TeamClaimError, match="chmod 600"):
        team_claim.read_team_key_file(key_file)
    key_file.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(key_file)
    with pytest.raises(team_claim.TeamClaimError, match="link"):
        team_claim.read_team_key_file(link)
    with pytest.raises(team_claim.TeamClaimError):
        team_claim.read_team_key_file(tmp_path / "missing")
    key_file.write_bytes(b"")
    with pytest.raises(team_claim.TeamClaimError):
        team_claim.read_team_key_file(key_file)
    key_file.write_bytes(b"\xff" * 20)
    with pytest.raises(team_claim.TeamClaimError, match="UTF-8"):
        team_claim.read_team_key_file(key_file)
    with pytest.raises(team_claim.TeamClaimError):
        team_claim.read_team_key_file(tmp_path)


def key_file(tmp_path):
    path = tmp_path / "team.key"
    path.write_text(TEAM_KEY + "\n")
    path.chmod(0o600)
    return path


def test_cli_alias_and_pack_from_a_key_file(tmp_path, capsys):
    descriptor = tmp_path / "submission.json"
    descriptor.write_text(json.dumps(body()))
    out = tmp_path / "submission.zip"
    assert (
        cli.main(
            [
                "submission",
                "alias",
                "--team-number",
                "11",
                "--team-key-file",
                str(key_file(tmp_path)),
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == ALIAS_VECTOR
    assert (
        cli.main(
            [
                "submission",
                "pack",
                "--descriptor",
                str(descriptor),
                "--team-number",
                "11",
                "--team-key-file",
                str(key_file(tmp_path)),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert ALIAS_VECTOR in captured.out and TEAM_KEY not in captured.out + captured.err
    with zipfile.ZipFile(out) as archive:
        assert sorted(archive.namelist()) == ["submission.json", "team-claim.json"]
    # An existing output is not replaced without --force.
    assert (
        cli.main(
            [
                "submission",
                "pack",
                "--descriptor",
                str(descriptor),
                "--team-number",
                "11",
                "--team-key-file",
                str(key_file(tmp_path)),
                "--out",
                str(out),
            ]
        )
        == 1
    )
    assert "--force" in capsys.readouterr().err
    assert (
        cli.main(
            [
                "submission",
                "pack",
                "--descriptor",
                str(descriptor),
                "--team-number",
                "11",
                "--team-key-file",
                str(key_file(tmp_path)),
                "--out",
                str(out),
                "--force",
            ]
        )
        == 0
    )


def test_cli_pack_refuses_a_disagreeing_team_id_and_never_prints_the_key(tmp_path, capsys):
    descriptor = tmp_path / "submission.json"
    descriptor.write_text(json.dumps(dict(body(), team_id="team-example-0001")))
    out = tmp_path / "submission.zip"
    assert (
        cli.main(
            [
                "submission",
                "pack",
                "--descriptor",
                str(descriptor),
                "--team-number",
                "11",
                "--team-key-file",
                str(key_file(tmp_path)),
                "--out",
                str(out),
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "disagrees" in captured.err and TEAM_KEY not in captured.out + captured.err
    assert not out.exists()
    descriptor.write_text("not json")
    assert (
        cli.main(
            [
                "submission",
                "pack",
                "--descriptor",
                str(descriptor),
                "--team-number",
                "11",
                "--team-key-file",
                str(key_file(tmp_path)),
                "--out",
                str(out),
            ]
        )
        == 1
    )
    assert "JSON" in capsys.readouterr().err


def test_cli_hidden_prompt_is_used_only_on_a_terminal(tmp_path, monkeypatch, capsys):
    prompted = []
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(getpass, "getpass", lambda prompt: prompted.append(prompt) or TEAM_KEY)
    assert cli.main(["submission", "alias", "--team-number", "11"]) == 0
    assert capsys.readouterr().out.strip() == ALIAS_VECTOR and prompted == ["Team Key (hidden): "]
    # No terminal: refused rather than echoed.
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert cli.main(["submission", "alias", "--team-number", "11"]) == 1
    captured = capsys.readouterr()
    assert "--team-key-file" in captured.err and TEAM_KEY not in captured.out + captured.err

    # A terminal that cannot disable echo: getpass warns, and the warning is a refusal.
    def echoing(prompt):
        warnings.warn("Can not control echo on the terminal.", getpass.GetPassWarning)
        return TEAM_KEY

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(getpass, "getpass", echoing)
    assert cli.main(["submission", "alias", "--team-number", "11"]) == 1
    captured = capsys.readouterr()
    assert "cannot hide input" in captured.err and TEAM_KEY not in captured.out + captured.err


@pytest.mark.parametrize(
    "argv",
    [
        ["submission", "alias", "--team-number", "11", "--team-key", TEAM_KEY],
        ["submission", "alias", "--team-number", "11", "--team-key=" + TEAM_KEY],
        ["submission", "pack", "--descriptor", "x", "--team-number", "11", "--team-key", TEAM_KEY],
        ["submission", "alias", "--team-number", "11", "--team-ke", TEAM_KEY],
        ["submission", "alias", "--team-number", "11", "--team-k=" + TEAM_KEY],
        # Round-1 review: spellings the prefix guard does not see must not reach
        # argparse's "unrecognized arguments" echo either.
        ["submission", "alias", "--team-number", "11", "-team-key", TEAM_KEY],
        ["submission", "alias", "--team-number", "11", "--Team-Key", TEAM_KEY],
        ["submission", "alias", "--team-number", "11", "--key", TEAM_KEY],
        ["submission", "alias", "--team-number", "11", TEAM_KEY],
        ["submission", "alias", "--team-number", TEAM_KEY],
        ["submission", TEAM_KEY, "--team-number", "11"],
        ["submission", "pack", "--descriptor", "x", "--team-number", "11", "--key", TEAM_KEY],
    ],
)
def test_cli_never_accepts_or_echoes_the_key_as_an_argument(argv, capsys):
    # Neither argparse's prefix matching (`--team-key` -> `--team-key-file`), its
    # "unrecognized arguments" / "invalid ... value" / "invalid choice" messages, nor
    # a SystemExit from inside parse_args may see or carry the value.
    assert cli.main(argv) == cli.EXIT_USAGE
    captured = capsys.readouterr()
    assert "never a command-line argument" in captured.err
    assert TEAM_KEY not in captured.out + captured.err


def test_cli_usage_errors_that_name_only_the_parsers_own_options_still_explain(capsys):
    assert cli.main(["submission", "alias"]) == cli.EXIT_USAGE
    assert "the following arguments are required: --team-number" in capsys.readouterr().err
    assert cli.main(["submission", "alias", "--team-number"]) == cli.EXIT_USAGE
    assert "argument --team-number: expected one argument" in capsys.readouterr().err


def test_pack_output_is_what_the_organizer_side_reads(tmp_path):
    """The organizer's bounded reader wants a plain single-disk zip: EOCD, no ZIP64, no dirs."""
    out = tmp_path / "submission.zip"
    team_claim.pack_submission(body(), 11, TEAM_KEY, out)
    raw = out.read_bytes()
    assert raw.rfind(b"PK\x05\x06") > 0 and b"PK\x06\x06" not in raw and b"PK\x06\x07" not in raw
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for entry in archive.infolist():
            assert not entry.flag_bits & 1 and not entry.is_dir()
            assert (entry.external_attr >> 16) & 0o170000 == 0o100000
    assert os.path.getsize(out) < 8192
