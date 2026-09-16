# Proving your team inside the submission zip

There is no registration page. Your team proves who it is by putting its **website team
number** and a **proof computed under its Team Key** inside the zip you upload to CodaBench,
from the CodaBench account your team will use for every upload. This page is everything a
team needs.

**Your Team Key never goes into the zip.** An uploaded submission zip is downloadable by
anyone once the run is placed on a leaderboard, so nothing secret may travel in it. The
toolkit puts a proof in instead: it shows the organizers that you hold the key, it hands a
reader of your zip neither your key nor anything the organizers store, and it cannot be
lifted into a different upload — it verifies for the one `submission.json` it was computed
over. One thing it does not do, because no proof carried inside the zip could: whoever has
your archive can re-upload the **whole** thing unchanged, and the claim in it still
verifies. That would link *their* account to your team only while your team is not yet
linked; once your account is linked, a second account claiming your team is refused.

## What you already have

* **Team number** and **Team Key**: issued to your team on the website when it registered.
  The key works like a password. Do not post it, commit it or paste it into an issue.
* **One CodaBench account** chosen by the team. Every upload, on every track you enter,
  comes from that account. Request entry to the competition from it as usual.

## The two files in `submission.zip`

| file | what it is |
|---|---|
| `submission.json` | the sealed descriptor, exactly as documented in `SUBMISSION-DESCRIPTOR.md` |
| `team-claim.json` | `{"schema_version": "2.0", "site_team_id": <your team number>, "descriptor_sha256": "<sha256 of submission.json>", "proof": "<64 hex>"}` |

`team-claim.json` is **required on the first upload from your account** in a competition
and **harmless afterwards**: keep writing it into every zip. The toolkit writes it; you
never fill it in by hand.

The proof is
`hmac_sha256(sha256("agenthon2026-team-proof-key:v2:" + team_key), "agenthon2026-team-claim:v2:" + team_number + ":" + descriptor_sha256)`,
where `descriptor_sha256` is the sha256 of the exact `submission.json` bytes in the same
zip. The organizers recompute it from the website's own copy of your key. Because it is
bound to that one descriptor, a copy of your claim on its own cannot be attached to any
other upload.

## Your team id is derived, not assigned

The `team_id` in `submission.json` is computed from the same two values:

```
team_id = "team-" + sha256("agenthon2026-team-alias:" + str(team_number) + ":" + team_key).hexdigest()[:32]
```

The key is hashed exactly as issued: no trimming, no case changes. Nobody emails you a
team id; the toolkit computes it. A different key gives a different id, so if your Team
Key is ever rotated on the website, tell the organizers before your next upload.

## The toolkit does all of this

```bash
# prints your team id only (asks for the Team Key without echo)
qfbench2 submission alias --team-number 42

# seals the descriptor with your team id and writes submission.zip with both files
qfbench2 submission pack --descriptor submission.json --team-number 42 --out submission.zip
```

The Team Key is asked for on a hidden prompt, or read from a file you own with
`--team-key-file <path>` (mode 600, the key alone, one trailing newline allowed). It is
never a command-line argument, never printed, and never written anywhere: the toolkit uses
it to compute your team id and your proof, and that is all. `pack` refuses a descriptor
whose `team_id` disagrees with the derived id, and it refuses to run where the prompt
cannot hide input; use `--team-key-file` there.

## Development submission limits

At the participant Development opening, **Track 2 allows 5 uploads per team per day**,
with **20 total uploads per team for this track during Development**. Use the same designated
CodaBench account for every upload. Track 1 has a 1-per-day limit; Tracks 2, 3 and 4 retain
5 per day.

Development runs through **October 12, 2026**. The joint **Final + Verification phase runs
October 13–25, 2026**. Each team makes **one final submission per track**; organizers perform
verification within that same phase, with no separate participant Verification submission.
Registration and Development close together on October 12, 2026 at **23:59 Anywhere on Earth (AoE, UTC−12)**. The joint Final + Verification phase closes on October 25, 2026 at **23:59 AoE**. Other competition dates and task/data cutoffs are unchanged.

## What happens when something is wrong

Running `qfbench2 submission alias` or `qfbench2 submission pack` locally does not upload
anything or use a submission attempt. **An upload to CodaBench counts against the phase's
platform submission limits even when it is held or cancelled and receives no score.** Check
the limits on the competition's Submission Format page before uploading. Fix and validate
locally first; uploading a replacement uses another attempt.

For the team-claim checks below, a **descriptor whose `team_id` names a different team than
your linked account** is cancelled. The other claim problems hold the upload for a later
intake pass; retrying the same unchanged invalid claim will not fix it. A held upload may
not show an individual explanation. If the cause is unclear, contact the organizers through
the competition's support channel with your submission ID and visible status before uploading
again. Never include your Team Key, proof, password or API token in a support message.

| situation | outcome |
|---|---|
| first upload from your account, valid claim | account linked to your team, upload proceeds |
| first upload, no `team-claim.json` (or an unreadable one) | held: `unlinked_account_no_claim`; add the file and upload again |
| a proof that does not verify, unknown team number, or your team is already linked to another account | held: `claim_conflict`; check the number and key, or ask the organizers if a teammate linked first |
| your account is already linked to one team and claims another | held: `claim_conflict`; one account, one team |
| linked account, claim present but it names another team, was built under an old key, or was copied from a different zip | held: `claim_conflict` |
| linked account, `team_id` in `submission.json` is not your derived id | cancelled (`descriptor_team_mismatch`); the only participant-visible refusal |
| linked account, no claim file at all | fine, the link is already made |
| website unreachable while linking | held with no reason, retried on the next pass |

Same account on another track later: keep the claim file in the zip, the link is extended
to that competition on your first upload there.

## Never do this

* Never send your Team Key, CodaBench password or API token to anyone, including organizers.
* Never put the key in an issue, a commit, a Docker image, a model prompt or a log. It
  does not belong in the zip either, and the toolkit never puts it there.
* Never share one team's key with another team: one team, one account, one alias.
