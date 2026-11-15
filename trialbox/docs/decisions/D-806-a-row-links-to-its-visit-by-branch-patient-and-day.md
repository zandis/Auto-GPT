# D-806 A row links to its visit by branch, patient and day when visit numbers do not join

- **Task:** F7 (from the first look at a real source; facts kept off the repository)
- **PR:** this branch (`agent/F7-encounter-by-branch-patient-day`)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-538 (a table read whole on a delta night), D-580 (counts, never values), DATA-017

## Context

Some exports number a visit differently in each table. A diagnosis or a vital then names a visit number no visit row
has, and `{ref: {type: Encounter, hid: enc_no}}` links nothing. What joins is the patient and the day, in one branch.

## Decision

1. **`{ref: {type: Encounter, by_day: {table, keys, day, their_day}}}`** links a row to the one visit `table` holds for
   the row's `keys` (columns both tables hold: branch, patient) and day.
2. **A day with several visits, or none, links to none**, and so does a day whose one visit the mapping refused or
   left out; each is counted per table (`encounter_by_day` in the night's completeness: `linked`,
   `several_visits_that_day`, `no_visit_that_day`, `visit_not_mapped`). Never guessed.
3. **Every visit row read counts toward its day**, mapped or not, so a refused visit cannot turn a day of two into a
   day of one.
4. **The mapping is checked when it loads**: the visit table exists, makes the resource and is mapped first.
5. **The visit table is read whole on a delta night** (lane B's `pipeline.py`, two hunks): an unchanged visit missing
   from the night's rows would make a day of two visits look like one.

## Known limits

- A delta night reads the visit table whole: more rows read each night.
- The day is the calendar day in the mapping's time zone (or the offset a value states).
