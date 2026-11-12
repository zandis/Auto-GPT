# D-579 The chart-number rule is asked at install and written to the box's settings

- **Task:** NEW-DIN-3, the installer's half (DIN-003; given to lane D by the integrator on 2026-11-12; the opt-out
  desk's half is lane E's, the first-run page's is lane C's)
- **PR:** this branch (`agent/NEW-DIN-3-chartno-rule-at-install`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-301 (`tb_common.chartno`: one normaliser for chart numbers; the site's rule is
  `TB_CHARTNO_RULE`, default `asis`)

## Context

`tb_common.chartno` says the rule is "set once at installation from the hospital's chart-number format". Nothing
set it: no question in the settings wizard, no line in `deploy/.env`. Every box ran on `asis`, where leading zeros
are significant: a sheet that lost them (`00123456` saved as `123456`) gives a second pseudonym for the same
patient, and an opt-out or a fact filed under one spelling does not meet the record under the other.

## Decision

Written when the card is complete.
