# D-995 every CI job's time limit is inside 90 minutes, or named with its reason

- **Task:** CI-TIMEOUTS (lane D), the follow-up promised on #639 after #965 (train 69)
- **PR:** this branch (`agent/CI-TIMEOUTS-every-job-inside-ninety`)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-537 (the owner: no CI job over 90 minutes, no ceiling raised to get there), D-564 and D-970 (the CI
  tiers), D-578 (no workflow run by hand)

## Context

A job's `timeout-minutes` is where a hang ends and what a stuck run costs. Three jobs that run on cards, trains or
nights had limits far above what they take, and one (compose, 150) was above D-537's 90. Measured on 2026-11-16 and
2026-11-17:

| job | workflow | was | measured | now |
| --- | --- | --- | --- | --- |
| checks | trialbox-ci.yml | 15 | 3 min 8 s | 8 |
| compose | trialbox-e2e.yml | 150 | 37.5 min (about 48 with the new-study walk) | 90 |
| rehearse | trialbox-rehearse-box.yml | 120 | about 20 min a variant (run 44047178035: 19 min) | 60 |

## Decision

1. **The three limits are lowered** to the table's last column: each is more than twice its measured time, so a slow
   runner does not fail the job, and a hang ends sooner.
2. **A test guards the rule** (`tests/unit/test_ci_jobs_inside_ninety.py`): every job in `.github/workflows` names a
   `timeout-minutes` (none runs to GitHub's 360), and a limit above 90 must be on the test's list with its reason. The
   list may only shrink; a job that falls to 90 or below must leave it.
3. **Three jobs stay above 90, named, for the owner** (asked on #639): scale-50k (340; the 50k night measured 74 min),
   multiarch (120; a release tag or by hand, never measured) and the P-0 media build (360; by hand, never run). This
   card does not lower them without a measured run: lowering a limit blind risks a release-day red, and D-537 says to
   shrink the work, which is the owner's call for these.

## Consequences

- A hung check ends after 8 minutes, not 15; a hung compose job after 90, not 150; a hung rehearsal after 60, not 120.
- A new job without a limit, or with one above 90, fails the card's own tests.
