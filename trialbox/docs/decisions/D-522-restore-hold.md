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
2. **The restore sets it as soon as the restored rows are in**, before anything else can stop it and before any
   folder is set aside (`tools.trialbox.backup.restore`; the flag is a row of the restored database, so it is
   written right after the rows were compared with the backup's). A restore that fails or is killed after that
   leaves a held box. The report says `hold: held`; when the flag could not be written (no audit directory, a
   database error) it says `NOT set: <why>` and the command prints that the box will screen: keep the services
   stopped.
3. **The restore takes its own hold off only when it ends complete and nothing was carried.** Carried: a hold
   that stood on the box before the restore (or could not be read), or an earlier restore's set-aside audit chain
   beside the audit folder (`audit.pre-restore-*`: its events may not be re-applied yet, and a second run does not
   see them). Then only a person releases it. `backup.restored` carries `hold` and the count to re-apply.
4. **The orchestrator reads it** from the store each time, and **a hold that cannot be read is a hold**. While it
   is `held`: the timer and the night's chain start no list job (`scheduler._held`: SCREEN, MICROBATCH, COHORT and
   NAV; audited `scheduler.held`, "held after a restore"); a list scenario fails at its first step
   (`scheduler.require_released`: SCREEN, MICROBATCH and COHORT through `require_open`, NAV itself: also a NAV
   that was queued at the backup or that the administrator retries); the timer's weekly sample of "criteria not
   matched" is not drawn. The ingest, retention and the monthly calibration run: they list nobody.
5. **A person releases it** on `/ops/flags` with the reason, after the listed events were re-applied. The change
   is audited with the account.
6. **`trialbox doctor` shows it** (`restore_hold`: WARN).

## Consequences

- A box restored on a new machine with no opt-out register (D-493: `unknown`) starts held: somebody has to say
  that the office's records were checked.
- A backup taken while the box was held restores the flag as `held`: the hold stays, also when that restore is
  itself complete. Releasing it is one change.
- A restore done before this card left no hold: nothing is held after the update.

## Not decided here

- **Who may release.** `/ops/flags` is the administrator's page; D-455 names a steward. A release by the steward's
  own account needs a right for this one flag (the console, lane C).
- **CASE and FEAS** are not held: CASE answers for one patient a person names, FEAS counts. Whether a held box
  should refuse them too is the owner's.
- **The console's own drawing of the not-matched sample** on a page view: `notmatched_sample.weekly` is held
  whoever calls it; any other drawing path of the console is lane C's.
- A restore killed between the restored rows and their comparison with the backup has set no hold yet; no folder
  was set aside then, and its re-run sees what a first run sees.
- The list to re-apply is in the restore's report and in the audit event; the console does not show it as a list
  to tick off.
