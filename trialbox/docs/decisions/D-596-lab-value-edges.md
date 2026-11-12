# D-596 A lab number the box cannot hold has no value, with or without a unit; a look-up factor is above zero

- **Task:** two findings in lane E's folder from lane B's review of #398 (NEW-B-6, D-527), passed by the integrator
  on 2026-11-12
- **PR:** this branch (`agent/DIN-lab-value-edges`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-215 (a result that cannot be read is no value, never a guess), D-590 (the shape of a result
  that lost its value: no `value[x]`, the text in a note, counted), D-527 (a row that breaks the mapping is a
  rejected row)

## Context

1. A lab result of thirty digits had three outcomes: with a unit, or for an analyte with no plausible range, the
   arithmetic failed inside the mapper (a rejected row since D-527, the end of the night before); with no unit and
   a plausible range it was kept with no value (D-590).
2. A look-up row with `factor` 0 loaded: every result of that analyte became 0, a wrong lab result, not a missing
   one. A negative factor turned the sign.

## Decision

1. **A number the box cannot hold is a result with no value**: when the value times the factor cannot be written
   as a number (more digits than the arithmetic keeps, or not finite), the result is kept with no `value[x]`, its
   text in a note, the reason `unknown_value`, and it is counted per analyte under `value_unreadable` (D-580's
   counter). The same with and without a unit. The row is not rejected: the result exists, its number does not.
2. **A look-up factor is a finite number above zero**, checked when the mapping loads (the night, the back-fill
   and the mapping check): a factor of 0 or below stops the mapping from loading, naming the look-up and the row.
   An empty factor is 1, as before.
