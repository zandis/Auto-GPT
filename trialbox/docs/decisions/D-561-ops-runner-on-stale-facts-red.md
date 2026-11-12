# D-561 The operations runner is on after the install; health facts that are missing or old are red; `doctor` fails when the runner is off

- **Task:** NEW-OPS-8 (finding OPS-009 of the deep review of 2026-11-12,
  `docs/reviews/2026-11-12-deep-review/12-maintenance-operations.md`; plan TB-PLAN-07 v7.2, wave 0, lane D)
- **PR:** this branch (`agent/NEW-OPS-8-ops-timer-on`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-178 (the operations page and its host runner), D-377 (the systemd units), D-273 (the health
  line and `/metrics`)

## Why

`install.sh` installed `trialbox-ops.timer` and left it off; turning it on was a line of RUNBOOK §15. Without the
runner nothing writes the host's health facts, and the health line then said WARN for ever: a disk over 85 %, a
backup older than 36 hours and a certificate about to end were never red in the mail or on `/metrics`, and "Back up
now" and "Apply this update" on the Operations page did nothing. Neither `doctor` nor the installer said so. A WARN
that never goes away teaches people not to read the line.

## Decision

1. **The installer turns the runner on.** `deploy/install.sh` enables and starts `trialbox-ops.timer` with the other
   timers. `box-install.sh` runs the same step. There is no manual step left in RUNBOOK §15.
2. **Facts that are missing or old are red.** `tb_common.metrics.evaluate` gives the check `facts` the level `red`
   when the runner never wrote the facts, or when they are older than `FACTS_STALE_H`. The message names the timer.
   The period is not new: one hour was the rule already, 60 runs of the one-minute timer.
3. **`doctor` checks the runner.** A new check `ops_runner` reads the runner's own record (`status.json` in the
   operations folder): PASS when its facts are fresh; otherwise FAIL in VALIDATION and PRODUCTION (WARN in DEV and
   TEST), and it says whether `trialbox-ops.timer` is enabled when systemd can be asked. It is not a host check on a
   platform (pods; no host timer).
4. **A box with no host runner says which it is.** The in-process box, the demo and the tests run the runner inside
   the console (`TB_OPS_RUNNER=inline`) and write the same facts; they are not affected.

## Consequences

- A box whose runner stopped is red within the hour, on the health line, in the daily mail and on `/metrics`.
- A box installed before this card keeps its timer off until the installer or an update runs again; `doctor` then
  FAILs with the one command that turns it on, and the health line is red. That is the intended signal.
- For the first minute after an install the facts are missing and the line is red until the first run.

## Not done here

- The checks the facts do not carry yet (a failed night, the clock, the GPU): OPS-010.
- A message path for red health on a box with no mail relay: OPS-008, T-730.
