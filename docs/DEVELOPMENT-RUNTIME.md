# Development runtime and House requests

This page describes the selected **Development** resources and the planned execution-relative
House timing release. The timing change is pending deployment and verification; participant
access remains held. This page does not certify Final resources or scoring.
Read your track's task card alongside this guide; the card supplies CPU, memory, GPU and network
settings, and may supply a per-unit timeout.

## Competition schedule

Development runs through **October 12, 2026**. The joint **Final + Verification phase runs
October 13–25, 2026**. Each team makes **one final submission per track**; organizers perform
verification within that same phase, with no separate participant Verification submission.
If two Final submissions finish a track with the same ranking score, the tie is broken in favour
of the one uploaded earlier.
Registration and Development close together on October 12, 2026 at **23:59 Anywhere on Earth (AoE, UTC−12)**. The joint Final + Verification phase closes on October 25, 2026 at **23:59 AoE**. Other competition dates and task/data cutoffs are unchanged.

## Submission limits at the Development opening

| Track | Uploads per team per day | Total uploads per team in Development |
|---|---:|---:|
| 1 — Coding | 1 | 20 |
| 2 — Forecasting | 5 | 20 |
| 3 — Simulation | 5 | 20 |
| 4 — Explainability | 5 | 20 |

Use your team's single designated CodaBench account for all uploads. Local validation and
packaging do not consume an attempt; an upload does, including a held or cancelled upload
that receives no score. An upload the platform marks `Failed` does **not** consume one — the
platform's daily count excludes it. Validate locally before uploading. These are the limits for the
participant Development opening. The joint Final + Verification phase retains one final
submission per team per track, with no separate participant Verification submission.

## Container limits

| Track | CPU quota per unit | Memory per unit | Container execution ceiling | Network |
|---|---:|---:|---|---|
| Coding | 16 CPUs | 128 GiB | The card's `agent.timeout_sec` | Restricted House access |
| Forecasting | 16 CPUs | 128 GiB | 1,800 seconds | Restricted House access |
| Simulation | 4 CPUs | 16 GiB | 1,800 seconds | None |
| Explainability | 16 CPUs | 128 GiB | 600 seconds | Restricted House access |

CPU values are quotas, not exclusive physical cores. Swap is disabled. Forecasting and Simulation
use the launcher's 1,800-second fallback where the card supplies no timeout; an absent timeout
does not mean unlimited execution.

All four tracks use these additional per-unit limits:

| Resource | Applied setting |
|---|---|
| Processes and threads | 256 PIDs across the container; `nproc` soft/hard limit 256 |
| Open files | 1,024 file descriptors per process |
| User and root filesystem | Non-root user; read-only root filesystem |
| Inputs | Read-only at `/input` |
| Temporary space | 64 MiB tmpfs at `/tmp`, with `noexec`, `nosuid` and `nodev` |
| Deliverables | Writable `/output`; Coding also mounts the same directory at `/app/output` |
| Output acceptance | At most 64 MiB for the complete output tree per unit |

The selected Development runtime is `runc`. Earlier gVisor measurements are not a description of
this runtime or a guarantee of its performance.

A 64 MiB per-file operating-system limit applies while running. The complete output tree is
checked **after the process exits**; 64 MiB is not a live aggregate quota on the output mount.
Track-specific file names, schemas and smaller file limits still apply.

The launcher requests a 1 GiB quota on the image's writable layer. That layer is separate from
the mounted `/output` directory, and the root filesystem remains read-only. This is neither a
1 GiB writable workspace nor an image-download size limit. Simulation's card field `disk = "10G"`
is not used by this launcher and does not provide a writable 10 GiB workspace.

### Run it locally the way the platform runs it

The starter packs' quick-start `docker run` lines check that your image starts and writes output.
They do **not** apply the settings above, so an image can pass them and still fail on the platform.
Before you upload, run at least one unit with the platform's settings:

```bash
docker run --rm \
  --read-only --user 65534:65534 --cap-drop=ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
  --pids-limit 256 --ulimit nofile=1024:1024 --ulimit nproc=256:256 \
  --cpus <card cpus> --memory <card memory> --memory-swap <card memory> \
  --network=none \
  -v "$PWD/units/<unit>":/input:ro \
  -v "$PWD/out":/output \
  -e QFBENCH_SEED=0 -e QFBENCH_NETWORK=none \
  <image> <verb> <args from your track's starter pack>
```

Coding also binds the same output directory at `/app/output` (`-v "$PWD/out":/app/output`). Make
`out/` writable by uid 65534 (`chmod 777 out` is fine locally). Expect exit 0 and your
deliverables in `out/`.

What this catches, in order of how often it bites:

- **No home directory.** The process runs as uid 65534 with no user entry, so `HOME` is unset or
  `/nonexistent`, and the root filesystem is read-only: anything that writes under `~`, `/root`,
  `/app` or its own install directory fails at startup — Hugging Face and Transformers caches,
  Numba and Matplotlib caches, `pip`, tool state files. Set `ENV HOME=/tmp` in your Dockerfile, or
  point `HF_HOME`, `NUMBA_CACHE_DIR`, `MPLCONFIGDIR` and `XDG_CACHE_HOME` at `/tmp` (64 MiB) or at
  a directory you bake into the image read-only.
- **`/tmp` is `noexec`.** Nothing extracted or compiled into `/tmp` can be executed; JIT caches
  that write executables there fail. Bake binaries into the image.
- **Process and file-descriptor limits** (256 PIDs, 1,024 open files) reached by thread pools and
  data loaders that are sized for a workstation.
- **Writing outside `/output`.** Only `/output` (and `/app/output` for Coding) is writable and
  only its contents are scored.

To exercise a House-model code path locally, point your agent at your own OpenAI-compatible
server instead of `--network=none`: `-e MODEL_ENDPOINT=http://host.docker.internal:<port>
-e MODEL_NAME=<your local model> -e MODEL_TOKEN=<any string>` and use the platform's call shape,
`POST $MODEL_ENDPOINT/v1/chat/completions` with `Authorization: Bearer $MODEL_TOKEN` — see
[Calling the House route](HOUSE-MODEL.md#calling-the-house-route). The platform's proxy
variables are not present locally; a client that reads them from the environment works in both
places.

## Execution clocks

The **per-unit container clock** includes container creation, an image pull when needed, and
execution. A House unit's absolute deadline can shorten this ceiling. Cleanup has a separate
bounded grace period; the ceiling is not an end-to-end time allowance for every organizer step.

The **Development platform clock** is 43,200 seconds (12 hours) for the ingestion stage that
runs the submission's units sequentially. It is not 12 hours per unit, and it does not promise
that every unit can use its full individual ceiling. Scoring is a separate program stage with
its own platform clock. Time waiting in the platform queue is outside these stage clocks.

**When the stage clock runs out, the run is still scored.** The units your run did not reach
before the stage clock ended are recorded as `not_reached` and count as not passed, exactly as a
wrong, crashed, timed-out or missing output does: they stay in the fixed denominator at the worst
value of the metric, and every unit that did run is scored normally. So a run that is cut short
receives the score it earned on what it ran, over the full roster — not "no score". You will see
the count on your run summary page, and `not_reached` in the reason table there. Because the run
is scored rather than failed, it consumes a submission attempt like any other completed run.

Budget for it: divide the stage clock by the number of units in the phase to get your average
per-unit allowance, and cap your agent so that one slow unit cannot spend the rest of the roster's
time. On Track 1's 87-unit Development roster that average is about 8 minutes per unit, well below
the per-unit ceilings the cards declare — the cards' ceilings do not all fit inside the stage
clock, and the stage clock is the binding one.

**Planned House timing — pending deployment and verification.** Each House unit will activate
once, when the organizer begins that unit's execution setup. This is not the participant's
first generation call. Queue waiting and earlier units
will not consume that unit's House window. Setup and provisioning after activation, followed by
container creation, any required image pull and execution, can consume its own window.

The unit's end time will be the earlier of its activation time plus the card's container ceiling
(or the existing launcher fallback), and the end of the actual 43,200-second ingestion stage.
The stage clock starts with the actual platform ingestion stage, not submission staging or a
fresh per-unit clock. Earlier units still consume the shared stage budget, so a later unit may
have less stage time remaining than its full individual ceiling.

The activation and end time will remain fixed for that allocation. Restarting or retrying the
same unit will not renew its window or reset its request counters. Each House bearer credential
will last at most 7,200 seconds from issue and never beyond the unit's fixed end time; issuing a
credential does not extend the unit window. This timing change adds no container time, platform
stage time, request allowance or other compute resources. Simulation remains offline.

The Development phase runs House/API and permitted offline submissions. **Bring-your-own models
and adapters are not part of this competition** (ruling of 2026-09-18): every submission runs
against the House model, `category` is `api` (Track 3: `simulator`), and a descriptor declaring
`byo-small` or `byo-large` is invalid — the toolkit refuses to pack it, and an upload carrying one
is held and never run.

## House request allowance

**The model budget is requests per unit.** For Coding, Forecasting and Explainability the House
allowance is **25 admitted generation requests per unit**, with **at most 4,000 output tokens per
request**. Both are counted and applied by the House route. An omitted output limit uses 4,000; a
larger requested limit is reduced to 4,000, and a smaller valid limit is preserved. Requests for
multiple generated alternatives are refused.

**There is no token allowance per unit.** The earlier per-unit figure of 1,000,000 input plus
100,000 output tokens is withdrawn, and nothing replaces it: the two limits in the paragraph above
are the whole model budget. The model's context window is a separate constraint on a single
request, not a cumulative allowance. See the [House model guide](HOUSE-MODEL.md) for model and
context metadata.

An admitted request is charged before forwarding to the model. An upstream error, connection
failure after admission or lost response does not refund it. A participant or SDK retry is a
new request and can consume another slot, even with identical content. Invalid requests refused
before admission do not consume a slot. Budget automatic retries accordingly.

## GPU and network access

`gpu = true` on a task card grants a GPU for permitted local code. The current Development cards
request one GPU on all four tracks; the selected workers have NVIDIA B200 devices. The `api`
category denotes House model access and does not remove the card's GPU grant. It does not
authorize an additional model server; there is no separate bring-your-own serving route. See the shared
[runtime page](../starter-packs/track1/RUNTIME-ENVIRONMENT.md#hardware-and-cuda-builds) for hardware
and CUDA build guidance.

For `network = "restricted"`, use the injected `$MODEL_ENDPOINT`, `$MODEL_NAME`, `$MODEL_TOKEN`
and proxy settings. `$MODEL_ENDPOINT` is the route origin; the API is served under `/v1`, so
chat completions are `POST $MODEL_ENDPOINT/v1/chat/completions` with
`Authorization: Bearer $MODEL_TOKEN`. A request to `$MODEL_ENDPOINT/chat/completions` is refused
(403) and a request without the bearer is refused (401); neither consumes allowance. The
variables, an OpenAI-client example and a raw-HTTP example are in
[Calling the House route](HOUSE-MODEL.md#calling-the-house-route). Access is limited to the
organizer's House route; package indexes, external model APIs and arbitrary Internet access are
unavailable. `network = "none"` is offline. Include dependencies and permitted artifacts in your
image at build time.

Development resources do not establish Final resource grants or comparable Final timing.
Simulation Development uses the developer profile on a shared queue; its practice results do
not certify official Final timing. Final execution and supported categories require their
separate published contract.

## Image access

Build for `linux/amd64` and use an immutable image digest. The supported public route requires
anonymous pullability. A private organizer mirror requires confirmation of the handoff and exact
usable reference before submission. See [Image submissions](IMAGE-SUBMISSIONS.md) for those
routes and their limits; selecting an image-access field does not transfer an image or grant
registry access.
