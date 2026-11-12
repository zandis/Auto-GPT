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
   is always rolled back, every record of every patient in `tb_withheld` or in the opt-out register (the worker's copy lags the register by a tick) is tombstoned
   again by the same code the opt-out worker uses (`omop.load.withhold_persons`), whatever the order of the later
   events was (an update after the as-of time and then the opt-out, or the opt-out alone). The consent statements
   stay, as in a live store (`KEEP_WITHHELD`): the refusal itself must reach the lake. An opt-out that was lifted
   since is not withheld now, so the patient's records of that time are exported: the as-of export follows the
   register of today for refusals, which is the fail-closed reading.
2. **A restore keeps the opt-outs recorded after the backup** (changed by the review of 2026-11-12; before it the
   restore only counted them). It reads the live register (`optout.optout_events`) before anything is replaced.
   After the databases are restored and their rows checked against the manifest, every event the live register
   held that the restored one does not is an event after the backup (compared row by row, so no clock is
   compared and an opt-out that committed while the snapshot was being taken is found too). Every **opt-out**
   among them is written into the restored register as it was (pseudonym, source, note, who, when), in one
   transaction; run again, the restore finds them there and adds nothing. This needs no key: the rows go from the
   live database to the restored one inside the restore's own process and are never printed, written to disk or
   audited. A **lift** is not replayed: the patient stays withheld until a person lifts the opt-out again (the
   restore fails closed). The restore reports `optouts_after_backup` in counts only (events, by action, the
   opt-outs by source, the registry's own and the typed ones, the first and the last time, `kept`, `not_kept`,
   `lifts_reverted`, `state`), prints them, writes them into `backup.restored` and into `backup.restore_failed`,
   and is `complete` only when every later opt-out was kept and no typed lift was reverted.
   - **A box with no register to read** (a new machine, a box that never had one, a move to another site's
     hardware) says `state: unknown`: what the old box recorded after the backup is not known here, the restore is
     not complete, and the office's records since the snapshot are checked. Never "none".
   - A register that cannot be read is `unreadable`, not zero, and the restore is not complete.
   - A backup that holds no trial database does not replace the register: `not_replaced`, nothing is lost.
   - `--no-copy` is refused while the register holds events a person typed after the backup, or cannot be read:
     the kept copy would be the only other record of them.
   - If the restore stops after the trial database was replaced, it still puts the opt-outs back before it
     reports the failure, so a second run does not start from a register that has already lost them.
   - The audit chain the box wrote after the backup's copy of it is in the folder set aside
     (`audit-data.pre-restore-*`); its events are listed for re-applying too (a gap of D-455). The register's own
     events are left out of that list once every later opt-out was kept.
3. **A restore fails the jobs that were running at the backup.** After the databases are restored and their rows
   checked against the manifest, every job in `orch.jobs` that the restart recovery would run again (not queued, not
   finished, not waiting for an approval) is set to `failed` with the step it was in and the message "interrupted by
   a restore". The orchestrator then finds nothing to re-queue. The requester is not mailed by the restore tool (no
   service is up); the jobs are listed in the restore's output and counted in the audit event (`jobs_failed`), and
   the console shows them failed with the message. Jobs that were queued and had not started stay queued: they have
   done nothing yet.

## Consequences

- T-627 can build on the export: an as-of lake holds no row of a patient who is opted out today, but the consent row.
- A restore over a box with later opt-outs keeps them and says how many. It ends "NOT complete" only for what
  needs a person: a typed lift that was reverted, a box with no register to read, an opt-out that could not be put
  back.
- The kept copy of the box before the restore (D-274) still holds the later register, encrypted to the hospital's
  key: that is where the names are, if the office has no other record.

## Not decided here

- Replaying the later opt-outs from the kept copy onto **another** machine (that copy is encrypted to the
  hospital's key; on the same box no key is needed, see point 2).
- Replaying lifts.
- What a job queued before the backup and finished after it does when it runs again (its mail may go twice).
