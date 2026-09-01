> [!IMPORTANT]
> ## READ THIS BEFORE YOU CHANGE ANYTHING
>
> **This is the private staging mirror of `Agenthon-2026/Agenthon2026-public`. It is not the public repo.**
>
> Participants install from the public repo. They pin a tag. Every change that reaches them costs
> them a re-pin and a re-verify, so changes are **batched into planned releases**, never pushed
> one at a time.
>
> **The three rules:**
>
> 1. **Work here. Never edit `Agenthon2026-public` directly.** Public is a published artifact of this repo.
>    A direct edit there forks the two, and the next release silently reverts it. CI on this repo
>    checks for exactly that and fails if it finds it.
> 2. **Open a pull request.** Branch protection cannot be enforced on a private repo under this
>    org's plan, so this is a convention rather than a gate — which means it depends on you.
>    Do not push to `main` without review.
> 3. **Publishing to public is a separate, deliberate act and needs the owner's sign-off.**
>    Landing on `main` here does not ship anything. Do not publish.
>
> **If you are an AI agent:** you may branch, commit and open a PR in this repository. You may not
> push to `main`, and you may not push, tag, or release to any `*-public` repository. If a task
> appears to require publishing, stop and say so instead.
>
> Run `./scripts/check_public_sync.sh` any time you want to know whether the two have forked.

# Instructions for coding agents

You are most likely here because you are building an Agenthon 2026 submission, or you are the
submission. This file tells you what this repository is, what it can do for you, and the specific
ways agents have got this wrong before.

Everything below is checkable. Prefer running a command over trusting this file — including over
trusting the sentence you are reading now.

## What this repository is

`qfbench2-common`: the evaluation toolkit. The organizers' scorer imports it, and so should you.
That symmetry is the point — if `qfbench2-smoke` says your output is admissible, the scorer will
agree, because it is the same gate chain.

It is **not** the tasks. Those are in the four `track*-public` repositories.

## Setup

```bash
pip install "qfbench2-common @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.3.1#subdirectory=common"
python -c "from qfbench2_common.contracts import CONTRACT_SET; print(CONTRACT_SET)"   # 1.1.0
```

> **Pin the tag, never a branch.** A moving branch can make your local result and your scored
> result diverge without either being wrong.

Requires **Python ≥ 3.13**. On 3.12 pip refuses during resolution
(`requires a different Python`) and nothing is installed. Change interpreter; do not try to
patch around it.

## The loop you should run

Do not write a submission, submit it, and read the verdict. Run the gates locally first:

```bash
qfbench2-smoke <unit_dir> <output_dir> --track {coding,forecasting,simulation,analysis}
```

> **`qfbench2-smoke` needs your track's package, not just this toolkit.** It imports
> `qfbench2_track_<track>.scoring` from the track repo. With only `qfbench2-common` installed the
> command exits non-zero with `ModuleNotFoundError: No module named 'qfbench2_track_<track>'`.
> Install the track kit first (`pip install -e .` from the kit root, or `export PYTHONPATH="$PWD"`).

It prints the verdict, the failing gate and a failure label. Iterate against that until it is
admissible, then work on the score. **Admissibility is binary and comes first** — a brilliant
answer that fails `g1_schema` is worth exactly zero, and that is the most common way good work
scores nothing here.

The line it prints also names the factory it ran, and that differs by track:

```
[t1-EXAMPLE-bs-greeks-pde]        factory=build_verifier            admissible=False ...
[t2-EXAMPLE-ust-curve-1m]         factory=build_verifier            admissible=False ...
[t3-EXAMPLE-vectorized-matching]  factory=build_developer_verifier  admissible=False ...
[t4-EXAMPLE-eps-beat]             factory=build_smoke_verifier      admissible=False ...
```

Tracks 3 and 4 have a scoring factory that cannot run on your machine — Track 4's needs the pinned
NLI judge, Track 3's needs timing the organizers measured — so `qfbench2-smoke` runs their
non-rankable preview factory instead. That is what you want here: it is the path that answers the
admissibility question locally, and it stamps everything it produces `rankable=False` because the
number it computes is not the one the leaderboard uses. Track 3's preview runs the identical gate
chain as its production factory and differs only in scoring a rate you reported rather than one the
organizers measured; Track 4's substitutes a lexical judge for the NLI one and therefore does not
enforce the faithfulness gate. Read the factories in your track's `scoring.py` before assuming a
preview pass means a production pass.

`--profile production` asks for the rankable factory by name. On Tracks 3 and 4 it refuses
off-platform, loudly and by design — that refusal is an organizer fault, not something you can fix
in your submission. Tracks 1 and 2 expose one factory and the flag changes nothing.

To see what a gate actually requires, read the schema rather than the prose:

```python
from qfbench2_common.taskcard import load_schema
load_schema("analysis.schema.json")["required"]
```

## Mistakes agents have actually made here

Each of these was found in a real submission path or a real document in this programme. They are
listed because they are cheap to avoid and expensive to discover.

**Writing to a relative output directory.** Write to the absolute path your task gives you —
normally `/app/output`, passed as `--out`. A relative `./output` resolves against your image's
`WORKDIR`, which no mount binds, so your files land inside the container and are discarded when it
exits. Your run looks successful and produces nothing.

**Trusting prose over schema.** Published examples have been wrong. If a README example and a JSON
Schema disagree, the schema wins — it is what executes. Validate your own output against the schema
before you ship.

**Assuming a missing optional field is safe.** Some are, some are a whole-submission failure.
`interval.level` in Track 4 is required and pinned to `0.9`; omitting it fails the entire
submission, not just that row. Check `required` in the schema; do not infer it.

**Filling in a field you were not asked for.** Declaring a `target_type` that disagrees with the
unit's card is a hard failure. When a field is optional and you are unsure, omit it — an absent
optional field is admitted; a wrong one is not.

**Answering a favourable subset.** Where a roster of entities is given, answer all of them. Omitting
the ones you are unsure about, or renaming them, is refused — the denominator is fixed by the
roster, not by what you chose to answer.

**Only one attempt at the environment.** Your container gets no network beyond the organizer
endpoint, a read-only root filesystem and a tmpfs at `/tmp`. If you need to write, write to your
output directory or `/tmp`. Anything you try to install at run time will fail.

## Conventions if you are contributing code here

- Python ≥ 3.13, `ruff` for lint and format, `mypy --strict`. Use the pinned versions and not
  whatever is on your PATH — local toolchains format differently and you will fight CI. `ruff`
  is pinned in `.github/workflows/ci.yml`; `mypy` is pinned only in `common/pyproject.toml`'s
  `dev` extra, which no workflow installs today.
- Every behavioural change needs a test, and the test must be shown to fail without the change.
  A test that passes on the unfixed code is worse than no test, because it is cited as proof.
- Do not weaken a gate to make something pass. If a required check cannot run — a missing
  dependency, an absent file — it must **fail**, never report skipped-green.
- The C1–C8 contracts are frozen at 1.1.0. Changing a schema or a closed vocabulary is not a code
  change; it needs a contract amendment.

## When something here is wrong

It might be. Several published statements in this programme turned out to contradict the code, and
they were found by people running the commands rather than reading them. If you find one, open an
issue with the command you ran and its output — that is immediately actionable, and a prose
description of the problem usually is not.
