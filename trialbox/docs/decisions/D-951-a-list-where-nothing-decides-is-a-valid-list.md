# D-951 A list where nothing decides is a valid candidate list

- **Task:** G6 of the integrator's second review of the P1b run (#639, 2026-11-16). Every all-human ruleset that was approved, 3 protocols, failed SCREEN at the report with a `ValidationError`.
  - D-909 sets `judging.mode = "nothing"` when no criterion is a machine's (`screen_cascade`).
  - The candidate list's `Judging.mode` allowed only agreement, single and none, both in `schemas/candidate_list.schema.json` and in the generated model, so `screen.candidate_list` raised.
  - D-909's own test stopped at the cascade, so it never reached the report.

  **Date:** 2026-11-16. **Status:** reserved.
- **Decision.** `nothing` is a mode of the candidate list. It is in the schema with a description, and the model is regenerated (`tools/gen_contracts.py`). The mail and the PDF already say it, through `screen.judging.nothing`.
- **Guard.** A test reads every mode the screen code writes and requires each one to be in the schema. A new mode can no longer pass the cascade's tests and then fail at the report.
- **Test:** `tests/unit/test_judging_mode_nothing_reports.py`. The run's list builds and its JSON is valid against the schema. Two of its tests fail on master.
