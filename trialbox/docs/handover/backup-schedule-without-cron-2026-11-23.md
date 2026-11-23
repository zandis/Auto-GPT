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

## Review round (the independent review of #1388: fix first)

Each finding has a test that fails on `910db4df` (16 failed there, the rest are the first round's tests); all in
`tests/unit/test_backup_schedule_timer.py`.

- **F1** install.sh's PRODUCTION stop (no `/etc/cron.d`) now applies only where systemd is not the init either;
  on a systemd host it warns that the retention cron is not installed (H92-02) and goes on to the timers.
  `test_install_sh_production_on_a_systemd_host_without_cron_goes_on_to_the_timers` runs install.sh's own lines.
- **F2, F11** any failure of the timer install (enable done and start failed, a failing reload on a timer box,
  the cron file that cannot go, a quote in the install folder) removes the timers (disable --now, units removed,
  verified) before the cron file is written; unverifiable: no cron file, exit 1, the action.
  `test_a_failed_timer_install_leaves_the_cron_file_alone_and_no_timer[4 cases]`,
  `test_timers_that_cannot_be_removed_stop_the_install_with_one_action`.
- **F3, R2** without root on a timer host: exit 1, nothing changed; `TB_SYSTEMD=0` as root: the timers go
  (verified), then the cron file. `test_tb_systemd_0_or_no_root_over_a_timer_box_keeps_one_schedule`.
- **F4** R1 `test_the_mail_cron_sent_is_sent_by_the_timer_and_systemds_own_characters_are_doubled`; R3, R6 the
  invariant (the `[Timer]` section is exactly `OnCalendar` and `Persistent`; `After=`); R4
  `test_doctor_reads_every_timer_and_only_a_running_enabled_one_counts`; R5
  `test_a_cron_line_the_timer_cannot_carry_exactly_is_refused[45 4 1 * * ...]`.
- **F5** environment lines other than `SHELL=/bin/sh` and `MAILTO=`, and a minute or hour out of range, are
  refused (same parametrised test). **F6** a fixed hour of 02 is refused (D-1090 item 4); the shipped 04:45 and
  `*:17` are shown as calendar expressions: `test_no_fixed_time_falls_in_the_hour_the_spring_forward_day_skips`.
- **F7** the service runs with cron's `PATH=/usr/bin:/bin`; **F10** after `docker.service trialbox.service` (both
  in the invariant). **F8** doctor and backup-status read every timer: disabled, stopped (enabled, not active) or
  either one missing is a problem; `enabled-runtime` fires: `test_doctor_reads_every_timer_...`,
  `test_a_timer_enabled_but_not_running_reads_as_stopped`. **F9** install.sh passes `TB_SYSTEMD_DIR` as
  `--systemd-dir`: `test_install_sh_hands_its_systemd_folder_to_backup_install`.
- Not done: F7's `TimeoutStartSec=infinity` (a hung night blocks the next start; under cron `backup.lock` refused
  the second run: the same night without a backup either way). F8's cron-to-timer generator host reads as "no cron
  daemon" (a false FAIL with the action, not a silent pass).
- Mutants: the review's R1 to R6 and 12 more (the fallback without the removal, the removal not verified,
  `TB_SYSTEMD=0` keeping the timers, non-root not refused, doctor reading the nightly timer only, a stopped timer
  firing, environment lines skipped, range unchecked, 02:xx allowed, install.sh's PRODUCTION stop kept, no
  `--systemd-dir`, cron's PATH dropped): 18 planted, 18 caught (the stopped-timer one after one added test).
- **The bench's red on `2d96b872`** (`test_backup_alert_on_the_health_page.py::test_doctor_warns_in_production_when_the_page_is_the_only_route`,
  WARN where PASS is due on a systemd host): doctor built in code asked the host's own timers. Like the cron daemon,
  the timers are now asked only by the command-line doctor (`inputs_from`, `DoctorInputs.backup_timers`). Test:
  `test_doctor_built_in_code_asks_no_host_and_the_command_line_doctor_does`; the 103 test files that cover doctor
  and backup status also pass with a simulated systemd host.
- H92-02 is not the same code path (install.sh writes the retention file itself): the row stays open.

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
M9 `TB_SYSTEMD=0` ignored; M10 systemd's `$` not doubled; M11 install.sh without its systemd-host line; M12 a failed
enable leaves no schedule.

## Files

`tools/trialbox/backup_schedule.py`, `tools/trialbox/doctor.py` (the `backup` check, `DoctorInputs.cron_running`),
`tools/trialbox/__main__.py` (`--systemd-dir`), `deploy/backup/trialbox-backup.cron` (comment), `deploy/install.sh`
(one line before the backup step), `tests/unit/test_backup_schedule_timer.py` (new),
`docs/runbook/05-updates-backup-restore-secrets.md` (one paragraph). Decision: D-1090
(`docs/decisions/D-1090-the-backup-timer-wins-over-cron.md`, row reserved).
