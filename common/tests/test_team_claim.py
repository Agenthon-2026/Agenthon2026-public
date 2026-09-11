"""The team claim: derived team_id, the proof file, the zip, and a key written nowhere at all."""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import io
import json
import os
import stat
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
DIGEST_VECTOR = "a" * 64
# The published proof vector. The organizer repository asserts the same value for the same
# inputs (agenthon2026-codabench, tests/test_registered_team_admission.py); change one end
# and the other end's test suite fails.
PROOF_VECTOR = hmac.new(
    hashlib.sha256(b"agenthon2026-team-proof-key:v2:" + TEAM_KEY.encode()).digest(),
    b"agenthon2026-team-claim:v2:11:" + DIGEST_VECTOR.encode(),
    hashlib.sha256,
).hexdigest()


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
    raw = team_claim.build_team_claim(11, TEAM_KEY, DIGEST_VECTOR)
    assert json.loads(raw) == {
        "schema_version": "2.0",
        "site_team_id": 11,
        "descriptor_sha256": DIGEST_VECTOR,
        "proof": PROOF_VECTOR,
    }
    assert len(raw) <= 1024
    assert len(team_claim.build_team_claim(11, "é" * 256, DIGEST_VECTOR)) <= 1024
    # The claim carries no secret: that is the whole reason it is safe in a public zip.
    assert TEAM_KEY.encode() not in raw


def test_proof_is_the_published_formula_and_binds_to_one_descriptor():
    assert team_claim.team_claim_proof(11, TEAM_KEY, DIGEST_VECTOR) == PROOF_VECTOR
    # Nothing an attacker can vary is free: team number, key and descriptor all bind.
    assert team_claim.team_claim_proof(12, TEAM_KEY, DIGEST_VECTOR) != PROOF_VECTOR
    assert team_claim.team_claim_proof(11, TEAM_KEY + " ", DIGEST_VECTOR) != PROOF_VECTOR
    assert team_claim.team_claim_proof(11, TEAM_KEY, "b" * 64) != PROOF_VECTOR
    # The proof is not the fingerprint the organizer stores, and not the alias.
    assert PROOF_VECTOR != hashlib.sha256(TEAM_KEY.encode()).hexdigest()
    assert PROOF_VECTOR not in ALIAS_VECTOR


@pytest.mark.parametrize(
    "digest",
    [
        "",
        "A" * 64,
        "a" * 63,
        "a" * 65,
        "g" * 64,
        11,
        None,
        b"a" * 64,
        # A trailing newline is the one an anchored `^...$` used to let through, because `$`
        # also matches immediately before it. The organizer's reader uses `fullmatch` and
        # refuses it, so accepting it here would have built a claim the intake calls
        # `claim_malformed` -- a held upload with no participant-visible cause.
        "a" * 64 + "\n",
        "a" * 64 + "\r\n",
        "\n" + "a" * 64,
        "a" * 64 + "\n" + "b" * 64,
    ],
)
def test_proof_refuses_anything_that_is_not_a_lowercase_hex_digest(digest):
    with pytest.raises(team_claim.TeamClaimError):
        team_claim.team_claim_proof(11, TEAM_KEY, digest)


def test_the_digest_pattern_refuses_a_trailing_newline_under_both_spellings():
    """`HEX64_RE` is anchored with `\\A`/`\\Z`, so `.match` and `.fullmatch` agree.

    Both spellings are asserted because the module used `.match` against a `^...$` pattern,
    and `$` matches before a trailing newline: `"a" * 64 + "\\n"` was accepted here and
    refused by the organizer, whose `parse_team_claim` uses `fullmatch`. Pinning only the
    call site would leave the next reader free to reintroduce `.match` on a `$` pattern.
    """
    trailing = "a" * 64 + "\n"
    assert team_claim.HEX64_RE.fullmatch(trailing) is None
    assert team_claim.HEX64_RE.match(trailing) is None
    assert team_claim.ALIAS_RE.fullmatch(ALIAS_VECTOR + "\n") is None
    assert team_claim.ALIAS_RE.match(ALIAS_VECTOR + "\n") is None
    # ...and the values that must still be accepted are.
    assert team_claim.HEX64_RE.fullmatch(DIGEST_VECTOR) is not None
    assert team_claim.HEX64_RE.match(DIGEST_VECTOR) is not None
    assert team_claim.ALIAS_RE.fullmatch(ALIAS_VECTOR) is not None
    assert team_claim.ALIAS_RE.match(ALIAS_VECTOR) is not None


def test_descriptor_digest_is_over_the_exact_member_bytes(tmp_path):
    out = tmp_path / "submission.zip"
    team_claim.pack_submission(body(), 11, TEAM_KEY, out)
    with zipfile.ZipFile(out) as archive:
        member = archive.read("submission.json")
        claim = json.loads(archive.read("team-claim.json"))
    assert claim["descriptor_sha256"] == hashlib.sha256(member).hexdigest()
    assert claim["proof"] == team_claim.team_claim_proof(11, TEAM_KEY, claim["descriptor_sha256"])


def test_a_claim_lifted_from_one_zip_does_not_verify_for_another(tmp_path):
    """The point of binding the proof: a copied claim is worthless for a different upload."""
    other = body()
    other["image"] = dict(other["image"], repository="team-example/qfb2-solver-v2")
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    team_claim.pack_submission(body(), 11, TEAM_KEY, first)
    team_claim.pack_submission(other, 11, TEAM_KEY, second)
    claims, digests = [], []
    for path in (first, second):
        with zipfile.ZipFile(path) as archive:
            claims.append(json.loads(archive.read("team-claim.json")))
            digests.append(hashlib.sha256(archive.read("submission.json")).hexdigest())
    assert digests[0] != digests[1]
    assert claims[0]["proof"] != claims[1]["proof"]
    # The stolen proof does not verify against the other upload's descriptor.
    assert claims[0]["proof"] != team_claim.team_claim_proof(11, TEAM_KEY, digests[1])


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
    assert set(claim) == {"schema_version", "site_team_id", "descriptor_sha256", "proof"}
    assert claim["schema_version"] == "2.0" and claim["site_team_id"] == 11
    first = out.read_bytes()
    team_claim.pack_submission(body(), 11, TEAM_KEY, out)
    assert out.read_bytes() == first
    # The key appears nowhere in the zip. The zip is downloadable by anyone once the run is
    # placed on a leaderboard, so this assertion is the whole contract.
    assert TEAM_KEY.encode() not in first
    assert TEAM_KEY.encode() not in json.dumps(descriptor).encode()


def test_pack_refuses_a_symlinked_or_non_regular_output(tmp_path):
    target = tmp_path / "elsewhere.zip"
    target.write_bytes(b"")
    link = tmp_path / "submission.zip"
    link.symlink_to(target)
    with pytest.raises(team_claim.TeamClaimError):
        team_claim.pack_submission(body(), 11, TEAM_KEY, link)
    assert target.read_bytes() == b""


def test_pack_never_reuses_a_pre_existing_world_readable_file(tmp_path):
    """A reader holding the old file open (or another link) never sees the new archive."""
    out = tmp_path / "submission.zip"
    out.write_bytes(b"OLD-WORLD-READABLE")
    out.chmod(0o644)
    other_link = tmp_path / "hard-link-to-old.zip"
    os.link(out, other_link)
    with out.open("rb") as already_open:
        team_claim.pack_submission(body(), 11, TEAM_KEY, out)
        assert already_open.read() == b"OLD-WORLD-READABLE"
    assert other_link.read_bytes() == b"OLD-WORLD-READABLE"
    assert stat.S_IMODE(other_link.stat().st_mode) == 0o644
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert not os.path.samefile(out, other_link)
    fresh = out.read_bytes()
    assert TEAM_KEY.encode() not in fresh and b"OLD" not in fresh


def test_pack_output_is_0600_before_the_first_byte(tmp_path, monkeypatch):
    """The mode is checked from inside write(): no byte lands in a wider-than-0600 file."""
    out = tmp_path / "submission.zip"
    out.write_bytes(b"old")
    out.chmod(0o666)
    modes_at_write = []

    class Raw(io.FileIO):
        def write(self, data):
            modes_at_write.append(stat.S_IMODE(os.fstat(self.fileno()).st_mode))
            return super().write(data)

    monkeypatch.setattr(team_claim.os, "fdopen", lambda fd, mode="r", *a, **k: Raw(fd, mode))
    previous = os.umask(0o000)  # the widest umask: only an explicit mode can make it 0600
    try:
        team_claim.pack_submission(body(), 11, TEAM_KEY, out)
    finally:
        os.umask(previous)
    assert modes_at_write and all(mode == 0o600 for mode in modes_at_write)
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert TEAM_KEY.encode() not in out.read_bytes()


def test_pack_refuses_an_unwritable_output_without_naming_the_key(tmp_path):
    out = tmp_path / "missing-directory" / "submission.zip"
    with pytest.raises(team_claim.TeamClaimError) as caught:
        team_claim.pack_submission(body(), 11, TEAM_KEY, out)
    assert TEAM_KEY not in str(caught.value)
    assert not out.exists()


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


# --------------------------------------------------------------------------------------
# What the published zip does and does not give away.
#
# The premise, measured on the platform on 2026-09-10: a submission zip is downloadable by
# anyone, with no credential of any kind, once its run is placed on a leaderboard -- and the
# leaderboard rule places every team's best run there automatically. So every byte these two
# tests inspect should be read as "published to the whole internet".
# --------------------------------------------------------------------------------------


def _values(zip_path) -> list:
    """Every scalar the archive publishes: both members' JSON leaves, plus the member names."""
    out = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                out.append(key)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        else:
            out.append(node)

    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            out.append(name)
            walk(json.loads(archive.read(name)))
    return out


def test_the_zip_publishes_no_value_the_team_key_can_be_read_out_of(tmp_path):
    """No value in the archive is the key, or any stored/replayable handle on it.

    This is the assertion schema 2.0 exists to make, so it is made over every scalar in the
    archive rather than over a substring of the raw bytes: a `assert KEY not in raw` catches
    only a verbatim copy, and every interesting failure here -- shipping the fingerprint, the
    HMAC key, a base64 of the key -- would sail past it.

    The battery below is every value an implementation might plausibly have reached for, and
    in particular the two that the rejected designs would have shipped:

    * `sha256(key)` IS `key_fingerprint`, the value the organizer's private registry stores and
      compares. Publishing it would make a public zip equivalent to a registry-row disclosure
      and would let the reader claim the team for as long as the key stands.
    * `proof_key` is the HMAC key. Publishing it would let the reader mint a valid proof for
      any descriptor, which is exactly the replay the descriptor binding is there to stop.
    """
    out = tmp_path / "submission.zip"
    team_claim.pack_submission(body(), 11, TEAM_KEY, out)
    raw = out.read_bytes()
    key = TEAM_KEY.encode()

    forbidden = {
        TEAM_KEY,
        hashlib.sha256(key).hexdigest(),  # = key_fingerprint
        hashlib.sha256(b"agenthon2026-team-proof-key:v2:" + key).hexdigest(),  # = proof_key
        hashlib.sha1(key).hexdigest(),  # noqa: S324 - a value under test, not a security choice
        hashlib.md5(key).hexdigest(),  # noqa: S324 - likewise
        hashlib.sha512(key).hexdigest(),
        base64.b64encode(key).decode(),
        key.hex(),
        TEAM_KEY[::-1],
    }
    published = _values(out)
    for value in published:
        assert value not in forbidden, f"the archive publishes a handle on the Team Key: {value!r}"
    for value in forbidden:
        assert value.encode() not in raw, f"the raw archive bytes carry {value!r}"

    # And the one value that IS published under the key verifies for this descriptor only --
    # the property that makes it safe to publish at all.
    with zipfile.ZipFile(out) as archive:
        claim = json.loads(archive.read(team_claim.TEAM_CLAIM_FILE))
        member = archive.read("submission.json")
    assert claim["descriptor_sha256"] == hashlib.sha256(member).hexdigest()
    assert claim["proof"] == team_claim.team_claim_proof(11, TEAM_KEY, claim["descriptor_sha256"])
    assert claim["proof"] != team_claim.team_claim_proof(11, TEAM_KEY, "b" * 64)


def test_the_published_team_id_is_the_offline_search_oracle_for_a_low_entropy_key(tmp_path):
    """The residual this design does NOT remove, pinned so nobody re-derives it as removed.

    **The oracle is the `team_id`, not the claim file.** `submission.json` carries
    `team_id = "team-" + sha256(b"agenthon2026-team-alias:" + N + b":" + K)[:32]`, and that
    value is published in every zip and shown on the leaderboard. It is there whether or not
    a `team-claim.json` is, it is there for every upload after the first, and no change to the
    claim contract can remove it: the descriptor has to carry the team's identity. So anyone
    holding a published zip -- or just reading the board -- can compute the alias for a
    *candidate* key and compare. Changing or deleting the claim file would not close this.

    The proof is searchable too, for the same reason (whatever the organizer can recompute, a
    guesser can recompute), but it is the lesser half: it exists only where a claim file does.
    Both are asserted below, alias first, so the attribution cannot drift back.

    So the design removes DISCLOSURE (the key is not in the zip) and REPLAY (the proof is bound
    to one descriptor). It does not remove GUESSING, and nothing in either repository can.

    **Measured 2026-09-10 against the live agenthon.net roster: all 349 issued keys are exactly
    24 characters drawn from digits, lower case, upper case and punctuation.** A uniform
    generator over that alphabet is about 2**157, so the search is hopeless and the residual is
    theoretical for the keys that have actually been issued. It would become real only if the
    website ever issued short keys. The thing to raise if anyone wants to close it properly is
    therefore the documented 8-character minimum (`MIN_KEY_CHARS`, and its twin in the
    organizer's `registration_roster.py`) -- not anything in the claim contract.

    This test asserts the weakness rather than the strength on purpose, at the 8-character
    minimum the contract still permits rather than at the 24 characters the website issues. If
    a future change makes either value non-searchable, this test fails and the change gets the
    credit it deserves; until then nobody can call a published zip safe for a weak key.
    """
    out = tmp_path / "submission.zip"
    team_claim.pack_submission(body(), 11, "hunter22", out)  # the 8-char minimum
    with zipfile.ZipFile(out) as archive:
        descriptor = json.loads(archive.read("submission.json"))
        claim = json.loads(archive.read(team_claim.TEAM_CLAIM_FILE))
    candidates = ("password", "letmein1", "hunter22", "trustno1")

    # 1. The alias alone. This is the oracle: `team_id` is published by design, in the zip and
    #    on the leaderboard, and it needs no claim file to exist.
    assert [
        c
        for c in candidates
        if hmac.compare_digest(team_claim.derive_team_alias(11, c), descriptor["team_id"])
    ] == ["hunter22"]

    # 2. And the proof, where a claim file happens to be present, using only values the
    #    archive itself publishes.
    assert [
        candidate
        for candidate in candidates
        if hmac.compare_digest(
            team_claim.team_claim_proof(
                claim["site_team_id"], candidate, claim["descriptor_sha256"]
            ),
            claim["proof"],
        )
    ] == ["hunter22"]
