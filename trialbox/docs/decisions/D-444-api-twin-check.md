# D-444 API twin check: the API checks the session and the permit before the body; every page action has an `/api/v1` twin or a reason

- **Task:** T-657 (`docs/plan/28-master-plan-v6.md` §6.2)
- **PR:** this branch (`agent/T-657-api-twin-check`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** ROLE-019, ROLE-020; FIT-019 in part (the check and its list; the missing twins are a follow-up card)
- **Builds on:** D-125 (every screen action through a documented token API), D-146 (the API refuses what the page
  refuses), D-366 (role x route matrix), D-425 (every call site asks `permit`)

## Decision

1. **Session first, on every state-changing `/api/v1` route.** The console's router builds its routes with
   `console.api_first.GuardedRoute`. A POST, PUT, PATCH or DELETE under `/api/v1/` gets a first dependency that signs
   the bearer token in (`Helpers.api_session`: 401, the must-change refusal, the D-146 scope check) before FastAPI
   validates the body. An anonymous call answers 401, never 422 with the body's schema (ROLE-019). Only the
   session's own routes (`POST` and `DELETE /api/v1/session`) are left open, each with its reason in
   `api_first.SESSION_OPEN`. A body that is not JSON at all fails before any dependency; the validation-error handler
   runs the same guard first for these routes.
2. **The permit that does not need the body, before the body.** Each such route declares, with
   `@before_body(check)`, the module's own guard (study visible, the role's `permit` row, the delegation task) as it
   stands at the top of the handler. Where the exact row depends on the body (EDC switch on or off; a mark that
   needs `task.approach` or `task.screen`), the check refuses an account that holds none of the possible rows; the
   handler still asks the exact row. No answer becomes more permissive than the handler's `permit` call: the check
   only refuses earlier. A route that takes a body must declare it (test).
3. **The matrix records the real answer.** With 1 and 2, the role x route walk's empty body `{}` reaches the guard
   first, so the API rows show the role's real answer instead of `Y` for every role. The table was regenerated.
4. **Twin check.** `tests/console/test_api_twin_check.py` walks the app's route table: every state-changing page
   route has an `/api/v1` route with the same path under `/api/v1` (any changing method), or one that names it with
   `@page_twin(path)`, or is listed with a reason. Two lists: `EXEMPT` (page-only by design, short, permanent) and
   `NO_TWIN_YET` (the FIT-019 gap as found today, to be closed by follow-up cards; the list may only shrink: an
   entry that gains a twin or no longer exists fails the test, and its length has a ceiling). A new page action
   with neither a twin nor a line fails.
5. **A study outside the account's scope is 404 (ROLE-020).** On `/site` pages and `/api/v1/site/*`, a
   study-scoped account that names a study it does not see gets 404, not its own study's data silently.

## Open

- The `NO_TWIN_YET` routes have no API yet (FIT-019: delegation log, staff, not-matched review, SAE register, sheets,
  schedule undo, flags, users and others). Each needs its twin or a reason to move to `EXEMPT`.
