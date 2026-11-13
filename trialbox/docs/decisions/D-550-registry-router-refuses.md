# D-550 The registry's changing routes take the person from the signed claim and refuse a call without one

- **Task:** T-715b (TB-PLAN-07 wave 2: "T-715 router by router"; the first router after lifecycle and sponsor)
- **PR:** this branch (`agent/T-715b-registry-router-refuses`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-483 (actor assertion v3 and its stages), D-487 (the chart-number door on the registry's route),
  D-464 (callers per route)

## The problem

D-483 left four route groups in stage `report`: a changing call without a verified person was counted and let
through, and the person was the body's `by`. On the real orchestrator in the production trust configuration,
the console's token alone and `"by": "console:dr_tanaka"` set a candidate's status: the answer was 200 and the
row said `updated_by: console:dr_tanaka`. The registry's export and the audit trail then carried that name.

## The decision

1. **The registry group moves to stage `refuse`** (`route_actors.yaml`). `POST /registry/{ruleset}` and
   `POST /registry/{ruleset}/promote` have `require_actor("request.prepare")`: a verified v3 assertion for this
   action, this study, this request and this body, and the matrix asked again. A refusal is 403 with code
   `ACTOR` and one `actor.refused` event.
2. **No field of the request names a person.** The two routes have request models of their own
   (`RegistryUpdateBody`, `RegistryPromoteBody`): the change without `by`, and any field they do not know is
   refused (422), so a typed `by` is not silently dropped. The handler builds the contract's `RegistryUpdate` /
   `RegistryPromote` with `by` = the claim's subject; the contract's own rules (the statuses, the sources, the
   tiers) still decide what is valid.
3. **The study of a registry route is its `{ruleset}`.** `require_actor` reads the study from `{rs}` or
   `{ruleset}`, as the report stage already did.
4. **The console signs both calls** (`console.app`: `request.prepare`, the right its registry page already
   asked) and the backend sends the change without `by` (`registry_update_body`, `registry_promote_body`).
   D-487's door on a row by chart number stays: it now always finds the verified person the stage admitted.
5. **The list of report routes shrinks by two** (`tests/unit/data/actor_report_routes.txt`: 30 left).

## Consequences

- The registry's `updated_by`, its events and its audit records name `console:<username>`, always. Before, the
  console sent the account's mailbox (or user name); a row changed before this card keeps what it has.
- A console of the release before this one gets 403 on the two routes (it fails closed); `trialbox update`
  replaces both images in one step (D-483).
- The demo tool's seeding of the registry signs as the demo's coordinator (`tools/role_demo.py`).
- Tests that pinned the report stage are changed to the stricter rule, each named in the pull request.

## What it does not do

- Study, data core and site set-up stay in stage `report` (30 changing routes): one card per router.
- The registry's export route (`GET .../export.xlsx`) is not a changing route; it keeps its v2 check (D-438).
- A row a person changes by mail or a scenario does not come through these routes.

## Reuse check

Nothing new: the dependency, the stage table and the console's minting place are D-483's.

## Dropped (D-311)

No sign-off step.
