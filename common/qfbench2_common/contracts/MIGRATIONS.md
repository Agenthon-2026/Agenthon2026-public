# Contract set changelog

The contract set is the frozen interface between a submission, the ingestion program and the
scorer. This file records what changed between published versions, so that a submission built
against one version can tell whether a later one affects it.

## 1.1.0 — current

The version this package ships. `qfbench2_common.contracts.CONTRACT_SET` reports it at runtime:

```python
from qfbench2_common.contracts import CONTRACT_SET
print(CONTRACT_SET)   # 1.1.0
```

Participant-visible surface:

- **C5 — submission descriptor.** `submission.json` carries `image` as an object with
  `registry`, `repository` and `digest`, which the consumer reassembles into a
  digest-pinned reference. The earlier free-string form is not accepted.
- **C3 — output sanitisation.** What your container writes is filtered before it reaches the
  scorer; anything outside the documented output contract is dropped rather than scored.
- **C4 — result states.** Every expected unit resolves to exactly one state. A unit you fail
  still occupies its place in the denominator, so declining to answer cannot improve a score.

The remaining contracts (C1, C2, C6, C7, C8) govern organizer-side roster, run-record, dataset,
worker and publication concerns and impose no requirement on a submission.

## Earlier versions

Superseded before the competition opened and not documented here; 1.1.0 is the first published
contract set.

---

# C5 → 1.1.0 (2026-09-03) — `models` may be empty

**What changed.** `submission.schema.json` drops `minItems: 1` on `models`, and
`SubmissionDescriptor.from_mapping` drops the matching `min_items=1`. The `models` **key stays
required**, so an empty array is a positive statement — "this submission calls no model" —
distinct from a lazy omission, which is still refused. Every row that IS declared still requires
all five fields. `schema_version` may be `1.0.0` or `1.1.0`; the parser checks the major only, so
every valid 1.0.0 descriptor is still valid with an unchanged digest.

**Why.** Model-free entries are a normal, intended shape: a deterministic Track 3 simulator,
Track 2's text-blind baselines and Track 4's minimal RAG baseline call no model, and 1.0.0
forced each of them to invent a placeholder row — which makes
`models` unusable as evidence exactly where the disclosure rule matters.

**What a producer must change.** Nothing. A model-free submission may now write `models: []`
instead of a placeholder row, and should — with a toolkit that carries this version. The
`v2.3.1` toolkit refuses `models: []` ("'models' must hold at least 1 item(s)"); validate locally
with the tag that ships this change or later.

---

# Optional C2 stable-output repeat evidence (candidate, 2026-09-21)

**What changed.** A repeat may additionally carry `stable_output_binding` with exactly
`policy_digest` and `content_digest`, both SHA-256 digests. Existing signed records remain
readable and their bytes are unchanged. This does not replace `output_tree_digest` or the
top-level `bindings.sanitized_tree_digest`; those continue to bind the complete retained C3
tree. The new field is also inside the Runner attestation payload.

**Why.** Track 3's `events.json` contains measured time, so honest repeated output trees
differ even when their trace and ledger bytes agree. Comparing the whole tree across repeats
therefore rejects honest runs. Removing all repeat binding would admit alternating valid and
invalid output. The stable binding lets the scorer compare only a predeclared semantic member
set while retaining the full artifact binding separately.

**Producer and consumer.** Both call `stable_output_binding` on the immutable sanitized tree
with the same organizer-owned policy ID, allowed stable members and required stable members.
The policy digest commits all three; the content digest uses the existing `digest_member_set`
preimage. Required-member absence, duplicate paths and symlinks are refused. Optional-member
presence changes the content digest. The member policy never comes from participant output.

**Migration order.** Deploy the schema/parser reader first, then the matching track validator
and Runner producer in one pinned release. Old readers have a closed repeat key set and will
refuse the new field. A track adopting this evidence must require it for its new official
profile, recompute the expected policy and content from the retained sanitized output, and
refuse missing/mismatched evidence. Legacy Development records do not become rankable merely
because the reader accepts them. This hub candidate does not activate a production producer
or claim that Track 3's end-to-end timing defect has been fixed.

---

# C2 1.1.0 → 1.2.0 — bounded host execution faults

A container that times out before starting can meet every execution control and still fail
because of the organizer's infrastructure. C2 now records that fault separately from unmet
controls. A participant timeout after starting still consumes the C1 failure penalty.

Only C2 changes version. C1 `schema_version`, `contract_set`, and C3–C8 stay at their existing
versions. This migration does not change the failure penalty or the expected roster.

## New field and evidence

Every 1.2.0 record requires this closed object, included in the existing attestation payload:

```json
"execution_fault": {
  "attribution": "infrastructure",
  "reason": "create_timeout",
  "evidence": "host_lifecycle"
}
```

The canonical parser derives the object from signed host lifecycle facts and refuses any
disagreement. The Runner independently compares the Hub's `fault` / `docker_fault` claims
with those same host facts before signing. It never derives blame from participant stderr.

| Host evidence, in precedence order | `reason` | `attribution` |
|---|---|---|
| `cleanup_confirmed=false` | `cleanup_unconfirmed` | `infrastructure` |
| `timed_out=true` and `phase_reached=created` | `create_timeout` | `infrastructure` |
| Neither condition | `none` | `none` |

`none` means neither bounded condition was established. It is not a general certificate that
the host was healthy. The initial vocabulary does not classify arbitrary daemon refusal text.
An organizer infrastructure claim outside this vocabulary causes the Runner to refuse signing;
the resulting absent C2 aborts evaluation. Extending the vocabulary requires a canonical
classifier and independent host evidence, not just a new unsigned observation label.

An infrastructure diagnosis requires `rankability.state=organizer_failure`. Its unmet-control
list may be empty; no hardware or telemetry gap is invented to encode the fault. Existing real
control failures remain recorded. `participant_outcome` continues to describe completion, so
it can remain `failure` on an infrastructure fault. The scoring driver checks organizer failure
first and aborts the entire C1 evaluation before publishing scores or partial results.

## Reader and writer migration

1. Upgrade all C2 readers and scoring bundles first. The reader verifies the full C2 signature
   and accepts existing signed 1.1.0 records without injecting a field or changing their bytes.
   Exactly 1.1.0 and 1.2.0 are supported; unknown or malformed versions are refused.
   The empty-control exception is top-level only; repeat rankability remains unchanged.
   An absent legacy field is unknown evidence. Ordinary legacy participant failures remain
   scoreable; a legacy infrastructure claim or timeout before start is refused as ambiguous.
   Obtain a new run with host evidence; never rewrite or re-sign old history to supply a diagnosis.
2. Publish and pin a toolkit artifact containing the new parser and regenerate scoring bundles.
   Record those exact artifacts in the existing release evidence. Old strict readers reject
   the new field, so writer-first rollout causes an intentional parse failure.
3. Upgrade the production Runner writer to emit 1.2.0 for every new record. It uses the same
   three-field object for fault-free and faulting records. Run the paired Runner-to-score tests
   against the exact Hub source used to build the bundle.
4. Keep the Development self-attester on 1.1.0. It already maps its organizer infrastructure
   observation to `organizer_failure`; it does not collect the independent production host
   evidence required by the new writer. Its non-rankable development trust policy is unchanged.

Signature verification is required for both versions. A known key id alone does not authenticate
a payload. The scoring loader now verifies the complete record before admitting lifecycle or
fault data; an invalid signature aborts evaluation. Test fixtures that intentionally mutate a
record must sign their final payload unless the test is explicitly exercising tampering.

This participant-toolkit port provides the canonical reader. It does not package the private ingestion or scoring programs, activate the Runner, or establish production signing custody.

---

# C2 1.2.0 → 1.3.0 — a signed participant refusal

A run can exit 0 and still fail through the participant's own doing: it leaves none of the stable
output the unit requires, its trace cannot be read, a sidecar it wrote is invalid, its repeats'
stable outputs differ, or the sanitizer refuses its output tree. Daemon facts alone derive such a
run as `success`, so no signed C2 could state the failure, and a Runner that found one could only
hold the unit as the organizer's. C2 now carries the Runner's verdict as one signed member, and
the scoring driver charges it as a participant failure.

Only C2 changes version. C1 `schema_version`, `contract_set`, C3–C8 and the C4 failure-code
registry stay at their existing versions: every refusal is scored as a code the registry already
has. This migration does not change the failure penalty or the expected roster.

## New member

Every 1.3.0 record requires `participant_refusal`, inside the existing attestation payload. It is
`null` when the Runner refused nothing, or one code from a closed set:

```json
"participant_refusal": "repeats_differ"
```

| `participant_refusal` | The run exited 0 cleanly, and | Scored as |
|---|---|---|
| `no_stable_output` | left none of the stable output the unit requires | `no_output` |
| `trace_missing` | its trace cannot be read | `malformed_output` |
| `sidecar_invalid` | a sidecar it wrote is invalid | `schema_invalid` |
| `repeats_differ` | its repeats' stable outputs differ | `incomplete_output` |
| `output_refused` | the sanitizer refused its output tree | `malformed_output` |

`run_record.PARTICIPANT_REFUSAL_CODES` is the closed set and
`run_record.PARTICIPANT_REFUSAL_FAILURE_CODES` is the table. The scoring driver and a track scorer
that reads C2 itself use the same table, so they cannot report different codes for one run.

## What the parser enforces

- The member is required on 1.3.0, where an explicit `null` is the statement "nothing was
  refused", and refused on 1.1.0 and 1.2.0. A value outside the closed set is refused, never read
  as an "other".
- A code makes `participant_outcome` a `failure`:
  `derive_participant_outcome(lifecycle, participant_refusal=code)`. A record that declares
  `success` beside a refusal does not parse, and neither does a clean exit that declares `failure`
  without one.
- A refusal is refused on a record that attributes the run to the organizer: an infrastructure
  `execution_fault`, or `rankability.state = organizer_failure`. An organizer fault is never
  charged to the participant, and the Runner never signs both.
- A refusal is refused on a lifecycle that already derives a failure. A timeout, an out-of-memory
  kill or a nonzero exit keeps its lifecycle code (`resource_timeout`, `resource_oom`,
  `container_crashed`, `image_unusable`); a refusal describes a run the lifecycle calls a success.
- The member is inside the attestation payload, so a refusal added, removed or changed after
  signing fails verification.

## How it is scored

The scoring driver still checks organizer failure first and aborts the whole evaluation on one,
and it still charges a canary hit as `contamination_detected` before it reads the outcome. A
refusal then takes the participant-failure branch like any other failed run: the unit keeps its
place in the C1 denominator at the plan's worst-case score `W`, with the public code from the
table, and no track scorer is asked about it.

## Reader and writer migration

1. Upgrade the C2 readers and the scoring bundles first, together. An older toolkit refuses a
   1.3.0 record outright (an unsupported version, or an unknown field), so a writer-first rollout
   aborts evaluations rather than scoring them. A scoring driver that predates this change would,
   on a newer toolkit, charge a refusal under the lifecycle code `container_crashed`, so the bundle
   and the toolkit it runs on move in one release.
2. 1.1.0 and 1.2.0 records are read exactly as before: no member is injected, their signed bytes
   are unchanged, and they score as they did.
3. Upgrade the Runner writer to emit 1.3.0 for every new record, with `participant_refusal: null`
   unless it refuses the output of a clean exit. It signs a refusal only on a record it would
   otherwise charge (no infrastructure fault, no `organizer_failure`), never beside a lifecycle
   failure, and `derive_participant_outcome` gives the outcome to sign.
4. A track scorer that reads C2 itself reads the same member and the same table.
5. The Development self-attester stays on 1.1.0.
