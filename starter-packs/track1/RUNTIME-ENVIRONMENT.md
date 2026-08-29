# The machine your submission runs on

Everything here is **measured on the evaluation fleet**, not quoted from a spec sheet. You vendor
your dependencies at build time and the host is not something you can adapt to at run time — so if
you build against the wrong CUDA or the wrong architecture, you find out during evaluation, on the
sealed set, once. Treat this page as the contract.

## Hardware

| | |
|---|---|
| GPU | **NVIDIA B200** |
| GPUs per unit | **1** — not multi-GPU |
| GPU memory | 183,359 MiB (~183 GB) |
| **Compute capability** | **10.0** (Blackwell, `sm_100`) |
| Driver | 580.173.02 |
| **Maximum CUDA runtime** | **13.0** |

### The trap: `sm_100`

**Compute capability 10.0 is the single most likely thing to break a submission that works on your
laptop.** A great many prebuilt wheels ship cubins for `sm_70` through `sm_90` and stop there,
because Blackwell is newer than they are. On this fleet such a wheel either:

- falls back to **JIT-compiling from PTX**, which works but adds seconds to minutes on first kernel
  launch and can push a unit past its wall-clock budget; or
- **fails outright** with `no kernel image is available for execution on the device`, if the wheel
  shipped no PTX either.

If you ship CuPy, PyTorch, TensorRT or anything with compiled kernels, check it targets `sm_100` or
carries PTX. Building against CUDA 12.8+ is the usual way to get that.

Do not build against a CUDA newer than **13.0** — the driver will refuse to load it.

## Whether you get a GPU at all

`gpu = true` on a unit card is what grants the device. Across the public cards:

| track | public cards granting a GPU | practical meaning |
|---|---|---|
| Track 1 | **87/87** | GPU present, but ranking is **correctness**, so acceleration only turns a timeout into a pass |
| Track 2 | **104/104** | GPU present; the scored payload is small, so the benefit is limited |
| Track 3 | **72/72** | GPU present and **throughput is the score** |
| Track 4 | **11/11** | GPU present — but see the caveat below before designing around it |

**Do not design around the GPU.** The public cards grant a device. The held-out evaluation cards
are not visible to you, and their resource grants are not published — so treat a GPU as available
for development **and make sure your submission still completes without one**. A submission that
only works with a device is a submission that may not finish.

## The sandbox

Units run under **gVisor** (`runsc`, release-20260803.0) with `nvproxy`, not under stock `runc`.
Consequences worth knowing:

- Syscalls are mediated. Exotic syscalls, some `ioctl`s and direct device pokes may behave
  differently or be refused. Ordinary CUDA work through the driver API is fine — measured:
  `cuInit`, context creation, a 4 MiB device round trip and 183 GB of visible memory all work.
- **Container-name DNS is not reliable.** Address anything you need by IP, or expect it to be
  supplied. This is a property of the sandboxed network stack, not of your image.
- Startup is slower than `runc`. Budget for it.

## Network

`network = restricted` reaches **only** `$MODEL_ENDPOINT`, through an egress proxy. Everything else
is refused, including package indexes — **vendor every dependency at build time.**

`network = none` units get nothing at all.

`$MODEL_ENDPOINT` is injected into your container; do not hardcode a host. Cross-container calls to
it cost roughly 91–95% of native throughput, which is the tax every `api` submission pays.

## Your image

- Build **`linux/amd64`**. The fleet is x86-64; an `arm64` image will not run, and building on an
  Apple-silicon machine produces one by default.
- **The image must accept the track verb as its first argument.** `SUBMISSION_CLI.md` sanctions
  **two** ways to satisfy that: build with no `ENTRYPOINT` so the verb resolves on `PATH`, **or**
  set an `ENTRYPOINT` that takes the verb as an argument — which is what Track 1's own FinanceZero
  baseline does (`baselines/README.md:120-121`; note line 120 is a **verbless** `ENTRYPOINT` and
  the verb arrives on 121 in `CMD ["solve", ...]`). Both are fine. A submission that satisfies
  neither never starts, and the error is not shown to you.
- **`LABEL qfbench2.interface_version="2.0"` is required** (`SUBMISSION_CLI.md:28`) and it must
  match the `interface_version` in your descriptor. This one is genuinely checked; an unlabelled
  image is rejected.
- The image must be **publicly pullable**. Ingestion holds no registry credential. Check this with
  an anonymous token request — `docker pull`, `docker manifest inspect` and `buildx imagetools
  inspect` all use *your* credential and succeed on a private package, telling you nothing. On
  GHCR specifically, a freshly pushed package is **private by default** and flipping it public is
  a UI-only action (Package settings → Change visibility); no API does it.


### The anonymous pullability check

Run this before every submission — `docker pull`, `docker manifest inspect` and
`buildx imagetools inspect` all use *your* credential and succeed on a private package, telling you
nothing:

```bash
REPO=your-org/your-image
TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:$REPO:pull&service=ghcr.io" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
  -H 'Accept: application/vnd.oci.image.index.v1+json' \
  "https://ghcr.io/v2/$REPO/manifests/sha256:<your-digest>"
```

`200` means an unauthenticated client can fetch the manifest. Anything else means your submission
will not start.

## Resource limits

Taken from the unit card, which is the authority on resources — read the card you are running
against rather than assuming an exemplar's values hold. The cards are not uniform across tracks,
and they are not complete either: not every track's cards declare every knob (Track 2's declare no
timeout at all — its budgets live in the track README). Where the card is silent, the track
README's numbers are the only ones that exist.
