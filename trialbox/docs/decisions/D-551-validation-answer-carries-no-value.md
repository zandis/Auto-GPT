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
   - **The place names only what the route declares**: a parameter, a field of its models (any depth, by name or
     alias), a position in a list. Anything else is written `*`: an extra key on a model that forbids one, a key
     of a mapping. That text is the caller's.
   - **No message text for the error types whose text is written by a rule's author or names what was sent**
     (`value_error`, `assertion_error`, the two tag errors of a tagged union): the answer says "the value was
     refused by a rule of this field". The framework's other messages name the rule or the allowed values.
2. **Every service app has it.** `tb_common.http.make_app` sets it, so every internal service does; the console,
   which builds its own app, ends its own handler with it (`console.api_first`).
3. **A test holds the list of apps**: a service that builds its own app must be named there.

## What it does not do

- **A rule's own words no longer reach the caller of a 422.** A model's rule that says something useful
  ("give the pseudonym or the chart number, not both") is answered with the fixed sentence instead. Routes that
  want to say more raise their own error, as the registry's do.
- **The REDCap simulator** (a test stand-in, `services/rc_sim`) keeps the framework's answer.
- A caller that read `input` from a 422 answer would lose it; nothing in the repository does.

## What the adversarial review changed

One review by a fresh reviewer, with runs on a small app and on the real orchestrator. Verdict: fix first.

- **A key the caller chose came back in the place** (`{"A1234567": 1}` on a contract that forbids extra fields:
  `loc: ["body", "A1234567"]`; a key of a mapping likewise). And three error types put the value in the message.
  The first version of this record said the framework's messages never do; that was wrong. Both are closed as
  written above, with the cases in the test.
- **The test of the apps** now reads a call however it is spaced, sees `Starlette(` too, and asks the
  orchestrator's app for its installed handler.
- **Outside this card, reported to the integrator (by reading):** error answers built from an exception's own
  text (`HTTPException(detail=str(exc))` in the orchestrator, the lake, the trace store and others: the lake's
  database errors can quote a value); the access log writes the path, so a value in a path parameter is logged;
  an unhandled error's traceback is logged with what it holds; the test bench's own app (a tool) keeps the
  framework's answer.

## Reuse check

The framework's own hook for this answer (an exception handler) is what is used; no library is added.

## Dropped (D-311)

No sign-off step.
