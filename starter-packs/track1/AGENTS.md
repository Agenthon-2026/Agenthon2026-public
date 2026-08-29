# Track 1 — Coding Agents. Read this before writing anything.

> **Two more pages ship in this folder, and you need both.**
> [SUBMISSION-DESCRIPTOR.md](SUBMISSION-DESCRIPTOR.md) — the twelve descriptor fields, and the most
> common way a submission fails before it ever runs.
> [RUNTIME-ENVIRONMENT.md](RUNTIME-ENVIRONMENT.md) — the fleet, the `sm_100` trap, the image
> requirements, and how to check your image is actually pullable.
> Also in this folder: `conformance.sh`, the local sweep this pack tells you to run before any push.

You are helping build a **submission** for Agenthon 2026 Track 1. You are not authoring
competition tasks. If you find yourself editing anything under `units/`, stop — that is the
practice kit, and changing it only makes your local results disagree with the real harness.

> **Accelerated libraries:** see the section at the end of this file for what is worth using on
> THIS track and what is not. Nothing is required or checked, but usage of these libraries are heavily encouraged. **Bringing your own model?** Read the
> BYO section at the end first — those rules change what your image contains.

> **The descriptor has its own page.** `submission.json` is twelve required fields with
> `additionalProperties: false`, validated by a toolkit that installs in one command. It is the
> most common failure. See [SUBMISSION-DESCRIPTOR.md](SUBMISSION-DESCRIPTOR.md) before you build
> one, and start from the fixture it points at.

## What you are building

One **Docker image**. The harness runs it once per task, offline, and grades what it writes.

The invocation contract is the **verb and its arguments**:

```
solve --task-dir /input --out /app/output
```

How you make that resolve is your choice. The FinanceZero baseline uses an explicit entrypoint:

```
ENTRYPOINT ["python", "/agent/finance_zero.py"]
CMD ["solve", "--task-dir", "/input", "--out", "/app/output"]
LABEL qfbench2.interface_version="2.0"
```

but `SUBMISSION_CLI.md` also permits building with **no `ENTRYPOINT`** and resolving the verb from
`PATH`. What is *not* optional is the label: `LABEL qfbench2.interface_version="2.0"`, required by
`SUBMISSION_CLI.md:28` and enforced by the harness. It is **not** checked by `scoring.py` --
`_g0_integrity` reads the *unit's* `card.toml` and never looks at a Docker label, so do not go
looking there to confirm it.

- `/input` is mounted read-only and **the whole unit directory is mounted there**, not just
  `instruction.md`, `card.toml` and `environment/data/`. That includes `checks/test_outputs.py`,
  which is the only machine-readable statement of the output contract. Read it at run time when it
  is present and fall back when it is not -- this is worth more than every corpus statistic below.
- `/app/output` is where you write. **Do not assume the output filename.** The exemplar writes
  `results.parquet`; it is 1 unit of 87. See the next section before you write anything.

## Do not guess the input OR output format. Read the unit.

`t1-EXAMPLE-bs-greeks-pde` ships `environment/data/options.parquet`, so an agent that starts there
and generalises will look for a parquet. Across the 79 public units that carry data, exactly **4**
contain any parquet at all. The corpus is:

```
125 csv    69 json    9 py    4 xml    4 tsv    4 html    3 zip    3 xlsx    4 parquet/pqt    1 jsonl
```

An agent hardcoding `*.parquet` fails on roughly 95% of units:
`FileNotFoundError: no .parquet input found under /input`, zero output, zero admissible,
and a leaderboard score of `-1000000000.0`. That sentinel means *nothing was admissible*, not that
the maths was wrong, and it is indistinguishable from submitting an empty zip.

So: read `instruction.md` for what the task actually gives you, read `card.toml`, and **walk
`environment/data/` for whatever is there** rather than searching for an extension you expect. The
input layout is per-unit and the exemplar is not representative of it.

So: **read `checks/test_outputs.py` and `instruction.md` for the unit you are solving, every time,
and assume nothing.** The filename, the format and the shape are all per-unit.

**And not every input is a table.** `curve_data.json` is a config object, not tabular data:

```json
{"maturities": [1, 2, 3, 5, 7, 10], "par_rates": [0.045, 0.0475, ...], "coupon_freq": 1}
```

An agent that tries to load every file as a dataframe reports "no table" and writes nothing.

## Three traps that are invisible until they cost you

**1. `instruction.md` says `/app/data`; the harness mounts `/input`.** 41 of 87 units phrase their
instructions against `/app/data`, which is where the data sits when the *unit image* is built. At
evaluation time the unit tree is mounted read-only at `/input`, so the data is at
`/input/environment/data/`. An agent that follows the instruction text literally finds nothing.
Resolve paths relative to `/input`; treat `/app/data` in prose as meaning "the unit's data dir".

**2. The canary GUID is in `instruction.md`, on 66 of 87 units.** Gate `g2` fails a submission whose
output contains a canary. So **never echo instruction or input text into your deliverable** — no
"prompt: ..." debug field, no copying the task description into a metadata blob. This is the easiest
way to fail a unit you otherwise solved.

**3. Never crash.** One uncaught exception forfeits *every* gate for that unit at once. A unit you
cannot solve should still write a well-formed file of the right name and shape and exit 0 — a wrong
answer is scored, an exception is not. Wrap the solve body and always emit something valid.

## Sweep all 87 units before you push. `conformance.sh` is in this pack.

```bash
./conformance.sh my-agent:dev /path/to/track1-coding-public
```

Runs your image against every public unit offline and reports two things: did it **exit 0**, and did
it write **a file that unit's checker expects in the output directory**. Those are the two failures
that score zero without ever being about your finance, and it catches both in minutes, locally,
before any push.

Be precise about what the second check is, because it is narrower than "the filename the checker
opens". The expected names are the quoted filenames in the unit's `checks/*.py`, **restricted to
the ones the checker resolves against the output directory** — a bare name a helper joins to
`OUTPUT_DIR`, or a path under `/app/output`. Names the checker reaches through a data or reference
root (`DATA_DIR`, `/app/data/...`, `REF_DIR`) are **inputs and reference files that ship with the
unit**; they already exist, so they are deliberately excluded. Names under a log root (`log_dir`,
`/logs/verifier`) — `reward.txt`, `diagnostic.json`, `reward_summary.json` — are the scorer's own
artifacts, written by the checker rather than expected from you, and are excluded for the same
reason. If any of them were counted, an agent that wrote none of its own deliverables would still
be credited `ok`.

**Read the `unchecked` count in its summary line.** The expected filenames are read out of every
`checks/*.py` in the unit, so the 11 units whose `test_outputs.py` names no file itself — they hand
the whole job to `checks/verifier.py` — are covered by reading that module too. **No public unit is
`UNCHECKED` today.** Should one ever be, it is reported by name; it is **not** counted as `ok`, and
it does not fail the run either. The sweep proved nothing about such a unit, so run its own checker
before you trust it. A clean run reads:

```
units 87   ok 87   crashed 0   wrote-nothing-expected 0   unchecked 0
```

It is the floor, not a pass. For whether the numbers are right:

## Run the unit's own checker before you submit. Every time.

The kit ships each public unit's real checker — the same assertions the harness runs. There is no reason to discover a
failure from a leaderboard number when you can see the assertion locally:

```bash
python -m pytest units/<unit-id>/checks/test_outputs.py -v
```

with your output in place. Do it for **several units, not just the exemplar** — the exemplar is
atypical in both input and output format, and passing it proves less than you would think.

What the checker tells you that a score never will: the exact failing assertion. `test_put_call_parity`
failing is a different afternoon from `test_required_columns` failing, and the leaderboard renders
both identically.

## Where to write

Write to **`/app/output`**, as the CMD says. The harness binds the same host directory at *both*
`/app/output` and `/output`, so either path reaches the same files:

```
qfbench2-t1-EXAMPLE-bs-greeks-pde-...
  mount  .../output/t1-EXAMPLE-bs-greeks-pde -> /output
  mount  .../output/t1-EXAMPLE-bs-greeks-pde -> /app/output
```

This matters because the units' checkers disagree with each other about which one they read —
`bs-greeks-pde` hardcodes `/output`, `zero-coupon-bootstrapping` uses `/app/output` — and the dual
mount is what makes that harmless. It is only a problem when you run **locally** and mount one path:
then the checker reports a missing `results.parquet` you can plainly see. Mount both, as the local
recipe below does.

## Your image must be publicly pullable, and a private one fails silently

The submission zip names your image **by digest**, and that image must be pullable **with no
credentials at all**: `ingest.py` pulls it inside the *program* container, which holds no registry
credential. A private image therefore fails at the pull — and in the worst way: the run still
reports **`Finished`** and lands on the same score floor as a submission that ran and was wrong.
It also fails *inconsistently*: a host that happens to have your image cached runs it fine while
every other host does not.

Before every submission, run the **anonymous pullability check** in
[RUNTIME-ENVIRONMENT.md](RUNTIME-ENVIRONMENT.md). A fresh GHCR package is **private by default**,
and the package page saying "public" is a different claim from the registry answering anonymously.

## Read the card, do not hardcode limits

Every unit ships a `card.toml`. Across all 87 public practice units the limits are identical:

```
cpus = 16 · memory = "128G" · gpu = true · network = "restricted"
```

But `[agent].timeout_sec` already varies in the public set — 1200, 1800, 2400, 3600 and 5400 all
appear, with 1800 the most common. **Read it from the card at runtime.** And read the card for
resources even when the prose disagrees: the exemplar's own `instruction.md` says "4 vCPUs, 8 GB
RAM, no GPU" while its `card.toml` declares `cpus = 16, memory = "128G", gpu = true`. The card is
the authority, on resources as well as on paths. Held-out evaluation units
are authored separately and there is no promise their limits match the practice set, so an agent
that assumes 16 cores and a GPU may meet a unit that has neither. Degrade gracefully: check what you
were given, and fall back to a CPU path rather than crashing.

## Network is `restricted`, which is stricter than it sounds

At run time you can reach **`$MODEL_ENDPOINT`** through the audited proxy and nothing else. PyPI,
conda, HuggingFace Hub, NGC and GitHub are all unreachable. Call it with **`$MODEL_NAME`**, the
pinned house-model id — it is OpenAI-compatible, free, and metered per run. Every connection is
logged (domain, bytes, timestamps) and that log is the audit artifact for the verification phase.

**Every dependency must be baked into the image at build time.** A `pip install` in your agent's
code path will fail during evaluation even though it worked while you were developing. Same for
model weights, tokenizers, and anything `transformers` would lazily download — set
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` while testing so the failure surfaces on your
machine instead of on the leaderboard.

Test locally with `--network=none`. If it passes there, `restricted` will not surprise you.

## Never vendor the task data into your image

The competition requires submissions under an **OSI-approved license**, and that licence covers
your own code — not the task data. The task data are the small input files that ship with each
coding exercise, and they come from the public QF-Bench v1 pool rather than from the organizers;
QF-Bench retains any rights in that material, and the kit redistributes it for non-commercial
academic use with attribution. Task cards, tests and harness code written by the organizers are
under this kit's own licence. The licence recorded for each individual file is in that unit's
`manifest.json`, and the kit's `DATA-LICENSE.md` explains the default. Copying unit data into your
image would redistribute it under your submission's licence, which is not ours to grant.

Keep a `.dockerignore` that excludes the kit. Ship a `LICENSE` (Apache-2.0 is fine) and keep SPDX
headers on your sources.

## Determinism

Two runs of your agent on the same unit with `--network=none` should produce byte-identical
`solution.py` and `results.parquet`. Seed everything. Non-determinism will not fail an invariant
check directly, but it makes pass@3 unpredictable and makes your own debugging much harder.

## Scoring

**pass@1 is primary, pass@3 secondary.** A task counts as passed only when *all* its unit tests
pass. Before any score is computed you must clear four admissibility gates in order:

| Gate | Fails when |
|---|---|
| `g0_integrity` | input checksums do not match `manifest.json` — i.e. you modified `/input` |
| `g1_schema` | wrong files, columns or dtypes in `/app/output` |
| `g2_cutoff_resource` | you used data after the cutoff, or abused resources |
| `g3_domain_semantics` | the finance is wrong — broken parity, violated bounds, impossible physics |

A submission that fails any gate scores **zero**, no partial credit. `g3` is where a plausible-looking
answer usually dies, and it is the gate the invariant tests implement.

The baseline to beat is **FinanceZero**, a single language-model call. It is in `baselines/`.

**If you see `-1000000000.0`, that is not a score.** It is the sentinel for *zero admissible units*,
and it is what you get for a missing file, a wrong filename, a schema mismatch or a failed
invariant — all rendered identically. It means nothing you submitted was admissible, not that your
numbers were poor. A submission can write a correct 98-row `results.parquet` with exactly the
required columns and still return this, because a *different* unit in the same task wanted
`results.json`.

So treat `-1e9` as "something was rejected before scoring" and go find it with the local checker
above. Do not tune your maths in response to it.

## Run it locally before you ever submit

This is the exact shape the harness uses. Mount the unit directory itself at `/input` read-only,
and mount one host output directory at **both** output paths:

```bash
mkdir -p /tmp/run/output

docker run --rm \
  --network=none \
  --cpus=16 --memory=128g --gpus all \
  -v "$PWD/units/t1-EXAMPLE-bs-greeks-pde":/input:ro \
  -v /tmp/run/output:/output \
  -v /tmp/run/output:/app/output \
  my-agent:dev solve --task-dir /input --out /app/output
```

`--network=none` is deliberate: it is stricter than the `restricted` mode used in scoring, so
anything that passes here will not surprise you later. Swap in `-e MODEL_ENDPOINT -e MODEL_NAME`
and drop to a proxied network only when you actually need the house model.

Set `--cpus` and `--memory` from the unit's own `card.toml` rather than copying the numbers above,
and expect **exit 0**. Then run the unit's `checks/test.sh` against the same output directory to see
whether you passed.

**The verb must resolve, or you score zero on every unit.** It arrives as the first argument after
the image reference. Three ways to get this wrong, all recorded as *your* failure rather than an
organizer fault:

| Exit | Cause |
|---|---|
| `127` | the verb is not on `PATH` |
| `126` | it is on `PATH` but not executable |
| anything else | your own parser consumed the verb and rejected it |

So test the invocation itself first — build the image, run it with `solve` and a throwaway task
dir, and confirm exit 0 — before you invest in the finance.

## Self-grading needs more mounts than the run does

The run recipe above mounts `/input` and both output paths. That is enough to *run* your agent, and
not enough to *self-grade* on every unit — the checkers open paths the run never provides:

```
17 units   /tests/reference_data      expected values for self-grading
13 units   /app/data                  the unit's data at its build-time location
 4 units   other bare /app or /tests files (prices.csv, bonds.csv, corporate_actions.json, ...)
 2 units   /app/params.json           unit-specific config at the image root
 1 unit    /app/earnings.json
 1 unit    /tests/references          note: distinct from /tests/reference_data
```

**36 of 87** units' checkers open a path the documented run recipe never mounts — so more than a third of the corpus cannot be self-graded with the recipe alone, which is
exactly when people give up and push to the fleet to find out. Mount the unit's `checks/` and `environment/`
where the checker expects them:

```bash
  -v "$PWD/units/<id>/environment/data":/app/data:ro \
  -v "$PWD/units/<id>/checks/reference_data":/tests/reference_data:ro \
```

and for the units that read a bare `/app/<file>`, mount the file from `environment/data/`. Read the
top of the unit's `test_outputs.py` — the absolute paths are declared in the first 25 lines.

## Which architecture you are graded on

The evaluation fleet is **x86-64 with NVIDIA B200 (sm_100)**. Build for `linux/amd64`.

This matters more than it looks if you use floating point: the same agent can produce parquet bytes
that are **identical within an architecture and different across architectures**, while passing every
assertion on both. If the verification phase re-runs your submission and compares outputs
byte-for-byte, an image built only for arm64 — or a multi-arch image whose manifest resolves
differently between runs — could differ from itself.

**Unresolved, and worth asking the organizers rather than guessing:** whether the reproducibility
check is architecture-pinned. Until that is answered, build single-arch `linux/amd64` and pin your
numeric stack, and do not assume a multi-arch manifest is safe.

## Performance, if you get that far

The evaluation sandbox is **gVisor**, not plain Docker. Measured on the evaluation hardware:

- CPU arithmetic, heap allocation and GPU work: **essentially free** (~7-8%, heap ~0%, GPU unaffected).
- Raw syscalls: **~85% slower**.
- **Sockets, and the shape matters enormously** — in-process pair ~76%, loopback TCP ~67%, and
  **cross-container ~91-95%, a 10-20x slowdown**. Measured on two hosts.

**And do not rely on container names resolving.** Docker's embedded DNS did not resolve for a
sandboxed client on the eval network, while an unsandboxed client on the same network resolved the
same name fine. Anything you reach must be addressed by IP or handed to you explicitly — which is
what `$MODEL_ENDPOINT` already does.

That last one has a concrete design consequence. **Do not run a model server as a separate process
and talk to it over `localhost` HTTP.** Anything you serve inside the image must run in-process —
`vllm.LLM(...)` or the TensorRT-LLM runtime object — never a server you POST to. (And see the BYO
section below: a BYO submission ships a LoRA adapter, not weights.) The natural architecture is the slow one here, and the symptom looks like a slow
model rather than a sandbox tax.

Also: do not measure your own CPU time with `os.times()` or `getrusage` inside the sandbox. gVisor
misreports CPU time by roughly 4×. Measure work completed, not CPU seconds.

## Where to look in the kit

| Path | What it gives you |
|---|---|
| `units/t1-EXAMPLE-bs-greeks-pde/` | the exemplar — start here, read its `checks/` |
| `units/` | 87 `public-dev` practice tasks (practice only, never ranked) |
| `docs/CONCEPTS.md` | plain-English explainer of pass@k, gates, images |
| `docs/CATEGORIES.md` | the ten task categories |
| `qfbench2_track_coding/scoring.py` | the actual verifier and pass@k scorer |
| `baselines/` | FinanceZero, the baseline to beat |
| `templates/` | blank `card.toml`, `Dockerfile`, test templates |
| `SUBMISSION_CLI.md` | packaging and submitting |

The held-out evaluation tasks, the oracle solutions, the sealed scorer and the canary registry
are not in the kit and never will be. Do not go looking for them, and do not let a plausible-looking
`reference/` or `expected.json` in a practice unit convince you that you have found the answer key —
public-dev units are allowed to ship reference values so you can self-grade.

## Accelerated libraries on this track

**The sponsor stack on this track:** cuDF, CuPy, Numba + numba-cuda, nvidia-nat, NeMo Guardrails,
nvmath-python, cuOpt, cuML, cuGraph, NVTX, TensorRT-LLM + Nemotron (lora adapter). Availability is
not a recommendation — everything below is where each one actually pays on this corpus.

Every unit grants a B200 (87/87), but ranking is **pass@k correctness** — so acceleration only
converts a timeout into a pass. It is a tool for a specific unit that is timing out, not a
strategy. Nothing here is required or checked.

| library | the units that justify it |
|---|---|
| **CuPy** | Monte Carlo: `t1-credit-portfolio-var-cvar` is 100k sims × 990 obligors; also most `derivatives-pricing` and `risk-management` units |
| **Numba / numba-cuda** | PDE stencils (`t1-bs-greeks-pde`), GARCH recursions. **`numba==0.60.0` is already pinned in an exemplar unit** — sanctioned precedent and the lowest-friction option here |
| **nvmath-python** | exactly **one** unit, `t1-fft-compound-poisson`. Real, and narrow |
| **TensorRT-LLM / vLLM + Nemotron** | the `byo` path — a LoRA adapter on the organizer-served base; see the BYO section |

`NVTX` is annotation and costs nothing — use it if you are profiling. `NeMo Guardrails` is CPU-only
and harmless, but there is nothing on T1 for it to guard.

**One thing unique to T1:** its checks are invariant-based, so GPU RNG divergence and float
reassociation are **safe here and nowhere else in the competition**. That removes a fear that would
otherwise stop you.

The cross-track `sm_100` trap and the CUDA ≤ 13.0 ceiling are in
[RUNTIME-ENVIRONMENT.md](RUNTIME-ENVIRONMENT.md) — read them before shipping any compiled kernel.

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
