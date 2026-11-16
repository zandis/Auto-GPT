# D-953 A notes-only screen gets its population's pairs as its budget

- **Task:** G7 of the integrator's second review of the P1b run (#639, 2026-11-16). Every notes-only ruleset, 4 protocols, stopped at SCREEN "running" with "has no coded criterion, so every patient goes to the models: set max_pairs" (`engine.py`, D-788).
  - The mail grammar has no `max_pairs` key and no default, so a job could never set one.
  - A coded ruleset with no budget set runs without one, and its report already names the population's own pairs as its budget (T-689).

  **Date:** 2026-11-16. **Status:** reserved.
- **Decision** (`screen_cascade.notes_only_budget`). When SCREEN has no `max_pairs` and the ruleset has no coded criterion, the cascade's budget is the population's pairs: every scoped patient, once for each note inclusion and exclusion. The test for "coded" is the cascade's own (`Run.applied`).
  - A coded ruleset is unchanged, with no budget.
  - The cascade's guard (D-788) stays for every other caller.
  - The report's `budget.source` is still "population".
- **Test:** `tests/unit/test_notes_only_ruleset.py::test_a_screen_with_no_budget_set_gives_a_notes_only_ruleset_its_populations_pairs`. The budget is the population's pairs, every pair fits, and a coded ruleset gets none.
