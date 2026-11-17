# D-924 S1 is one query where it was measured to fit, and D-748's batches elsewhere

- **Task:** NEW-B-58 (the nightly perf-5k red: `cascade_s` 17.92 s against the 14.67 s baseline; first slow on train 19, D-748), lane B2 · **PR:** `agent/NEW-B-58-s1-batches-from-lake-memory` · **Date:** 2026-11-17 · **Status:** accepted · **Builds on:** D-748, D-920

1. D-748's batches run the ruleset's whole SQL once per batch, about 0.5 s of fixed cost a query. At 5,000 patients × 36 index dates that is 16 queries and 12.9 s of S1 on the gate's host, against 5.0 s in one query.
2. **Batching as a join (D-750's form) was not chosen:** the per-query cost is the SQL's own scans, which a join does not remove. **Sizing from memory alone was not chosen either:** the measurements do not fit a per-row model (24,000 rows failed on a 10,000-patient lake at 1 GB, while 180,000 rows fitted in 1.9 GB at 5,000 patients).
3. **The rule** (`matching.cascade.engine.patients_per_query`, used by the cascade's S1 and by `matching/batches.py`): S1 is one query when its rows are at most `TB_CASCADE_S1_WHOLE_ROWS` (180,000, the measured 5,000 × 36) **and** the lake says its memory limit is at least `TB_CASCADE_S1_WHOLE_GB` (4, twice the 1.9 GB that one query peaked at). Otherwise D-748's batches apply unchanged.
   - The lake says its limit through `memory_limit_bytes()`: in process, from `lake.store.memory_limit`; over HTTP, from the lake's new `GET /limits`. A lake that cannot say gets the batches.
   - A run's own `s1_rows` or a set `TB_CASCADE_S1_ROWS` always keeps the batches.
4. **Measured on the bench gate's host** (4 CPUs, 16 GB): the gate passes, with cascade 16.44 s against the scaled 14.67 s (+12.1 %) and peak 1,951 MB against 1,871 MB (+4.3 %). With D-748's batches the same host took 25.87 s.
   - The 50,000-patient night carries 1,800,000 rows, so it keeps D-748's batches and its memory peak exactly.
5. **Tests:** `tests/unit/test_s1_whole_or_batches.py` covers the rule and each of its refusals, the size parser, the route and the client, and through the cascade one query gives the batches' answers. D-748's and D-920's batch tests pass unchanged.
