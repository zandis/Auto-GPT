# D-752 Update, stop and boot at scale

- **Task:** T-695 (F-09, F-10, F-24 of `docs/reviews/2026-11-11-scale-timeouts.md`), lane B2 · **PR:** `agent/T-695-update-stop-boot-at-scale` · **Date:** 2026-11-15 · **Status:** accepted

1. A command's limit kills its whole process group (`tools/trialbox/procgroup.py`, used by the update's and the ops runner's commands): never the shell alone with the updater left running.
2. Never a stop under a running job: the update refuses before it stops the services, and an OS patch refuses before it upgrades, when a job runs or the jobs cannot be counted (as D-455).
3. The whole update's limit is the 3 h of its fixed steps plus twice the sized dump, backup and restore steps (D-455), none when a size cannot be read; the health wait is the longest start period plus retries of the compose files (`tools/trialbox/bootwait.py`), in the update, `install.sh` and the systemd unit, `TB_INSTALL_UP_TIMEOUT` still overriding.
4. The database gets `stop_grace_period: 120s` (the review's floor; an override file raises it) for its shutdown checkpoint; the systemd stop limit is above the longest grace.
5. Not in this card: every service's migrations as a step of their own (17 stores migrate at start, each as its own role, D-378/D-486); the schemas no service owns already run before the health-gated start (`orchestrator.migrate`). Tests: `tests/unit/test_t695_update_stop_boot.py` (11), `test_host_baseline.py` (+1).
