# D-751 PostgreSQL is sized from its memory cap

- **Task:** T-703 (F-19 of `docs/reviews/2026-11-11-scale-timeouts.md`), lane B2 · **PR:** `agent/T-703-postgres-sized-from-host` · **Date:** 2026-11-15 · **Status:** accepted

1. `deploy/install.sh` writes PostgreSQL's settings from `TB_MEM_DB` (`tools/trialbox/pgsize.py`, PGTune's rules): `shared_buffers` a quarter, `effective_cache_size` three quarters, `maintenance_work_mem` a sixteenth (at most 2 GB), WAL 4 to 16 GB (bulk writes), `/dev/shm` as large as the buffers.
2. `idle_in_transaction_session_timeout` is twice the longest lake query a job may wait on (`TB_LAKE_QUERY_LIMITS`, D-746).
3. A value set by hand is kept; compose's defaults are PostgreSQL's own, so a dev or test stack is unchanged; the platform manifest carries the sizes of its 4Gi limit, kept by a test.
4. `trialbox doctor` (`postgres_memory`) fails when `shared_buffers` is the default on a host of 64 GB or more, and warns on a smaller one.
5. Tests: `tests/unit/test_pgsize.py` (11). The database's cap itself (`TB_MEM_DB`, the hardware profiles) is unchanged.
