## Executive summary (read this first)

The currently supported participant image route is an anonymously pullable Linux/amd64 container, identified by an immutable digest. Upload the descriptor and team proof to CodaBench, not the container layers or registry credentials. A public container can be downloaded by other people, including the files and model artifacts packaged inside it. The descriptor's `organizer_mirror` option does not itself transfer a private image or grant the backend access. Do not make a confidential image public just to work around a failed pull: arrange an organizer-confirmed private route before attempting that submission.

## Public registry images

Build and push your image before packaging the submission. Set the descriptor's `image` fields to its registry, repository and digest, and set `image_access` to `public`. Follow your track's submission interface for the container label, entrypoint and output paths.

Test pullability without your workstation's registry credentials. An ordinary `docker pull` may succeed only because you are logged in. The [runtime guide](../starter-packs/track2/RUNTIME-ENVIRONMENT.md#the-anonymous-pullability-check) provides an anonymous GHCR check. A package hosted at a public GitHub repository is not necessarily a public container package; check the package's own visibility.

An immutable digest selects the image bytes. Rebuilding or modifying an image requires pushing it, updating `image.digest` (and the registry/repository if changed), then repacking to recompute `descriptor_digest`. Keep dependencies in the image; downloading them during evaluation is not a supported installation method.

## Private images and organizer mirrors

Private registry credentials are not accepted in `submission.json`, `team-claim.json` or another ZIP member. The Team Key verifies team membership; it is not an image-pull credential. Do not put credentials in the container either.

An organizer mirror means that organizers have already arranged access to a specific image and confirmed the reference participants should submit. Merely selecting `image_access: "organizer_mirror"` does none of that. This update does not establish a self-service confidential image-transfer endpoint or a verified participant mirror workflow.

If your image must remain private, contact the organizers through the competition's support channel before uploading. Ask for the supported private handoff procedure without posting a token, Team Key, private archive or confidential source in a public issue. Wait for confirmation of the exact usable image reference. Until such confirmation, the private-image route is not ready for your submission.

## Pulls, quotas and model eligibility

Image retrieval and startup use the execution lifecycle's wall-clock budget. Large images and slow registries can leave less time for the agent itself; keep the image focused on dependencies and artifacts it needs. This is not a newly announced image-size quota. A maximum image size must be stated separately from output-directory and memory limits.

Validate locally before uploading. A held or cancelled CodaBench upload still consumes a platform submission attempt. The [team-claim guide](../starter-packs/track2/TEAM-CLAIM.md) explains packing and account linking.

Image access does not grant a GPU, authorize additional models, or enable a BYO serving route. Check the track's artifact policy and the separately announced supported execution modes. A valid descriptor proves format compatibility, not that an unannounced service is available.
