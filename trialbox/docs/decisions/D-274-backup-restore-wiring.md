**D-274 Backups that a box really takes and a restore that cannot lose the box: one point in time, a content hash
of any size, a copy before a restore, an audit row, and the backup wired at install.** Card T-117b (plan v6 §6.2.5,
`docs/plan/28-master-plan-v6.md`) with fix group D-274 (FG-E of the critical-issues register,
`docs/reviews/2026-11-10-critical-issues-register.md`): rows CR-056 and CR-057; the deep-review findings CR-058,
DATA-024, OPS-028, OPS-045 (restore defects), OPS-046, OPS-048 and DI-10, DI-11, DI-12
(`docs/reviews/2026-11-10-deep-review/`). Branch `agent/T-117b-backups-d274`, one draft pull request. Date 2026-11-11.
Status: proposed. Follows D-126, D-187 and D-188.

*Why.* The backup code was merged (D-187, D-188), but install never installed its cron, `doctor` never looked at it,
nothing ran it in Docker, and the one alert went to `root` on a box with no mail. A restore over a box that held data
kept no copy of the databases, checked neither the site nor the age, and on a whole database left behind tables the
backup did not hold, so its own row check failed after everything was replaced (CR-056). The per-table content hash
built one string over the whole table, which Postgres refuses past 1 GB (CR-057). The two databases and the files
were read at different moments while the box wrote (DI-11). The restore left no audit trace, and events parked
while the orchestrator was down were never sent (DI-10). A backup held no `deploy/.env` or settings (DI-12).

1. *Content hash* (CR-057). A table's hash is `rs1:<a>:<b>`: the sums of the first and the last 64 bits of each row's
   md5 (`backup_schedule.row_agg`). A sum does not depend on row order and never grows into one value, so any table
   hashes. The manifest names the scheme per database (`row_hash`); a backup without it used `md5`, and its restore
   still computes `md5`.
2. *Restore* (CR-056). Before anything changes: the backup's site must be `TB_SITE_ID` (`--other-site` to move a
   site), it must be at most 14 days old (`--older-ok`) and not dated in the future. A box that holds any table or
   file is first kept whole as one more encrypted backup (`keep_copy`: `pg_dump` of each database, rows counted, the
   data folders) in `--keep-to` (default `deploy/pre-restore`, never pruned), with the box's public key; without a
   key the restore refuses, unless `--no-copy`. Each database is then emptied (its `tb_prefix` schemas, or on a box
   every schema but the system ones, in one transaction), restored, and its rows checked **before** any folder
   moves. A failure is audited (`backup.restore_failed`) and its message names the kept copy and the command that
   puts it back.
3. *Audit* (DI-10). A restore appends `backup.restored` (file, site, age, kept copy, rows, folders, missing packs) to
   the restored audit log (`audit` in the layout, else `TB_AUDIT_DIR`). The nightly run's events kept in
   `deploy/site/backup-audit-pending.jsonl` are sent first, in order, with the next event that can be sent.
4. *One point in time* (DI-11). The nightly run pauses every running service but `db` (`docker compose pause`) from
   before the first snapshot until the backup container has read every volume, and unpauses them whatever happens.
   `backup-last.json` records `point_in_time` (held, paused services, seconds). `TB_BACKUP_QUIESCE=off` leaves them
   running and the record says so.
5. *Host part* (DI-12, OPS-046). Each nightly backup holds `host/`: `deploy/.env`, the settings file, `deploy/site`,
   `deploy/secrets` (the pgBackRest cipher, the public key) and the volumes `authelia-data` and `caddy-data` (the
   proxy's CA: without it every clinic PC must trust a new root). `traces-data` is left out on purpose: traces are
   diagnostics, not needed to rebuild, and may hold note text (PV-13). A restore writes `host/` only to a folder
   named `--dir host=<folder>`; it never overwrites `deploy/.env` by itself.
6. *Install* (CR-058, OPS-028). `deploy/install.sh` runs `python3 -m tools.trialbox backup-install --deploy deploy`
   after the stack is up: it writes `/etc/cron.d/trialbox-backup` (0644, the install folder, `MAILTO` from
   `TB_BACKUP_MAILTO` only on a host with `sendmail`, else empty), sets up WAL archiving (7.) and runs the first
   backup when the key is there. In PRODUCTION it refuses, and install stops, without an alert route
   (`TB_BACKUP_ALERT_CMD`, or `TB_BACKUP_MAILTO` with a mail transfer agent); `backup-status` is red without one too.
7. *WAL archiving on by default* (DATA-024, OPS-048). Unless `deploy/.env` says `TB_PG_ARCHIVE_MODE=off`,
   `backup-install` turns it on when the db image carries pgBackRest and the repository is off the box
   (`TB_PGBACKREST_REPO`, else `pgbackrest-<site>` on the first off-box target): the cipher pass is made once
   (0600), the stanza is created, archiving is switched on, `db` is recreated and `pgbackrest check` must pass, or
   archiving goes off again (a failing `archive_command` would fill the disk). The compose default stays `off`, so a
   box without pgBackRest never archives into nothing.
8. *Doctor* (CR-058, OPS-028, OPS-048). Check `backup`, read from the deploy folder of `--env-file`: FAIL in
   PRODUCTION (WARN elsewhere) without a target, an off-box target, an alert route or the cron file, and when the
   newest good backup is missing or older than `TB_BACKUP_MAX_AGE_HOURS`; WARN in PRODUCTION while WAL archiving is
   off. On a platform it passes and points to the platform's `backup_target` check.
9. *OPS-045.* The IT pack no longer calls the 4-hour RTO measured; the measurement on the 50,000-patient set stays
   with T-213b.

*Evidence.* `tests/unit/test_backup.py` (site and age refusals, copy or refusal, a failed row check that names the
copy and moves no folder, a whole-database restore that leaves no extra table, the row hash, the host part, the
audit row), `tests/unit/test_backup_schedule.py` (pause and unpause around the snapshots and the container, the host
files, parked audit events sent in order, the cron file and the alert route, WAL archiving set-up and its fall-back,
`backup-install` running the first backup, install.sh's order), `tests/unit/test_trialbox_doctor.py`
(`doctor` FAILs on a missing off-box target, route, cron file or an old backup); `tools/backup_drill.py` restores over
a box with data and checks the kept copy and the audit row.

*Not done here.* The db image does not carry pgBackRest yet (`deploy/docker/db.Dockerfile` and `deploy/images.lock`
are T-673's files), so on the default image archiving stays off and `doctor` warns. The update path's rollback
(`tools/trialbox/update.py`) still leaves later tables behind and is not audited; point-in-time restore is not
audited. `backup-status` does not send through the mail gateway (it has no send command). No real Docker run here:
the compose steps are tested with a recording runner; the box rehearsal (PR #68) runs them for real.
