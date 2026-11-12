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

1. **The question.** The settings wizard has a question `chartno_rule`, right after the MRN pattern: `asis`,
   `digits[:width]` or `hex[:width][:lower]`. The answer goes to `deploy/.env` as `TB_CHARTNO_RULE`; every service
   reads `.env`, so every path from a chart number to a pseudonym uses the same rule.
2. **An answer is checked.** It must be a rule `tb_common.chartno` reads, and it must not contradict the MRN
   pattern: a chart number written by the rule has to be one the pattern accepts (`digits:10` with `^\d{8}$`,
   or a digit rule with `^C\d{7}$`, is refused).
3. **No answer.** When the site answered an MRN pattern of exactly n digits, the rule is `digits:n`, and the
   wizard says so: every number that pattern accepts is already n digits, so padding can join only spellings of
   one number. Any other pattern stays `asis`, with a warning that leading zeros are significant. The wizard's own
   default pattern is a placeholder; no rule is read from it.
4. **The box.** `tools/box/plan.py` passes `chartno_rule` from the owner's first-run answers when they have the
   field. The first-run page that asks it is lane C's; until it does, a box gets `asis` and the warning.

## Consequences

- A new site whose answers give `^\d{8}$` now gets `digits:8` without writing it. An 8-digit number is unchanged;
  `123456` becomes `00123456`. The adapter already refused a column of such numbers (`column_refusal`), so no
  pseudonym a box could have made before changes.
- **Not changed, and to know:** the wizard writes the whole `.env`; a box that is installed again with another
  rule gets other pseudonyms for chart numbers not already written the new way. The runbook says to set it at
  install. A tool that moves an existing box from one rule to another is not built.
- The two answer files in the repository answer the question: the rehearsal `digits:8`, site C `asis`.
