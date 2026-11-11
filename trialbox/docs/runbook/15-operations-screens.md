# 15. Operations screens (D-178)

The administrator's console has an **Operations** page (`/admin/ops`, also a tile on the health tab): the version and
the bundle last applied, backups (every target's files, the newest backup's age, red after 36 hours, the last check),
update and rollback (bundles waiting, each update's result, the rollback points kept), logs (days collected),
secrets (names, present, age; never a value) and the network sheet (en, ja, zh-TW, to download). Only the
administrator opens it (`tb_common.authz.admin_allowed`); every other role gets 403.

Each action asks first, in one sentence that names its consequence, and is an audit event (`console.ops`). The
console does not run the action itself: it leaves a request in the operations folder (deploy/ops on the host, mounted in the
console at `/data/ops`), and the host's runner runs the command this runbook already names and writes the result:

| Button | What the runner runs |
| --- | --- |
| Back up now | `trialbox backup` to `TB_BACKUP_TARGETS` (§5; the services pause a few minutes) |
| Check the newest backups | `trialbox backup-check` on the newest file of each target, in a trialbox-py container: whole, not cut, the copies equal. The content needs the key: `backup-verify` (§5) |
| Verify this bundle | `tools/apply_update.sh <bundle> --dry-run` for a bundle copied into `deploy/updates/incoming` |
| Apply this update | `tools/apply_update.sh <bundle>` (§5: backup first, automatic rollback) |
| Collect yesterday's logs | `trialbox logs collect` |
| Write the network sheet again | `tools/network_sheet.py` into the folder's network part |

**Turn the runner on once** (as root, in `/opt/trialbox`): a systemd timer that runs
`python3 -m tools.trialbox ops run` every minute (it needs only the host's `python3`). Make
`/etc/systemd/system/trialbox-ops.service` with `[Service]`, `Type=oneshot`, `WorkingDirectory=/opt/trialbox`,
`ExecStart=/usr/bin/python3 -m tools.trialbox ops run`, and `trialbox-ops.timer` with `[Timer]`, `OnBootSec=1min`,
`OnUnitActiveSec=1min`, `[Install]`, `WantedBy=timers.target`; then `systemctl enable --now trialbox-ops.timer`. The
first run makes the folder (requests writable by the console's user, uid 10001). The page warns when the runner has
not answered for 15 minutes. A request cut off by a restart shows as interrupted and is not run again; a request
that waited more than 60 minutes (the runner was off) is not run: ask again. `python3 -m tools.trialbox ops status` prints what the page shows. Manual rollback after
a good update: apply the previous release's bundle. Restore stays a command with the key in hand (§5).

The in-process box, the demo and the tests run the same runner inside the console (`TB_OPS_RUNNER=inline`). Held by
`tests/console/test_ops_pages.py`.
