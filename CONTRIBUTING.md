# Contributing

This is the **private staging mirror** of `Agenthon-2026/Agenthon2026-public`.

## Why staging exists

Participants install the public repo and pin a tag. A push to public is not free for them: it
costs a re-pin, a re-verify, and — if scoring moved — a recalibration of whatever they were
optimising against. Small frequent updates are worse than one planned release, so we batch.

## How to work

1. Branch from `main` here.
2. Open a PR. Get a review. Branch protection is not available on a private repo under this org's
   plan, so nothing mechanically stops a direct push — please don't.
3. Land on `main`. **Nothing has shipped yet.** `main` here is the release candidate.
4. Releases are cut by the owner, from this repo, on a schedule.

## What never happens here

- **Nobody edits `Agenthon2026-public` directly.** If you find yourself with push access to a public repo
  and a fix in hand, bring it here instead. CI checks for direct public edits and fails.
- **Nobody publishes without the owner's sign-off.** Not a formality: a release changes what
  every entrant is measured against.

## Checking the two have not forked

```bash
./scripts/check_public_sync.sh
```

- exit 0 — public holds nothing this repo is missing (ahead is fine and expected)
- exit 1 — public was edited directly; the offending commits are printed
- exit 2 — could not determine. Not a pass.

## Release lanes

| Lane | When | Example |
|---|---|---|
| **Patch** `vX.Y.Z` | A documented command fails, or a scored result is wrong | an install line that cannot resolve |
| **Minor** `vX.Y.0` | Everything else, batched | docs, new guards, hardening |

The patch test is deliberately narrow: *does something we told a participant to do not work?*
