# `submission.json` — the descriptor, in full

The descriptor is where submissions fail most often — before any code runs. This page documents it
in full. Read it before writing anything; the file format is the same for every track.

> **This track's values:** `competition_id: "agenthon2026-forecasting-dev"` for the Development
> phase; the fixture to copy is `contracts/fixtures/c5/forecasting_dev.json`. `category` is `api`
> if your forecaster calls the house model. For a deterministic forecaster that calls no model, no
> enum value is strictly truthful — the fixture itself uses `byo-small` with `access: "local"` for
> that case (a legacy category name — see the note in the field table); start there and say so in your report.

## Install the toolkit — one command

```
pip install "qfbench2-common @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.3.1#subdirectory=common"
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
| `schema_version` | `"1.0.0"` |
| `interface_version` | `"2.0"` — must match the image's `qfbench2.interface_version` label |
| `competition_id` | `agenthon2026-<track>-<phase>`. The suffixed form is what the C5 golden fixtures and accepted submissions use. Note the toolkit contradicts itself — `contracts/release.py:106` defines the form WITHOUT the phase suffix — and **neither the schema nor the parser enforces either form**, so nothing catches a wrong value locally. Use the suffix. |
| `team_id` | **your team id — this documentation cannot tell you what yours is.** Take it from your CodaBench profile or a prior submission. There is no default, and any non-empty string validates, so a wrong value is not caught. |
| `track` | `coding` \| `forecasting` \| `simulation` \| `analysis` |
| `phase` | `dev` \| `final` \| `verification` |
| `category` | `api` \| `byo-small` \| `byo-large` \| `simulator` — the enum the schema validates. The `byo-*` names are **legacy** names the schema retains: there is no small-weights tier (no permitted Nemotron is under ~7B), and a BYO submission ships a **LoRA adapter, not weights**. Use the value in this track's callout at the top of this page. The enum is **not validated against `track`** (a wrong pairing passes), so getting it right is on you. |
| `image` | **an object** — see below |
| `image_access` | `public` \| `organizer_mirror` |
| `models` | array, **`minItems: 1`** — required even when your submission uses no model |
| `license` | An OSI-approved identifier for **your own submission** — this is your code's licence, not the task data's. Any well-formed identifier validates, so nothing catches a wrong choice. The task data are a corpus of central-bank speeches and statements, government statistical releases and macro panels, wrapped in cards and indexes the organizers wrote. Rights differ file by file: U.S. federal material is public domain and organizer-written material is under this kit's own licence, but for most non-U.S. central-bank and corporate documents the kit records the rights position as undetermined and grants nothing, so those are not yours to redistribute either. Each unit's `manifest.json` carries the source and licence for every file, and the kit's `DATA-LICENSE.md` sets out the categories. Do not vendor task data into your submission. |
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

### `models` is required even with no model

A submission that loads no weights and calls no endpoint still needs one entry. Describe what you
actually use:

```json
"models": [{
  "name": "none-deterministic-engine",
  "version": "my-engine-1",
  "training_cutoff": "not-applicable",
  "access": "local",
  "revision": "<a commit sha or build id>"
}]
```

All five keys are required per entry.

**Two of them you may not be able to fill truthfully, and you should know that going in.** For an
`api` submission calling the house model, nothing published names the pinned model id —
`SUBMISSION_CLI.md` only says it "is published with the model pin". Yet the same document says
floating aliases "are rejected at verification" and cutoffs "MUST be declared". So
`models[].version` and `models[].training_cutoff` are unknowable from the documentation in the same
way `team_id` is, and a descriptor that validates may still be wrong at verification. Put in the
most honest value you can and raise it with the organizers, rather than inventing a
plausible-looking pin.

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

One file, `submission.json`, at the root of the archive. Nothing else.
