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
500 MB. Measured on that lake: the memory grows mostly with the rows the query carries, **patients times index
dates** (patients count too, and the ruleset's weight). At 500 MB GZQO fitted 4,000 rows and failed at 6,000; RA-BIO,
heavier, fitted 2,000 and failed at 3,000. At 1 GB both fitted 12,000 rows at 36, 12 and 1 index dates; GZQO at 12
index dates failed at 24,000. At 3 GB the whole 10k scope fitted one GZQO query (360,000 rows); the 50k one did not. An approved ruleset's SQL cannot change without a new approval, but a patient's
S1 rows (one per index date) depend on that patient alone.

## Decision

1. **S1 asks for its scope in batches** (`_Run._s1_rows`): the same approved SQL, the same index dates, a slice of the
   scope per query; the rows are concatenated. No SQL changes, no re-approval.
2. **A batch is counted in rows:** `TB_CASCADE_S1_ROWS` (declared, default 12,000: what fitted both heavy rulesets at
   1 GB, the smallest lake limit `lake.store.memory_limit` derives; a lake held below that sets it lower, the 500 MB
   gate run used 1,500), patients per query = rows ÷ index dates (at least one). `CascadeConfig.s1_rows` overrides it
   for one run. A value that is not a whole number above 0 is refused, naming the setting (or `s1_rows`).
4. **The time it costs:** each S1 query has a fixed cost (about 1.1–1.5 s for GZQO's SQL: its `safe_sql` check and
   the lake's planning), so batches cost time: at 50,000 patients with 36 index dates and the default, 151 queries,
   about 4 minutes of fixed cost, within the night. A box with a larger lake limit may raise the setting.
3. **The batches change no answer:** every patient's statuses, outcomes and stage counts are the same at any batch
   size (AD-6).

## Measured

At 10,000 patients with the lake at 500 MB (`tools.scale_gate`, measure mode): one query, FAIL (LAKE-LIMIT, S1);
batches of 2,000 patients with 36 index dates, FAIL (72,000 rows a query); 1,500 rows a query, **the screen ends**:
286 model calls in 391 s, the screen's peak 0.67 GiB, the lake's 0.88 GiB, gate green. At 50,000 patients with 36
index dates and the default: 333 patients a query, 151 queries. On the 10k lake, GZQO, 36 index dates: one query
14 s; batches of 4,000 rows 149 s (91 queries).

## Not in this card

The coverage and proposed-fact reads after S1 (`coverage.py`, `proposed.py`) and the coded values still pass the
whole scope as a list (T-694 part 4, lane B2's next); the FEAS funnel (`feas_compute.py`), the cohort query
(`cohort.py`) and `evaluate.py` still ask for the whole scope in one query and will likely meet the same limit at
50,000; the note stage in batches (part 3, lane A2); the per-ruleset
weight of the SQL (a ruleset with more criteria needs fewer rows a query: the setting takes it).

## Tests

`tests/unit/test_cascade_s1_batches.py` (8 tests): on the synthetic site through the whole cascade, batches of 37,
100 and 1,000 patients give the same answers and stage counts as one query, with one query per batch, each within its
size, and each scoped patient asked for exactly once; a batch of one patient on 12 of the site's patients gives the same answers; the setting, its default and its
refusals, and a configured batch of 0 or below refused; the setting is declared. The batch tests fail on the parent (no `s1_rows`). No state change.

## Review

A fresh read-only review found no wrong answer (40 comparisons of batched against one query, all 8 rulesets,
identical). It found: the first default (4,000) rested on an unmeasured 3 GB figure and cost about ten times S1's time
(fixed: 12,000 from a measurement at 1 GB, the time stated); the record's 500 MB figure was RA-BIO's, not GZQO's
(fixed); the tests did not check that each patient is asked for once (a mutant stepping one short survived; fixed);
a configured batch of 0 fell back silently and a negative one meant one patient (fixed: refused); the whole-scope
queries outside this card are now named.
