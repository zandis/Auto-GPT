# D-534 The limits lint lists every fixed wait, not only those above a minute

- **Task:** NEW-B-12 (T-687's wave 1 row of plan v7: "its lint covers every timeout and `LIMIT`, not only those
  above 60 s"; PERF-002, PLAN-012)
- **PR:** this branch (`agent/NEW-B-12-limits-lint-every-timeout`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-471 (T-687: the limits lint and its allow-list), OD-10

## Context

The limits lint (`tools/limits_lint.py`) lists every fixed `LIMIT` / `limit=` in `services/`, whatever its number,
and every fixed `timeout=` **above 60 seconds**. The floor was the first card's line: "a wait of a minute or less
is a call, not work that grows with the hospital". That is a guess about each of them, and nobody had looked: a
45 s limit around a model call, a 60 s limit around a call to the adapter, a 10 s limit around a list that may
grow were all invisible to the lint, and a new one could be added without a word.

## Decision

1. **No floor.** Every `timeout=<number>`, every parameter named `timeout` (or `*_timeout`) with a number as its
   default and every `Timeout(<number>, ...)` in `services/` is listed, whatever the number (0 or less is "do not
   wait", not a limit).
2. **The 19 waits of a minute or less that exist today are on the allow-list**, each read and given its reason:
   all are one call whose size does not grow with the hospital (a page for the console, a health answer, one SMTP
   session, one request that starts a job which is then followed) or a wait of the box's own threads. None was
   found to be a cut. The list says so line by line ("not a cut"), as it does for the `LIMIT 1` reads.
3. **A new short wait fails the lint** until it has a line with a reason, like any other limit.

## Consequences

- `tools/limits_allow.yaml` grows by 19 lines (20 literals); the lint counts 102 literals in `services/`.
- A card that adds a `timeout=` of any length adds its line in the same pull request.

## Not decided here

- Waits outside `services/` (`libs/`, `tools/`): the lint's tree is unchanged.
- Limits that are not written as `timeout=` or `LIMIT` (a `range(n)`, a slice, a `time.sleep` in a loop with a
  fixed count): the lint does not see them. The scale gate does, when they bite.
