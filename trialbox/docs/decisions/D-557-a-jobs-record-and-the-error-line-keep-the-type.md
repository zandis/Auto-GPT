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
   (`JobError.detail`), and the job page shows it. And several of the job errors the scenarios write themselves
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
   in the log line of the failure, under the log's rules.
2. **The job errors the scenarios write name only the box's own words.** `StepFailed` and `FeasError` join the
   classes of D-555's test, each with the list of what a text may be built from: the study and its version, the
   job's type, state and ids, a limit, the name of an option (never its value), the name of a file the sender
   attached, a count, another error's type. The chart number, the typed option values and the sender's address
   are gone from the texts. The test reads the scenarios and the reports now, not only the top folder.
3. **The unhandled-error line holds the error's type and where it was raised** (`tb_common.http.trace_of`):
   `error` is the type, `trace` the frames (file, line, function, the line of code as written) and the types of
   the errors it came from. Not the text. Every service made by `make_app` has it.
4. **The two answers are fixed sentences.**

## What it does not do

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

## Reuse check

`traceback` of the standard library formats the frames; the test is D-555's, extended. Nothing is added.

## Dropped (D-311)

No sign-off step.
