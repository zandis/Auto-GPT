# P19: the provenance index equals the audit chain after a downgrade

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** P-19 of the integrator's R1+1 batch D, part H: `provenance_index` FAIL, 108 rows missing against the
  chain, unchanged across update/downgrade
- **Date:** 2026-11-27
- **Base:** int/r1plus1 3390bf74
- **Findings:** [`provenance-index-after-downgrade-p19-2026-11-27/findings.json`](provenance-index-after-downgrade-p19-2026-11-27/findings.json)
  (P19-01 to P19-03)

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

- At a resync, the drain writes the rows of the chain's lines that came from journal rows newer than the newest one
  the database still holds: exactly the lines whose rows went back with the tables. A line written twice is one row.
- While the tables are not there, the drain asks again before each batch; from then on it writes the index.
- Lines older than that are never written back by the drain: their rows were written, or were taken out at an opt-out.
  Only `trialbox provenance --rebuild` reads the register that says which. The drain's role cannot read the register.
  So case 2's lines from before the tables existed still need that rebuild (P19-03).

## Test

`tests/unit/test_provenance_index_after_downgrade_p19.py`, a real drain and the real index on the test cluster:

- a night, an update (the rollback point's `pg_dump`) and a second night, then a downgrade (`pg_restore` of the dump)
  and the drain started again: `check()` is equal after each step (fails on the base: the second night's two rows
  missing);
- tables made after the drain started: the next line is indexed without a restart (fails on the base);
- an opt-out that takes the index's newest use row: a restart writes nothing back (passes on both, kept as a guard).

## What was not verified

- The walk's box: its 108 rows were not read, so which case made them is not shown.
- A compose box's real update and downgrade (`tools/trialbox/update.py`): the test restores the database the way
  the rollback does (`pg_restore` of a dump), not through the update tool.
