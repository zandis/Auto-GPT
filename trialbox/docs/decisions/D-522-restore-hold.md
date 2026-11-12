# D-522 A restore that is not complete holds the box's list jobs until a person releases the hold

- **Task:** NEW-B-3 (the item T-691 left open: D-455, "Open", review M3)
- **PR:** this branch (`agent/NEW-B-3-restore-hold`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-455 (a restore lists the audit events after the backup's snapshot and exits 4), D-493 (a
  restore puts the opt-outs back and says what it could not), D-207 (audited feature flags), D-386 (a list job
  runs only for an open study), T-609 (the note-reading hold: an operator's hold as an audited flag)

## Context

The databases a restore brings back are of the backup's snapshot. What was recorded after it and is unsafe to lose
(opt-outs, erasures of EDC drafts, break-glass, EDC signatures, consent changes) is listed by the restore, audited
(`backup.restore_reapply`) and makes it exit 4, "NOT complete"; so does an opt-out register that could not be read
or put back (D-493). Nothing then kept the box from screening: the services start, the night's ingest runs and the
micro-batch lists a patient whose opt-out is in the list to re-apply. D-455 left the hold open because it had no
place to record an acknowledgement.

## Decision

1. **The hold is an audited flag**, `screening.after_restore` (`tb_common.flags`): `released` (the default) or
   `held`. The flag store already gives what the hold needs: one row in the trial database, a change with an actor
   and a reason, an audit event per change (`flag.set`), a page a person changes it on (`/ops/flags`), and a read
   every service can do without a restart. No new table and no new audit event.
2. **The restore sets it.** `tools.trialbox.backup.restore`, after the restored rows are in, sets the flag to
   `held` when the restore is not complete (`complete` is false: events to re-apply, or opt-outs that are unknown,
   unreadable or not kept). The reason holds counts and times only. The report says `hold: held`; when the flag
   could not be written (no audit directory, a database error) it says `NOT set: <why>` and the command prints
   that the box will screen: keep the services stopped.
3. **The orchestrator reads it.** While it is `held`: the timer and the night's chain start no list job
   (`scheduler._held`: SCREEN, MICROBATCH, COHORT and NAV; audited `scheduler.held`, "held after a restore"), and a
   list scenario a person asks for fails at its first step (`scheduler.require_open`) with a message that says
   why and where to release. The ingest, retention and the monthly calibration run: they list nobody.
4. **A person releases it** on `/ops/flags` with the reason, after the listed events were re-applied. The change
   is audited with the account.
5. **`trialbox doctor` shows it** (`restore hold`: WARN with the restore's reason).

## Consequences

- A box restored on a new machine with no opt-out register (D-493: `unknown`) starts held: somebody has to say
  that the office's records were checked.
- A backup taken while the box was held restores the flag as `held`: the hold stays, also when that restore is
  itself complete. Releasing it is one change.
- A restore done before this card left no hold: nothing is held after the update.

## Not decided here

- **Who may release.** `/ops/flags` is the administrator's page; D-455 names a steward. A release by the steward's
  own account needs a right for this one flag (the console, lane C).
- **A NAV, CASE or FEAS job a person asks for** does not pass `require_open` and is not held; the timer's NAV is.
- The list to re-apply is in the restore's report and in the audit event; the console does not show it as a list
  to tick off.
