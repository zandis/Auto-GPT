# D-920 The FEAS funnel, the cohort list and SqlEngine ask the lake for their patients in batches

- **Task:** NEW-B-53 (T-694, F-07 of `docs/reviews/2026-11-11-scale-timeouts.md`), lane B2 · **PR:** `agent/NEW-B-53-feas-cohort-evaluate-in-batches` · **Date:** 2026-11-16 · **Status:** accepted · **Builds on:** D-748

1. `matching.batches.query_by_patients` asks a query that takes the index dates (`$1`) and the patients (`$2`) for a slice of the patients at a time, as many as fit `TB_CASCADE_S1_ROWS` rows (patients times index dates, D-748's setting and measure), and puts the tables together in the slices' order; a batch of 0 rows or less is refused.
2. "Every patient" (`$2` NULL before) is the snapshot's patients in `pid` order, asked first in one small query, so the funnel's per-patient rows (it groups and orders by `pid`) come out as one query gave them.
3. The FEAS funnel (`feas_compute.compute`), `cohort.items_at` and `SqlEngine.evaluate` ask through it; the SQL, its approval and the extra parameters (lookback, departments) are unchanged.
4. A patient's rows depend on that patient alone, so batches change no count, row or answer; at 50,000 patients and 36 month-ends the funnel is about 150 queries instead of one that meets the lake's memory limit.
5. Tests: `tests/unit/test_scope_queries_in_batches.py` (the funnel at 37 and 250 patients a batch against one query; the approved SQL for every patient at 37 and 12,000 rows and for given patients at 1 and 37; no patients; a batch of none refused); `test_lake_query_status.py` names the new caller.
