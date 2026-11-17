# D-977 the nightly sends the lake to restic when the custodians' shares cover the KEK

- **Task:** PERF-010 R3c (lane D), the nightly wiring of D-968's restic backup
- **PR:** this branch (`agent/PERF-010-R3c-the-nightly-runs-restic`)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-968 (restic: R1 the pinned image, R2 the password as a box key, R3a the runner, R3b the lake to
  restic), D-894 (the TPM KEK's escrow shares), D-455 (the nightly's point in time)

## Context

After R3b, `trialbox backup --restic` could send the lake to restic, but nothing ran it: the nightly
(`backup-nightly`, `tools/trialbox/backup_schedule.py`) always ran `trialbox backup` in the `trialbox-py` image,
which has no restic, without `--restic`, and without the KEK that opens `restic.key`.

## Decision

1. **The choice is made each night, on the host, before the job starts** (`ComposeOps.incremental`).
   - `TB_BACKUP_RESTIC=off`: the single `.tbbak`, said so.
   - The KEK not covered by the custodians' shares (no KEK, a passphrase or KMS KEK, a TPM KEK without a current
     escrow set; `restic_repo.shares_cover`): the single `.tbbak`, with the reason. Never a failure, and never a
     restic key the custodians could not open.
   - Covered: the host makes `restic.key` under the KEK if it is not there yet (`restic_repo.make_key`, the function
     of `python -m tools.keys restic-key`); a KEK that cannot be opened then keeps the single `.tbbak` for the night,
     named.
   - `TB_BACKUP_RESTIC` is `auto` (the default) or `off`; any other value is a setting error, which fails the run with
     its record (as every bad backup setting does, D-455).
2. **The restic job** runs in the release's backup image (`TB_BACKUP_IMAGE`, default `trialbox-backup:1.0.0`, the job
   image R1 put in the bundle) with `--restic`, the secrets volume at `/run/secrets/trialbox:ro` and the unsealed KEK
   (`TB_KEK_HOST_DIR`, default `/run/trialbox`) at `/run/trialbox:ro`. The single backup's job is unchanged
   (`trialbox-py`, no KEK, no `--restic`).
3. **The record**: `backup-last.json` and the `backup.done` / `backup.failed` audit carry `incremental`:
   `{"restic": true|false, "why": "..."}`. The words name the reason, never a key or a share.
4. A restic step that fails during the run fails the night (the alert, as for any failed backup); there is no silent
   fall-back to a backup without the lake.

## Test

`tests/unit/test_nightly_restic.py` (12 tests): which KEKs are covered (shamir; TPM only with its current escrow set;
not a passphrase KEK or none); the host makes the key once and only wrapped; not covered keeps the single backup and
makes no key; `off`; a bad setting; the restic job's image and read-only mounts and `--restic`; the single job as
before; the image and KEK folder from the settings; the night's record; a KEK that cannot be opened keeps the single
backup.

## Remains

R4: the box rehearsal backs up, wipes, restores and compares, with restic.
