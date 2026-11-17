# D-979 the db image moves to postgres:16-trixie's current base digest

- **Task:** SC-1 (lane D), path 1 card 1 of the 2026-12-10 lapse of the image findings (the integrator's order, #639)
- **PR:** this branch (`agent/SC-1-the-db-image-on-a-newer-base`)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-204 (the db image), D-348 (`deploy/images.lock`), D-340 and D-574 (the per-image exceptions),
  D-186 (the allow-list's `review_by`)

## Context

`deploy/supply-chain-allowlist.yaml` holds 94 exceptions that lapse on 2026-12-10. Of these, 30 are Trivy findings in
`trialbox-postgres`, our own image built `FROM postgres:16-trixie@<digest>`. After that date `allowlist-check`, every
gate that loads the file, and one unit test fail (lane D's reading, #639, 2026-11-17). The base was pinned on
2026-11-11 at `sha256:f9a7b9eb…`. Docker Hub's index for `postgres:16-trixie` is now `sha256:dd2bf3ce…`, rebuilt on
newer Debian and PostgreSQL patches.

## Decision

1. **The base moves** to `postgres:16-trixie@sha256:dd2bf3ce2dc83a81674cf7f217fcfd8a5009a4b325dda5b843bfee82a06cff6f`,
   in `deploy/docker/db.Dockerfile`'s `POSTGRES_BASE` default and `deploy/images.lock` (`images.db.base.digest`), with
   the lock's `checked` note.
   - The new index still holds linux/amd64 and linux/arm64.
   - Every pinned package version is still published for both platforms: pgvector `0.8.7-1.pgdg13+1`, pgBackRest
     `2.60.0-1.pgdg13+1`, PGroonga `4.1.0-1` and libgroonga `16.1.5-1`, so the package pins stay.
   - The PostgreSQL major stays 16.
2. **No allow-list entry is added, and none is removed in this change.** An entry that matches nothing is only a note
   in the gates ("allow-list entry matched nothing"), never a failure. The images workflow's Trivy gate on this branch
   names the entries the move clears. Removing them is an allow-list change, which takes the owner's yes. The removal
   is posted on #639 as an exact diff for whoever has it.

## Test

- The existing guards hold the pins equal: `tests/integration/test_db_image.py` (lock against Dockerfile and
  compose), `test_images_lock*` and `test_pg_major`.
- The images workflow builds the image from the new base, with the packages held at their pins, and runs the release
  gates.
- The box rehearsal installs and runs the box on it.

## Remains

- SC-2: caddy and authelia move to newer pinned digests.
- SC-3: HAPI moves if an upstream tag carries the fixes.
- What stays flagged gets a group re-review, prepared for the owner's yes.
