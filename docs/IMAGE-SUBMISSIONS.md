## Executive summary (read this first)

There's no private-image route in Agenthon 2026: your image must be anonymously pullable. A public image can be pulled by anyone, including the files and model artifacts inside it; leave out anything you don't want to share. Every Development and Final submission names a `linux/amd64` container image pinned by an immutable digest, with `image_access` set to `public`. Upload the descriptor and team proof to CodaBench, not the container layers or registry credentials.

The Final cannot run an image that declares a Docker `VOLUME`, including one inherited from its base image. Such an upload is marked Failed when its run starts and does not use an attempt; remove the `VOLUME` (or choose another base image) and upload again.

## Public registry images

Build and push your image before packaging the submission. Set the descriptor's `image` fields to its registry, repository and digest, and set `image_access` to `public`. Follow your track's submission interface for the container label, entrypoint and output paths.

Test pullability without your workstation's registry credentials. An ordinary `docker pull` may succeed only because you are logged in. The [runtime guide](../starter-packs/track2/RUNTIME-ENVIRONMENT.md#the-anonymous-pullability-check) provides an anonymous GHCR check. A package hosted at a public GitHub repository is not necessarily a public container package; check the package's own visibility.

An immutable digest selects the image bytes. Rebuilding or modifying an image requires pushing it, updating `image.digest` (and the registry/repository if changed), then repacking to recompute `descriptor_digest`. Keep dependencies in the image; downloading them during evaluation is not a supported installation method.

## No private images or organizer mirrors

There's no private-image route in Agenthon 2026. The descriptor schema still lists `organizer_mirror` as an `image_access` value, but that option isn't available, and there's no private handoff to request. Set `image_access` to `public` and make sure the image passes the anonymous pullability check linked above.

Private registry credentials are not accepted in `submission.json`, `team-claim.json` or another ZIP member. The Team Key verifies team membership; it is not an image-pull credential. Do not put credentials in the container either.

## Pulls, quotas and model eligibility

Image retrieval and startup use the execution lifecycle's wall-clock budget. Large images and slow registries can leave less time for the agent itself; keep the image focused on dependencies and artifacts it needs. This is not a newly announced image-size quota. A maximum image size must be stated separately from output-directory and memory limits.

Validate locally before uploading. A held or cancelled CodaBench upload still consumes a platform submission attempt. The [team-claim guide](../starter-packs/track2/TEAM-CLAIM.md) explains packing and account linking.

Image access does not grant a GPU or authorize additional models; there is no bring-your-own serving route in this competition. Check the track's artifact policy and the separately announced supported execution modes. A valid descriptor proves format compatibility, not that an unannounced service is available.
