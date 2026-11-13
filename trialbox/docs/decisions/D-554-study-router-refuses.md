# D-554 The study router's changing routes refuse a call without a verified person

- **Task:** T-715d (the fourth router of T-715; the integrator's word of 2026-11-13)
- **PR:** this branch (`agent/T-715d-study-router-refuses`), stacked on T-715b (#459) and T-715c
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-483 (the acting person of a changing route, and the two stages), D-550 (the registry router,
  the same move), D-366 / D-380 (the permission matrix)

## The problem

The study router was in stage `report`: a changing call without a verified person was counted and logged, and
let through, and the person of the record was the body's `by`. Any caller the route gate admits (a service
token) could save a study's settings, its screening scope or its REDCap link, or write the box's REDCap
connection and its token, under a typed name — and the audit trail showed that name as the actor.

## The decision

The group `study` moves to stage `refuse` (`route_actors.yaml`). Its seven changing routes take the verified
person of the call and no field of any body names a person:

| route | action |
| --- | --- |
| `PUT /studies/{rs}/settings` | `study.setup` |
| `PUT /studies/{rs}/screen-scope` | `study.setup` |
| `PUT /studies/{rs}/redcap-link` | `study.setup` |
| `POST /studies/{rs}/redcap-link/test` | `study.setup` |
| `PUT /redcap/connections/{ref}` | `site.setup` |
| `POST /redcap/connections/{ref}/test` | `site.setup` |
| `POST /studies/{rs}/redcap-read` | `request.prepare` (a service principal too) |

- **A REDCap connection is the box's, not one study's.** Its path names no study, so the claim names none
  (`study: ""`) and asks the site's own row of the matrix (`site.setup`, the admin or a coordinator). A claim
  that names a study is refused on those two routes, and a claim that names none is refused on the study's.
- **The read keeps `request.prepare`** and keeps admitting the console's nightly timer
  (`service:console-nightly`, which `route_actors.yaml` already lists for that action): the steps the read
  derives name the verified person or the timer, as D-483 set out.
- **Every body forbids a field it does not know** (`extra="forbid"`): a typed `by` is refused, not ignored,
  because the body is signed.
- The console signs all seven at their call sites (`console.actor.call` / `assert_for`), including the settings
  save, whose helper (`console.s28.save`) now takes the header and whose body no longer carries a name.
- The GET routes of the router need no stage dependency: the report stage counts changing calls only.

## What it does not do

- The matrix is unchanged: the roles that could save a study's set-up before can still save it.
- `datacore` and `setup` stay in `report`; they are the two groups left (and the registry's own card is #459).
- The orchestrator still does not read an account's role from the console's database: the claim carries it, as
  D-483 decided.

## Reuse check

`orchestrator.actor.require_actor`, `console.actor.call` and `tests.actor3.SignedClient` are the ones the
earlier routers use; nothing is added. The two tests that used `PUT /studies/{rs}/settings` as their example of
a reporting route now use `POST /studies/{rs}/forms/builtin`, which is still in that stage.

## Dropped (D-311)

No sign-off step.
