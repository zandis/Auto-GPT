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
| Back up now | the nightly's snapshot backup to `TB_BACKUP_TARGETS` (§5, D-455): no service is stopped or paused; refused while the nightly runs |
| Check the newest backups | `trialbox backup-check` on the newest file of each target, in a trialbox-py container: whole, not cut, the copies equal. The content needs the key: `backup-verify` (§5) |
| Verify this bundle | `tools/apply_update.sh <bundle> --dry-run` for a bundle copied into `deploy/updates/incoming` |
| Apply this update | `tools/apply_update.sh <bundle>` (§5: backup first, automatic rollback) |
| Apply this update in the quiet hour | the same, run by the operations timer in the box's quiet hour (`TB_UPDATE_QUIET_AT`, 05:00 for `TB_UPDATE_QUIET_HOURS` 2 by default, the site's clock) once no job runs; it waits up to 26 hours, then expires and is asked again (T-730b, D-731). The status lists it under `waiting`, with why |
| Collect yesterday's logs | `trialbox logs collect` |
| Write the network sheet again | `tools/network_sheet.py` into the folder's network part |

**The runner** is a systemd timer that runs `python3 -m tools.trialbox ops run` every minute (it needs only the
host's `python3`). `install.sh` installs `trialbox-ops.service` and `trialbox-ops.timer` from `deploy/systemd`
(D-377) and enables and starts the timer (NEW-OPS-8, D-561). The runner also writes the host's health facts: when
they are missing or more than an hour old the health line is red, and `trialbox doctor` fails its `ops_runner`
check in PRODUCTION. On a box installed before D-561, run the installer again or, as root,
`systemctl enable --now trialbox-ops.timer`. The
first run makes the folder (requests writable by the console's user, uid 10001). The page warns when the runner has
not answered for 15 minutes. A request cut off by a restart shows as interrupted and is not run again; a request
that waited more than 60 minutes (the runner was off) is not run: ask again. `python3 -m tools.trialbox ops status` prints what the page shows. Manual rollback after
a good update: apply the previous release's bundle. Restore stays a command with the key in hand (§5).

The in-process box, the demo and the tests run the same runner inside the console (`TB_OPS_RUNNER=inline`). Held by
`tests/console/test_ops_pages.py`.

## From /admin (T-209c, D-406)

The health tab of `/admin` shows a Backups tile (age of the newest backup, the last key check, the last check run
here) and an Update tile (the last bundle and how it ended, bundles waiting, rollback points), each one click from its
tab here. The Accounts tile names the locked accounts and links to **Unlock, sign-in codes and authenticators**
(`/ops/identity`), the unused-account report (`/admin/accounts`) and **Feature flags** (`/ops/flags`): a locked
colleague is two clicks from `/admin`.

Third-party logs (PostgreSQL, HAPI, the model server, Authelia, Caddy, Prometheus) are not scrubbed. `trialbox logs
collect` keeps them apart in `logs/third-party/<day>/` (0600, class D3, a `CLASS` file says so) for
`retention.third_party_logs_days` (30) days. Never forward them to the SIEM and never put them in a support bundle;
the scrubbed logs of TrialBox's own services are in `logs/services/<day>/`.

## Box health and monitoring (T-209a, D-379)

The runner also writes the box's health facts each minute: the backup as `backup-status` sees it, the last key check
of a backup, the fill of every disk the box writes to and the end date of the hospital's certificate. The console
adds the model self-test (canary) and gives one level, ok, warn or red (`libs/tb_common/metrics.py`):

| Check | Red when | Warn when | Setting |
| --- | --- | --- | --- |
| Model self-test | it failed, or a woken model failed its wake check: note reading was off last night | it has not run, is stale or checked one model | (canary, D-117) |
| Backup | `backup-status` alerts: the newest good backup is older than 36 h, or the last run failed | no good backup found | `TB_BACKUP_MAX_AGE_HOURS` |
| Backup verified | no `backup-verify` with the private key for 100 days | after 90 days, or never | `TB_HEALTH_VERIFIED_DAYS` |
| Disk | over 85 % | over 70 % | `TB_HEALTH_DISK_RED`, `TB_HEALTH_DISK_WARN`; more paths in `TB_HEALTH_DISKS` |
| Certificate | ends within 30 days | within 45 days | `TB_HEALTH_CERT_RED_DAYS`, `TB_HEALTH_CERT_WARN_DAYS` |

Where it shows:

- **The coordinators' morning mail (N2)** begins with one health line. A red line sends the mail even when nothing
  else is in it. A coordinator who sees a red line, or no line at all, tells the administrator.
- **The daily health mail** goes to every administrator with a mailbox at `TB_HEALTH_MAIL_AT` (07:00), every day,
  with one line per check.
- **`/metrics`** on the console (Prometheus text): a signed-in administrator, or a scraper with the metrics token.

`backup-verify` now writes `deploy/site/backup-verified.json` (time, file name and sha256; no content). Run it with
the key from the envelope at least once a quarter (§5).

**Optional monitoring overlay.** Prometheus on the box's loopback, scraping the console's `/metrics`, with the same
thresholds as alert rules (`deploy/monitoring/rules.yml`):

1. `sudo python3 -m tools.trialbox ops metrics-token` once. It writes `deploy/secrets/metrics.token` and never prints it.
2. Add `docker-compose.monitoring.yml` to `COMPOSE_FILE` in `deploy/.env`, after the secrets overlay, and run
   `docker compose --project-directory deploy up -d --wait`.
3. Open `http://127.0.0.1:9090/alerts` on the box (or over SSH). Hospital IT may point its own Prometheus at the
   console's `/metrics` with the same token instead.

Held by `tests/unit/test_metrics.py` and `tests/console/test_health_mail.py` (frozen clock).
