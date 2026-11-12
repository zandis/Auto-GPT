# D-540 A new study gets its first approval in the console

- **Task:** NEW-JRN-1 (`docs/plan/33-plan-v7.md` section 5, wave 0, lane C; TB-PLAN-07)
- **PR:** this branch (`agent/NEW-JRN-1-first-approval`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Measures:** closes JRN-001 (Blocker) of `docs/reviews/2026-11-12-deep-review/04-user-journeys.md`
- **Builds on:** D-133 (a study page answers only for a study TrialBox has), D-380 (the steward names the PI; until
  then nobody acts as PI), D-104 (an account limited to its studies), D-147 (only the logged PI approves)

## Context

A new study could not get its first approval through the console. The PI's approval answered 403 until the steward
named the PI (D-380). The steward's delegation page answered 404 until the study was approved, because a study was
"known" only when a ruleset folder existed, and that folder is written at approval. Every test and demo wrote the
PI entry into the database with `TeamStore`, so nothing caught it. A rehearsal on 2026-11-12 saw the rest: the PI's
and the coordinator's accounts are limited to their studies, so the new study was "page does not exist" for both.

## The decision

1. **A study whose criteria wait for approval is a study.** `console.studies.known_study` answers yes for a ruleset
   id that has a job in state `awaiting_approval` (`waiting_studies`, the same job listing as the home page's
   approval queue). The delegation log, the set-up page and the other study pages open for it, under the same role
   and scope rules as for any study. A mistyped code, and a study whose only job was rejected or failed, still get
   the 404 page.
2. **The pages say who must act.**
   - The approval page, while the log names no PI: "Nobody can approve these criteria yet ... the data steward
     names the PI", with the link to the log for the account that may name one.
   - Every page of the account that names a PI (the matrix row `delegation.name_pi`): a task "<study>: name the
     principal investigator" for each waiting study without a PI, with the link. It goes when the PI is named.
   - The delegation log, when no investigator account can open the study: the administrator creates the account or
     adds the study to an account limited to other studies.
   - A request for a study outside an account's own (`POST /pilot/protocol`, `/pilot/request`): 403 "Your account
     is limited to its own studies (...)", not the 404 page. The answer is the same whether the study exists or
     not, so it tells a limited account nothing about other studies.
3. **The journeys go through the pages.** `tests/e2e/journeys/journeys.yaml` has the journey "a new study from
   protocol to first list" as four steps (J-ADM-05, J-STW-05, J-PI-08, J-CRC-08), walked on the in-process box
   with no PI seeded for it. `tools/e2e_simple.py` stage 12 names the new study's PI through the steward's page.
   Seeding the delegation log of the studies a demo ships with (`tools/demo.py`, `tools/feas_demo.py: seed_pi`)
   stays: that is the demo's starting state, not a journey.

## What it does not do

- It adds no right: who may name a PI, approve, start a request or change an account's studies is as before.
- The administrator still adds a new study to the accounts that are limited to studies, by hand, on "Users".
  A page that offers this at the moment the study is made is not built.
- JRN-015 (a) (the banner "Criteria waiting for your approval" shown to accounts that cannot approve) is not
  changed here.

## Dropped (D-311)

No sign-off or owner review step.
