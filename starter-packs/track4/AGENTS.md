# Track 4 — Explainability. Read this before writing anything.

> **Two more pages ship in this folder, and you need both.**
> [SUBMISSION-DESCRIPTOR.md](SUBMISSION-DESCRIPTOR.md) — the twelve descriptor fields, and the most
> common way a submission fails before it ever runs.
> [RUNTIME-ENVIRONMENT.md](RUNTIME-ENVIRONMENT.md) — the fleet, the `sm_100` trap, the image
> requirements, and how to check your image is actually pullable.

You are helping build a **submission** for Agenthon 2026 Track 4. You are not authoring competition
tasks; if you find yourself editing anything under `units/`, stop.

> **Accelerated libraries:** see the section at the end of this file — and in particular what NOT
> to embed. **Bring-your-own models and adapters are not part of this competition** — see the
> note at the end of this file.

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

The Final cannot run an image that declares a Docker `VOLUME`, including one inherited from its base
image. Such an upload is marked Failed when its run starts and does not use an attempt; remove the
`VOLUME` (or choose another base image) and upload again.

`/input` is the unit directory, read-only. `/output` is yours. T4 uses the plain `/output`
contract — the dual `/app/output` mount is **Track 1 only** (`SUBMISSION_CLI.md` invariant 8).

## Count the corpus: 11 units

**11 units, 30 branches, 69 corpus documents.** Measured across all 11 units:

- **All 69 corpus documents use a flat `text` field. Not one carries `spans[]`.** Write the `text`
  path first; keep a `spans` fallback because the schema still permits it, but do not build on it.
- **`corpus/manifest.json` is present in 10 of the 11 units, and it is NOT a corpus document.**
  `corpus.py:354-358` skips it by name, calling it "the corpus INDEX, not a corpus document". An
  agent that globs `corpus/*.json` and treats each hit as a document will index a non-document, and
  a citation to it is `CITATION_UNRESOLVED` — the unit fails closed.
- **A citable `doc_id` is the manifest-declared filename stem** (`corpus.py:399-415`, grammar
  `DOC_ID_RE`), not a free string and not necessarily the document's own `doc_id` field. They agree
  on all 69 public documents; the filename stem is the authoritative one.
- **`question.json` exists in no public unit** — it was a deprecated stub whose body was
  `{"redirect": "task.json"}`. Read `task.json`. Ignore `analysis.schema.json`'s surviving mention
  of "q.json" and the harness's old `--question` flag; no CLI defines it and no unit contains it.
- **12 `card.toml` files** — one per unit plus `templates/card.toml`. All 11 unit cards carry
  `[agent] timeout_sec = 600.0`.

**On families: `docs/CATEGORIES.md` is "an illustrative taxonomy, not a roster".** The `family` values actually
present across the 11 public units are `auction_demand`, `cpi_component_nowcast`, `credit_event`,
`eps_beat_consensus`, `eps_growth_regression`, `eps_yoy_direction`, `macro_revision_direction`,
`positioning_shift`, `post_earnings_reaction`, `rate_curve_cross_section`. **Hardcode none of
them.**

Entity rows range well beyond the exemplar's single row: the public units run to 12 rows, and the
exemplar's own `task.json` says real tasks have 3-30. Size for the range, not the sample.

## The gate that decides admissibility: roster set equality

`alignment.py:216-277` enforces **exact unique set equality with the trusted roster**, and it
raises before any metric is computed.

| you did | reason raised | source |
|---|---|---|
| omitted an entity on the roster | `ENTITY_MISSING` | `alignment.py:267-276` |
| named an entity not on the roster | `ENTITY_UNKNOWN` | `alignment.py:259-266` |
| named the same entity twice | `ENTITY_DUPLICATE` | `alignment.py:250-258` |

The docstring is blunt: *"Exact unique set equality with the trusted roster, or a participant
failure with counts."* **Answering a subset is a whole-unit failure**, not partial credit — the
roster fixes the graded set. One extra row does the same. Emit exactly the roster, once each.

Four more participant-side failures at the same layer:

- **`rank` is all-or-nothing** (`alignment.py:502-517`). Supply it for any entity and you must
  supply it for every entity, as a permutation of `1..n`. A partial ranking fails the unit.
- **A wrong `target_type` is fatal; omitting it is safe** (`alignment.py:419-425` →
  `TARGET_TYPE_MISMATCH`, a *participant* failure). If you are not certain, omit it.
- **Inverted intervals fail** (`alignment.py:307-312` → `INTERVAL_INVALID` when `lo > hi`).
- **NaN and Inf fail in any number the schema names (`point_forecast`, `interval`, `rank`, span
  offsets); rows are never silently dropped** (`alignment.py:199-213` → `NONFINITE_VALUE`; `rank`
  and offsets fail at the schema check). Sanitise before you write.

Two baseline facts worth knowing while you read the kit: `baselines/baseline_agent/formatter.py`'s
`build_answer` takes `target_type: str | None = None` and its own docstring warns against
hardcoding it — pass the card's value or omit; and `strong_rag_baseline/indexer.py` handles flat
`text` first (`:36-37`) and `spans` second (`:38-40`).

**The kit's `docs/CONCEPTS.md`, section "Faithfulness", is the canonical description of the
faithfulness rule** — from scorer 5.2.0 a per-claim penalty: the checks in order, the claim as the
hypothesis, false versus neutral claims, and the `penalty_k` / `contradiction_bar` parameters. `README.md`'s smoke-check section restates it
more briefly and its `answer.json` example is nested and valid. Read CONCEPTS.md alongside this
file; do not rely on line numbers, both files moved on 2026-09-05.

## The output contract is uniform: `answer.json`. The *shape* is where you die.

One filename, everywhere: `qfbench2_track_analysis/scoring.py` opens exactly
`output_dir / "answer.json"` and nothing else. The scorer is per-track, not per-unit, so this holds
across the corpus. An answer written anywhere else, even `/output/<dir>/answer.json`, counts as no
answer. Other files in `/output` are not scored, but under the organizers' platform rules the
output checker reads the whole tree after your process exits. If your process exited 0, the unit
scores `no_output` when the tree has any of these:

- more than 256 files, more than 4,096 files and folders together, or folders nested 8 or more levels deep;
- a symbolic or hard link, or a special file;
- a file with a setuid, setgid or sticky bit;
- a file more than 64 times larger than the disk space it occupies (a heavily sparse file);
- two names that differ only in letter case or Unicode form, a name that is not valid UTF-8 or not in Unicode NFC form, a name with a backslash or a control character, or a top-level name that starts with a letter and a colon (such as `C:`);
- no files at all, or more than 64 MiB in total (a single file is capped at 64 MiB). The same cap applies in the Final.

A process that exits non-zero scores `container_crashed` whatever its output tree holds (a run
that hits the time limit scores `resource_timeout`, and one killed for memory `resource_oom`).

In the Final, a canary string anywhere in the output is scored as contamination.

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
submitted_reasons  OPTIONAL, 1 to 3 reasons — see "How reasoning is scored" below
label, point_forecast, target_type, evidence_trace   — OPTIONAL in the schema

Additional alignment requirements:
  classification     label is required and must belong to the task's label vocabulary
  regression/ranking point_forecast is required
  any target type    a point_forecast or interval value you supply must be finite
  target_type        optional; if supplied, it must match the task
  evidence_trace     optional
```

The real contract is `entity_predictions[]`, one object per entity row — never a flat
single-object answer. Copy `templates/answer.example.json` or
`baselines/baseline_agent/formatter.py`; the README's example is also valid.

Fields the schema does not name are allowed in `answer.json`, at the top level and in each entity
row (the template's `_comment` is one); they do not fail the unit. Assume the leakage scan reads
them like every other byte of your output. This differs from `submission.json`, whose schema
refuses unknown keys.

## How faithfulness is judged: your `claim` text is the hypothesis

From Track 4 scorer 5.2.0 faithfulness is a **per-claim penalty**, not an admission gate. Each
claim is either **false** or **neutral**, and each false claim costs a share of the unit. The unit's analysis score is multiplied by
`1 - F / (F + min(T, 3 × E))`, where F is the number of false claims, T the number of other
claims and E the number of entities in the unit. A unit with no false claims is not penalised,
and a unit whose every claim is false scores 0. Other claims dilute the false ones only up to a
cap of 3 × E claims in total (three times the number of entities, counted over the whole unit,
not a limit per entity). Up to the cap the cost is the plain share: on a unit with 7 or more
entities, one false claim among twenty claims costs 5%; with fewer entities the cap is lower,
so it costs more (on a 1-entity unit, one false claim among twenty costs 1/(1 + 3) = 25%). Past
the cap, adding more claims does not shrink what a false claim costs (on a 10-entity unit, one
false claim always costs at least 1/31 of it). From scorer 5.2.2 a content-free claim is false
(rule 4 below). From scorer 5.3.0 only the first 20 claims about each entity, in the order they appear in
`answer.json`, are checked and counted; later claims about that entity are ignored, not penalised (F and
T count the first 20 only, E is unchanged), and the Development board scores with the same NLI judge as
the Final. The answer as a whole is still checked: the schema applies to every claim, and a citation
that does not resolve, is undated or is dated after the cutoff refuses the unit even in an ignored
claim. Nothing about
faithfulness refuses a unit any more; structural errors (schema, roster, embargo, malformed
citations) still do. A neutral claim is never charged and earns nothing here; evidence earns credit
only through the reasoning score. Whether your evidence supports your *forecast* is reasoning
grading's question.

A claim is **false** when any one of these holds:

1. **Wrong entity.** Every corpus document carries, in the unit's manifest, either the roster
   entities it is about (`entity_ids`) or `shared: true` for a market-wide document. A claim for
   entity E that cites a document the manifest does not list E on, and does not mark shared, is
   false (before 5.2.0 it refused the whole unit). A document about someone off the roster
   (`entity_ids: []`) is about nobody on it. You can verify this yourself from the manifest.
2. **Out-of-range citation.** Offsets that are not a real slice of the document name no passage.
3. **Malformed claim.** Empty, over 4000 characters, or over 400 judge tokens (the judge's own
   tokenizer).
4. **A figure its passage does not carry, exact code.** **Every** figure in a claim must appear
   in a span the claim cites, read against the whole cited span `text[span_start:span_end]`.
   A claim cites one span of one document (`doc_id`, `span_start`, `span_end`), so figures from
   two documents need two claims, one per document. Figures from two passages of one document fit
   in one claim only if its span covers both, within the 8,000-character cap; otherwise write two
   claims.
   Dates, years, periods, counts of periods ("13 weeks"), identifiers and form or item numbers are
   not figures; from scorer 5.2.1 neither are a date without a year ("3/20"), a month and year
   ("03/2025"), an index base ("1982-84=100"), a period label with a two-digit year ("Q4-25") or
   a rule number ("Rule 12b-2"). A number inside one of the unit's own entity names or tickers as
   `task.json` writes them ("Phillips 66", "S&P 500") is not a figure. A figure that equals a
   value you submitted and are scored on is exempt: your point forecast on a regression or ranking
   unit, and your interval bounds only on a unit whose interval leg is scored. From scorer 5.2.1
   the same scale steps as for passages apply ("$5.9bn" for 5.9 in billions, "12%" for 0.12), but
   no rounding, and the exemption reads the sign you write: a figure is not exempt when the
   direction you write contradicts the value's sign. A minus sign, accounting parentheses or a fall
   word that governs the figure ("yields declined 20 bps") make it negative, a plus sign or a rise
   word ("rose 10 bps") positive, so "declined 20 bps" is not an upper bound of 20. A half-width
   written with "±", "+/-" or "plus or minus" ("±10 bps", "+/- 10 bps", "plus or minus 10 bps")
   is exempt when it equals half the width of your scored interval, and so is the unit's interval
   level written next to an interval word ("the 90% interval").
   Your rank is never exempt. For figures in a passage, separators, scale, percent-versus-ratio,
   sign and rounding to your precision are tolerated. From scorer 5.2.1 equivalent forms of a
   number are read as the same figure in claim and passage: a fraction of a point ("1/4 percentage
   point" and "quarter-point" are 0.25, and so 25 bps; "½ point" is 0.5, and so 50 bps), a number
   in words before a unit ("four basis points", "two percent"), and glued forms ("7.3x", "$212mm",
   "1.5pp", which matches "150 bps" by the same x100 step). Such a form is now a figure, so it
   must be found in a passage you cite. A different figure still fails: 50 bps is not "1/4
   percentage point". (Under scorer 5.2.0 a
   figure was exempt only when it equalled your own value exactly, with no scale step and no sign.)
   From scorer 5.2.2 numbers inside a web address ("?id=77", "/series/42", an EDGAR path),
   disguised or not (look-alike colons and slashes, invisible characters, a scheme-less "//host",
   a "www." host), are not figures, in claim and passage alike. A claim that is word for word a
   piece of a span it cites passes the figure check whole, even if the quote is cut mid-number.
   From scorer 5.2.2 two more rules make a claim false, both by exact code:
   - **A citation over 8,000 characters** (the published per-citation cap) makes the claim
     false, whatever it states, a verbatim quote included. Cite the passage that states your
     figures, not a whole filing.
   - **A content-free claim is false.** A claim with no figure is content-free when, once the
     unit's own entity names, ids and tickers are set aside, every word left is a function word
     or an evidence/meta word, and either nothing but function words is left (the entity name
     alone) or one of the words is a filler word about the evidence: evidence, passage(s),
     excerpt, pre-cutoff, cutoff, cite(d), citing, retrieved, top-retrieved, nearest,
     placeholder, fallback, inference, context(ual), wording, document(s), source(s),
     model-entailed ("Pre-cutoff evidence selected for the submitted prediction.", "Evidence for
     X from the cited pre-cutoff passage."). Such a claim asserts nothing a passage could
     support. It is false and is not put to the judge. Any other word makes a claim contentful
     ("Guidance was cut.", "Rates rose."), and so do ordinary finance words without a filler
     word ("AAPL has no forecast.", "No quotes were submitted."). So does a digit, an arrow ("X
     ↑", "▲") or a letter outside a-z (an accented letter, another script) left once the names
     are set aside, however few words the claim has. The word lists are in
     `qfbench2_track_analysis/scoring.py`: the function words ("a", "the", "of", "for", "is",
     "has", "not", "no", "any", ...) are `CONTENT_FREE_FUNCTION_WORDS`, the evidence/meta words
     `CONTENT_FREE_META_WORDS` and the filler words `CONTENT_FREE_FILLER_ANCHORS`.
   Run the local checker (`baselines/guardrails_example/citation_rail.check_claim_rules`) before
   you write `answer.json`: it applies these rules with the scorer's own code.
5. **Contradicted.** The NLI ensemble reads each cited passage (premise) against **your `claim`
   text** (hypothesis) and returns the three-way probability that the passage contradicts it,
   averaged over its two models; above `contradiction_bar` = 0.9 the claim is false. A verbatim
   quote of a span it cites is not put to the judge. The judge reads a window of about 500
   tokens: from scorer 5.2.2 a passage longer than that is judged on the window that shares the
   most words with your claim (the first window on a tie), so a contradiction deep in a long
   passage is read.

**Claims are extractive facts.** State what the passage says, with the figures it carries. A
figure you computed (a change, a ratio, an average) belongs in `submitted_reasons` (the
`mechanism`), where derivations are judged. A quoted passage as a claim is an accurate claim.

**Citing the task table.** A value the task gives you (a row of `task.json` `entities`) is cited
with the reserved `"doc_id": "task"`. Its text is one line per `entities` row, in file order, each
`json.dumps(row, ensure_ascii=False, separators=(", ", ": "))`, joined by `"\n"`, no trailing
newline (`qfbench2_track_analysis.corpus.task_table_text(task)` builds it and each row's
offsets). The span must lie inside the citing entity's own row; another row, or a span crossing
rows, is a wrong-entity citation. A task value used in a claim without such a citation is a
figure its passage does not carry.

Two consequences that are easy to miss:

- the entity binding is at the **document** level, read from the manifest — a claim for entity E
  citing another company's filing is false however apt the passage;
- a claim with any figure that is not in its passage is false by code, not by a model — check
  every number against the exact span you cite, at the precision you wrote it.

Cards still carry `faithfulness_threshold = 0.80`: from 5.2.0 that value is read only as "use the
per-claim penalty", and any other value is refused. `penalty_k` = 1 and `contradiction_bar` = 0.9
are fixed scorer constants; a card or plan that names either is refused. **Under the previously published scorer 3.1.0 the
gate asked a different question** — whether the passage entails your *prediction* — which is now
recorded as `prediction_relevance` and never affects your score.

Every `task.json` (and each public practice unit's card, though no held-out evaluation card) still carries a `faithfulness_rubric` text written for that retired
admission gate: an NLI score above 0.5 per claim, with 80% of claims supported. It is a legacy
field, and neither scorer 5.3.0 nor the reasoning grader reads it. The rules are the ones above and
in the track's `SUBMISSION_CLI.md` ("How faithfulness is scored").

And the schema is not a sufficient pre-submission check on this track: it marks `label` and
`point_forecast` optional, while `alignment.py:453-464` rejects a missing `label` on a classification
unit and `:469-474` rejects a missing `point_forecast` on regression and ranking — both loudly, before
any metric.

## Traps that are invisible until they cost a run

**1. Support the public loader's two text representations.** Read a document's `text` field
when present; otherwise join `spans[].text` with a single space. Compute citation offsets
against that exact string:

```python
def document_text(doc):
    if "text" in doc:
        return doc["text"]
    return " ".join(sp["text"] for sp in doc["spans"])   # schema-permitted fallback
```

**2. Never pass a corpus-declared offset into a citation. Compute it against the text you
resolved.** Historic exemplar data shipped declared `start`/`end` offsets that matched nothing
under the scorer's rule; compute offsets yourself to avoid relying on stale metadata:
slice the string you actually built, and verify your citation resolves non-empty before emitting
it. The two ways a citation can resolve to nothing are not equally forgiving, and the harsher one
is the one people hit:

* an **empty or zero-width span** in a document that does exist names no passage: from scorer
  5.2.0 the claim carrying it is false (out of range), costing that claim's share of the unit;
* an **unresolvable `doc_id`** — a name not declared `role: corpus` in the unit's manifest — is a
  participant failure that never reaches the judge at all. Measured: `domain_gate_failed`, the
  unit scores W = 0.0 (the previously published scorer 3.1.0: −0.27; 0.0 on the analysis scale shows as −0.27 on the
  leaderboard, which is −0.27 + 1.27 × analysis), and no entailment is computed.

The first costs one claim's share of the unit (from scorer 5.2.0); the second refuses the unit, and no
good prediction elsewhere in it recovers that.

**3. Canaries: where they are, and where they are not.** Regex-scanning every file under
`units/` for a UUIDv4 finds **11 of 112 files carrying one — every one a `card.toml`**, one per
unit. `task.json`, `manifest.json` and all 69 corpus documents: **0 hits**. (Contrast Track 1,
where 66 of 87 `instruction.md` files carry one.)

So the canary sits in **`card.toml`, inside the `/input` mount you can read**, and **the corpus is
clean**. Quoting corpus evidence does not risk a canary echo on any public unit; echoing `card.toml`
does. **Never copy card or manifest text into the answer.**

T4's `_g2_cutoff_resource` **is active**:
`scoring.py:721-731` compares `answer["task_id"]` against the unit's and raises `TASK_ID_MISMATCH`, so
**echo `task_id` through**. A leakage scan additionally lives in shared `qfbench2_common.leakage`,
verdict-only (`clean`/`hit` plus counts), over **all bytes at any depth with no extension
allowlist**, failing closed. Assume it runs over your output tree.

**4. `target_type`: emit it from the task, or omit it — never guess.** `SUBMISSION_CLI.md`
invariant 7 says the answer "must include a matching `target_type`"; the schema makes it optional;
and a **wrong** value is fatal (`TARGET_TYPE_MISMATCH`, `alignment.py:419-425`) while omitting it
is safe. Read it from `task.json["target"]["type"]` / `card.toml [scoring].params.target_type`, and
if you cannot resolve it, omit it. The shipped baseline's `build_answer` takes it as a parameter
and warns against hardcoding — do not reintroduce a constant.

**5. Apply the embargo filter to fallback retrieval too.** The baseline's corrected
`_newest_eligible` helper selects only documents with `doc_date <= cutoff`. The older fallback
used the first indexed document without checking its date. Keep the corrected filter when
adapting the baseline, and test it with a synthetic post-cutoff document in a copy of a public
unit. If no eligible document exists, the baseline cannot produce a valid supporting citation;
a placeholder does not make an answer admissible.

**6. Never crash, and never write an empty file.** A missing, empty, unparseable or
not-an-object `answer.json` is all the same outcome — "no usable output", **attributed to you** as
`SCHEMA_INVALID_OUTPUT`. Wrap the whole body, always emit a schema-valid answer, exit 0.
Write it as UTF-8 without a byte-order mark. A byte-order mark or non-UTF-8 bytes fail: the
scorer cannot read the file as JSON, and the unit gets the worst-case score.

**7. `span_index` is documented and does not exist — and DO NOT handle it.** "Handle all three
shapes defensively" sounds prudent and is actively harmful, proved by execution:

The premise the judge sees is built by `qfbench2_common.scoring.faithfulness._doc_text`, which knows
**exactly two** shapes — `text`, then `spans[].text` joined with a single space — and returns `""`
for anything else. So if you reconstruct text from `span_index` and cite offsets into it, the
citation can pass structural smoke checks yet resolve to an **empty premise**, which cannot
support the prediction under the real judge.

Structural smoke checks do not substitute for inspecting the resolved premise and running
the judge diagnostic.

**Treat a `span_index`-only document as not citable and leave it out.** A document the scorer renders
as empty cannot support anything, and citing into a void is strictly worse than citing nothing,
because it looks clean.


**8. On a `ranking` unit the score comes from `point_forecast`, and `label` is never read for
it.** The schema marks `point_forecast` optional. It is not optional in practice:
`alignment.py:469-474` raises `SCHEMA_INVALID` — *"entity … carries no point_forecast on a
{target_type} unit"* — for **both** regression and ranking, before any metric runs.

**Put the ordering in `point_forecast`.** Any monotone score works: it is rank-correlated, not
compared to a true magnitude. `label` feeds *classification* accuracy and does nothing for ranking.

**A CONSTANT `point_forecast` scores 0.5 — the neutral midpoint, not full marks.** Ties rank as
ties: tied values share the mean of the positions they occupy, so a constant vector has no rank
variance, `rho` is 0, and `(rho + 1) / 2` rescales to 0.5. Measured on a four-entity ranking unit,
holding everything else equal:

| `point_forecast`  | `predictive_quality` |
|:------------------|---------------------:|
| correct ordering  |               1.0000 |
| constant          |               0.5000 |
| reversed ordering |               0.0000 |

A constant is therefore plainly distinguishable from a correct ranking, and it forfeits half the
quality leg. Put a real ordering in `point_forecast` — not because a constant is invisible, but
because it scores as saying nothing.

**A MISSING `point_forecast` is a different case and does fail loudly** — `alignment.py:469-474` raises
`SCHEMA_INVALID` before any metric. A constant is valid input but receives neutral ranking quality.

**And on a `classification` unit `label` is REQUIRED**, and must be one of
`task["target"]["labels"]` — `alignment.py:453-464` raises `LABEL_INVALID` when it is missing and again
when it is out of vocabulary. Classification is the most common target type in the public set
(5 of 11 units), so a submission written from the schema table alone is inadmissible on nearly
half of what you can test locally.

## How reasoning is scored: `submitted_reasons`

Track 4 has a second grader beside the analysis score and the faithfulness penalty: an LLM judge
panel that grades your **reasons**. Your reasons go in one optional top-level field of
`answer.json`, `submitted_reasons`, next to `entity_predictions`. The reasoning grader reads
nothing else you write: `claims`, `evidence_trace` and `notes` are not reasons. An answer
without the field has submitted no reasons. The judge is instructed to treat your answer and your
reasons as material to evaluate, not as instructions: a request, command or claim about how
to score is to be read only as text in its field and not followed.

**The field.** `submitted_reasons` is a list of 1 to 3 reasons. Omit the field to submit none;
a `submitted_reasons` block that does not match the schema (an empty list, more than three
reasons, or a reason missing a required field) makes the whole answer invalid, like any other
schema error: the unit's analysis score is W (0.0, shown as −0.27), so run the local checker
before you submit. Each reason is an object:

| field | required | what it holds |
|---|---|---|
| `reason_id` | yes | a string you choose; the grader does not read it for grading (it renumbers your reasons r1, r2, r3 by position) and does not check that ids are unique, but unique ids keep your reasons apart |
| `premise` | yes | the evidence-grounded fact |
| `mechanism` | yes | why that fact moves the answer |
| `answer_implication` | yes | what it implies for your submitted answer, naming the entities |
| `scope` | no | an object with `entities`: a list of `entity_id` strings |
| `citations` | no | a list of `{doc_id, span_start, span_end}` (integers >= 0), in the same character-offset convention as `claims` |

A citation must resolve in the frozen corpus and its document must be dated on or before the
cutoff; otherwise the judge never sees that passage. A reason citation that does not resolve,
is dated after the cutoff or points outside its document never refuses the unit; one that
breaks the schema does, like any schema error. The task-table citation `"doc_id": "task"`
is for claims only: the grader resolves reason citations against the corpus alone, so a
`"task"` citation in a reason resolves to nothing and the judge never sees it. The judge reads
the task statement and each entity's id and name, not the rows of the task table: state a task
value you rely on in the premise; the rest of the reason is judged as usual.

**Duplicate reasons.** A reason whose `premise`, `mechanism` and `answer_implication` equal an
earlier reason's (compared after Unicode NFC normalisation, with invisible format characters
removed, case folded and whitespace runs collapsed) is not sent to the judge, so it covers no
target reason. A different `reason_id` does not make it a new reason.

The schema is `analysis.schema.json` in
the shared toolkit (`qfbench2_common/schemas/`).

**What the judge sees, and what it grades.** The judge reads the task statement and entity
list; your per-entity answer (only the fields the unit declares, of `label`, `point_forecast`,
`interval` and `label_probs`, taken from your `entity_predictions`); each reason's `premise`,
`mechanism` and `answer_implication`; and the corpus text your citations resolve to. It does
not see `scope` or the raw citations. It compares your reasons with the unit's hidden target
reasons and grades four components, `target_reason_coverage`, `evidence_grounding`,
`inferential_link` and `answer_consistency`, plus the flags `valid_grounded_premise`,
`has_answer_implication` and `contradiction`, with 5 judge votes per cell. A target reason that
none of yours covers scores 0 against a denominator of all the unit's target reasons, so
submitting fewer reasons never scores higher. From Track 4 scorer 5.2.0 the reasoning score is
a **bonus** on top of the analysis score (final-score/v2):

    final = -0.27 + 1.27 x analysis + 0.25 x reasoning

`analysis` is your 0..1 analysis score after the per-claim faithfulness penalty (it combines
your prediction and, on units that score one, your interval; from scorer 5.2.1 the interval part
can score above 0.5 only as far as the point forecast beats the naive rule), shown on the
old leaderboard scale (`-0.27 + 1.27 x analysis`: 0 shows -0.27, the old worst case, and 1 shows
1.0); `reasoning` is in [0, 1]. The bonus is uncapped, so the maximum is 1.25. A keyed unit with
no judged reasons (missing, not judged, or refused for the deny list) adds 0: leaving reasons out never costs anything. A malformed `submitted_reasons` block is
different: it fails the answer schema and the unit scores W (see "The field" above). Reasoning is judged only on keyed (held-out) units, not on public dev units, but
the format is the same everywhere: practise it on the dev units.

**Old scores and resubmitting.** Leaderboard scores already posted under the earlier scorer stay
as they were (frozen, not re-scored). A submission made with the new starter package is scored
with scorer 5.3.0 and this final formula.

**Your answer rows.** The judge's per-entity answer is built from `entity_predictions` in the
same `answer.json`: each row keeps `entity_id` and the answer fields the unit declares, and every
other field (`claims`, `rank`, and any of `label`, `point_forecast`, `interval` or
`label_probs` the unit does not declare) is dropped before the judge sees it. The rows must name
every entity of the task's entity list exactly once. Their order does not matter: they are put in
entity-list order. A missing, extra or repeated entity, or a row without a declared field, means
that unit's reasoning is not judged and scores 0; give every row `label` (classification) or
`point_forecast` (regression, ranking) besides the required `interval`. A top-level
`submitted_answer` is not read.

**Which fields a unit declares.** The declaration is part of the unit's reasoning key, which is
organizer material and not in the unit you receive. In the released units: regression and
ranking units declare `point_forecast` and `interval`; classification units declare `label`,
plus `interval` on units that score an interval leg (numeric truth, and `interval_leg` not set
to false in `card.toml`). No unit declares `label_probs`. An undeclared field is dropped before
the judge reads your answer; it is not an error and costs nothing.

**Caps.** Reasons are checked in the order you submit them. A reason is judged only if every citation in it is at most 8,000 characters and, together with the reasons already judged, the reasons stay within 6,500 bytes and their cited evidence within 46,500 bytes. A reason that does not fit is not judged and scores 0 (every target reason stays in the denominator); later reasons are still checked. If no reason fits, the unit's reasoning scores 0. Put your strongest reason first. The 3,000-byte answer cap still applies to the whole unit. Nothing is clipped.

| cap | limit, per unit |
|---|---|
| one citation: `span_end - span_start` | 8,000 characters (cite the passage, not the document) |
| your per-entity answer as the judge reads it (each row's `entity_id` and declared fields) | 3,000 bytes |
| your reasons as the judge reads them (`reason_id`, `premise`, `mechanism`, `answer_implication`) | 6,500 bytes |
| the cited passages as the judge reads them (each resolved citation's text with its `doc_id`, offsets and reason id) | 46,500 bytes |

The last three are counted the way the grader counts what the judge reads: UTF-8 bytes of compact
JSON. Plain ASCII text is one byte per character; a line break, quote or backslash is two (it is
escaped); accented letters, typographic quotes and non-Latin scripts take two to four; a control
character six; a URI in cited text is masked with the same number of `█` (three bytes each), a
URL in your own reason text with the same number of `#` (one byte each); and
every citation adds about 75 bytes of JSON around its text plus its `doc_id` and offsets. In practice: about 6,000 characters of
plain reason text over three reasons, and about 45,000 characters of plain cited text in a few
citations. The three caps add up to the grader's 56,000-byte limit on what the judge reads from
you, so an answer within them never reaches that limit. The local checker below reports each
(`cap_answer_bytes`, `cap_reason_bytes`, `cap_evidence_bytes`).

**Deny list.** The grader refuses a unit's request, and that unit's reasoning scores 0, if the
text you wrote, including a reason the caps skip, contains any of these, case-insensitively, as a substring: `leaderboard`,
`canary`, `/home/`, `units/`, `reference/`, `outcome.json`, `team_id`, `team name`,
`participant_id`, `participant name`, `submission_id`, `other submission`. `mechanism` and
`answer_implication` are always checked. Exempt: the corpus text your citations resolve to,
and a `premise` that is a verbatim quote of a corpus document: with every URL masked, it has at
least 3 words and, the document's URLs masked the same way, appears in one corpus document. A
premise that adds any word of your own, a bare token such as `units/`, `canary` or `/home/`, and
a quote of one or two words are checked. So do not put file paths or the other listed tokens in
your own words.

URLs in reasons are masked, not refused. The deny list still runs on the URL as written, so a
URL containing a listed token (for example a path with `units/`) is refused; so is a `://` with
no scheme letters before it. Disguised URLs are masked too: look-alike colons and slashes
(fullwidth or other Unicode forms), invisible characters inside a URL, a scheme-less `//host`
and a `www.` host; a deny-listed phrase disguised the same way is refused. These are not
URLs and are left as written: a bare host or path (`example.org/a`), `mailto:` and `data:`, an
IP address, a non-breaking space between the slashes, and dot or bracket obfuscation
(`example[.]org`).

**Organiser faults.** If the grader fails on an organiser input (the task, the key, the
corpus, the judge forms or the policy), the grading run stops, the organiser fixes it and the
submission is re-graded. A unit that can never be graded is dropped from the reasoning score
for every submission, never for one submission only.

**Check it locally.** `check_submitted_reasons(answer, corpus, cutoff_date)` in
`baselines/guardrails_example/citation_rail.py` (standard library only, advisory) flags the
shape errors (`reasons_shape`; a shape error fails the whole answer, not just the reasons), citations the judge would not see, each cap including the byte backstop, and
deny-list hits. The demo runs it: `python -m baselines.guardrails_example.demo` from the track repository root.

**Worked example** on the public dev unit `units/t4-EXAMPLE-eps-beat/` in the track repository. The offsets are real: each
citation slices exactly the quoted premise out of the document's flat text, so both premises
are verbatim quotes. The label and the reasoning are illustrative, not a statement about the
outcome.

```json
{
  "task_id": "t4-EXAMPLE-eps-beat",
  "entity_predictions": [
    {
      "entity_id": "AAPL",
      "label": "beat",
      "interval": {"level": 0.90, "lo": 1.42, "hi": 1.68},
      "claims": [
        {
          "doc_id": "EDGAR_0000320193_10Q_20240202",
          "span_start": 295,
          "span_end": 433,
          "claim": "Services net sales were $23.1 billion in the December quarter, up 11.3% year over year."
        }
      ]
    }
  ],
  "submitted_reasons": [
    {
      "reason_id": "r1",
      "premise": "total revenue is expected to grow low- to mid-single digits year over year; Services revenue is expected to grow double digits year over year; gross margin is expected to be between 46.0 and 47.0 percent",
      "mechanism": "Guidance of revenue growth at a steady 46 to 47 percent gross margin means gross profit, and with it earnings per share, should rise year over year in the March quarter rather than fall.",
      "answer_implication": "Supports a label of beat for AAPL: earnings growth of that kind puts diluted EPS above the 1.50 consensus.",
      "scope": {"entities": ["AAPL"]},
      "citations": [
        {"doc_id": "EDGAR_0000320193_8K_20240201", "span_start": 711, "span_end": 914}
      ]
    },
    {
      "reason_id": "r2",
      "premise": "Services net sales were $23.1 billion for the three months ended December 30, 2023, an increase of $2.3 billion, or 11.3%, year over year.",
      "mechanism": "Services carry a gross margin far above the company average, so double-digit Services growth lifts profit faster than revenue.",
      "answer_implication": "Adds to the case that AAPL's earnings clear the consensus by more than the 5% threshold (beat).",
      "scope": {"entities": ["AAPL"]},
      "citations": [
        {"doc_id": "EDGAR_0000320193_10Q_20240202", "span_start": 295, "span_end": 433}
      ]
    }
  ]
}
```

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

**Public practice timeouts: 600 s.** The public unit cards carry `[agent] timeout_sec = 600.0`.
(`[environment].timeout` does not exist on these cards, despite
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

**How to call it.** `$MODEL_ENDPOINT` is the route origin and the API is served under `/v1`:
`POST $MODEL_ENDPOINT/v1/chat/completions`, with `Authorization: Bearer $MODEL_TOKEN` and
`model = $MODEL_NAME`. With the OpenAI client that is
`OpenAI(base_url=os.environ["MODEL_ENDPOINT"].rstrip("/") + "/v1", api_key=os.environ["MODEL_TOKEN"])`.
`$MODEL_ENDPOINT/chat/completions` (no `/v1`) is refused with 403 and a call without the bearer
with 401. Leave the injected proxy variables untouched. Full contract:
[Calling the House route](../../docs/HOUSE-MODEL.md#calling-the-house-route).


Anything you serve in-image must run **in-process** (`vllm.LLM(...)`), never as a server you POST
to over `localhost`. Container-name DNS does not resolve for a sandboxed client, and on gVisor sockets cost
67–95% by shape (in-process ~76%, loopback ~67%, cross-container **91–95%, a 10–20× slowdown**).
CPU arithmetic and heap allocation are essentially free (~7–8% / ~0%); raw syscalls are ~85% slower.
Do not measure your own CPU time with `os.times()`/`getrusage` — gVisor misreports it by ~4×. Hosts
are x86-64 B200 (sm_100); build `linux/amd64`.

## Scoring, and what a public run can and cannot tell you

`composite = 0.70 × predictive_quality + 0.30 × interval_quality` (scorer 5.3.0; the previously
published scorer 3.1.0 subtracted `0.30 × |interval_coverage − 0.90|` instead, which made wide intervals
nearly free; from scorer 5.2.0 a unit without an interval leg scores the prediction leg alone),
multiplied from scorer 5.2.0 by the faithfulness factor
`1 − F / (F + min(T, 3 × E))` (F false claims, T other claims, E entities; from scorer 5.3.0 only the
first 20 claims about each entity count), and gated on **zero embargo
violations** and the structural checks. A claim is false when it cites a document the manifest
does not bind to its entity (nor marks shared), cites an out-of-range slice, is malformed, cites a
span over 8,000 characters, states any figure no cited span carries (exact code), is content-free
(from scorer 5.2.2), or when the ensemble's three-way NLI
probability that the cited span contradicts your claim text exceeds `contradiction_bar = 0.9`
(the penalty denominator is F + min(T, 3 × E), not the raw claim count, so padding past 3 × E does
not dilute a false claim; see "How faithfulness is judged" above). `predictive_quality` is accuracy / soft ratio against the unit's naive rule,
`naive_mae/(naive_mae+mae)` / rescaled Spearman by `target_type` (on a regression unit whose
naive rule is exact, `naive_mae = 0`, only the exact truth scores 1 and any other answer scores
0). From scorer 5.2.0 accuracy and
rescaled Spearman are **anchored to the naive rule**: 0 stays 0, the unit's declared naive rule
scores 0.5, a perfect answer 1, linear in between; the anchor is the stronger of the naive rule's
quality and, on ranking, a constant forecast's 0.5.

**An ineligible or inadmissible unit does not drop out of the aggregate.** `scoring.py`: *"An
inadmissible unit scores W, not `None`. The frozen policy is a pre-committed worst value that stays
in the denominator."* `W = 0·w_a + 0·w_c = **0.0**` (shown as −0.27 on the leaderboard, which is −0.27 + 1.27 × analysis; `DOMAIN_MIN`; both legs
are ratios in [0, 1] — the previously published scorer 3.1.0 used a worst value of −0.27), and
`UnitOutcome.score` is documented "ALWAYS a float in the frozen domain — never `None`". So a risky
answer that might be ruled ineligible is **not free**: it takes W and stays in the denominator, and
no unit can be dropped by failing it.

An inadmissible answer scores W; every admissible answer scores above W on any unit with an
interval leg, because the interval leg is always positive. (On a pure-label or interval-exempt unit
the composite is the prediction leg alone from scorer 5.2.0, so an admissible answer with every
label wrong scores exactly W = 0.0 (shown as −0.27 on the leaderboard) — and still no worse than failing.) Measured on a four-entity regression
unit under scorer 5.2.1, naive rule 2.5 with interval [0.5, 3.5]:

| answer                                                         | composite |
|:---------------------------------------------------------------|----------:|
| perfect forecast, interval [0.5, 4.5] covering every value     |   +0.8737 |
| bad forecast (all 0), very wide interval [−1000, 1000]          |   +0.2008 |
| bad forecast (all 0), zero-width interval at 0                 |   +0.2297 |
| inadmissible (one roster entity omitted)                       |    0.0000 |

The interval leg charges width, so the ±1000 interval scores below the zero-width miss. (The
previously published scorer 3.1.0 charged no width, only `0.30 × |interval_coverage − 0.90|`, so widening
toward full coverage was nearly free: past 90% coverage it cost at most 0.03.) Every
admissible row stays above the inadmissible one. Answer rather than omitting. (The one surviving `None` is the public practice path, where no
`reference/outcome.json` is mounted.)

**The interval leg is an interval score against the unit's naive interval (scorer 5.3.0).** Per
row the score is the width `hi − lo` plus `2/alpha` (20 at 90%) times the distance by which the
realized value falls outside `[lo, hi]`, averaged over the roster; `naive / (naive + yours)` is
0.5 when your intervals match the naive rule's. Width costs and misses cost twenty times their
distance, so neither erring wide nor erring tight is free. From scorer 5.2.1 the interval part can
score above 0.5 only as far as the point forecast beats the naive rule:

    interval_quality = min(naive / (naive + yours), max(0.5, predictive_quality))

So an answer that keeps the naive rule's points and only narrows the band cannot score above the
naive rule, while a band worse than the naive rule's still costs in full. The uncapped value is
recorded as `raw_interval_quality` in the unit's diagnostics. (The previously published scorer 3.1.0 scored
`− w_c × |coverage − interval_level|` instead, which made erring wide nearly free.) Your
`interval.level` must equal the **unit's** `interval_level`; the schema's `const: 0.9` happens to
agree today. A unit whose reference roster carries no numeric target, or a classification unit
whose card declares `interval_leg = false` (its numeric truth is only a label code), has **no
interval leg** at all — from scorer 5.2.0 `composite = predictive_quality` (anchored), not capped
at 0.70.
A statistical prediction alone does not establish admissibility: the submitted answer must
also satisfy the citation and embargo checks. This guide makes no measured accuracy or
faithfulness-pass-rate claim for a text-blind baseline.

**What a local public run cannot show you.** Public practice units carry no resolved outcome,
so the smoke verifier returns no numerical score and marks the result non-rankable.
A clean smoke run demonstrates only the checks that smoke performs,
not predictive quality or rankable admissibility. And the faithfulness
gate needs a judge: `_g3_domain_semantics` **raises `T4OrganizerFault` when no judge is present**
(*"skipping it and defaulting faithfulness to 1.0 is the defect this scorer exists to remove"*) —
the judge is mandatory in every rankable factory, and `build_smoke_verifier` is a separately named
factory that stamps `rankable=False`.

You can run `python faithfulness/judge.py --answer <answer.json> --unit <public-unit-directory>`
as a diagnostic with its model dependencies cached. That result
does not establish platform acceptance: the rankable scorer must use the selected model
revisions, calibration and complete gate chain. See the track README's faithfulness section
for the retained two-way entailment definition and its limitations. Resolved outcomes are also
needed to measure predictive quality; an unlabeled practice run cannot supply it.

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

> **Before you upload, run one unit with the platform's own container settings** — non-root user, read-only root filesystem, `noexec` `/tmp`, process and file limits — using the command in [Run it locally the way the platform runs it](../../docs/DEVELOPMENT-RUNTIME.md#run-it-locally-the-way-the-platform-runs-it). The quick-start line above does not apply them, and an image that writes to its home directory or install path passes here and fails there.


Expect **exit 0** and a schema-valid `/tmp/run/output/answer.json`. Then, in order:

1. Validate against `analysis.schema.json` — the failures in the table above are the ones people
   actually hit. Then run `check_claim_rules(answer, unit_dir)` from
   `baselines/guardrails_example/citation_rail.py`, from the kit root: the schema alone accepts a
   NaN and a label outside the task's vocabulary, and this check refuses them as the scorer does.
2. Run a citation rail: every `doc_id` resolves, every `doc_date <= cutoff_date`, every
   `(span_start, span_end)` slices to non-empty text **under the join-with-space convention**.
   `baselines/guardrails_example/citation_rail.py` is std-lib and does this; advisory, never scored.
3. Run `faithfulness/judge.py --answer <answer.json> --unit <public-unit-directory>` for a
   local NLI diagnostic; this does not produce a leaderboard score.
4. Re-run with a synthetic post-cutoff document dropped into a copy of the corpus and confirm your
   agent neither cites it nor crashes, including through its fallback path (trap 5).
5. Test the shapes the exemplar never exercises: 30 entity rows, a `regression` target, a `ranking`
   target, a document with a flat `text` field, and an all-post-cutoff corpus.

## Where to look in the kit

| Path | What it gives you |
|---|---|
| `units/t4-EXAMPLE-eps-beat/` | a public exemplar; one entity, one family, one target type |
| `qfbench2_track_analysis/scoring.py` | the real gates and composite. Read `_g3_domain_semantics` and `_score` |
| `qfbench2_track_analysis/numeric.py` | the numeric backstop: what counts as a figure, what is tolerated, and the anchored rule's stated limit |
| `baselines/strong_rag_baseline/indexer.py` | offset arithmetic; handles flat `text` first, `spans` second |
| `baselines/strong_rag_baseline/span_finder.py` | locate model quotes as exact substrings; never trust model offsets |
| `baselines/baseline_agent/` | runnable std-lib floor. Read traps 4 and 5 first |
| `baselines/guardrails_example/` | advisory citation rail. Never scored |
| `faithfulness/judge.py` | the pinned DeBERTa NLI ensemble |
| `docs/CONCEPTS.md` § Faithfulness | the canonical description of the gate and what it does not measure |
| `docs/CATEGORIES.md` | an illustrative taxonomy — not a roster; do not hardcode families |
| `templates/answer.example.json` | the canonical output shape |

Held-out units, resolved outcomes, the sealed scorer and the canary registry are not here.

## Accelerated libraries on this track

**The sponsor stack on this track:** NeMo Guardrails, torch + transformers with pre-baked
**NeMo Retriever** embeddings, nvidia-nat. Nothing
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
- **Do NOT bundle a reader model of your own** (TensorRT-LLM, vLLM or otherwise): every
  submission runs against the House model — see the note at the end.

The cross-track `sm_100` trap and the CUDA ≤ 13.0 ceiling are in
[RUNTIME-ENVIRONMENT.md](RUNTIME-ENVIRONMENT.md).

## Bring-your-own models and adapters are not part of this competition

Ruling of 2026-09-18, superseding the adapter-only option this file used to describe. Every
Track 4 submission runs against the House model through the endpoint the runtime hands you
(`MODEL_ENDPOINT` + `/v1`, bearer `MODEL_TOKEN` — see
[docs/HOUSE-MODEL.md](../../docs/HOUSE-MODEL.md)). There is no LoRA adapter path and no in-image
language-model weights path. The only in-image neural models the Track 4 artifact policy allows
are NeMo Retriever embedding models, baked into the image at build time, as described under
"Accelerated libraries on this track". Declare `"category": "api"` and list the House model in
`models`; the former `byo-small` / `byo-large` values are invalid since toolkit 2.4.3
(`qfbench2 submission pack` refuses them), and an upload that still carries one is held by the
organizer's intake and never run. Non-LLM artifacts — fitted statistical or tree models,
calibration parameters, retrieval indexes — remain ordinary bundled artifacts under the track's
artifact policy.
