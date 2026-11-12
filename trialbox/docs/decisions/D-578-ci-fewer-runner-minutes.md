# D-578 CI: fewer billed runner minutes for the same checks

- **Task:** CI-COST (given to lane D by the integrator on 2026-11-12, after the owner asked for a review of how
  the project uses GitHub Actions)
- **PR:** this branch (`agent/CI-COST-fewer-runner-minutes`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-564 (the CI tiers: a draft runs the fast tier, the full tier runs on a pull request that is not
  a draft, on a merge train, on master and by hand)

## Context

Measured by the integrator on 2026-11-12: the last 1,000 workflow runs, all of that day, billed about 30,000
runner minutes. 31 % went to runs cancelled by a newer push to the same branch. Every job bills whole minutes on
a runner of its own, so six checks of under a minute each cost six minutes and six set-ups. The image gates ran
129 times on card pull requests (about 2,900 minutes with the arm64 leg). A push to master right after a train
merge ran the full suite again on a tree the train had already proved.

## Decision

Written when the card is complete (the measurements and the minutes per train before and after).
