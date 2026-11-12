# D-596 A lab number the mapping cannot compute is a rejected row with or without a unit; a look-up factor is above zero

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

1. **A number the mapping cannot compute is a rejected row, with or without a unit.** D-527 decided the outcome
   for a row whose arithmetic fails (rejected, counted under one fixed reason, the night goes on), and its test
   pins it for a result that states its unit. The same value without a unit took another road: the plausibility
   check of D-590 came first and kept it as a result with no value. The arithmetic now comes first, so both are
   the rejected row of D-527. The first version of this card made both "kept with no value"; that contradicted
   D-527's test, and the test stands.
2. **A look-up factor is a finite number above zero**, checked when the mapping loads (the night, the back-fill
   and the mapping check): a factor of 0 or below stops the mapping from loading, naming the look-up and the row.
   An empty factor is 1, as before; a cell that holds only blanks is refused (the night's own factor check, D-527,
   already refused it). The factor must also be above zero as the number results are computed with: `1e-400`
   is 0 in every result and is refused.
3. "Thirty digits" is an example. What the arithmetic cannot compute depends on the factor: with a factor of 1
   or 10 a 28-digit value already fails; the rule is the arithmetic's, not a digit count.
