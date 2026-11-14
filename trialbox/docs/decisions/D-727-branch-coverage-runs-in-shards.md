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

## Decision

(written when the card is built)
