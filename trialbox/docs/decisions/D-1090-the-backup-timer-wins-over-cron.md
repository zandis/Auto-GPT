# D-1090 The backup timer wins over cron (H-92)

- **Task:** lane H, card H-92 (walk step 8, the bench's rehearsal host ran no cron daemon; the integrator's ruling,
  comment 7088635278: the schedule must not depend on a cron daemon the box may lack) · **Date:** 2026-11-23
- **Status:** reserved for H-92 (the integrator flips the row when merged)
- **Builds on:** D-274 (the backup schedule), D-1089 (every host command brings its own environment), D-377 (the
  systemd units install.sh installs)

## Decision

1. **Where systemd is the init** (`/run/systemd/system` and `systemctl`), `backup-install` run as root, with
   `TB_SYSTEMD` not `0`, writes each line of `deploy/backup/trialbox-backup.cron` as a service and a timer
   (`trialbox-backup-nightly`, `trialbox-backup-status`): the line's command (`/bin/sh -c`, cron's `PATH`), its
   minute and hour in local time, `Persistent=true`, after `docker.service` and `trialbox.service`. It enables and
   starts both, then removes `/etc/cron.d/trialbox-backup`. **The timers win.**
2. **Elsewhere** the cron file, as before; it needs a running cron daemon.
3. **Never two schedules.** Before a cron file is written on a host that has the timers (a failed timer install, a
   re-run with `TB_SYSTEMD=0`), the timers are disabled and stopped, their units removed, and that is verified; if
   it cannot be verified, nothing is written and the one action is said (exit 1). Without root on such a host,
   nothing is changed (exit 1, run it as root).
4. **What a timer cannot carry exactly is refused, never guessed:** an environment line other than `SHELL=/bin/sh`
   and `MAILTO=`, a day, month or weekday field, a step, a minute or hour out of range, a fixed hour of 02 (the
   spring-forward day has no 02:xx and systemd skips it; cron runs it after the jump). The failed timer install then
   falls back to the cron file under item 3.
5. **Doctor** (`backup`) and `backup-status` name the schedule in use (`timer`, `cron`, `none`), reading every
   backup timer: enabled (or enabled-runtime) and running. A timer disabled or stopped, both schedules, or none that
   fires is a problem with one action (FAIL in PRODUCTION, WARN elsewhere, as the check's other problems).
6. The invariant: each timer runs exactly the command of the cron line it replaces, at its time, and that command
   runs the nightly backup from a bare environment.
   `tests/unit/test_backup_schedule_timer.py::test_the_timer_runs_the_installed_cron_lines_command_from_a_bare_environment`.

## Why

A box installs systemd units already (D-377); it may have no cron package. One schedule per host keeps the age
alert honest: two would fire the same night, and `backup.lock` would turn the second into a false failure alert.

## Not chosen

- Timers and cron both, relying on `backup.lock`: a nightly false alert.
- A hand-written timer file beside the cron template: two texts that can drift; the units are made from the
  template.
- Installing a cron daemon: a package the box does not otherwise need.
