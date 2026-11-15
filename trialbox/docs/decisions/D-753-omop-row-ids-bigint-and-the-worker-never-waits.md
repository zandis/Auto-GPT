# D-753 The OMOP row ids are bigint, and the opt-out worker never waits for a load

- **Task:** T-702, the rest after D-678 (F-17 of `docs/reviews/2026-11-11-scale-timeouts.md`), lane B2 · **PR:** `agent/T-702-omop-export-ids-lock` · **Date:** 2026-11-15 · **Status:** accepted

1. Migration 9 of the OMOP store (`omop.schema.row_ids_ddl`) widens to `bigint` every `integer` id column of the CDM tables but the concept ids and the person, provider, care-site and location ids (their own sequences), and TrialBox's row-id columns (`tb_record.record_id`, the appointment, claim and consent keys); `tb_row_seq` loses its int4 end (2,147,483,647, about 4,300 records a patient at 500,000 patients).
2. The opt-out worker's `withhold` tries the load's lock and is refused at once (`LoadRunning`) while a load holds it: its tick ends (the clear is reported failed, as any store not cleared, and tried again on the next tick); before, it waited for the whole load and its health line went red.
3. The migration rewrites the widened tables once (minutes at 50,000 patients); the OMOP store is behind its flag (the dual write), so few boxes hold a large one.
4. Not in this card: the export back from OMOP streamed (`omop.export.export_rows` is still whole): the next card.
5. Tests: `tests/unit/test_omop_row_ids_and_worker.py` (3: every row-id column bigint, partitions too; the sequence past the int4 end into a row; the worker refused within seconds under a held load, then withheld after it). The migration's hash is pinned; the version counts are 9.
