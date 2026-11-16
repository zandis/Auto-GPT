# D-846 A table of vitals written one item per row is paired by patient and exact time

- **Task:** CGRD-A8, the inpatient half (from the first look at a real source; facts kept off the repository)
- **PR:** this branch (`agent/CGRD-A8-long-vitals-paired-by-time`)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-806 (a table read whole on a delta night), D-580 (counted, never guessed)

## Decision

1. **`tables.<t>.pivot: {keys, item, value, columns}`** turns the rows of one patient at one exact time into one row,
   each listed item code in its canonical column (`height_cm`, `weight_kg`, `sbp`, `dbp`); the base mapping's vital
   observations read it as a wide table. Grouped on disk (a scratch SQLite table, gone when the pivot ends).
2. **Never crossed, never guessed**: pairing uses the exact time. Two different values of one item at one time leave
   it empty (`values_that_disagree`); an unlisted item code and a row without its keys are counted.
3. **An unpaired pressure is an observation of its own** (systolic 8480-6 or diastolic 8462-4), never a panel with one
   half: the base mapping gains the two resources.
4. **A pivoted table is read whole on a delta night**: a pair split across nights would otherwise be read as halves.
   `mapping_check` asks the source for the keys, item and value, and pivots what it reads. Counts go to the night's
   completeness (`pivot`). The goldens move by `mapping_version` and hashes only.
