# P19: the provenance index equals the audit chain after a downgrade

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** P-19 of the integrator's R1+1 batch D, part H: `provenance_index` FAIL, 108 rows missing against the
  chain, unchanged across update/downgrade
- **Date:** 2026-11-27
- **Base:** int/r1plus1 3390bf74
- **Findings:** [`provenance-index-after-downgrade-p19-2026-11-27/findings.json`](provenance-index-after-downgrade-p19-2026-11-27/findings.json)
  (P19-01 to P19-04)

## Files outside the card

Bodies only, no interface changed (assigned to lane H by the integrator):

- `libs/tb_common/audit_writer.py`: `Drain.open` writes the index rows back after a journal resync;
  `Drain.step` asks again for the index's tables while they are not there; `Drain._catch_up` (new, private)
- `libs/tb_common/provenance_index.py`: `catch_up` (a new function; nothing existing changed)

The card's own: `tests/unit/test_provenance_index_after_downgrade_p19.py`, this page and its findings.

## The writer that skipped them

The audit drain is the index's only writer: it writes a line's rows as it drains the line into the chain. Nothing
else writes them except `trialbox provenance --rebuild`, run by hand. It skipped lines in two ways:

1. **A downgrade or rollback** puts the trial database back from the rollback point's dump, with the provenance
   tables, while the chain keeps every line drained since. The drain sees the journal does not match the chain and
   records `audit.journal_resync`, but it wrote nothing back to the index: those rows stayed missing, and the count
   did not move across later updates and downgrades (P19-01).
2. **Tables made after the drain started** (the role script run on a running box) were not written until the drain
   was started again: `Drain.index` was decided once, at its start (P19-02).

Which of the two made the walk's 108 rows is not known here: the box's log was not read (the resync line, or the
"provenance index not installed" line at the drain's start, would say).

## Change

- At a resync, the drain writes the rows of the chain's lines after the newest line the restored index still holds
  and before the resync's own record: exactly the lines whose rows went back with the tables (the index is written in
  chain order). A line written twice is one row. (Review round: this replaced the first anchor, the journal's
  `max(at)`, see below.)
- A use row is not written back for a patient the chain holds a `console.opt_out` of: the register went back with the
  database, the chain did not.
- A catch-up that fails stays pending; the running drain tries it again a minute later, from where it stopped.
- While the tables are not there, the drain asks again before each batch; from then on it writes the index.
- Lines older than that are never written back by the drain: their rows were written, or were taken out at an opt-out.
  Only `trialbox provenance --rebuild` reads the register that says which. The drain's role cannot read the register.
  So case 2's lines from before the tables existed still need that rebuild (P19-03).
- The anchor is the index's newest line, bounded by the resync. The lead's concern about it (an opt-out that takes
  the index's newest use row makes an older line the newest, and a catch-up from there writes the erased row back) is
  met by the chain's opt-outs: such a patient's use rows are withheld. A use row taken out for another reason (a
  registry refusal, a rebuild that read the register) and newest in the index would still come back: see Review round.

## Case 2 and the update path

Running the rebuild from the update path (its finish step after a switch, a rollback or a downgrade) was looked at
and not done. No role of a compose box can do the whole rebuild: it reads the register and deletes and writes both
tables. `tb_orchestrator` reads the register but may only read the index (and delete use rows).
`tb_audit_writer` writes the index but may not delete or read the register. The admin role `trialbox` may do all of
it, but the update reaches it only through `psql` in the `db` container, and the rebuild is Python. So the doctor's
remedy, `trialbox provenance --rebuild`, has no documented place to run on a compose box either (P19-03). The manual
form today is the rebuild run where the admin's database address and the chain are both reachable, with the
services' Python. Not tested here.

## A downgrade and the opt-out register (P19-04, reported to the lead)

An update's rollback (`restore_databases`, and `update rollback <bundle>` after a killed update) puts the whole trial
database back from the rollback point's dump, the opt-out register with it. An opt-out recorded after the dump, and
the erasures that followed it, are then gone. A backup restore lists such events, audits them
(`backup.restore_reapply`) and holds the list jobs until a person releases them (D-493, D-522). The update's rollback
does neither. Read from the code, not shown by a test; not fixed here.

## Test

`tests/unit/test_provenance_index_after_downgrade_p19.py`, a real drain and the real index on the test cluster:

- a night, an update (the rollback point's `pg_dump`) and a second night, then a downgrade (`pg_restore` of the dump)
  and the drain started again: `check()` is equal after each step (fails on the base: the second night's two rows
  missing);
- tables made after the drain started: the next line is indexed without a restart (fails on the base);
- an opt-out that takes the index's newest use row: a restart writes nothing back (passes on both, kept as a guard).

## Review round (P19-R1 to R5, F1 to F5)

| Finding | Fix | Test (failed on the first change) |
| --- | --- | --- |
| R1 / F1 High: an opt-out after the dump, its use row re-made | the chain's `console.opt_out` pseudonyms are withheld | `test_an_opt_out_recorded_after_the_dump_stays_out_after_the_downgrade` |
| R2 / F2: a backlog at the dump, a row journaled before the drain starts | anchor = the index's newest line, not the journal's `max(at)` | `test_a_row_journaled_before_the_dump_and_drained_after_it_is_written_back` |
| R3 / F2: an empty journal at the dump | no line held: every line before the resync | `test_a_dump_taken_before_the_first_journal_row_is_caught_up` |
| R4 / F3: a failure part way is never retried | pending, retried by `step` after `Drain.RETRY` s | `test_a_catch_up_that_fails_part_way_is_tried_again_and_writes_each_row_once` |
| R5: a line with an unreadable journal time is skipped | no time is read | `test_a_line_whose_journal_time_cannot_be_read_is_not_passed_over` |
| F4: the catch-up runs at every start | not changed: `open` returns before it unless the cursor's journal row is gone or moved; guarded by the older opt-out test (a restart on the same database writes nothing back) | - |
| F5: "not installed" at every batch | said at the start only | `test_index_not_installed_is_said_once_not_at_every_batch` |

Left open: the pending retry lives in the running drain; a drain stopped after a failed catch-up and after it drained
a new row does not try again (the doctor's check names the gap). A registry refusal copied by the opt-out worker is not
named in the chain (its audit event holds counts only), so a lost line of such a patient is written back; the use rows
of the register's patients are taken out by the worker's clear, which is still owed (D-989, lane D). A lift after an
opt-out is not read: that patient's rows stay out until a rebuild.

## What was not verified

- The walk's box: its 108 rows were not read, so which case made them is not shown.
- P19-04: no rollback with an opt-out recorded after its dump was run.
- A compose box's real update and downgrade (`tools/trialbox/update.py`): the test restores the database the way
  the rollback does (`pg_restore` of a dump), not through the update tool.
