# D-557 A failed job's record and the unhandled-error line keep an error's type, not its text

- **Task:** NEW-TRUST-5 (findings 1, 2, 3, 5 and 6 of NEW-TRUST-3 and NEW-TRUST-4; the integrator's word of
  2026-11-13)
- **PR:** this branch (`agent/NEW-TRUST-5-error-texts-and-records`), on top of NEW-TRUST-3 (#482) and NEW-TRUST-4
  (#484)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-551, D-555, D-556

## The problem

D-555 held the orchestrator's answers. Three more places keep or show an error's own words:

1. **A failed job's record.** An error a job did not expect was kept with 300 characters of its own text
   (`JobError.detail`: in the jobs' JSON and the tools that read it; the job page shows the step and the message). And several of the job errors the scenarios write themselves
   repeated what the sender typed: a CASE request with a chart number of the wrong shape was refused with
   `mrn='<the number>'` in the job's record; a language, a date or a variant that could not be read came back as
   typed; a sender who is not a list recipient was named by address.
2. **The unhandled-error line of the log.** It logged the whole traceback, whose last line is the error's text.
   The log's scrubber knows the shape of a chart number and of a secret, not every value: a database error
   quotes its statement's values, a validation error prints its input, an f-string holds a value of the path.
3. **Two answers**: a notice refused for an outside address named the address; a source that does not exist
   named the value of the path.

## The decision

1. **The job's record keeps the type of an unexpected error** (`RuntimeError`), nothing of its text. The text is
   in the log line of the failure, under the log's rules. The same for an ingest the adapter records as a failure
   it did not expect (a type and up to 500 characters of text: the record keeps the type; the adapter's own
   sentences, "the source folder is empty", "night refused: ...", stay), for an ingest that finished with errors
   (the record says how many and names the published report), and for a step another service did not do: its
   own message when the answer has the shape of one or is a refusal's sentence, else which service and what
   status (never a 5xx's body or a body that is not the service's JSON).
2. **The job errors the scenarios write name only the box's own words.** `StepFailed` and `FeasError` join the
   classes of D-555's test, each with the list of what a text may be built from: the study and its version, the
   job's type, state and ids, a limit, the name of an option (never its value), the name of a file the sender
   attached, a count, another error's type. The chart number, the typed option values (a language, a date, a
   variant and its key, a look-back, a bundle reference, ids that are not ids, a `since`, a `version`) and the
   sender's address are gone from the texts. The test reads the scenarios and the reports now, not only the top
   folder, and the classes made from `StepFailed` with it. An argument that is not an f-string itself is listed
   whole, so a value joined to a text cannot hide behind it.
3. **The unhandled-error line holds the error's type and where it was raised** (`tb_common.http.trace_of`):
   `error` is the type, `trace` the frames (file, line, function, the line of code as written) and the types of
   the errors it came from. Not the text. Every service made by `make_app` has it.
4. **The two answers are fixed sentences.**

## What it does not do

- **An operator loses the text of an error no handler expected** (a refused connection's host, a constraint's
  name, the key of a `KeyError`): the unhandled-error line has the type and the place only. No step of the
  runbook reads that text. A job's failure keeps its text in the log line the job runner writes.
- **The routing table's refusal** ("phi output may not be sent to <address>") is still the text of a job that
  was refused for its recipients (`core._error`): the address is one of the study's own list or the sender's.
- **The problems of an uploaded alliance table or of a TWPAS bundle** are listed in the job error as their
  validators wrote them, which can quote a cell of the uploaded table (aggregate cohort tables, not patient
  rows) and, for a merge, the other senders' addresses.
- **The adapter still writes** the type and 500 characters of an error's text into its own run record and report
  (another lane's service); the orchestrator no longer copies it into the job. Sent to the integrator.

- **The other log lines that carry a traceback** (a `log.exception` written by a module's author, about forty in
  the services) keep the error's text, scrubbed by the log's rules. They are each about one known failure; the
  unhandled-error line is the one that takes any error of any handler.
- **Another error's text inside a job error** stays in the places the test lists one by one (a prompt registry's
  refusal, a cascade that could not run, an approval workbook that could not be read, the routing table's
  refusal, a FHIR validator's first line): errors written in this repository about the study's own files.
- **The names of files a sender attached** stay in job errors: the answer goes to that sender, and the name is
  what tells them which file.
- **The data core's and the REDCap bridge's own error classes** (`SponsorError`, `LifeError`, `DataError`,
  `LinkError`, `RcError`) are another lane's modules. By reading, `SponsorError` repeats up to 40 characters of a
  cell of an uploaded layout and `RcError` up to 200 characters of what REDCap answered. Sent to the integrator.

## What the adversarial review changed

One review by a fresh reviewer, on a copy of the commit, with mutations. Verdict: fix first.

- **An INGEST job's record still kept 500 characters of an error's text**, copied from the adapter's run record,
  and an ingest that finished with errors listed the report's error lines, which can hold an error's text. Both
  are as the decision says now.
- **The sender's address was still there**, inside the routing refusal that the new text went on to quote. The
  text ends before it.
- **Another service's answer** (up to 2,000 characters of its body) became the job error's message. Only a
  service's own message is kept.
- **More typed values**: a look-back, ids that are not ids, a bundle reference, a variant's key, a `since`.
- **The test's rule had two holes**: an f-string anywhere in an argument hid the rest of it, and the three
  classes made from `StepFailed` were not read. Both closed, with a test of the rule itself.
- The trace keeps the last 30 frames of each error and five errors of a chain, so one line stays a line.
- After the first whole-suite run: three tests showed the cut was too wide. The adapter's own sentences and a
  refusal's sentence ("an ingest is already running") are the service's words for the operator and stay; only
  the unexpected failure's text and unshaped bodies are left out.
- **Checked and sound:** no local values in the trace; the text is absent for chained errors, notes and grouped
  errors; nothing parses a job's `error.detail` or the changed messages; the console maps the data source's code
  to its own sentence.

## Reuse check

`traceback` of the standard library formats the frames; the test is D-555's, extended. Nothing is added.

## Dropped (D-311)

No sign-off step.
