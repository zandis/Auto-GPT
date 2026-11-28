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

Superseded twice (see "Design round" and "Round 3"): the drain now writes every missing row at every start, so
P19-03 below is closed; the update's rollback keeps the register (P19-04 closed). The first round's change, kept for
the record; the design round below replaces the anchor, the chain's opt-outs and
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

Superseded: the drain's catch-up writes case 2's lines at every start through the register's trigger (no role needs
the whole rebuild), and the rebuild runs in one transaction. Kept for the record:

Running the rebuild from the update path (its finish step after a switch, a rollback or a downgrade) was looked at
and not done. No role of a compose box can do the whole rebuild: it reads the register and deletes and writes both
tables. `tb_orchestrator` reads the register but may only read the index (and delete use rows).
`tb_audit_writer` writes the index but may not delete or read the register. The admin role `trialbox` may do all of
it, but the update reaches it only through `psql` in the `db` container, and the rebuild is Python. So the doctor's
remedy, `trialbox provenance --rebuild`, has no documented place to run on a compose box either (P19-03). The manual
form today is the rebuild run where the admin's database address and the chain are both reachable, with the
services' Python. Not tested here.

## A downgrade and the opt-out register (P19-04, reported to the lead)

*Partly fixed in round 4 (below): the register is copied whole and the index emptied; the list hold is owed.*

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

**Owed outside this card** (the design's requirements on other lanes; round 3 below did the first three):

- the console's opt-out transaction: lock 211989, the register's row, `erase`, the journal row, one commit; its
  lift handler keeps the register's event (it does today: a lift is its own event);
- the update tool's rollback and `restore_databases`: export the live register before the restore and apply it
  again before any service starts, and remove the export once the marker reads `clean`;
- the console's and the CLI's searches pass the audit directory; the doctor prints the marker.

## What was not verified

*Round 4 changes this list: see its own.*

- The walk's box: its 108 rows were not read, so which case made them is not shown.
- P19-04: no rollback with an opt-out recorded after its dump was run.
- A compose box's real update and downgrade (`tools/trialbox/update.py`): the test restores the database the way
  the rollback does (`pg_restore` of a dump), not through the update tool.

## Round 3 (reviews 1584 codex P19-D1/D2, X1 to X8, N2; opus F1 to F7)

*Superseded by round 4: the catch-up, the sweeps and the register's lock are gone.*

- **The update's rollback keeps the register** (P19-04, D1, D2, F1): `update.RESTORE_SH`, between the dump's load into
  the fresh database and the swap, copies each register event of the database in place that the restored one lacks
  (pseudonym, action, who, when; a lift too), then runs `provenance.sweep()` there. A row the dump brought back for a
  patient who said no after it is gone before any service sees the database; the drain's catch-up then withholds the
  lines it writes back. The database in place is untouched until the swap, so a rollback run again reads it again.
  Tests run `RESTORE_SH` itself on the test cluster (no live register kept by the test).
- **One lock for every consent writer** (X2, F3): `OptOutRegister._add` (the console's opt-out and lift, the registry
  worker's copy) takes `pg_advisory_xact_lock(211989)` first and, for an opt-out, runs the sweep in its own
  transaction. `tbs_optout` gets USAGE on `provenance` and EXECUTE on `sweep`.
- **The searches are held** (X1): the console's page and `trialbox provenance --search` pass the audit directory;
  refused while the marker is not `clean` (the page says the index cannot be read, the CLI exits 1). A full
  `--rebuild` writes `clean` (P19-DESIGN §2).
- **The drain**: the sweep runs before the catch-up and each is committed before the marker says `clean` (F2, X5); a
  failed sweep after an opt-out is owed and retried (X3); a live failure keeps an owed retry's time (X7).
- **The index**: `installed()` asks for the trigger on `model_uses`, running `provenance.withhold`, enabled (X4, F5);
  the catch-up compares rows, so a half-written line is completed (N2); `add` counts the rows written (F6);
  `rebuild` is one transaction (X8).
- **Grants** (X6): `provenance.withheld` is executable by `trialbox` alone (the earlier grants are revoked).

## Round 4: detect and refuse (P19-DESIGN-3; reviews 1584 codex Y1 to Y10, D7; opus G1 to G8)

The integrator's ruling: the index is no longer repaired in place. Four writers (the drain's catch-up and sweep, the
console's sweep, the restore's sweep) are replaced by one marker and one rebuild.

- **The marker** (`<audit dir>/PROVENANCE_STATE`, version 2): `provenance_index.require_rebuild` is its one setter,
  called by the update tool's rollback after `stop` and before any image or database goes back
  (`update.mark_rebuild_required`; a marker that cannot be written stops the rollback there), by the backup restore
  once the audit folder is back, and by the drain on a journal resync or a failed index write. Clean is derived:
  readable, version 2 and `verified`; anything else (no file, unreadable, bad JSON, version 1) requires the rebuild,
  the reason named. Written through `mkstemp`, mode 0644, fsync, rename.
- **Refused while required**: `provenance_index.search` (the console's page: its 503; `trialbox provenance --search`:
  exit 1), the drain's index writes (the chain line is written), the doctor and `--check` (FAIL with the text
  `the provenance index must be rebuilt (<reason>, since <time>); provenance search and index writes are refused until
  then: run trialbox provenance --rebuild`, before any database work). The register, screening and every other page
  are untouched.
- **The rebuild** (`provenance_index.rebuild`, `trialbox provenance --rebuild`, `python -m tb_common.provenance_index
  rebuild`): refuses by name (not autocommit, not installed, a second register schema, a keeper that cannot read the
  register, a drain that does not yield); holds the writer's lock 211990 from its first chain read to its verified
  marker (the drain's batch takes it with `pg_try_advisory_lock`, so no line is appended meanwhile); one transaction
  per day file with `done_through` after each, so a kill is resumed by the next run; only a rebuild from empty
  deletes the tables first. Every row goes through the register's trigger, so an opt-out made at any moment wins.
- **The restore** (`update.RESTORE_SH`): the live register replaces the restored one whole, ids and order kept, the
  sequence moved on (Y2); a partitioned register is found (Y6); an empty live register is skipped (Y7); the index is
  emptied before the swap whatever release made the dump (Y1, G1); the last line says how many register events were
  kept, and `update.rolled_back` carries it with `provenance_index: emptied; rebuild required` (G2's audit half).
- **Never coupled** (G3): `OptOutRegister` takes no lock and runs no sweep; the role script grants the keeper's read
  for tables its login roles make (`ALTER DEFAULT PRIVILEGES FOR ROLE tbs_optout, tb_console, tb_orchestrator`).
- **The drain** requires an autocommit connection (Y8).

Deviations from the design: the design's `GRANT DELETE ... TO tb_audit_writer` (the rebuild's role) is not made,
because D-997's tests hold that the drain cannot take a row back; so `deploy/install.sh` does not run the rebuild
(no role there can) and an upgraded box's doctor fails `provenance_index` until the administrator runs
`trialbox provenance --rebuild` (P19-03 stays open). A new box has nothing to rebuild: at its start the drain writes the
verified marker when there is no marker file, the index is installed and empty and no chain line makes a row
(`provenance_index.mark_new_box`, under the writer's lock, only where no marker is), so a fresh install's doctor passes. The demo box (`DemoBox`) writes no marker: its rollback restores
no database and its container is recreated from the image. P19-03 and P19-04 are `open` with a `remaining` note
(the register has no partial state).

What was not verified in round 4: a compose box's real rollback (the tests run `RESTORE_SH` itself on the test
cluster); the rebuild's time at a site's size (no site figure was declared, so nothing was measured: the test that
skipped without one was dropped in the fix round, review B2).

Fix round (reviews of PR 1584):
- B1: on a box's host `trialbox provenance --rebuild` runs in a one-off `audit-writer` container (`compose run`,
  the admin's `TB_DB_URL` in the environment), the one service that writes the audit folder; RUNBOOK §5 names it.
- The host check's doctor runs in an image without the audit volume: `provenance_index` says WARN "not checked here".
- P19-1: the rollback streams the live register into the restored database (no file); the count read first is
  checked there, so a stream cut short refuses before the swap.
- P19-2: when the live register differs from the dump's, the rollback sets `screening.after_restore` (held, with its
  flag event) in the restored database before the swap; `update.rolled_back` carries `screening_hold`.
- P19-3: a dump without `provenance.withhold` (the release before P-19) loses its services' grants on the index in
  the restored database; the next update's role script grants them again.
- P19-4: a resumed rebuild reads its recorded day file again. P19-5: the drain's start writes the rows of the
  newest chain line that has rows (a stop between a line and its rows). P19-6: the batch's lock is released as taken;
  a marker that cannot be written takes the verified marker away. P19-7: a search reads the marker again after its
  query and refuses when it changed. P19-8: a failed probe before a batch requires the rebuild.
- Left as limitations (detect and refuse): P19-9 (a rollback point older than the register refuses before the swap,
  the services stay stopped); P19-6 when the audit folder takes no write at all (the verified marker cannot be
  removed either); P19-3 holds until someone runs the old release's role script by hand.
