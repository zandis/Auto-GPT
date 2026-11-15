# D-840 The conformance kit loads on a real REDCap; TrialBox keeps a field's decimal places itself

- **Task:** CGRD-B1 (from the browser run against a real REDCap 17 instance; synthetic records only)
- **PR:** this branch (`agent/CGRD-B1-the-kit-loads-on-redcap`), cut from CGRD-B4 (#722)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-584 (the conformance project), STD-061 (a value written as REDCap's import takes it)

## Decision

1. The kit's calculations write powers as products and never two minus signs in a row (a real REDCap refused `^`
   and stores a double minus blank, D-819); the original forms stay as evaluator tests.
2. An instance may not offer `number_1dp`. The kit's temperature is `number` with its range, and the decimal places
   are said in the field annotation as `@TB-DECIMALS=n`: REDCap ignores an action tag it does not know; TrialBox
   reads it as the field's places (more is refused, never rounded; `37` is sent as `37.0`), in `field_sha` when set.
3. The instance check's R1 cases follow: REDCap's `number` takes `37` and `37.55`; TrialBox sends `37.0` and
   refuses `37.55` itself.
