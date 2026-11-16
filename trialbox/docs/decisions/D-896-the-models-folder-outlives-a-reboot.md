# D-896 the models folder outlives a reboot (F15/W6)

- **Task:** WEIGHTS-AT-REBOOT, lane D backlog item 1 on #639 (2026-11-16); lane G's PoC-1 run log F15, workaround W6
- **PR:** this branch (`agent/WEIGHTS-AT-REBOOT-the-models-folder-is-kept`)
- **Date:** 2026-11-16
- **Status:** accepted

## Cause

On the GPU VM, lane G put the weights in `/models` and bind-mounted them onto `deploy/models` by hand. The bind was
gone after a reboot, so llm-service came back unhealthy on an empty folder. `deploy/poc.sh` read `TB_MODELS_DIR`
from the environment only (`poc.sh:71`) and never wrote it down. A later run, a `compose up`, `trialbox doctor --env-file
deploy/.env` or `deploy/check_weights.sh` without the variable all fell back to `deploy/models`. A relative
`TB_MODELS_DIR` also meant two folders: the preflight read it relative to the install folder, compose relative to
`deploy/`.

## Decision

1. `poc.sh` works out the models folder once (`models_dir`), always as an absolute path:
   - `TB_MODELS_DIR` as typed, relative to the install folder;
   - else the folder kept in `deploy/.env`, relative to `deploy/` as compose reads it;
   - else `deploy/models`.

   The preflight, the pin and compose (exported) all use that one folder.
2. In gpu mode, a folder other than `deploy/models` is written to `deploy/.env` as `TB_MODELS_DIR=<absolute path>`.
   There is one line, replaced rather than appended, and it is said with `ok`. Compose, a restart, the next run, the
   doctor's `weights` check and `check_weights.sh` all read it from there.
3. A models folder that is a mount point with no fstab line and no systemd mount unit gets a warning before anything
   starts. The warning says the mount is lost at the next reboot, and gives the setting that lasts.
4. RUNBOOK §9 says the same.

The bundle route (`install.sh`) loads the weights onto disk under `deploy/models` and was not affected.

**Not proven here:** a real reboot on the GPU VM (the integrator's B11 run).

## Test

`tests/unit/test_poc_gpu.py`, which uses stand-ins for docker, nvidia-smi, mountpoint, findmnt and systemctl:

- A folder given once is kept in `deploy/.env`. The next run, without the variable, checks and pins that folder, and
  the line is not appended twice.
- A relative folder is kept as an absolute path.
- A hand-made mount is warned about, with the setting to use.
