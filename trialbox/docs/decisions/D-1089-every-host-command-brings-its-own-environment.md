# D-1089 Every host command brings its own environment (H88)

- **Task:** lane H, card H-88 (the bench's install walk, step 8, 2026-11-22; the integrator's ruling of the same day:
  master's restore drill of #1305 stays, H-84's throwaway server is not carried) · **Date:** 2026-11-22
- **Status:** proposed (the integrator adds the row when merged)
- **Builds on:** D-831 (HOST-PYTHON: the host's `python3` has the standard library and PyYAML), D-274 (the backup
  schedule), #1305 (the installed `trialbox` and its box drill)

## Decision

1. Every entry of the host tool, `trialbox` on `PATH` (install.sh's link to `tools/trialbox/__main__.py`) and
   `python3 -m tools.trialbox`, goes through one launcher, `tools/trialbox/launch.py`, before it does anything.
2. **Import path.** The install folder's `libs/` and the install folder come first, found from the launcher's own
   location. What the caller's `PYTHONPATH` added comes after them and never counts as the host having a library.
   `tools/trialbox/__init__.py` puts `libs/` on the path for `python3 -m tools.trialbox.<module>` too.
3. **Settings.** The box's own `deploy/.env` (beside the launcher's install folder) wins over the caller's
   environment for each key it sets, so `sudo` and cron dropping the environment do not matter and a caller's
   `TB_DB_URL`, `TB_IMAGE` or `TB_ENV` does not override the box. A `TB_ENV` the file does not set is never the
   caller's (PRODUCTION applies). A file that is there but is not a readable regular file (a folder, a dangling
   link, unreadable), is owned by neither root nor the user running the command, or is writable by group or others
   stops the command (exit 2, nothing run); none there is no setting. One exception, #1305's own design (its review,
   item 12): the module form `python -m tools.trialbox restore-drill` keeps the caller's connection and `--dir`.
   Inside a container (the box image, `/.dockerenv`) the launcher leaves the environment as whoever started it set
   it: compose, install.sh, this launcher or the rehearsal (whose doctor blanks `TB_LLM_API_KEY` on purpose so that
   it sees the gateway's own key file, D-450). The box's file is the host's rule.
4. **Libraries.** A command that needs a library the host does not have (`launch.COMMANDS`) runs in a one-off
   container of the box's Python image, as `ops.py` and `audit_heads.py` run theirs; the runtime (`TB_DOCKER`) and
   the image (`TB_IMAGE`) are the box file's or the defaults, never the caller's: `--pull never`, `--network none`
   (the compose network only for a command that needs the database; the model network for `eval`), `--cap-drop
   ALL`, `no-new-privileges`, the invoking user's uid and gid, the settings by `--env-file deploy/.env` only to a
   command that has a network, only the files its arguments name (inputs read-only), its output and exit code
   passed through. Where the libraries are there (the image, a developer's interpreter) the command runs in place.
5. **The schedule.** The backup cron file sets no `PYTHONPATH`. `trialbox doctor` (`backup`) warns in every
   environment on a file that does; `backup-install` run again replaces it.
6. The invariant: every host command runs from a bare environment (cron's and sudo's) with the system interpreter;
   none takes its import path, settings or DSN from the caller (except item 3's module-form drill).
   `tests/unit/test_host_commands_own_environment.py::test_every_host_command_runs_from_a_bare_environment`.

## Why

The scheduled backup stopped on "No module named 'tb_common'": its line relied on cron's `PYTHONPATH` line, and a
command typed by hand from cron's line had none. Each command finding its own environment removes the class of
fault rather than one instance, and keeps the libraries the image pins off the host.

## Not chosen

- Installing the libraries on the host: a second, unpinned copy of what the image pins.
- A wrapper script per command: a second entry the runbook's lines would bypass.
- H-84's throwaway database server for the drill: the integrator kept #1305's drill.
