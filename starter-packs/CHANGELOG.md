# Starter pack changelog

The starter packs will change during the Development phase. This file is how you tell whether a
change affects you.

**Watch this file** rather than re-reading the packs: on GitHub, *Watch → Custom → Releases* plus
this file's *History* view, or just check the top entry when you sit down to work.

## How to read an entry

Every change is tagged with what it costs you:

| tag | what it means for you |
| --- | --- |
| **`ACTION`** | Your submission needs a change. Read it now. |
| **`CLARIFIED`** | The behaviour did not change; the description of it was wrong or unclear. Read it if you were confused by that part. |
| **`ADDED`** | New material. Nothing you already built breaks. |

Anything that would change how you are scored gets `ACTION`, always — including a change we
consider a bug fix.

## What will not change

These are frozen for the Development phase. If one of them appears to change, it is a mistake and
we want to hear about it:

- the submission descriptor contract (`submission.json` fields and their meanings)
- the answer schema each track validates against

**The phase dates have been amended:** Development now ends October 12, 2026, followed by a
joint Final + Verification phase on October 13–25. Other competition dates are unchanged.
See the `ACTION` entry below.

**The metric each track is scored on was on this list, and is not any more.** The ranking metric
changed — see the `ACTION` entry below. Removing it is the honest thing to do: the list is only
useful if everything on it is true. A metric change always lands here with an `ACTION` tag and
never happens silently, which is the guarantee that actually protects you.

---

## Unreleased

### Track 4 scorer 5.2.2 — filler and whole-document claims are false, claim-level `citations` list removed, numbers in web addresses, reasons checked one by one

**`ACTION`** **Pull the Track 4 repository; toolkit `v2.5.1` is unchanged.** Track 4 scorer 5.2.2
needs no new toolkit release: keep toolkit `v2.5.1` installed. The Development task switches to
5.2.2 separately; the switch is announced on Agenthon-2026/track4-analysis-public#2, and
Development scores from before and after it are not comparable. The Development board runs
without the NLI contradiction check and does not grade reasons, so the four claim rules below
that are decided by exact code (content-free claims, citations over 8,000 characters, numbers in
web addresses, a claim carrying the removed `citations` key) apply on Development and in the Final
alike; the judge window and the reasoning rules apply in the Final only.

**`ACTION`** **Track 4: a content-free claim is false.** Under 5.2.1 such a claim was neutral. A
claim with no figure is content-free when, once the unit's own entity names, ids and tickers are
set aside, every word left is a function word or an evidence/meta word, and either nothing but
function words is left or one of the words is a filler word about the evidence: evidence,
passage(s), excerpt, pre-cutoff, cutoff, cite(d), citing, retrieved, top-retrieved, nearest,
placeholder, fallback, inference, context(ual), wording, document(s), source(s), model-entailed
("Pre-cutoff evidence selected for the submitted prediction."). It is false and is not put to
the judge. Any other word makes a claim contentful ("Guidance was cut."), and so do ordinary
finance words without a filler word ("AAPL has no forecast."), a digit, an arrow or a letter
outside a-z. The word lists are `CONTENT_FREE_FUNCTION_WORDS`, `CONTENT_FREE_META_WORDS` and
`CONTENT_FREE_FILLER_ANCHORS` in `qfbench2_track_analysis/scoring.py`.

**`ACTION`** **Track 4: a claim citing a span over 8,000 characters is false**, whatever it
states, a verbatim quote of the span included. Under 5.2.1 such a span anchored no figure, but a
verbatim quote of it still passed. Cite the passage that states your figures, not the whole
document.

**`ACTION`** **Track 4: numbers inside web addresses are not figures**, in claims and passages
alike ("?id=77", "/series/42", a port, an EDGAR path), including disguised addresses: look-alike
colons and slashes, invisible characters, a scheme-less "//host", a "www." host. A figure outside
the address is still checked, and the judge still reads the text as written.

**`ACTION`** **Track 4:** The claim-level `citations` list is removed: a claim cites one span of
one document with its own `doc_id`, `span_start` and `span_end`, and a claim that still carries a
`citations` key is false, like a malformed claim (never put to the judge, the list not read, the
claim's own span checked as usual); the key never refuses the unit. The Track 4 local checker
reports such a claim (`check_answer` as `claim_citations`).

**`ACTION`** **Track 4 (Final only): a long cited passage is judged on its best-matching window.**
The judge reads a window of about 500 tokens. Under 5.2.1 it read the opening window of a longer
passage; from 5.2.2 it reads the window that shares the most words with your claim, and the first
window on a tie.

**`ACTION`** **Track 4 reasoning (Final only): the size caps are checked reason by reason.** Under
5.2.1 a unit over any cap had its whole reasoning score 0. From 5.2.2 reasons are checked in the
order you submit them: a reason is judged only if every citation in it is at most 8,000
characters and, together with the reasons already judged, the reasons stay within 6,500 bytes
and their cited evidence within 46,500 bytes. A reason that does not fit is not judged and
scores 0, and later reasons are still checked. The 3,000-byte answer cap still
applies to the whole unit. Put your strongest reason first.

**`ACTION`** **Track 4 reasoning (Final only): URLs in reasons are masked, not refused.** Under
5.2.1 a URL in a reason refused the unit's reasoning. From 5.2.2 every URL, disguised ones
included, is masked with one "#" per character, and the byte caps are measured on the masked
text. The deny list still runs on the text as written, so a URL that contains a listed phrase
(for example a path with `units/`) is refused, and so is a "://" with no scheme letters before
it, and a deny-listed phrase disguised with look-alike or invisible characters.

**`ADDED`** **Track 4: the local checker applies the new rules with the scorer's own code.**
`check_claim_rules` reports `claim_over_cap` and `claim_content_free`; `check_submitted_reasons`
applies the per-reason caps, the URL masking and the deny list; `reasons_judged()` reports which
reasons will be judged and why the others are not. Run it before your agent writes `answer.json`.

**`CLARIFIED`** **Toolkit: the `submitted_reasons` description in `analysis.schema.json` is out of
date.** It still says a unit over a cap is not judged and that URLs are on the deny list. From
scorer 5.2.2 the caps are checked reason by reason and URLs are masked, as above; these entries
supersede that text. What the schema accepts is unchanged.

### Toolkit `v2.5.1` and Track 4 scorer 5.2.1 — the interval cap, claim figures in more forms, a signed participant refusal

**`ACTION`** **Reinstall the toolkit and the Track 4 package together.** Toolkit `v2.5.1` goes with
Track 4 scorer 5.2.1: pull the Track 4 repository and reinstall toolkit `v2.5.1` at the same time.
The Development task switches to 5.2.1 separately; the switch is announced on
Agenthon-2026/track4-analysis-public#2, and Development scores from before and after it are not
comparable.

**`ACTION`** **Track 4: the interval part can score above 0.5 only as far as the point forecast
beats the naive rule.** `interval_quality = min(naive / (naive + yours), max(0.5,
predictive_quality))`. An answer that keeps the naive rule's points and only narrows the band no
longer scores above the naive rule; a band worse than the naive rule's still costs in full. The
uncapped value is recorded as `raw_interval_quality` in the unit's diagnostics.

**`ACTION`** **Track 4: equivalent forms of a number are read as the same figure in claims and
passages.** A fraction of a point ("1/4 percentage point" and "quarter-point" are 0.25, so 25 bps;
"½ point" is 0.5), a number in words before a unit ("four basis points") and glued forms ("7.3x",
"$212mm", "1.5pp") are figures, so each must be found in a passage you cite. A month/day date
after a date word ("on 3/20", "ended 12/31"), a month and year ("03/2025"), an index base
("1982-84=100"), a period label with a two-digit year ("Q4-25") and a rule number ("Rule 12b-2")
are no longer figures.

**`ACTION`** **Track 4: your own forecast values are recognised in more forms.** Restating a
scored value of yours is exempt at the same scale steps as passages ("12%" for 0.12, "$5.9bn" for
5.9 in billions), with no rounding, and the exemption reads the sign you write: a value written
with a direction that contradicts its sign is not exempt. A half-width written with "±", "+/-" or
"plus or minus" is exempt when it equals half the width of your scored interval, and so is the
unit's interval level written next to an interval word ("the 90% interval").

**`ACTION`** **Track 4 reasoning (Final only): a premise is exempt from the deny list only as a
verbatim quote of one corpus document, at least three words long once URLs are masked.** The
Development board does not grade reasons.

**`ADDED`** **Toolkit: organizer data faults in the Track 4 scoring helpers stop the run as an
organizer fault.** A missing, misaligned or non-finite naive baseline in `predictive_quality`, and
non-finite bounds or truth values or an interval level outside (0, 1) in `mean_interval_score`,
now raise `OrganizerFault` instead of a plain error. Valid inputs score exactly as in `v2.5.0`.

**`ADDED`** **C2 `1.3.0` (Track 3 Final): a signed participant refusal in the run record.** A Final
run that fails only because of the submission (no stable output, no readable trace, an invalid
sidecar, repeats whose stable outputs differ, or an output tree the output checks refuse) is
scored as a participant failure with one of the existing public codes (`no_output`,
`malformed_output`, `schema_invalid` or `incomplete_output`), as any failed run is. Nothing changes
for Development.

**`CLARIFIED`** **The Development runtime guide no longer says participant access remains
held.** That clause predated the opening of Development.

**`CLARIFIED`** **Install commands now pin toolkit `v2.5.1`** in the top-level README, AGENTS.md, the
toolkit README, the glossary and the Track 4 submission guide. Tracks 1–3 need no change; their
starter packs keep `v2.4.4`, which still works.

### Track 4 — scorer 5.2.0: per-claim faithfulness, anchored scores, graded reasons

**`ACTION`** **Track 4: the 80% faithfulness gate is replaced by a per-claim penalty.** Under the
published Track 4 scorer 3.1.0, faithfulness checked each entity's prediction, not your claim
text: a prediction was supported when a span it cited entailed it (NLI above `tau_citation` =
0.5), and a unit was refused, scoring the worst case W = -0.27, unless at least 80% of the
roster's predictions were supported. From Track 4 scorer 5.2.0 your claims themselves are
checked: each claim is either false or neutral, and each unit's analysis score is multiplied
by `1 - F / (F + min(T, 3 × E))` (F false claims, T other claims, E entities in the unit). Each
false claim costs a share of the unit; other claims beyond 3 × E in total (not per entity) do not
dilute that cost; a unit with no false claims is not penalised; a unit whose every claim is false
scores 0. Content-free claims are neutral: they neither earn nor cost. `penalty_k` = 1,
`contradiction_bar` = 0.9 and the cap of 3 × E are fixed scorer constants; a card or plan naming
`penalty_k` or `contradiction_bar` is refused. Cards keep `faithfulness_threshold = 0.80`, now
read only as "use the per-claim penalty". Structural errors (schema, roster, embargo, malformed
citations) still refuse a unit.

A claim is false when it:

- cites a document the unit manifest does not label for its entity (or mark shared);
- cites offsets outside the document;
- is empty, over 4000 characters or over 400 judge tokens;
- states **any** figure that no span it cites carries. Figures are read against the whole cited
  span, not only the part the judge reads, and a span over 8,000 characters anchors no figure.
  Exempt: a figure exactly equal to your own scored value, and a number that is part of one of the
  unit's own entity names or tickers ("Phillips 66", "S&P 500"). A claim that quotes a span it
  cites word for word passes the figure check (even over the 8,000-character cap) and is not put
  to the judge;
- or when the NLI ensemble's three-way probability that a cited passage contradicts it exceeds
  `contradiction_bar` = 0.9.

Every other claim is neutral and costs nothing. A value from the task table is now citable as
`"doc_id": "task"`, with a span inside the citing entity's row of the task table.

**`ACTION`** **Track 4: classification accuracy and ranking Spearman are anchored to the unit's
naive rule.** The prediction leg maps 0 to 0, the unit's declared naive answer to 0.5 and a
perfect answer to 1, linearly in between (the anchor is the stronger of the naive rule and, on
ranking, a constant forecast). A unit without an interval leg scores the prediction leg alone
rather than 0.70 times it. Regression and the interval leg are unchanged. Nothing in your answer
format changes; the same answer can score differently on these units.

**`ACTION`** **Track 4: reasons are graded from one optional top-level field of `answer.json`,
`submitted_reasons`.** Until now nothing published said where reasons go, so no answer carried
any, and a keyed unit with no judged reasons scores 0 on reasoning. The reasoning score is an LLM
judge panel's grade of your reasons against the unit's hidden target reasons. Submit 1 to 3
reasons, each with `reason_id`, `premise`,
`mechanism` and `answer_implication` (and optionally `scope` and corpus `citations`; a `"task"`
citation in a reason resolves to nothing). The judge reads your per-entity answer from
`entity_predictions` (the unit's declared answer fields only; `claims` are never read as
reasons); the rows must name every task entity exactly once, in any order. Reasoning is judged on
keyed units only, but the format is the same on the dev units. A `submitted_reasons` block that does not match the schema (an empty list, more than three reasons, or a reason missing a required field) makes the whole answer invalid, like any other schema error: the unit's analysis score is W (0.0,
shown as -0.27), so run the local checker before you submit.

The caps apply per unit: 8,000 characters per citation, and three byte caps that add up to the
grader's 56,000-byte limit, counted as UTF-8 bytes of compact JSON: your per-entity answer as the
judge reads it (3,000 bytes), your reasons' judge-visible fields (6,500 bytes) and the cited
passages as the judge reads them (46,500 bytes). An answer within the three caps can no longer
trip the 56,000-byte limit. Over a cap, or on the deny list (URLs, file paths and identity
references in your own words), that unit's reasoning scores 0.

**`ACTION`** **Track 4: the final score is no longer a 0.75 / 0.25 blend.**
`final = -0.27 + 1.27 x analysis + 0.25 x reasoning`. `analysis` is your 0..1 analysis score after
the per-claim faithfulness penalty, shown on the old leaderboard scale (0 shows -0.27, the old
worst case; 1 shows 1.0); `reasoning` in [0, 1] is an uncapped bonus, so the maximum is 1.25.
Missing, not-judged or refused reasons add 0: leaving reasons out never costs anything (a
schema-invalid `submitted_reasons` block is different; it makes the whole answer invalid). Scores already on the
leaderboard stay frozen; a submission made with the new starter package is scored with scorer
5.2.0 and this formula.

**What to do:**

- keep claims extractive (state what the cited passage says, with its figures) and cite only
  documents labelled for the entity;
- move computed figures (changes, ratios, averages) into `submitted_reasons`, where derivations
  are judged;
- cite task-table values with `"doc_id": "task"`;
- remove false claims rather than adding extra claims to soften them;
- add 1 to 3 `submitted_reasons` and check them against the caps with the local checker
  (`cap_answer_bytes`, `cap_reason_bytes`, `cap_evidence_bytes`).

**`ADDED`** **`analysis.schema.json` accepts the optional `submitted_reasons` field.** The
change is additive: every answer that validated before still validates, and an answer without
the field is unchanged. The Track 4 local rail (`baselines/guardrails_example/citation_rail.py`
in the track repository) gains `check_submitted_reasons` (shape, caps and deny list), accepts
`"doc_id": "task"` claim citations (`check_answer(..., task=task)`), runs every deterministic
5.2.0 claim rule with the scorer's own code (`check_claim_rules`), and flags duplicate reasons and
task citations in reasons.

**`CLARIFIED`** The `submitted_reasons` schema description now states the byte caps, and the docs
say how duplicate reasons, `reason_id`, declared answer fields, task citations in reasons and
verbatim quotes over 8,000-character spans are handled.

Details: "How faithfulness is judged" and "How reasoning is scored" in
`starter-packs/track4/AGENTS.md`, and the Track 4 kit's `docs/CONCEPTS.md`, "Faithfulness".

### Toolkit `v2.5.0` — Track 4 regression scoring and the interval leg

**`ACTION`** **Reinstall the toolkit and the Track 4 package together.** Toolkit `v2.5.0` and
Track 4 scorer 5.2.0 are one release: upgrade both or neither. Toolkit `v2.5.0` with the
published Track 4 package 3.1.0 raises an error on every regression unit, because 3.1.0 does not
pass the unit's naive rule, which `v2.5.0` requires. The Track 4 package at 5.2.0 needs toolkit
`v2.5.0`.

**`ACTION`** **Track 4: a regression unit's `predictive_quality` is scored against the unit's
declared naive rule.** It is now the soft ratio `naive_mae / (naive_mae + mae)`, where
`naive_mae` is the error of the unit's `naive_values` (1.0 when both errors are zero). Matching
the naive rule scores 0.5; beating it scores above 0.5. This replaces the `1 - MAE /
dispersion_MAE` formula of `v2.4.4`. Classification and ranking units are unchanged.

**`ADDED`** **Toolkit: a missing or `NaN` entity in a regression prediction makes
`predictive_quality` 0.0 for the whole unit.** In toolkit `v2.4.4` the function scored a missing
or `NaN` entity as if it had predicted the cross-entity mean. This matters only if you call the toolkit directly: the published
Track 4 scorer 3.1.0 already refused an answer that left out an entity or gave a non-finite value
(the unit scored W = -0.27), and scorer 5.2.0 still refuses it.

**`ACTION`** **Track 4: the interval leg replaces the calibration penalty.** The published scorer
3.1.0 scored `0.70 × predictive_quality − 0.30 × |interval_coverage − 0.90|`, and an inadmissible
answer scored `W = -0.27`. From scorer 5.2.0 the composite is `0.70 * predictive_quality + 0.30 *
interval_quality` on a [0, 1] domain, and an inadmissible answer scores `W = 0.0`. From scorer 5.2.0, 0.0 on the analysis
scale shows as -0.27 on the leaderboard (leaderboard = -0.27 + 1.27 x analysis). A unit may declare `interval_leg = false`
(classification only; C1 `1.3.0` adds it as an optional `scoring_params` key), in which case it is
scored on the label alone. C1 `1.3.0` also carries each classification unit's `labels`
vocabulary (required on classification units, refused on the others); the toolkit's plan parser
accepts both keys. The current numbers are in `starter-packs/track4/AGENTS.md`.

**`ACTION`** **Track 4: in the new figure check, only an exact, scored own value is exempt.** The
published scorer 3.1.0 did not check the figures in your claims at all. From scorer 5.2.0 a claim
figure is excluded from the check only when it exactly equals a value you submitted and are
scored on: the point forecast on regression and ranking units, and the
interval bounds only when the unit's interval leg is scored. Your rank is never excluded, and no
scale, percent-versus-ratio or rounding tolerance applies to your own values (a point of `0.0523`
restated as "5.2%" is a figure the cited passage must state). Write your forecast exactly as
you submitted it, or cite a passage for any other figure. Details: `starter-packs/track4/AGENTS.md`.

**`ADDED`** **`mean_interval_score` is exported from `qfbench2_common.scoring.faithfulness`.** It
is the mean interval score over every roster row that the interval leg uses, so you can compute
it locally.

**`CLARIFIED`** **`analysis_composite` is retired.** It still computes the published scorer 3.1.0
formula (`0.70 × accuracy − 0.30 × |interval_coverage − 0.90|`) and stays exported for old
records, but nothing scores with it and its numbers do not match a 5.2.0 score.

**`CLARIFIED`** **Install commands now pin toolkit `v2.5.0`** in the top-level README, AGENTS.md, the
toolkit README, the glossary and the Track 4 submission guide. Tracks 1–3 need no change: `v2.5.0`
changes nothing for them, and their starter packs keep `v2.4.4`, which still works.

### Track 1: rule 8 clarified, rule 9 added (a pass needs run-time use of the House model)

**`ACTION`** **From 5 October 2026, 00:00 AoE (12:00 UTC), a Track 1 task counts as passed only if your agent
used the House model to solve it at run time.** A call made only to meet this rule, followed by a prepared
answer, does not count. A Track 1 submission that calls no model (`models: []`) still validates and
runs, but it earns no credit. Rule 8 now says directly that your team's own solutions to public
units may be used as examples for other units only, never on the unit they solve. From 5 October
2026, 00:00 AoE (12:00 UTC), the Track 1 leaderboard ranks only runs uploaded after 25 September 2026 at 05:00 UTC, for every
team. Every team's Track 1 Development total rises from 20 to 23 uploads from 25 September 2026 at 05:00 UTC
(still one a day). Tracks 2–4 are unchanged. The full
text is in the Track 1 README, rules 8 and 9.

**What you should do:** upload a Track 1 run after 25 September 2026 at 05:00 UTC that meets rules 8 and 9.
From 5 October 2026, 00:00 AoE (12:00 UTC), only runs uploaded after 25 September 2026 at 05:00 UTC are ranked, for every team,
including teams whose earlier runs already met both rules.

### Track 1: a run cut short by the 12-hour stage clock is now scored instead of failing

**`ACTION`** **A Track 1 run whose stage clock ends before the roster is finished is now
SCORED.** A phase has ONE total wall-clock allowance for the whole roster (see
[`docs/DEVELOPMENT-RUNTIME.md`](../docs/DEVELOPMENT-RUNTIME.md) "Execution clocks"), separate from
the per-unit ceiling the cards declare. Until now, spending it mid-roster ended the run as
`Failed` with no score and no explanation. From this change: the units the run never started are
recorded with the reason code `not_reached` and count as **not passed** in the fixed denominator,
at the worst value of the metric — exactly as a wrong, crashed, timed-out or missing output does.
Every unit that did run is scored normally, and the run gets the score it earned over the whole
roster. The count and the reason code appear on your run summary page.
Because such a run is scored rather than failed, it consumes a submission attempt like any other
completed run.

**What you should do:** divide the phase's total allowance by the number of units in the phase and
cap your agent so one slow unit cannot spend the rest of the roster's time. On Track 1's Development roster (the size is stated on the task page and in the track
README) that average is about 8 minutes per unit — well below the per-unit ceilings the
cards declare, because those ceilings do not all fit inside the stage clock. The stage clock is the
binding limit.

### House route: `low_effort` and `reasoning_budget` pass through unchanged

**`CLARIFIED`** **The House route passes `low_effort` and `reasoning_budget` through unchanged.**
Inside `chat_template_kwargs`, both reach the model as you sent them, and so does a top-level
`reasoning_budget`. We have not tested what setting them does on the model we serve, so we make no
promise about their effect. Details: `docs/HOUSE-MODEL.md`, "Development thinking controls".

### Development rosters: Track 1 goes to 86 tasks, Track 3 to 71 units

**`ACTION`** **Track 1: the Development roster is 86 tasks, not 87.** `t1-polars-api-migration` was
withdrawn on 2026-09-23 because it could not be passed. Pull `track1-coding-public` again: the pack's
sweep, the worked `conformance.sh` output and the per-unit counts in
`starter-packs/track1/AGENTS.md` are all over 86 now. Nothing is re-run — every score you already
have stands, and was measured over the 87-task roster, so it is not directly comparable with a score
measured over 86.

**`ACTION`** **Track 3: the Development roster is 71 units, not 72.** The worked exemplar
`t3-EXAMPLE-vectorized-matching` was withdrawn on 2026-09-23: it ships no reference material and was
never part of the regression set. It stays in `track3-simulation-public` as documentation, under
`examples/`, so a sweep of `units/` no longer reaches it and needs no exception. Pull the repository
again. Nothing is re-run — scores already given stand, measured over the 72-unit roster, and are not
directly comparable with a score measured over 71.

### Model budget — requests per unit; the per-unit token cap is withdrawn

**`ACTION`** **The model budget is 25 admitted requests per unit and 4,000 output tokens per
request, and nothing else.** Both are counted and applied by the House route. The earlier per-unit
figure of 1,000,000 input plus 100,000 output tokens is withdrawn and nothing replaces it, so an
agent that was pacing itself against a cumulative token allowance can stop. Budget the 25 requests
instead: an admitted request is charged before forwarding, so an upstream failure, a lost response
or an SDK retry can spend a slot. The model's context window is a separate constraint on a single
request. Details: `docs/DEVELOPMENT-RUNTIME.md` and `docs/HOUSE-MODEL.md`.

**`ADDED`** **A tie in a track's ranking score goes to the earlier Final submission.** If two
Final submissions finish a track with the same ranking score, the one uploaded earlier is ranked
ahead. Nothing about Development standings changes.

**`CLARIFIED`** **An upload the platform marks `Failed` does not consume a Development
attempt.** The platform's daily count excludes it. Held and cancelled uploads still consume one,
as before.

### Track 3 scorer — reinstall the toolkit; official repeat check narrowed to stable outputs

**`ACTION`** **Track 3: reinstall toolkit `v2.4.4` before installing the updated
`track3-simulation-public` package.** The scorer in that repository now imports
`digest_members` and `stable_output_binding` from the toolkit at package import, so on `v2.4.3` or
older `import qfbench2_track_simulation` fails with `cannot import name 'digest_members'`,
and `pip install .` stops with `No matching distribution found for qfbench2-common<3,>=2.4.4`. Run
the install command in `starter-packs/track3/SUBMISSION-DESCRIPTOR.md` (it pins `v2.4.4`), then
`pip install .` from the Track 3 repository root. Nothing changes in what you submit.

**`ACTION`** **Official timing compares the stable outputs across repeats; the scored run's
whole-tree digest is still recorded and checked as before.** Under the official profile every
repeat, warm-ups included, must reproduce the same `trace.parquet` byte for byte (the policy
`t3-stable-output-v1` hashes the file bytes), and the same `message_trace.parquet` where the card
requires the ledger (when the ledger is optional and present, it counts too); for batch units every
sub-run must reproduce both files. The files that report measurements of the run (`events.json`,
`batch_events.json`, the profile sidecar) no longer have to be byte-identical across repeats; each
is still checked for structure, scenario, seed, counts, trace hash and rate arithmetic. The
previous check compared a digest that included those volatile files and so refused honest repeats
(`track3-simulation-public#5`). Development self-report timing is unchanged. Details:
`docs/STABLE-REPEAT-EVIDENCE.md` in the Track 3 repository.

### Toolkit `v2.4.4` — organizer-side contracts for the scoring path

**`ADDED`** **Forecast-resolution and stable-repeat contracts.** The toolkit gains
`qfbench2_common.contracts.forecast_protocol`, the `stable_output_binding` and
`digest_members` helpers in `contracts.digest`, the shared record fields for Track 3 repeat
evidence, a C2 execution-fault reader and a GPU-selector check in the Development attestation
(organizer side). These are organizer-side contracts for the scoring path; nothing in a
submission changes and **no action is required by this entry**. An existing `v2.4.3` install
keeps working unless your track's install instructions require this version; if a track package
requires it, that package's own install instructions say so.

**`CLARIFIED`** **Install commands pin toolkit `v2.4.4`.** New installs use the command in your
guide; an existing `v2.4.3` install needs no change unless your track's install instructions
require this version. To see which you have:

```bash
python -c "from importlib.metadata import version; print(version('qfbench2-common'))"
```

### Toolkit `v2.4.3` — bring-your-own is out of scope

**`ACTION`** **Bring-your-own models and adapters are not part of this competition.** Ruling of
2026-09-18, superseding the adapter-only option the packs described until now. Every submission
on Tracks 1, 2 and 4 runs against the House model through the endpoint the runtime hands you
(`MODEL_ENDPOINT` + `/v1`, bearer `MODEL_TOKEN`, see `docs/HOUSE-MODEL.md`); Track 3 ships no
model. `category` is `api` (Track 3: `simulator`). The descriptor enum no longer accepts
`byo-small` or `byo-large`: `qfbench2 submission pack` refuses such a descriptor with a named
reason, and an upload that still carries one is held by the organizer's intake and never run.
If your descriptor declares one of them, change it to `api`, list the House model in `models`,
and re-pack. Non-LLM artifacts (fitted statistical or tree models, calibration parameters,
retrieval indexes) remain ordinary bundled artifacts under each track's artifact policy.

**`CLARIFIED`** **The forecasting and analysis fixtures are `api` examples.** The six packaged
`contracts/fixtures/c5/forecasting_*.json` and `analysis_*.json` descriptors now declare
`"category": "api"` with the House model in `models` and matching descriptor digests. Copy the
one for your phase as before.

**`CLARIFIED`** **Install commands pin toolkit `v2.4.3`** — superseded by `v2.4.4` above; a
`v2.4.3` install still works unless your track's install instructions require `v2.4.4`. The
original note confirmed a `v2.4.3` install with:

```bash
python -c "from importlib.metadata import version; assert version('qfbench2-common') == '2.4.3'"
```

### Toolkit `v2.4.2`

This patch updates the packaged simulation example and participant guidance. It does not
change scoring or descriptor acceptance. The Development opening also introduces the Track 1
submission limit below. Publication follows the release announcement; this entry records the
prepared changes.

**`ACTION`** **Track 1: one Development upload per team per day at opening.** Tracks 2, 3 and 4
retain 5 uploads per team per day. Every track retains a total of 20 Development uploads per
team. Use your team's designated CodaBench account; held or cancelled uploads also count.
Local validation and packaging use no attempts.

**`ACTION`** **Revised Development deadline and joint Final + Verification phase.**
Development runs through October 12, 2026. Final submission evaluation and organizer
verification share October 13–25, 2026. Each team makes one final submission per track;
there is no separate participant Verification submission. Registration and Development close together on October 12, 2026 at **23:59 Anywhere on Earth (AoE, UTC−12)**. The joint Final + Verification phase closes on October 25, 2026 at **23:59 AoE**. Other competition dates and all
task/data cutoffs are unchanged. Technical descriptor values `dev`, `final` and `verification`
remain supported; the schema has not been renamed.

**`CLARIFIED`** **The simulation Development fixture is model-free.** The packaged
`contracts/fixtures/c5/simulation_dev.json` now uses schema `1.1.0` and `models: []`, with its
matching descriptor digest. It no longer declares a model that the simulator does not call.
Existing valid schema `1.0.0` and `1.1.0` descriptors remain accepted.

**`CLARIFIED`** **Local packaging is free; uploads consume submission attempts.** All four
`TEAM-CLAIM.md` guides now distinguish local alias/pack commands from uploaded submissions.
Held or cancelled uploads count against the phase's platform submission limit even when they
receive no score. Validate locally before uploading a replacement.

**`CLARIFIED`** **Track 3 Development timing is provisional.** The starter guidance describes
current practice feedback from checked self-reported throughput on a shared Development queue.
Trusted repeat evidence and a dedicated timing instance remain official Final requirements;
the repeat-evidence repair is not delivered by this patch.

**`CLARIFIED`** **Install commands pinned toolkit `v2.4.2`** — superseded by `v2.4.3` above.

Earlier tags, including `v2.4.1`, remain unchanged.

## Toolkit `v2.4.1`

Every install command in the guides pins this tag. Everything in this section ships with it.

**`ACTION`** **Your `team_id` is derived, and `submission.zip` carries a second file.** There is
no registration page. `team_id` is computed from your website team number and Team Key
(`qfbench2 submission alias --team-number <N>`), and the zip must contain `team-claim.json`
beside `submission.json` on the first upload from your CodaBench account in each competition
(harmless afterwards). `qfbench2 submission pack --descriptor submission.json --team-number <N>
--out submission.zip` writes both. The Team Key is entered on a hidden prompt or read from
`--team-key-file`, never given as an argument, **and it never goes into the zip**: an uploaded
submission zip is downloadable by anyone once the run is placed on a leaderboard, so
`team-claim.json` carries a proof computed under your key and bound to that one `submission.json`
(schema `2.0`), not the key. Nothing about how you invoke the toolkit changes. Read
`TEAM-CLAIM.md` in your starter pack for what happens on a missing or wrong claim: everything
except a wrong `team_id` holds the upload for your next attempt instead of cancelling it. The
descriptor contract itself is unchanged; this is the value of one existing field and one extra
file in the zip.

**`CLARIFIED`** **Install commands now pin toolkit `v2.4.1`.** Re-run the install command in
your guide, then check the installed package:

```bash
python -c "from importlib.metadata import version; assert version('qfbench2-common') == '2.4.1'"
```

Toolkit `v2.3.1` rejects `models: []`. The older `v2.4.0` tag accepts it but incorrectly reports
package version `2.3.1`; `v2.4.1` corrects that version label. The existing tags remain unchanged.

**`CLARIFIED`** **Local `crps_composite` now agrees with the leaderboard on a zero-weight
component.** A component whose weight is zero and whose reference scale is exactly zero used to
divide zero by zero in the public toolkit and poison the local composite with `NaN`. The
leaderboard never scored it that way; the public copy did. It now contributes `0.0`, as the
scorer on the backend always has. A zero scale under a **non-zero** weight still raises, and a
merely small scale is still divided by — a non-finite local composite still means something is
wrong with the inputs, not with the tool.

**`ACTION`** **Track 3: report your real `wall_clock_sec`; do not make it byte-stable.** The
repeat check as published requires an identical `output_tree_digest` across measured repeats,
and `events.json` inside that tree is required to carry a real wall-clock figure, which cannot be
identical across repeats. Both statements describe the code; together they refuse an honest
submission. The Track 3 starter pack now carries the defect as a callout: report real numbers,
do not work around the check, and the repair (the side that produces the per-repeat digest has
to change) is tracked at `Agenthon2026#116`. If you built a workaround that pins the timing
fields, remove it — the check is what is wrong, not your output. This does not affect
Development, which ranks through the practice factory.

**`CLARIFIED`** **`qfbench2 smoke` no longer shows you a traceback for a failure that is ours.**
A track with no local preview factory, or a preview that fails on our side, used to end in an
uncaught `OrganizerFault` traceback. It now says plainly that nothing you did caused it and
where to report it. No track hits this today; it is there so that the first time it happens the
message is right.

**`CLARIFIED`** Guide corrections, no behaviour change: the Track 4 guide describes the retained
scoring, baseline fallback and smoke behaviour as they are; the Track 2 guide and `common/README`
state the House API allowance and what a local preview does and does not cover; Track 1 ships no
official baseline agent, and the guide no longer promises one.

## Shipped earlier, never dated

The three entries below have been live in every toolkit you could install — the ranking and
public-safety changes since `v2.3.1`, `models: []` since `v2.4.0` — but sat under *Unreleased*
without a date. They move here unchanged; nothing about them is new in `v2.4.1`.

**`ACTION`** **C5 1.1.0 permits model-free descriptors.** Set `models: []` when your
submission calls no model. The `models` key remains required, and each declared model still
needs all five disclosure fields. This relaxation was first published in toolkit `v2.4.0` as
the September 3 exception to the descriptor freeze; the other frozen interfaces are unchanged.

Both `schema_version: "1.0.0"` and `"1.1.0"` remain accepted. Previously valid descriptors keep
their existing `descriptor_digest`; declaring a model does not require a descriptor change.
If you change a descriptor, reseal its digest and validate it with
`SubmissionDescriptor.from_mapping`, as described in your track's descriptor guide.

**`ACTION`** **Ranking metric: ties are now ties.** Tied predicted values used to be broken by
position, so every tie silently resolved to whatever order the roster happened to arrive in. Two
submissions that express no opinion about the ordering — a constant prediction, and a submission
that predicted nothing at all — could each score **1.0000**, full marks, whenever the roster
happened to be in ascending truth order. Tied values now share the mean of the positions they
occupy, and missing values form one tied group sorted last. On a ranking unit:

- a prediction carrying no ordering information — any constant — scores a neutral **0.5**,
  whatever order the roster is in;
- a prediction that is **absent** scores **0.0**, the worst score, not the best.

A perfect ranking still scores 1.0 and an exactly reversed one still scores 0.0; those did not
move. If your ranking submission emits a constant, falls back to a default, or leaves entities
unpredicted, its score changes. Predicting an ordering you actually believe is now the only way to
score above neutral.

**`ACTION`** **Public-safety check: the practice-unit exemption is pinned to one path.** This
changes the toolkit's behaviour, not your submission — read it if your own tooling calls
`qfbench2_common.manifest.assert_public_safe`. The check used to exempt practice (`public-dev`)
units from every answer-material rule, so a practice unit could carry `reference/outcome.json` —
an answer key at the exact path the scorer reads — and the check reported no errors at all.
Answer-bearing material is now permitted **only under `checks/reference_data/`**, matched by path
component rather than by string prefix, and nothing beneath that root may itself carry an
answer-material or oracle name. Self-grading from `checks/reference_data/` is unaffected;
everything else is refused on every split.

One thing to know about calling it: `assert_public_safe` **returns** a list of error strings — it
does not raise. Wrapping it in `try`/`except` and treating "no exception" as a pass reports clean
on every input, including a unit that is leaking. Read the returned list and check that it is
empty.

## 2026-08-28 — Development phase opens

**`ADDED`** Starter packs for all four tracks: `AGENTS.md`, `RUNTIME-ENVIRONMENT.md` and
`SUBMISSION-DESCRIPTOR.md` per track, plus `conformance.sh` for Track 1.

**`ADDED`** The shared toolkit `qfbench2-common` is installable from this repository.

---

*Found something wrong in a pack? Open an issue on this repository — that is faster for everyone
than working around it, and the fix reaches every other participant too.*
