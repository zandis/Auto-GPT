# D-775 The daily limits are declared settings a VALIDATION box can lift

- **Task:** lane G's blocker 5, the owner's ruling D-507 of 2026-11-15 (the integrator's routing on #649; option (a),
  under D-504, as the integrator settled it on #639)
- **PR:** this branch (`agent/D-507-daily-limits-as-declared-settings`), from master after train 17
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-146 (the daily per-sender limit of heavy jobs, J-02), T-108c (the mails one recipient gets a day),
  D-127 (one rule for `TB_ENV`: PRODUCTION when unset)

## The problem

Lane G's accuracy run on public data mails one FEAS per protocol, and its results by mail, to a VALIDATION box. The
daily limits stop it: 20 heavy jobs a sender (FEAS, SCREEN, COHORT, NAV, MICROBATCH, CALIBRATION) and 200 mails a
recipient. Both could already be changed on any box: the jobs limit in the site's `settings.yaml`, the mail limit by
the declared `TB_MAIL_PER_RECIPIENT_PER_DAY`. Lane G's runner sets a box through `install.sh --answers` (`env_extra`),
which reaches declared variables, not `settings.yaml`. Nothing kept a production site from lifting either limit.
**Shown by tests** before the change (kept failing output: the new module did not exist).

## The decision

- **One rule for both limits** (`tb_common.daily_limits.applied`):
  - on VALIDATION, TEST and DEV a setting may take any value, 0 (no limit) included;
  - on PRODUCTION, and on a site box with `TB_ENV` unset, a setting may lower a limit but never lift it. 0, or a value
    above today's default (20, 200), is not applied, and today's value holds.
- **The jobs limit gets a declared variable,** `TB_JOBS_PER_SENDER_PER_DAY`, which overrides `settings.yaml`
  (`rate_limit_per_sender_per_day`, `rate_limits_per_day`), so `env_extra` reaches it. `tb_common.authz.daily_limit`
  takes the environment (the process's when not given) and applies the rule; its callers (the orchestrator's job
  start, the mail intake) are unchanged.
- **The mail limit** keeps its variable and takes the same rule (`daily_limits.mail_per_recipient`, read by the mail
  gateway at start).
- **A lift not applied is said:** each service logs it once at start, and `doctor` has a `daily_limits` check that
  FAILs naming the setting (`daily_limits.refused_lifts`).

## Lines outside lane C2's files

The integrator asked for them to be named:
- `services/mail_gateway/app.py`: the limit read through `daily_limits.mail_per_recipient`, and the start-up log;
- `services/orchestrator/core.py`: the start-up log in `Orchestrator.__init__`, and `import os`;
- `tools/trialbox/doctor.py`: `check_daily_limits` in `CHECKS`, and its docstring line;
- `tests/unit/test_trialbox_doctor.py`: the pinned set of check names gains `daily_limits` (a deliberate change: a
  new check).

## Held by

`tests/unit/test_daily_limits_as_declared_settings.py`.

## Dropped (D-311)

No sign-off step.
