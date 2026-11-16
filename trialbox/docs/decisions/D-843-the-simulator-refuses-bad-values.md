# D-843 The REDCap simulator refuses the values a real REDCap refuses

- **Task:** CGRD-B5a (packet 2, B5 items 2, 3, 7, 8; EDC-001), from the browser run against a real REDCap 17
- **PR:** this branch (`agent/CGRD-B5a-sim-refuses-bad-values`), cut from CGRD-B3 (#725) with NEW-EDC-3b (#729)
  merged in
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-584 (the stand-in run), STD-061

## Decision

1. The simulator refuses, as REDCap does: a choice that is not one of the field's codes (yes/no and true/false take
   0 or 1); a word or a comma in an integer or number field; a date or date-time in neither Y-M-D nor M/D/Y (a ROC
   date, D-M-Y), or a day the calendar has not. A range is not checked: REDCap's import does not refuse it.
2. One bad value refuses the whole import: nothing of the file is written (it already checked every row first).
3. A row on the other arm's event is still taken, as REDCap takes it: the bridge's own check (D-841) is what is
   tested. The stand-in run's expected failures drop R1.
