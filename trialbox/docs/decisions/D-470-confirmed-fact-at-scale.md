# D-470 A chart fact without its own date takes the date of its chart section, so a confirmed fact can count

- **Task:** G1 bug B1 (`docs/plan/measurements/g1-2026-11-11/BUGS.md`, branch `claude/g1-results-2026-11`)
- **PR:** this branch (`fix/g1-B1-confirmed-fact-at-scale`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-135 (a proposed fact only sends a patient to "needs information"; once confirmed it counts),
  D-142 DUMP-01 (an undated record leaves a criterion unknown where the dated ones do not settle it), D-215 (chart
  dates: 和暦, 民國, Gregorian)

## What G1 showed

Stage 12 of hospital-ja (50,000 patients, the real model pair) confirmed every chart fact, and both chart patients
still needed information: 10000004 should have been ready, 10000005 excluded by its confirmed breast cancer. The same
stage passed in every rehearsal and still passes on the stub at 500 and 5,000 patients. The patient count is not the
cause: the new site has its own lake, built from its own inputs only. The difference is the reader of the charts.
The stub copies the date of the dated line above onto every fact. The prompt (`chart_facts` v2) asks the model for the
date "as written in the chart, empty when the chart does not say", and the real model did that: a lab line under the
visit's heading, and "乳癌（2019年手術）", came back without a full date (G1 also kept 7 facts where the stub keeps 9).
Such a fact was published with no date at all, and by DUMP-01 an undated record leaves the criterion unknown. The
coordinator could confirm it, and it still could never count or exclude.

## Decision

1. **A chart fact the model leaves undated takes the date of its chart section**
   (`sitesetup.charts.section_day`): the last line at or above the line where its quote ends that holds a full date
   (和暦, 民國 or Gregorian), skipping any date-of-birth line. The model's own date, when it gives a readable one, is
   kept. A chart without any date leaves the fact undated, as before (unknown, DUMP-01). Dates of birth and sex have
   no day.
2. **This is not inventing a date.** The date is written in the chart, at the head of the record the quote is in:
   the fact was recorded that day. It is set on the *proposed* fact, so it shows on the review list beside the quote
   before anyone confirms it, and a coordinator corrects it (Correct, `day`) when the record copied an older result.
   A proposed fact still never counts and never excludes (D-135).
3. **The stub and the real model now give the lake the same kind of fact.** The stub's rule ("the date of the line or
   of the last dated line above it") was the behaviour every test and the e2e assumed; it is now the product's rule,
   not the stand-in's.

## Not done

- A history-type diagnosis ("乳癌（2019年手術）") gets the visit's date as its day, which the lake uses as onset and
  recorded date alike (the stub always did the same). For "any history of" this is exact; for a windowed criterion
  ("malignancy in the last 5 years") the coordinator must correct the day. Keeping onset and recorded date apart for
  chart facts needs a store column and is left for a card.
- The prompt is unchanged (a new prompt version needs qualification on the pair, D-359).
- G1's real-model facts were not kept by the run (only the check's evidence), so the exact seven facts are inferred
  from that evidence, not read. The evidence fits this cause and no other found: after confirmation feasibility
  counted 10000005 as remaining on a confirmed fact (the exclusion not TRUE) while the patient check said unknown,
  which is exactly an undated malignancy; the stage-12 check now records each chart fact's domain, code and day so
  the next pair run shows them.
