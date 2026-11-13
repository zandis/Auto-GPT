# D-637 A test gives the settings it changed back

- **Task:** BREAKER-TEST (a test seen failing three times on 2026-11-13, through the integrator)
- **PR:** this branch (`agent/BREAKER-TEST-a-clock-the-test-moves`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-146 (a test must not leave the service token set), D-635 (a test gives its connections back)

## Context

`tests/unit/test_job_cancel_breaker.py::test_screen_fails_fast_on_a_wedged_model_and_runs_again_after_the_window`
failed in three whole-suite runs and passed alone: "the judge model did not answer 8 calls in a row" where the
test sets 3. It was taken for a wall-clock test. It is not: it already runs on a clock the test moves.

Found by running the files in one process: a test that drives `tools/complete_run.py` in process leaves
`TB_SCREEN_LLM_CONCURRENCY=4` in the process environment (the tool sets it for the parts it runs, as a
command-line tool may). The breaker's threshold is at least twice the calls in flight
(`BreakerSettings.from_env`, T-689), so every later test of that worker ran with a threshold of 8. Which test
runs after which depends on how the workers split the files, hence "under load".

## Decision

The harness gives the settings back, as it gives the connections back: after each test, every `TB_*`
environment variable is what it was before the test (an autouse fixture in `tests/conftest.py`). A variable a
wider fixture set before the test is part of "before" and stays. D-146's fixture for four named variables is
kept: it also names why.

No test is changed, and neither is the tool: setting its own process's environment is right for a command-line
tool.

## Consequences

- A test cannot change another test's settings through the process environment, whichever tool it drives.
- The breaker test needs no change; the order that failed is kept as a test of the fixture.
