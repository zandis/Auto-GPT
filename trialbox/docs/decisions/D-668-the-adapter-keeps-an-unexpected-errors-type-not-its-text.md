# D-668 The adapter keeps an unexpected error's type, not its text

- **Task:** NEW-B-27 (a finding by reading from lane C2's NEW-TRUST-5, D-557; placed by the integrator on
  2026-11-13)
- **PR:** this branch (`agent/NEW-B-27-adapter-record-keeps-no-error-text`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-664 (the lake's answers: the same class), D-520 (a rejected row's key never holds a feed
  value), D-663 (the night's run record, read by the orchestrator), D-557 (answers carry no value)

## Context

When a night failed on an error nobody expected, the adapter kept `Type: text[:500]` in the run record (the
service's thread, the night's own process, and the publish run), and the pipeline put `validation failed to run:
<text>` and `fhir-store load failed: <text>` into the ingest report. The orchestrator reads the run record's
`detail` into the job's error; the report's errors go to the console and the mail.

An unexpected error's text is written by code the adapter does not own: a driver, a parser, the FHIR store's
answer, the standard library. Such a text quotes what it choked on. `could not convert string to float: '...'`
holds a row's value. Confirmed by a test in both forms of the run (thread and process) before the change.

## Decision

1. **One function decides what is kept of a failure outside the log**: `adapter.failure.words(exc, run)`.
2. **The adapter's own sentences stay whole.** The exact classes `SiteKeyError`, `FutureNight`,
   `NothingToPublish`, `RunLockHeld`, `FeedGuardError`, `KeyMissingError`: raised with sentences written in this
   code base that hold dates, snapshot names, file paths and settings. The exact class, never a subclass made
   elsewhere. Sentences that are not exceptions ("an ingest is already running", "night refused: ...", the
   completeness lines) are not touched.
3. **A mapping error keeps its words up to the first value**: `pipeline.reject_key`, the form D-520 decided.
4. **Anything else is its type**, with where the rest is: `ValueError (the error's text is in the adapter's log
   only, it can hold a row's value; run <id>)`.
5. **The text is not lost.** Every place that now keeps the type logs the error with its traceback
   (`log.exception`); two of them (the two "validation failed to run" lines and the two FHIR lines) did not log
   before.
6. **No masking, no cutting of foreign text.** D-664's review showed that a rule that tries to keep the safe part
   of a foreign text leaks. The type is kept; the text is not looked at.

Places changed: `adapter/app.py` (the run in the service's thread; the publish run), `adapter/run_job.py` (the
night's own process), `adapter/pipeline.py` (`validation failed to run`, `JP Core validation failed to run`),
`adapter/publish.py` (`fhir-store load failed`, `fhir-store put-back failed`).

## What this does not do

- `RebuildRefused` ("the lake refused snapshot X: <the lake's answer>") is not in the own list: it carries
  another service's text. It is kept as its type.
- The publish module's `lake rebuild failed: <the lake's words>` lines are left as they are: over HTTP the lake's
  answer is already D-664's. A lake run inside the adapter's process (tests, the CLI) still passes its raw text
  there. Sent to the integrator as a finding.
- The adapter's log holds the full text, as before. Who may read the log is not this card's.

## Tests

`tests/unit/test_adapter_failure_words.py`: six kinds of unexpected error whose text holds a value (with and
without quote marks) keep the type only; each own class stays whole; a mapping error is cut at its first value; a
subclass made elsewhere is not taken for an own class; the run record in the process form and in the thread form;
a refused night keeps its sentence; the report's lines for a validator and a FHIR store that raise.
`tests/unit/test_adapter_run_job_main.py`: the body of the night's process run in the test process (four endings),
so its lines are counted by the coverage gate (they ran only in a child before).
