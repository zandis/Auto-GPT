# D-841 A record's arm is read from all its rows; dates go to REDCap as YYYY-MM-DD

- **Task:** CGRD-B3 (from the browser run against a real REDCap 17 instance; synthetic records only)
- **PR:** this branch (`agent/CGRD-B3-arm-checked-dates-ymd`), cut from CGRD-B1 (#723)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** T-302b / D-414 (`wrong_arm`: a value is never written to another arm)

## Decision

1. A real REDCap takes a row for a record on an event of the other arm, with no error: the bridge's own check is the
   only guard. The send and the preview now read a record's events from an export of the record id alone, which every
   event row has: a REDCap that leaves out of a narrower read an event row holding none of the fields asked for can
   no longer leave the record with no arm, and a value bound for the other arm is held (`wrong_arm`).
2. A real REDCap reads an import's date only as Y-M-D or M/D/Y, whatever the field shows (a ROC date was read as
   day 115). TrialBox sends Y-M-D for every date validation and refuses any other form at decide time (pinned by
   tests; no change was needed).
