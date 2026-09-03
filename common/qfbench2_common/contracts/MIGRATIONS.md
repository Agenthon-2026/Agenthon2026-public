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
Track 2's text-blind baselines, Track 4's minimal RAG baseline and Track 1's Finance-Zero baseline
all call no model, and 1.0.0 forced each of them to invent a placeholder row — which makes
`models` unusable as evidence exactly where the disclosure rule matters.

**What a producer must change.** Nothing. A model-free submission may now write `models: []`
instead of a placeholder row, and should — with a toolkit that carries this version. The
`v2.3.1` toolkit refuses `models: []` ("'models' must hold at least 1 item(s)"); validate locally
with the tag that ships this change or later.
