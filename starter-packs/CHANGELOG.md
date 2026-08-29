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
- the phase dates

**The metric each track is scored on was on this list, and is not any more.** The ranking metric
changed — see the `ACTION` entry below. Removing it is the honest thing to do: the list is only
useful if everything on it is true. A metric change always lands here with an `ACTION` tag and
never happens silently, which is the guarantee that actually protects you.

---

## Unreleased

_Changes land here first._

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
