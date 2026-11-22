# The host commands bring their own environment (2026-11-22)

**Reader:** the people who build TrialBox: lane H, the integrator and the independent reviewer. For builders, so in
one language.

Card H-88 (high-risk: backup, restore, the key file read on the host). The bench's install walk, step 8, on an
installed box: the scheduled backup stopped on "No module named 'tb_common'"; the restore drill the same, then on
"TB_DB_URL is not set". The integrator's ruling (2026-11-22): master's restore drill of #1305 (`box_drill.py`, the
installed `trialbox`) stays; H-88 is built on master `7dcba1bef0809b0729f22971678469908dfae2ff` without H-84's
throwaway server. The branch first carried H-84; the merge of master took master's side for every file H-84 changed,
so the diff against master is H-88's files only. Decision: D-1089.

## Pull request body (draft)

**What changes for a box.** Nothing is typed differently. Every `trialbox ...` (install.sh's link to
`tools/trialbox/__main__.py`) and every `python3 -m tools.trialbox ...` (cron's, the installer's) now goes through
`tools/trialbox/launch.py` first (D-1089):

- its import path comes from its own folder: the install folder's `libs/` and the install folder first; what the
  caller's `PYTHONPATH` added comes after and never counts as the host having a library
  (`tools/trialbox/__init__.py` also puts `libs/` on the path for `python3 -m tools.trialbox.<module>`);
- its settings are the box's own `deploy/.env`, read by the tool: a key of that file wins over the caller's value.
  One exception keeps #1305's design (its review, item 12): the module form `python -m tools.trialbox
  restore-drill` keeps the caller's connection and `--dir`; the installed `trialbox restore-drill` reads the box's
  settings itself (`BoxDrill`), as before;
- a command that needs a library the host's `python3` does not have runs in a one-off container of the box's own
  Python image (`TB_IMAGE` from the box's file; default `trialbox-py:1.0.0`), as `ops.py` and `audit_heads.py` run
  theirs: `--pull never`, `--network none` (`trialbox-net` for `backup`, `restore`, `model`, `omop-store`, `mail`;
  `trialbox-model-net` for `eval`), `--cap-drop ALL`, `no-new-privileges`, the invoking user's uid and gid, the
  settings by `--env-file deploy/.env`, only the files its arguments name at their own paths (inputs read-only;
  `deploy/site` read-write for a command that writes its record), its output and exit code passed through. Where the
  libraries are there (the image, a developer's interpreter) it runs in place. The commands that go to the image on a
  box: `backup-keygen`, `backup`, `backup-check`, `backup-verify`, `restore`, `exports`, `eval`, `model`,
  `omop-store`, `mail`. The rest, `restore-drill` among them (its image steps are `box_drill.py`'s own), run on the
  host. The table is `launch.COMMANDS`; a command added to the parser without its line fails
  `test_the_command_table_is_the_parsers`.

**The scheduled backup.** `deploy/backup/trialbox-backup.cron` sets no `PYTHONPATH`; its lines are master's
(`cd <install folder> && python3 -m tools.trialbox backup-nightly ...`) and work from cron's bare environment because
the tool brings its own. The update path does not rewrite the cron file (`update.py` has no `backup-install` step);
an old file keeps working after an update, since the fix is in the code it runs. `trialbox doctor` (`backup`) WARNs
in every environment on a file of the old form and names the fix.

**What an installed box does.** Apply the update; then, as root, `python3 -m tools.trialbox backup-install --deploy
deploy --no-first-run` from the install folder replaces the cron file (doctor's `backup` WARN goes). Nothing else.

**The invariant test (D-1089):**
`tests/unit/test_host_commands_own_environment.py::test_every_host_command_runs_from_a_bare_environment`, over all
33 commands: `--help` in both forms (the module form from the install folder; the installed form as its shebang runs
it, `python3 -I .../__main__.py`, from `/`) and one read-only call of the installed form, in cron's and sudo's
environment (`PATH=/usr/sbin:/usr/bin:/bin` with the stand-ins first, no `PYTHONPATH`, no `HOME`) with a "system"
`python3`: a venv of the base interpreter without site packages, PyYAML linked in (what install.sh requires), where
`psycopg`, `zstandard`, `cryptography`, `httpx` and `tb_common` do not import. With it:
`test_the_callers_path_and_settings_never_win` (a planted `tb_common`, `zstandard` and `cryptography` on the
caller's `PYTHONPATH`, a caller's `TB_DB_URL` and `TB_IMAGE`: none used) and
`test_the_box_file_wins_except_for_the_module_forms_drill`.

**The test the integrator asked for:**
`test_the_installed_cron_line_runs_the_nightly_backup_from_crons_bare_environment` takes the line `backup-install`
writes (rendered by `backup_schedule.install_cron`; only its log path is moved into the test's folder) and runs its
command with `/bin/sh -c` from `/`. The stand-in `docker` records every call, runs the db container's snapshot script
against the test's PostgreSQL (two scratch databases with synthetic rows) and the image's `trialbox backup` with the
test's interpreter: a real `.tbbak` lands on the off-box target and verifies with the test's own key. On master it
fails with the bench's words:

```
AssertionError: backup-nightly: backup failed: ModuleNotFoundError: No module named 'tb_common'
```

**The drill, typed as the runbook writes it:**
`test_the_drill_typed_with_sudo_as_the_runbook_writes_it_runs_from_a_bare_environment`: `sudo trialbox
restore-drill <file> --key <key>`, `trialbox` linked to a copy of the install folder's `__main__.py` and run by its
own shebang, a stand-in `sudo` doing what `env_reset` does (`env -i`, `secure_path`, `HOME=/root`), the caller's
`TB_DB_URL` and `PYTHONPATH` planted; BoxDrill's Docker calls run against the test's PostgreSQL. It passes, and it
passes on master too: #1305 had already fixed the drill's half of step 8. Here it guards that half against the
launcher.

**H88-03 (doctor's product checks on the host's python): a later card.** Step 8 is backup and restore; the walk's
proof is the backup line and the drill, neither of which runs doctor's product checks. Doctor reports those checks
as "check error" lines, not a crash, and `doctor --preflight` (RUNBOOK 01's host form) is clean in the bare test.

**What a person runs on the bench (step 8).** As root, after the update:
1. `python3 -m tools.trialbox backup-install --deploy deploy --no-first-run` from the install folder; then the 04:45
   line's command in cron's environment: `env -i PATH=/usr/bin:/bin SHELL=/bin/sh sh -c "$(grep '^45 4 '
   /etc/cron.d/trialbox-backup | cut -d' ' -f7-)"`; then `tail /var/log/trialbox-backup.log` (a new `.tbbak`, no "No
   module named") and `trialbox backup-status`.
2. From another user's shell: `sudo trialbox restore-drill <the newest .tbbak> --key <the key>`: exit 0,
   `"ok": true`.

**What is not verified.** No real Docker, cron or sudo here: the container argv (`--pull never`, the mounts, the
`--env-file`, `--user`) is shown on a stand-in only, and docker's own `--env-file` parsing (quotes kept) is the one
`update.py` already relies on. `eval`, `mail`, `model`, `omop-store` in the image are routed and their `--help` and
one call shown; their real work in the image is not run. `restore` in the image cannot ask compose which services
run (H88-04).

## Findings

| Id | Severity | Claim | Basis | State |
| --- | --- | --- | --- | --- |
| H88-01 | High | the scheduled backup run from cron's bare environment stops on "No module named 'tb_common'" | shown | fixed a6e6adc2 |
| H88-02 | Medium | `model status` and `omop-store` need psycopg and `mail` the gateway's code and pydantic: on the host's python3 each stopped on ModuleNotFoundError | shown | fixed a6e6adc2 |
| H88-03 | Medium | plain `trialbox doctor --env-file deploy/.env` on the host's python3 reports "check error: ModuleNotFoundError" for its checks that import pydantic, criteria_compiler or psycopg | shown | open |
| H88-04 | Medium | `restore` in the box image cannot ask docker compose which services run (D-724) or run `TB_DB_ROLES_CMD`: it refuses unless `--services-stopped` | hypothesis | open |
| H88-05 | Low | a missing input file (`backup-check`, `backup-verify`, `backup --public`) ends in a traceback, not a sentence | shown | open |

H84-03 and H84-04 are H-84's and go with it: the drill they were about is not carried (the installed drill of #1305
answers both on master, shown by the sudo test above). H88-04 is read from `__main__._backup_cmd` and
`backup.reapply_service_roles`, not run. H88-05 is old behaviour, seen by the probes.

## Mutation pass

18 mutants planted on the master-based build, run against `tests/unit/test_host_commands_own_environment.py`,
`test_restore_drill.py`, `test_install_faults.py` and `test_host_python_runs.py`: 18 caught. M11 survived its first
round (the box's file had already replaced the caller's `TB_IMAGE` before the image was chosen); a direct check of
`container_argv` now catches it.

| Mutant | Caught by |
| --- | --- |
| M01 a module on the caller's `PYTHONPATH` counts as the host's | `test_the_callers_path_and_settings_never_win` |
| M02 the product's path after the caller's | the same |
| M03 the caller's settings win over `deploy/.env` | the same |
| M04 the box's file applied to the module-form drill | `test_the_box_file_wins_except_for_the_module_forms_drill` |
| M05 the box's file never applied to the installed drill | the same |
| M06 `--pull missing` | `test_every_host_command_runs_from_a_bare_environment[backup-keygen, ...]` |
| M07 the DSN on the container's command line | the same |
| M08 the entry without the launcher | the same |
| M09 the container's exit code swallowed | `test_the_container_keeps_the_exit_code_...` |
| M10 never to the image | `test_every_host_command_runs_from_a_bare_environment[...]` |
| M11 the caller's `TB_IMAGE` wins | `test_the_box_file_wins_except_for_the_module_forms_drill` (second round) |
| M12 the compose network for every image command | `test_every_host_command_runs_from_a_bare_environment[...]` |
| M13 the capabilities kept | the same |
| M14 the cron template sets `PYTHONPATH` again | `test_the_installed_cron_line_runs_the_nightly_backup_...` |
| M15 the box's `deploy/.env` not read | `test_the_callers_path_and_settings_never_win` |
| M16 doctor misses the old-form file | `test_an_old_form_schedule_is_reported_and_replaced` |
| M17 `__init__` puts no `libs/` on the path | `test_install_faults.py::test_installed_nightly_command_imports_its_host_modules` |
| M18 `mail` routed without `pydantic` | `test_every_host_command_runs_from_a_bare_environment[mail]` |

## Files

`tools/trialbox/launch.py` (new), `tools/trialbox/__init__.py`, `tools/trialbox/__main__.py` (the entry block only),
`tools/trialbox/backup_schedule.py` (`cron_old_form`), `tools/trialbox/doctor.py` (the old-form WARN),
`deploy/backup/trialbox-backup.cron` (no `PYTHONPATH`), `tests/unit/test_host_commands_own_environment.py` (new),
`docs/runbook/05-updates-backup-restore-secrets.md` (one paragraph at the page's end),
`docs/decisions/D-1089-every-host-command-brings-its-own-environment.md`. Files outside the card: none (no change
to `box_drill.py`, `restore_drill.py` or their tests).
