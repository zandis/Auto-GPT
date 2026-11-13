# D-559 The site set-up's two refusals of unreadable text say what to do

- **Task:** NEW-SITE-1 (left to this lane by lane E's refusal-sentence card; the integrator's word of 2026-11-13)
- **PR:** this branch (`agent/NEW-SITE-1-charset-refusals-name-the-remedy`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** lane E's sentences for the data pages (`dc.err.FORM-ENCODING`, `dc.err.DATA-SHEET`)

## The problem

Two refusals of the site set-up pages named the fault and no remedy for a file whose character set cannot be
told: `site.err.CHART-TEXT` ("The text is not in a known character set") and `site.err.SHEET-READ` ("This file
cannot be read. Save it as Excel (.xlsx) or CSV."). A coordinator with a CSV saved by Excel in the system's code
page was told to save it as CSV, which it already was.

## The decision

Both sentences end with the remedy the data pages' refusals give, in the same words, in English, Japanese and
Traditional Chinese: save it as UTF-8 with a byte order mark (in Excel: "CSV UTF-8") and try again. The sheet
refusal says it for the case it applies to (a CSV whose text is the cause) and keeps naming the two formats.

Sentences only: no key is added, no code changes.

## Review

No reviewer was asked: six strings that repeat a remedy already reviewed in lane E's card, held by a test that
each language carries it and none of the forbidden words.

## Reuse check

Lane E's wording of the remedy, word for word; nothing is added.

## Dropped (D-311)

No sign-off step.
