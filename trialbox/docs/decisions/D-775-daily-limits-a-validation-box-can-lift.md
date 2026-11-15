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
- **The jobs limit gets a declared variable,** `TB_JOBS_PER_SENDER_PER_DAY`, so `env_extra` reaches it. It applies
  to the heavy job types only:
  - where a lift is allowed, it replaces the site's `settings.yaml` value;
  - elsewhere, it may only lower the site's own limit for each type. A site that lowered FEAS to 3 keeps 3 whatever
    the variable says (`daily_limits.site_jobs`, then `jobs_per_sender`).

  `tb_common.authz.daily_limit` takes the environment (the process's when not given) and applies the rule. Its callers
  (the orchestrator's job start, the mail intake) are unchanged.
- **A type not counted by default** (CASE, CONSENT, STATUS) keeps the site's per-type value as it is, on any box: a
  value there is a new limit, never a lift, and the variable never reaches it.
- **The mail limit** keeps its variable and takes the same rule (`daily_limits.mail_per_recipient`, read by the mail
  gateway at start).
- **A lift not applied is said:** each service logs it once at start, and `doctor` has a `daily_limits` check that
  FAILs naming the setting (`daily_limits.refused_lifts`). A limit variable that is not a whole number is ignored
  (the site's values and the defaults hold) and said the same way, on any box (`daily_limits.malformed`).

## A change for existing PRODUCTION sites

A PRODUCTION site that had lifted a heavy limit in `settings.yaml` loses the lift on upgrade. Examples:
- `rate_limits_per_day: {SCREEN: 40}`, as the old example comment suggested, becomes 20;
- a per-type or per-sender 0 ("no limit") becomes 20.

`doctor` FAILs naming each such setting until it is lowered or removed. A site that set nothing, or lowered a limit,
is unchanged. The example settings files say so.

## Lines outside lane C2's files

The integrator asked for them to be named. Shared files, changed in their own rows only:
- `libs/tb_common/config.py`: the `TB_JOBS_PER_SENDER_PER_DAY` row, and the mail row's doc line;
- `deploy/settings.example.yaml` and `deploy/platform/base/settings.example.yaml`: the per-type comment;
- `docs/decisions/REGISTRY.md`: this record's row.

Other lanes' files, in their smallest hunks:
- `services/mail_gateway/app.py`: the limit read through `daily_limits.mail_per_recipient`, and the start-up log;
- `services/orchestrator/core.py`: the start-up log in `Orchestrator.__init__`, and `import os`;
- `tools/trialbox/doctor.py`: `check_daily_limits` in `CHECKS`, and its docstring line;
- `tests/unit/test_trialbox_doctor.py`: the pinned set of check names gains `daily_limits` (a deliberate change: a
  new check).

## Adversarial review

NOT SOUND on the first pass:
1. On PRODUCTION the variable could raise a limit the site had lowered (FEAS 3 with the variable at 20 gave 20), with
   no log and a doctor PASS.
2. A type not counted by default was measured against 20: a per-type CASE limit was cut, given a limit of 20 where
   there was none, or reached by the variable.
3. A malformed variable was ignored without a word.
4. This record left out the change for existing PRODUCTION sites and some shared files.

All are fixed and held by tests. Two details also changed: doctor's PASS line shows the limit of each heavy type, and
`TB_ENV` is read by the one rule (spaces and case ignored; blank or unknown counts as PRODUCTION).

## Held by

`tests/unit/test_daily_limits_as_declared_settings.py`.

## Dropped (D-311)

No sign-off step.
