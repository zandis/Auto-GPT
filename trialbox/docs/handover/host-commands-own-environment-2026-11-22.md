# The host commands bring their own environment (2026-11-22)

**Reader:** the people who build TrialBox: lane H, the integrator and the independent reviewer. For builders, so in
one language.

Card H-88 (high-risk: backup, restore, the key file read on the host). The bench's install walk, step 8, on an
installed box: the scheduled backup stopped on "No module named 'tb_common'"; the restore drill the same, then on
"TB_DB_URL is not set". Built on H-84 (PR #1359, `17ddf6e43d75476bba4876bdb4b6d66ec8396336`, not on master yet),
merged with master `97048772e0bb82c2ec3d8ec0edb29983e6f9a60e`. It settles H-84's findings H84-03 and H84-04.

## Pull request body (draft)

**What changes for a box.** Nothing is typed differently. Every `python3 -m tools.trialbox ...` (the runbook's, the
installer's, cron's) now goes through `tools/trialbox/launch.py` before it does anything:

- its import path comes from its own folder: the install folder's `libs/` and the install folder first; what the
  caller's `PYTHONPATH` added from outside the install folder is dropped (`tools/trialbox/__init__.py` also puts
  `libs/` on the path for `python3 -m tools.trialbox.<module>`);
- its settings are the box's own `deploy/.env`, read by the tool: a key of that file wins over the caller's value,
  so `sudo` dropping `TB_DB_URL` no longer matters, and a caller's `TB_DB_URL`, `TB_IMAGE` or `TB_ENV` never wins
  over the box's file (no new way to override it is added);
- a command that needs what the host's `python3` does not have runs in a one-off container of the box's own Python
  image (`TB_IMAGE`, default `trialbox-py:1.0.0`, as `ops.py` and `audit_heads.py` run theirs): `--pull never`,
  `--network none` (the compose network `trialbox-net` only for `backup`, `restore`, `model`, `omop-store`, `mail`;
  `trialbox-model-net` for `eval`), `--cap-drop ALL`, `no-new-privileges`, the invoking user's uid and gid, the
  settings by `--env-file deploy/.env` (no value on a command line), and only the files its arguments name, each at
  its own path (inputs read-only; `deploy/site` read-write for a command that writes its record). Its output and exit
  code are the command's. Where the libraries are present (the image itself, a developer's interpreter) the command
  runs in place, as before. The table is `launch.COMMANDS`; a command added to the parser without its line fails
  `test_the_command_table_is_the_parsers`.

The commands that go to the image on a box: `backup-keygen`, `backup`, `backup-check`, `backup-verify`, `restore`,
`exports`, `eval`, `model`, `omop-store`, `mail`. The rest run on the host with the standard library and PyYAML.

**The restore drill** (`sudo python3 -m tools.trialbox restore-drill <file> --key <key>`, unchanged) keeps its host
part on the host with the standard library only: the space and memory checks, the lock, the sweep, the throwaway
server (H-84: `docker run` of the box's db image, `--network none`), its readiness (now `docker exec ... pg_isready`
when this process has no psycopg), its removal, the key-check record and the audit event (`restore_drill.record`
with the standard library: `audit_layout` is held to `backup.layout` by a test). Only the unpack, the restore and the
comparison run in a one-off container of the box's Python image, `tb-restore-drill-<id>-restore`, labelled like the
others (so a sweep takes it): `--network none`, `--pull never`, `--read-only`, `--cap-drop ALL` with
`DAC_READ_SEARCH` only (root must traverse the database user's 0700 socket folder), the invoking user's uid and gid,
exactly four mounts at their own paths (the backup read-only, the key read-only, the drill's 0700 unpack folder and
the throwaway's socket folder), and `PGPASSWORD`, `TB_DB_URL`, `TB_HAPI_DB_URL` by name only (the URLs give the
database names and `tb_prefix`; with no network nothing can be reached by them). It has no Docker socket, so its
`pg_restore` is relayed: the container writes a request (the flags and the dump it reads) into the unpack folder;
the host runs `docker exec -i -e PGPASSWORD <throwaway> pg_restore` (H-84's own command) with that dump as input, and
refuses anything but the drill's own restore (restore's flags, a scratch database of this drill on this throwaway's
socket, a dump of the unpack folder). The order on this path is: the throwaway starts, then the container unpacks
and restores; the in-process path (a box image, a developer's interpreter) is H-84's, unchanged.

**The scheduled backup.** `deploy/backup/trialbox-backup.cron` sets no `PYTHONPATH` any more; its lines are as
before (`cd <install folder> && python3 -m tools.trialbox backup-nightly ...`), and they work from cron's bare
environment because the tool brings its own. The update path does not rewrite the cron file (`update.py` has no
`backup-install` step), but an old file keeps working after an update: the fix is in the code it runs, not in the
line. `trialbox doctor` (check `backup`) now WARNs, in every environment, on a file of the old form ("it sets
PYTHONPATH") and names the fix.

**What an installed box does.** Apply the update. Then, as root from the install folder:
`python3 -m tools.trialbox backup-install --deploy deploy --no-first-run` replaces the cron file (doctor's `backup`
WARN goes). Nothing else.

**The invariant test (H-88):**
`tests/unit/test_host_commands_own_environment.py::test_every_host_command_runs_from_a_bare_environment`
(parametrised over `launch.COMMANDS`): every `trialbox` host command runs from a bare environment with the system
interpreter; none reads its import path, its settings or its DSN from the caller's environment
(`test_the_callers_path_and_settings_never_win`: a planted `tb_common` and `zstandard` on the caller's
`PYTHONPATH`, a caller's `TB_DB_URL` and `TB_IMAGE`: none is used). The bare environment: `PATH=/usr/sbin:/usr/bin:
/bin` with the stand-ins first, no `PYTHONPATH`, no `HOME`, cwd `/` (cron) or the install folder (the runbook), and a
"system" `python3`: a venv of the base interpreter without site packages, PyYAML linked in (what install.sh
requires), in which `psycopg`, `zstandard`, `cryptography`, `httpx` and `tb_common` do not import.

**The test the integrator asked for:**
`test_the_installed_cron_line_runs_the_nightly_backup_from_crons_bare_environment` takes the line `backup-install`
writes (rendered by `backup_schedule.install_cron`; only its log path is moved into the test's folder) and runs its
command with `/bin/sh -c` in cron's environment. The stand-in `docker` records every call, runs the db container's
snapshot script against the test's PostgreSQL (two scratch databases with synthetic rows) and the box image's
`trialbox backup` with the test's interpreter, so a real `.tbbak` is written to the off-box target and it verifies
with the test's own key. On the base (`013ea1ed`, H-84 merged with master) it fails with the bench's words:

```
AssertionError: backup-nightly: backup failed: ModuleNotFoundError: No module named 'tb_common'
    backup-nightly failed: .../trialbox-backup.log, RUNBOOK 5
```

The drill as the runbook writes it:
`tests/unit/test_restore_drill.py::test_the_drill_typed_with_sudo_as_the_runbook_writes_it_runs_from_a_bare_environment`:
`sudo python3 -m tools.trialbox restore-drill ...` from the install folder, a stand-in `sudo` that does what
`env_reset` does (`env -i` with `secure_path`, `HOME=/root`, the user's names, `TERM`), the caller's `TB_DB_URL` and
`PYTHONPATH` planted. On the base it fails with "ModuleNotFoundError: No module named 'zstandard'" (H84-03); now it
passes, the settings from the box's `deploy/.env`, nothing live touched. H-84's invariant is kept and extended:
`test_a_drill_in_the_image_never_touches_the_live_server_or_any_object_of_the_box` (pass, a failed restore, a wrong
key) holds H-84's assertions and the split's own (the container's network, mounts, environment by name, no Docker
socket); `test_a_restore_the_drill_did_not_ask_for_is_refused` holds the relay to the drill's own restore.

**What a person runs on the bench to prove it** (no Docker daemon, no cron and no sudo here: Docker, the image, cron
and sudo are stood in). As root on the installed box, after the update:

1. `python3 -m tools.trialbox backup-install --deploy deploy --no-first-run` from the install folder; then the
   04:45 line's command by hand in cron's environment:
   `env -i PATH=/usr/bin:/bin SHELL=/bin/sh sh -c "$(grep '^45 4 ' /etc/cron.d/trialbox-backup | cut -d' ' -f7-)"`,
   then `tail /var/log/trialbox-backup.log` (no "No module named"; "wrote trialbox-....tbbak") and
   `python3 -m tools.trialbox backup-status`.
2. `sudo python3 -m tools.trialbox restore-drill <the newest .tbbak> --key <the key>` from the install folder, as
   RUNBOOK §5 writes it, typed by a user other than root; exit 0, `"ok": true`; `docker ps -a --filter
   label=tb.restore-drill` empty afterwards.
3. `python3 -m tools.trialbox backup-check <the .tbbak>` and `python3 -m tools.trialbox doctor --env-file
   deploy/.env` (the `backup` line without "old form").

**What is not verified.** No real Docker: the container argv (`--pull never`, the mounts at their own paths, the
`--env-file`, `--user`, `DAC_READ_SEARCH` on the socket folder) is shown on a stand-in only, and docker's own
`--env-file` parsing (quotes are kept, unlike the shell's) is the one `update.py` already relies on. No real cron or
sudo. `eval`, `mail`, `model` in the image are routed and their `--help` and one call shown; their real work in the
image (the model network, the gateway's outbox) is not run. The drill test runs as root here; as a non-root user
H-84's chown to the database user's uid fails (H-84's, unchanged).

## Decision (lane H's number block is used up: question: a decision number)

- **Decision.** Every `trialbox` entry goes through one launcher (`tools/trialbox/launch.py`): the import path from
  its own location, the settings from the box's `deploy/.env` (the file wins), and the box image's one-off container
  for a command that needs libraries the host does not have; never a second mechanism per command. The restore drill
  is the one split: its Docker part on the host, its library part in a `--network none` container that reaches the
  throwaway's socket folder only, with `pg_restore` relayed to the host's `docker exec`.
- **Why.** The host's `python3` has the standard library and PyYAML (install.sh HOST-PYTHON, D-831); cron and sudo
  drop the caller's environment. Making each command find its own environment removes the class of fault, not one
  instance. Running the whole drill in a container would need the Docker socket inside it (a root-equivalent
  grant); running all of it on the host would need psycopg, zstandard and cryptography there.
- **Not chosen.** Installing the libraries on the host (a second, unpinned copy of what the image pins); a wrapper
  script on `PATH` (a second entry that the runbook's `python3 -m` lines would bypass); passing the DSN on the drill
  container's command line.

## Findings

| Id | Severity | Claim | Basis | State |
| --- | --- | --- | --- | --- |
| H84-03 | High | the drill typed with the host's `python3` stops on a module the host lacks | shown | fixed 3a7da014 |
| H84-04 | Medium | `sudo` drops `TB_DB_URL`, so the drill refuses at once | shown | fixed 3a7da014 |
| H88-01 | High | the scheduled backup from cron's bare environment stops on "No module named 'tb_common'" | shown | fixed 3a7da014 |
| H88-02 | Medium | `model status` and `omop-store` need psycopg and `mail` needs the gateway's code: on the host's python3 each stopped on ModuleNotFoundError | shown | fixed 3a7da014 |
| H88-03 | Medium | plain `trialbox doctor --env-file deploy/.env` on the host's python3 reports "check error: ModuleNotFoundError" for its checks that import pydantic, criteria_compiler or psycopg | shown | open |
| H88-04 | Medium | `restore` in the box image cannot ask docker compose which services run (D-724) or run `TB_DB_ROLES_CMD`: it refuses unless `--services-stopped` | hypothesis | open |
| H88-05 | Low | a missing input file (`backup-check`, `backup-verify`, `backup --public`) ends in a traceback, not a sentence | shown | open |

H88-03: the bare test of `doctor --preflight` (RUNBOOK 01's host form) is clean; the plain `doctor`'s JSON on the
host python carries those check errors. Doctor runs host checks (the cron file, the zone, the disks) and product
checks in one process; which half goes to the image is a design question (question below). H88-04 is read from
`__main__._backup_cmd` (`ComposeBox(a.deploy).running_services()`) and `backup.reapply_service_roles`, not run.
H88-05 is old behaviour, seen by the probes.

## Mutation pass

20 mutants planted, each run against `tests/unit/test_host_commands_own_environment.py` and
`tests/unit/test_restore_drill.py`: 20 caught. Two survived the first round (M10, M18: the refusal test's cases were
refused for another reason, a dump that was not there and a request of the wrong length); the test was given a dump
that is there outside the unpack folder and a request of the right length with another flag, and both were caught.

| Mutant | Caught by |
| --- | --- |
| M01 the launcher keeps the caller's `PYTHONPATH` | `test_the_callers_path_and_settings_never_win` |
| M02 its own path after the caller's | the same |
| M03 the caller's `TB_DB_URL` and `TB_IMAGE` win over `deploy/.env` | the same |
| M04 the drill's container on the compose network | `test_a_drill_in_the_image_never_touches_...` |
| M05 `--pull missing` in the launcher | `test_every_host_command_runs_from_a_bare_environment[backup...]` |
| M06 the box's DSN on the container's command line | the same |
| M07 the entry without the launcher | the same |
| M08 the container's exit code swallowed | `test_the_container_keeps_the_exit_code_...` |
| M09 the relay restores into any database | `test_a_restore_the_drill_did_not_ask_for_is_refused` |
| M10 the relay takes a dump from anywhere | the same (second round) |
| M11 the Docker socket in the drill's container | `test_a_drill_in_the_image_never_touches_...` |
| M12 never to the image | `test_every_host_command_runs_from_a_bare_environment[backup...]` |
| M13 the drill's container keeps its capabilities | `test_a_drill_in_the_image_never_touches_...` |
| M14 the cron template sets `PYTHONPATH` again | `test_the_installed_cron_line_runs_the_nightly_backup_...` |
| M15 the box's `deploy/.env` not read | `test_every_host_command_runs_from_a_bare_environment[backup...]` |
| M16 the throwaway's password on the drill container's command line | `test_a_drill_in_the_image_never_touches_...` |
| M17 doctor misses the old-form file | `test_an_old_form_schedule_is_reported_and_replaced` |
| M18 the relay takes any flags | `test_a_restore_the_drill_did_not_ask_for_is_refused` (second round) |
| M19 the box's deploy folder mounted into the drill's container | `test_a_drill_in_the_image_never_touches_...` |
| M20 the relay takes another drill's socket | `test_a_restore_the_drill_did_not_ask_for_is_refused` |

## Files

`tools/trialbox/launch.py` (new), `tools/trialbox/__init__.py`, `tools/trialbox/__main__.py` (the entry, the drill's
command), `tools/trialbox/restore_drill.py` (the split), `tools/trialbox/backup_schedule.py` (`cron_old_form`),
`tools/trialbox/doctor.py` (the old-form WARN), `deploy/backup/trialbox-backup.cron` (no `PYTHONPATH`),
`tests/unit/test_host_commands_own_environment.py` (new), `tests/unit/test_restore_drill.py` (cases added; no
assertion of H-84's changed), `docs/runbook/05-updates-backup-restore-secrets.md` (one sentence on the drill and one on
the old schedule). No runbook command text changed. Files outside the card: none.

## Questions

- question: a decision number (lane H's block is used up).
- question: H88-03, doctor's product checks on the host: run them in the box image (and the host checks on the host),
  or install nothing and keep them as check errors with the line to run them in the image?
