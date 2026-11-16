# D-822 The box form installs a VALIDATION box

- **Task:** BOX-VALIDATION, the owner's blockers 8 and 10 of 2026-11-15 (lane G's first real-model accuracy run)
- **PR:** this branch (`agent/BOX-VALIDATION-the-box-form-installs-validation`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-127 (a box is PRODUCTION unless the operator says), D-726 (a rehearsal box is TEST)

## Context

A box made by `box-install.sh` was always PRODUCTION: the owner's answers (`tb_common.box_answers`) had no
environment and the box plan never wrote `TB_ENV` (`tools/box/plan.py`). Lane G's accuracy run needs a VALIDATION
box with local models, on public data. `TB_ENV`'s declared help named DEV, TEST and PRODUCTION only.

## Decision

1. The owner's answers take `environment`: PRODUCTION (the default, also of the provisional answers) or VALIDATION.
   Any other value (DEV, TEST, a typo) is a problem of the form (`environment`), never a guess: a box is not a DEV
   or TEST box, and a rehearsal box is TEST by its own installer argument (D-726).
2. The box plan writes the answer as `TB_ENV`.
3. `TB_ENV`'s declared help names DEV, TEST, VALIDATION and PRODUCTION.
4. The first-run page does not ask it yet (lane C2 and W); an answers file gives it.

## Test

`tests/unit/test_box_validation_env.py`: before, 10 failed; after, 10 passed, with the box plan, answers and config
tests unchanged.
