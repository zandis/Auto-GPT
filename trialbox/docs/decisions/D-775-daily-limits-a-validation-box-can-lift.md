# D-775 The heavy-jobs daily limit is a declared setting

- **Task:** lane G's blocker 5, the owner's ruling D-507, cut to the build phase by D-511 (the integrator, 2026-11-15)
- **PR:** this branch (`agent/D-507-daily-limits-as-declared-settings`), from master after train 17
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)

## Decision

- **`TB_JOBS_PER_SENDER_PER_DAY`** is declared (`tb_common.config`). When set, it is the daily limit of every heavy job
  type (FEAS, SCREEN, COHORT, NAV, MICROBATCH, CALIBRATION; D-146), overriding `settings.yaml`. 0 means no limit,
  which is how lane G's VALIDATION box lifts it. `install.sh --answers` reaches it through `env_extra`; it does not
  reach `settings.yaml`.
- Unset, or not a whole number, a box behaves as before. A type not counted by default (CASE, CONSENT, STATUS) never
  takes it.
- The mails one recipient gets a day already have their declared setting, `TB_MAIL_PER_RECIPIENT_PER_DAY`, unchanged.

## Remains (after PoC-1, D-511)

D-507's option (a), as the integrator settled it: on PRODUCTION (or with `TB_ENV` unset) a setting may lower a limit
but never lift it; today's value holds, it is logged, and `doctor` FAILs naming it. Built and reviewed on this branch's
first commits, then removed to keep the build phase's scope; the history keeps it for that card.

## Held by

`tests/unit/test_daily_limits_as_declared_settings.py`.
