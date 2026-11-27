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

Assigned to lane H by the integrator. The first rounds changed bodies only; the design round (below) changes
interfaces:

- `libs/tb_common/audit_writer.py`: `Drain.open` owes a repair at every start and runs it; `Drain.step` asks again
  for the index's tables while they are not there and sweeps after a batch with an opt-out; `Drain._catch_up`,
  `Drain._sweep` (private)
- `libs/tb_common/provenance_index.py`: `INDEX_SQL` gains the register's functions and trigger; `add`, `rebuild` and
  `check` lose their `erased` argument; `catch_up`, `sweep`, `read_state`, `write_state`, `ProvenanceUnderRepair`
  are new; `search` takes `directory`; `installed` also asks for the trigger
- the callers of `erased`: `tools/trialbox/doctor.py`, `tools/trialbox/provenance.py` (its `_erased` goes)
- lane D: both role scripts carry the new `INDEX_SQL` word for word and give its functions to `provenance_keeper`
- `tests/unit/test_provenance_index.py`: its database has the register; the opt-out case asks it

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

The first round's change, kept for the record; the design round below replaces the anchor, the chain's opt-outs and
the retry that lived in the running drain.

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
| F4: the catch-up runs at every start | not changed in that round; the cited guard could not fail (review N4: the older opt-out test never made a resync, so the open-gate was untested). The design round makes it run at every start, on purpose and tested | `test_a_restore_with_a_matching_cursor_still_repairs` (design round) |
| F5: "not installed" at every batch | said at the start only | `test_index_not_installed_is_said_once_not_at_every_batch` |

Left open in that round (each closed by the design round below): the retry lived in the running drain; a registry
refusal was not named in the chain, so its lost line was written back; a lift after an opt-out was not read.

## Design round (P19-DESIGN; reviews 1584 D1 to D7, N1 to N5)

The root cause of the review's findings: the first rounds decided what to withhold from the chain's
`console.opt_out` lines, and when to repair from a flag set in memory at a journal resync. Both were the wrong
authority.

- **The register is the one authority, asked inside the database on every insert.** `provenance.withheld(pid, at)`
  reads `optout.optout_events`; a `BEFORE INSERT` trigger on `model_uses` (`model_uses_withhold`) skips a row it
  withholds, whoever inserts it; `provenance.sweep()` deletes the ones already there (what `pg_restore` put back,
  whose data loads before the trigger exists). `check` asks the same function, so the doctor and the writer agree.
  The functions belong to `provenance_keeper` (NOLOGIN, no member), the one role that reads the register here.
- **The rule for a lift:** a row of time `at` is withheld while the opt-out is in force, and when `at` is not after
  the latest lift. Earlier rows stay erased; a back-dated row falls on the withheld side.
- **The repair obligation is a file,** `<audit dir>/PROVENANCE_STATE` (`clean`, `repair-required`, `repairing`),
  in the one store a restore does not put back. Every start of the drain owes a repair; only a catch-up and a sweep
  that both finished write `clean`. A missing file is owed. `search(..., directory=)` refuses while it is not clean.
- **The repair is a set difference:** every row-bearing chain line whose hash the index does not hold, in chain
  order, each line in one transaction (so a hash in the index means the whole line).
- **The race (N1):** the trigger and the sweep take the advisory lock 211989; the console's opt-out transaction is
  to take it too (below). Until then the drain sweeps after any batch that drained a `console.opt_out`.

| Finding | Test |
| --- | --- |
| D1: a registry refusal (counts only in the chain) | `test_a_registry_refusal_in_the_register_is_withheld_at_catch_up` |
| D2: a use row in the dump, its patient out after it | `test_a_use_row_in_the_dump_is_swept_after_the_restore` |
| D3: a restored journal that matches the chain's cursor | `test_a_restore_with_a_matching_cursor_still_repairs` |
| D4: a fresh drain after a failed repair and a batch | `test_a_fresh_drain_after_a_partial_failure_and_a_batch_finishes_the_repair` |
| D5: a failed probe at the start | `test_a_failed_probe_at_the_resync_keeps_the_repair_owed` |
| D6: a lift | `test_a_lift_releases_only_rows_after_it` |
| D7: the naive journal time, in a record whose hash is valid | `test_catch_up_writes_a_line_with_a_naive_journal_time` |
| N1: an opt-out between the restore and the drain's start | `test_an_opt_out_between_the_restore_and_the_drains_start_is_withheld` |
| N2: a line with two calls, half written | `test_a_line_with_two_calls_is_written_whole_or_not_at_all` |
| N3: a failed repair on a connection that is not autocommit | `test_a_failed_catch_up_leaves_the_connection_usable` |
| a kill -9 in the middle of the repair | `test_kill_9_mid_catch_up_is_finished_by_the_next_drain` |
| the search while a repair is owed | `test_search_refuses_while_the_repair_is_owed` |
| the doctor's check and the writer | `test_the_doctor_check_agrees_with_the_writer` |
| tables without the trigger (an old role script) | `test_an_old_role_script_writes_no_unfiltered_index` |

N4 is the F4 row above. N5: P19-01 and P19-02 are marked fixed in the findings.

The tests' downgrade puts back the dump and then applies the live register's rows again before any service starts,
as the design asks of the update tool (below).

**Owed outside this card** (the design's requirements on other lanes; not done here):

- the console's opt-out transaction: lock 211989, the register's row, `erase`, the journal row, one commit; its
  lift handler keeps the register's event (it does today: a lift is its own event);
- the update tool's rollback and `restore_databases`: export the live register before the restore and apply it
  again before any service starts, and remove the export once the marker reads `clean`;
- the console's and the CLI's searches pass the audit directory; the doctor prints the marker.

## What was not verified

- The walk's box: its 108 rows were not read, so which case made them is not shown.
- P19-04: no rollback with an opt-out recorded after its dump was run.
- A compose box's real update and downgrade (`tools/trialbox/update.py`): the test restores the database the way
  the rollback does (`pg_restore` of a dump), not through the update tool.
