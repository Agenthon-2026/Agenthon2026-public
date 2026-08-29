# Agenthon 2026 — starter packs

One folder per track, and **each folder is self-contained**: take your track's folder and you have
everything — the pack itself plus the two pages it depends on.

| track | folder |
|---|---|
| Track 1 — Coding | [track1/](track1/) |
| Track 2 — Time-Series Forecasting | [track2/](track2/) |
| Track 3 — Simulation | [track3/](track3/) |
| Track 4 — Explainability | [track4/](track4/) |

Inside each folder:

- **`AGENTS.md`** — the pack. Written for a coding agent rather than a human browsing a repo:
  what to build, the traps that cost a submission, and what was measured rather than assumed.
  Includes this track's accelerated-library guidance.
- **`SUBMISSION-DESCRIPTOR.md`** — `submission.json` in full. The most common way a submission
  fails before it ever runs.
- **`RUNTIME-ENVIRONMENT.md`** — the machine your code runs on: hardware, sandbox, network,
  image requirements.

**[CHANGELOG.md](CHANGELOG.md)** records every change to these packs during Development, tagged
by whether it needs action from you. Watch it rather than re-reading the packs.

The tracks differ enough that reading another track's pack will mislead you — Track 1 tolerates
floating-point reassociation that is fatal on Track 3, for instance. Read your own.

Everything measurable in these packs was measured against the public kits as of **2026-08-28**.
