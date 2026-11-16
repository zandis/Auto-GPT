# D-810 A change time that is not a date never decides a delta night

- **Task:** F14 (from the first look at a real source; facts kept off the repository)
- **PR:** this branch (`agent/F14-change-time-not-a-date`)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** T-615b (DATA-008: an empty change time is read), DATA-017 (a row read twice merges by its key)

## Context

A source can write a placeholder in a table's change-time column. A delta night compared change times with the
night's start as text: a placeholder of letters sorted after every date, a compact date (`20260930`) after a dashed
one (`2026-10-01`). Rows were kept or dropped by accident, and nothing said so.

## Decision

1. **Change times are compared as dates** when both are (dashes, slashes, or 8, 12 or 14 digits); as text otherwise,
   as before.
2. **A row whose change time is not a date is read every night** (on a csv source), as one with an empty change time
   is: a row read twice is merged by its key, a row skipped is a change lost.
3. **It is counted** per table (`change_time_not_a_date` in the night's completeness) with a warning that names the
   table and the count, never the value (lane B's `pipeline.py`, one hunk).

## Known limits

- A SQL source still compares in the database; a column of placeholders there is read whole by the comparison. A
  site whose change column holds no date declares no `delta` for that table.
