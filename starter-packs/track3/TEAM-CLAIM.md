# Proving your team inside the submission zip

There is no registration page. Your team proves who it is by putting its **website team
number** and **Team Key** inside the zip you upload to CodaBench, once, from the CodaBench
account your team will use for every upload. This page is everything a team needs.

## What you already have

* **Team number** and **Team Key**: issued to your team on the website when it registered.
  The key works like a password. Do not post it, commit it or paste it into an issue.
* **One CodaBench account** chosen by the team. Every upload, on every track you enter,
  comes from that account. Request entry to the competition from it as usual.

## The two files in `submission.zip`

| file | what it is |
|---|---|
| `submission.json` | the sealed descriptor, exactly as documented in `SUBMISSION-DESCRIPTOR.md` |
| `team-claim.json` | `{"schema_version": "1.0", "site_team_id": <your team number>, "team_key": "<your Team Key>"}` |

`team-claim.json` is **required on the first upload from your account** in a competition
and **harmless afterwards**: keep writing it into every zip. It is read in memory only,
never stored, by the organizer's intake to bind your account to your team; it is never
logged or shown to anyone.

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
never a command-line argument, never printed, and never written anywhere but inside the
zip. `pack` refuses a descriptor whose `team_id` disagrees with the derived id, and it
refuses to run where the prompt cannot hide input; use `--team-key-file` there.

## What happens when something is wrong

Nothing here costs you a submission attempt. Only a **descriptor whose `team_id` names a
different team than your linked account** is cancelled; every other problem *holds* the
upload until the next intake pass, so fixing it and uploading again is enough.

| situation | outcome |
|---|---|
| first upload from your account, valid claim | account linked to your team, upload proceeds |
| first upload, no `team-claim.json` (or an unreadable one) | held: `unlinked_account_no_claim`; add the file and upload again |
| wrong key, unknown team number, or your team is already linked to another account | held: `claim_conflict`; check the number and key, or ask the organizers if a teammate linked first |
| your account is already linked to one team and claims another | held: `claim_conflict`; one account, one team |
| linked account, claim present but it names another team or an old key | held: `claim_conflict` |
| linked account, `team_id` in `submission.json` is not your derived id | cancelled (`descriptor_team_mismatch`); the only participant-visible refusal |
| linked account, no claim file at all | fine, the link is already made |
| website unreachable while linking | held with no reason, retried on the next pass |

Same account on another track later: keep the claim file in the zip, the link is extended
to that competition on your first upload there.

## Never do this

* Never send your Team Key, CodaBench password or API token to anyone, including organizers.
* Never put the key in an issue, a commit, a Docker image, a model prompt or a log.
* Never share one team's key with another team: one team, one account, one alias.
