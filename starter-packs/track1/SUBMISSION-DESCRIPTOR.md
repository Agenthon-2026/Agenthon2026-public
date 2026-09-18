# `submission.json` — the descriptor, in full

The descriptor is where submissions fail most often — before any code runs. This page documents it
in full. Read it before writing anything; the file format is the same for every track.

> **This track's values:** `competition_id: "agenthon2026-coding-dev"` for the Development
> phase; the fixture to copy is `contracts/fixtures/c5/coding_dev.json`. `category` is `api` if
> your agent calls the house model. For a deterministic submission that calls no model, no enum
> value is strictly truthful — declare `api` and leave `models` empty (`[]`), and say so in your report.

## Install the toolkit — one command

```
pip install "qfbench2-common @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.4.3#subdirectory=common"
```

> **Pin the tag, never a branch.** A moving branch can make your local result and your scored
> result diverge without either being wrong.

**Needs Python >= 3.13** — on 3.12 the resolver refuses outright:
`ERROR: Package 'qfbench2-common' requires a different Python: 3.12.x not in '>=3.13'`.

> One thing to watch. If an install line you find elsewhere omits `-public` from the repository
> name, or pins an older tag, do not use it — it resolves somewhere you cannot read, or to a
> pre-freeze version that yields the stale 7-key schema this page warns about below. Use the line
> above.

What the installed toolkit gives you: `image` is an object,
`additionalProperties: false`, 12 required keys, `contracts` imports, `seal_descriptor_digest`
present, and it reproduces all twelve published C5 fixture digests.

### Copy a published fixture rather than hand-writing a descriptor

The toolkit ships a **valid** descriptor per (track, phase) at
`qfbench2_common/contracts/fixtures/c5/<track>_<phase>.json`. `descriptor.py:28-30` says the Hub
publishes one for each and that *"Nobody hand-writes a third example."*

**Start from your track's fixture.** It answers `competition_id`, `category` and the `models` shape
without guesswork. The `invalid/` fixtures next to them are the negative controls.

### If you have a stale local checkout, it will pass anyway

A working copy of the toolkit pinned before the freeze carries the old 7-key schema with no
`image` object and `additionalProperties` unset — so a legacy descriptor validates cleanly against
it. `main` is fine; a stale clone is not. Check what you actually have:

```python
import json, pathlib, qfbench2_common
s = json.load(open(pathlib.Path(qfbench2_common.__file__).parent / "schemas/submission.schema.json"))
assert "image" in s["properties"] and s.get("additionalProperties") is False and len(s["required"]) == 12
```

Do not write a shim if that fails — a shim does not fail, it agrees with you. Re-clone or reinstall.

### Schema validation alone is not enough

`invalid/wrong_descriptor_digest.json` **passes** the JSON Schema and is caught only by the
toolkit's parser. Validate with `SubmissionDescriptor.from_mapping` and reseal with
`seal_descriptor_digest` (a reseal of a correct descriptor is a no-op); do not stop at `jsonschema`.

## The twelve required fields

`additionalProperties: false` — an unknown key is a validation error, not a warning.

| field | notes |
|---|---|
| `schema_version` | `"1.0.0"` or `"1.1.0"` (the toolkit that ships this doc implements 1.1.0) |
| `interface_version` | `"2.0"` — must match the image's `qfbench2.interface_version` label |
| `competition_id` | `agenthon2026-<track>-<phase>`. The suffixed form is what the C5 golden fixtures and accepted submissions use. Note the toolkit contradicts itself — `contracts/release.py:106` defines the form WITHOUT the phase suffix — and **neither the schema nor the parser enforces either form**, so nothing catches a wrong value locally. Use the suffix. |
| `team_id` | **derived, not assigned.** `team-` + the first 32 hex characters of `sha256("agenthon2026-team-alias:" + str(team_number) + ":" + team_key)`, computed by `qfbench2 submission alias` / `pack` from your website team number and Team Key (hidden prompt or `--team-key-file`; never an argument). Any non-empty string validates locally, so a hand-typed wrong value is not caught here; `pack` refuses a `team_id` that disagrees with the derived one, and the organizer cancels a descriptor whose `team_id` names a team other than the one linked to your account. See `TEAM-CLAIM.md`. |
| `track` | `coding` \| `forecasting` \| `simulation` \| `analysis` |
| `phase` | `dev` \| `final` \| `verification`. These technical values remain supported. Development and registration close October 12, 2026 at 23:59 Anywhere on Earth (AoE, UTC−12); the joint Final + Verification phase runs October 13–25 and closes October 25 at 23:59 AoE, with one final submission per team per track and no separate participant Verification submission. Follow the organizer’s phase-specific descriptor instructions. |
| `category` | `api` \| `simulator` — the enum the schema validates. `api` on Tracks 1, 2 and 4 (every submission runs against the House model; bring-your-own models and adapters are not part of this competition, and the former `byo-small` / `byo-large` values are invalid since toolkit 2.4.3), `simulator` on Track 3. The enum is **not validated against `track`** (a wrong pairing passes), so getting it right is on you. |
| `image` | **an object** — see below |
| `image_access` | `public` \| `organizer_mirror` |
| `models` | array — one entry per model you actually use; **`[]` when your submission uses no model** (C5 1.1.0) |
| `license` | An OSI-approved identifier for **your own submission** — this is your code's licence, not the task data's. Any well-formed identifier validates, so nothing catches a wrong choice. The task data are the small input files that ship with each coding exercise, and they come from the public QF-Bench v1 pool rather than from the organizers; QF-Bench retains any rights in that material, and the kit redistributes it for non-commercial academic use with attribution. Task cards, tests and harness code written by the organizers are under this kit's own licence. The licence recorded for each individual file is in that unit's `manifest.json`, and the kit's `DATA-LICENSE.md` explains the default. Do not vendor task data into your submission. |
| `descriptor_digest` | Self-referential — see below. **Prefixed**, e.g. `sha256:4a7f532e...`, not bare hex — the same *format* as `image.digest`. The two values are different; they are digests of different things. |

### `image` is an object, not a string

```json
"image": {
  "registry":   "ghcr.io",
  "repository": "your-org/your-image",
  "digest":     "sha256:<64 hex>"
}
```

**Do not use `image_digest` or `model_disclosure`.** Both were replaced at the freeze, and the
toolkit ships the old shapes as *negative* fixtures —
`contracts/fixtures/c5/invalid/legacy_image_digest_field.json` and `legacy_model_disclosure.json`.
A descriptor using them is invalid on two counts: a missing required key, and an unknown one.

### The trap the kit itself sets: `house_endpoint_only`

`SUBMISSION_CLI.md` (search for `house_endpoint_only`) tells you that you "may set
`house_endpoint_only: true` in `submission.json`". **Do not.** The schema's twelve properties are
exactly:

```
category  competition_id  descriptor_digest  image  image_access  interface_version
license   models          phase              schema_version  team_id  track
```

`house_endpoint_only` is not among them, and neither are `open_weights` or `api_domains`, which
belonged to the old schema. With `additionalProperties: false` each one is a hard validation
error — `unknown field(s) [...]; the vocabulary is closed`. This deserves more attention than the
legacy fields above: those you have to dig up, whereas this one the kit actively recommends.

### `models` is required, and `[]` is the model-free answer

The key must be present — an absent key is refused, because silence is not a disclosure. A
submission that loads no weights and calls no endpoint writes the empty list, which is a positive
statement ("this submission calls no model"), not a placeholder:

```json
"models": []
```

(Until C5 1.1.0 the validator demanded at least one entry, so a model-free submission had to
invent a row such as `"name": "none-deterministic-engine"`. Do not do that any more: an invented
row makes `models` useless as evidence exactly where the disclosure rule matters.) Every entry you
DO declare still needs all five keys: `name`, `version`, `training_cutoff`, `access`, `revision`.

For an authorized `api` submission using the House model, copy the five-field disclosure row in
[House model identity](../../docs/HOUSE-MODEL.md). It records the reported model and tokenizer
snapshot and explicitly declares the unpublished training cutoff. The runtime route alias `house`
is distinct from the model identity in `models[].name`; use the injected `MODEL_NAME` for calls.
The guide explains the existing narrow base-pretraining exception and the cutoffs that still
apply to participant tuning. Reseal the descriptor after updating the row.

### `descriptor_digest`

The sha256 of the descriptor **with `descriptor_digest` itself removed**, serialised under
**RFC 8785 (JCS)** canonicalisation — sorted keys, no insignificant whitespace, canonical number
forms. Not `json.dumps(..., sort_keys=True)`; JCS has specific rules for numbers and string escapes.

With the toolkit:

```python
from qfbench2_common.contracts.descriptor import seal_descriptor_digest
sealed = seal_descriptor_digest(my_descriptor)   # returns the descriptor with the digest filled in
```

Hand-implementing JCS is possible, and pointless. Install the toolkit.

**Build to the schema anyway.** A descriptor rejected at the descriptor check with that message is
an organizer-side failure and is being fixed; a descriptor that does not validate is yours and
will not be. If your submission is refused with that message today, that is the known issue and
not a defect in your work.

## The zip

Two files at the root of the archive, nothing else:

| file | what it is |
|---|---|
| `submission.json` | this descriptor, sealed |
| `team-claim.json` | `{"schema_version": "2.0", "site_team_id": <your team number>, "descriptor_sha256": "<sha256 of the exact `submission.json` bytes in this zip>", "proof": "<64 hex>"}` |

**Your Team Key never goes into the zip, and must not.** An uploaded submission zip is
downloadable by anyone once the run is placed on a leaderboard, so nothing secret may travel in
it. `team-claim.json` carries a *proof* instead — an HMAC computed under the key and bound to the
digest of this zip's `submission.json`. A `schema_version` `"1.0"` document, the superseded shape
that carried a `team_key` field, is refused rather than read; if you ever uploaded one, treat that
key as published and ask the organizers to rotate it.

`team-claim.json` is required on the **first upload from your CodaBench account** in a
competition and harmless afterwards: keep writing it. It is how the organizer links your account
to your team; there is no registration page. Let the toolkit write both:

```bash
qfbench2 submission pack --descriptor submission.json --team-number <N> --out submission.zip
```

It asks for the Team Key without echo (or reads `--team-key-file`), sets `team_id` to the derived
id, reseals the digest, computes the proof over the exact `submission.json` bytes it is about to
write, and writes the zip. The key is used for those two derivations and nothing else: it is never
an argument, never printed and never written anywhere. What happens on a missing or wrong claim
is in [`TEAM-CLAIM.md`](TEAM-CLAIM.md): everything except a wrong `team_id` *holds* the upload
for your next attempt rather than cancelling it.
