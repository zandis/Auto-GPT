# D-943 FEAS drops an unknown inclusion by D-18: an intended difference, not a known failure

- **Task:** ENG-005, lane A2's share: burn down the `KNOWN` table of expected failures in screening (plan v7 §5, plan 37). Lane A2's backlog (#639, 2026-11-16). **Date:** 2026-11-16. **Status:** reserved.
- **Decision:**
  - **What was in the table.** The path-independence test (`tests/property/test_path_independence.py`, D-459) had one line left in `KNOWN`: finding M4 of the 2026-11-12 architecture review. FEAS drops a patient whose inclusion has no value (`IS TRUE`), while SCREEN keeps the patient for review. It ran as a strict xfail.
  - **It is a rule, not a defect.** D-18 decides that half of M4:
    - a funnel's `remaining` counts a patient only when every applied inclusion is true;
    - the patients dropped only by unknowns are reported per step;
    - the `unknown_as_pass` sensitivity variant is always included.

    A count is a lower bound with its sensitivity beside it; a list is who a person looks at. COHORT's same rule was already listed as intended (`cohort.documented`).
  - **The test now reads it as intended.** The line moves to `INTENDED` as `feas.unknown`, citing D-18. FEAS's expected status is "-" when an applied structured inclusion is unknown. `KNOWN` is empty, so a new expected failure has to name its finding again.
  - **What stays open.** M4's other halves (opt-out and consent, the code-gap overrides, month-ends) are covered by `counts.contact`, `feas.population` and D-477 (R2), as before.
- **Test:** `tests/property/test_path_independence.py` (283 passed; `KNOWN` empty).
