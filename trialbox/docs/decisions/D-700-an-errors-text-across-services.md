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
  rebuild that broke is the engine's error, type and text, in the publish's answer and in its stored record.
- **The rejection of a mailed request whose subject cannot be read** repeated the typed command, job id, ruleset,
  option and value, in the reply and in the mail gateway's record of it.
- **A cascade run of the console that broke** kept 500 characters of the error's text for its page.

## The decision

1. **One rule for a failure another service recorded** (`tb_common.http.kept_failure`): a service's own sentence
   is kept ("the source folder is empty", "night refused: ..."); a record that starts with one name and a colon
   (`ConversionException: ...`, `error: ...`, `_Refused: ...`) is a failure it did not expect, written as the
   error's type and the error's own text, and only the name is kept in a record a person reads. The
   orchestrator's ingest job (D-557) and the site set-up's publish use it, on writing and on reading a record
   kept before this card.
2. **A cascade run that broke keeps the error's type**, also when an older run's record is read; the log line
   holds the type and where it was raised, as the unhandled-error line does (D-557), not the text.
3. **A subject that cannot be read is refused by its rule**, without what was typed; an option's name is said
   only once it is one of the allowed names.
4. **A test reads every service** (`tests/unit/test_error_text_across_services.py`): a statement inside
   `except <a general error> as e` that takes the error's text, outside a log call, must be in a listed file.
   - **This lane's places** (the console, the orchestrator, the site set-up) are listed by file, the errors
     caught and the number of statements, each with what it is, and the list is exact: a place made type-only
     leaves it, a new statement fails, also in a file that is already listed.
   - **Other lanes' files** are listed by service, not judged here, and may only leave the list (a new file
     fails; a file that is gone from the findings does not, so that the lake's own card can land in any order).

## Kept, with the reason

- **"Cancelled by <address>"** in a cancelled job's record (`orchestrator/core.py`): the address of the signed-in
  person who cancelled, in that job's own record, shown to the roles that see the job; the audit trail holds the
  same person. It is who did it, not something that was typed.
- **The mail gateway's "<sender> is not permitted to send ..."**: the reply goes to that sender, with their own
  address.

## What it does not do

- **Spellings the reading does not see**: an error handed whole to a helper (`lake_error(..., exc)`,
  `NotSent(exc)`), `"%s" % e`, a formatted traceback, an error's own `message` field. No service puts a
  formatted traceback or a `%`-formatted error into an answer today.
- **Errors that are not general by name** (a library's own classes): by reading, three places use such a text
  (the lake's SQL guard quotes the caller's own SQL, the adapter's CSV reader, the migration tool's stderr).
- **`services/channels/grammar.py`** repeats a typed token in its refusal the way the subject parser did
  (another lane's; sent to the integrator).

- It changes no other lane's service. The listed files, by reading: the adapter (its run record, the ingest
  report's lines, a publish's record, two validators, a backfill, two feed readers), the lake (two files, taken
  off by D-664), the mail gateway (three), the model services (four), the matching's proposals (one), the trace
  store (one). Sent to the integrator with this card.
- An error class written in a service for its own refusals is not a general error and is not read by this test
  (the orchestrator's are held by D-555's test).
- The rule recognises the shape `"<ErrorType>: "` by the type's spelling (a name with a capital and a lower-case
  letter, with or without a module path). A service's sentence that starts the same way ("Refused: ...") would
  be cut to its first word: it fails safe.

## What the adversarial review changed

One review by a fresh reviewer, with mutations. Verdict: fix first.

- **The first pattern was weaker than the one it replaced**: a type whose name has no capital (`error`, as zlib,
  struct and re raise; `gaierror`) or starts with an underscore passed its text through. Any single name before
  the colon is a type now; every sentence a service writes of its own was checked against it (none starts with
  one word and a colon).
- **The list was exact by file only**, and the console's largest file has one listed place: a second statement
  there passed. It is exact by file, error and count.
- **The cascade's new log line carried the error's text** (a full traceback). It uses D-557's text-free line.
- A record kept before this card is reduced when it is read (the publish's, a cascade run's).
- **Checked and sound:** the raise-through of the site set-up's publish ends in the shared handler's "internal
  error" with the text-free log line; the publish's audit event holds no text; `run.error` is used by one
  template only.

## Reuse check

D-555's reading helpers are reused by the new test; nothing is added.

## Dropped (D-311)

No sign-off step.
