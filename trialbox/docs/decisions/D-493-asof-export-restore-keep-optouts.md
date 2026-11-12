# D-493 An as-of export and a restore keep the opt-outs: the tombstone stays, the restore says what it lost

- **Task:** T-728 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.3, wave G; privacy)
- **PR:** this branch (`agent/T-728-asof-restore-optouts`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** F-9, F-8 (the report and the audit; the re-entry stays a person's), F-11 of
  `docs/reviews/2026-11-12-architecture/lifecycle.md` (proposal G-7)
- **Builds on:** D-441 (the opt-out worker, `tb_withheld`, the tombstone with the reason `opted out`), D-384 (the
  export as of a time), D-274 and D-455 (the restore: the kept copy, `backup.restore_reapply`), D-465 (the erasure
  registry: the register is kept), D-147 (the register's events never name who in the audit)
- **Read by:** T-627 (an as-of SCREEN; it must not ship before the export half), T-206b

## Context

Two ways back into the data for a patient who has opted out:

- **The export as of a time** (`omop.export.export_rows(as_of=...)`) winds every record changed after that time back
  to its before-image. An opt-out is such a change (a tombstone with the before-image kept), so an export as of a day
  before the opt-out held the patient in full (F-9). No production caller yet; T-627 will be one.
- **A restore** replaces the trial database, and with it the opt-out register, by the backup's. Opt-outs typed by
  the office or the steward after the backup are gone, nothing says so, and they cannot be replayed from the audit
  (its events hold counts, never who). The patient is back on lists the next morning (F-8). And the jobs that were
  running when the backup was taken are in the restored database as running: the orchestrator's restart recovery
  runs them again, on data and requests of that day, and a job that had finished and mailed after the backup mails
  again (F-11).

## Decision

1. **An as-of export never brings a withheld patient back.** After the wind-back, inside the same transaction that
   is always rolled back, every record of every patient in `tb_withheld` (the patients opted out now) is tombstoned
   again by the same code the opt-out worker uses (`omop.load.withhold_persons`), whatever the order of the later
   events was (an update after the as-of time and then the opt-out, or the opt-out alone). The consent statements
   stay, as in a live store (`KEEP_WITHHELD`): the refusal itself must reach the lake. An opt-out that was lifted
   since is not withheld now, so the patient's records of that time are exported: the as-of export follows the
   register of today for refusals, which is the fail-closed reading.
2. **A restore counts the opt-outs it is about to lose, before it empties the database.** It reads the live
   register (`optout.optout_events`) for events after the backup's snapshot of the trial database and reports
   `optouts_after_backup`: how many events, how many by action, the opt-outs by source, how many were the
   registry's own (they come back at the worker's next tick) and how many a person typed (they must be entered
   again), the first and the last time. Never a pseudonym, a note or who typed it. The count is printed by `trialbox restore` with the instruction "enter them
   again", is in the `backup.restored` audit event, and makes the restore `complete: false`. A register that cannot
   be read is reported as such, not as zero.
3. **A restore fails the jobs that were running at the backup.** After the databases are restored and their rows
   checked against the manifest, every job in `orch.jobs` that the restart recovery would run again (not queued, not
   finished, not waiting for an approval) is set to `failed` with the step it was in and the message "interrupted by
   a restore". The orchestrator then finds nothing to re-queue. The requester is not mailed by the restore tool (no
   service is up); the jobs are listed in the restore's output and counted in the audit event (`jobs_failed`), and
   the console shows them failed with the message. Jobs that were queued and had not started stay queued: they have
   done nothing yet.

## Consequences

- T-627 can build on the export: an as-of lake holds no row of a patient who is opted out today, but the consent row.
- A restore over a box with later opt-outs ends "NOT complete" and says how many must be entered again. Refusals
  that came from the registry come back by themselves at the worker's next tick; `typed` says how many a person
  entered.
- The kept copy of the box before the restore (D-274) still holds the later register, encrypted to the hospital's
  key: that is where the names are, if the office has no other record.

## Not decided here

- Replaying the later opt-outs from the kept copy automatically (it needs the hospital's private key on the box).
- What a job queued before the backup and finished after it does when it runs again (its mail may go twice).
