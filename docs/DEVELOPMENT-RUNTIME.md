# Development runtime and House requests

This page describes the selected **Development** resources and the planned execution-relative
House timing release. The timing change is pending deployment and verification; participant
access remains held. This page does not certify Final resources or scoring.
Read your track's task card alongside this guide; the card supplies CPU, memory, GPU and network
settings, and may supply a per-unit timeout.

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

## Execution clocks

The **per-unit container clock** includes container creation, an image pull when needed, and
execution. A House unit's absolute deadline can shorten this ceiling. Cleanup has a separate
bounded grace period; the ceiling is not an end-to-end time allowance for every organizer step.

The **Development platform clock** is 43,200 seconds (12 hours) for the ingestion stage that
runs the submission's units sequentially. It is not 12 hours per unit, and it does not promise
that every unit can use its full individual ceiling. Scoring is a separate program stage with
its own platform clock. Time waiting in the platform queue is outside these stage clocks.

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

The initial opening is planned for House/API and permitted offline submissions. BYO adapter
serving is planned for a later opening under its existing eligibility contract, with separate
availability instructions. Neither the planned timing release nor this page announces that
participant intake or a BYO route is open.

## House request allowance

For Coding, Forecasting and Explainability, the selected House allowance is **25 admitted generation
requests per unit**, with **at most 4,000 output tokens per request**. An omitted output limit
uses 4,000; a larger requested limit is reduced to 4,000, and a smaller valid limit is preserved.
Requests for multiple generated alternatives are refused.

The published input allowance remains **1,000,000 input tokens per unit**. Track cumulative
input usage in your agent and keep requests within that allowance. The model's context window
is a separate constraint on a request, not a cumulative allowance. See the [House model guide](HOUSE-MODEL.md) for model and
context metadata.

An admitted request is charged before forwarding to the model. An upstream error, connection
failure after admission or lost response does not refund it. A participant or SDK retry is a
new request and can consume another slot, even with identical content. Invalid requests refused
before admission do not consume a slot. Budget automatic retries accordingly.

## GPU and network access

`gpu = true` on a task card grants a GPU for permitted local code. The current Development cards
request one GPU on all four tracks; the selected workers have NVIDIA B200 devices. The `api`
category denotes House model access and does not remove the card's GPU grant. It does not
authorize an additional model server or enable a separate BYO serving route. See the shared
[runtime page](../starter-packs/track1/RUNTIME-ENVIRONMENT.md#hardware-and-cuda-builds) for hardware
and CUDA build guidance.

For `network = "restricted"`, use the injected `$MODEL_ENDPOINT`, `$MODEL_NAME` and proxy
settings. Access is limited to the organizer's House route; package indexes, external model
APIs and arbitrary Internet access are unavailable. `network = "none"` is offline. Include
dependencies and permitted artifacts in your image at build time.

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
