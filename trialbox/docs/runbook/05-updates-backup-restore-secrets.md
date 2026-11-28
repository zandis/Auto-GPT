# 5. Updates, backup, restore, secrets

**Reader:** the box owner (a restore with Aimedics in a supervised session, §21).

**Updates** (D-138, D-210): `sudo tools/apply_update.sh trialbox-<version>.tar --dry-run`, then without `--dry-run`.
On the Operations page an update can also be asked for in the box's quiet hour, so that nobody stays late for it:
it then runs when the quiet hour comes and no job runs, with the same backup and automatic rollback (§15, D-731).

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

**Each release runs its own start-up steps.** The updater that runs is the installed release's. After it has put
the new release's files in place, step 4 runs the new release's `python3 -m tools.trialbox pre-start` before it
starts the stack: what the new stack needs on the host first (a secret file a new service reads, the image pins) is
made by the release that needs it. A release that adds such a step adds it to `tools/trialbox/prestart.py`. The
release installed before this command existed cannot run it, so a bundle that adds a step names a release that has
the command as its `min_installed_version`; the verifier then refuses the bundle on an older box before anything
changes, and the box takes the release in between first.

The same holds once the database is up and before the services start: the updater runs the new release's
`python3 -m tools.trialbox db-up` (the list `DB_STEPS` in the same file). This release's steps there are: the
database container on the new release's settings, the services' database roles, the schemas no service owns.
A fresh install runs both commands too.

**Model weights against their pins** (T-677, D-393). On a GPU box the update's check step runs
`trialbox doctor --weights` first: every pinned build's weights in the models folder must still hash to their pin.
A difference writes `deploy/site/weights_changed.json`, the gateway refuses every model call (`weights_changed`) and
reports itself unhealthy, and the update rolls back. The same check runs every night at 01:30 before the scheduled
runs (`trialbox-weights.timer`, `deploy/check_weights.sh`), and by hand with `trialbox doctor --verify-all`. A pass
removes the flag. The gateway also compares each model server's `GET /v1/models` (the folder it serves and its
`max_model_len`) with the pin at start and every hour, and refuses `model_mismatch` until they agree.

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
`--no-backup` is for a test box only and is audited; a PRODUCTION box refuses it without `--no-backup-reason REASON`
(D-1321). If the rollback itself fails, the marker stays: restore from the
backup. Driver updates are outside the bundle and need a change request. Held by `tests/unit/test_update_path.py`,
`tests/unit/test_update_safety.py` and `tools/update_drill.py`.

**Backup** (D-126, D-187, D-188). The backup key, once. A **PRODUCTION** box makes it at install (E2E P-01;
`trialbox backup-keygen` and the stick ceremony are refused there): on the install's terminal the paper copy is shown
once, the screen is cleared and hospital IT types the whole copy back before `backup.pub` is made; an unattended
install (no terminal) seals the key under the install's KEK passphrase into `deploy/secrets/backup-key-<fp>.sealed`
and, before `backup.pub` is made, onto the one declared off-box backup target. The install declares `TB_BACKUP_OFFBOX`
when the box has no declaration (`deploy/secrets/backup-target.json`: the folder, which must be exactly a mount point,
and its mount's point, filesystem type, source, mount id and root, the folder's device and inode, a `/dev` source
with its `/dev/disk/by-uuid` name; tmpfs, overlay and the box's own filesystems are refused, and a `/dev` source
without a by-uuid name, as on a host without udev, cannot be declared). Every run that writes the sealed copy checks
the opened folder against that record; any difference (another source, the share unmounted or its folder gone, the
mount moved, a remount, a re-plug or a reboot since the declaration) refuses before a key is made and is journaled
(`backup.target_mismatch`; no record: `backup.target_undeclared`). To change it, or to take a remounted target
again, as root: `python3 -m tools.backup_key_ceremony --declare-backup-target <folder> --operator "<name>"
--replace` (the old record is kept as `backup-target.<time>.<n>.old`); it moves no file, so copy
`backup-key-<fp>.sealed` to the new target by hand. A FAT or exFAT target has no file modes: the sealed copy
(encrypted) is made there as its mount gives it. Run again by hand, as root on the box:
`python3 -m tools.backup_key_ceremony --install`. The install's own declaration takes no share served by the box
itself (localhost, a loopback address, the box's own name or address). The install's `--kek-passphrase-file` is
removed before the key is made and written back if the ceremony refuses; an install killed during the ceremony
leaves no file, so keep the passphrase somewhere else as well. The install does not check, when it removes the
file, that it is still the one it read: do not replace or rewrite the file while the install runs. A passphrase
file a later install finds beside a sealed key is kept and named: remove it by hand (`rm -- <file>`). To restore with a sealed key (the copy on the backup target), as
root on the box: `python3 -m tools.backup_key_ceremony --unseal <the .sealed file>` asks for the passphrase and does
not show it (never type it where it is shown; piped, it reads one line of stdin) and writes the key file only to
`deploy/secrets/restore/trialbox-backup.key` (never to a stick); then `restore --key
deploy/secrets/restore/trialbox-backup.key`; then `python3 -m tools.backup_key_ceremony --forget-restore-key`. A
damaged medium, a file that is not a sealed key and a wrong passphrase are told apart. A DEV, TEST or VALIDATION
box, with hospital IT: `python -m tools.trialbox backup-keygen --private
/media/usb/trialbox-backup.key --public deploy/secrets/backup.pub`. The private key goes in their sealed envelope; the
box keeps only the public key and cannot read its own backups. A backup (`.tbbak`) holds the trial and HAPI
databases, every data folder and a manifest, compressed with zstd level 3 on every core and then encrypted
(AES-256-GCM to an X25519 key). The trial database includes the judged-pair store (`orch.judged_pairs`, D-908): model
answers to note questions, by pseudonym; and the answer store (`orch.answers`, D-1360): each patient's latest answer
on each criterion, by pseudonym; after a restore the opt-out worker deletes again the rows of every patient on
the register (it clears the owed tables). The box keeps running: each database is dumped and counted in one database snapshot,
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
2. **Schedule.** `deploy/install.sh` installs it (D-274): as root in the install folder it runs `PYTHONPATH=libs python3 -m
   tools.trialbox backup-install --deploy deploy`, which writes `/etc/cron.d/trialbox-backup`, turns WAL archiving
   on when it can (below), and runs the first backup once the backup key is there (run the command again once the
   key is made). In PRODUCTION it refuses without an **alert route**: `TB_BACKUP_ALERT_CMD` (a command that
   reads the message on stdin), or `TB_BACKUP_MAILTO` on a host with a mail transfer agent, or, on a box with no
   mail, `TB_BACKUP_ALERT_ROUTE=health-page`: the site's written choice that the red backup tile on the `/admin`
   health tab and the audit carry the alert (D-735). Then nobody is mailed: someone must open the health tab every
   working day, and `doctor` WARNs in PRODUCTION to keep that in sight. Any other value is a setting error. The cron runs
   `backup-nightly` at 04:45 (move it after the night's jobs) and `backup-status --quiet` every hour. A run checks
   free space first and never runs twice at once. It first **waits while a job runs or is queued**, at most
   `TB_BACKUP_JOB_WAIT_S` (6 h: half the 12 h between the 24 h cron and the 36 h age alert), then goes on anyway
   and records the jobs it ran beside (`beside_jobs`, ids and types). **Nothing is paused** (D-455): each database is copied as one
   snapshot (`trialbox_wf`, then `hapi`) and the files are read after both; `backup-last.json` records the window
   (`point_in_time`: each snapshot's time, `files_done_at`, the step limits). Rows written after a database's snapshot
   are not in the backup. `TB_BACKUP_QUIESCE=pause` pauses every service but `db` for one instant of databases and
   files, but never while a job runs, and holds the watchdog's maintenance flag meanwhile (the watchdog never restarts
   a paused container, and restarts nothing while `deploy/watchdog/maintenance` exists: to hold services still by
   hand, write `{"by": "<you>", "why": "<what>"}` there and remove it after). Each step's time limit
   comes from what it reads: `TB_BACKUP_STEP_START_S` (900) plus the measured size at `TB_BACKUP_MIN_MBPS` (5 MB/s);
   with no size, no limit (a hung run then shows as "another backup run holds the lock" and the age alert). A target
   keeps at most `TB_BACKUP_KEEP` backups and at most `TB_BACKUP_KEEP_SHARE` (0.5) of its capacity; the newest is
   always kept, and only a file with its `.sha256` sidecar counts; two good backups always stay, and a target too
   small for two turns the run red. The lake's `db/` and `parquet/` are read under the lake's lock: a rebuild waits
   for that read (and a restore refuses a lake that fails its own check). Each backup also holds a
   `host` part: `deploy/.env`, the settings file, `deploy/site`, `deploy/secrets` (the pgBackRest cipher) and the
   Authelia and Caddy volumes. The result is in `deploy/site/backup-last.json` and the audit (`backup.done`,
   `backup.failed`). `trialbox doctor --env-file deploy/.env` FAILs in PRODUCTION without an off-box target, an
   alert route or the cron file, and when the newest good backup is missing or too old.
3. **Age alert.** `python3 -m tools.trialbox backup-status` shows the newest good off-box backup (the one
   `backup-last.json` records, with the same name, size and sha256 on the share) and its age. It turns red (exit 1)
   when that backup is older than `TB_BACKUP_MAX_AGE_HOURS` (36) or dated in the future, when the last nightly run
   or its pgBackRest step failed, or when WAL archiving fails, is off on the server, or has archived nothing for 26 hours.
   Red is audited (`backup.alert`, again every 24 h, `backup.alert_cleared` when it ends), mailed by cron to `MAILTO`, and piped to
   `TB_BACKUP_ALERT_CMD` when set (a command that reads the message on stdin, e.g. the hospital's mail tool). The message holds no patient data.
   Fix the cause, then run `PYTHONPATH=libs python3 -m tools.trialbox backup-nightly` from the install folder. 修正原因後，請在安裝目錄執行上述指令。原因を解消したら、インストール先のディレクトリでこのコマンドを実行します。
4. **Check a backup** with hospital IT: `trialbox backup-verify <file> --key <private key>` (reads it all, checks
   every hash and the sidecar). A backup made before D-187 (layout 1, gzip or zstd) still verifies and restores.

**Point-in-time restore (pgBackRest).** On by default (D-274): `backup-install` does steps 2 to 4 below by itself
when the db image carries pgBackRest and a target is off the box (the repository goes to `TB_PGBACKREST_REPO`, else
`pgbackrest-<site>` on the first off-box target), unless `deploy/.env` says `TB_PG_ARCHIVE_MODE=off`; when the check
fails it turns archiving off again. The box's db image carries pgBackRest (2.60, `deploy/docker/db.Dockerfile`,
D-371), so there is no image to build and none to swap; `doctor` warns while archiving is off. The `db` service compresses WAL with zstd and TOAST with lz4 and
gives new databases data checksums. Three weekly full backups are kept, so the database restores to any second of at
least the last two weeks:

1. In `deploy/.env` set `TB_PGBACKREST_REPO=<a folder on the hospital share>`. Keep the box's own db image: never set
   `POSTGRES_IMAGE` to another one (an image without pgvector and PGroonga, or with another C library, would change
   the index collation order and lose the two extensions; the old Alpine pgBackRest image is gone).
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

**Restore drill (T-730d, D-892).** Hospital IT brings the private key from the envelope. In a root shell on the
box, run `trialbox restore-drill <backup file> --key <key>`. Operations → Backups fills in the newest backup path.
The command checks free space for the unpacked backup and scratch databases first. If space is short, it reports
the GB needed and starts nothing. The release image uses its locked zstandard to unpack and verify every file
against the signed manifest. The database administrator creates scratch databases (`tb_drill_<id>_<name>`).
The drill runs pg_restore as their owner and uses the site connection from `deploy/.env` to compare rows and hashes.
It removes scratch databases and unpacked files even after a failure. Exit 0 means pass, 1 failure, 2 nothing started.
The key-check record and audit event (`backup.restore_drill`) omit the key and its path. A failed drill alerts by mail
or on the health page and turns `backup_verified` red until a drill passes. It also turns red after
`TB_HEALTH_VERIFIED_DAYS` (100) days without a key check. Run the drill at least every 90 days, after hardware
changes and before go-live acceptance (§6).

**Restore.** Bring three things: the backup file, the private key (hospital IT) and **the vendor reference data
pack** the backup names. A backup holds no vendor pack rows (layout 2, above), so a restore onto a fresh box is not
whole without the pack (DATA-018). To see which pack: `trialbox backup-verify <file> --key <private key>` lists it
under `refdata_packs` (`pack_id`, e.g. `trialbox-refdata-20261109`; a pack of `origin: site` is the hospital's own
and comes back with the database). The vendor pack is a `.tar` file (usually `<pack_id>.tar`; the restore reads the
`pack_id` inside it), in the update bundle that installed it (its `refdata:` items), in `deploy/refdata/loaded` of the
old box, or from the vendor. Keep a copy of `deploy/refdata/loaded` beside the off-box backups. Then:

1. Reinstall (§1) and put each `<pack_id>.tar` in `deploy/refdata/loaded` (or a folder you give as `--refdata`).
2. Stop every service but the database: `docker compose stop $(docker compose ps --services | grep -vx db)`. The
   restore asks compose which services run and refuses, before anything changes, while any but `db` does: it moves
   their folders aside, and what a running service wrote meanwhile would be lost (D-724). Where compose cannot
   answer, stop them yourself and add `--services-stopped`. Start them again after the restore.
3. `trialbox restore <file> --key <private key> --yes [--refdata <folder>]`. Every hash is checked first; a
   backup of another site (`--other-site`) or older than 14 days (`--older-ok`) is refused before anything changes.
   A box that holds data is first kept whole as one more encrypted backup in `--keep-to` (default
   `deploy/pre-restore`, with the box's public key `--public`; `--no-copy` skips it): if the restore then fails,
   the message names that file, and `trialbox restore <it>` puts the box back. Each database is emptied, restored
   and its rows checked before any folder moves; replaced folders are moved aside, not deleted. The restore is a
   `backup.restored` event in the restored audit log. Add `--dir host=<folder>` to get the `host` part back. The
   restore loads the packs the backup names from that folder. Each file gets back the owner it had when it was
   backed up, and each folder the owner of the folder it replaced, so the services (which run as their own user)
   can write their volumes again (D-724).
4. If a pack is not there the restore says which (`refdata.missing`, e.g. `['trialbox-refdata-20261109']`) and exits
   3 (`ok=False`; the database rows themselves are already restored and equal): put that pack file in the folder and
   run the restore again. The restored lake must pass its own check (sidecars, D-455) before any folder moves.
4. **Events after the backup (D-455).** The databases are of the backup's snapshot; the audit chain was copied a
   little later and may hold events the restored databases do not: opt-outs, EDC draft erasures, break-glass,
   EDC signatures and submissions, consent changes. The restore lists them (`to_reapply`: time, event, place in
   the chain), writes `backup.restore_reapply` and exits 4 ("NOT complete"). A steward opens each one in the audit
   browser and does it again (records the opt-out again, closes the break-glass, re-signs or re-sends the EDC
   record) before screening resumes.
   **The box is held until then (D-522).** The restore sets the flag `screening.after_restore` to `held` as soon
   as the restored rows are in, and takes it off itself only when it ends complete and no earlier hold or restore
   stands: after a restore that is not complete (this step or the next), that failed part-way, or that was run a
   second time, the box stays held. While held, the timer starts no list job (SCREEN, MICROBATCH, COHORT, NAV), a
   list a person asks for fails with a message that says so, and the weekly not-matched sample is not drawn. The
   ingest and retention run. `sudo trialbox doctor --env-file deploy/.env` on the host shows the hold (`restore_hold`: HELD, released or UNREADABLE; see "The hold after a restore" below). When every listed event is re-applied, the data steward (or the administrator) sets the flag to `released` on
   `/ops/flags`, with the reason (who re-applied what), and confirms it on the next page ("Yes, do it"); the change is in the audit. If the restore prints that the
   hold could not be set, keep the services stopped until the events are re-applied.
5. **Opt-outs recorded after the backup (D-493).** Before the restore empties the trial database it reads the
   box's opt-out register. After the restored rows are checked it **puts back every opt-out** the register held
   that the backup does not (as it was recorded: who, when, why), so nobody who said no after the backup is listed
   again. It prints and audits counts only (`optouts_after_backup` in `backup.restored`: found, kept, not kept; how
   many a person typed and how many the registry's worker wrote; never who). What still needs a person, and makes
   the restore exit 4 ("NOT complete"):
   - **a lift typed after the backup** (`lifts_reverted`): it is not replayed, the patient stays withheld until a
     steward lifts the opt-out again;
   - **a new machine, or a box with no register** (`state: unknown`): what the old box recorded after the backup
     cannot be read here. Check the office's records (paper form, mail, phone note) since the backup's snapshot
     and enter each opt-out again before screening resumes;
   - **a register that could not be read or written** (`unreadable`, `not_kept`): the same, from the office's
     record or from the kept copy of the box before the restore (step 2).
   `--no-copy` is refused while the register holds events a person typed after the backup: the copy would be the
   only other record of them. Run again, the restore finds the kept opt-outs there and adds nothing twice.
6. **Jobs that were running at the backup (D-493).** The restored queue holds them as running. The restore sets
   each to failed ("interrupted by a restore") and lists them (`jobs_failed`): the orchestrator does not run them
   again, and nobody is mailed twice. Ask the requester to send a request again if it is still wanted. Jobs that
   were waiting in the queue and had not started run when the services start.

Rows that do not match the backup fail the restore; a backup made before
D-187 or by the update path, counted on a running box, gives a warning instead. Held by `tests/unit/test_backup.py`,
`tests/unit/test_backup_schedule.py` and `tools/backup_drill.py` (`make backup-drill`: the nightly run, layout,
status and alert, wipe, restore with the pack loaded again, an old-format restore, the Postgres settings and a
point-in-time recovery).

**Database roles after a restore (D-378).** Each service signs in as its own role and reaches only its own schemas,
which belong to group roles. A restore made as `trialbox` leaves its tables and functions owned by `trialbox`, so
the restore runs the role script itself after the trial database is restored (D-573): set
`TB_DB_ROLES_CMD="docker compose --project-directory deploy exec -T db /docker-entrypoint-initdb.d/30-service-roles.sh"`
in the environment of `trialbox restore`, run from the release folder. Without it a PRODUCTION restore ends "NOT
complete" (exit 4) and prints that line to run by hand; when the command fails the restore stops with its output:
do not start the services, fix what it names and run the restore again. `deploy/install.sh` runs the script on
every install and upgrade. Run it through the `db` container, as above: the container holds the service roles'
passwords. Run from the host without the `TB_DB_PW_*` variables, the script clears the service roles' passwords
and every service is locked out until it runs again with them.
**After `trialbox update` (D-484, T-716).** The update does not run the role script. Since D-484 the orchestrator
reads the break-glass grants and the delegation log itself, so its role must be in the `breakglass` and `team`
schemas. On a box updated to the release with D-484 and not reinstalled, every reveal under a break-glass grant and
every investigator's reveal is refused, and the audit trail says "the grant store cannot be read" or "the
delegation log cannot be read" (`screen.reveal_refused`); a coordinator's reveal is not affected. Run the role
script once after that update, through the `db` container:
`docker compose --project-directory deploy exec -T db /docker-entrypoint-initdb.d/30-service-roles.sh`. Nothing is
lost: the refused reveals can be asked again.
Since D-461 the console is not in the EDC's roles (`tbs_edc`; `tbw_edc` and `tbr_edc` since D-486): the console
reaches the EDC only through the
orchestrator, and the script takes an earlier membership away on its next run.
Since D-486 (T-718) the EDC schema belongs to an owner role of its own (`tbo_edc`, whose one member is
`trialbox`); the orchestrator is its writer (`tbw_edc`) and cannot create, alter or drop anything in it, its
append-only triggers included. Its tables are made by the box's admin, not by the orchestrator at start:
`deploy/install.sh` and `trialbox update` do it, and after a restore run it once after the role script:
`python3 -m tools.trialbox migrate`. An orchestrator that finds the schema behind its release, or a trail table
without its trigger, does not start and says to run this. The role script ends the open database sessions of a
service it moves out of an older group (once, at the update that brings D-486); the service reconnects by itself.
The script also gives the audit journal back to its owner and the services their right to write to it (D-394): until
it runs, a restored box refuses actions that must be audited. When the database is older than the audit chain (an
update rollback), the `audit-writer` service writes an `audit.journal_resync` event and goes on; `docker compose logs
audit-writer` says what it found.
Since D-541 the FHIR store signs in as its own role (`tb_fhir_store`, the owner of the database `hapi` only), never as
the server's superuser. A restore loads `hapi` as the superuser, so the same script, run after the restore, gives the
tables back to that role.


## The audit chain waits for a person

The audit log is a chain: each event carries the hash of the one before. `HEAD.json` in the audit folder says where
the chain ends, and each night `trialbox audit-sign` writes a signed head to the anchor folder (the hospital's share).
The box stops and asks for a person in three cases. In each, the message names this section.

| What you see | What it means | What to do |
| --- | --- | --- |
| `audit.anchored after a signed head`, from an update, `doctor`, the nightly `audit-sign`, `trialbox logs` or the console's audit page | A release before this one found the chain without `HEAD.json` and went on without asking. Events after the last signed head may have been removed with it. **The box still works and still writes audit events.** The nightly signed head and the audit archive wait | Steps 1 to 3 below |
| `the audit chain has no head anchor, but ... a signed head`, and the `audit-writer` service is unhealthy | `HEAD.json` is gone now. Nothing is written to the chain; the events wait in the database (the journal) and none is lost. The writer asks again after 1 minute, then 2, 4, up to once an hour | Steps 1 to 3 below |
| `signed head on the box (event N)`, or `... is a signed head over event N` | The chain no longer holds an event that was signed: it was cut below a signed head or rewritten, and `HEAD.json` was written to match. **`--reanchor` does not clear this.** | Step 1, then stop and call the vendor (page 07). Keep the audit folder and the anchor folder as they are |

1. **Look first.** As root in `/opt/trialbox`: `python3 -m tools.trialbox audit-sign --deploy deploy`. It checks the
   chain against every signed head in the anchor folder, signs nothing while the chain waits, and prints why. The
   console's audit page (Verify) shows the same. Note the event number of the last signed head and its date.
2. **Decide who signs for it.** The events after the last signed head cannot be proved complete. The site's
   administrator and the person responsible for the study's records agree on the reason (a restore, a disk fault, a
   known mistake) and write it in the site log. If nobody can explain the missing `HEAD.json`, treat it as an incident
   (page 07) before step 3.
3. **Re-anchor**, once, in the one container that may write the chain:
   `docker compose --project-directory deploy exec audit-writer python -m tools.audit_verify /data/audit --reanchor "<the reason, with the ticket>" --actor "<your name>"`.
   It rewrites no line. It adds one event, `audit.reanchored`, with the old anchor, the chain as found, the reason and
   the name, and it stays in the chain and on the console's audit page for ever. Run step 1 again after it: it now
   signs, and the night's signing and the archive go on.

What the box can and cannot show. A chain cut **below** a signed head is always found: by the nightly check, and at
once by a writer or a console that is given the anchor folder. Events removed **after** the newest signed head, with
`HEAD.json` written to match, are not found by the box alone: the head file is not keyed. That needs a head kept off
the box (the anchor folder on the hospital's share, never on the box's own disk) and frequent signing; the night's
signing leaves at most one day open. On an installed box the `audit-writer` service is not given the anchor folder, so
there the nightly check is the one that finds a cut below a signed head, within a day.


**Restore over the live stack, one command (H-100).** In a root shell on the box, from the install folder. The
private key from the envelope must be a file owned by root and readable by root alone (mode 0600), not a link: a
key on a removable stick cannot carry that mode, so copy it first and remove the copy afterwards:

    sudo install -m 0600 -o root -g root /media/usb/trialbox-backup.key /root/trialbox-backup.key
    sudo trialbox restore --last --key /root/trialbox-backup.key --yes --restart
    sudo rm /root/trialbox-backup.key

Before anything is stopped: `--last` names the newest backup `backup-nightly` recorded good
(`deploy/site/backup-last.json`), or name a file instead; the file itself is read and its sha256 must equal its
`.sha256` sidecar and the nightly's record (the restore is given that hash and refuses any other file); the key is
checked; and the space the restore needs is checked in `deploy/` (the backup unpacked, about four times the file,
and a copy of each database it replaces, up to the databases' own size). Any of these refused: exit 2, nothing
changed. `--restart` never stands for `--yes`; without `--restart` nothing is stopped and step 2's refusal applies.

`--restart` stops every service but `db` (the restore still asks compose afterwards and refuses while any other
runs). The restore runs in one container of the release's backup image (`TB_BACKUP_IMAGE`), which carries the
database client tools: the database URLs, the database superuser and the service roles' passwords come from the box's
own `deploy/.env`, as the nightly's job gets them, and travel by name only. Compose and the container engine get only
their own needs (PATH, HOME) and the engine settings `deploy/.env` names: a `COMPOSE_*` or `DOCKER_*` exported in the
shell never points the restore at another project or engine. Each data volume's folder is given to the restore so its
contents move aside within the volume, the copy of the box goes to `deploy/pre-restore`, and the service-role script
runs inside it after the trial database is restored (the paragraph "Database roles after a restore", above, is then
done). Every guard of the steps above holds: the site, the age, the copy of a box that holds data, the rows checked
before any folder moves, the hold.

**All or nothing.** The restore first copies each database it replaces. If anything fails, is interrupted (Ctrl-C) or
is stopped by a signal after the first change, it puts the databases and the folders back as they were (each folder
with its own owner and mode), holds the list jobs (`screening.after_restore`, step 4) and writes
`backup.restore_failed` with `state: rolled_back`. While it puts them back, further Ctrl-C, SIGTERM or SIGHUP are
ignored, and the host's step waits for it to the end whatever it receives. If the putting back itself fails, it says
`NOT as it was` and keeps the copy of the databases it took first (`deploy/pre-restore/pre-restore-dumps-<time>`,
readable by root alone) and names it: do not start the services; `pg_restore` that copy, or restore the kept copy of
the box. `--no-copy` on the host needs `--yes-really`: without the kept copy a failed restore whose putting back also
fails leaves nothing to go back to. One restore runs at a time (`deploy/site/restore.lock`); a scratch folder
(`deploy/.restore-*`) left by a restore that was killed is removed by the next one.

**The hold after a restore (step 4).** `sudo trialbox doctor --env-file deploy/.env`, typed on the box's host, shows
the hold (`restore_hold`, H-136). It reads it through the box (`docker compose exec db`, as the backup asks the job
count), never with the host's own Python or a database address on the host, so it reads it right after a restore.
Its line is one of three:

- `WARN restore_hold HELD since <time> by <who>: ...` with the reason the restore gave: the box is held;
- `PASS restore_hold released ...`: no restore is waiting (or the hold was never set on this box);
- `FAIL restore_hold UNREADABLE: ... (<cause>)`: the hold could not be read (the `db` service does not run, the
  box file cannot be trusted, the container engine does not start). Treat the box as held: read the flag on
  `/ops/flags` and run the doctor again once the cause is fixed. It is never a pass.

The same line shows on every kind of box (PoC or PRODUCTION) and in the host check (`deploy/check_host.sh`, whose
doctor runs in the box image: the host reads the hold through the box and hands it in). The doctor is a check,
not an install stop (D-1091): a held or unreadable hold stops no install, start or update. On a PoC box the host
check's FAIL lines warn and the step goes on; on a PRODUCTION box they are the install's FAIL lines, as before.

**Releasing the hold.** When every listed event is re-applied, the data steward (or the administrator) opens
`/ops/flags` in the console, chooses `released` for `screening.after_restore`, types the reason (who re-applied
what) and presses Change. That opens a second page, "Please confirm", that names the flag, its old and its new
value: the change is made only by its button "Yes, do it" (the form alone changes nothing). The page then shows
`held → released`, by whom and when, with the reason; the change is in the audit. There is no release command:
`trialbox model release` is for the models' flag (page 19). Run `trialbox doctor` again: it says `released`.

**What it says.** Every end says the box in one line: `restore: the box now: <what compose says runs>; the data:
<restored | not changed | put back as it was | NOT as it was>; next: <the command>`. With `--restart` every service
the box's compose defines starts again and is waited for until healthy (`docker compose up -d --pull never --wait`:
every image from the bundle, as an update starts the box, unless deploy/.env says `TB_INSTALL_PULL=missing`), whatever an
earlier run left stopped, when the restore ended complete (exit 0) or held (exit 4 with `hold: held`). A restore
refused inside before any change starts again only the services this run stopped (`--no-deps`), and names the ones
it found stopped without starting them: an earlier run may have left them stopped on data that is not as it was.
After a put-back the next step is to read the error and start them as they were; otherwise they stay stopped. After the start the whole expected set is checked (the services compose defines, less the
one-shot ones; after a refused restore, what this run stopped and `db`, and a run that stopped nothing starts
nothing and never prints a start of the whole project): `the services run again and are healthy: 16 of 16`, or `did not all come back healthy: 13 of 16`
with the names and exit 1 (a restore that ended 4, NOT complete, keeps 4). A second Ctrl-C while the command says
the box's state ends the asking, not the line: it then says `the box now: not asked (interrupted again)`. Then the hold is said: released by the restore, or held until a person releases it (step
4). **A restore that was interrupted (Ctrl-C, a closed session) is run again with the same command:** the re-run
stops what runs, restores, starts every service and checks them all; a second restore leaves the box held (step 4). A stop that
fails, an interrupt or an error on the host is said the same way and kept as an audit event
(`deploy/site/backup-audit-pending.jsonl` while the orchestrator is down). Compare the `rows` the restore prints with
`databases` of `trialbox backup-verify <file> --key <private key>`: they are equal. The steps above are the same
restore by hand.

**A box whose nightly sends the lake to restic (H-132).** Its backup file holds the databases and every folder but the
lake, which is in the restic repository beside it (`trialbox-restic`). `backup-verify` and `restore` (both forms
above) then need one more option to open that repository: `--restic-from-box` on the box itself (the box's restic
key under its unsealed KEK), or `--restic-share <file>` once per custodian's share on a new box. Without one, both
refuse and name the two options. The file's folder is read as a whole (the sidecar, the repository and its escrow
file), read-only.

**A rerun of the same restore takes off its own hold (INT-M5, ruling 7178128292).** This narrows "run a second time,
the box stays held" in step 4 and "a second restore leaves the box held" above, for one case only. The restore writes
its id first in the hold's reason: `[restore <the backup's sha256>@<the run's start, UTC>]`. A rerun of the same
command takes the hold off only when all four of these are true:

- it restores the same backup file;
- the hold carries an earlier restore's id for that backup;
- nothing changed the hold since: its last change on `/ops/flags` is that restore's own setting of it;
- the rerun ends complete.

The release is in the audit: `flag.set` names both restore ids and the backup's sha256, and `backup.restored` carries
`restore_id` and `rerun_of`. This holds whether the first run was ended by Ctrl-C or SIGTERM (put back, held), by
SIGKILL, or by a power loss (held on the restored database). Every other hold stays for a person, as above: one a
person set or changed, one of another backup, one of a restore that did not end complete, and one with an earlier
restore's set-aside audit chain on the box. Read `trialbox doctor` (`restore_hold`) after the rerun.

**Restoring into a second, empty box.** A box newly installed beside the first (new hardware, a stand-by) takes the
first box's backup with the one command above, given four things. Each one missing is refused before anything
changes:

1. **The backup file, by name.** `--last` reads this box's own nightly record, and a new box has none. Copy the first
   box's backup file and its `.sha256` sidecar into one folder on this box and name the file; the sidecar must match.
2. **The key, owned by root, mode 0600.** `--key` names a file owned by root and readable by root alone, not a link:
   copy it from the stick first, as above.
3. **`--no-copy` with `--yes-really`, or a target for the copy.** A box that holds data is kept as an encrypted copy
   first, which needs this box's public key and a folder (`--public <key> --keep-to <folder>`). On a box that has no
   backup key yet, `--no-copy --yes-really` goes on without the copy.
4. **The same site.** The backup's site must be this box's `TB_SITE_ID`. A box installed by the four questions takes
   its site id from the hospital's name: give it the first box's name on "Information still needed" first, then
   compare `grep '^TB_SITE_ID=' deploy/.env` on both boxes. The id is set once, from the first name given: a later
   name changes the display name only. A backup taken while the box still ran on the stand-in name carries the
   stand-in id (`TRIALBOX-SITE-NAME-NEEDE`): once the name is given, it restores, on this box or another, only with
   `--other-site`. Otherwise `--other-site` is for moving a site to new hardware only.

The command, from the install folder of the second box:

    sudo install -m 0600 -o root -g root /media/usb/trialbox-backup.key /root/trialbox-backup.key
    sudo trialbox restore /srv/restore/trialbox-<site id>-<time>.tbbak --key /root/trialbox-backup.key --yes --restart --no-copy --yes-really
    sudo rm /root/trialbox-backup.key

## Secrets (D-128, D-138): the one place to rotate them

| Command (as root, in `/opt/trialbox`) | What it does |
| --- | --- |
| `python3 -m tools.trialbox secrets status` | each token's file, mode and age; never a value |
| `python3 -m tools.trialbox secrets rotate` | **at handover, then yearly**: every service token, the operator token, both database passwords, the model key and the console's signing key |
| `... secrets rotate --service orchestrator` | one service's token; only it restarts |
| `... secrets rotate --service db` | the two database passwords (`ALTER ROLE`, on stdin) |
| `... secrets rotate --service actor` | the console's key that signs the acting person (D-485): a new `deploy/secrets/services/actor-sign.key`; the console and the orchestrator restart |
| `... secrets status` | lists the console's signing key ("actor signing key"): `present` must be true on a box with service tokens, or nobody's actions are signed. The update that brings the release with D-485 to an installed box does not make the key and rolls back (nothing is lost); see D-485, "Not done" |
| `... secrets rotate --service model` | the on-box model servers' key (D-437): a new `deploy/secrets/model/llm.key`; the vLLM servers, model-guard and the gateway are recreated in one command (model calls fail until vLLM has loaded again) |
| `... secrets init` | make any missing token and the orchestrator's actor key (the installer runs it; run it once on a box updated past D-143, else chart-number reveals and exports are refused) |

The mail passwords and a cloud-model key are the hospital's: change them at their source, put the new value in
`deploy/.env`, then `docker compose --project-directory deploy up -d --force-recreate mail-gateway` (or `gateway`). A
box installed before step 8 keeps its shared `TB_SERVICE_TOKEN` (with a warning) until the first full rotation;
outside DEV and TEST the gateway (D-437) and the orchestrator (D-464) refuse it, so run `secrets init` first. The
administrator's token for scripts is `deploy/secrets/services/operator.token` (header `X-TB-Service-Token`).

**The health page's watcher** (D-1365). With `TB_BACKUP_ALERT_ROUTE=health-page`, name the person who opens it every
working day in `TB_BACKUP_ALERT_WATCHER`; the install note and `doctor` show the name, or warn while nobody is named.
A name holds letters and digits of any script, single spaces and `. , - ( ) （ ） / ’ ' ・ · 〜 ～` only (`'` not
first or last), at most 100 characters; anything else (a line break, a double quote, `$`, a backslash) is refused,
so a name can never add or change a setting.

**A PRODUCTION install needs a backup target off the box and the hospital's audit share as its anchor folder**
(10K-4, D-1390). `python3 -m tools.trialbox finish-check --deploy deploy` accepts only what it can show and refuses
what it cannot tell. Each folder `deploy/.env` names must be there, with no link in its path and no bind of another
folder behind it, not a system folder (`/etc`, `/home`, `/opt`, `/usr`, `/var/lib`, `/var/log`, `/boot`, `/tmp`,
`/media`, `/proc`, `/sys`, `/dev`, `/run` ...) nor around one, not the install folder, its `deploy/secrets`, the feed
folder or the audit data, on a disk or a share (ext4, xfs, btrfs, exfat, vfat, ntfs3, nfs, nfs4, cifs, smb3), never a
memory file system. In PRODUCTION one target of `TB_BACKUP_TARGETS` must be a share the box does not serve, or a
physical disk (not a loop device, zram or a virtual disk) holding none of the box's own data: not the system disk
(another partition of it is not enough), not Docker's data root, not the audit folders; for a disk
`TB_BACKUP_OFFBOX` names the same folder, so the nightly backup counts it too. `TB_AUDIT_ANCHOR_TARGETS` must be the
mount point of the hospital's audit share (nfs, nfs4, cifs, smb3; mount it `nosuid,nodev`), under folders only root
may write; the anchor, backup and log folders do not overlap. Of the folders the first-run page asks, the console
reads the anchor folder only, read-only; it is checked before it is mounted and again at every start of the stack
(`deploy/settings_guard.sh`), which does not start when the rule no longer holds. `deploy/install.sh` checks a re-run
before the bundle step (nothing is loaded or changed when it refuses) and every install before the stack starts; when
an older install.sh loaded this release, the release that run brought is applied (as after `trialbox update`) and the
refusal says so: correct `deploy/.env` and run the install again. `deploy/box-install.sh` checks after the first-run
answers are applied, before the restart; the first-run page does not open again: mount the share or disk at the
folder named, or correct the line, then `sudo deploy/box-install.sh --firstrun`. **An installed PRODUCTION site that
runs `deploy/install.sh` again** (02, the anchor folders; 05, after a restore and for the EDC tables; 12, the TLS
check per release) stops there until both are set; `trialbox update` and `trialbox restore` do not run it.

**The host commands' own environment (H-88, D-1089).** `trialbox` and `python3 -m tools.trialbox` find the product
from their own folder and read `deploy/.env` themselves, so `sudo` and cron need nothing more; a command that needs
the box image's libraries runs in a one-off container of `TB_IMAGE` (never pulled). A backup cron file from before
H-88 sets `PYTHONPATH`: `trialbox doctor` (`backup`) warns until
`python3 -m tools.trialbox backup-install --deploy deploy --no-first-run` is run again.

**The backup schedule without cron (H-92).** Where systemd is the init, `backup-install` writes the schedule as
timers (`systemctl list-timers 'trialbox-backup-*'`: 04:45 nightly, hourly check; a missed night runs after boot)
and removes `/etc/cron.d/trialbox-backup`; elsewhere the cron file stays and needs a running cron daemon. Never both
(D-1090). An existing box moves with `python3 -m tools.trialbox backup-install --deploy deploy --no-first-run`.
`trialbox doctor` (`backup`) and `backup-status` name the schedule in use and the one action when none fires or both
would.

## What an update replaces, and a loose services/ or models/ (H-144, D-1463)

An update replaces the signed host tree only: `deploy/`, `tools/`, `libs/` and `schemas/` in the install folder. The
services' code and `models/` come with the box image, never from the install folder. A `services/`, `models/`, `rulesets/`, `catalogue/` or `eval/`
folder found in the install folder (one left from an install before the signed host tree) is not the release's: no
update replaces or checks it, and nothing reads it. The update names it at its end ("update: note (H-144): ...") and
leaves it; `sudo trialbox doctor --env-file deploy/.env` WARNs `release_tree` while it is there, naming each folder
and the command that removes it (a FAIL when the command's own PYTHONPATH holds the folder: run that way, a host
command would import it). Look in the folder for a change of your own first, then, for example:

    sudo rm -rf -- /opt/trialbox/services /opt/trialbox/models

The doctor's checks that need the box image's libraries, the services' code or `models/` (`doctor.IMAGE_CHECKS`) run
in a one-off container of the box's own image when `trialbox doctor` is typed on the host; a check that cannot run
there is a FAIL that says why, never a pass.

**The update's networks (H-150).** Before the database starts, an update's database step (`python3 -m tools.trialbox
db-up`, run by the release being installed) puts the box's networks on that release's settings with the box's own
compose, then recreates through compose every container that does not answer to its service's name on one of its
networks; the line says so ("db, orchestrator recreated through compose (no service name on a network)"). A container
still without its name stops the update, which is then rolled back. Before H-150, a release that changed a network's
settings (H-137's address range behind Caddy) left `db` with no name on trialbox-net, and the services could not find
it ("failed to resolve host 'db'").

**The rollback's database restore (H-151).** A release that carries H-151 puts each database back by loading the
dump into a database made fresh beside the one in place (`<db>_tbrb`, with its owner, encoding, collation and grants),
and swaps the two names in one transaction only when the whole load is in; the replaced database (`<db>_tbold`) is
then dropped. A restore that fails or is stopped leaves the database in place as it was and the marker in place: run
the rollback again. The volume needs room for the largest database twice while it runs; the update's space check
counts it.
