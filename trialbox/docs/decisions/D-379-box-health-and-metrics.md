# D-379 Box health, its thresholds and /metrics

- **Task:** T-209a, monitoring part a (`docs/plan/28-master-plan-v6.md` §6.2)
- **PR:** this branch (`agent/T-209a-monitoring`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** OPS-027, OPS-030, OPS-031, OPS-032, OPS-047 (`docs/reviews/2026-11-10-deep-review/09-operations.md`)
- **Builds on:** D-178 (the operations runner and its status), D-187 and D-274 (T-117b: `backup-status`,
  `backup-last.json`), D-117 (the canary gate), D-108 (N2), D-360 (T-108a: compose limits)

## Context

Nothing on the box told a person it was unhealthy, except the backup age (OPS-027). A failed canary showed only in
the audit and on an admin tile (OPS-032). Certificate expiry was checked only when a person ran `check-tls`
(OPS-030). Disks were watched only by the backup preflight (OPS-031). Nothing proved that the backup key still read
the backups (OPS-047).

## Decision

1. **One health, five checks** in `libs/tb_common/metrics.py` (standard library only, so the host runs it): canary,
   backup, backup verified, each disk, certificate; plus a warn when the host facts are older than an hour. Levels
   ok, warn, red; the box's level is the worst check.
2. **Thresholds.** Canary red when it failed or a wake check failed. Backup red when `backup-status` alerts (36 h,
   T-117b; reused, not re-implemented). Backup verified red after 100 days, warn after 90 or never. Disk warn over
   70 %, red over 85 %. Certificate red within 30 days, warn within 45; Caddy's own certificate is ok. Each is a
   setting in `deploy/.env`.
3. **Where the facts come from.** The host runner (`trialbox ops run`, every minute) writes them into the operations
   status the console already reads: `backup_schedule.status`, `deploy/site/backup-verified.json`, `shutil.disk_usage`
   of `/`, Docker's root, the install folder, the backup targets and `TB_HEALTH_DISKS` (one per device), and the
   certificate file's end date (public; no key read). The canary comes from the orchestrator's `/models`.
4. **`backup-verify` records** its success in `deploy/site/backup-verified.json` (0600: time, file, sha256, the
   backup's own date). An audit event for it is left to T-209b or later; the file is what the check reads.
5. **Mail.** N2 begins with one translated health line; a red line sends N2 on a morning with nothing else. A new
   `HEALTH` notice goes to every administrator with a mailbox every day at `TB_HEALTH_MAIL_AT` (07:00) through the
   same `POST /notices` path (internal addresses only, at most once per person and day).
6. **`/metrics`.** The console serves the health in the Prometheus text format to a signed-in administrator or a
   bearer of the metrics token (`TB_METRICS_TOKEN_FILE`, compared in constant time). The orchestrator serves the
   canary half behind its service token (its reads are protected, D-130).
7. **Monitoring overlay** `deploy/docker-compose.monitoring.yml`: Prometheus 3.5 (LTS, pinned by digest in
   `deploy/images.lock`), loopback only, 30 days or 2 GB, with the thresholds as alert rules. Optional; the mails do
   not need it. `trialbox ops metrics-token` makes the token once.

## Consequences

- A coordinator sees "note reading was off last night" in the morning mail without opening the console.
- A box that never ran `backup-verify` shows warn from its first day; IT clears it with one key check.
- Dropped (D-311): no named reviewer for the thresholds.
