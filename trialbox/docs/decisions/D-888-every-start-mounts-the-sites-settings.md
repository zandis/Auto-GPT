# D-888 every start of the box mounts the site's settings, never the example

- **Task:** SETTINGS-FILE, the integrator's red from lane G's box (#639, 2026-11-15)
- **PR:** this branch (`agent/SETTINGS-FILE-every-start-reads-the-sites`), stacked on #750 (D-887)
- **Date:** 2026-11-15
- **Status:** accepted

## Decision

1. install.sh writes `TB_SETTINGS_FILE=./settings.yaml` to deploy/.env (it only exported it): compose reads it on
   every start. A re-run exports it before the bundle step, so re-running install repairs an older box.
2. `deploy/settings_guard.sh` refuses a start whose site settings.yaml exists while compose would mount another file,
   with what to add; it follows compose's precedence (environment, then deploy/.env). The systemd unit runs it as
   ExecStartPre and tools/apply_update.sh before the update.
3. The rehearsal's reinstall leg recreates the adapter without the installer and checks it mounts deploy/settings.yaml.

## Test

`tests/unit/test_settings_file_every_start.py`: before, 10 failed; after, 10 passed.
