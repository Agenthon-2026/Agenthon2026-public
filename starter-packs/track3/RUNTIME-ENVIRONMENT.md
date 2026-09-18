# Development runtime and image builds

The [shared Development runtime guide](../../docs/DEVELOPMENT-RUNTIME.md) gives the applied
per-track CPU, memory, process, temporary-space, output and time limits, plus House request
accounting. The planned execution-relative House timing change remains pending deployment and
verification; it is not a statement of live availability.
These Development settings do not certify Final resources or comparable Final timing.

## Planned timing and access

Simulation stays offline with no House allocation; its existing unit and platform-stage clocks
remain unchanged. The [shared guide](../../docs/DEVELOPMENT-RUNTIME.md#execution-clocks) describes
the House timing rules for the other tracks. Bring-your-own models and adapters are not part of this
competition on any track (ruling of 2026-09-18).

## Hardware and CUDA builds

The GPU model, memory and driver below were rechecked through read-only worker observations on
2026-09-15. The architecture guidance identifies the image build target; these observations are
not a fresh compatibility test of your CUDA libraries.

| Item | Observed value |
|---|---|
| Architecture | x86-64; build images for `linux/amd64` |
| GPU | NVIDIA B200, one device on the selected worker |
| GPU memory | 183,359 MiB reported by the driver |
| Compute capability | 10.0 (Blackwell, `sm_100`) |
| Driver | 580.173.02 |

`gpu = true` on the task card grants a device for permitted local code. The `api` category means
House model access; it does not cancel that grant or authorize an additional model server.
The shared guide explains [GPU and network access](../../docs/DEVELOPMENT-RUNTIME.md#gpu-and-network-access).

### Building for `sm_100`

A prebuilt wheel containing only older GPU cubins may need to JIT-compile compatible PTX, adding
startup time, or fail with `no kernel image is available for execution on the device` if it
contains neither compatible native code nor usable PTX.

For CuPy, PyTorch, TensorRT or other compiled kernels, check the artifact for `sm_100` support or
compatible PTX. CUDA 12.8 and later toolchains support this architecture, but the toolkit version
alone does not prove that a particular wheel includes the needed kernels. Test the exact image
and libraries you intend to submit. The driver's reported CUDA version is not a guarantee that
every library or newer runtime will work. First-use compilation consumes execution time.

## Container and network settings

The selected Development runtime is `runc`, with a non-root user, a read-only root filesystem
and a small non-executable `/tmp`. Read the [container limits](../../docs/DEVELOPMENT-RUNTIME.md#container-limits)
before choosing writable paths. Historical gVisor tests do not establish current runtime
compatibility or performance.

Restricted units reach only the injected House route through the supplied proxy settings.
Offline units have no network. Include dependencies in the image at build time; do not hardcode
an endpoint or attempt package downloads during evaluation.

## Your image

Build a Linux/amd64 image and set `LABEL qfbench2.interface_version="2.0"` to match the descriptor.
The image must accept the track verb as its first argument: either resolve the verb on `PATH`
with no `ENTRYPOINT`, or use an `ENTRYPOINT` that consumes that leading argument. Follow your
track's `SUBMISSION_CLI.md` for the verb, arguments and output paths.

The [image submission guide](../../docs/IMAGE-SUBMISSIONS.md) explains anonymous public pulls,
immutable digests and the organizer confirmation required for a private mirror. Selecting
`organizer_mirror` does not arrange image transfer or registry access.

### The anonymous pullability check

Test without workstation registry credentials. A normal `docker pull`, `docker manifest inspect`
or `buildx imagetools inspect` may use your saved login and therefore cannot by itself prove
anonymous access. For GHCR, request an anonymous pull token and check the exact manifest digest:

```bash
REPO=your-org/your-image
TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:$REPO:pull&service=ghcr.io" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
  -H 'Accept: application/vnd.oci.image.index.v1+json' \
  "https://ghcr.io/v2/$REPO/manifests/sha256:<your-digest>"
```

`200` confirms anonymous access to that manifest at the time of the check. Also verify that the
image's layers can be pulled from a credential-free environment. Manifest access alone does not
prove architecture, entrypoint, dependency or execution compatibility.
