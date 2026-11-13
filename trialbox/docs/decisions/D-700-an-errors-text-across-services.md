# D-700 Across every service, an error nobody wrote is used by its text only in the listed places

- **Task:** NEW-TRUST-6 (the three places left by the lake's error-answer card, #488 / D-664; the integrator's word
  of 2026-11-13)
- **PR:** this branch (`agent/NEW-TRUST-6-error-text-across-services`), on top of NEW-TRUST-5 (#492)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-555, D-557 (the orchestrator's answers and job records), D-664 (the lake's)

## The problem

D-555 and D-557 hold the orchestrator; D-664 the lake. The same fault can sit in any service: a general error
(`Exception`, `ValueError`, `KeyError`, a file or OS error) is caught and its text goes into an answer, a stored
record or a report. Nothing read the other services for it. Two places were in this lane and still open:

- **A failed publish of the site set-up** kept 300 characters of the lake's record of the rebuild, which for a
  rebuild that broke is the engine's error, type and text, and the publish page showed it.
- **A cascade run of the console that broke** kept 500 characters of the error's text for its page.

## The decision

1. **One rule for a failure another service recorded** (`tb_common.http.kept_failure`): a service's own sentence
   is kept ("the source folder is empty", "night refused: ..."); a record of the shape `"<ErrorType>: <text>"`
   is a failure it did not expect, and only the type is kept in a record a person reads. The orchestrator's
   ingest job (D-557) and the site set-up's publish use it.
2. **A cascade run that broke keeps the error's type**; the text is in the console's log.
3. **A test reads every service** (`tests/unit/test_error_text_across_services.py`): a statement inside
   `except <a general error> as e` that takes the error's text, outside a log call, must be in a listed file.
   - **This lane's files** (the console, the orchestrator, the site set-up) are listed one by one with what each
     is, and the list is exact: a place made type-only leaves it, a new place fails.
   - **Other lanes' files** are listed by service, not judged here, and may only leave the list (a new file
     fails; a file that is gone from the findings does not, so that the lake's own card can land in any order).

## What it does not do

- It changes no other lane's service. The listed files, by reading: the adapter (its run record, the ingest
  report's lines, a publish's record, two validators, a backfill, two feed readers), the lake (two files, taken
  off by D-664), the mail gateway (three), the model services (four), the matching's proposals (one), the trace
  store (one). Sent to the integrator with this card.
- An error class written in a service for its own refusals is not a general error and is not read by this test
  (the orchestrator's are held by D-555's test).
- The rule recognises the shape `"<ErrorType>: "` by the type's spelling (a name with a capital and a lower-case
  letter, with or without a module path). A service's sentence that starts the same way ("Refused: ...") would
  be cut to its first word: it fails safe.

## Reuse check

D-555's reading helpers are reused by the new test; nothing is added.

## Dropped (D-311)

No sign-off step.
