# D-999 the make targets that run the e2e tests mark the branch's test root first

- **Task:** a red of the nightly compose job of 2026-11-17 (lane D's CI, the D-537 check-in on #639)
- **PR:** this branch (`agent/TEST-COMPOSE-marks-its-test-root`)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** the test-root guard (`tools/pglocal.py` `check_test_root` and `mark_test_root`), H-10 (the new-study
  walk in the compose job, nightly only)

## Context

The nightly compose job (run 44157898449, job 134303482264, `make test-compose`) failed in the new-study walk, on its
first night in that job. The walk starts a local box with `tools/demo.py`. demo.py marks `TB_TEST_ROOT`, and the guard
refused the root: "TB_TEST_ROOT=…/tb-tests-master is refused: it holds files and no .tb-test-root marker (not a test
root)".

The job's earlier steps had written into the root, and nothing had marked it. `make test`, `make walk` and the walk
targets each mark the root before they run. `test-compose` and `test-e2e`, which collect `tests/e2e`, did not.

## Decision

`test-compose` and `test-e2e` run `tools.pglocal mark "$(TB_TEST_ROOT)"` first, as the other test targets do. The guard
stays as it is: a folder of other files is still refused.

## Test

`tests/unit/test_e2e_targets_mark_their_root.py` checks two things:
- both targets mark the root before their pytest line. This failed on `test-compose` before the change;
- the walk tests these targets collect start `tools/demo.py`, which marks the root and refuses an unmarked one.
