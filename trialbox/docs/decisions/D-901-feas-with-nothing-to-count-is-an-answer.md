# D-901 FEAS with nothing to count is an answer, not a failed job

- **Task:** red of lane G's accuracy run (#639, 2026-11-15, tcga); **Date:** 2026-11-15; **Status:** reserved
- **Decision:** FEAS counts structured criteria only (D-40). A ruleset with none (every criterion mixed, note or human) ends its FEAS job done, with a summary and headline saying there is nothing to count (en, ja, zh-TW), no funnel, no attachment, `patients_scoped` 0; the lake is not read and the job chain goes on. Before, the job failed with "ruleset has no structured criteria to count".
- **Test:** `tests/unit/test_feas_nothing_to_count.py`.
