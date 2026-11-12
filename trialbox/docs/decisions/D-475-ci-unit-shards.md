# D-475 The pull-request `unit` job in parallel shards, the coverage ratchet on their combined coverage, and a fast `cross-card` job

- **Task:** T-747 (no plan row: the integrator's card prompt of 2026-11-12 is the row)
- **PR:** this branch (`agent/T-747-ci-unit-shards`)
- **Date:** 2026-11-12
- **Status:** proposed (in review)
- **Builds on:** D-201 (test isolation, one cluster per xdist worker), D-206 (the CI gate and its job names),
  T-651 (the coverage ratchet), D-384 (`e2e-simple` keeps its plain name across a matrix)

## Context

The `unit` job of `.github/workflows/trialbox-ci.yml` ran the whole unit suite (about 6,580 tests) on one runner:
35 to 43 minutes of pytest in the runs of 2026-11-12 (set-up under a minute), up to 55 on a busy day. Every push of
every pull request runs it, and every merge to master sends the next pull request through it again. Separately,
four pull requests in one day each lost a full round to a test that fails only when two cards meet (an audit event
without a label, a new route without a permit row, a new table without an inventory row, ...).

## Decision

(filled in by the card's commits)
