# D-623 Two more tests in the cross-card list

- **Task:** CROSS-CARD-2 (asked by the integrator after train 5 was built, 2026-11-13)
- **PR:** this branch (`agent/CROSS-CARD-2-two-meeting-tests`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-475 (the cross-card tests: the tests that fail only when two cards meet, run first in CI)

## Context

On train 5 two tests caught a card meeting another that `make cross-card` did not run:

- `tests/unit/test_db_schemas_enumerated.py`: a new `Database.connect` by a name made at run time, which the
  enumerated schema list cannot see;
- `tests/unit/test_runbook_install_commands.py`: a new command in section 1 of the runbook with no test that
  runs it.

Both were found only in the unit shards of the full tier, after the train was built. Each card was green alone.

## Decision

Both files join `CROSS_CARD_TESTS` in the `Makefile`, so the fast tier's `cross-card` job runs them on every
branch. Measured together on this machine: 38 tests in about 45 seconds on one worker. The unit shards still
run them, as they run the rest of the list.

`tests/unit/test_test_shard.py::test_the_cross_card_list_names_existing_tests` names both, so that neither
leaves the list without a decision.

## Consequences

- A runbook command without a runner, or a database opened under a run-time name, is red on the card's own
  branch in the fast tier, not on the train.
- The `cross-card` job grows by under a minute.
