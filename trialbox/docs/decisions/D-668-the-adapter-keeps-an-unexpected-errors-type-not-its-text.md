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
4. **Anything else is its type**: `ValueError (the error's text is not kept, it can hold a row's value; the
   adapter's log has where it failed; run <id>)`.
5. **The log gets the type and the frames, not the text** (`failure.log_failure`: file, line and function of each
   frame). "No feed value in a log" is the data-handling rule D-520 builds on, and the log line of an unexpected
   failure broke it before this card at three places (`log.exception` in the run's thread, the night's process
   and the publish run). The same form as the lake's build log (D-664). The four report lines (validation, JP
   Core, FHIR load, FHIR put-back) and the back-fill's validation line did not log at all; they now log this way.
6. **No masking, no cutting of foreign text.** D-664's review showed that a rule that tries to keep the safe part
   of a foreign text leaks. The type is kept; the text is not looked at. `words` and `log_failure` never raise.
7. **The JP Core check's "base R4" message is the element and the kind of problem** (pydantic's `loc` and `type`),
   not pydantic's message lines, which quote the value (`input_value='...'`). That message reached the report's
   `errors` and `profile_validation.messages`.

Places changed: `adapter/app.py` (the run in the service's thread; the publish run), `adapter/run_job.py` (the
night's own process), `adapter/pipeline.py` (`validation failed to run`, `JP Core validation failed to run`),
`adapter/publish.py` (`fhir-store load failed`, `fhir-store put-back failed`), `adapter/backfill.py` (`validation
failed to run`), `adapter/validate/jpcore.py` (`base R4: ...`).

## What this does not do

- **The lake's words in the adapter's lines are left as they are**: `lake rebuild failed: <the lake's words>`
  (`publish.py`, `backfill.py`) and `RebuildRefused` ("the lake refused snapshot X: <the lake's answer>", kept
  whole on that path). Over HTTP (`TB_ADAPTER_LAKE=http`, what the deploy sets) the lake's answer is D-664's.
  With `TB_ADAPTER_LAKE=local` (a declared setting; tests and the CLI use it) the lake runs in the adapter's
  process and its raw text passes. The remedy is D-664's `error_answer` at those lines, which is not on this
  card's base yet. Sent to the integrator as a follow-up.
- `omop.error` in the report keeps an `OmopError`'s text (the OMOP writer's own sentences; none read holds a row's
  value). Not changed.
- Whether the HL7 validator's diagnostics in `validation.messages` quote values was not checked here. Sent to the
  integrator as a finding.

## Tests

`tests/unit/test_adapter_failure_words.py`: six kinds of unexpected error whose text holds a value (with and
without quote marks) keep the type only; each own class stays whole; a mapping error is cut at its first value; a
subclass of an own class made elsewhere is not taken for it; `words` never raises; the log line holds the type and
the frames and never the text; the run record and the log in the process form and in the thread form; a refused
night keeps its sentence; the report's lines for a validator and a FHIR store that raise; the back-fill's line;
the JP Core base message names the element and never the value.
`tests/unit/test_adapter_run_job_main.py`: the body of the night's process run in the test process (four endings),
so its lines are counted by the coverage gate (they ran only in a child before).
