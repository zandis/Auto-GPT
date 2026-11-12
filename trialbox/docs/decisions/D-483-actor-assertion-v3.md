# D-483 Actor assertion v3: the person, the right and the request in one signed claim, minted in one place and checked by one dependency

- **Card:** T-715 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-715-actor-assertion-v3`); it is built on T-714's branch (PR #312, the `orch_box`
  fixture) and shows that card's commits until it merges
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-143 / D-447 (the signed actor, used once), D-146 (the signed role), D-273 (the signed study
  scope), D-425 (the matrix, `permit`), D-464 (callers per route), D-482 (the real-box fixture)
- **Closes:** finding F2 and proposal TR-3 of `docs/reviews/2026-11-12-architecture/trust.md`, in stages (see
  "Stages")

## The problem

About forty changing routes of the orchestrator take the acting person from the request body (`by`) under any
admitted service token: a subject is enrolled, a study setting saved, a serious adverse event acknowledged under a
name that never signed in, and the audit line is the same as a real one. Six route groups take the person from a
signed assertion (v2), which carries a name, a session, a role and a study list, and nothing about what the person
was allowed to do, to what, or with which request body.

## The decision

(filled in with the build; see the pull request)
