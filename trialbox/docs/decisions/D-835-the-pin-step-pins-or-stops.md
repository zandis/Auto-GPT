# D-835 the installer's pin step pins the pair or stops

- **Task:** I-4 of the independent examination of the bundle and installer path (2026-11-15, #639)
- **PR:** this branch (`agent/I-4-the-pin-step-pins-or-stops`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-142 (the pin step), D-831 (alive_start/alive_stop)

## Decision

1. The pin containers (`pin_model --install`, and `pin_tool`: promote, confirm, demote) run as the installer's own
   user, as the wizard, the secrets and `doctor --serving` already do. The image user (uid 10001) could not write a
   root-owned `deploy/site`: on lane G's box PermissionError on /d/site/manifests was only a warning and the install
   went on with no model pinned. The files stay readable by the services (umask 022).
2. A failed `pin_model --install` stops the install, naming the fix (weights in deploy/models, RUNBOOK §8).
3. The hashing (`--install`, `--verify-all`) and the wait for a healthy stack print a heartbeat once a minute.

## Test

`tests/unit/test_install_pin_step.py` runs the pin block with stand-ins: before, a failed pin went on and no
container ran as the installer's user; after, all pass.
