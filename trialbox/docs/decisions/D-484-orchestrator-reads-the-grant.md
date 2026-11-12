# D-484 The orchestrator reads the break-glass grant and the delegation log itself and writes the use; `breakglass` is no longer a role

- **Card:** T-716 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-716-orchestrator-reads-the-grant`); built on T-715's branch (PR #317), which is
  built on T-714's (PR #312): it shows their commits until they merge
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-280 / D-430 (break-glass: one rule, 60 minutes, each use recorded), D-273 (chart numbers only to a
  signed role and study), D-438 (one reveal path in the console), D-483 (actor assertion v3)
- **Closes:** finding F5 (a) and (c) and proposal TR-4 of `docs/reviews/2026-11-12-architecture/trust.md`

## The problem

The console checks a break-glass grant: a row, for this person, this patient or this job, open now. It then signs
the word `breakglass` as the person's role, and the orchestrator gives a chart number to that word. The
orchestrator never sees the grant: a caller that can sign (the console's token) gets every listed patient's chart
number with the word alone, and the grant's use counter, which the console writes before the call, stays at zero.
The same holds for an investigator's standing in a study: the console reads the delegation log, the orchestrator
is told the result.

## The decision

(filled in with the build; see the pull request)
