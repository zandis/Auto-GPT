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

**Backup** (D-126, D-187, D-188). Once, with hospital IT: `python -m tools.trialbox backup-keygen --private
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
2. **Schedule.** `deploy/install.sh` installs it (D-274): as root in the install folder it runs `python3 -m
   tools.trialbox backup-install --deploy deploy`, which writes `/etc/cron.d/trialbox-backup`, turns WAL archiving
   on when it can (below), and runs the first backup once the backup key is there (run the command again after
   `backup-keygen`). In PRODUCTION it refuses without an **alert route**: `TB_BACKUP_ALERT_CMD` (a command that
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
   or its pgBackRest step failed, or when WAL archiving fails, is off on the server, or has archived nothing for 26
   hours. Red is audited (`backup.alert`, again every 24 h, `backup.alert_cleared` when it ends), mailed by cron to
   `MAILTO`, and piped to `TB_BACKUP_ALERT_CMD` when set (a command that reads the message on stdin, e.g. the
   hospital's mail tool). The message holds no patient data. Fix the cause, then run `backup-nightly` by hand.
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

**Restore drill (T-730d, D-892).** Proof that the newest backup restores, without touching the box's data. Hospital
IT brings the key from the envelope and types, on the box's host (the Operations page's backups tab shows this line
with the newest file filled in): `sudo python3 -m tools.trialbox restore-drill <backup file> --key <the key>`. It
checks free space first (the unpacked backup and scratch databases; it says how many GB it needs and starts nothing
when short), opens the backup with the key and checks every file against its signed manifest, restores each
database into a scratch database (`tb_drill_<id>_<name>`, never the live one), compares rows and content hashes
with the manifest, and drops the scratch databases and the unpacked files, after a failure too. Exit 0 is a pass,
1 a fail, 2 nothing started. The result (never the key or its path) is the box's key-check record and an audit
event (`backup.restore_drill`): the health check's `backup_verified` turns red after `TB_HEALTH_VERIFIED_DAYS` (100)
days without one, or at once on a failed drill until one passes, and a failed drill is a backup problem that goes
through the alert route (mail, or the health page). Run it at least every 90 days, after hardware changes and before
go-live acceptance (§6).

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
   ingest and retention run. `trialbox doctor` shows the hold (`restore_hold`). When every listed event is re-applied, the data steward (or the administrator) sets the flag to `released` on
   `/ops/flags`, with the reason (who re-applied what); the change is in the audit. If the restore prints that the
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


## Lake ids per patient (D-1253): the one rebuild

**For a box that holds synthetic data only.** From the release with D-1253, the id of a patient's record (a visit,
a diagnosis, a lab result, an order, ...) is made from the hospital's number **and the patient**; before, from the
number alone, and two patients with the same order number were one record. Every such id changed once. The first
night after the update refuses, before it reads or writes anything, with one message that names what still holds
ids of the earlier rule (the lake's snapshots, the OMOP store, the derived store) and this step; the vector store,
the patient twin, the candidate pool and the EDC drafts refuse at their own first write in the same words. Nothing
is half-migrated, and nothing goes on until the box is rebuilt once, from its sources:

1. **The plan** (changes nothing): what is there, per store, and what the rebuild clears. It runs from
   `/opt/trialbox` as the box's admin (`TB_DB_URL` of `deploy/.env`), in a one-off adapter container that sees the
   lake: every store is read, not only the adapter's.

   ```sh
   python3 -m tools.trialbox id-rule-rebuild
   ```

2. **EDC values a person decided.** A value a person confirmed, edited, signed or sent is a record, and its trail is
   append-only (D-281): the rebuild never clears it. While any such value cites a lake row of the earlier rule, the
   rebuild stops before it changes anything and names each study with its count. Then a person decides, per study,
   with the trial team: export the study's EDC values first (the study's ODM export, `GET
   /api/v1/studies/<study>/edc/export/odm`) and keep the file with the study's records; what happens to the study's
   EDC store after that is not decided yet (D-1253) and is asked of Aimedics. Open drafts that nobody decided are
   cleared; the next draft run makes them again.
3. **The rebuild** clears what was made from the old ids and stamps every store with the new rule: the lake's
   snapshots and their copies (the site key, the pid map, the site set-up's facts, the embedding cache and the FHIR
   ledger stay), the OMOP store's feed records of patients' clinical data (the persons stay), the derived scores,
   the note chunks, the patient twin's documents and the candidate pool. What it cleared is in
   `/data/lake/id_rule_rebuild.json` (counts only).

   ```sh
   python3 -m tools.trialbox id-rule-rebuild --yes
   ```

4. **The first night after it** reads every table whole (there is no snapshot to merge over), loads OMOP and the
   lake from it; the next jobs fill the derived scores, the note chunks, the twin and the pool again. fhir-store
   follows by itself: its ledger deletes the old ids and loads the new ones.

What stays as it was: **published job outputs** (candidate lists, CASE sheets) made before the rebuild cite the old
ids and cannot be traced into the rebuilt lake; the **audit chain** is not touched. A site whose export sends a
deleted row as its bare key (no chart number) must now send the chart number with it: a delete without its patient
removes nothing and is counted (`deletes_without_patient` in the night's report), since the same number may be
another patient's.

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
