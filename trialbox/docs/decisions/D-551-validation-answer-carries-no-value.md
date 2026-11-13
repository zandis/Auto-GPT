# D-551 A service's answer to a request of the wrong shape carries no value of that request

- **Task:** NEW-TRUST-2 (a finding of the review of T-715b, #459, older than that card; the integrator's word of
  2026-11-13)
- **PR:** this branch (`agent/NEW-TRUST-2-422-carries-no-value`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-147 / D-273 (a chart number is never kept, logged or given back), D-125 (the console's API)

## The problem

When a request does not fit its route's model, the web framework answers 422 and repeats what was sent, field by
field (`"input": ...`). A registry change with a chart number and a missing field came back with the chart number
in the answer. The orchestrator writes only the path and the status to its log, but the caller has the text, and a
client that logs a refusal logs the chart number with it. The console's API did the same to its own callers.

## The decision

1. **One answer** (`tb_common.http.validation_answer`): for each problem, its `type`, its place (`loc`) and its
   message (`msg`). No `input`, no `ctx` (which can hold the value), no link.
2. **Every service app has it.** `tb_common.http.make_app` sets it, so every internal service does; the console,
   which builds its own app, ends its own handler with it (`console.api_first`).
3. **A test holds the list of apps**: a service that builds its own app must be named there.

## What it does not do

- **A message can still name a value when our own code puts one there** (a rule written in a model that says
  "x is not ..."). The framework's own messages name the rule, not the value; the test's model shows the way to
  write one.
- **The REDCap simulator** (a test stand-in, `services/rc_sim`) keeps the framework's answer.
- A caller that read `input` from a 422 answer would lose it; nothing in the repository does.

## Reuse check

The framework's own hook for this answer (an exception handler) is what is used; no library is added.

## Dropped (D-311)

No sign-off step.
