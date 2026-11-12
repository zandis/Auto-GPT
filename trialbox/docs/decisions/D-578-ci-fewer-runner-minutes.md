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

1. **One job for the short checks.** `lint`, `types`, `docs`, `contracts`, `trace` and `shell` are the steps of
   one job, `checks`: one runner, one set-up. Every check step runs unless the run was cancelled, so a failed
   step does not hide the next, and the job fails when any failed. The fast tier is `changes`, `checks`,
   `data-scan`, `cross-card`.
2. **The image gates** run for a merge train, on master when what goes into an image changed, for a release tag,
   weekly and by hand. Not on a card's pull request: a card that changes an image says so and goes on a train
   early. The arm64 leg runs for a train, master and a release tag; the weekly run and a run by hand scan amd64.
   The multi-architecture job still runs for a release tag or by hand only.
3. **The lock job** of the supply-chain workflow starts on what it reads (the locks, `deploy/`, the gate code, its
   tests and fixtures, the Makefile, the workflows), not on all of `trialbox/`. Its gate tests also run with the
   unit tests, and new advisories are the weekly run's.
4. **A push to master at a tree a train proved** runs the fast tier only. `tools/ci_proved_tree.py` says so only
   when the pushed commit is a merge of two whose tree equals the second parent's, that parent is the head of a
   merged pull request from a `train/*` branch, and every `unit` check GitHub Actions recorded on that head
   passed. Any doubt or error says no, and the full tier runs. The nightly run keeps the whole suite on master.

### Why the lock job "failed" 22 times

It did not fail on a lock. Of the 22 failures among the 400 most recent runs of 2026-11-12, 21 were jobs that
never got a runner (no step ran; all between 09:06 and 10:09 UTC, when the workflow had 21 failures and 1
success), and one was a checkout that could not fetch the pull request's merge ref. No run failed in the lock
check, the allow-list check, pip-audit, the licence gate or the gate tests. A successful job takes 33 to 40
seconds.

### The unit shards (measured, not changed)

From the push run on master 43263463727 (all six shards green):

| Shard | Wall | Three slowest files (seconds, from the 30 slowest tests) |
| --- | --- | --- |
| 1/6 | 19 m 40 s | `unit/test_recall_ledger.py` 211; `unit/test_criteria_safety.py` 126; `integration/test_ad_mab.py` 74 |
| 2/6 | 22 m 05 s | `integration/test_list_demo.py` 639; `unit/test_cascade_pipeline.py` 74; `unit/test_outbox_killloop.py` 66 |
| 3/6 | 19 m 55 s | `integration/test_e2e_simple.py` 279; `integration/test_cohort_inproc.py` 98; `unit/test_omop_core.py` 83 |
| 4/6 | 10 m 34 s | `unit/test_ingest_streams.py` 110; `integration/test_twpas_inproc.py` 109; `integration/test_feas_lake.py` 26 |
| 5/6 | 16 m 24 s | `integration/test_poc_scripts.py` 165; `integration/test_rc_demo.py` 126; `integration/test_nav_retro.py` 111 |
| 6/6 | 16 m 09 s | `console/test_orch_box.py` 151; `e2e/journeys/test_journeys.py` 148; `integration/test_cgmh_demo.py` 97 |

The shards are cut by a hash of the file path, not by duration. The six pytest steps sum to about 100 minutes; an
even cut would be about 17 minutes a shard against 21 for the longest now. Weights would shorten the wait by
about 4 minutes and would not lower the bill: the same tests run for the same time. No dependency is proposed
(pytest-split would be one more locked package for no billed minute). What would lower the bill is in the tests:
`test_list_demo.py` alone is 639 seconds, and `test_e2e_simple.py` (279 seconds) runs in shard 3 while the job
`e2e-simple` runs the same scenario through its tool (not checked whether one could stand for the other). Those
are other lanes' tests; they are named here, not touched.

### Billed minutes, before and after (estimates; a job bills whole minutes)

| What | Before | After |
| --- | --- | --- |
| fast tier, one push to a pull request | 9 jobs and `lock`: about 11 | 4 jobs: about 7; `lock` only when its inputs changed |
| image gates on card pull requests, 2026-11-12 | 129 runs, about 2,900 | 0 |
| a train: its full run, then the push to master | about 135 + about 135 | about 130 + about 7 when master had nothing the train lacked |

The image gates of a train are as before. A push to master now also starts them when an image's input changed;
that run repeats what the train scanned and could go the same way as rule 4 if the owner wants it.

## Consequences

- **Branch protection.** Where the required checks name `lint` or `contracts`, they must name `checks` instead,
  at the moment this lands; `types`, `docs`, `trace` and `shell` no longer exist as check names. `unit`, `goldens`,
  `data-scan` and `e2e-simple` are unchanged.
- A card that changes an image no longer sees the image gates on its own pull request. It says so in its body.
- The `changes` job may read checks and pull requests (read only) to ask about a train's head.
- `tests/unit/test_ci_tiers.py` holds the tiers, the steps of `checks` and their commands, the image gates'
  triggers and the lock job's paths; `tests/unit/test_ci_proved_tree.py` holds rule 4.
