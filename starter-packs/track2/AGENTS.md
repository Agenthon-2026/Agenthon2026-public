# Track 2 — Forecasting. Read this before writing anything.

> **Two more pages ship in this folder, and you need both.**
> [SUBMISSION-DESCRIPTOR.md](SUBMISSION-DESCRIPTOR.md) — the twelve descriptor fields, and the most
> common way a submission fails before it ever runs.
> [RUNTIME-ENVIRONMENT.md](RUNTIME-ENVIRONMENT.md) — the fleet, the `sm_100` trap, the image
> requirements, and how to check your image is actually pullable.

You are helping build a **submission** for Agenthon 2026 Track 2 — one **Docker image**, run once
per card, graded on what it writes. You are not authoring cards: if you find yourself editing
`units/` or `regression_suite/`, stop.

```
forecast --panels /input --text /input/text/ --asof <YYYY-MM-DD> --out /output/forecast.parquet
```

The verb arrives as the first argument after the image reference: resolve it from `PATH` (no
`ENTRYPOINT`) or consume it as a leading positional. `LABEL qfbench2.interface_version="2.0"` is
required. Output goes to **`/output`** — not `/app/output`; that is Track 1's path and T2 has no
dual mount.

> **Accelerated libraries:** see the section at the end of this file — the honest answer on this
> track is that there is almost no surface. **Bringing your own model?** Read the BYO section at
> the end first — those rules change what your image contains.

> **The descriptor has its own page.** `submission.json` is twelve required fields with
> `additionalProperties: false`, validated by a toolkit that installs in one command. It is the
> most common failure. See [SUBMISSION-DESCRIPTOR.md](SUBMISSION-DESCRIPTOR.md) before you build
> one, and start from the fixture it points at.

## The corpus: 104 units, and the exemplar is not its shape

`units/` holds **104** directories: the exemplar plus 103 practice units. The practice units are
not the held-out set — do not over-fit to the shape you can see.

### Measured across all 104 units

**Confirmed, 104/104:**
- the forecast panel is at the **unit root**, never under a `panels/` subdirectory — so
  `--panels /input` is right and `--panels /input/panels/` finds nothing
- every unit ships both `card.toml` and `manifest.json`

**The exemplar's shape is NOT the corpus.** `t2-EXAMPLE-ust-curve-1m` is 4 assets on a single
horizon `[21]`. Across the corpus:

| | seen |
|---|---|
| distinct horizon lists | **14** — per UNIT: `[21]` (26), `[126, 189]` (16), `[63]` (16), and 11 more |
| asset counts per declaration | 1, 2, 3, 4 and **10** |
| distinct `panel_id`s | 5 — `rates_daily`, `g10_fx_daily`, `factors_daily`, and two others |

**The trap is multi-horizon.** `[126, 189]` is not a single-element list, and it is the second most
common shape in the corpus. Anything that reads `horizons[0]`, assumes one forecast per asset, or
sizes an output array from the exemplar will run cleanly on the public unit and produce a
wrong-shaped `forecast.parquet` on roughly a third of the practice set. Read `horizons` as a list
and emit one row per (asset, horizon, draw).

*(Counting note: cards declare `horizons` under BOTH `[metadata]` and `[targets]`, so a naive grep
double-counts — the row above is per unit. `asset_ids` counts remain per declaration, since it
appears under both `[panels.*]` and `[targets]`; the distinct values and the range are the point,
not the totals.)*

Two more cards sit under `regression_suite/units/` and are **CI fixtures, not practice units**:
synthetic, `cpus = 2`, `network = "none"`, no `manifest.json`. `qfbench2-smoke` refuses them before
scoring on card-schema errors (`task/id: 'reg-t2-daily' does not match '^t[1-4]-...'`) — and it
scores all 104 real units: `admissible=104, not-admissible=0`. Do not calibrate against the
regression fixtures.

The exemplar itself holds 9 files, 8 tracked by `manifest.json` (all but the manifest itself):
`1 parquet` (the panel, role `input`), `2 txt` + `1 json` (the corpus), `1 toml` (the card),
`2 md` + `1 sh` (docs). Two things vary across the corpus that the exemplar will not show you:

- **The panel's asset column is not stably named.** The exemplar uses `asset_id`; both regression
  panels use `asset`. The reference CLI accepts either (`cli._ASSET_COLS = ("asset", "asset_id")`,
  commented "the pilot and prospective batches use `asset`"). Accept both.
  Measured across all 116 panels in 104 units: **115 are exactly
  `['date','asset','value','panel_id']`** and exactly one — the exemplar — is
  `['date','asset_id','value']`. The README's stated shape is right for 99.1% of the corpus and the
  exemplar is the outlier. Handle both, and do not assume the exemplar's column names.

Also: the exemplar's `card.toml` declares `start_date = "2000-01-03"`; the shipped parquet holds
**516 rows, 129 per asset, 2024-01-02 → 2024-06-28**. Read the file, not the card.

## The output contract is uniform — and it is an exact set, not a minimum

**The filenames are not per-unit** — the inverse of Track 1. They are hard-coded at module scope in `qfbench2_track_forecasting/scoring.py`:

```python
PARTICIPANT_FILES = ("forecast.parquet", "forecast_meta.json", "forecast_rationale.md")
```

`g0_integrity` compares the output directory's listing against that tuple and refuses on any
difference. **Exactly three files. Not two, not four.** Seven refusals, measured with the real
scorer:

The schema requires `unit_id` (not `card_id`), and `cutoff.bind_metadata`
then requires `unit_id`, `asof` and `target` to **equal the card's**.
`templates/forecast_meta.example.json` is correct and says so in its own `_comment` — copy the
template.

The parquet contract, from `grid.py` and `limits.py`:

- columns **exactly** `("draw", "asset", "horizon", "value")` — an extra column is refused, not ignored
- row count **exactly** `n_draws × len(assets) × len(horizons)`, checked on the footer first
- `draw` ids contiguous and zero-based; every `(draw, asset, horizon)` cell occupied **exactly
  once** — duplicates refused, never averaged
- `asset_ids` and `horizons` must match the plan's grid **in order**; the realized vector is
  flattened the same way
- every `value` finite; `n_draws ∈ [200, 20000]` — but the **ceiling is code-only** (`limits.py:81`).
  `forecast.schema.json:44-48` has `minimum: 200` and **no maximum**, so schema validation alone will
  not catch an oversized draw count. Two more code-only ceilings the schema does not carry:
  `max_uncompressed_bytes = 2 GiB` and `max_rows = 5_000_000` (`limits.py:75,77`)
- ceilings: parquet ≤ 64 MiB, meta ≤ 256 KiB, rationale ≤ 1 MiB, ≤ 8 columns, ≤ 64 row groups

`forecast_rationale.md` is **required and never scored** — `rationale_has_content` learns exactly
one bit, whether it holds one non-whitespace character. Write it; do not optimise it.

## Two things that cost score outright, and are easy to miss

### 1. `target_type` — 16 of 104 units want a CUMULATIVE quantity, not a level

Cards declare `target_type`. Across the 104 public units it is **`level` on 90 and `log_return` on
16**. That is not cosmetic:

- On a `level` unit you forecast the value itself.
- On a **`log_return`** unit (`value_unit = "cumulative_log_return"`) the panel's `value` is
  *already a per-period return*, so the scored target is a **sum over the horizon, anchored at 0** --
  not an anchored level.

**The kit's own reference CLI gets this wrong.** `cli.py:130-141` anchors on the last observation for
every card, which is incorrect on all 16. Copy its structure if you like; do not copy that.

And the failure is not where you would look for it: a `target` in `forecast_meta.json` that
*disagrees* with the card fails **`g2_cutoff_resource`**, not `g1` or `g3`
(`{'code': 'schema_invalid', 'violation_count': 1}`) — note the gate. **Omitting `target` entirely
is admissible** -- `cutoff.py:129-140` only checks that
it does not disagree -- so if you are unsure, leave it out rather than guess.

### 2. Horizons are in PANEL STEPS, and 4 units ship a monthly panel

`horizons = [21]` means 21 **panel rows**, not 21 days. Most panels are business-daily, so 21 rows is
about a month. But four units ship a **monthly** panel (median step ~31 days) while declaring
horizons that look business-daily:

```
t2-F4-covid-nfp-2020      horizons=[21]        t2-F4-cpi-vintage-2022   horizons=[21]
t2-F1-cpi-glidepath-2023  horizons=[140,160]   t2-F1-sahm-watch-2024    horizons=[145,165]
```

Read those as business days and you forecast **21 months** instead of one, or **145 months** instead
of about seven. Silent, and catastrophic to the score.

**Do not use `target_frequency` to decide this.** That field describes the *target*, not the
panel: the **exemplar itself** declares `target_frequency = "monthly"` on a business-daily panel
with `horizons = [21]`. Measure the panel's own date spacing instead — it is the only discriminator
that is right on all 104 units.

## Four traps that are invisible until they cost a run

**1. Install the toolkit before any local check, and use exactly this line.**

```bash
pip install "qfbench2-common @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.3.1#subdirectory=common"
```

> **Pin the tag, never a branch.** A moving branch can make your local result and your scored
> result diverge without either being wrong.

With it, the `forecast` CLI, `regression_suite/run_regression.py`
(`ALL REGRESSION CHECKS PASSED`) and `python scoring/scoring.py score` all run.
`qfbench2-smoke --track forecasting` needs **one more step**: it imports
`qfbench2_track_forecasting.scoring` from the track kit, so install the kit as well
(`pip install -e .` from the kit root, or `export PYTHONPATH="$PWD"`). Without it the command
exits non-zero with `ModuleNotFoundError: No module named 'qfbench2_track_forecasting'`.

One install failure looks like a broken package and is covered on
[SUBMISSION-DESCRIPTOR.md](SUBMISSION-DESCRIPTOR.md): it requires **Python >= 3.13**. If an install
line you find elsewhere omits `-public` from the repository name, or pins an old tag or a raw commit
SHA — do not use it.

**2. `--panels` names a directory that does not exist in the kit.** `SUBMISSION_CLI.md` records ("verified by
execution") that the *staged* unit puts panels under `panels/`, that
`stage_bundle.py` relocates root panels into it, and that `--panels /input/` dies with "no .parquet
found" while `/input/panels/` scores. But **no unit in the kit ships a `panels/` directory** (0 of 104), and the
exemplar's `forecast_card.md` states the panel is at `/input/rates_daily.parquet`. Measured:
`<unit>/*.parquet` → **1 or 2 files — 12 of 104 units ship TWO panels**, so `glob('*.parquet')[0]`
silently drops one. On five units the dropped file can hold the **target** —
`t2-F3-boj-ust-channel-2023`, `t2-F3-divergence-2014`, `t2-F3-dollar-vortex-2022`,
`t2-F3-election-2024-joint`, `t2-F3-safe-haven-paradox-2011` — because `rates_daily` sorts after
`factors_daily`/`g10_fx_daily`. `<unit>/panels/*.parquet` → 0 files. So an agent that learns
`/input/*.parquet` from the exemplar finds nothing at evaluation time, and one that hardcodes
`/input/panels/*.parquet` finds nothing locally. The reference CLI survives because `_read_panels`
globs the given directory **and then its parent** — do the same, never assert on the directory
name. Both invocations are admissible. (`stage_bundle.py` is private, so what else the staged tree
holds is unverifiable. The verb passes no assets or horizons, so `card.toml` must be reachable —
the CLI tries `<panels>/card.toml` then `<panels>/../card.toml`.)

**3. `g2` does not check your text corpus, whatever the docs say.** `README.md` leakage rule 2 and
`SUBMISSION_CLI.md` invariant 6 both say a post-as-of document in `/input/text/` fails g2 and fails
*your* submission. `_g2_cutoff_resource`'s own docstring disagrees: under the frozen topology the
scorer receives `input/ref` and `input/res` only, so the corpus is not in its namespace, and
`run_regression.py` names its own test "post-as-of corpus document (**refused by the STAGING scan,
not by g2**)". The corpus is organizer material checked before publication. What g2 *can* fail you
for is the metadata binding. Skip corpus date-filtering; get the three declared fields right.

**4. Gates short-circuit, and every card is in the denominator.** `HierarchicalVerifier.run` returns
on the **first** failing gate; the rest never run, and there is no partial credit inside a card. A
card you fail is not dropped — it takes a pre-committed **W = 4.0**, and real scores are **clipped
into [0.0, 4.0]**, so failing can at best tie the worst honest attempt, never beat it. A card you
cannot forecast well should still emit three well-formed files and exit 0. **And if you see 4.0,
that is not "your maths was bad"** — a missing file, a fourth file, a wrong meta key and a wrong
asset order all render as it identically. Find it with the local scorer, not by re-tuning.

## The resource contract

Read it from the card. It does not vary across the participant-facing set — all **104** unit cards
declare the same `cpus = 16 · memory = "128G" · gpu = true · network = "restricted"`, and
`templates/card.toml` matches. The two regression fixtures declare `2 / 4G / gpu = false /
network = "none"` and are not participant units. `README.md` and `docs/NVIDIA-STACK.md` both state
that **every** T2 card grants that same sandbox.

**No card declares a timeout.** `SUBMISSION_CLI.md` says the harness enforces
`card.environment.timeout`, but **no `card.toml` in the kit has one** (0 of 104 units, both
regression fixtures, and the template) and the shared
`taskcard.schema.json` defines no such key under `[environment]` — only `build_timeout_sec`. The
only numbers are `README.md`'s, and the second binds first: **1800 s per unit** (a ceiling) but
**43 200 s for the whole Development submission** (86 400 s Final/Verification). Over ~100 cards
that is **~400 s per card**, and the clock starts at `docker create`, so a cold image pull (90–187 s
cold vs ~15 s warm, measured on this fleet) is billed to it. Design against ~400 s or you get cut
off partway through the roster with the rest unscored, at 4.0 each.

`gpu = true` is a grant, not a guarantee — whether a device is attached is a property of the worker.
**Your image must still start with no GPU present.**

**`network = "restricted"`** means you reach **`$MODEL_ENDPOINT`** (with `$MODEL_NAME`) through the
audited proxy and nothing else — no PyPI, no HuggingFace, no NGC, and **no vendor model API**;
`api.openai.com`, `api.anthropic.com` and the rest are refused, and no participant API key is
injected or injectable. Read `HTTP_PROXY`/`HTTPS_PROXY` from the environment, never hardcode a proxy
host. Vendor-side tools — web search, code execution, retrieval — **must be disabled** in every
call. The per-unit budget is 1,000,000 input + 100,000 output tokens, audited from proxy logs.
Bake everything in at build time and test with `--network=none`; it is stricter than `restricted`.

## Scoring, and what the metric actually rewards

`S = 0.5·marginal CRPS + 0.3·joint variogram + 0.2·tail penalty`, **lower is better**
(`LEADERBOARD_SORT = "asc"`). Two adjustments the formula hides:

- **Normalization.** Each component is divided by an official text-blind baseline's component on
  that card, so **1.0 means "no better than a random walk that ignores the text"**. Your local
  scorer cannot do this — it runs `RAW_UNRANKABLE` by construction, so its composite is not
  comparable across cards.
- **Single-cell renormalization.** On a one-asset, one-horizon card the variogram is 0 by
  construction, so weights become `(0.714, 0, 0.286)`; multi-cell cards are byte-identical. A code
  comment reports that a substantial minority of units on both splits are single-cell.

There is **no gate that checks whether the text helped**. Information uplift (best text-blind
baseline minus your composite) is a reported diagnostic, not a ranking dimension.

**The `baselines/` you are told to beat may all be the same random walk.** All five —
`theta_arima`, `chronos`, `timesfm`, `lag_llama`, `moirai` — wrap their import in `try/except
ImportError` and fall through to `BaselineForecaster._gaussian_rw_samples`. No weights are vendored
and the restricted network cannot fetch them; `run_example.sh` printed `baseline impl:
gaussian-rw-fallback (statsforecast not installed)`. A schema reference, not a difficulty bar.

`docs/NVIDIA-STACK.md` rules **CUDA / RAPIDS / cuDF "No fit"**, correctly: the scored payload is
`n_draws × cells` rows — the exemplar's is 2000 rows, 25.6 KB, produced in 2.3 s — and scoring is
CPU CRPS arithmetic. GPU libraries only bloat your image and your cold-pull budget.

## Documentation that describes code which does not exist

Each checked by grep or `ls`. Do not implement against any of it.

- **`T2_UNCALIBRATED_MARGINAL`, `T2_BAD_DEPENDENCE`, `T2_TAIL_MISCALIBRATION`** — named as g3 flags
  in `docs/CONCEPTS.md`, `docs/CATEGORIES.md` and `templates/forecast_card.md`, with **zero
  occurrences in any `.py` file** and in **no unit card** (all 106 checked; `CATEGORIES.md` carries
  only one of the three). Real
  `_g3_domain_semantics` checks grid and cell coverage only: a degenerate distribution is admissible
  and simply scores terribly.
- **A "g4" gate** — twice in `SOLVER-PLAYBOOK.md`; `GATES` has four entries, g0–g3, and `README.md`
  is explicit that cross-unit lookup is detected by nothing.
- **Six referenced paths that do not exist:** `data/`, `data-pipelines/`, `baseline-scores.csv`,
  `units-adversarial/`, `EVALUATION.md`, `scripts/`. **`rationale.md` and `forecast.csv`** —
  `SOLVER-PLAYBOOK.md` §6 offers both; both fail g0.
- **`representation: "parametric"`** — in the shared schema's enum, refused by the scorer because no
  loader exists. The kit's own `AGENTS.md` rule 5 says horizons are always business days; `reg-t2-monthly`
  ships `horizons = [3]` in months, so do not assume — and do not resolve it with
  `target_frequency` either (the exemplar declares `monthly` on a business-daily panel). Measure
  the panel's own date spacing; see "Horizons are in PANEL STEPS" above.

**Canary and licensing.** Every card carries `[contamination] canary_guid`. Keep task material out
of your deliverables: contamination is checked, the checks differ by track and are not all visible
from the public kit, and submissions are also read by humans. The task data are a corpus of
central-bank speeches and statements, government statistical releases and macro panels, wrapped in
cards and indexes the organizers wrote. Rights differ file by file: U.S. federal material is
public domain and organizer-written material is under this kit's own licence, but for most
non-U.S. central-bank and corporate documents the kit records the rights position as undetermined
and grants nothing, so those are not yours to redistribute either. Each unit's `manifest.json`
carries the source and licence for every file, and the kit's `DATA-LICENSE.md` sets out the
categories. Do not vendor task data into your image. Still forbidden: **cross-unit lookup**, and
baking any card's target into your image from any source.

## Facts from the evaluation fleet

- Sandbox is **gVisor (runsc)**: CPU arithmetic ~7-8%, heap ~0%, raw syscalls ~85%, sockets 67-95%
  by shape (in-process pair ~76%, loopback TCP ~67%, **cross-container 91-95%, a 10-20x slowdown**).
  So **never run a model server as a separate process and POST to localhost** — anything served
  in-image must run in-process (`vllm.LLM(...)`). The natural architecture is the slow one here and
  the symptom looks like a slow model. (A BYO submission ships a LoRA adapter, not weights — see
  the BYO section below.)
- **Container-name DNS does not resolve** for a sandboxed client. Use IPs, or what you are given.
- **Do not measure your own CPU time** with `os.times()`/`getrusage`; gVisor misreports it ~4x.
- Hosts are **x86-64 B200 (sm_100)**. Build single-arch `linux/amd64` and pin your numeric stack.
- Submissions are a zip containing `submission.json` naming a **digest-pinned, publicly pullable**
  image — ingestion holds no registry credential, and a private image fails silently at the pull.
  The twelve required fields, the `image` object, the legacy-field traps and the self-referential
  `descriptor_digest` are all on [SUBMISSION-DESCRIPTOR.md](SUBMISSION-DESCRIPTOR.md); the
  anonymous pullability check is in [RUNTIME-ENVIRONMENT.md](RUNTIME-ENVIRONMENT.md).
- The harness sets `QFBENCH_SEED`; verification reruns the top of the board (`api` statistically,
  BYO **bit-reproducibly**). Seed everything, pin models to dated snapshots, disclose training
  cutoffs; `*-latest` aliases are rejected.

## Run it locally before you ever submit

```bash
pip install "numpy==2.1.3" "pandas==2.2.3" "pyarrow==18.1.0" "jsonschema==4.23.0"
pip install "qfbench2-common @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.3.1#subdirectory=common"

mkdir -p /tmp/run/output
docker run --rm --network=none --cpus=16 --memory=128g \
  -v "$PWD/units/t2-EXAMPLE-ust-curve-1m":/input:ro -v /tmp/run/output:/output \
  my-agent:dev \
  forecast --panels /input --text /input/text/ --asof 2024-06-28 \
           --out /output/forecast.parquet

python scoring/scoring.py score --card units/t2-EXAMPLE-ust-curve-1m/card.toml \
  --forecast /tmp/run/output/forecast.parquet
```

Expect exit 0 and four `"pass"` gates. Without `--realized` you get gates only and
`"scored": false` — no realized outcomes ship publicly, so **admissibility is the only thing you
can check locally.** Then run
`python regression_suite/run_regression.py`: seconds, and the one self-test with pinned numbers
(composites to 1e-9) exercising the exact minimal `ctx {unit_dir, output_dir}` the driver passes.

Test the invocation itself first — build, run `forecast --help`, confirm exit 0 — before you invest
in the forecasting. `127` = verb not on `PATH`, `126` = not executable, anything else = your parser
ate it; all three are recorded as your failure.

## Where to look in the kit

| Path | What it gives you |
|---|---|
| `units/t2-EXAMPLE-ust-curve-1m/` | the exemplar (**one of 104**); `run_example.sh` runs end to end |
| `qfbench2_track_forecasting/scoring.py` | the real gate stack — `PARTICIPANT_FILES`, `GATES`, `_score` |
| `.../grid.py` · `limits.py` | the exact grid and every ceiling, with the exploit each one closes |
| `.../cli.py` | the reference verb — a joint Gaussian random walk that ignores the text |
| `templates/forecast_meta.example.json` | the **correct** sidecar; the README's is broken |
| `docs/SOLVER-PLAYBOOK.md` | method that scored well internally — take the modelling, ignore its filenames |

The sealed evaluation cards, the realized outcomes, `ref_scale.json` (answer-equivalent — it
inverts to the target) and the signed evaluation plan are not in the kit and never will be.

## Accelerated libraries on this track

**The sponsor stack on this track:** nvidia-nat, Numba, TensorRT-LLM + Nemotron (lora adapter).

If you do ship anything compiled, the `sm_100` trap and the CUDA ≤ 13.0 ceiling in
[RUNTIME-ENVIRONMENT.md](RUNTIME-ENVIRONMENT.md) apply.

## Bringing your own model: adapter-only, rank ≤ 64

**The shape.** Your submission ships **only a LoRA adapter** — never model weights, and never a
model server. The organizer runs the base for you: when your submission is evaluated, a dedicated
server is started *for that submission* — base: the same model behind `$MODEL_ENDPOINT`,
**`nvidia/nemotron-3-super-120b-a12b`** — with your adapter loaded at launch, and it is destroyed
when your submission finishes.

**Your contract, end to end:**

1. **Ship the adapter as `adapter_model.safetensors` + `adapter_config.json`** in your image.
   Exactly one adapter per submission. The directory the pair must sit in is not announced yet —
   it comes with the submission instructions — so keep the two files together in one directory
   that you can relocate with a single line, and do not scatter them through the image. Your image
   never runs a model server, and gets much smaller for it.
2. **Extraction is static.** The adapter is copied out of your image without executing any of your
   code, and the server starts with it already loaded. Before any unit runs, the server must list
   your adapter as a served model — an adapter that fails to load fails the submission right
   there, cheaply and with a named reason. An over-cap adapter is refused at load:
   `LoRA rank 128 is greater than max_lora_rank 64`.
3. **At run time your code sees the same contract as an `api` submission:** call
   `$MODEL_ENDPOINT` (OpenAI-compatible) with `$MODEL_NAME` — which for a BYO run names *your
   adapter*, so every call routes through it. There is nothing for you to start, configure, or
   connect to; no server lifecycle is yours.
4. **Teardown is automatic.** The server and the extracted adapter are destroyed with your
   submission's run. Nothing persists between submissions.

**Build rules:**

- **Rank ≤ 64.** Enforced by the server at load, not penalised later.
- **Declare `target_modules` accurately** in `adapter_config.json`; it is read.
- **Full fine-tuning is not permitted.** The honest reason: a full fine-tune cannot be verified as
  Nemotron-derived by any available means, so the choice is between a rule that is enforceable and
  one that is decorative.
- There is no small-weights tier — no permitted Nemotron is under ~7B, and the
  `byo-small`/`byo-large` descriptor categories are legacy names from before this rule. BYO means
  bring your own **adapter**.
- **During a BYO run the worker's GPU serves the base model.** Plan your own code as CPU plus API
  calls — your GPU use *is* the model serving.

**Testing your adapter locally** — this is the one place you run a server yourself:

```
vllm serve <base> --enable-lora --max-lora-rank 64 --lora-modules mine=<adapter-dir>
```

vLLM 0.28.0 accepts exactly `(1, 8, 16, 32, 64, 128, 256, 320, 512)` for `--max-lora-rank`, and
the **default is 16** — without the flag you will hit a much tighter cap and may conclude your
adapter is broken when it is not.

**Why rank is the number that matters:** it sets how much an adapter can change the base. On a
4096-wide layer, rank 64 carries about 3% as many parameters as the matrix it adapts, against
100% for a full fine-tune — low enough that the model underneath is unambiguously Nemotron, high
enough for real domain adaptation.
