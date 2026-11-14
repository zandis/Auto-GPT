# D-703 A test holds the intended-use statement on every page of every role

- **Task:** NEW-IU-1 (an outside assessment claimed the statement of TB-IU-01 C1 is absent from the console; the
  integrator's word of 2026-11-13)
- **PR:** this branch (`agent/NEW-IU-1-statement-on-every-page`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** T-116 / T-506 (the forbidden-word walk and the statement in the footer)

## The claim, and what was true

The claim is wrong: the statement is in the footer of the console's base page (`tb_common.wording.STATEMENT`,
`footer.statement`), in the reader's language, and the reports, sheets and mails carry it. What the tests held:

- **Reports, sheets and mails:** `tests/unit/test_wording_outputs.py` (each report and workbook, the case sheet,
  the consent pages, every mail body, a sent mail in both parts), in each language.
- **The console:** one test, of the home page, for the administrator, in three languages.

So the pages were right and one page was proven. Nothing held that a page built outside the base page, or a
page of another role, carries it.

## The decision

The walk that already opens every page each of the seven roles can open, in three languages
(`tests/console/test_wording_walk.py`), now also requires on every page it opens the statement in the footer, in
the reader's language, word for word. The sign-in page, the one page seen without an account, has its own test
(the browser's language). A page without the footer line, or with the statement of another language, fails.

No page had to change: the walk passes as the console is.

## What it does not do

- It reads the pages the walk reaches (every GET page whose path it can fill for a finished screening, case and
  feasibility run); a file a job produced is held by the outputs' test.

## Reuse check

The existing walk; nothing is added.

## Dropped (D-311)

No sign-off step.
