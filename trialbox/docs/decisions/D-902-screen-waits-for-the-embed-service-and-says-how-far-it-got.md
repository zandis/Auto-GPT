# D-902 SCREEN waits for the embed service and says how far it got

- **Task:** red of lane G's accuracy run (#639, 2026-11-15, tcga), the SCREEN checkpoint card; **Date:** 2026-11-15; **Status:** reserved
- **Decision:** a request to the embed service that fails in transport (a dropped or refused connection, a timeout, a 5xx) is sent again after a growing wait (2 s doubling to 30 s) until the job has spent `TB_EMBED_OUTAGE_WAIT_S` (600) seconds waiting, as a model outage is waited out (T-689). A 4xx or a malformed answer fails at once. When the job gives up, its sentence names the requests answered and the sentences embedded, and says they are kept: the vectors stay in the orchestrator's cache (D-900), so the request sent again starts where this one stopped. No judge answer is lost: S2b runs before S3.
- **Not here:** resuming a job after a model answer (S3/S4) by its own id; the kept answers (T-689) cover a restart of the orchestrator.
- **Test:** `tests/unit/test_screen_survives_an_embed_outage.py`.
