# D-750 A lake query that takes a list of patients reads it as a join

- **Task:** NEW-B-49, T-694 part 4 (F-07 of `docs/reviews/2026-11-11-scale-timeouts.md`: "joins, not patient
  lists"), lane B2
- **PR:** this branch (`agent/NEW-B-49-patient-lists-as-joins`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-748 (S1 in batches), D-746 (the lake's time limit per job type)

## Context

The code's own lake queries took a list of patients as `list_contains(CAST($1 AS VARCHAR[]), pid)`. DuckDB checks
that per row against the whole list: the cost is rows times the list's length (F-07: 1 M rows x 50,000 patients,
28 s). The coverage and proposed-fact reads after S1, the coded values of the candidate list (seven tables, with a
second list of record ids), the twin's timeline, FEAS's profile, the micro-batch's bookings, the screen's deceased
check, the navigator's claims, the cascade screen's patient check and the nightly derive's read
(`derived_store.rows_from_lake`) all asked this way.

## Decision

1. **A list of patients, or of record ids, is read as `pid IN (SELECT unnest(CAST($n AS VARCHAR[])))`**: a hash
   join, rows plus list. The NULL-means-everyone form keeps its meaning (`CAST($n AS VARCHAR[]) IS NULL OR pid IN
   (...)`). Each query's answer is the same; no parameter changes; the lake's SQL guard already allows `unnest` (the
   compiled SQL uses it).
2. **A lint test keeps it so** (`tests/unit/test_patient_lists_are_joins.py`): no per-row list check
   (`list_contains`, `list_has`, `array_contains`, `array_has`, any case and cast) over a patient or record-id column
   in `services`, `libs` or `tools`, except the two listed with their reason: the cascade's note query (lane A2's
   card) and the approved S1 SQL of the compiler (D-275; D-748 asks for it in batches).
3. **Short lists of codes** (`list_contains($2, code)` over a criterion's code list, departments, products) stay:
   they are tens of codes, not a scope.

## Measured

DuckDB 1.5.5, 1 M rows over 50,000 patients, half of the list's patients present: a list of 1,000 patients 0.27 s
as `list_contains`, 0.06 s as a join; 10,000: 2.34 s and 0.51 s; 50,000: 8.6 s and 2.6 s. The review, with 200,000
patients in the table: 1,000: 0.48 s and 0.08 s; 10,000: 4.05 s and 0.53 s; 50,000: 27.4 s and 2.65 s (F-07's 28 s).
At 10,000 and above the join's time is almost all binding the list itself (about 2.7 s at 50,000, linear in the
list, the same for both forms).

## Not in this card

The cascade's note query (`NOTES_SQL`) and the note stage in batches: T-694 part 3, lane A2's card (listed in the
lint test until it lands). The approved S1 SQL is not changed (D-275); D-748 asks for it in batches. The binding cost
of a very long list remains (about 2.7 s at 50,000): batching, where a caller needs it, is per caller.

## Tests

`tests/unit/test_patient_lists_are_joins.py` (19 tests; the lint fails on the parent): no per-row list check over a
patient or record-id column but the two listed; the pattern finds each form (casts, case, `list_has`/`array_has`,
a sub-select) and leaves code lists and one patient's documents; each changed query of the code, run on a synthetic
lake of every lake table, passes the lake's SQL guard and reads the same rows, as many times, as its `list_contains`
form, for NULL (where the query allows it), an empty list, repeats and unknown ids, every patient and a NULL in the
list (coded values: with three lists of record ids). The changed modules'
existing tests pass unchanged. No state change.

## Review

A fresh read-only review ran every changed query against its old form on a synthetic lake (19 queries, 0
differences, no doubled rows; every id column is VARCHAR), `EXPLAIN` (a hash semi join, also in the OR-NULL form and
inside the coded values' UNION ALL) and the SQL guard (all accepted). It found: two queries in
`derived_store.rows_from_lake` missed (fixed); the lint's pattern missed the compiler's S1 form, the record-id
columns, other casts and DuckDB's other names (fixed, the S1 SQL listed); the 50,000 figure understated the old cost
against F-07 (both measurements now given); the equivalence test compared two inline strings, not the code's SQL
(fixed). Two gaps it found existed before this card and stay: no test fails when `proposed.SQL` loses its NULL form
or the coded values lose the claim's record-id filter.
