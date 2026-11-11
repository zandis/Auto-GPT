# 5. Updates, backup, restore, secrets

**Updates** (D-138, D-210): `sudo tools/apply_update.sh trialbox-<version>.tar --dry-run`, then without `--dry-run`.

The order of a release across the acceptance box and the sites (three working days apart), who applies it on site
and what is filed: `docs/validation/change-control.md` §4 (D-344).

1. **Checked before anything changes.** The bundle is verified with a vendor key the box trusts (the signature,
   `key_id`, every sha256 and size), `not_after` (an expired bundle is refused), `release_seq` above the installed one,
   `min_installed_version`, the compatibility table `compat.json` (schema versions, vocabulary release, model pin,
   prompt registry), the image digests of `release.json` against `images.lock` (a digest not pinned is refused), and
   the free space on every disk it writes, with the numbers (`needs 13.5 GB …, free 4.2 GB`). Any refusal: exit 1,
   nothing changed.
2. **Backup first** to `TB_BACKUP_TARGETS` with `deploy/secrets/backup.pub`. No key or no target: the update refuses.
3. **Rollback point:** replaced images tagged `<repo>:rollback-<bundle>`, overwritten models kept, both databases
   dumped locally and encrypted with a key made for this update, the rulesets repository tagged.
4. **Apply:** images loaded, models copied, `docker compose up -d --wait` (services migrate at start), rulesets
   (approval and equivalence gates), health check, then the reference data pack as its own step (if only that fails,
   the new release stays and the pack waits in `deploy/refdata/pending`).
5. `update.applied` in the audit; the rollback point (dumps and key) deleted. A failure in step 4 before the reference
   data puts images, models, databases and rulesets back, restarts, checks and writes `update.rolled_back`; exit 1. If
   the backup or the rollback point fails, the stopped services are started again and nothing else changed.

**After the update that brings D-275, run one ingest** (the nightly one is enough). Until then the lake still holds records the new rule leaves out (a result entered in error, a cancelled order, a sex of `other` / `unknown` as text), and orders with no date that the old ingest dropped are only read again when the source sends them. Approved rulesets need no new approval: their SQL runs guarded by the current rules (`criteria_compiler/compile_sql/overlay.py`) until they are next compiled.

**While an update runs** `deploy/updates/IN_PROGRESS.json` names the bundle and the step. It is removed only when the
update or its rollback completed; while it exists no other update starts. After a power cut or a killed update:

| Command | What it does |
| --- | --- |
| `tools/apply_update.sh status` | the bundle, the step it stopped at, running or interrupted, the installed `release_seq`, the trusted keys |
| `tools/apply_update.sh rollback <bundle>` | puts the box back as before that update (or only restarts the services, if it stopped before the rollback point), audits it, removes the marker |
| `tools/apply_update.sh clean` | removes left-over rollback points of finished updates |
| `python3 -m tools.update_status check` | exit 3 while an update is unfinished (a start guard) |

**Older releases.** A bundle with a `release_seq` not above the installed one is refused. Only on the vendor's written
instruction: `tools/apply_update.sh <bundle> --allow-downgrade "<ticket and reason>"`; the audit gets
`update.downgrade`. A bundle that does not know the box's schema version is refused even then.

**Vendor keys.** The box trusts at most two keys (`deploy/updates/trust.json`; before the first update,
`deploy/keys/vendor_ed25519.pub` and `vendor_ed25519.next.pub`). The vendor changes keys with a rotation bundle, signed
by a trusted key, applied like any update and accepted once; a retired key is never trusted again.

Every step is in `deploy/updates/history.jsonl`; `deploy/updates/installed.json` records what is installed.
`--no-backup` is for a test box only and is audited. If the rollback itself fails, the marker stays: restore from the
backup. Driver updates are outside the bundle and need a change request. Held by `tests/unit/test_update_path.py`,
`tests/unit/test_update_safety.py` and `tools/update_drill.py`.

**Backup** (D-126, D-187, D-188). Once, with hospital IT: `python -m tools.trialbox backup-keygen --private
/media/usb/trialbox-backup.key --public deploy/secrets/backup.pub`. The private key goes in their sealed envelope; the
box keeps only the public key and cannot read its own backups. A backup (`.tbbak`) holds the trial and HAPI
databases, every data folder and a manifest, compressed with zstd level 3 on every core and then encrypted
(AES-256-GCM to an X25519 key). The box keeps running: each database is dumped and counted in one database snapshot,
and a file that changes while it is read is read again. Left out on purpose: the vendor reference pack's rows (public;
the pack file is kept in `deploy/refdata/loaded` and loaded again by the restore; the hospital's own reference rows
are in the backup), the lake's NDJSON except that of `CURRENT` and the two newest snapshots (every Parquet and DuckDB
file and every report is kept), the lake's `tmp/` spill and half-built snapshots. The manifest lists what was left
out, the sha256 and size of every file and the rows of every table. `<file>.sha256` beside each backup marks it
complete (`sha256sum -c` works on it). The ruleset repository `/data/rulesets` is in it; it is also a git repository
you may push to the hospital's git server.

1. **Targets.** In `deploy/.env`, `TB_BACKUP_TARGETS=<NAS share> <USB disk>` (keep the newest `TB_BACKUP_KEEP`, 14,
   of this box's files; other boxes' files on the same share are never touched). At least one must be **off-box**:
   an NFS or SMB share, a USB disk, or a path hospital IT names in `TB_BACKUP_OFFBOX` (e.g. an iSCSI volume in
   another room; on Windows/WSL2 a share mapped as a drive letter). A named path counts only on another device than
   the box's own disk, or when hospital IT puts a file `.trialbox-offbox` in it. In PRODUCTION a box whose targets
   are all on its own disks still writes the backup, but the run fails and stays red.
2. **Schedule.** `deploy/install.sh` installs it (D-274): as root in the install folder it runs `python3 -m
   tools.trialbox backup-install --deploy deploy`, which writes `/etc/cron.d/trialbox-backup`, turns WAL archiving
   on when it can (below), and runs the first backup once the backup key is there (run the command again after
   `backup-keygen`). In PRODUCTION it refuses without an **alert route**: `TB_BACKUP_ALERT_CMD` (a command that
   reads the message on stdin), or `TB_BACKUP_MAILTO` on a host with a mail transfer agent. The cron runs
   `backup-nightly` at 04:45 (move it after the night's jobs) and `backup-status --quiet` every hour. A run checks
   free space first, never runs twice at once, and pauses every service but `db` while it reads, so the databases
   and the files are of one point in time (`TB_BACKUP_QUIESCE=off` leaves them running). Each backup also holds a
   `host` part: `deploy/.env`, the settings file, `deploy/site`, `deploy/secrets` (the pgBackRest cipher) and the
   Authelia and Caddy volumes. The result is in `deploy/site/backup-last.json` and the audit (`backup.done`,
   `backup.failed`). `trialbox doctor --env-file deploy/.env` FAILs in PRODUCTION without an off-box target, an
   alert route or the cron file, and when the newest good backup is missing or too old.
3. **Age alert.** `python3 -m tools.trialbox backup-status` shows the newest good off-box backup (the one
   `backup-last.json` records, with the same name, size and sha256 on the share) and its age. It turns red (exit 1)
   when that backup is older than `TB_BACKUP_MAX_AGE_HOURS` (36) or dated in the future, when the last nightly run
   or its pgBackRest step failed, or when WAL archiving fails, is off on the server, or has archived nothing for 26
   hours. Red is audited (`backup.alert`, again every 24 h, `backup.alert_cleared` when it ends), mailed by cron to
   `MAILTO`, and piped to `TB_BACKUP_ALERT_CMD` when set (a command that reads the message on stdin, e.g. the
   hospital's mail tool). The message holds no patient data. Fix the cause, then run `backup-nightly` by hand.
4. **Check a backup** with hospital IT: `trialbox backup-verify <file> --key <private key>` (reads it all, checks
   every hash and the sidecar). A backup made before D-187 (layout 1, gzip or zstd) still verifies and restores.

**Point-in-time restore (pgBackRest).** On by default (D-274): `backup-install` does steps 2 to 4 below by itself
when the db image carries pgBackRest and a target is off the box (the repository goes to `TB_PGBACKREST_REPO`, else
`pgbackrest-<site>` on the first off-box target), unless `deploy/.env` says `TB_PG_ARCHIVE_MODE=off`; when the check
fails it turns archiving off again. The default db image has no pgBackRest yet, so step 1 is still needed; `doctor`
warns while archiving is off. The `db` service compresses WAL with zstd and TOAST with lz4 and
gives new databases data checksums. Three weekly full backups are kept, so the database restores to any second of at
least the last two weeks:

1. Build the image with pgBackRest: `docker build -t trialbox-db-pitr:16 deploy/pgbackrest`; in `deploy/.env` set
   `POSTGRES_IMAGE=trialbox-db-pitr:16` and `TB_PGBACKREST_REPO=<a folder on the hospital share>`.
2. The repository key: `install -d -m 700 deploy/secrets/pgbackrest; (umask 077; printf '[global]\nrepo1-cipher-pass=%s\n'
   "$(openssl rand -base64 48)" > deploy/secrets/pgbackrest/cipher.conf)`, then give the file and the repository
   folder to the container's postgres user (`docker compose --project-directory deploy exec db id -u postgres`, then
   `chown -R <uid> ...`). Hospital IT keeps a copy of the key with the backup key: the box holds this one, unlike the
   `.tbbak` key, and without it the repository cannot be read.
3. `docker compose --project-directory deploy up -d db`, then `docker compose --project-directory deploy exec -u
   postgres db pgbackrest --stanza=trialbox stanza-create`.
4. Only now set `TB_PG_ARCHIVE_MODE=on` in `deploy/.env`, run `docker compose --project-directory deploy up -d db`
   (it recreates `db` with the new setting; a plain restart keeps the old one) and run `... pgbackrest
   --stanza=trialbox check` (it must say the WAL segment was archived). Never turn archiving on before: with
   archiving on and no working pgBackRest, Postgres keeps every WAL file until the disk is full (`backup-status`
   turns red first). `backup-nightly` then takes a full backup on Sundays (`TB_PGBACKREST_FULL_DAY`, the box's local
   day) and a differential on other days.
5. **To restore to a time:** stop the services, then `docker compose --project-directory deploy stop db`, `docker
   compose --project-directory deploy run --rm -u postgres db pgbackrest --stanza=trialbox --delta --type=time
   "--target=2026-11-08 14:05:00+09" --target-action=promote restore`, and start everything again. Then run
   `backup-nightly` so a new full chain starts.

**Restore.** Bring three things: the backup file, the private key (hospital IT) and **the vendor reference data
pack** the backup names. A backup holds no vendor pack rows (layout 2, above), so a restore onto a fresh box is not
whole without the pack (DATA-018). To see which pack: `trialbox backup-verify <file> --key <private key>` lists it
under `refdata_packs` (`pack_id`, e.g. `trialbox-refdata-20261109`; a pack of `origin: site` is the hospital's own
and comes back with the database). The vendor pack is a `.tar` file (usually `<pack_id>.tar`; the restore reads the
`pack_id` inside it), in the update bundle that installed it (its `refdata:` items), in `deploy/refdata/loaded` of the
old box, or from the vendor. Keep a copy of `deploy/refdata/loaded` beside the off-box backups. Then:

1. Reinstall (§1) and put each `<pack_id>.tar` in `deploy/refdata/loaded` (or a folder you give as `--refdata`).
2. `trialbox restore <file> --key <private key> --yes [--refdata <folder>]`. Every hash is checked first; a
   backup of another site (`--other-site`) or older than 14 days (`--older-ok`) is refused before anything changes.
   A box that holds data is first kept whole as one more encrypted backup in `--keep-to` (default
   `deploy/pre-restore`, with the box's public key `--public`; `--no-copy` skips it): if the restore then fails,
   the message names that file, and `trialbox restore <it>` puts the box back. Each database is emptied, restored
   and its rows checked before any folder moves; replaced folders are moved aside, not deleted. The restore is a
   `backup.restored` event in the restored audit log. Add `--dir host=<folder>` to get the `host` part back. The
   restore loads the packs the backup names from that folder.
3. If a pack is not there the restore says which (`refdata.missing`, e.g. `['trialbox-refdata-20261109']`) and exits
   3 (`ok=False`; the database rows themselves are already restored and equal): put that pack file in the folder and
   run the restore again. Rows that do not match the backup fail the restore; a backup made before
D-187 or by the update path, counted on a running box, gives a warning instead. Held by `tests/unit/test_backup.py`,
`tests/unit/test_backup_schedule.py` and `tools/backup_drill.py` (`make backup-drill`: the nightly run, layout,
status and alert, wipe, restore with the pack loaded again, an old-format restore, the Postgres settings and a
point-in-time recovery).

**Database roles after a restore (D-378).** Each service signs in as its own role and reaches only its own schemas,
which belong to group roles. A restore made as `trialbox` leaves its tables owned by `trialbox`, so run the role
script once after it: `docker compose --project-directory deploy exec -T db /docker-entrypoint-initdb.d/30-service-roles.sh`
(`deploy/install.sh` runs it on every install and upgrade). It is safe to run any time.


## Secrets (D-128, D-138): the one place to rotate them

| Command (as root, in `/opt/trialbox`) | What it does |
| --- | --- |
| `python3 -m tools.trialbox secrets status` | each token's file, mode and age; never a value |
| `python3 -m tools.trialbox secrets rotate` | **at handover, then yearly**: every service token, the operator token and both database passwords |
| `... secrets rotate --service orchestrator` | one service's token; only it restarts |
| `... secrets rotate --service db` | the two database passwords (`ALTER ROLE`, on stdin) |
| `... secrets init` | make any missing token and the orchestrator's actor key (the installer runs it; run it once on a box updated past D-143, else chart-number reveals and exports are refused) |

The mail passwords and a cloud-model key are the hospital's: change them at their source, put the new value in
`deploy/.env`, then `docker compose --project-directory deploy up -d --force-recreate mail-gateway` (or `gateway`). A
box installed before step 8 keeps its shared `TB_SERVICE_TOKEN` (with a warning) until the first full rotation. The
administrator's token for scripts is `deploy/secrets/services/operator.token` (header `X-TB-Service-Token`).
