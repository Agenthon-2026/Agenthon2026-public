# Track 4 — Explainability. Read this before writing anything.

> **Two more pages ship in this folder, and you need both.**
> [SUBMISSION-DESCRIPTOR.md](SUBMISSION-DESCRIPTOR.md) — the twelve descriptor fields, and the most
> common way a submission fails before it ever runs.
> [RUNTIME-ENVIRONMENT.md](RUNTIME-ENVIRONMENT.md) — the fleet, the `sm_100` trap, the image
> requirements, and how to check your image is actually pullable.

You are helping build a **submission** for Agenthon 2026 Track 4. You are not authoring competition
tasks; if you find yourself editing anything under `units/`, stop.

> **Accelerated libraries:** see the section at the end of this file — and in particular what NOT
> to embed. **Bringing your own model?** Read the BYO section at the end first — those rules
> change what your image contains.

> **The descriptor has its own page.** `submission.json` is twelve required fields with
> `additionalProperties: false`, validated by a toolkit that installs in one command. It is the
> most common failure. See [SUBMISSION-DESCRIPTOR.md](SUBMISSION-DESCRIPTOR.md) before you build
> one, and start from the fixture it points at.

## What you are building

One **Docker image**. The harness runs it once per unit and grades the file it writes:
`analyze --task /input/task.json --corpus /input/corpus/ --out /output/answer.json`.

The verb is the **container command**. Either put `analyze` on `PATH` with no `ENTRYPOINT`, or
consume it as a leading positional
(`parser.add_argument("verb", nargs="?", default="analyze", choices=["analyze"])`).
`LABEL qfbench2.interface_version="2.0"` is required.

`/input` is the unit directory, read-only. `/output` is yours. T4 uses the plain `/output`
contract — the dual `/app/output` mount is **Track 1 only** (`SUBMISSION_CLI.md` invariant 8).

## Count the corpus: 11 units

**11 units, 30 branches, 69 corpus documents.** Measured across all 11 units:

- **All 69 corpus documents use a flat `text` field. Not one carries `spans[]`.** Write the `text`
  path first; keep a `spans` fallback because the schema still permits it, but do not build on it.
- **`corpus/manifest.json` is present in 10 of the 11 units, and it is NOT a corpus document.**
  `corpus.py:234-238` skips it by name, calling it "the corpus INDEX, not a corpus document". An
  agent that globs `corpus/*.json` and treats each hit as a document will index a non-document, and
  a citation to it is `CITATION_UNRESOLVED` — the unit fails closed.
- **A citable `doc_id` is the manifest-declared filename stem** (`corpus.py:252-268`, grammar
  `DOC_ID_RE`), not a free string and not necessarily the document's own `doc_id` field. They agree
  on all 69 public documents; the filename stem is the authoritative one.
- **`question.json` exists in no public unit** — it was a deprecated stub whose body was
  `{"redirect": "task.json"}`. Read `task.json`. Ignore `analysis.schema.json`'s surviving mention
  of "q.json" and the harness's old `--question` flag; no CLI defines it and no unit contains it.
- **12 `card.toml` files** — one per unit plus `templates/card.toml`. All 11 unit cards carry
  `[agent] timeout_sec = 600.0`.

**On families: `docs/CATEGORIES.md` is "an illustrative taxonomy, not a roster" — its own words —
and the held-out set spans more families than the public one.** The `family` values actually
present across the 11 public units are `auction_demand`, `cpi_component_nowcast`, `credit_event`,
`eps_beat_consensus`, `eps_growth_regression`, `eps_yoy_direction`, `macro_revision_direction`,
`positioning_shift`, `post_earnings_reaction`, `rate_curve_cross_section`. **Hardcode none of
them.**

Entity rows range well beyond the exemplar's single row: the public units run to 12 rows, and the
exemplar's own `task.json` says real tasks have 3-30. Size for the range, not the sample.

## The gate that decides admissibility: roster set equality

`alignment.py:142-203` enforces **exact unique set equality with the trusted roster**, and it
raises before any metric is computed.

| you did | reason raised | source |
|---|---|---|
| omitted an entity on the roster | `ENTITY_MISSING` | `alignment.py:193-200` |
| named an entity not on the roster | `ENTITY_UNKNOWN` | `alignment.py:186-190` |
| named the same entity twice | `ENTITY_DUPLICATE` | `alignment.py:177-182` |

The docstring is blunt: *"Exact unique set equality with the trusted roster, or a participant
failure with counts."* **Answering a subset is a whole-unit failure**, not partial credit — the
roster fixes the graded set. One extra row does the same. Emit exactly the roster, once each.

Four more participant-side failures at the same layer:

- **`rank` is all-or-nothing** (`alignment.py:382-397`). Supply it for any entity and you must
  supply it for every entity, as a permutation of `1..n`. A partial ranking fails the unit.
- **A wrong `target_type` is fatal; omitting it is safe** (`alignment.py:301-307` →
  `TARGET_TYPE_MISMATCH`, a *participant* failure). If you are not certain, omit it.
- **Inverted intervals fail** (`alignment.py:233-238` → `INTERVAL_INVALID` when `lo > hi`).
- **NaN and Inf fail; rows are never silently dropped** (`alignment.py:125-139` →
  `NONFINITE_VALUE`). Sanitise before you write.

Two baseline facts worth knowing while you read the kit: `baselines/baseline_agent/formatter.py`'s
`build_answer` takes `target_type: str | None = None` and its own docstring warns against
hardcoding it — pass the card's value or omit; and `strong_rag_baseline/indexer.py` handles flat
`text` first (`:36-37`) and `spans` second (`:38-40`).

**The kit's `README.md:235-286` documents the faithfulness gate correctly** — the canonical
hypothesis, the roster-as-denominator, the `tau_citation`/`faithfulness_threshold` split, and the
ranking `point_forecast` rule. Read it alongside this file. Its `answer.json` example at
`README.md:94-116` is nested and valid.

## The output contract is uniform: `answer.json`. The *shape* is where you die.

One filename, everywhere: `qfbench2_track_analysis/scoring.py` opens exactly
`output_dir / "answer.json"` and nothing else. The scorer is per-track, not per-unit, so this holds
across the corpus.

**`analysis.schema.json` does not ship in this repo.** It lives in `qfbench2-common`, which
installs in one command — see [SUBMISSION-DESCRIPTOR.md](SUBMISSION-DESCRIPTOR.md), which also
covers the install failure that actually bites (Python >= 3.13).
`g1_schema` requires:

```
top level      required: task_id, entity_predictions (minItems 1)
per entity     required: entity_id, interval, claims (minItems 1)
  interval     required: level, lo, hi   —   level is "const": 0.90
  claim        required: doc_id, span_start, span_end, claim
notes          must be an OBJECT if present
label, point_forecast, target_type, evidence_trace   — all OPTIONAL in the schema
                                                       AND NOT OPTIONAL IN PRACTICE:
                                                       alignment.py:337 rejects a missing `label`
                                                       on a classification unit, and :353 rejects a
                                                       missing `point_forecast` on regression or
                                                       ranking. The schema is not a sufficient
                                                       pre-submission check on this track.
```

The real contract is `entity_predictions[]`, one object per entity row — never a flat
single-object answer. Copy `templates/answer.example.json` or
`baselines/baseline_agent/formatter.py`; the README's example is also valid.

## How faithfulness is judged: your prose is not read

`hypothesis.py` derives a **canonical hypothesis from your prediction fields** —
`label` / `point_forecast` / `rank` / `interval` — and asks whether **your citations** entail it.
The `claim` prose you write is **not** read for entailment — accurately describing a cited
passage earns nothing by itself; the citation must entail your *prediction*.

Two consequences that are easy to miss:

- a citation only supports **the entity it is attached to** — relevance is structural, not textual;
- citations must support the **prediction**, not merely be accurately described.

And the schema is not a sufficient pre-submission check on this track: it marks `label` and
`point_forecast` optional, while `alignment.py:337` rejects a missing `label` on a classification
unit and `:353` rejects a missing `point_forecast` on regression and ranking — both loudly, before
any metric.

## Traps that are invisible until they cost a run

**1. Corpus documents are flat `text`. Write that path first.** All 87 public corpus documents
carry a plain `text` field and no `spans[]` — and the organizers measured the same across all 52
sealed held-out units (`track4-analysis-public#30`). The schema still permits a `spans[]` shape,
so keep the four-line fallback, but do not build on it:

```python
def document_text(doc):
    if "text" in doc:                       # every unit, public and sealed
        return doc["text"]
    return " ".join(sp["text"] for sp in doc["spans"])   # schema-permitted fallback
```

**2. Never pass a corpus-declared offset into a citation. Compute it against the text you
resolved.** Historic exemplar data shipped declared `start`/`end` offsets that matched nothing
under the scorer's rule; that data is fixed, but the habit is what protects you on sealed data:
slice the string you actually built, and verify your citation resolves non-empty before emitting
it. A citation that resolves to nothing gives the NLI judge an empty premise and scores zero
entailment on a track where faithfulness is the **gate**, not a component.

**3. Canaries: where they are, and where they are not.** Regex-scanning every file under
`units/` for a UUIDv4 finds **11 of 112 files carrying one — every one a `card.toml`**, one per
unit. `task.json`, `manifest.json` and all 69 corpus documents: **0 hits**. (Contrast Track 1,
where 66 of 87 `instruction.md` files carry one.)

So the canary sits in **`card.toml`, inside the `/input` mount you can read**, and **the corpus is
clean**. Quoting corpus evidence does not risk a canary echo on any public unit; echoing `card.toml`
does. **Never copy card or manifest text into the answer.**

Two caveats, stated rather than inferred. **(a)** The held-out corpora are unverifiable from here;
if an organiser ever plants a canary in a corpus document, verbatim quoting becomes the exposure
and nothing in the public kit would warn you. **(b)** T4's `_g2_cutoff_resource` **is active**:
`scoring.py:417` compares `answer["task_id"]` against the unit's and raises `TASK_ID_MISMATCH`, so
**echo `task_id` through**. A leakage scan additionally lives in shared `qfbench2_common.leakage`,
verdict-only (`clean`/`hit` plus counts), over **all bytes at any depth with no extension
allowlist**, failing closed. Assume it runs over your output tree.

**4. `target_type`: emit it from the task, or omit it — never guess.** `SUBMISSION_CLI.md`
invariant 7 says the answer "must include a matching `target_type`"; the schema makes it optional;
and a **wrong** value is fatal (`TARGET_TYPE_MISMATCH`, `alignment.py:301-307`) while omitting it
is safe. Read it from `task.json["target"]["type"]` / `card.toml [scoring].params.target_type`, and
if you cannot resolve it, omit it. The shipped baseline's `build_answer` takes it as a parameter
and warns against hardcoding — do not reintroduce a constant.

**5. The shipped baseline's fallback commits an embargo violation.** With no in-embargo retrieval
hit, `baseline_agent/cli.py` emits a placeholder claim citing `docs[0]` — the alphabetically first
indexed document, with **no `doc_date` filter applied** — and `doc_date` is confirmed by the
organizers as the field every dated corpus document carries, exemplar and held-out alike, and the
one the retriever's embargo filter already reads. On the `stale_evidence_trap` family, whose
corpus is deliberately seeded with post-cutoff documents, that path cites the poison and returns
`T4_STALE_EVIDENCE`: ineligible. Filter your fallback too.

**6. Never crash, and never write an empty file.** A missing, empty, unparseable or
not-an-object `answer.json` is all the same outcome — "no usable output", **attributed to you** as
`SCHEMA_INVALID_OUTPUT`. Wrap the whole body, always emit a schema-valid answer, exit 0.

**7. `span_index` is documented and does not exist — and DO NOT handle it.** "Handle all three
shapes defensively" sounds prudent and is actively harmful, proved by execution:

The premise the judge sees is built by `qfbench2_common.scoring.faithfulness._doc_text`, which knows
**exactly two** shapes — `text`, then `spans[].text` joined with a single space — and returns `""`
for anything else. So if you reconstruct text from `span_index` and cite offsets into it, the
citation **resolves**, **passes the embargo check**, **passes every gate you can run locally**, and
then slices to an **empty premise**: zero entailment, no error, no signal.

Such a citation passes every gate you can run locally and fails in the one place you cannot
measure.

**Treat a `span_index`-only document as not citable and leave it out.** A document the scorer renders
as empty cannot support anything, and citing into a void is strictly worse than citing nothing,
because it looks clean.


**8. On a `ranking` unit the score comes from `point_forecast`, and `label` is never read for
it.** The schema marks `point_forecast` optional. It is not optional in practice:
`alignment.py:353` raises `SCHEMA_INVALID` — *"entity … carries no point_forecast on a
{target_type} unit"* — for **both** regression and ranking, before any metric runs.

**Put the ordering in `point_forecast`.** Any monotone score works: it is rank-correlated, not
compared to a true magnitude. `label` feeds *classification* accuracy and does nothing for ranking.

**A CONSTANT `point_forecast` scores full marks — silently.** `align_predictions` re-indexes
against the trusted roster before any metric runs, and a correlation over a constant vector
resolves to the roster's own order — so a constant and a correct ranking are indistinguishable on
the leaderboard. Put a real ordering in `point_forecast`.

**A MISSING `point_forecast` is a different case and does fail loudly** — `alignment.py:353` raises
`SCHEMA_INVALID` before any metric. Absent is caught; present-but-constant is not.

**And on a `classification` unit `label` is REQUIRED**, and must be one of
`task["target"]["labels"]` — `alignment.py:337` raises `LABEL_INVALID` when it is missing and again
when it is out of vocabulary. Classification is the most common target type in the public set
(5 of 11 units), so a submission written from the schema table alone is inadmissible on nearly
half of what you can test locally.

## The resource contract

**12 `card.toml` files** (11 units + `templates/card.toml`), identical on `[environment]`:
`cpus = 16 · memory = "128G" · gpu = true · network = "restricted"`.

**The GPU: develop with it, and make sure you finish without it.** All 12 public cards grant a
device. The held-out evaluation cards are not visible to you and their resource grants are not
published. Note that `unit_caps()` resolves `bool(env.get("gpu", False))`, so a card that omits the
key inherits `False` — you cannot assume a device from silence. A design that *requires* a device
is a bet on cards you cannot observe; a design that *uses* one when present and completes on CPU is
safe either way. (The `strong_rag_baseline` ships BM25-only on a CPU-only premise; treat its
architecture as the example, not that premise.)

**And even where `gpu = true`, do not assume a device is attached.** `gpu_args()` raises
`GpuPinError` — an *organizer* failure — for any `gpu = true` card when `QFBENCH_GPU_DEVICE` is
unset, because ruling R-5 requires a device **UUID** and refuses `device=0`. `--gpus all` survives
only in the smoke profile, which stamps the run **unrankable**. Detect CUDA at runtime and fall
back to a CPU path rather than crashing.

**Timeouts: 600 s.** Every unit card carries `[agent] timeout_sec = 600.0`, and the organizers
confirm every held-out card does too. (`[environment].timeout` does not exist on any card, despite
`SUBMISSION_CLI.md` naming it.) Budget for 600 s — a third of Track 1's typical 1800 s, and not
much for per-row retrieval plus a model call across up to 30 rows. Read the card anyway. Image
size: **≤ 15 GB recommended, over 20 GB may be rejected**.

## Network: `restricted`

At run time you reach **`$MODEL_ENDPOINT`** through the audited proxy and nothing else. Call it
with **`$MODEL_NAME`**. No PyPI, no HuggingFace Hub, no NGC, no vendor APIs — `api.anthropic.com`,
`api.openai.com` and friends are refused by the proxy, the eval network is `--internal`, and **no
participant API keys exist**. Read `HTTP_PROXY`/`HTTPS_PROXY` from the environment; never hardcode
a proxy host. Vendor every dependency and every weight at build time. `TRANSFORMERS_OFFLINE=1` is
already set in the scoring environment — set it and `HF_HUB_OFFLINE=1` while testing so lazy
downloads fail on your machine instead of the leaderboard. Test with `--network=none`.

Anything you serve in-image must run **in-process** (`vllm.LLM(...)`), never as a server you POST
to over `localhost` — and a BYO submission ships a LoRA adapter, not weights (see the BYO section
below). Container-name DNS does not resolve for a sandboxed client, and on gVisor sockets cost
67–95% by shape (in-process ~76%, loopback ~67%, cross-container **91–95%, a 10–20× slowdown**).
CPU arithmetic and heap allocation are essentially free (~7–8% / ~0%); raw syscalls are ~85% slower.
Do not measure your own CPU time with `os.times()`/`getrusage` — gVisor misreports it by ~4×. Hosts
are x86-64 B200 (sm_100); build `linux/amd64`.

## Scoring, and what a public run can and cannot tell you

`composite = 0.70 × predictive_quality − 0.30 × |interval_coverage − 0.90|`, gated on **citation
faithfulness ≥ 0.80** and **zero embargo violations**. A claim counts as supported when — under
`hypothesis.py`, which derives the hypothesis from your PREDICTION fields rather than your prose —
ensemble-NLI entailment of `(cited span, claim)` exceeds `tau_citation = 0.5`; at least 80% of
claims must be supported. `predictive_quality` is accuracy / MAE skill score / rescaled Spearman by
`target_type`.

**An ineligible or inadmissible unit does not drop out of the aggregate.** `scoring.py`: *"An
inadmissible unit scores W, not `None`. The frozen policy is a pre-committed worst value that stays
in the denominator."* `W = 0·w_a − w_c·interval_level = **−0.27**` (`DOMAIN_MIN`), and
`UnitOutcome.score` is documented "ALWAYS a float in the frozen domain — never `None`". So a risky
answer that might be ruled ineligible is **not free** — it costs more than the worst admissible
answer you could have submitted instead. Answer conservatively rather than omitting. (The one
surviving `None` is the public practice path, where no `reference/outcome.json` is mounted.)

**The calibration term is a penalty on miscoverage, not a reward for coverage — and it is not
symmetric in reach.** `scoring.py:615` is
`composite = w_a * quality − w_c * abs(coverage − params.interval_level)`. The coefficient is
symmetric, but with `interval_level = 0.90` and coverage in `[0,1]` the worst over-coverage term is
`w_c × 0.10` while the worst under-coverage term is `w_c × 0.90` — **nine times larger**. Erring
wide is far cheaper than erring tight. Note also that `:216-230` compares your `interval.level`
against the **unit's** `interval_level`, not a hardcoded 0.90; the schema's `const: 0.9` happens to
agree today. A unit whose reference roster carries no numeric target has **no calibration leg** at
all — the term is dropped and `composite = 0.70 × predictive_quality`. And **text-blind is
ineligible, not merely weak**: TabPFN and gradient boosting are documented at ~0.45–0.58 accuracy
with a **0% faithfulness pass rate**. Use them for your predictive floor; you cannot submit one.

**What a local public run cannot show you — two things, both verified in the scorer.** Public units
carry no `reference/outcome.json`, so `_score` returns `{"score": None, "note": "no resolved
outcome (public smoke)"}` — a clean run tells you *admissible*, never *good*. And the faithfulness
gate needs a judge: `_g3_domain_semantics` **raises `T4OrganizerFault` when no judge is present**
(*"skipping it and defaulting faithfulness to 1.0 is the defect this scorer exists to remove"*) —
the judge is mandatory in every rankable factory, and `build_smoke_verifier` is a separately named
factory that stamps `rankable=False`. So **nothing you can run locally clears the faithfulness
gate**. Run `faithfulness/judge.py --answer ...` yourself — it needs `transformers` + `torch` and
the two pinned DeBERTa models cached locally (~3.5 GB, minutes to load on CPU) — and treat 0.80 as
a hard floor, because nothing else will tell you.

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

## Run it locally before you submit

```bash
mkdir -p /tmp/run/output
docker run --rm --network=none \
  `# drop the two flags below on a dev box with fewer cores: Docker refuses to start the` \
  `# container ("range of CPUs is from 0.01 to N") and the error looks like an image fault` \
  --cpus=16 --memory=128g \
  -v "$PWD/units/t4-EXAMPLE-eps-beat":/input:ro -v /tmp/run/output:/output \
  my-t4-agent:dev \
  analyze --task /input/task.json --corpus /input/corpus/ --out /output/answer.json
```

Expect **exit 0** and a schema-valid `/tmp/run/output/answer.json`. Then, in order:

1. Validate against `analysis.schema.json` — the failures in the table above are the ones people
   actually hit.
2. Run a citation rail: every `doc_id` resolves, every `doc_date <= cutoff_date`, every
   `(span_start, span_end)` slices to non-empty text **under the join-with-space convention**.
   `baselines/guardrails_example/citation_rail.py` is std-lib and does this; advisory, never scored.
3. `faithfulness/judge.py` for the NLI gate.
4. Re-run with a synthetic post-cutoff document dropped into a copy of the corpus and confirm your
   agent neither cites it nor crashes — that is the `stale_evidence_trap` family, and the shipped
   baseline fails it (trap 5).
5. Test the shapes the exemplar never exercises: 30 entity rows, a `regression` target, a `ranking`
   target, a document with a flat `text` field, and an all-post-cutoff corpus.

## Where to look in the kit

| Path | What it gives you |
|---|---|
| `units/t4-EXAMPLE-eps-beat/` | the exemplar — one of 12; one entity, one family, one target type |
| `qfbench2_track_analysis/scoring.py` | the real gates and composite. Read `_g3_domain_semantics` and `_score` |
| `baselines/strong_rag_baseline/indexer.py` | offset arithmetic; handles flat `text` first, `spans` second |
| `baselines/strong_rag_baseline/span_finder.py` | locate model quotes as exact substrings; never trust model offsets |
| `baselines/baseline_agent/` | runnable std-lib floor. Read traps 4 and 5 first |
| `baselines/guardrails_example/` | advisory citation rail. Never scored |
| `faithfulness/judge.py` | the pinned DeBERTa NLI ensemble |
| `docs/CATEGORIES.md` | an illustrative taxonomy — not a roster; do not hardcode families |
| `templates/answer.example.json` | the canonical output shape |

Held-out units, resolved outcomes, the sealed scorer and the canary registry are not here.

## Accelerated libraries on this track

**The sponsor stack on this track:** NeMo Guardrails, torch + transformers with pre-baked
**NeMo Retriever** embeddings, nvidia-nat, TensorRT-LLM + Nemotron reader (lora adapter). Nothing
here is required or checked, but usage of these libraries is heavily encouraged.

The ranking is composite quality gated by an NLI judge, so acceleration buys nothing directly. All
12 public cards grant a B200 — see the resource contract above for why you should still complete
without one.

- **NeMo Guardrails** is CPU-only and unaffected by any of this.
- **NeMo Retriever embeddings** are usable — bake them into the image at build time.
- **Do NOT try to embed the DeBERTa judge.** The two pinned DeBERTa-v3-large models are ~3.5 GB and
  take minutes to load on CPU, against a 600 s unit budget under `network = restricted`. It is the
  organizers' scoring instrument, not a component of your submission — run it on your own machine
  as a pre-submission check instead.
- A TensorRT-LLM / vLLM reader is the `byo` path — see below.

The cross-track `sm_100` trap and the CUDA ≤ 13.0 ceiling are in
[RUNTIME-ENVIRONMENT.md](RUNTIME-ENVIRONMENT.md).

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
