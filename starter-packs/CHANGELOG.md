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

### Toolkit `v2.4.4` — organizer-side contracts for the scoring path

**`ADDED`** **Signed forecast-resolution and stable-repeat contracts.** The toolkit gains
`qfbench2_common.contracts.forecast_protocol`, the `stable_output_binding` and
`member_set_digest` helpers in `contracts.digest`, the shared record fields for Track 3 repeat
evidence, a C2 execution-fault reader and the Development self-attestation's GPU-selector
prerequisite. These are organizer-side contracts the scoring path will use; nothing in a
submission changes and **no action is required**. An existing `v2.4.3` install keeps working
with every current guide. A Track 3 scorer package that requires this version will say so in
its own changelog entry when it is published.

**`CLARIFIED`** **Install commands pin toolkit `v2.4.4`.** New installs use the command in your
guide; an existing `v2.4.3` install needs no change. To see which you have:

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
`v2.4.3` install still works. The original note: reinstall with the command in your guide and
confirm the installed package:

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
