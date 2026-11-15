# RUNBOOK §4 part: disk full

**Reader:** the box owner, with hospital IT where the disk is theirs.

*T-635 (OPS-074). Signs: jobs fail with a write error, the database stops, `backup-status` is red, `doctor` warns.
Never free space by deleting from the audit volume, the secrets volume or the database files.*

**Drill (T-213b):** `test_runbook_04_disk_full` (Docker drill: the data disk is filled to 95 % with a junk file; the
checks below find it; the safe steps free space; the audit chain still verifies after).

1. **Where:** `df -h /data /var/lib/docker /` and `docker system df`. Note which disk is full.
2. **WAL archiving stuck?** `python3 -m tools.trialbox backup-status`. With archiving on and the archive failing,
   Postgres keeps every WAL file (§5, point-in-time restore). Fix the archive target first (the share is down or
   full); the WAL files then go by themselves. Never delete WAL files by hand.
3. **Safe to remove:**
   - left-over rollback points of finished updates: `tools/apply_update.sh clean` (§5);
   - old images of earlier releases: `docker image prune` (not `-a` while a rollback point is kept);
   - service logs already collected: `python3 -m tools.trialbox logs prune` (§2);
   - a pre-restore copy in `/opt/trialbox/deploy/pre-restore` once the restore is confirmed good (it is encrypted;
     ask hospital IT);
   - the lake's spill folder `/data/lake/tmp` when no job runs (Jobs page empty).
4. **Not safe:** the audit volume (`audit-data`), the secrets volume, the database volume, the lake snapshots in
   use, `/opt/trialbox/deploy/updates`, `deploy/refdata/loaded`.
5. If the disk is still above 85 %: open a P2 ticket (§21) with `df -h` and `docker system df` (no patient data).
   The cause is growth, and the box needs more disk or a shorter retention (§2).
6. After: `trialbox doctor --env-file deploy/.env`, and run the job that failed again.
