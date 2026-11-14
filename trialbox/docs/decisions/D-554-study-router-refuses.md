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

## What the adversarial review changed

One review by a fresh reviewer, with six mutations of the change (a dropped dependency, the wrong action, a body
that keeps `by`, three unsigned console call sites), each caught by a test. Verdict: fix first; no way in was
found.

- Two lint errors of the first commit (an import out of order, a fixture taken by name) are fixed.
- The read no longer asks `person_of` for the person of the derived steps: the dependency has already verified
  the same action, study and principal, so it is the claim's person.
- `console.s28.save` takes the body that was signed and sends that body, instead of building it a second time.
- A leftover list and an over-wide docstring of the new test are gone.
- **Checked and sound:** only the console may call the group (`route_callers.yaml`); no tool calls these routes;
  the notice timer, which holds `study.setup` for another route, is refused here (only the read admits a
  principal); a claim with a study is refused on a connection route and a claim with none on a study's; no
  refusal carries a value of the request.

## Open with the owner

- **Closed by D-701 (T-715e): the owner decided 2026-11-13 that it is the administrator's alone; the routes ask
  the row `redcap.connection`.** As it stood: who may write the box's REDCap token at the orchestrator. The console's page for it is the administrator's
  alone (D-146, review J-05). The route asks `site.setup`, which the matrix gives the administrator and the
  coordinator, so the orchestrator is wider than the page. Nothing reaches it today (only the console signs, and
  both call sites are behind the administrator check), but a later console path that signs `site.setup` for a
  coordinator could rewrite the token every linked study reads through. Making it the administrator's alone is a
  new row of the matrix, which is the owner's to decide; this card does not add one.
- Until D-551 (#467) is on the same base, the framework's 422 for an unknown field repeats that field's value to
  the signed caller. D-551 removes it for every service.
- The link test is gated on the page by `can_request` and signed for `study.setup`; today no role has one
  without the other on a study's page.

## Reuse check

`orchestrator.actor.require_actor`, `console.actor.call` and `tests.actor3.SignedClient` are the ones the
earlier routers use; nothing is added. The two tests that used `PUT /studies/{rs}/settings` as their example of
a reporting route now use `POST /studies/{rs}/forms/builtin`, which is still in that stage.

## Dropped (D-311)

No sign-off step.
