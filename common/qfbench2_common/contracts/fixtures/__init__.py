"""Golden C1-C8 fixtures, shipped **inside the package** so every repo consumes the same bytes.

## Executive summary (read this first)

CodaBench ships the C5 fixtures verbatim as its generated examples and the website renders from the
same files. Nobody hand-writes a third example — that is how the generated-example drift happened.
`load_fixture("c5/coding_dev.json")` is the supported way to read one.

Everything here is **synthetic**. Team ids are `team-example-*`, image digests are constructed hex,
and unit handles are opaque `u-<hex>` strings derived by `derive_opaque_roster` from the synthetic
ids in `FIXTURE_SEALED_IDS`. No sealed unit id, target value, canary, roster entry or credential
appears in any file.

### The dev signing key is public and forgeable, on purpose

The signed fixtures (C1, C6, C7, C8) carry real Ed25519 envelopes produced by the **development**
key whose seed is the constant below. That is what makes the fixtures verifiable end to end in a
test instead of carrying a placeholder that proves nothing. Because the seed is public, anything the
dev trust store accepts is forgeable, so `verify_signed(..., require_production_trust=True)` — the
default — refuses it. Production must never load `dev_trust_store.json`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import _ed25519
from ..signing import TrustStore

__all__ = [
    "DEV_KEY_ID",
    "DEV_SEED",
    "DEV_SELFATTEST_KEY_ID",
    "DEV_SELFATTEST_SEED",
    "FIXTURE_HANDLE_SALT",
    "FIXTURE_SEALED_IDS",
    "dev_public_key",
    "dev_selfattest_public_key",
    "dev_trust_store",
    "fixture_path",
    "iter_c5_fixtures",
    "load_fixture",
]

FIXTURE_DIR = Path(__file__).resolve().parent

#: NOT A CREDENTIAL. A published, deterministic test vector; the dev trust store it unlocks is
#: refused by every production verification path.
DEV_SEED = b"qfbench2-dev-signing-key-DO-NOT-US"[:32].ljust(32, b"\x00")
DEV_KEY_ID = "dev-organizer-2026"

#: NOT A CREDENTIAL either, and deliberately a SECOND published key rather than a second use of the
#: first. `DEV_KEY_ID` stands in for the Runner -- an organizer-side program that checks the Hub's
#: account of a run against host facts it gathered itself. `DEV_SELFATTEST_KEY_ID` stands for
#: something weaker and different in kind: the Hub attesting its own observation, on the Development
#: phase, where no Runner exists. One key for both would make those two producers indistinguishable
#: in the artifact, and "who signed this" is the only question the key id answers.
#:
#: The separation is also the ENFORCEMENT. A production trust store contains neither of these, so a
#: self-attested C2 is refused by `score.py`'s existing unknown-signer check without a single new
#: branch. Nothing has to remember to exclude it.
DEV_SELFATTEST_SEED = b"qfbench2-dev-hub-selfattest-key-DO"[:32].ljust(32, b"\x00")
DEV_SELFATTEST_KEY_ID = "dev-hub-selfattest-2026"

#: NOT A CREDENTIAL, and not a production salt. Published so the shipped C1 rosters are
#: *reproducible*: a test can re-derive `u-63796a87128182d0` from `synthetic-coding-unit-01` and
#: this string and show that the fixtures were minted by `derive_opaque_roster` rather than typed.
#: A real phase salt is organizer-held secret material and never appears in a repository.
FIXTURE_HANDLE_SALT = "agenthon2026-synthetic-fixture-handle-salt-v1"

#: The synthetic sealed ids the shipped `final`-phase rosters derive from, in roster order. These
#: are inventions; no sealed unit id appears anywhere in this package.
FIXTURE_SEALED_IDS = {
    "coding": ("synthetic-coding-unit-01", "synthetic-coding-unit-02", "synthetic-coding-unit-03"),
    "forecasting": (
        "synthetic-forecasting-unit-01",
        "synthetic-forecasting-unit-02",
        "synthetic-forecasting-unit-03",
    ),
    "simulation": ("synthetic-simulation-unit-01", "synthetic-simulation-unit-02"),
    "analysis": ("synthetic-analysis-unit-01", "synthetic-analysis-unit-02"),
}


def dev_public_key() -> bytes:
    return _ed25519.public_key_from_seed(DEV_SEED)


def dev_selfattest_public_key() -> bytes:
    return _ed25519.public_key_from_seed(DEV_SELFATTEST_SEED)


def dev_trust_store() -> TrustStore:
    """The development trust store. `require_production_trust=False` is needed to use it."""
    return TrustStore(
        {DEV_KEY_ID: dev_public_key(), DEV_SELFATTEST_KEY_ID: dev_selfattest_public_key()},
        profile="development",
        label="shipped dev fixtures",
    )


def fixture_path(name: str) -> Path:
    """Resolve a fixture by relative name, refusing any path that escapes the fixture directory."""
    candidate = (FIXTURE_DIR / name).resolve()
    if not candidate.is_relative_to(FIXTURE_DIR) or not candidate.is_file():
        raise FileNotFoundError(f"no such contract fixture: {name}")
    return candidate


def load_fixture(name: str) -> Any:
    return json.loads(fixture_path(name).read_text(encoding="utf-8"))


def iter_c5_fixtures() -> list[tuple[str, str, dict[str, Any]]]:
    """Every valid C5 fixture as `(track, phase, document)` — four tracks by three phases."""
    out = []
    for path in sorted((FIXTURE_DIR / "c5").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        out.append((document["track"], document["phase"], document))
    return out
