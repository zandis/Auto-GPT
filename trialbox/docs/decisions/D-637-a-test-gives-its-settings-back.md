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

Found by running the files in one process. `tools/complete_run.py` sets `TB_SCREEN_LLM_CONCURRENCY` in its own
process environment for the parts it runs, as a command-line tool may. `tests/unit/test_g3_throughput_curve.py::
test_a_part_sets_the_setting_for_its_screen` drives it in process and takes the value away again with
`monkeypatch.delenv`; monkeypatch remembers what it removed (4) and puts it back when the test ends. The breaker's
threshold is at least twice the calls in flight (`BreakerSettings.from_env`, T-689), so every later test of that
worker ran with a threshold of 8. Which test runs after which depends on how the workers split the files, hence
"under load".

## Decision

The harness gives the settings back, as it gives the connections back: after each test, every `TB_*`
environment variable is what it was before the test (`tests/settings_kept.py`, a plugin registered in
`tests/conftest.py`). Its fixture belongs to the session, so it is set up first and ends last of the test's own
fixtures: after monkeypatch has undone (or redone) its changes. What a wider fixture set while it was set up is
part of "before" and stays for the tests that share it. D-146's fixture for four named variables is kept.

No test is changed, and neither is the tool. The one test that leaves the value is lane G's; with the harness
rule it no longer matters which test does.

## Consequences

- A test cannot change another test's settings through the process environment, whichever tool it drives.
- The breaker test needs no change; the way the value was left behind is kept as a test of the harness.
- Not covered: a setting changed outside the process environment (a module's own cached value).
