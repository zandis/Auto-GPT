# The backup schedule without a cron daemon (2026-11-23)

**Reader:** the people who build TrialBox: lane H, the integrator and the independent reviewer.

Card H-92 (walk step 8, backup; high-risk: backup and restore on the box's host). The ruling (comment 7088635278):
the schedule must not depend on a cron daemon the box may lack; use a systemd timer, which the box installs. On the
bench's rehearsal host the scheduled backup did not run: (a) `No module named 'zstandard'` on the host's python, a
master from before H-88 (#1373; fixed there, see below); (b) the host runs no cron daemon. This card is (b).

## Pull request body (draft)

**Which schedule.** `trialbox backup-install` decides once per run:

- systemd is the init (`/run/systemd/system` and `systemctl`, install.sh's own test), it runs as root, and
  `TB_SYSTEMD` is not `0`: each job line of `deploy/backup/trialbox-backup.cron` becomes
  `trialbox-<subcommand>.service` and `.timer` in `/etc/systemd/system` (`--systemd-dir`):
  `trialbox-backup-nightly` (04:45) and `trialbox-backup-status` (hourly at :17). The service's `ExecStart` is
  `/bin/sh -c '<the cron line's command>'` (systemd's `%` and `$` doubled), the timer's `OnCalendar` is the cron
  line's minute and hour in local time, `Persistent=true`. `daemon-reload`, `enable --now` both timers, then the
  cron file is removed. **The timer wins; never both.** If systemctl fails, the cron file is written instead and
  said, no timer is enabled.
- otherwise: the cron file, as before; when no cron daemon runs either, a line says nothing will run it.

The units are derived from the cron template, so the two cannot drift; a cron line a timer cannot carry exactly
(a day-of-week, a step) is a ValueError, not a guess. A site whose only alert route was cron's `MAILTO` keeps it: the
timer's script mails what the command prints (it prints only on trouble) through the host's `sendmail`. Every
existing refusal (the PRODUCTION alert route, a MAILTO without a mail transfer agent) is the same code for both.
No unit carries a setting or a secret: the tool reads `deploy/.env` itself (H-88).

**What says which schedule runs.** `doctor` (`backup`) starts its facts with `schedule: timer|cron|none`. Problems
(FAIL in PRODUCTION, WARN elsewhere, as the check's other problems), each with one action:
- the cron file is there, no cron daemon runs, no timer: "start the host's cron daemon" (no systemd) or
  `backup-install --deploy deploy --no-first-run` as root (systemd host: it installs the timer);
- the timer is enabled and the cron file is back: both would fire; `backup-install` removes the cron file;
- systemd host, neither: `backup-install`. The old "no /etc/cron.d/trialbox-backup" FAIL is kept as it was.
A systemd host still on cron WARNs (PRODUCTION) that `backup-install` moves it. `backup-status` prints a
`schedule:` line (and `"schedule"` in `--json`); its exit code stays the backup's age (see below).
The cron daemon is asked by the doctor run from the command line (`inputs_from`); `DoctorInputs` built in code
asks nothing unless given `cron_running`.

**An existing box.** Its cron line keeps running wherever a cron daemon runs. As root,
`python3 -m tools.trialbox backup-install --deploy deploy --no-first-run` moves it: timers enabled, the cron file
removed. `install.sh` now runs the backup step on a systemd host that has no `/etc/cron.d` (no cron package).

**The invariant test (H-92):**
`tests/unit/test_backup_schedule_timer.py::test_the_timer_runs_the_installed_cron_lines_command_from_a_bare_environment`:
the timers `install_timers` writes are one per cron line, each runs exactly that line's command at its time,
Persistent; the nightly one, run as systemd hands it to the shell from H-88's bare harness (cwd `/`, PATH only, the
host's python without zstandard, the docker stand-in), writes a `.tbbak` that verifies with the test's key.

**Tests (all fail on master `f5d0f1fd`: 4 failed, 3 errors).** The invariant; the mail and refusal test; with
systemd and no cron daemon the schedule is the timer and doctor passes; with neither, doctor FAILs with the action
and backup-status says `schedule: none: FAIL`; with both, exactly one (the cron file goes; a hand-restored one is a
FAIL; a failing systemctl or `TB_SYSTEMD=0` gives the cron file only); the old cron-only box keeps working and is
moved; install.sh's step condition.

**H-88's question (reading only).** Yes: with H-88 on master the cron line's command, on a host without the
product's modules, runs the backup in the image:
`test_host_commands_own_environment.py::test_the_installed_cron_line_runs_the_nightly_backup_from_crons_bare_environment`
(a host python without zstandard; the image's `trialbox backup` runs through the docker stand-in).

**What a person runs on the bench (step 8).** As root, from the install folder after the update:
`python3 -m tools.trialbox backup-install --deploy deploy --no-first-run`; `systemctl list-timers 'trialbox-backup-*'`
(two timers, `/etc/cron.d/trialbox-backup` gone); `systemctl start trialbox-backup-nightly.service`; then
`tail /var/log/trialbox-backup.log` (a new `.tbbak`) and `trialbox doctor --env-file deploy/.env` (`backup`:
`schedule: timer`).

**What is not verified.** No systemd, no cron daemon and no Docker here: `systemctl` is a recorder, the init and the
daemon are inputs; systemd's own parsing of the units (the quoting of `ExecStart`, `Persistent` after a boot) is
not run. The mail path through `sendmail` is shown as text only. The rehearsal host is a container with no
systemd: there the cron path stays.

## Findings

| Id | Severity | Claim | Basis | State |
| --- | --- | --- | --- | --- |
| H92-01 | High | the backup schedule was a cron file only: a host with no cron daemon never ran the nightly backup, and doctor passed | shown | fixed 8789a789 |
| H92-02 | Medium | `/etc/cron.d/trialbox-retention` (log retention, the signed audit head) has the same dependence on a cron daemon | hypothesis | open |
| H92-03 | Low | `backup-status`'s exit code does not carry a missing schedule (only doctor FAILs): an exit change breaks `test_cli_status_exit_codes` on a host with `/etc/cron.d`, a ruling | shown | open |

H92-02 is read from install.sh, not run: install.sh writes it and only on a host with `/etc/cron.d`; doctor's
`audit_heads` would then FAIL on the head's age, not name the cause.

## Mutation pass

12 planted, 12 caught (M10 after one added assertion), against the card's file, `test_host_commands_own_environment.py`,
`test_backup_schedule.py`, `test_trialbox_doctor.py`, `test_backup_alert_on_the_health_page.py`:
M1 the timer's command loses its `cd`; M2 the timer in UTC; M3 not Persistent; M4 the cron file kept; M5 timers not
enabled; M6 doctor never asks for the cron daemon; M7 both schedules not flagged; M8 the timer path never taken;
M9 `TB_SYSTEMD=0` ignored; M10 systemd's `$` not doubled; M11 install.sh's condition back to cron only; M12 a failed
enable leaves no schedule.

## Files

`tools/trialbox/backup_schedule.py`, `tools/trialbox/doctor.py` (the `backup` check, `DoctorInputs.cron_running`),
`tools/trialbox/__main__.py` (`--systemd-dir`), `deploy/backup/trialbox-backup.cron` (comment),
`deploy/install.sh` (the backup step's condition), `tests/unit/test_backup_schedule_timer.py` (new),
`docs/runbook/05-updates-backup-restore-secrets.md` (one paragraph). No decision number is used; one may be wanted
for "the timer wins over cron" (the integrator's call).
