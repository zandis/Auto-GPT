# D-377 Systemd units and the egress table at boot

- **Task:** T-108b, operations in code, part b (`docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-108b-systemd`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-043, OPS-049, OPS-064 (the restart half)
- **Builds on:** D-360 (T-108a, the watchdog), D-176 (the console network and the host input chain), D-178 (`ops`)

## Context

The egress table of `deploy/egress.py` lived only in the kernel. After a reboot Docker restarted every
`unless-stopped` container with no table loaded, so the services on `egress-net` and `console-net` had a way out
until a person ran `deploy/network.sh apply` (CR-043, OPS-049). The comment in `network.sh` pointed to a unit that
did not exist. The stack did not come back in order after a host restart either (OPS-064), and the watchdog of
D-360 had no timer.

## Decision

1. **A state file.** `network.sh apply` writes the box's subnets and the applied script to
   `/var/lib/trialbox/egress-state.json` (`--state`, `TB_EGRESS_STATE`). `network.sh save` writes it without loading.
   `network.sh restore` reads only the file (no Docker) and loads the **closed** table for those subnets:
   intra-box traffic, published ports, the default deny and the host input drop, but no allow rule, because a saved
   container address may belong to another container after a reboot. A state file that is missing, names another
   table or holds a value that is not a subnet is refused, and nothing is loaded.
2. **The egress unit runs before Docker.** `deploy/systemd/trialbox-egress.service` is a oneshot with
   `DefaultDependencies=no`, `Before=docker.service trialbox.service`, `RequiredBy=docker.service trialbox.service`. It
   fails closed: without a usable state file Docker does not start (RUNBOOK §4 has the way out). Stopping the unit
   leaves the table.
3. **The stack unit.** `trialbox.service` `Requires=` and `After=` the egress unit and Docker, runs
   `docker compose --project-directory <root>/deploy up -d --pull never --wait` with the compose files and profile kept
   in `deploy/.env`, then `network.sh apply` for the new addresses. `ExecStop` is `compose stop`, so Docker does not
   start the containers by itself on the next boot; the unit does, after the table.
4. **Two timers.** `trialbox-egress-refresh.timer` runs `apply --if-changed` every two minutes (skipped when the live
   table is the saved one; a restarted container gets a new address). `trialbox-watchdog.timer` runs one watchdog
   pass every minute (D-360). With the stack down, `apply` loads the closed table of the state file, never an empty one.
5. **The installer** renders the units (`@TB_ROOT@` is the install folder) into `/etc/systemd/system` and enables the
   egress unit, the stack unit and the two timers, only after `apply` succeeded. `trialbox-ops.service` and its timer
   (RUNBOOK §15) are installed and left off.
6. **The test.** `tests/unit/test_systemd_units.py` holds the order (egress before Docker and the stack; the stack
   requires and follows egress), the timers, `systemd-analyze verify` on the rendered units when it is installed,
   and the save and restore of the table with fakes for nft and Docker.

## Consequences

- Between the boot and the stack unit's `apply`, the allowed pairs (mail, model endpoints, NHI) are closed too. That
  is a few minutes of no outbound mail after a restart, never an open box.
- A subnet that Docker gives anew (after `compose down`) is not in the state file until the next `apply`; the refresh
  timer catches it within two minutes.
- Not done here: a real power cycle on a box (T-213), and the rehearsal does not run systemd as PID 1, so the order is
  held on the unit files.
