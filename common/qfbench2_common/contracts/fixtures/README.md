# Golden C1–C8 fixtures — contract set 1.1.0

## Executive summary (read this first)

These files are the **one** set of contract examples for the whole program. CodaBench ships the C5
files verbatim as its generated examples; the website renders participant documentation from the
same bytes; the Hub test suite parses every one of them on each run. Nobody hand-writes a second
example — the pair of overlapping model-disclosure representations that produced the
generated-example drift is exactly what that rule prevents.

Read one with the package, never by guessing a path:

```python
from qfbench2_common.contracts.fixtures import load_fixture, iter_c5_fixtures
plan = load_fixture("c1/coding_final.expanded.json")
for track, phase, descriptor in iter_c5_fixtures():
    ...
```

## What is here

| File | Contract | Notes |
|---|---|---|
| `c1/<track>_final.expanded.json` | C1 | Resolver/scorer form: carries unit identities |
| `c1/coding_final.public.json` | C1 | Public commitment: counts, digests and policy only |
| `c2_run_record.json` | C2 | A successful, rankable coding run, bound to the C1/C3/C5/C7 files here |
| `c3_artifact_tree.json` | C3 | Three sanitized entries, one recorded symlink rejection |
| `c4_unit_result.json` | C4 | `participant_success` |
| `c4_unit_result_failure.json` | C4 | `participant_failure` with `resource_timeout` |
| `c4_aggregate.json` | C4 | 3 units × 3 attempt slots = 9; eight scored, one failed |
| `c4_failure_code_registry.json` | C4 | The versioned registry the website generates wording from |
| `c5/<track>_<phase>.json` | C5 | **4 tracks × 3 phases = 12 valid descriptors** |
| `c5/invalid/*.json` | C5 | Ten refused variants, one per defect the freeze closes |
| `c6_sealed_handle.json` | C6 | The bundle-visible handle: five fields, no digest |
| `c6_resolver_descriptor.json` | C6 | Signed resolver side, including an `answer_equivalent` artifact |
| `c7_hardware.json` | C7 | Fully measured → rankable |
| `c7_hardware_unmeasured.json` | C7 | The Track 3 GPU box before it exists → **not rankable** |
| `c7_worker_heartbeat.json` | — | A worker preflight bound to `c7_hardware.json` by instance digest |
| `c8_release_evidence.json` | C8 | A publishable manifest, `hide_prediction_output` true on every scored phase |
| `dev_trust_store.json` | — | The development trust store (see the warning below) |

The files cross-reference each other: `c2_run_record.json`'s `bindings` really are the digests of
`c1/coding_final.expanded.json`, `c5/coding_final.json`, `c7_hardware.json` and
`c3_artifact_tree.json`; the C4 rows really are bound to that plan and that record;
`c6_resolver_descriptor.json`'s roster commitment really is the forecasting plan's; and
`c7_worker_heartbeat.json` really is bound to `c7_hardware.json`. A fixture set whose parts do not
refer to each other cannot exercise the binding checks, which are most of what C2 is for.

## Re-signing is a cascade, and the order matters

Almost everything here is downstream of something else, so a change to one file is rarely one file.
The dependency order, which is the order to regenerate in:

```
C1 expanded  ->  plan_digest        ->  C2 bindings, C4 plan_digest
C1 roster    ->  roster.digest      ->  C6 roster_commitment, C1 public commitment
C7 body      ->  instance_digest    ->  C2 bindings, the worker heartbeat
C2 record    ->  record digest      ->  C4 run_record_digest
```

Every arrow crosses a signature, so each step is "edit, recompute, re-sign", never "edit". C2's
attestation is signed over the **frozen attestation payload** — the record minus
`attestation.signature` only, per `run_record.attestation_payload` — and nothing else computes it
correctly.

## Sealed-phase handles are derived, not typed

Every shipped `final` roster is minted by `derive_opaque_roster(FIXTURE_SEALED_IDS[track],
phase_salt=FIXTURE_HANDLE_SALT)`, and a test re-derives them and refuses a mismatch. That is
deliberate: the shipped example of "what a sealed roster looks like" has to be an example of how
one is actually produced, or the next person picks a hex string by hand and thinks that is the
supported path.

`FIXTURE_HANDLE_SALT` is published in `__init__.py` and is **not** a production salt — a real
phase salt is organizer-held secret material, differs per phase, and never appears in a repository.
The synthetic sealed ids it derives from (`synthetic-coding-unit-01`, …) are inventions.

## The dev signing key is public, and that is deliberate

The signed fixtures (C1, C6, C7, C8, and C2's attestation) carry real Ed25519 envelopes produced by
the seed in `contracts/fixtures/__init__.py`. That makes them verifiable end to end in a test rather
than carrying a placeholder that proves nothing.

C2's attestation is signed over the **frozen attestation payload** — the record minus its
`attestation` block, per `qfbench2_common.contracts.run_record.attestation_payload`. Re-sign it with
that function and nothing else: until the payload was frozen on 2026-08-22 this fixture's
`payload_digest` covered no computable structure at all, which is precisely the decorative
signature the freeze removes. Any edit to `c2_run_record.json` therefore requires re-signing, and
`c4_unit_result*.json` carry a digest of the whole record and must be refreshed with it.

Because the seed is published, **anything `dev_trust_store.json` accepts is forgeable.** The store
declares `"profile": "development"`, and `verify_signed(...)` refuses a development store unless the
caller passes `require_production_trust=False`. Production must never load this file. Key custody,
rotation, revocation and the replay window are decision D7 and belong to a named human security
owner; nothing in this package waits on that decision, because an unconfigured trust store already
fails closed.

## Data-firewall statement

Everything here is synthetic. Team ids are `team-example-*`, unit handles are opaque `u-<hex>`
strings derived from invented sealed ids, image digests are `sha256` of a literal
`"synthetic:<label>"` string, and the S3-shaped URIs point at a bucket name that does not exist. No
sealed unit id, task text, answer, target value, canary, roster entry, credential or broker URL
appears in any file.
