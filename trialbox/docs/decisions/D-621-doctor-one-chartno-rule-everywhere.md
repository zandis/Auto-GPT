# D-621 `doctor` holds every service to the chart-number rule the pid map was built with

- **Task:** DOCTOR-CHARTNO (given to lane D by the integrator on 2026-11-12, from the review of lane E's #399)
- **PR:** this branch (`agent/DOCTOR-chartno-rule-in-every-service`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-301 (`tb_common.chartno`), D-579 (the installer asks the rule and writes `TB_CHARTNO_RULE`),
  D-595 (the adapter records the rule beside the site key and refuses a night under another)

## Context

The adapter records the chart-number rule in the pid map and refuses a night under another rule. Other processes
make pseudonyms too, each under its own `TB_CHARTNO_RULE`, without asking the pid map: the orchestrator's
`/setup/pseudonym` (site set-up, the opt-out desk), candidates, scenarios, the data core API, `tools/keys.py`. A
container that runs with another rule than the adapter is not noticed: an opt-out could be registered under a
pseudonym the feed never produces.

## Decision

Written when the card is complete.
