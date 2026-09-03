# Track 3 — Simulation. Read this before writing anything.

> **Two more pages ship in this folder, and you need both.**
> [SUBMISSION-DESCRIPTOR.md](SUBMISSION-DESCRIPTOR.md) — the twelve descriptor fields, and the most
> common way a submission fails before it ever runs.
> [RUNTIME-ENVIRONMENT.md](RUNTIME-ENVIRONMENT.md) — the fleet, the `sm_100` trap, the image
> requirements, and how to check your image is actually pullable.

You are helping build a **submission** for Agenthon 2026 Track 3. You are not authoring competition
tasks. If you find yourself editing anything under `units/`, stop — that is the practice kit, and
changing it only makes your local results disagree with the real harness.

## STOP: do not carry Track 1 advice across. It inverts here.

Track 1's checks are **invariant-based** — put-call parity holds or it does not — so GPU RNG
divergence, float-reduction reassociation and unstable sorts are harmless there. A T1 agent learns
"get the maths right, the bits don't matter."

**On Track 3 the bits are the answer.** 49 of the 72 public units are Tier A, and Tier A means:

- your trace must have **exactly** the reference's row count — not within a tolerance, equal;
- on every fill row (`msg_type ∈ {ORDER_FILLED, PARTIAL_FILL}`), `order_id`, `price` and `size` must
  match the reference **positionally, in order**, with `t_ns` within **1000 ns**;
- the multiset of `(order_id, msg_type, agent_id, side, price, size)` keys — **stringified** — must
  match in *both* directions: a missing event and an extra event are each a breach;
- Kendall-tau over the whole event sequence must be **≥ 0.999**. No card overrides it — all 72 leave
  `kendall_tau_floor` unset, so the module default governs every unit.

Everything a T1 agent reaches for is therefore off the exact path: **float reductions** (last-bit
nondeterminism), **unstable sorts / argsort** (GPU tie-breaking reorders equal-priority events),
**atomics without a fixed reduction order**. `baselines/gpu_starter/README.md` says this itself.
Integer/comparison work on independent elements is bit-exact and safe; the event queue and matching
*order* cannot be vectorized without changing execution order.

The other 23 units are Tier B (agent-mix 11, calibration-stylized-facts 12) — mid-price log-return
KS ≤ 0.08, mean spread within 10 bps. Do not generalise from those either.

**An approximation that would pass T1 fails T3 outright**, and the failure is inadmissibility, not a
lower score. There is no partial credit.

The practical consequence: the organizer-pinned ABIDES fork (`baselines/abides_fork/`) reproduces
every shipped reference byte for byte, and an independently written engine must match those fill
sequences exactly to score at all. Weigh wrapping and accelerating the fork against writing your
own engine before you start.

## What you are building

One **Docker image** implementing **both verbs**. The harness picks per unit from the unit's
contents: `batch.json` + `scenarios/` → `simulate-batch`, everything else → `simulate`. Six of the
72 public units (`t3-gbatch-*`) are batched.

```
simulate       --config /input/scenario.json --out /output/trace.parquet
simulate-batch --batch-dir /input/scenarios  --out-dir /output
```

The verb arrives as the first argument after the image reference, and `LABEL
qfbench2.interface_version="2.0"` is required. `baselines/Dockerfile` uses **no `ENTRYPOINT`** and
puts both verbs on `PATH`; the `ENTRYPOINT ["python","agent.py"]` form works if your parser consumes
the verb as a leading positional. Exit `127` (not on `PATH`), `126` (not executable) or your own
parser's rejection are recorded as **your** failure — zero on that unit.

`submission.json` must declare **`category: "simulator"`**, a required closed enum. Declare it
explicitly rather than relying on any default.

> **The descriptor is twelve required fields, not one.** See
> [SUBMISSION-DESCRIPTOR.md](SUBMISSION-DESCRIPTOR.md) for the full set, why `image` is an object,
> why `models` must be present and is `[]` for a simulator that uses no model, and how to compute the
> self-referential `descriptor_digest`. The toolkit that validates it installs in one command.
> Install it and start from its fixture; do **not** write your own shim — a shim does not fail, it
> agrees with you.

## Count the corpus. Inputs are uniform; arity is not.

Parsed from all 72 `card.toml` and every scenario file under `units/`. Unlike Track 1, **every T3
input is JSON** — there is no format lottery:

```
66 units  scenario.json            (single-market)
 6 units  batch.json + scenarios/  (3, 4, 4, 5, 6, 8 subs = 30 sub-scenarios)
```

The 66 scenario files carry 12–14 top-level keys, 2.0–3.2 KB each. `agent_configs` is on **66 of 66**
and is authoritative; **`agent_mix` is on only 59**, so an agent that sizes the population from
`agent_mix` crashes on 7 units. Batch sub-names are the scenario file **stems**, and two units do not
use `sub_NN`: `t3-gbatch-hetero-mix` (`sub_00_noise … sub_04_base`) and `t3-gbatch-varsize`
(`sub_00_short … sub_03_med`) — derive the name from the filename, never synthesise it.

Scenario JSON also carries a `tolerance` block (singular). **Nothing in the scorer reads it** —
`scoring._CardPolicy` takes tolerances from `card.toml` `[scoring.params]`, and the card is not
mounted (trap 3). Treat it as documentation.

## The output contract, and it *is* uniform

Extracted from `qfbench2_track_simulation/{scoring,semantics,batch,limits}.py` — the files the gates
actually open. Unlike T1 there is no per-unit filename lottery:

| Unit shape | Files the gates open, under `/output` |
|---|---|
| single-market (66) | `trace.parquet`, `events.json`, `message_trace.parquet` |
| batch (6) | `batch_events.json` + per sub `<sub>/trace.parquet`, `<sub>/events.json`, `<sub>/message_trace.parquet` |

`limits.py` declares this a **closed allowlist**, max depth 2, with the sub list read from the
organizer's `batch.json` and never from a listing of what you produced.

`trace.parquet` is 7 columns and the dtypes are load-bearing (trap 4): `t_ns int64 · agent_id int32 ·
msg_type string · side string · price int64 · size int64 · order_id int64`.

`events.json` needs all six of `scenario_id, n_events, wall_clock_sec, events_per_sec, seed,
trace_sha256`, and four cross-checks fire: `events_per_sec == n_events/wall_clock_sec` within 5 %;
`n_events ==` the real row count; `scenario_id` and `seed` **must equal the scenario's**; and
`trace_sha256` is **recomputed** from the file you wrote — hash the parquet *after* closing it.
`batch_events.json` needs `total_events`, `wall_clock_sec`, `events_per_sec` and a `per_scenario`
list covering exactly the declared subs — no extras, no duplicates — each `n_events` equalling that
sub's real row count and summing to `total_events`.

## Six traps that are invisible until they cost you

**1. The message ledger is required on 65 of 72 units — read the cards, and emit it always.**
`requires_message_ledger = true` on **59 of 66** single units, and `batch.py::score_subs` demands a
per-sub ledger on all 6 batch units **unconditionally**, even though all six batch cards say
`false`. Total **65 of 72**; the 13 cards saying `false` are the exemplar, the six `t3-gb-*` single
throughput units, and the six batch cards (whose `false` is overridden by `score_subs`).
Missing the ledger where it is required is inadmissibility (`t3.latency_causality_violation`), so
**emit it always**: only the exemplar and the six `t3-gb-*` single throughput units can skip it,
and emitting it there too costs nothing.

Its 10 columns and self-consistency rules are non-negotiable: `seq` a contiguous `0..N-1`
permutation; `t_recv_ns - t_send_ns == latency_ns ≥ 0`; `(message_id, dst_id)` unique (**not
`message_id` alone** — broadcasts share an id, and requiring id-uniqueness rejected all 65 shipped
references); a causal parent delivered to the sender before the child is sent; `AGENT_WAKEUP` rows
self-addressed, zero latency, null `t_send_ns`. Empty fails; truncated fails a 90 %-of-reference
coverage floor.

**2. `batch_events.json` requires `wall_clock_sec`.** `batch.check_aggregate`
(`batch.py:265-271`) requires it; missing it returns
`SCHEMA_INVALID_OUTPUT: "batch_events is missing required field(s): wall_clock_sec"`. Copy the
dict from `baselines/abides_fork/simulate_batch.py`, not from any README.

**3. `/input` almost certainly holds only the scenario, not the unit directory.** `SUBMISSION_CLI.md`
says "the UNIT DIRECTORY itself is mounted at `/input`". Three sources contradict it:
`throughput/run_unit.py::_stage_input` copies **only** `scenario.json` (or only `scenarios/`);
`README.md`'s own `docker run` example mounts one file at `/input/scenario.json`;
`baselines/gpu_starter/verify_gate.sh` does the same. Under that reading there is **no
`/input/card.toml`, no `/input/manifest.json`, and for batch units no `/input/batch.json`**. We
**cannot verify** which the production Runner does — it is not in this repo. **Depend on nothing but
`/input/scenario.json` and `/input/scenarios/*.json`**; reading the card for tolerances or
`batch.json` for the roster crashes under one reading and works under the other.

**4. Emit the reference dtypes — for the sha and the io contract, not the identity keys.** The
identity-key builder is `semantics._canonical_key_matrix` (`semantics.py:203-242`), and it renders
integral floats as integers — verified by running the real gate on a float64-cast copy of a
reference trace: `check_tier_a → True`, zero breaches. So a dtype slip does **not** nuke the event
keys. What still cares: the `[io].output_trace_cols` contract (7 columns, exactly
`t_ns int64 · agent_id int32 · msg_type string · side string · price int64 · size int64 ·
order_id int64`) and **byte-exact sha equality against the reference** — a float64 parquet cannot
hash equal to an int64 one. Write the reference dtypes; just know that getting them wrong surfaces
as a sha or io breach, not as "100% missing events". `agent_id` is in the identity key, so agent
numbering must still match.

**5. Never crash, and never trust the exemplar.** One uncaught exception forfeits every gate for that
unit at once — a wrong answer is scored, an exception is not. `t3-EXAMPLE-vectorized-matching` is
unrepresentative on every axis that matters: it is the **only unit of 72 with no reference
material at all** (it cannot be self-graded), it is 1 of only 7 needing no ledger, its `README.md`
is stale (trust the cards and the kit code, not that file — and never drop `PARTIAL_FILL` rows,
9.0 % of all reference rows), and it is a **runaway**: ~36 million agent wakeups, 165× the next
largest unit. Treat it as unrunnable rather than merely slow, calibrate nothing on it, and start
from `t3-s001-price-time-priority`: Tier A, reference trace *and* ledger shipped.

**6. Contamination handling differs from Track 1.** All 72 cards carry a
`[contamination].canary_guid`, and a T1 agent will expect `g2` to reject output containing one. On
T3 the card is not in your mount, so there is nothing there for you to echo, and closed-resource is
enforced at the container boundary (`--network=none`) rather than by inspecting your output. Do not
copy input text into your output, and do not port the T1 canary defence — it is solving a problem
this track's inputs do not give you.

## Determinism is a gate, not a nicety

`telemetry._assert_repeats_reproduce_scored_tree` requires **every measured repeat** to produce an
identical `output_tree_digest` and `event_count` to the tree that was scored. Repeats that disagree
are a **participant failure**, not a flake (`every_repeat_must_pass` is asserted in
`tests/test_contract_boundary.py`). So parquet writes must be byte-reproducible: fixed compression
(`snappy`, as the baseline uses), `index=False`, no wall-clock or hostname in metadata,
deterministic row order.

The timing fields (`wall_clock_sec`, `events_per_sec`, `peak_memory_bytes`) measure time; they
cannot be byte-stable and are the harness's concern, not yours. **What you control:** make the
parquet outputs byte-identical across runs, keep `events.json` to the required keys plus
`peak_memory_bytes` / `gpu_seconds`, and put nothing else volatile in `/output`. Do not burn time
trying to make the timing fields deterministic — they measure time; they cannot be.

## The resource contract, verified

Parsed from all 72 `card.toml` `[environment]` blocks. **Zero variation**, batch units included:

```
cpus = 4 · memory = "16G" · disk = "10G" · network = "none" · gpu = true
```

There is also **no `[agent].timeout_sec` on any T3 card** — unlike T1, where it takes five values;
the production deadline is the Runner's and is not published here. `gpu = true` on 72 of 72 means the
flag no longer discriminates: the efficiency branch keys on `gpu_seconds > 0` and award eligibility
on measured `gpu_utilization`, never the card. **The GPU is optional** — T3 ranks on raw `events/sec`
and nothing else, and the organizers state that a well-optimized CPU simulator competes on equal
terms.

Hardware: **NVIDIA B200, compute capability 10.0**, driver
580.173.02, host CUDA 13.0.3, gVisor `release-20260803.0`. Build **linux/amd64**, compile for
**`sm_100`** — a PTX-only build JITs on first launch, inside your timed window. CUDA **12.x images
work**: the driver is backward compatible and `cupy-cuda12x` was verified JIT-compiling for `sm_100`
on a 12.8 base. `sm_90` cubins do not run here.

Eval container: **Python 3.13** (pinned, not a floor), NumPy 1.26.x, Pandas 2.2.x, SciPy 1.13.x
pre-installed. The ABIDES baseline is the deliberate exception — Python **3.11**, `numpy==1.26.4,
pandas==1.5.3, scipy==1.17.1, pyarrow==15.0.2, coloredlogs==15.0.1`, plus four organizer patches
(pomegranate removal, kernel message ledger, exchange-protocol STP, oracle scheduled jump) over
`jpmorganchase/abides-jpmc-public@f9cbe513`. That stack generated the frozen references; your image
is not constrained by it.

**Vendor everything.** `baselines/README.md` §4 allows Numba, CuPy, JAX, Cython and Rust/PyO3, all
"allowed but must be vendored"; network is off at run time. No image-size scoring rule is
documented anywhere in the kit — the only size cost that is real is pull time.
**cuOpt has no fit anywhere in T3**: `docs/NVIDIA-STACK.md` finds no discrete-optimization surface in
the public and sealed units and recommends dropping it from the sponsor mapping. **cuDF is
dev-side only** — vectorizing the book over a cuDF frame reorders events and fails Tier A; the
sanctioned use is `scripts/analyze_trace_cudf.py`, post-hoc forensics localizing the first divergent
event, and it never enters the eval image.

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

## The sandbox taxes syscalls and IPC — not your event loop

Measured under a real T3 card's caps:

| shape | sandbox cost |
|---|---|
| CPU arithmetic | **~7 %** |
| allocation churn / heap ops | **~0 %** (noise) |
| raw syscalls | **~85 %** |
| sockets | **67–95 % by shape** — in-process pair ~76 %, loopback TCP ~67 %, cross-container ~91–95 % |

Object churn and heap traffic — the bulk of a Python discrete-event loop — are **free** under
gVisor. What is expensive is exactly what gVisor
intercepts. The consequence is specific: **a simulator that parallelises across worker processes
talking over sockets loses most of its speedup to the sandbox**, and reads as an algorithmic failure
when it is not one. Same for per-event logging and any `fsync` in the hot path. Batch writes, stay
in-process, prefer shared memory over sockets.

GPU work has **no measurable steady-state penalty** (0.0218 s vs 0.0217 s on a repeated matmul). The
only GPU cost is **CUDA context creation, +65 to +365 ms on the first call**, and it lands inside the
timed window — create it once and reuse it across scenarios.

**Do not measure your own CPU time inside the sandbox.** gVisor misreports by ~4×: `os.times()`
reported 0.55 cores against a `--cpus=2` cap on a workload doing 91 % of `runc`'s work. That breaks
`os.times()`, `getrusage()`, `/proc/stat`, `time.process_time()` and every library built on them.
`time.perf_counter()` wall clock is fine. Measure work done.

## `simulate-batch` is the one legitimately parallel surface

The `t3-gbatch-*` family ranks on **aggregate** throughput over N independent sub-scenarios, and they
really are independent — the baseline runs them serially and the docs say "a GPU submission is
expected to batch them in parallel for a higher aggregate events/sec." This is the only parallelism
that survives the exact-match gate, because correctness stays per-sub: each output must reproduce
that scenario's **isolated** reference. `batch.score_isolation` enforces it and **one leaky sub fails
the whole batch** — book, agent or RNG state crossing between markets produces a divergent sub-trace.
The baseline gets isolation by resetting ABIDES's global id counters and re-seeding `np.random` from
the scenario seed on every sub-run; reproduce that property, and test it by running each sub alone
and diffing against the batch run. Fan out with threads or in-process workers over shared memory, not
subprocesses on sockets. 30 sub-scenarios across 6 units, 3–8 wide: enough to matter, not enough to
hide per-worker startup cost.

## Best Systems Diagnosis — the strongest promotable surface

A named special award keyed to an `nsys` → SimProfile pipeline, recipe at `docs/PROFILING.md`. It is
**diagnostic only** — never an admissibility gate, and no submission is rejected for an absent or
poor profile. Four awards ride beside the leaderboard; none re-orders it. Annotate your hot path with
NVTX ranges named for the SimProfile components — `matching`, `event_queue`, `latency`,
`agent_logic`, `io` — then:

```bash
nsys profile -o run --trace=cuda,nvtx <your simulate command>
nsys stats --report nvtx_sum --format json run.nsys-rep > nvtx.json
python scripts/nsys_to_profile.py --nsys-json nvtx.json --gpu-util <0..1> \
    --peak-memory <bytes> --out profile.json --wall-clock <sec>
```

NVTX works with no GPU, so a CPU-only submission can win this.
`throughput/simprofile.py::verify_profile` scores `quality = granularity × consistency`, where
granularity saturates at **4 components** and consistency requires component times to sum to the run
wall-clock within **±10 %**. Any breach zeroes it — annotate the *whole* hot path, use ≥ 4 components.

Two things cost you the award. **Profile on your own machine**: profiler overhead must never touch
the ranked run, and in-unit CPU accounting is wrong by ~4×, so it will tell you your simulator is
idle when it is saturated. And **a self-consistent fabrication cannot win** — `verify_profile` is
checked against host-measured wall-clock and peak memory, and when the caller has only your
self-report it passes `ground_truth_self_reported=True`, forcing `quality = 0.0`.

**Unresolved, worth asking the organizers rather than guessing:** `docs/PROFILING.md` step 5 says
"drop `profile.json` next to your `trace.parquet` in `/output`", but `limits.py` declares the C3
output allowlist as exactly `trace.parquet, events.json, message_trace.parquet` (plus
`batch_events.json` and per-sub files) — **`profile.json` is not on it**. Whether the Runner drops
non-allowlisted files or rejects the tree is not determinable from this repo.

## Run it locally before you ever submit

The exact shape `throughput/run_unit.py` uses. Note the staged input — only the scenario:

```bash
mkdir -p /tmp/t3/in /tmp/t3/out && cp units/t3-s001-price-time-priority/scenario.json /tmp/t3/in/
docker run --rm --network=none --cpus=4 --memory=16g --gpus all \
  -v /tmp/t3/in:/input:ro -v /tmp/t3/out:/output \
  my-sim:dev simulate --config /input/scenario.json --out /output/trace.parquet

mkdir -p /tmp/t3b/in /tmp/t3b/out && cp -r units/t3-gbatch-homog-4/scenarios /tmp/t3b/in/scenarios
docker run --rm --network=none --cpus=4 --memory=16g --gpus all \
  -v /tmp/t3b/in:/input:ro -v /tmp/t3b/out:/output \
  my-sim:dev simulate-batch --batch-dir /input/scenarios --out-dir /output
```

> **Do not start the sweep alphabetically.** `t3-EXAMPLE-vectorized-matching` is first by name and
> is a runaway: roughly 230 agents x 10,040 Hz x 3,600 s is about **36 million agent wakeups, ~165x
> the next largest unit**. An agent that sweeps in order hangs on unit #1 and looks like an infinite
> loop. Run it last, or with an event budget.

Expect **exit 0**, and sweep all 72 units for two things first: did it exit 0, and did it write
every file that unit's gates open. Those are the failures that score zero without ever being about
your simulation.

> **Install the toolkit before self-grading** (the one-command install is on
> [SUBMISSION-DESCRIPTOR.md](SUBMISSION-DESCRIPTOR.md)). With it,
> `from qfbench2_track_simulation import semantics, scoring, batch, limits` just works — do not
> load the modules by file path; a bare `spec_from_file_location` on `batch.py` dies on its
> relative import (`from .semantics import ...`), and `batch.check_aggregate` is the very check
> trap 2 is about. Note `build_reference_cache.py` prints "6 batch unit(s) intentionally not
> bridged", so the regression loop can never self-grade a batch unit — grade those by running each
> sub alone and diffing against the batch run.

Then self-grade against the shipped references — **71 of 72 units ship one**, far better
coverage than Track 1 gave you:

```bash
python regression_suite/build_reference_cache.py     # once; derived from units/, gitignored
python regression_suite/run_regression.py --candidate-image my-sim:dev \
    --scenarios-dir regression_suite/scenarios/ --reference-dir regression_suite/reference_traces/ \
    --output-dir run_outputs/ --workers 4
```

**Clone with Git LFS content.** Every `*.parquet` is LFS-tracked (`.gitattributes`); without it you
get 130-byte pointer stubs and every reference comparison silently compares garbage.
`build_reference_cache.py` refuses to build a cache of stubs — that refusal is your signal to run
`git lfs pull`, not a bug. When a unit fails, localize the first divergent event with
`python scripts/analyze_trace_cudf.py --candidate run_outputs/<id> --reference units/<id>`.

## What the leaderboard is, and what it is not

Admissible submissions rank on **`events/sec`, descending**, and nothing else. Both halves of that
fraction are the organizer's: the numerator is the Runner's parquet-footer row count (frozen ruling
R-3, and it must equal the reference count exactly — padding is refused at the numerator *and* by the
semantic gate), the denominator host-measured wall clock, median over the measured repeats after the
warm-up discard. **Your `events_per_sec` is never the ranked number**; it is only cross-checked for
internal consistency. Four gates run in order; failing any is inadmissible, no partial credit:

| Gate | Fails when |
|---|---|
| `g0_integrity` | trusted telemetry / exclusive instance missing; or `events.json` (`batch_events.json`) absent or unreadable |
| `g1_schema` | six required fields missing; `events_per_sec` inconsistent > 5 %; `scenario_id`/`seed` ≠ the scenario's; `trace_sha256` does not recompute; repeats disagree |
| `g2_cutoff_resource` | closed-resource violations — enforced at the container boundary (`--network=none`), not by inspecting your output |
| `g3_domain_semantics` | Tier A exactness, Tier B statistics, Family-5 stylized facts, ledger causality, batch isolation |

Treat every published throughput number as indicative of scale, not a target — the shipped
references report **3,471 to 18,046 events/sec (geomean 13,793)** on this hardware, and no
throughput floor is enforced in `scoring.py`.

## Where to look in the kit

| Path | What it gives you |
|---|---|
| `units/t3-s001-price-time-priority/` | start here — Tier A, reference trace + ledger |
| `units/t3-EXAMPLE-vectorized-matching/` | the exemplar. No reference. Stale README. Read trap 5 first |
| `units/` | 72 `public-dev` practice units (66 single + 6 batch) |
| `qfbench2_track_simulation/semantics.py` | Tier A / Tier B / ledger checks — the actual assertions |
| `qfbench2_track_simulation/scoring.py` | gate wiring, card policy, the two verifier factories |
| `qfbench2_track_simulation/batch.py` | isolation gate + aggregate anti-inflation |
| `qfbench2_track_simulation/limits.py` | the exact output allowlist |
| `baselines/abides_fork/` | the working `simulate` / `simulate-batch` reference implementation |
| `baselines/gpu_starter/` | what is and is not safe to accelerate, with a gate-compatibility proof |
| `docs/PROFILING.md` | the nsys → SimProfile recipe (Best Systems Diagnosis) |
| `docs/NVIDIA-STACK.md` | per-tool fit; why cuOpt is out and cuDF is dev-side only |
| `throughput/README.md` | the four awards and the telemetry-integrity rules |

The sealed scenarios, their reference traces and `private/scoring/final_scorer.py` are not in the
kit and never will be. Do not go looking for them.


## Corpus variations that crash a naive parser

Across all 96 scenario files:

- **`exchange_config.stp_policy` is present on all 66 single scenarios and absent on all 30 batch
  sub-scenarios.** So `d["exchange_config"]["stp_policy"]` raises on **every sub of every GB unit**.
  Use `.get()`.
- **`exchange_config.protocol_enforcement` appears on 7 files only.**
- **`latency_config.model` has four values**: `log_normal` (89), `pareto` (3), `uniform` (3),
  `deterministic` (1). **`t3-s001` — the recommended starting unit — is `uniform`, which is 3 of
  96.** Do not generalise its latency model. Handle all four.
- **`output_config.snapshot_interval_ns` is nonzero on 4 units.**
- **The biggest hazard is in `agent_configs[].params`: authoritative, but not uniform.** `MarketMaker` carries **no `arrival_rate_hz` on any of its 94
  configs** — it is cadence-driven via `rebalance_interval_ns`. Scheduling every agent off
  `params["arrival_rate_hz"]` KeyErrors on **94 of 96** files. `ValueTrader` ships three different
  key sets (`order_size_std` on 1 of 95, `fundamental_value_source` on 52 of 95).
- **Keys vary WITHIN a latency model, not just between them.** Of the 3 `pareto` files one carries
  `scale_ns` and no `mean_ns`/`sigma`; one of the 3 `uniform` files has no `sigma`. Dispatching on
  `latency_config.model` and then indexing `params["mean_ns"]` still crashes.

## `check_numeric_sanity` refuses more than dtypes

`semantics.py:122-157` requires every row to carry a **strictly positive** `price` and `size`, and
returns `False` on an empty frame. A zero-size cancel acknowledgement or a zero-price row is
inadmissible — and neither follows from the output contract or the dtype trap above. It is not
enough to get the column types right.

## Accelerated libraries on this track

**The sponsor stack on this track:** CuPy, Numba + numba-cuda, cuda-python, CCCL. Nothing here
is required or checked, but usage of these libraries is heavily encouraged.

Throughput **is** the score here, so this is the only track where a faster submission is a better
one — and also the track where naive acceleration is fatal, because 49 of 72 units score an exact
fill sequence. **A faster wrong trace scores zero.** Seed everything and avoid nondeterministic
reductions; `baselines/gpu_starter/README.md` names the unsafe patterns itself (float reductions,
unstable argsort, unordered atomics).

| library | why, on this corpus |
|---|---|
| **CuPy** | fits the `simulate-batch` family, where independent sub-scenarios are the one legitimately parallel surface |
| **Numba / numba-cuda** | matching-engine inner loops |
| **cuda-python, CCCL** | when you want the primitives rather than an array library |
| **Nsight Systems + NVTX** | the flagship — the Best Systems Diagnosis award keys off an nsys→SimProfile trace, costs you nothing, and works on a CPU-only submission |

**Where the wins actually were, measured on the reference stack:** this track's bottleneck is
startup cost and hot-loop Python, not kernels. Two byte-neutral changes worth copying — silence
per-event `warnings.warn` in the hot loop (`-W ignore` / `PYTHONWARNINGS=ignore`; ABIDES emits a
unique message per unmatched execution, so Python's default filter never dedupes), and defer heavy
imports out of module scope (`scipy.spatial.distance` alone is ~450 ms of a ~1.9 s cold import).
Profile the import path before reaching for a GPU.

`cuOpt` has no fit anywhere in T3, and `cuDF` is dev-side only — both per the kit's own
`docs/NVIDIA-STACK.md`, and both covered in the resource-contract section above.

There is **no `byo` model path on this track** — a simulator ships no model, and `category` is
`simulator`. The cross-track `sm_100` trap and the CUDA ≤ 13.0 ceiling are in
[RUNTIME-ENVIRONMENT.md](RUNTIME-ENVIRONMENT.md).
