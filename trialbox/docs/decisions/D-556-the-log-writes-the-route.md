# D-556 A service's log writes the route, not the path that was sent

- **Task:** NEW-TRUST-4 (a finding of the review of NEW-TRUST-2, #467; the integrator's word of 2026-11-13)
- **PR:** this branch (`agent/NEW-TRUST-4-access-log-writes-the-route`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-551, D-555 (an answer carries no value of the request), D-147 / D-273 (a chart number is never
  kept, logged or given back)

## The problem

Every service made by `tb_common.http.make_app` writes one line per request, and the line held the path as it was
sent. A path carries what the caller put in it. On the orchestrator these routes have a value in the path:

- a record of a study (a screening number): `/studies/{rs}/records/{record}`, `/data/{record}`,
  `/entry/{record}`, `/subjects/{record}` with its `step` and `undo`, `/edc/trail/{record}`,
  `/aes/{record}/{event}/ack`;
- a job: `/jobs/{job_id}` and its `cancel`, `retry`, `reveal`;
- a name the caller chose: `/registry/{ruleset}`, `/rulesets/{ruleset}`, `/redcap/connections/{ref}`,
  `/setup/{ws}/...`, `/studies/{rs}/sync/{name}`, `/export/{fmt}`.

None of them is a chart number or a pseudonym by design. But a path is free text until its route has judged it: a
chart number typed where a record or a ruleset id belongs was written to the log before anything refused it, and
so was every path of no route at all (a 404). The line of an unhandled error held the same path.

## The decision

The request line and the unhandled-error line hold **the route's template** (`/studies/{rs}/records/{record}`),
with the method, the status and the time as before (`tb_common.http.route_of`).

- A request that reached its handler has its route in the scope. One that was answered earlier (a refused token,
  a method the route does not take) is matched against the app's routes.
- A router included under a fixed prefix keeps its own path, so the prefix is put back from the path that was
  sent, but only when it holds no value of a path parameter.
- A path that matches no route is written `(no route)`.

The field keeps its name (`path`), so whoever reads the log by that field reads a route there.

## What it does not do

- **The traceback of an unhandled error is still logged whole** and can hold a value: an error's own text
  (`no row for <what>`), a database error that quotes its statement's values, a validation error that prints its
  input. By reading, a chart number can be in such a line today wherever a handler lets an error through that was
  made with one. Finding for the integrator, not changed here.
- **The audit trail's `console.denied` and the older `actor.refused` events keep the first 80 characters of the
  path** in their detail (about twenty places in the console, one in the orchestrator). The audit trail is not
  the log and may hold a screening number; whether it should hold a typed path is a finding, not changed here.
- The console builds its own app and writes no request line of its own.

## Reuse check

The framework's own route matching (`starlette.routing`) tells the route; nothing is added.

## Dropped (D-311)

No sign-off step.
