# D-698 The screening log a site prints is in the reader's language

- **Task:** NEW-UX-3 (deep-review finding UX-003, High: the screening-log workbook is English machine codes and not
  laid out to print)
- **PR:** this branch (`agent/NEW-UX-3-printable-screening-log`), from master
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-387 (the pre-screen log), D-435 (the sponsor layout), D-549 (no formulas in a file)

## Context

The screening-log workbook is the ICH E6 log a site prints or hands to the trial office and the monitor. Downloaded
from a Japanese session it had English machine headings (`screening_no, pseudonym, pi_mark, ...`) and values
(`approach`, `not_reached`), dates as text, no column widths, no frozen header, no print titles, no orientation, and
an "about" sheet that said the time in UTC. The page itself is translated. Shown by tests before the change.

## Decision

1. **The workbook's first sheet is the log for people**: the headings in the reader's language (the console's
   catalogue, three languages; the page's own words where the page has them), every coded column in words as the
   page writes it (the investigator's decision and its reason, the last contact, the status, the referral's route,
   outcome and reason, and the IRB warnings an approach went ahead despite), the dates as dates (`yyyy-mm-dd`), the
   header bold and frozen, the columns as wide as their text (a CJK character counted two; 10 to 40), and laid out
   to print: landscape, one page wide, the header on every page.
2. **The machine-readable sheets stay as they were** (`screening log`, `pre-screen log`, `about`, with their codes),
   and the workbook still opens on `screening log`: systems, scripts and the sponsor layout read them.
3. **The "about" sheet says when the file was made in the site's time zone**, as the enrolment workbook does.
4. The sponsor layout (D-435) keeps the sponsor's own headings and words; only its "made" time moves to the site's
   zone.

## Not in this card

- The enrolment CSV and workbook (`state,now,candidate`; a withdrawal reason as a number): the same treatment is a
  follow-up in the orchestrator's report.
- The pseudonym stays whole (32 characters): it is how the box finds the row again.

## The adversarial review (by running) and what it changed

| Finding | Severity | Outcome |
| --- | --- | --- |
| The new first sheet became the active sheet; a reader of the active sheet (an existing test) got the translated headings | high | fixed, test first: the workbook opens on the machine sheet |
| The IRB-override heading said in ja and zh-TW that the IRB approved an exception; the column lists the IRB warnings the approach went ahead despite | medium | fixed, test first: the page's words |
| The referral columns, the decision reason and the overridden warnings were still codes | medium | fixed, test first |
| CJK columns too narrow | low | fixed, test first |
| The ja status heading differed from the page | low | fixed, test first |

## Evidence

`tests/console/test_screening_log_printable.py`: the first sheet in Japanese (title, headings, words, a date as a
date, frozen header, print titles, landscape, one page wide, widths); the machine sheets unchanged; "made" in the
site's zone; every heading in three languages; the review's three cases. Three of the first four failed before the
change (the machine sheets' test pins what stays); the review's failed before its fixes.
