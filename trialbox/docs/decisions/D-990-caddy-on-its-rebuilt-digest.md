# D-990 caddy moves to its rebuilt digest; authelia and HAPI have nothing newer

- **Task:** SC-2 (lane D), path 1 card 2 of the 2026-12-10 lapse of the image findings (the integrator's order, #639)
- **PR:** this branch (`agent/SC-2-caddy-on-its-rebuilt-digest`), stacked on SC-1 (D-979)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-979 (SC-1), D-348 (`deploy/images.lock`), D-574 (the caddy and authelia exceptions)

## Context

Of the 94 allow-list exceptions that lapse on 2026-12-10, 3 are findings in `caddy:2.11.9-alpine` and 9 are in
`authelia/authelia:4.39.28` (8 findings and the `os_packages_unreadable` entry). The integrator asked for both images
to move to newer pinned digests. HAPI (22 entries) was to move only if an upstream tag carries the fixes, reported
before any move.

## What the registry says (Docker Hub, 2026-11-17)

- **caddy:** `2.11.9-alpine` was rebuilt under its tag. The index changed from `sha256:0bbb055b…` (pinned) to
  `sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0`, with linux/amd64 and linux/arm64 still
  in it. `2.11.9-alpine` is still the newest patch tag of its line.
- **authelia:** `4.39.28` is unchanged at `sha256:bd97cff4…` and is still the newest tag (4.39.25 to 4.39.28 are the
  latest). No newer digest exists to move to.
- **HAPI:** `v8.12.0-2` is unchanged at `sha256:0ff86aac…` and is still the newest 8.x image (`v8.12.0-1`,
  `v8.12.0-2` and their `-tomcat` variants). No upstream tag carries fixes yet.

## Decision

1. **caddy moves** to the rebuilt digest in `deploy/images.lock`, `deploy/docker-compose.identity.yml` and the
   identity workflow's `CADDY_IMAGE`. `tools.images_lock check-compose` holds them equal. The hosted-demo scripts under
   `deploy/gcp/` pin a different tag (`caddy:2.11.9`, not alpine), belong to another lane, and are not touched. The
   step logs under `docs/handover/` are records of earlier runs and keep their digests.
2. **authelia and HAPI do not move:** there is no newer image. Their entries go to the group re-review that lane D
   prepares for the owner's yes, with vLLM's.
3. **No allow-list entry is added or removed here.** The images workflow's Trivy gate names what the caddy move
   clears. The removal is an allow-list change for the owner's yes, posted on #639 as an exact diff.

## Test

- `tools.images_lock check-compose` passes: the compose files equal the lock.
- The existing lock tests hold.
- The images workflow gates the rebuilt caddy, and the box rehearsal runs the box with it.
