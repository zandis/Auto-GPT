# D-566 On a box the installer's backup step is a FAIL line, not a stop

- **Task:** OPS-003 (TB-PLAN-07 v7.2, `docs/plan/33-plan-v7.md`, wave 1, lane D; finding OPS-003 of
  `docs/reviews/2026-11-12-deep-review/12-maintenance-operations.md`)
- **PR:** this branch (`agent/OPS-003-backup-step-fail-line`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-274 (the backup schedule; PRODUCTION needs an alert route, OPS-028), T-632 (a FAIL at the end of
  the install does not stop it half-way: the install ends with exit 1 and the list), D-466 (the box form:
  `box-install.sh` runs `install.sh` with `TB_BOX=1`; a stop before "TrialBox is running" is fatal, a FAIL list at
  the end is not)
- **Read by:** OPS-004 (the real installer in the rehearsal and in CI), T-730 (the box's alert path and where the
  backup goes)

## Context

`box-install.sh` runs `install.sh` as root with `TB_ENV` unset (PRODUCTION). The box plan sets `TB_BACKUP_MAILTO`
and no `TB_BACKUP_ALERT_CMD`; a fresh Ubuntu has no mail transfer agent; `backup-install` then refuses (exit 1),
and `install.sh` stopped there with `die`. That stop is before "TrialBox is running", so `box-install.sh` ended
with "nothing for the wizard to serve". The first install form of both sites could not be installed by the script
written for it.

## Decision

1. **With `TB_BOX=1`, a backup schedule that is not installed is a line in the install's FAIL list.** The install
   goes on, prints "TrialBox is running", and ends with exit 1 and the list, which `box-install.sh` already treats
   as a running stack. The line says what is missing and where it is set later (the first-run wizard, then
   `python3 -m tools.trialbox backup-install`).
2. **Without `TB_BOX` nothing changes**: the IT form still stops at this step. There a person is at the terminal
   with `deploy/.env` open, and an install that ends without a backup schedule is the wrong default.
3. `backup-install` itself is unchanged: PRODUCTION still refuses a schedule without an alert route (D-274). The
   box has no backup schedule until one is placed, and `trialbox doctor` says so (the backup's age).

## Consequences

- The box installer reaches the wizard on a host with no mail relay.
- Until T-730 a box runs without a backup schedule after the install; the FAIL line and the doctor name it.
- No setting, no limit, no new store.
