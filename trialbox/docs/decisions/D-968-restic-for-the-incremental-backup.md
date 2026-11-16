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
  - **Module bumps.** On the source build the standard library's findings were gone, and `trialbox-py` and
    `trialbox-jvm` passed. The image gates still found twelve open advisories in six of restic 0.19.1's modules
    (`go-jose/v4` 4.1.4, `klauspost/compress` 1.18.6, `x/crypto` 0.52.0, `x/net` 0.55.0, `x/text` 0.37.0, `grpc`
    1.81.1). 0.19.1 is restic's newest release, and its main branch already carries newer versions of all six. The
    build raises exactly those six to the main branch's versions (`ARG RESTIC_MODULE_BUMPS`, each an exact version;
    `go get` adds their sums under GOSUMDB, `go mod verify`, then the build runs `-mod=readonly`). No advisory is
    waived. A bump is dropped once a restic release carries that version. The integrator confirmed this on #639.
    - The six bumps: `github.com/go-jose/go-jose/v4` v4.1.4 to v4.1.6; `github.com/klauspost/compress` v1.18.6 to
      v1.20.3; `golang.org/x/crypto` v0.52.0 to v0.59.0; `golang.org/x/net` v0.55.0 to v0.62.0; `golang.org/x/text`
      v0.37.0 to v0.44.0; `google.golang.org/grpc` v1.81.1 to v1.85.0.
    - **D-1039 (the integrator, 2026-11-16).** On the bumped build one advisory stayed: GO-2026-5932, the package
      `golang.org/x/crypto/openpgp` (unmaintained, unsafe by design), fixed after v0.58.0, the version on restic's main
      branch. `x/crypto` goes to v0.59.0, the first tag with the fix: the one bump past upstream, because upstream has
      not taken the fix yet. restic compiles `openpgp` only into its self-update command (`//go:build selfupdate`),
      which this build leaves out; the scanner flags the module from the binary's module list. The ruling's
      conditions: the version pinned (an exact version, its sum under GOSUMDB, `go mod verify`), the licence count
      still 86, and restic's own test suite (`go test -short ./...`) run in the build on these modules before the
      binary is kept; the restore rehearsal on the built binary is R4. The suite runs as an unprivileged user (`gotest`):
      restic's tests that make a file unreadable expect an error that root never gets. A failing run prints the
      failing tests, since the build log keeps only the step's tail.
      The FUSE mount tests are skipped with restic's own switch (`RESTIC_TEST_FUSE=0`): a build has no FUSE, and the
      box never mounts a repository. `go vet` is off (`-vet=off`): it is a lint, and Go 1.26's checks are newer than
      the release's code; the run that showed this (#894, rehearse at `6f20780c`) failed only on the mount test and
      on one helper package that `go test` reported as "build failed".
    - `x/crypto` v0.59.0 requires `golang.org/x/text` v0.44.0 (its own `go.mod`), so `x/text` goes to v0.44.0, one
      past restic's main branch (v0.43.0), as part of the same ruling; the build with v0.43.0 failed in `go get` with
      exactly that conflict. `x/sys` (v0.50.0) and `x/term` (v0.48.0) rise with them by Go's minimal version
      selection: they are not named bumps, and their sums are checked under GOSUMDB like every module.
    - The rule is checked: `deploy/docker/restic_bumps.sh` runs in the build before `go get`, against the release's
      own `go.mod`, and fails on a bump that names a module the release does not require, that is not an exact
      version, or that is not newer than the version the release carries. A restic upgrade that already carries a
      bump's version therefore fails the build until that bump is dropped. The unit test runs it against the release's
      `go.mod` (`tests/fixtures/restic/go.mod-v0.19.1`, byte for byte the one in the pinned source archive).
  - **Licence budget.** Syft reads no licence from a Go binary, so the image's Go modules count as unknown: 86 on the
    first source build. That is the one line that goes to the owner for a yes or no (#639). No allow-list entry is
    added without it.
- **R2, the password is a box key (landed: `agent/PERF-010-R2-restic-password-is-a-box-key`).**
  - `restic.key` is in `kek.PROTECTED` (and in `OPTIONAL`, since a box has none until its first incremental backup),
    so the custody report, `rotate-kek`, `doctor` and the key ceremony's record treat it like the other keys. It is in
    the inventory of `tools/keys.py`.
  - `python -m tools.keys restic-key` makes it, only under the KEK. A box without a KEK gets no key, and so no
    incremental backup: it keeps the single `.tbbak`. A plain `restic.key` is refused, both when making it and when
    opening it.
  - `tools/trialbox/restic_repo.py`:
    - `password()` opens it under the unsealed KEK.
    - `restic_env()` gives it to one restic process's environment only. It drops any `RESTIC_PASSWORD*` and
      `RESTIC_REPOSITORY*` from outside, so nothing else chooses the password or the repository.
    - `escrow_copy()` writes one file beside each repository, `trialbox-restic.key.json` (0600). It holds the
      wrapped key (KEK ciphertext) and what the custodians need to rebuild the KEK from their shares: back end, KEK id,
      share set id and threshold. It holds no salt, no custodian names and no share fingerprints.
      - It is written only when shares cover the KEK: a shamir KEK (the stewards' shares), or a TPM KEK whose escrow
        set (D-894) is of the current KEK.
      - A passphrase or KMS KEK has no custodians, so it gets no copy, and so no incremental backup. Its salt never
        leaves the box.
      - After `rotate-kek`, a TPM box keeps the old copy, which the old escrow shares still open, until
        `escrow-shares` is run again.
      - The same key re-wrapped replaces the copy. Another key is refused, because the repository's snapshots open
        only with the key they were made under.
      - The write never goes through a link: it refuses a link or a folder at the final name, writes a fresh random
        temporary name with `O_EXCL|O_NOFOLLOW`, renames it, and fsyncs the folder.
    - `open_from_target()` is the custodians' path: the target's file plus their shares (`kek_from_shares` or
      `kek_from_escrow`) give the password. Shares of another set or KEK are refused.
    - `make_key()` writes the key wrapped (`store_key` under the unsealed KEK) or not at all. It never takes
      `create_key_file`'s plain branch, so a locked or vanished KEK cannot produce a plain key.
    - `restic_env()` drops every `RESTIC_*` setting from outside, including the `copy` source's, before it sets the
      password.
  - The support bundle redacts a line that names `RESTIC_PASSWORD`. It cannot find the value by value, because the
    password exists only in restic's process environment. The secrets folders were already refused whole.
  - The adversarial review (D-311) found four defects in the first version: a write through a planted link, a plain
    key in a race, a stale escrow set after `rotate-kek`, and a passphrase KEK's salt on the target. All four are
    fixed and tested.
  - Who runs it: R3 calls `restic-key` from the nightly's host step before the first incremental backup, and mounts
    `/run/trialbox:ro` in the backup container so that `password()` can open the key there.
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

R2: `tests/unit/test_restic_password.py`:
- the key is protected and in the inventory;
- it is made wrapped, at 0600, kept on a second run, and only its fingerprint is printed;
- a box without a KEK, or with its KEK locked, gets no key at all;
- a plain key is refused, and a locked box cannot open it;
- the password goes only into restic's environment, and every outside `RESTIC_*` is dropped;
- the stewards' shares open the repository from the target alone (one file, 0600, no password, no salt);
- a TPM KEK gets no copy before its escrow shares; with them the custodians open it, and their names stay on the box;
- after `rotate-kek` the old copy is kept until new escrow shares, then the new shares open it and the old do not;
- a passphrase KEK gets no copy;
- another key is refused and the copy kept;
- a link at the final or the old temporary name is never written through;
- the support bundle redacts the name.
