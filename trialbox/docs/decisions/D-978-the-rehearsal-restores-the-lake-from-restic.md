# D-978 the box rehearsal backs up with restic and restores the lake by the custodians' path

- **Task:** PERF-010 R4 (lane D), the box rehearsal of D-968's restic backup
- **PR:** this branch (`agent/PERF-010-R4-the-rehearsal-restores-from-restic`), stacked on R3c (#944)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-977 (the nightly's choice), D-968 (restic R1 to R3b), D-887 (the rehearsal box is VALIDATION: the
  passphrase KEK), D-176 (the box rehearsal)
- **Ruling:** the integrator's option A (#639, 2026-11-17); not option B

## Context

The rehearsal box seals its keys under a passphrase KEK, because the host has no TPM. No custodians' shares cover
that KEK, so the box's own nightly keeps the single `.tbbak` (D-977) and restic never ran in a rehearsal. R4 had to
run the restic path end to end with the bundle's own images, without changing the box's KEK and without wiping the
live lake.

## Decision

1. **A new rehearsal step, `restic-restore`** (`tools/rehearse_box/box.sh`), runs after `screen-after-restart`, once
   the two SCREENs have built the lake. It is not fatal: a red here does not stop the steps after it.
   - **The box's own choice:** the box's nightly decision (`ComposeOps.incremental`) on its secrets volume must say
     "not covered" and name the passphrase back end.
   - **A throwaway KEK:** in `$TB_RH_DIR/restic-rehearsal` the step makes a shamir KEK (2 of 3) with
     `python -m tools.keys init`, unseals it there with two shares, and makes a backup key pair in the bundle's backup
     image. The box's KEK, `/run/trialbox` and `deploy/secrets/backup*` are never used.
   - **The nightly's own step:** `ComposeOps.make_backup` runs with `TB_SECRETS_DIR`, `TB_KEK_FILE` and
     `TB_KEK_HOST_DIR` pointing at that folder. The host makes `restic.key` under the throwaway KEK, and the job runs
     in the bundle's `trialbox-backup` image with `--restic`, against the box's real volumes read-only. The record
     must say `incremental.restic` is true, and the restic repository must be beside the file.
   - **The custodians' path:** `backup-verify --restic-share A --restic-share C` runs offline (`--network none`) in the
     backup image. It uses a different pair from the one that unsealed, and no box KEK. It restores into a temporary
     folder and checks every lake file against the sealed manifest; the step needs at least one lake file from restic.
   - The live lake is only read. The work folder, holding the throwaway keys, the backup and the repository, is
     removed at the end.
2. **The restic job mounts the secrets folder the host decided on** (`update._backup_container(secrets=...)`,
   `ComposeOps.secrets_dir()`). The nightly checks `TB_SECRETS_DIR`'s KEK and makes `restic.key` there, and the job
   now opens that same folder by path. When it is the box's own folder (unset, or `tools.keys.HOST_SECRETS`), the job
   mounts the `trialbox_tb-secrets` volume as before. D-977 always mounted the volume, so a site with `TB_SECRETS_DIR`
   set elsewhere would have checked one folder and opened another.
3. **`backup-verify` says how the lake came back:** `"restic": {"snapshot": ..., "files": N}` for a restic backup,
   `null` for a single `.tbbak`. This tells an empty restic record apart from a real restore. The output never holds a
   password, a share or a key.

4. **restic is given absolute paths** (`restic_repo.Repo.backup`). The rehearsal's first run (#951, run 44018457949)
   found the defect R3b's tests had missed: every lake file restored from restic was missing ("16 changed, 0
   unlisted"). `Repo.backup` listed the files relative to the lake root, with the root as the working folder. restic
   keeps a relative entry relative to the snapshot's top, so the restore put the files at `<target>/db/...`. The
   manifest's root (`/v/lake`, resolved) said `<target>/v/lake/db/...`. The listing now names each file under the
   resolved root, which restic keeps whole. The test stand-in (`tests/fixtures/restic/fake_restic.py`) had stored
   relative entries under the working folder. It now keeps them as restic does, and with that change seven
   `test_backup_restic` and two `test_restic_runner` tests failed with the rehearsal's exact message before the fix.

## Test

`tests/unit/test_rehearsal_restic.py`:

- the job mounts the decided folder by path, or the volume for the box's own folder;
- the nightly passes the folder it checked;
- verify's restic count;
- a lake reached through a link restores where the manifest's root says (it fails with an unresolved listing);
- the step runs after the SCREENs;
- the step uses a throwaway shamir KEK in the work folder and never the box's KEK or backup key;
- the step checks the box's own choice;
- the step restores by two shares, never `--restic-from-box`, and never removes the lake.

The step itself runs only in the box rehearsal (CI, Docker).

## Remains

PERF-010 is complete when the rehearsal's `restic-restore` is green on a train.
