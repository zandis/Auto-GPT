# D-699 The enrolment workbook opens on a report for people

- **Task:** NEW-UX-3b (the rest of deep-review finding UX-003: the enrolment workbook is machine words)
- **PR:** this branch (`agent/NEW-UX-3b-enrolment-workbook`), from master; D-698 is the screening log
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-698, D-549 (no formulas in a file)

## Context

The enrolment workbook the orchestrator writes (`states`, `months`, `screen_fail`, `withdrawals`, `about`) is in
machine words whatever the user's language: `candidate`, `screen_fail`, `declined`, a withdrawal reason as `3`. The
page is translated. Shown by tests before the change.

## Decision

1. **The console adds a sheet for people when it hands the file over** (`console.lifecycle_pages.printable_report`):
   the study and when the file was made, then the four tables under headings in the reader's language, each state and each reason in the page's words
   (`life.state.*`, `life.reason.sf.*`, `life.reason.wd.*`), a withdrawal's day as a date, laid out to print
   (portrait, one page wide). The workbook opens on it.
2. **The machine sheets stay as they were, `states` first**, and systems read them by sheet name. The file is
   normalised as the orchestrator's is, so the same report gives the same bytes (SPEC 11.2).
3. A file that is not the report, or not of its shape, is handed over as it came (logged), never half made.
4. The CSV stays the machine table (one long table for systems), with its byte-order mark.

## The adversarial review (by running) and what it changed

| Finding | Severity | Outcome |
| --- | --- | --- |
| Re-saving dropped the orchestrator's normalisation: the file was no longer byte-reproducible | medium | fixed: normalised again (a test pins it) |
| The printed sheet did not name the study nor when it was made | low | fixed, test first |
| The sheet began with a blank row | low | fixed, test first |
| A report of another shape answered 500 | low | fixed, test first: handed over as it came |

The review found every word matches its code (screen-failure reasons, withdrawal reasons 1 to 6, the months'
states), no value lost, no formula, and nothing shown that the machine sheets did not hold.

## Evidence

`tests/console/test_enrolment_workbook_printable.py`: the workbook opens on the report in Japanese (the words, a
withdrawal reason in words, a date as a date, the print layout); the machine sheets unchanged; another file given back
as it was; every heading in three languages; the review's three cases. All four first tests failed before the
change (the function did not exist); two of the review's failed before its fixes.
