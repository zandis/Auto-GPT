# D-701 Writing the box's REDCap connection and its key is the administrator's alone, at the orchestrator too

- **Task:** T-715e (the question D-554 left open with the owner)
- **PR:** this branch (`agent/T-715e-redcap-connection-admin-only`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Decided by:** the owner, 2026-11-13 ("all as your advice", on the integrator's advice of the administrator-only
  row; relayed by the integrator)
- **Builds on:** D-554 (the study router refuses a call without a verified person), D-146 review J-05 (the
  console's REDCap connection page is the administrator's), D-366 / D-380 (the permission matrix)

## The problem

D-554 made the two routes of the box's REDCap connections (`PUT /redcap/connections/{ref}` and its `/test`) take
a verified person. They have no study, so they asked the site's row of the matrix, `site.setup`, which the
administrator and the coordinator hold. The console's page for the connection is the administrator's alone. So the
orchestrator was wider than the page: nothing reached it (only the console signs, behind the administrator
check), but a later console path that signed `site.setup` for a coordinator could have rewritten the key every
linked study reads through.

## The decision

A row of its own in the permission matrix, **`redcap.connection`: the administrator, nobody else**. Both routes
ask it; the console signs its two calls for it. A coordinator's claim, signed for the very request, is refused by
the matrix ("right"); a claim for `site.setup` is refused as another action.

The role descriptions on the accounts page say it in three languages (`roles.right.redcap.connection`).

## What it does not do

- `site.setup` is unchanged: the site's set-up and site facts stay the administrator's and the coordinator's.
- A study's own REDCap link (`PUT /studies/{rs}/redcap-link`) stays `study.setup`: the coordinator links a study
  to a project through a connection the administrator made.
- Reading the connections' names (`GET /redcap/connections`) is not a changing route and is as before.

## Review

No reviewer was asked: one row of the matrix, one action name on two routes and two call sites, each held by a
test on the real orchestrator (a coordinator refused, the old action refused, the administrator accepted). Said
here so the integrator can ask for one.

## Reuse check

The matrix and `require_actor`, as D-554; nothing is added.

## Dropped (D-311)

No sign-off step.
