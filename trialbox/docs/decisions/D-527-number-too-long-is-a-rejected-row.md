# D-527 A number the mapping cannot compute is a rejected row, not the end of the night

- **Task:** NEW-B-6 (a finding sent to the night and capacity lane on 2026-11-12, confirmed by running)
- **PR:** this branch (`agent/NEW-B-6-number-too-long-is-a-rejected-row`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** STD-025 (T-615a: a row the mapping cannot read is rejected and counted by reason; the table goes
  on), D-520 (the key a rejected row is counted under holds no feed value), D-271 (a held night)

## Context

The night maps a table row by row and catches `ValueError` (the mapper's `MappingError` is one): the row is
rejected, counted under a value-free key, and the table goes on (`adapter/pipeline.py`). A lab value of thirty
digits is a number `Decimal` reads; the mapper's arithmetic on it (`value % 1`, at the default precision of 28
digits) raises `decimal.InvalidOperation`. That is an `ArithmeticError`, not a `ValueError`: the night ended
("ingest failed") on one row of one table. Run on train 4: 150 good creatinine rows and one of thirty digits, each
with its unit (`mg/dL`): no snapshot.

## Decision

1. **The night rejects a row on `ArithmeticError` as it does on `ValueError`.** `InvalidOperation`, `OverflowError`
   and `ZeroDivisionError` are all "a number the mapper cannot compute with": the row is counted, the table goes
   on, and the hold rule is unchanged (`REJECT_MAX_PCT`: a table with more than that share of rejected rows holds
   the night).
2. **Its key is the type and one fixed sentence**: `InvalidOperation: a number the mapping cannot compute`.
   `decimal` puts a list of signal classes in the message, not a sentence, and `reject_key`'s cut at the first quote
   mark left `[<class <value>`.
3. **Nothing else is caught.** A `TypeError` or a `KeyError` in the mapper is a fault of the mapping, not of a
   row, and still ends the night loudly.

4. **A fault of the mapping is not a row's.** The mapper parses a look-up row's `factor` per source row; with
   point 1 a factor typed wrongly would reject every row of its code each night, under a key that blames the feed,
   and never hold the night while that code is under the hold share. `adapter.pipeline.check_lookup_factors` reads
   every factor of every look-up before the first row and ends the load with the look-up and its row named.
5. **The first load (`adapter/backfill.py`) follows**: the same catch, the same check.

## Consequences

- On a **delta** night a rejected row leaves the record of the night before in the snapshot (it is not replaced
  and not removed), as for any rejected row since STD-025. Before this decision the night ended and nothing was
  published. The row is counted in `completeness.json` and in the log every night until the feed is corrected.

- One more key can appear under `rejected` in `completeness.json`, in the night's error, the audit and the log. It
  holds no feed value.
- The mapper is unchanged (`services/adapter/mapping` is another lane's). Whether such a value should be kept as
  text instead (as "NaN" is, D-215) is that lane's to decide; until then the row is rejected and counted, which is
  what the box does with any row it cannot read.

## Not decided here

- A thirty-digit value **without** a unit is kept today with no value and the reason "implausible without a unit"
  (D-590); with a unit it is rejected. Making the two agree is the mapping lane's.
