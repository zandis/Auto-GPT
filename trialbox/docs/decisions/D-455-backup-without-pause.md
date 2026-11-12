# D-455 The nightly backup without a pause: what "point in time" means while the services keep running; step limits from the size of the data; the watchdog leaves a paused service alone

- **Task:** T-691 (`docs/plan/28-master-plan-v6.md` §6.2.10; `docs/plan/31-master-plan-v6.1-addendum.md` §3.4)
- **PR:** this branch (`agent/T-691-backup-without-pause`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** scale review 2026-11-11 F-02 (Blocker: the nightly backup pauses every service for the whole dump,
  with 7,200 s per step), F-03 (rest: the console's Backup stops the services under a running job without asking;
  the two dumps have no limit), F-25 (the box's part: a fixed limit per backup step), F-26 (14 backups kept
  whatever their size)
- **Builds on:** D-187 (one snapshot per database, the manifest from the same snapshot), D-188 (the nightly
  schedule), D-274 (DI-11 the pause, now opt-in; the host part), D-360 (the watchdog), D-462 (the lake's
  build-beside layout: a backup never reads a half-built snapshot), OD-10 (no fixed limit)

## Decision

1. **The snapshot alone is the point in time; nothing is paused by default.** `TB_BACKUP_QUIESCE` now defaults to
   `off`. What the backup promises, written into `backup-last.json` (`point_in_time`):
   - each database is **one transaction snapshot** (`REPEATABLE READ`, `pg_export_snapshot`, `pg_dump --snapshot`):
     its dump, its row counts, its content hashes and the hospital's own reference rows are exactly one state of
     that database, and a restore must give those rows back or it fails (D-187, unchanged);
   - the two databases are snapshotted one after the other, `trialbox_wf` first, then `hapi`; the files (lake,
     objects, audit, rulesets, orchestrator files, mail, secrets, console) are read after both snapshots, each file
     in one consistent read (a file that changes while it is read is read again, D-187), and the lake's half-built
     snapshots and reader links are never read (D-462);
   - so the backup is a **window**, `snapshot_at` to `files_done_at`, both recorded: rows written after a
     database's snapshot are not in the backup; a file written during the window may be (an object or an audit line
     the restored database does not reference yet, which is harmless: the audit chain stays a valid prefix, an
     object nobody names is not read). The window is what a restore after a disaster loses, and it is minutes, not
     the 30 to 75 minutes of frozen services the pause cost every night at 50,000 patients.
   `TB_BACKUP_QUIESCE=pause` keeps D-274's pause for a site that wants one instant for the databases and the files,
   with two changes: the pause is never taken while a job runs (the backup asks the orchestrator's job table first;
   a running job means the snapshot-only backup, and the record names the job count and says so), and while the
   services are paused the backup holds the **maintenance flag** (6.) so the watchdog never restarts them.
   The row asked that "the backup waits for a running job". It does not wait: a job can run for a day at 500,000
   patients and a wait would need a limit OD-10 does not allow. The snapshot alone is consistent, so a backup under
   a running job needs no wait.
2. **Step limits come from the size of the data (OD-10).** Every backup step that used a fixed 7,200 s (the
   snapshot, the copy out of the db container, the backup container, the update path's backup command) or 4 h
   (pgBackRest) now gets `TB_BACKUP_STEP_START_S + bytes / TB_BACKUP_MIN_MBPS` seconds, where `bytes` is measured
   before the step: `pg_database_size` for a snapshot and its copy, the sum of the database sizes for pgBackRest,
   the dumps plus the volumes the container reads (walked on the host; the last good backup's size for a volume the
   host cannot read) for the backup container. Both settings are declared with their reason
   (`libs/tb_common/config.py`): `TB_BACKUP_MIN_MBPS` (default 5) is the slowest rate at which a step still counts
   as working, a tenth of the 30 to 50 MB/s the review measured for `pg_dump` on a box disk, so a slow share still
   finishes and only a hung step is stopped; `TB_BACKUP_STEP_START_S` (default 900) is the part of a step that does
   not grow with the data (a container start, a connection, the catalogue). When no size can be measured the step
   has **no** limit (never a fixed guess): a hung step then holds `backup.lock`, the next night says so, and the age
   alert (36 h) tells a person. The update path's two dumps, which had no limit, get the same rule.
3. **Retention by size as well as by count (F-26).** After a nightly run, a target keeps this box's newest backups
   while they are at most `TB_BACKUP_KEEP` in number **and** their total size is at most `TB_BACKUP_KEEP_SHARE`
   (default 0.5, declared: the part of a target this box's backups may fill, leaving the rest for the share's other
   users and the next night's file) of the target's capacity. The newest backup is always kept, whatever its size.
   pgBackRest is already held to three weekly full backups with their differentials and WAL
   (`deploy/pgbackrest/pgbackrest.conf`); that part of F-26 was closed before this card.
4. **The console's Backup no longer stops the services.** On a site box the console's "Back up now" runs the same
   snapshot backup as the night (under the same `backup.lock`, recorded in `backup-last.json` and audited
   `backup.done` / `backup.failed`), never pauses and never stops a service; its confirmation says so. A request
   without the console's new `mode` (one queued by an older console, which confirmed a stop) keeps the old
   quiet-box path, but is refused while a job runs: it never stops the services under a running job without the
   person asking again.
5. **The watchdog skips a paused container.** A container Docker reports as paused is never restarted, whatever its
   health says (a paused service's probe times out, so Docker calls it unhealthy after a few minutes); its
   unhealthy clock does not run while it is paused.
6. **A maintenance flag.** `deploy/watchdog/maintenance` (JSON: who, why, since, and the pid of the process that
   holds it). While it exists the watchdog restarts nothing and says `maintenance` for each service it would have
   acted on (the dry run too). A flag whose holder process is gone is stale: it is ignored (and removed outside a
   dry run), so a killed backup never leaves the watchdog off. A flag written by a person (no pid) stays until the
   person removes it; the watchdog names it on every pass. No time limit is attached to either.

## What is already closed (since the review was written)

- D-462 (T-722) made the lake build beside the served bytes and the backup leave out every `.building` / `.old`
  path and the reader links: a backup taken while a rebuild runs never holds a half-built snapshot. That is what
  lets item 1 read the lake without a pause.
- F-03's core (the console's backup left the services stopped for ever) was fixed with the review
  (`tests/unit/test_ops_backup_resumes.py`).
- pgBackRest's retention is three full backups (item 3).

## Open (not built here)

- **T-726** makes the backup a step of the night (after the ingest and the jobs) instead of a 04:45 clock time.
- **The platform (k8s) jobs** keep `activeDeadlineSeconds: 21600` (`deploy/platform/base/day2.yaml`) and
  `SPOOL_TIMEOUT_S`: a Kubernetes deadline is fixed in the manifest, so the size rule needs the job to set its own
  limits; left for a platform card (F-25's platform half).
- A progress line per step on the console (the review's "no progress") is not built: the result names each step's
  size and limit only after the run.
