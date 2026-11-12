# D-487 One identifiers module in the orchestrator; a chart number becomes a pseudonym over HTTP only for a verified person with a right, audited and capped

- **Card:** T-719 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-719-identifiers-one-door`); built on T-717's branch (PR #332) and so on #326, #317
  and #312: it shows their commits until they merge
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-438 (one reveal path in the console), D-464 (callers per route), D-483 (actor assertion v3)
- **Closes:** finding F3 and proposal TR-8, stage a, of `docs/reviews/2026-11-12-architecture/trust.md` (see
  "Not done" for stages b and c)

## The problem

`POST /setup/pseudonym {"chart_no": ...}` and `POST /registry/{rs}` with `mrn` return the pseudonym of any chart
number to any admitted token, with no person and no audit. Chart numbers are short and often sequential: a loop
over the number space rebuilds pseudonym to chart number for the whole hospital without the pid map, its key, the
reveal cap or one audit event. The pseudonym is only as secret as these two routes. And the code that turns one
into the other is in eight places of the orchestrator.

## The decision

(filled in with the build; see the pull request)
