# D-1001 in the branch-coverage shards the per-test hang guard is twice the project's

- **Task:** plan 10's 9i-1 (the nightlies green, lane D), the red of the nightly quality run of 2026-11-18
- **PR:** this branch (`agent/COVERAGE-TIMEOUT-the-hang-guard-scales-with-the-tracer`)
- **Date:** 2026-11-18
- **Status:** accepted
- **Builds on:** D-727 (the twelve coverage shards), D-537 (no CI job over 90 minutes)

## Context

`pyproject.toml` sets pytest-timeout's `timeout = 900`. It is a hang guard: a test that runs longer has stopped
making progress.

The nightly's branch-coverage shards run the same tests under the coverage tracer, which roughly doubles a test's time.
`tests/integration/test_e2e_simple.py::test_e2e_simple` (the build gate's whole hospital) is the slowest:

- 816 s in shard 3 on 2026-11-17;
- over 900 s on 2026-11-18 (run 44352122514, job 134970304788).

The second night the guard fired on a test that was still working. Shard 3 went red, so `branch-coverage` did too, and
`gateway/core.py` and `model_guard` could not report their floors. Shard 3 took 30 of its 90 minutes.

## Decision

The coverage shards pass `--timeout 1800` in `PYTEST_ADDOPTS`: twice the project's value, for the tracer. Every other
run keeps 900 s. The job's own limit (90 minutes, D-537) is unchanged, so a real hang still ends the shard.

## Test

`tests/unit/test_coverage_hang_guard.py` checks that:

- the shards' guard is twice pyproject's;
- the job limit is still 90;
- no other workflow changes the guard, and pyproject's is still 900.
