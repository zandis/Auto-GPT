# D-811 A birth date earlier than any human life allows is left out and counted

- **Task:** F9 (from the first look at a real source; facts kept off the repository)
- **PR:** this branch (`agent/F9-birth-date-older-than-any-life`)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** DIN-001 (a feed date is bounded at 1850: a smaller year is another calendar's)

## Context

A birth date between 1850 and about 122 years ago passed the feed's bound, though nobody alive can be that old (the
longest verified human life is 122 years). It is a placeholder or an error, and an age read from it is wrong.

## Decision

1. **`lived_at_most: {years: N, until: <death column>}`** on a date element: a birth date more than `N` years before
   the death date, or before today when there is none, is left out of the record.
2. **The patient is kept**: refusing the row would orphan every record of theirs. An unknown birth date leaves an age
   criterion unknown, which screening already handles.
3. **Counted** per table and element (`implausible_dates` in the night's completeness; lane B's `pipeline.py`, one
   hunk). Counts only.
4. The base mapping's `birthDate` carries it with `years: 122`. The 1850 bound for every other date is unchanged.
