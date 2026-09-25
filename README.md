# Agenthon 2026 — shared toolkit

This repository holds **`qfbench2-common`**, the evaluation toolkit shared by all four Agenthon
2026 tracks. It is the one piece of code that both you and the organizers run: the smoke test you
use locally and the sealed scorer that ranks you import the *same* package, so a result you can
reproduce here is a result that means something on the leaderboard.

If you are looking for the tasks themselves, they live in the track repositories:

| Track | Repository | What you build |
|---|---|---|
| 1 — Coding | [`track1-coding-public`](https://github.com/Agenthon-2026/track1-coding-public) | an agent that solves quantitative-finance coding tasks |
| 2 — Forecasting | [`track2-forecasting-public`](https://github.com/Agenthon-2026/track2-forecasting-public) | an agent that emits a probabilistic forecast |
| 3 — Simulation | [`track3-simulation-public`](https://github.com/Agenthon-2026/track3-simulation-public) | an agent that builds and profiles a market simulation |
| 4 — Explainability | [`track4-analysis-public`](https://github.com/Agenthon-2026/track4-analysis-public) | an agent that predicts from tables and cites its evidence |

**Start with a track repo, not this one.** Each has its own `README.md` and a `SUBMISSION_CLI.md`
that is the authoritative contract for what your container must produce. This repository is the
library they all depend on.

---

## Install

```bash
pip install "qfbench2-common @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.4.4#subdirectory=common"
```

**Python 3.13 or newer is required** (`requires-python = ">=3.13"`). On 3.12 or below pip refuses
during resolution — `ERROR: Package 'qfbench2-common' requires a different Python` — and nothing is
installed. Change interpreter; there is nothing to reinstall or patch around.

Runtime dependencies are `numpy`, `scipy` and `jsonschema`. Nothing else, deliberately: this
package is installed *inside* scoring images where a heavy dependency tree is a liability.

**Pin the tag.** Installing from a moving branch means your local result and your scored result can
diverge without either being wrong, and that is a miserable thing to debug the night before a
deadline.

## Check it worked

```bash
python -c "from qfbench2_common.contracts import CONTRACT_SET; print(CONTRACT_SET)"
# 1.1.0
```

If that prints `1.1.0` you have the frozen contract set the competition is scored against.

## What you get

Two command-line tools:

```bash
qfbench2-smoke <unit_dir> <output_dir> --track {coding,forecasting,simulation,analysis}
```

> **`qfbench2-smoke` needs your track's package, not just this toolkit.** It imports
> `qfbench2_track_<track>.scoring` from the track repo. With only `qfbench2-common` installed the
> command exits non-zero with `ModuleNotFoundError: No module named 'qfbench2_track_<track>'`.
> Install the track kit first (`pip install -e .` from the kit root, or `export PYTHONPATH="$PWD"`).

Runs the real admissibility gates over an output directory you produced. This is the single most
useful thing in the repository — it tells you whether your submission would be *accepted*, which is
a different and more urgent question than whether it would score well.

```bash
qfbench2 {smoke,card,manifest,eval,track1,track4,submission}
```

The fuller CLI: validate a `card.toml`, verify a manifest's checksums, lint an entire `units/`
tree, drive the Track 1 / Track 4 runner adapters, or pack your submission:

```bash
qfbench2 submission alias --team-number <N>        # prints your team_id (asks for the Team Key, hidden)
qfbench2 submission pack  --descriptor submission.json --team-number <N> --out submission.zip
```

There is no registration page. Your `team_id` is derived from your website team number and Team
Key, and `pack` writes `submission.zip` with `submission.json` (sealed) and `team-claim.json`,
which links your CodaBench account to your team on its first upload. **The Team Key itself never
enters the zip** — an uploaded zip is downloadable by anyone once the run is placed on a
leaderboard, so the claim carries a proof bound to that one descriptor instead. The key is asked
for on a hidden prompt or read from `--team-key-file`; it is never a command-line argument, and
the toolkit never writes it anywhere. See `starter-packs/<track>/TEAM-CLAIM.md`.

At the participant Development opening, **Track 1 allows 1 upload per team per day**;
**Tracks 2, 3 and 4 allow 5 per team per day**. Each track retains a **20-upload Development
total per team**; Track 1's is 23 (raised from 20 on 25 September 2026 at 05:00 UTC, with its rule 9). Held or cancelled uploads also consume attempts; local validation and
packaging do not. See [Development submission limits](docs/DEVELOPMENT-RUNTIME.md#submission-limits-at-the-development-opening).

Development runs through **October 12, 2026**. The joint **Final + Verification phase runs
October 13–25, 2026**. Each team makes **one final submission per track**; organizers perform
verification within that same phase, with no separate participant Verification submission.
If two Final submissions finish a track with the same ranking score, the tie is broken in favour
of the one uploaded earlier.
Registration and Development close together on October 12, 2026 at **23:59 Anywhere on Earth (AoE, UTC−12)**. The joint Final + Verification phase closes on October 25, 2026 at **23:59 AoE**. Other competition dates and task/data cutoffs are unchanged.

And the library:

| Module | What it is for |
|---|---|
| `qfbench2_common.taskcard` | parse and JSON-schema-validate `card.toml` |
| `qfbench2_common.manifest` | per-file `sha256` and public-safety enforcement |
| `qfbench2_common.leakage` | cutoff / embargo / network-mode checks |
| `qfbench2_common.verifier` | the gate chain: g0 integrity → g1 schema → g2 cutoff/resource → g3 domain |
| `qfbench2_common.failure_labels` | the cross-track failure taxonomy you will see in your results |
| `qfbench2_common.scoring` | the actual metrics — pass@k, CRPS, stylized facts, faithfulness, bootstrap CIs |
| `qfbench2_common.contracts` | the frozen C1–C8 contracts, including the submission descriptor |
| `qfbench2_common.schemas` | every JSON Schema your output is validated against |

## The schemas are the contract

Your track's `SUBMISSION_CLI.md` describes what to write in prose. These files decide it in code:

```
analysis.schema.json    Track 4 answer.json
forecast.schema.json    Track 2 forecast_meta.json
sim_scenario.schema.json Track 3 scenario output
taskcard.schema.json    card.toml
manifest.schema.json    per-file checksums
submission.schema.json  the zip you upload
```

Read them. When prose and schema disagree, the schema is what runs — and a submission that fails
schema validation is inadmissible no matter how good the underlying work was.

```python
from qfbench2_common.taskcard import load_schema
print(load_schema("analysis.schema.json")["required"])
# ['task_id', 'entity_predictions']
```

## Getting help

Open an issue in the relevant **track** repository — the track leads read those. Issues about the
toolkit itself belong here.

## Licence

CC BY-NC 4.0, see [`LICENSE`](LICENSE). Third-party data shipped inside the track repositories is covered by
those repositories' own notices, not by this one.
