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
