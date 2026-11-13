# D-549 Typed text is never a formula in a file the console hands to a person

- **Task:** NEW-CSV-1 (a finding from the review of lane E's #445, older than that card; given to lane C by the
  integrator on 2026-11-13)
- **PR:** this branch (`agent/NEW-CSV-1-formula-guard-on-console-exports`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** T-510 (the in-product feedback and its export), D-387 (the screening log), the registry export

## The problem

A spreadsheet runs a cell that begins with `=`, `+`, `-` or `@` as a formula (CWE-1236). The audit report and
the copy-assist sheet wrote such a cell with a leading quote. The feedback export did not: a tester's comment
`=1+1` was a live formula in the file a staff member opens (confirmed by running the export on unchanged code:
the cells came back `=1+1`, `+1+1`, `-1+1`, `@SUM(A1)`). And the workbooks the console hands out (the
screening log in three forms, the registry export) stored any text that begins with `=` as a formula: the
library does that with a typed reason.

## The decision

1. **One guard, two forms** (`libs/tb_common/sheets.py`). `csv_cell(value)`: a cell that begins with `=`, `+`,
   `-`, `@`, a tab or a carriage return is written with a leading quote. `no_formulas(workbook)`: every formula
   cell of a workbook becomes a text cell with the same characters; called once, just before the save.
2. **The feedback export** passes every cell through `csv_cell`.
3. **The screening log's workbooks, the registry export, the enrolment report and the EDC data workbook** call
   `no_formulas` before each save. They hold no formula of their own, so none is lost. The enrolment report's
   CSV passes its text cells through `csv_cell`.
4. **A new maker of a workbook must be named.** `tests/unit/test_formula_guard.py` lists every module of
   `services/` that makes a workbook: guarded here, or outside this card. A new one fails the test until it is
   put on one of the two lists.

## What it does not do

- **The audit report and the copy-assist sheet keep their own guard** (the same rule, written twice before this
  card). Moving them onto the shared one changes no byte and can follow.
- **Not judged here, only listed** (by reading, not by running; reported to the integrator): the data core's
  REDCap CSV (`datacore/export.py: redcap_csv`: a REDCap import reads that file, so a leading quote would change
  data: lane E's decision), `datacore/forms.py` and `sources.py`, the cohort CSV
  (`orchestrator/scenarios/cohort.py`: ids, counts and ruleset text), the orchestrator's report workbooks and
  the criteria review workbook (job outputs the console serves), site set-up's templates.
- **In a workbook a text that begins with `+`, `-` or `@` was a text cell already**; a spreadsheet does not run a
  text cell. In the CSV the leading quote is in the file: a program that reads the export sees it on such a cell.

## What the adversarial review changed

One review by a fresh reviewer; verdict: merge, no HIGH. It opened the files in a spreadsheet program
(LibreOffice): a guarded workbook shows `=1+1` as text where an unguarded one shows `2`; a delimiter or a quote
in a comment cannot break out of its cell; a later line of a cell that begins with `=` stays text.

- **Two more files the console serves had the same defect** and are guarded now: the enrolment report (CSV and
  workbook: a withdrawal's reason is typed) and the EDC data workbook (`datacore/export.py: xlsx`, one line in
  lane E's file, named in the pull request). Test first.
- **`csv_cell` looked at the first character only.** It now looks past blanks and invisible characters and
  reads a full-width sign as its plain form (a Japanese or Chinese keyboard types `＝`; whether Excel runs it on
  opening a CSV was not tested, so it is quoted).
- **The test that names every maker saw no CSV.** A second test holds every console module that writes a CSV
  to the shared cell (or to its own older rule, by name).
- **Left as limits:** the check that each save is guarded counts calls in the file's text; it does not follow
  which workbook is saved. A text that begins with `-`, `+` or `@` (a comment that opens with a dash) shows its
  leading quote in the CSV; no numeric column of the feedback export is affected.

## Reuse check

`defusedcsv` does the CSV half (a drop-in `csv` that escapes these cells); it is one more dependency for six
lines, and it does nothing for a workbook. Not added; say if it is wanted.

## Dropped (D-311)

No sign-off step.
