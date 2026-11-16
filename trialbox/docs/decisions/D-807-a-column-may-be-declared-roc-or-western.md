# D-807 A date column may be declared `roc_or_western`

- **Task:** F8 (from the first look at a real source; facts kept off the repository)
- **PR:** this branch (`agent/F8-western-date-in-roc-column`)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-589 (a site declares a date column's calendar; nothing is detected from values)

## Context

An export can write as a western date (`2026-01-13 00:00:00`) a column the database writes in the ROC calendar.
Declared `roc`, every such value is refused (D-589) and the whole table is lost.

## Decision

1. **A new declared calendar, `roc_or_western`** (`tables.<t>.dates: {col: roc_or_western}`). A ROC value is read as
   ROC. A western value that no ROC form can be is read as written: a four-digit year with separators, or 8, 12 or 14
   digits (ROC's compact forms are 7, 11 and 13). Anything else is refused, as in a `roc` column.
2. **Each western value read is counted** per table and column (`read_as_western` in the night's completeness;
   lane B's `pipeline.py`, one hunk). Counts only.
3. `roc` is unchanged: a western value in it is still refused. Only the site's declaration makes it acceptable.
