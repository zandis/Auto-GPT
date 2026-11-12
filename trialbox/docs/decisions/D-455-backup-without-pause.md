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
   **The backup waits for a running job (R1, the owner's ruling of 2026-11-12).** Before its snapshot the nightly
   asks the orchestrator's job table every minute and waits while a job runs or is queued (a count that cannot be
   taken counts as running), at most `TB_BACKUP_JOB_WAIT_S`. When the bound passes the backup is **not** skipped:
   it takes the snapshot anyway (it is consistent on its own) and records `beside_jobs` (count, each job's id and
   type, never a patient; the seconds waited and the bound) in `backup-last.json` and in the `backup.done` /
   `backup.failed` audit detail. The bound is a declared setting (OD-10) whose default comes from the night's own
   schedule: the age alert fires 36 h after the last good backup and the cron starts a backup every 24 h, so a
   night's backup may end at most 12 h after its 04:45 start and keep the box green; half of that, **6 h
   (21,600 s)**, is the wait, and the other half is left for the backup itself (1 to 5 h for 200 to 500 GB at
   500,000 patients, review F-02). The console's "Back up now" does not wait (a person asked for it now).
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

7. **The lake is read under its own lock (review H1).** The lake's served files (`db/`, `parquet/`) are listed and
   read while the backup holds `lake/.rebuild.lock` (the `flock` of D-462; `flock` needs no write access, so the
   backup container's read-only mount takes it too). A rebuild's swap, a hold and a release wait for that read (a
   job that starts then waits for it too): it is a lock on the lake, not a pause of the services. After the read,
   each file taken with its sidecar must hash to it and the listing must be unchanged, or the backup fails; a
   listing that is not one state is listed again up to `READ_TRIES` when no lock could be had, and fails at once
   under the lock (the lake on disk is then damaged and a person looks). The rest of the lake (NDJSON, the vector
   store, the site inputs) is read after, without the lock. **A restore runs the lake's own check** (each
   `db/<snapshot>.duckdb` and its Parquet files against their sidecars, the folder not empty) on the restored lake
   before any folder is put in place, refuses on a problem (a file that contradicts its sidecar, an empty Parquet
   folder), and reports `lake_check`; a file with no sidecar at all (a lake from before sidecars) is counted as
   `unsigned`, not refused. The lock file itself is not backed up.
8. **Retention counts only good backups (review M1).** A file is a backup only with its `.sha256` sidecar. The
   nightly prunes after every copy of the new file is checked; the size rule never leaves fewer than two good
   backups on a target, and when two are still more than the share allows the run records an error (red) instead.
9. **An unknown job count refuses (review M2, LOW).** A count that cannot be taken never allows a stop (an old
   console request) or a pause. The count includes queued jobs (they would start under a pause or a stop).
10. **Events after the snapshot are listed at a restore (review M3).** The audit chain is copied after the
   database snapshots, so it can hold events whose effect the restored databases lost. Each backup records
   `snapshot_at` per database (milliseconds; `created_at` for older backups). A restore lists the restored chain's
   events after the earliest snapshot whose loss is unsafe (`REAPPLY_EVENTS` in `tools/trialbox/backup.py`:
   opt-outs, erasures of EDC drafts, break-glass, EDC signatures and submissions, consent changes), with time,
   event and place in the chain (never the detail), in its report (`to_reapply`, `complete: false`), audits
   `backup.restore_reapply`, and the CLI exits 4 ("NOT complete") until a steward has re-applied them. No hold
   that keeps the box from screening until a steward acknowledges exists yet: see Open.
11. **A pause is never taken without every limit (review M4).** In pause mode every size is measured before the
   pause; a size that cannot be measured means the snapshot-only backup, never a step without a limit under a
   pause and the maintenance flag. The small queries (sizes, the job count) have `TB_BACKUP_QUERY_TIMEOUT_S`
   (default 60, declared: a catalogue query, not work sized by data).
12. **Smaller fixes (review LOW).** The maintenance flag records the holder's start time, so a reused pid does not
   keep the watchdog off; a paused container is printed as `paused` (not restarted); `TB_BACKUP_MIN_MBPS`,
   `TB_BACKUP_STEP_START_S` (above 0) and `TB_BACKUP_KEEP_SHARE` (above 0, at most 1) are checked, and a bad
   value fails the run with a `backup.failed` record naming it.

## What is already closed (since the review was written)

- D-462 (T-722) made the lake build beside the served bytes and the backup leave out every `.building` / `.old`
  path and the reader links: a backup taken while a rebuild runs never holds a half-built snapshot. That is what
  lets item 1 read the lake without a pause.
- F-03's core (the console's backup left the services stopped for ever) was fixed with the review
  (`tests/unit/test_ops_backup_resumes.py`).
- pgBackRest's retention is three full backups (item 3).

## Open (not built here)

- **R1 is decided and built** (the owner, 2026-11-12): the bounded wait of item 1. T-726 (the night as a chain) may
  later start the backup after the night's jobs instead of at 04:45; the wait then rarely runs.
- **A steward's acknowledgement hold after a restore (M3):** the list, the report, the audit event and the CLI's
  exit 4 are built; a hold that keeps screening off until a steward acknowledges the list (and `doctor` showing it)
  needs a place to record the acknowledgement; no existing mechanism fits.

- **T-726** makes the backup a step of the night (after the ingest and the jobs) instead of a 04:45 clock time.
- **The platform (k8s) jobs** keep `activeDeadlineSeconds: 21600` (`deploy/platform/base/day2.yaml`) and
  `SPOOL_TIMEOUT_S`: a Kubernetes deadline is fixed in the manifest, so the size rule needs the job to set its own
  limits; left for a platform card (F-25's platform half).
- A progress line per step on the console (the review's "no progress") is not built: the result names each step's
  size and limit only after the run.
