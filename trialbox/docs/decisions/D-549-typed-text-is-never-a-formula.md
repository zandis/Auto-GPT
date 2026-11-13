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
3. **The screening log's workbooks and the registry export** call `no_formulas` before each save. They hold no
   formula of their own, so none is lost.
4. **A new maker of a workbook must be named.** `tests/unit/test_formula_guard.py` lists every module of
   `services/` that makes a workbook: guarded here, or outside this card. A new one fails the test until it is
   put on one of the two lists.

## What it does not do

- **The audit report and the copy-assist sheet keep their own guard** (the same rule, written twice before this
  card). Moving them onto the shared one changes no byte and can follow.
- **Files made outside the console and the registry are not judged here**, only listed (by reading, not by
  running): the data core's exports (`datacore/export.py`, `forms.py`, `sources.py`: typed EDC values), the
  enrolment report (`orchestrator/lifecycle_api.py`, CSV and workbook), the cohort CSV
  (`orchestrator/scenarios/cohort.py`), the orchestrator's report workbooks, the criteria review workbook, site
  set-up's files. Reported to the integrator; the data core's are lane E's.
- **In a workbook a text that begins with `+`, `-` or `@` was a text cell already**; a spreadsheet does not run a
  text cell. In the CSV the leading quote is in the file: a program that reads the export sees it on such a cell.

## Reuse check

`defusedcsv` does the CSV half (a drop-in `csv` that escapes these cells); it is one more dependency for six
lines, and it does nothing for a workbook. Not added; say if it is wanted.

## Dropped (D-311)

No sign-off step.
