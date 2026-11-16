# D-968 restic for the incremental backup

- **Task:** PERF-010 (with PERF-011 and ENG-011), lane D. The owner's yes of 2026-11-16 was relayed on #639 by the
  integrator as D-535 and recorded as D-1035 (PR #897). Lane B2 advises on the consistent
  snapshot.
- **PR:** R1 `agent/PERF-010-R1-restic-pinned`; R2 to R4 follow, one PR each.
- **Date:** 2026-11-16
- **Status:** accepted (R1); R2 to R4 are written into this record as they land

## The ruling

restic does the incremental backup, on these conditions:

1. The repository password is a box key like the others. It is generated on the box and sealed under the KEK or TPM.
   It is never in a file in the clear and never in the support bundle. It is covered by the key ceremony's escrow
   shares (D-894), so the custodians can read a dead box's backups and no one else can.
2. The backup target holds ciphertext only.
3. Restore is rehearsed in the box rehearsal: back up, wipe, restore, compare.
4. restic is pinned by version and sha256 in the offline media and in the licence register.

## The plan (four cards)

- **R1, pin restic (this PR).** restic 0.19.1 is built from its release's source archive (pinned by sha256) with a
  patched Go (`golang:1.26.11-bookworm`, pinned by index digest; `GOTOOLCHAIN=local`, `-mod=readonly`, so only the
  modules of restic's own `go.sum` are fetched) into its own image, `trialbox-backup` (`deploy/docker/backup.Dockerfile`:
  `trialbox-py` plus `/usr/local/bin/restic`). Only the nightly backup's container runs it, with no network; no service
  image carries Go code. It is built by `make images` and `images-multiarch`, gated by the release gates
  (`SC_OWN_IMAGES`), carried in the signed bundle (`make_bundle.sh` names it, since it is no compose service) and in
  the box rehearsal's media, so the offline media carries the pinned build. The licence register gets a `software`
  kind and the row `restic` (BSD-2-Clause, the same version and source sum). `licence_register --check` fails when the
  register and the image's `ARG RESTIC_*` disagree, and a software row ships no path. NOTICE §7 names it.
  - **Why its own image, built from source.** The first form (the release binaries in `trialbox-py`, #887) failed
    the release gates twice: the binaries' Go standard library (Go 1.26.4) had open findings, and `trialbox-py`
    gained Go modules without licence data (Syft reads none from a Go binary), with no golang budget for that image.
    The integrator's order (#639): build from source with a patched Go first; if the gates still find something in
    restic's own modules, its own image, and the exact budget and licence entries go to the owner for one yes or no.
    Both are done here; the rehearsal's gate run gives the exact count.
- **R2, the password is a box key.**
  - `restic.key` is wrapped under the KEK (`kek.PROTECTED`) and listed in `tools/keys.py`.
  - The backup container mounts `/run/trialbox:ro` and gives the clear value only to restic's own process
    environment.
  - A copy of the wrapped file (KEK ciphertext) sits beside each repository on the target. The shares cover the KEK,
    so the custodians can open a dead box's repository from the target alone, and the target alone opens nothing.
- **R3, the lake goes to restic.**
  - The lake's Parquet and DuckDB files go to `<target>/trialbox-restic/`. The other targets are filled with
    `restic copy`.
  - The `.tbbak` keeps the database dumps, the small folders and the host part, encrypted to the hospital's key. It
    also holds the lake manifest (path, size, sha256) and the restic snapshot id.
  - A restore checks restic's restored lake against that sealed manifest.
  - The snapshot rule waits on lane B2's answer on #639.
- **R4, the rehearsal.** `tools/rehearse_box/box.sh` gets a `backup-restore` step: back up, wipe, restore, compare.

What changes for the hospital: its private key alone no longer opens the lake. The KEK is also needed, either on the
box or rebuilt from the custodians' shares.

## Test

R1: `tests/unit/test_restic_pinned.py`:
- restic is built from its pinned source archive with a Go image pinned by digest, under its `go.sum` only;
- no service image (`python`, `jvm`, `embed`, `db`) carries restic;
- the image is built by `make images` and `images-multiarch`, gated (`SC_OWN_IMAGES`) and bundled;
- the register row matches the image;
- the check names a version or a sum that differs, and an image with no pin;
- a software row ships no path;
- the whole register check passes.

`tests/unit/test_release_bundle.py` (and `test_rehearsal_profile.py`, which shares its fixtures) gate
`trialbox-backup` like the compose images, and the bundle's `release.json` names it (`backup`).

The image build runs `restic version` in the builder and in the image.
