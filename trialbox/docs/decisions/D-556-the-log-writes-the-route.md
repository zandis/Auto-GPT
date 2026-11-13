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

- **Nothing is built from the path that was sent.** The template is the framework's own: the route's path, and
  for a route of an included router the full template with the prefix it was included under (the framework keeps
  it beside the route while it handles the request).
- A request that was answered before its handler (a refused token, the route gate, a method the route does not
  take) is matched against the app's routes, the routes of included routers too; the route that takes the method
  is named before one that only fits the path.
- A mounted application is named by its mount's path when that is a fixed one, else `(mount)`.
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

## What the adversarial review changed

One review by a fresh reviewer, with experiments on small apps and on the real orchestrator. Verdict: fix first.

- **A refused request to a route of an included router was written `(no route)`** (95 method and route pairs of
  the orchestrator: the set-up, the EDC, the REDCap connections), the same as a scan of paths that do not exist:
  the lines an operator reads after an incident. They are matched now.
- **The first version put a router's prefix back from the path that was sent**, guarded by a comparison of
  values. A parameter of the prefix that is spelled otherwise once converted (a number, a UUID in capitals)
  passed the guard and came back in the line; and one route's name changed with the value sent. No service has
  such a prefix today, but the function is the shared one. Nothing is taken from the sent path any more.
- The route that takes the method is preferred over one that only fits the path.
- Tests for each: a refused token on a route of the app and of an included router, prefixes with a float, a UUID
  and a text parameter, a mounted application, two routes that fit one path.
- **Checked and sound:** nobody reads the field (no tool, check or test parses the log's `path`); the query
  string is not logged; no other line of the two middlewares holds the path.
- The names the framework keeps the full template under are private ones; the test of an included route pins
  them, so an upgrade that moves them fails there and not in the log.

## Reuse check

The framework's own route matching (`starlette.routing`) tells the route; nothing is added.

## Dropped (D-311)

No sign-off step.
