# D-416 Day 2 on the platform: backup, restore, logs, audit archive, digest updates, block storage

- **Task:** T-633 (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-633-platform-day2`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-126 (the encrypted backup, the hospital's key), D-138 (log retention, the audit archive), D-187
  (layout 2, one snapshot per database), D-211 (the platform form), D-274 (a restore keeps the box first), D-315 (the
  site's zone), D-409 (the pair on two MIG instances, the model key), D-311 (no development gates)
- **Closes:** OPS-050 (the day-2 half), OPS-068, OPS-069 (block storage, where data lives; the drill half is T-319),
  OPS-066 (the questionnaire; the answer is CGMH's), OPS-070 (requests and limits, the first-call question; the
  night measurement is T-319)

## Context

The platform form (D-211, D-409) installs and checks itself, but had no day 2: no backup job, no restore, no log
collection, no audit archive, no update or rollback. The appliance does those with host cron and `docker compose
exec`, which do not exist in a namespace. The database's claim was on the shared ReadWriteMany class (a network file
system), the platform kind at CGMH is unknown (Kubernetes, Docker or a batch scheduler), and nobody is named for root
or for the first call at night.

## Decision

1. **CronJobs in the base** (`deploy/platform/base/day2.yaml`): `trialbox-backup` (nightly), `trialbox-logs` (daily),
   `trialbox-restore` (suspended: run only as `kubectl create job --from=cronjob/trialbox-restore`). The site overlay
   sets `spec.timeZone` to `site.tz`; `doctor --platform` checks it.
2. **The same backup file.** The job writes the appliance's `.tbbak` (layout 2) under the appliance's directory names,
   so a platform backup restores on an appliance and the other way round (the interim cloud's move). The Python image
   has no PostgreSQL client (D-23): an init container writes `backup_schedule.snapshot_script` for each database
   naming the connection's variable, never its value; a second init container in the database image runs it with
   `psql` (one REPEATABLE READ snapshot: dump, row counts and hashes, the hospital's own reference rows); the main
   container packs and encrypts it with every data claim, mounted read-only. The files go to the claim
   `backup-share` (the hospital's share; encrypted to the hospital's key, so the share needs no encryption of its own
   and is not held to the encrypted class). `TB_HAPI_DB_URL` in the Secret `trialbox-db` puts the FHIR store in it.
3. **Restore through a spool.** `backup.restore` runs unchanged in the Python container with `TB_PG_DUMP_CMD` and
   `TB_PG_RESTORE_CMD` set to `platform-day2 pg`, which hands each call to `pg-spool.sh` in the database image beside
   it through a shared folder: the tool (only `psql`, `pg_dump`, `pg_restore`), its arguments with the connection
   as `@TB_DB_URL` or `@TB_HAPI_DB_URL` (a connection string is never written to disk; any other is refused), and
   standard input; output, errors and exit code come back. A plain container that stops at a `STOP` file, so the Job
   completes on any Kubernetes version (no native sidecar needed). The claims are mount points, which cannot be
   renamed aside: the backup is restored into `<claim>/.tb-restore-<time>` and moved up once the databases are
   restored and their rows checked; a box that holds data is kept first as an encrypted backup (D-274), after which
   its old files are removed. The private key is a Secret only during the restore; `backup_job` fails in VALIDATION
   and PRODUCTION while it is there (D-126).
4. **Logs and the audit archive.** The log job's service account lists pods and reads their logs, nothing else; its
   egress is the declared API server only (`trialbox-egress-ops`, rendered by `platform-egress`, checked by
   `network_policy`). It writes the site's day of every pod with `COVERAGE.json` (a log gap when a pod ran before the
   day began but its oldest kept line is later), prunes after `retention.logs_days`, and archives the audit chain
   with `logs.archive_audit` into the claim `logs-data`.
5. **Digest updates.** `platform-day2 update-overlay` writes `next` (the applied overlay plus an `images` entry per
   changed digest and the new `release.json` as `trialbox-release`) and `previous` (the applied overlay, untouched:
   the rollback); `deploy/platform/overlays/update` is the shape. The backup job runs first. A new image name or
   repository, or an image that would lose its digest, is refused: that is a new release's manifests.
6. **Block storage for the database.** The claim template `db-pg` stays ReadWriteOnce and goes on
   `TB_PLATFORM_DB_STORAGE_CLASS`, a block class that is not the shared one, evidenced by
   `TB_PLATFORM_DB_STORAGE_EVIDENCE`. `storage_encryption` holds the database's claims to that class.
7. **Doctor checks.** `backup_job` (a FAIL in every environment when there is none), `log_job`, `db_storage`,
   `pod_limits` (every container states requests and a memory limit: MIG isolates only the GPU). The doctor's Role
   reads CronJobs.
8. **Questions to the site.** Survey 51a (which platform), 51b (who is root and administers the storage, who
   restarts the pods at night), 51c (which storage: block for the database, shared for the rest, the backup share,
   pod log retention). RUNBOOK §26 has the jobs, the table of where patient data lives and who can read it, the
   restore, the update and rollback, and the kind drill.

## Consequences

- A site adds the ConfigMap `trialbox-backup-pub`, the share's claim binding, the block class and the CronJobs' zone.
- The backup reads the claims' files while the services run (the database is one snapshot); the appliance's pause of
  the writers has no equivalent a job may do in a namespace it does not administer.
- On a platform with several nodes, the ReadWriteOnce claims the backup mounts keep TrialBox's pods on one node.
- Not done here: the kind run itself (no Docker or kind on the build machine: `deploy/platform/kind-day2.sh` is the
  run, listed as remaining in the PR); the noisy-neighbour measurement and the isolation drills (T-319); the KEK
  unseal (T-210), until which the shared host holds synthetic data only.
