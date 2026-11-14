# D-707 What a validator said of a patient's bundle stays on that patient's row

- **Task:** NEW-TRUST-10 (from lane E's #520: the FHIR validator's sentences quote values; the integrator's word of
  2026-11-13)
- **PR:** this branch (`agent/NEW-TRUST-10-precheck-issues-stay-on-the-row`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-557 (a failed job's record names no request value), D-273 (who reads a patient's row)

## The trace

The validator's sentences and the pre-check's issues for one patient's TW-PAS bundle quote values of that
patient's resources (a gender code, a date, a decimal). From `orchestrator/scenarios/twpas.py` they go to:

| where | what it is | who reads it | |
| --- | --- | --- | --- |
| `row.precheck.issues` in the NAV list (`nav_xlsx`, "precheck_result") | the patient's own row of a patient-level workbook | the list's recipients | **kept** |
| `twpas_validation_<study>.json` | the NAV run's validation report, published patient-level | the list's recipients | **kept** |
| the error of a SUBMIT job that refused the bundle (`submit._check_validation`) | the job's record | everyone who can open the job's page (an administrator too, who does not read that patient), the Failed mail's text, the audit of the refusal | **reduced** |
| the note of a dry-run SUBMIT ("pre-check did not run: ...") in the job's summary | the job's record and the mail's text | the same | **reduced** |

Nothing else reads them: no console page shows `precheck` outside the workbook, the mail gateway does not, and
no log line writes them.

## The decision

- A SUBMIT that refuses a bundle says in the job's error **how many problems there are and where they are**: the
  validation report of the NAV job, by name. Not the sentences.
- A pre-check that did not run is said without the pre-check engine's own words (which can be an evaluation
  error's diagnostics), in the job's error for a live submission and in the job's summary for a dry run, with
  the same pointer.
- The NAV list and the validation report are unchanged: they are where a reader of that patient's row finds what
  to mend.

## What it does not do

- It does not change the adapter, which keeps the validator's sentences on purpose (lane E's #520).
- The structural-only note ("HL7 validator not installed") is the box's own word and stays.

## Review

One review by a fresh reviewer. Verdict: sound, one wording defect.

- **A pre-check that answers "not passed" with no sentence** made the error say "0 problem(s). They are listed
  ...", which pointed at nothing. That case has its own sentence now (the pre-check gave no reason; its result is
  in the report), by test.
- Checked and sound: the report and the NAV job are always there when the text names them; the sentences are still
  written to the report and to the patient's row, and the count equals the row's; no other text of the submit
  step repeats them; nothing depended on the old text; the change to the list of `test_error_answers` is a
  tightening.
- Left as they are, said here: the list still allows the joined gaps as a whole (the new test, not the reading
  rule, keeps engine words out of them); the count includes every sentence of the pre-check, also one that only
  informs; whether the NAV job's page offers the report to every reader of the list was not checked.

## Reuse check

Nothing is added.

## Dropped (D-311)

No sign-off step.
