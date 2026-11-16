# D-817 A placeholder birth date keeps the patient

- **Task:** CGRD-A6 (from the first look at a real source; facts kept off the repository)
- **PR:** this branch (`agent/CGRD-A6-placeholder-birth-date-keeps-the-patient`), cut from CGRD-A4 (#716) with master
  (train 27) merged in
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-811 (`lived_at_most`), DIN-001 (the feed's date range)

## Decision

1. On a date element that carries `lived_at_most` (the base mapping's `birthDate`), a value outside the feed's range
   (a placeholder such as `9999-12-31`, a year before 1850 or past today + 10) is left out and counted
   (`implausible_dates`), the patient kept. Before, the range check refused the whole patient row and orphaned every
   record of the patient.
2. A value that is no date at all is still refused, as is a date out of range on any other element.
