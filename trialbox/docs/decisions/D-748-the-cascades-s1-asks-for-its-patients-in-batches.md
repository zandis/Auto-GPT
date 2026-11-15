# D-748 The cascade's S1 asks the lake for its patients in batches of rows

- **Task:** NEW-B-47, part of T-694 (F-07 of `docs/reviews/2026-11-11-scale-timeouts.md`); the nightly of 2026-11-14
  (run 43631693731): `scale-50k` FAIL at the screen's S1
- **PR:** this branch (`agent/NEW-B-47-screen-s1-in-batches`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-275 (approved SQL run as stored, guarded by `safe_sql`), D-742 / D-746 (the lake's memory and time
  limits), the architecture review's AD-6 (batch sizes 1, 100 and 1,000 give the same statuses), OD-10

## Context

The nightly scale gate at 50,000 patients: the screen's S1 (the ruleset's compiled SQL over the whole scope, its
`base` being `patient CROSS JOIN` the index dates filtered by `list_contains` over every scoped patient) ran 190 s and
met the lake's memory limit (3 GB): the screen never ended. Reproduced at 10,000 patients with the lake held to
500 MB. Measured on that lake with GZQO's SQL: the memory grows with the rows the query carries, **patients times index
dates**, not with patients alone. About 2,000 rows fit 500 MB (one index date: 2,000 patients; 36 month-ends: 50
patients) and at least 6,000 fit 1 GB. An approved ruleset's SQL cannot change without a new approval, but a patient's
S1 rows (one per index date) depend on that patient alone.

## Decision

1. **S1 asks for its scope in batches** (`_Run._s1_rows`): the same approved SQL, the same index dates, a slice of the
   scope per query; the rows are concatenated. No SQL changes, no re-approval.
2. **A batch is counted in rows:** `TB_CASCADE_S1_ROWS` (declared, default 4,000: the box's lake limit of 3 GB fits
   about 12,000 rows by the measurement above, so a third of that), patients per query = rows ÷ index dates (at least
   one). `CascadeConfig.s1_rows` overrides it for one run. A value that is not a whole number above 0 is refused,
   naming the setting.
3. **The batches change no answer:** every patient's statuses, outcomes and stage counts are the same at any batch
   size (AD-6).

## Measured

At 10,000 patients with the lake at 500 MB (`tools.scale_gate`, measure mode): one query, FAIL (LAKE-LIMIT, S1);
batches of 2,000 patients with 36 index dates, FAIL (72,000 rows a query); 1,500 rows a query, **the screen ends**:
286 model calls in 391 s, the screen's peak 0.67 GiB, the lake's 0.88 GiB, gate green. At 50,000 patients with 36
index dates and the default: 111 patients a query, 451 queries.

## Not in this card

The coverage and proposed-fact reads after S1 (`coverage.py`, `proposed.py`) and the coded values still pass the
whole scope as a list (T-694 part 4, lane B2's next); the note stage in batches (part 3, lane A2); the per-ruleset
weight of the SQL (a ruleset with more criteria needs fewer rows a query: the setting takes it).

## Tests

`tests/unit/test_cascade_s1_batches.py` (6 tests): on the synthetic site through the whole cascade, batches of 37,
100 and 1,000 patients give the same answers and stage counts as one query, with one query per batch, each within its
size; a batch of one patient on 30 of the site's patients gives the same answers; the setting, its default and its
refusals; the setting is declared. The batch tests fail on the parent (no `s1_rows`). No state change.
