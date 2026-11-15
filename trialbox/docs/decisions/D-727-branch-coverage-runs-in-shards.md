# D-727 The nightly branch coverage runs in shards

- **Task:** NIGHTLY-QUALITY (the integrator, 2026-11-14: "TrialBox nightly quality" was cancelled on runs 3, 4 and
  5; it counts toward R1, nightly green three nights in a row)
- **PR:** this branch (`agent/NIGHTLY-QUALITY-branch-coverage-in-shards`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** T-651 (ENG-029: mutation and branch coverage at night), D-475 and D-564 (the unit suite in shards)

## Context

Runs 3, 4 and 5 of `.github/workflows/trialbox-nightly-quality.yml` ended "cancelled". The three mutation shards and
`mutation-score` passed each night. The one job that did not is `branch-coverage`: each night it ran for 60 minutes
16 seconds, its `timeout-minutes: 60`, and was cut off in "pytest -n auto with branch coverage" with "The operation
was canceled." at about 11 % of the suite. A timed-out job is reported as cancelled, so the run was. The pull
request runs the same suite in six shards of up to 40 minutes each with the cheap tracer (`COVERAGE_CORE: sysmon`);
on Python 3.12 sys.monitoring does not measure branches, so the nightly job uses the classic tracer, which is slower
still. One job of 60 minutes cannot hold it.

## Measured here (4 cores, the container of lane D's session, 2026-11-14)

- The whole unit suite without coverage: about 12 minutes (`make cross-card`, several runs this week).
- With `--cov --cov-branch` (the nightly's options): 82 % after 37 minutes alone, 96 % after about 95 minutes (the
  last hour shared the machine with another suite), and still in its last few percent when it was stopped. No test
  failed and none errored up to 96 %: the bursts of `E` in the nightly's log of run 5 were not seen here, and the
  cancelled job's log ends before pytest prints them. The tail is a few files that are very slow under the tracer.
- A first attempt filled this machine's disk (each worker's throwaway PostgreSQL cluster grows to gigabytes over a
  whole run) and gave 807 errors that were the disk's: one job for the whole suite also puts all of that on one
  runner's disk.

## Decision

1. `branch-coverage-shard`: twelve jobs, each `make test SHARD=i/12 SHARD_RECORD=...` with
   `--cov --cov-branch --cov-report=`, the pull request's own split (`tools/test_shard.py`: each test file in one
   shard, by a hash of its path). `fail-fast: false`; 90 minutes each: a twelfth of a run of hours, with room for a
   slow file, which stays whole in its shard. Each keeps its `.coverage` and its record as an artifact.
2. `branch-coverage` (the old name, so a reader of the run sees the same job): runs when a shard failed too
   (`!cancelled()`), fails unless every shard passed, checks with `tools.test_shard check` that every collected test
   ran in exactly one shard, combines the shards' coverage and runs `tools.coverage_ratchet` on it, as before.
3. The mutation jobs are unchanged: they passed every night.

The first green night's shard times decide whether twelve and 90 stay (the times are in each shard's
`--durations=30`).
