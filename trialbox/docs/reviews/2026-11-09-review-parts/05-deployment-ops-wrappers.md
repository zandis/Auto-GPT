# TrialBox pre-release review 05: deployment, operations, scripts and wrappers

Reviewer 5 of 6. Read-only static review of `/home/user/Auto-GPT/trialbox` at origin/master `ada9c8f`
(2026-11-09). No Docker daemon, no GPU, no GCP credentials in the review container: everything below is from
reading the code and documents, `shellcheck 0.11` on every shell script, and the local `gcloud` 570.0.0 help
text for the flags proposed in §3. Nothing was edited, committed or started.

## 1. Summary

The deployment story is unusually well thought through for a product at this stage: a signed offline bundle,
tiers that install only from measured serving records, per-service tokens with a rotation command, an encrypted
backup to a key the box does not hold, a backup-first update path with a rollback point, JSON logs with a PHI
scrubber, and a generated network sheet. The documents (RUNBOOK, SECURITY, DECISIONS) are honest about what has not
run. That honesty is also the main finding: **the whole operational path (install, update, rollback, backup on a
compose box) has never executed against a real Docker daemon**; it is held by unit tests against a recording fake
and by an in-process drill. Several of the gaps below are the kind that only show up on a real host.

Counts: **0 Critical, 9 High, 19 Medium, 9 Low** (37 findings).

The five that matter most:

1. **D-01** The egress deny-list is applied once by `install.sh` and never persisted. Every reboot leaves the four
   services on `egress-net` with unrestricted outbound until someone runs `deploy/network.sh apply`.
   SECURITY.md promises a systemd unit that no script installs.
2. **D-19** There is no scheduled backup. The only automatic backup is the one taken before an update; the hand-run
   `trialbox backup` on a compose box does not work as documented (D-138 admits it), and the default target is the
   box's own disk.
3. **D-11 / D-12 / D-13** The update path has no crash-consistency (power loss leaves no marker, no resume, no
   `update status` command), no free-space preflight (a ~40 GB bundle is staged under `/tmp`), and no anti-rollback
   (an older signed bundle still applies onto a newer schema). The compose rollback itself is **unverified**
   (D-15).
4. **D-30 / D-31** Today's incident is structural, not bad luck: the paid GPU VM's only off-switch was an `EXIT` trap in
   a laptop-side process, auth was a single long-lived SA key in a `mktemp -d` config, and there was no cloud-side
   cap, no on-VM watchdog, no budget alert. §3 gives the robust pattern with exact commands.
5. **D-35** A hospital cannot tell which TrialBox release it runs: every image is tagged `1.0.0`, `__version__`,
   `pyproject` and `/healthz` say `1.0.0`, there are no git tags and no changelog; the only release identity is a
   free-text bundle id in `deploy/updates/history.jsonl`, which the console does not show.

Shellcheck: 19 notes across 17 scripts, none severe; the two that matter are listed in D-07 and D-34.

## 2. Findings

Severity: **H**igh = must fix before a hospital install; **M**edium = fix before go-live or document as an accepted
risk; **L**ow = tidy-up. Effort: S (< 1 day), M (1–3 days), L (> 3 days). "Unverified" means the behaviour was
never executed on Docker/GPU/cloud by the authors either (their own D-138/D-139 statements).

### 2.1 Install (`deploy/install.sh`, `gpu_profile.sh`, compose files, Windows/WSL2)

| ID | Sev | Area | Finding | Evidence | Failure scenario | Fix | Effort |
|---|---|---|---|---|---|---|---|
| D-01 | **H** | Install / network | The nftables egress allowlist is applied once at install and never persisted. `install.sh` does not write the systemd service/timer that SECURITY.md §2 and `egress.py` say is needed; the only cron it installs is log retention. | `deploy/install.sh:268-276`; `deploy/egress.py:17-18` ("re-run after … a container restart"); `docs/SECURITY.md` §2 ("re-apply from a systemd unit"); `deploy/check_host.sh:52-56` FAILs when the table is absent, but only when run | Host reboot or `docker compose up -d` after a secret rotation: containers get new IPs, the old table (if any) no longer matches, and criteria-compiler, orchestrator, mail-gateway and gateway (all on `egress-net`, not `internal`) have unrestricted outbound until an operator notices. The box runs for days in this state with no alert. | `install.sh` writes `/etc/systemd/system/trialbox-egress.service` (`ExecStart=/opt/trialbox/deploy/network.sh apply`, `After=docker.service`) and `trialbox-egress.timer` (`OnUnitActiveSec=5min`), enables both; `svc_secrets.restart()` and `update.py` `restart()` call `network.sh apply` after `up`; console health tile shows "egress table loaded: yes/no" (read via `nft list table` from a host-side probe or a doctor runtime check). | S |
| D-02 | M | Install | `install.sh` exits 0 and prints "TrialBox is running" although `check_host.sh` reported FAIL lines (no LUKS, swap on, egress table absent, doctor FAIL on `secure_cookie` in PRODUCTION). | `deploy/install.sh:321` (`|| echo "… fix them before go-live"`), `:323-330` | A box goes live without disk encryption or egress rules because the installer's last words were "running". | Exit 4 on any FAIL unless `--accept-host-fail` is passed; print the FAIL lines again at the end. | S |
| D-03 | M | Install / config | When `deploy/settings.yaml` exists but `deploy/.env` does not, the installer copies `.env.example` into production. Only passwords, token, `TB_ENV`, mode and profile are then rewritten; `IMAP_HOST=greenmail`, `IMAP_PASS=trialbox`, `SMTP_HOST=mailhog`, `TB_SITE_ID=DEMO-A`, `MAIL_INTAKE_ADDR=trialbox@hospa.test`, `TB_MAIL_AUTHSERV_ID=mx.hospa.test`, `TB_EMBED_MODE=hash` survive. | `deploy/install.sh:164`; `.env.example:2-20` | A re-install after an operator deleted `.env` (or restored only `settings.yaml`) silently points mail at test hosts and labels the site `DEMO-A` in every backup file name and audit line. | Refuse to continue when `settings.yaml` exists without `.env`; or re-run the wizard with `--answers` derived from `settings.yaml`. Never copy `.env.example` on a site box. | S |
| D-04 | M | Compose / resources | No production service has memory, CPU or pids limits, `read_only`, `cap_drop`, `no-new-privileges` or `security_opt`; only the developer testbench does. HAPI is bounded only by `-Xmx`; the lake by its own 40 % heuristic; vLLM runs with `ipc: host`. | `deploy/docker-compose.yml` (no `deploy.resources.limits`, `mem_limit`, `pids_limit` anywhere); `deploy/docker-compose.testbench.yml:23-26` has them | One runaway container (HAPI during a large `$everything`, or the lake on a big DuckDB spill) takes the host into OOM; the kernel kills a random container, possibly `db`, mid-write. | Add per-service `deploy.resources.limits` (memory) sized per tier in the GPU overlays, `pids_limit`, `cap_drop: [ALL]` + `security_opt: [no-new-privileges:true]` for the nine TrialBox services, `read_only: true` with `tmpfs: [/tmp]` where the Dockerfile permits. Keep `ipc: host` only on the vLLM services. | M |
| D-05 | M | Images / pinning | Image pinning is inconsistent with SECURITY.md §1 ("the vLLM image pinned by digest"): only the GB10 overlay pins vLLM by digest; base, rtx5090 and rtxpro6000 use `vllm/vllm-openai:v0.32.0` by tag. `python:3.12-slim` in `python.Dockerfile` is unpinned; `nginx:1.27-alpine`, `caddy:2`, `get.docker.com | sh` in the GCP scripts are unpinned. `make_bundle.sh` pulls by tag on the vendor side when the image is missing. Every TrialBox image is tagged `1.0.0` (see D-35). | `deploy/docker-compose.yml:233`; `rtx5090.yml:49`; `rtxpro6000.yml:31`; `gb10.yml:38` (digest); `deploy/docker/python.Dockerfile:7`; `tools/make_bundle.sh:50` | A re-tagged `v0.32.0` upstream changes the model behaviour the serving record measured; the bundle still signs whatever was pulled. | Pin every third-party image by digest (as `postgres`, `hapi`, `greenmail`, `mailhog` already are); pin the Python base by digest; `make_bundle.sh` refuses an image whose `RepoDigests` do not match the compose pin. | S |
| D-06 | L | Install / MAC | SELinux/AppArmor are not considered: bind mounts have no `:z`/`:Z`, `/dev/null` is bind-mounted as a file for the optional CA, `check_host.sh` does not run `getenforce`/`aa-status`. Fine on Ubuntu 24.04 (AppArmor default docker profile); a RHEL/Rocky host in enforcing mode denies the `settings.yaml` and `secrets/services/public` mounts. | `deploy/docker-compose.yml:24,127,160,172,193`; `deploy/check_host.sh` | A hospital that standardises on RHEL gets "permission denied" on first start with no hint. | State "Ubuntu 24.04 LTS only" in RUNBOOK §1 and make `check_host.sh` FAIL on any other distro, or add `:z` labels and a documented SELinux boolean. | S |
| D-07 | L | Scripts | Shellcheck: `install.sh:57` passes `"$@"` to `check_host.sh` after the option loop consumed it (so `--check --gb10` drops `--gb10`); `install.sh:321` SC2046 unquoted `$(…)`; SC2015 x5 (`A && B || C` used as if-then-else in `check_host.sh:35,42,71,95`, `install.sh:121`); `windows/preflight.sh:19` SC2221/SC2222 one case pattern shadows another (harmless); `gcp/hosted-demo-startup.sh:37` SC2164 `cd` unchecked while the script runs without `set -e` (a failed `cd` builds the image from the wrong directory). | shellcheck output; file:line as listed | Minor misbehaviour; the `cd` one can silently build a stale demo image. | Fix the five lines; add `shellcheck` to `make lint`. | S |
| D-08 | M | Windows / WSL2 (D-125) | The WSL2 path is groundwork only and the checklist has gaps that will fail at a real install: `check_host.sh` will FAIL "LUKS" and "swap" on every WSL2 box (no dm-crypt visible, WSL swap) so D-02 applies doubly; the nightly cron and the console timers need WSL to be running, which it is not when no user session is open and no Windows service keeps it alive; the console's LAN access requires a TLS proxy (RUNBOOK §9) but the offline media lists no proxy package and the checklist has no step for it; `OFFLINE-MEDIA.md` promises `SHA256SUMS.sig` and "the installer compares both" vendor keys, neither exists in `install.sh`. The two preflight scripts themselves are sound. | `docs/handover/WINDOWS-INSTALL-CHECKLIST.md`; `docs/handover/OFFLINE-MEDIA.md:11,23`; `deploy/install.sh:134-137`; `deploy/check_host.sh:25-30`; `deploy/windows/preflight.sh:49-51` | The first Windows install either fails the host check by design or goes live with it ignored; at 02:00 nothing runs because WSL is asleep. | Before the first Windows site: a `--wsl2` mode in `check_host.sh` (BitLocker via `manage-bde` through interop, WSL swap=0 from `.wslconfig`), a Windows scheduled task or service that keeps the distro alive (`wsl.exe -d Ubuntu -- /bin/true` at boot, or `wsl --exec dbus-launch true` under a service), the proxy package and step in the checklist, and `SHA256SUMS.sig` verification in the installer. | M |
| D-09 | L | Compose / healthchecks | `up --wait --wait-timeout` defaults to 900 s but the GB10 overlay's start periods add to 600 s (judge) + 900 s (verifier, which waits for the judge) = up to 1500 s from a cold NVMe load; a slow first boot fails the install with "the stack did not become healthy" although nothing is wrong. | `deploy/docker-compose.gb10.yml:53,91`; `deploy/install.sh:266`; `tools/trialbox/update.py:442-443` | False install/update failure on the medium tier → an unnecessary rollback (D-15 risk). | Per-profile default: `TB_INSTALL_UP_TIMEOUT` 1800 for gb10/rtxpro6000 in the overlays' comments and in `install.sh`'s case. | S |
| D-10 | M | Compose / restart policy | The rtx5090 start-order helpers (`judge-sleep-init`, `model-swap-init`, `judge-wake-init`) are one-shot (`restart: "no"`); after a power loss both vLLM servers restart (`unless-stopped`) awake side by side, which needs ~35 GiB on a 32 GB card: the verifier crash-loops. RUNBOOK §10 says "after a host reboot run up -d --wait again" but nothing automates it. | `deploy/docker-compose.rtx5090.yml:105,131,141`; `docs/RUNBOOK.md` §10 last bullet | The small tier is down after every power cut until an operator runs compose by hand. | A `trialbox.service` systemd unit (`ExecStart=docker compose … up -d --wait`, `Restart=on-failure`) owning the stack instead of per-container `unless-stopped`; it also fixes D-01 ordering. | S |

Ports: the production compose publishes only `${TB_CONSOLE_BIND:-127.0.0.1}:${TB_HOST_CONSOLE_PORT:-8090}`; the
test overlay publishes eleven ports on 127.0.0.1 with overrides; the GCP VMs publish :80. No collision found.
Idempotency: re-running `install.sh` is safe in the paths I traced (settings kept and re-validated, `.env` keys
rewritten in place, `bootstrap-admin` exits 0 when an admin exists, refdata pending files removed after load).
Root vs non-root: as non-root the egress rules, the cron and the `secrets init` chown are skipped with a one-line
warning or silently (`install.sh:268,271`); the script should refuse to run a site install as non-root.

### 2.2 Update and rollback (`tools/apply_update.sh`, `tools/trialbox/update.py`, D-138, D-140)

| ID | Sev | Area | Finding | Evidence | Failure scenario | Fix | Effort |
|---|---|---|---|---|---|---|---|
| D-11 | **H** | Update / crash consistency | No journal, marker or resume. `Updater.run` writes `history.jsonl` lines and `rollback/point.json`, but nothing reads them back; there is no `trialbox update status`, `resume` or `rollback` command. `apply_update.sh`'s trap only covers INT/TERM. | `tools/trialbox/update.py:193-258`; `tools/apply_update.sh:41,63`; `tools/trialbox/__main__.py:55-60` (no status/resume) | **Power loss mid-update**: after `docker load` retagged `trialbox-py:1.0.0` but before `up --wait`, the host reboots; `unless-stopped` containers come back on a mix of old (running container's image id) and new images; migrations may run; the operator sees a working-looking box with `history.jsonl` ending in `ok apply` and plaintext dumps on disk (D-14). Nothing says "an update is in progress and was not checked". | Write `deploy/updates/IN_PROGRESS.json` (bundle, step, point path) before `apply`, remove it after `audited update.applied`; `trialbox update status` prints it; `trialbox update rollback <bundle>` replays `Box.rollback` from `point.json`; `install.sh`/a systemd `ExecStartPre` refuses to start the stack while the marker exists without `--i-know`. | M |
| D-12 | **H** | Update / disk | No free-space preflight anywhere. The verified payloads (images ~12 GB + models ~27 GB + refdata ~2.2 GB) are staged under `${TMPDIR:-/tmp}` (tmpfs on Fedora/Arch/WSL2 configurations; Ubuntu 24.04 is disk by default), then `docker load` writes another copy, `copy_models` keeps every overwritten model aside, both databases are dumped, and the backup is written — up to 3× the bundle on one disk. `rollback-<bundle>` image tags are never pruned, so each release leaves ~12 GB behind. | `tools/apply_update.sh:40`; `tools/trialbox/update.py:136-154,327-333,366-367`; no `shutil.disk_usage`/`statvfs` in `update.py`; `docs/handover/OFFLINE-MEDIA.md:31-32` (40 GB) | **Disk full mid-update**: `docker load` or `copy_models` fails → rollback → `pg_restore` of a multi-GB HAPI dump has no space → "ROLLBACK FAILED" → the hospital must bring the sealed-envelope key and restore from the encrypted backup (if one exists, D-19). | Preflight in `Updater.run`: required = staged size × 2 + dump estimate (`pg_database_size`) + 10 %; check the Docker data root, `TB_MODELS_DIR`, `deploy/updates` and the backup target; refuse with the numbers. Stage under `deploy/updates/stage/` (same filesystem as the data), not `/tmp`. `trialbox update clean` removes `rollback-*` tags and old `deploy/updates/<bundle>/` after the next successful update, keeping one. | M |
| D-13 | **H** | Update / anti-rollback | Acknowledged in D-138 and SECURITY §6 "Not done": the manifest has `bundle_id` and `created_at` only; `verify_update.py` compares against nothing; no key id, no expiry. | `tools/sign_bundle.py:73-74`; `tools/verify_update.py:94-98`; `schemas/update_manifest*`; `docs/SECURITY.md` §6 | An older signed bundle (a stolen USB stick from the previous visit, or an engineer's mistake) is applied: services with old code start on a newer schema. `Database.migrate` returns `len(versions)` and skips, so old code runs against tables it does not know; `pg_restore` in the rollback then puts a *newer* dump back under *older* images if the check fails late. Also the vendor key cannot be retired. | `update_manifest` 1.2.0: `release_seq` (monotonic integer), `key_id`, `not_after`; `verify_update.py --history deploy/updates/history.jsonl` refuses `release_seq <= last applied` unless `--allow-downgrade` (audited as `update.downgrade`); `deploy/keys/` holds a key set with ids; `install.sh` and `apply_update.sh` pass the history. | M |
| D-14 | M | Update / PHI at rest | Plaintext `pg_dump` files of `hapi` (full FHIR: names, identifiers) and `trialbox_wf` are written to `deploy/updates/<bundle>/rollback/` (0600 root, 0700 dir). They are deleted only on success; after any failure (and with `TB_UPDATE_KEEP_ROLLBACK`) they stay forever; their deletion is not audited; there is no expiry and no `clean` command. The design reason (the box cannot read its own encrypted backup) is sound, the lifecycle is not. | `tools/trialbox/update.py:14-15,238-240,366-367`; D-138 text | Months later a disk image or a support engineer with root finds complete PHI dumps outside every retention rule and outside the audit. | Encrypt the rollback dumps with a per-update random key kept 0600 beside them (so a disk image alone is useless), or at least: delete them in the rollback path's `finally` once `check after rollback` passed, add `trialbox update clean` with a 7-day expiry run by the nightly cron, and audit `update.rollback_point.removed`. Mention them in the RUNBOOK retention table. | S |
| D-15 | **H** (unverified) | Update / rollback on Docker | `ComposeBox` and `DemoBox` have never been executed against Docker; the unit tests use a recording fake runner; the demo-VM done-check "still to run" (D-138) was not run before D-139/D-140 either. Specific untested risks: `pg_restore --clean --if-exists --single-transaction` of HAPI's several-hundred-table schema commonly exceeds `max_locks_per_transaction` (default 64 × connections) → "out of shared memory" → rollback fails; the `--clean` of a database owned by the same role while `fhir-store` is stopped but `db` keeps other sessions; `docker compose up -d --wait` after retagging must recreate containers whose image id changed (it does, but only with the same compose file set, which comes from `COMPOSE_FILE` in `.env` — absent on a box installed by hand per RUNBOOK §1 step 5); the one-off backup container uses `--network trialbox-net` and `trialbox_<vol>` names that assume project name `trialbox`. | `docs/DECISIONS.md` D-138 "Not done" and D-139 "Not run here"; `tests/unit/test_update_path.py:140-200` (fake runner); `tools/update_drill.py:24-27` ("what it cannot show"); `tools/trialbox/update.py:468-476,406-424` | The first real update at a hospital is also the first real test of the rollback. | Run `deploy/gcp/demo-vm-update.sh` (already written) **and** a compose-box drill on a Docker host (the stub profile is enough) before release: good bundle, bad migration, unhealthy release, disk-full, power-cut (kill -9 the updater at each step). Add `--jobs`-free `pg_restore` with `-1` only for `trialbox_wf`; for `hapi` use `--clean` without `--single-transaction` and raise `max_locks_per_transaction` in the db service command. Mark the result in VALIDATION. | M |
| D-16 | M | Update / failed migration | Services migrate independently at start under a per-schema advisory lock; a failure in one service after others have migrated and accepted writes (the `up --wait` window, up to 900 s) is handled by restoring **both databases from the dump**, discarding every row written in the window, while the file stores (objects, audit, lake, orchestrator dir, rulesets git) are **not** rolled back. Each migration is one transaction (good), but there is no pre-flight "migrate on a copy" and no down-migration. | `libs/tb_common/db.py:155-175`; `tools/trialbox/update.py:440-443,468-476` | A job output file exists with no row; a ruleset imported by `post_apply` into `/data/rulesets` (a git repo) survives the DB rollback; the audit chain holds events for a release that was rolled back (acceptable, but undocumented). | Keep `PY_SERVICES` stopped during `up` except a `migrate` one-shot per image (`python -m tb_common.db migrate-all`) run before any service accepts traffic; roll back file stores for `rulesets-data` (git reset to the tag taken at the rollback point) and document that objects/audit are append-only and kept. | M |
| D-17 | M | Update / refdata (D-140) | The reference pack (≈2.2 GB tar, several GB in Postgres) is `docker compose cp`'d into the criteria-compiler container's writable layer at `/tmp` and loaded in one transaction with a 7200 s timeout; the copy is never removed until the container is recreated; the pack now sits inside the rollback dumps and the backup, multiplying their size and `pg_restore` time; D-140 admits "a compose box's apply_update with a real refdata payload" was not run. | `tools/trialbox/update.py:453-457`; `deploy/install.sh:284-292`; D-140 "Pack format" and "Not done" | Update time and disk doubled; a failed refdata load after a successful image update triggers a full multi-GB rollback for a data-only problem. | Bind-mount the staged pack read-only (`-v stage/refdata:/refdata:ro` through a compose profile or `docker run` with the compiler image) instead of `cp`; load refdata as its own step with its own rollback (re-load the previous pack, which is idempotent by design) and exclude schema `refdata` from the rollback dump. | M |
| D-18 | L | Update | `install.sh` verifies the bundle twice (`--dry-run`, then real) → ~40 GB hashed twice; `apply_update.sh` leaves `$STAGE.summary.json` and the stage in `/tmp` on SIGKILL. | `deploy/install.sh:142-143`; `tools/apply_update.sh:40-63` | Minutes lost per install; stale 40 GB in `/tmp`. | Pass `--stage` once and reuse; stage under `deploy/updates/stage` (D-12). | S |

### 2.3 Backup and restore operations

| ID | Sev | Area | Finding | Evidence | Failure scenario | Fix | Effort |
|---|---|---|---|---|---|---|---|
| D-19 | **H** | Backup / scheduling | No scheduled backup exists. `install.sh` installs only the log-retention cron; RUNBOOK §5 says "then `trialbox backup --to …`" by hand; D-138 "Not done" admits the hand-run command on a compose box "still needs `pg_dump` and the database reachable from where it runs" (the host has neither); the working path (one-off container, `_backup_container`) is reachable only through an update. The default `TB_BACKUP_TARGETS=$ROOT/deploy/backups` is the box's own disk. | `deploy/install.sh:259,271-276`; `docs/RUNBOOK.md` §5 "Backup"; D-138 "Not done" bullet 5; `tools/trialbox/backup.py:24-25,58` | A disk failure between two updates loses everything since the last update; the hospital believes it has "encrypted backups to its own key" (D-126) because the install succeeded. | Promote `_backup_container` to `trialbox backup --compose` (default on a box), install `/etc/cron.d/trialbox-backup` (`02:30 … trialbox backup --compose`, after INGEST), refuse a target on the same filesystem as the Docker data root unless `--allow-local`, and make `check_host.sh` FAIL when `TB_BACKUP_TARGETS` is empty, local-only or not mounted. | M |
| D-20 | M | Backup / visibility, drills, custody | A backup failure is invisible: cron writes to a log file; there is no console tile ("last backup: when, where, result"), no `backup.failed`/`backup.ok` audit event, no admin mail. `prune` keeps the newest 14 **by count**, so 14 failed nights leave zero recent backups with no warning; a failed `.part` is removed only by the next successful prune. No restore drill is scheduled or required for a site (only the CI drill on synthetic data); nothing checks the hospital's private key still opens a current backup. Key custody: one private key, one envelope; `backup-keygen` rightly refuses overwrite, but there is no second copy, no rotation path and `secrets status` does not show the backup key's fingerprint or age. | `tools/trialbox/backup.py:428-435`; `services/console/backend.py:324-344` (health = `/healthz` only); `tools/trialbox/svc_secrets.py:280-308` | The first time anyone looks is the restore after a disaster. | `backup` writes `deploy/backups/LAST.json` (time, targets, bytes, ok/error) and appends `backup.ok|failed` to the audit; console admin tile reads it and turns red after 36 h; `logs daily` → `ops daily` that also runs the backup and mails the admin on failure via mail-gateway; RUNBOOK §6 adds a **quarterly restore drill with hospital IT** (`backup-verify` with the envelope key) to the acceptance and the yearly rotation visit; print the backup key fingerprint in `secrets status` and on the network sheet. | M |
| D-21 | L | Restore | `restore` assumes the host paths `/var/lib/docker/volumes/trialbox_<vol>/_data` (not true for Docker Desktop/WSL2 setups), does not stop the services first, and RUNBOOK §5 "Reinstall, then restore" omits `docker compose stop`. | `tools/trialbox/backup.py:58-67,463-503`; `docs/RUNBOOK.md` §5 "Restore" | Services write into directories being replaced; a WSL2 box restores into the wrong path. | `restore --compose` that stops the stack, restores through the db container and named volumes, restarts; document it. | S |

### 2.4 Observability

| ID | Sev | Area | Finding | Evidence | Failure scenario | Fix | Effort |
|---|---|---|---|---|---|---|---|
| D-22 | M | Monitoring | Logs are structured JSON with a PHI scrubber for the nine TrialBox services (good); HAPI, Postgres and vLLM log plain text. There are **no metrics** (`/metrics` does not exist), no alerting channel, and no disk, GPU or DB monitoring: the only disk check is the audit log's 64 MB floor, which turns a full disk into `AuditFull` on every audited action (an outage) with no earlier warning. The admin "health" tile is the `/healthz` of each service. | `libs/tb_common/logging.py`; `libs/tb_common/http.py:52-70`; `libs/tb_common/audit.py:108-112`; `services/console/backend.py:324-344`; no `prometheus`/`/metrics` in `services/` or `libs/` | Hospital IT finds out the disk is full when the CRC's screening list fails; nobody sees a GPU that lost its driver after a kernel update until the night canary fails. | A `runtime` section in `/healthz` of the console (free space of each data volume and backup target, last backup age, last ingest, egress table loaded, GPU memory via gateway `/v1/serving/status`, DB size and connections, container restarts) with thresholds → tile colours; optional `/metrics` (Prometheus text, admin token) for the hospital's monitoring; a daily "box health" mail to `MAIL_ADMIN_ADDR` from `trialbox ops daily`. | M |
| D-23 | M | Support diagnostics | No PHI-free support bundle. RUNBOOK §7 asks the site to send `ingest_report.json`, `docker compose ps` and a job id by hand; versions, `history.jsonl`, doctor/check_host output, scrubbed service logs, disk/GPU state and the audit verification are not collected together, and nothing redacts `.env` or `settings.yaml` for sending. D-125's "Aimedics admin app" is post-platform. | `docs/RUNBOOK.md` §7; `tools/trialbox/__main__.py` (no such command) | Support asks for "the logs" and receives `deploy/.env` or an unscrubbed HAPI log. | `trialbox support-bundle --out usb/` : release identity (D-35), `history.jsonl`, doctor + check_host output, `compose config` with secrets redacted, the last 3 collected days of the nine services' logs (already scrubbed), `audit_verify` result, `df`, `nvidia-smi`, container restart counts; a manifest of what is inside; never HAPI/Postgres logs or any `/data` file. | S |
| D-24 | L | Logs | Container logs are capped at 5 × 50 MB per service; HAPI under a large ingest can exceed 250 MB before the 00:20 collection, so the collected day has a gap; `collect` cuts by UTC day while the cron fires at local 00:20. | `deploy/docker-compose.yml:9-11`; `tools/trialbox/logs.py:92-109`; `deploy/install.sh:273` | A SIEM import shows missing hours on busy days. | Raise `max-file` for `fhir-store` and `db`, or collect twice a day; note the UTC boundary in RUNBOOK §2. | S |

### 2.5 Configuration and secrets in operations

| ID | Sev | Area | Finding | Evidence | Failure scenario | Fix | Effort |
|---|---|---|---|---|---|---|---|
| D-25 | M | Config / env sprawl | ~121 distinct `TB_*` names are read in `libs/` and `services/` (237 across the repo); configuration lives in `deploy/.env` (sent to every container through `env_file`), `settings.yaml`, per-service `environment:` blocks in five compose files, and direct `os.environ` reads. The `TB_ENV` default is **inconsistent**: `tb_common.config.environment_name` → `PRODUCTION` when unset (D-127), `egress.py:116` → `PRODUCTION`, but `tools/trialbox/doctor.py` → `DEV` when unset (lines 71, 83, 175, 214, 235). | `grep -rhoE '\bTB_[A-Z0-9_]+'` counts; `libs/tb_common/config.py:229-232`; `tools/trialbox/doctor.py:71,83,175,214,235`; `deploy/egress.py:116` | A box whose `.env` lacks `TB_ENV` (hand install per RUNBOOK §1 step 5) runs every service as PRODUCTION while `doctor` evaluates it as DEV: `secure_cookie` and `note_block` are WARN instead of FAIL, so `check_host.sh` passes a misconfigured production box. | `doctor.inputs_from` uses `environment_name`; add a `tools/envdoc.py` that lists every `TB_*` read with its default and fails `make lint` on an undocumented one; move service-only knobs out of `.env` into the compose `environment:` blocks so `.env` is the site's 20 lines. | M |
| D-26 | M | Config / unsafe defaults | Defaults that are unsafe if left: `TB_CONSOLE_SECURE_COOKIE=0` (compose default; doctor FAILs only in PRODUCTION, and see D-25); `POSTGRES_WF_PASSWORD` falls back to `POSTGRES_PASSWORD` (role password reuse); `.env.example` ships `IMAP_PASS=trialbox`, `change-me` passwords and `TB_SERVICE_TOKEN=change-me…` (accepted as a legacy token unless it starts with `change-me`, which it does — good, but fragile); `HAPI_FHIR_ALLOW_MULTIPLE_DELETE=true`; `TB_CONSOLE_FORWARDED_ALLOW_IPS` must equal the proxy or `X-Forwarded-Proto` is ignored and the Secure cookie breaks sign-in silently. | `deploy/docker-compose.yml:43,72,201,204`; `.env.example:11,40,44-48`; `tools/trialbox/svc_secrets.py:147-149` | A hand-installed or partially restored box runs with a test password or an http cookie. | `install.sh` writes `TB_CONSOLE_SECURE_COOKIE=1` by default and asks for the proxy address (or `--console-plain-http` for a single-workstation box, audited); drop the `POSTGRES_WF_PASSWORD` fallback on a site box; `check_host.sh` greps `.env` for `change-me`, `greenmail`, `mailhog`, `hospa.test` and FAILs. | S |
| D-27 | M | Secrets / rotation | `secrets rotate --service db` is not atomic: `ALTER ROLE` (both roles), then `.env` rewrite, then recreate every DB user. A failure between the first two (disk full writing `.env`, Ctrl-C) leaves the database on the new passwords and `.env` on the old ones; there is no recovery command and the message does not say what to do. The token rotation is well done (both hashes kept until the restart succeeds). Nothing rotates or reports the backup key, `site_hmac.key`/`pid_map.key` (by design), the TLS certificate (not the box's) or the vendor key. | `tools/trialbox/svc_secrets.py:221-234,237-277` | The yearly rotation visit ends with a box that cannot reach its database and an engineer reading `ALTER ROLE` syntax to hospital IT. | Write `.env` to `.env.new` first, `ALTER ROLE` in one transaction, `os.replace`, then recreate; on any error print the exact `psql` to revert; keep a 0600 `.env.pre-rotate-<ts>` for 24 h; `secrets status` lists the backup key fingerprint and age. | S |
| D-28 | L | Network sheet | The sheet matches the compose files (services, ports, published port, callers from `CALLERS`, outbound rules, secret places); `test_network_sheet.py` holds it. Gaps for the reader it is written for: it does not say that outbound enforcement depends on an nftables table that is not persisted (D-01); it omits host-level listeners (sshd, dockerd socket) and the hospital proxy's inbound; the `EGRESS_EXTRA` row ("any … site additions") is a change-controlled hole that deserves a warning; it does not list the two plaintext rollback dumps (D-14) among "secrets, names and places". | `docs/handover/network-sheet.en.md`; `tools/network_sheet.py:266-282,328-362` | IT signs off a sheet that is true only while the table is loaded. | Add a "Host" section (sshd, docker socket, nftables service state), a note on `EGRESS_EXTRA` change control, and the rollback dumps row; render the egress service status into the site sheet at install. | S |
| D-29 | M | TLS lifecycle | The product terminates no TLS: the console is `http://127.0.0.1:8090`; LAN access needs the hospital's proxy, described in one line (RUNBOOK §9) with no reference unit (Caddy/nginx config, certificate path, renewal, HSTS, `X-Forwarded-Proto`, `TB_CONSOLE_FORWARDED_ALLOW_IPS` and `TB_CONSOLE_SSO_TRUSTED_PROXIES` set to the same address), no certificate expiry check, and no proxy package in the Windows offline media (D-08). Inter-service traffic is plaintext HTTP with bearer tokens (no mTLS, acknowledged). Postgres inside the Docker network is unencrypted (acceptable). | `docs/RUNBOOK.md` §9 "Remote access"; `deploy/docker-compose.yml:195-216`; `docs/handover/OFFLINE-MEDIA.md` | Each site invents its own proxy; an expired hospital certificate takes the console down with nothing on the box to say why; a wrong `FORWARDED_ALLOW_IPS` makes every sign-in loop. | Ship `deploy/proxy/` with a Caddy compose overlay (`caddy:2.<x>@sha256`, hospital-issued cert files or internal ACME), a `doctor` check that fetches `https://<console host>/healthz` and reports certificate days-left, and a RUNBOOK §9 table of the four variables that must agree. | M |

### 2.6 Cloud wrappers and the incident (`deploy/gcp/*.sh`)

| ID | Sev | Area | Finding | Evidence | Failure scenario | Fix | Effort |
|---|---|---|---|---|---|---|---|
| D-30 | **H** | Cloud / cost control | The paid VM's only off-switch is the `EXIT` trap of a driver process on a laptop or sandbox (`finish` → `stop_vm`), plus `--after-models` which also runs on the driver. Nothing on the cloud side bounds the VM's run time (`set-scheduling --max-run-duration` is never used), nothing on the VM stops itself, and there is no budget alert. The driver was run detached (`setsid nohup`); a SIGKILL or sandbox teardown skips every trap. | `deploy/gcp/complete-run.sh:45-60,76-85,110-111`; `deploy/gcp/gpu-pro6000-run.sh` (no shutdown logic); `deploy/gcp/setup-gcp.sh` (no budget) | Observed today: 61 minutes of `g4-standard-48` (~US$2.74/h) until stopped by hand; unbounded if nobody had looked. | §3: a cloud-side hard cap set once on the VM, an on-VM watchdog in the startup script, the workload moved onto the VM, a budget alert with a Pub/Sub kill switch. | S–M |
| D-31 | **H** | Cloud / auth | Auth is a single long-lived service-account key activated into a `mktemp -d` `CLOUDSDK_CONFIG` under `/tmp` of a sandbox. The access token lives one hour; after that gcloud must mint a new JWT from the stored key. The observed "invalid authentication credentials" after ~1 h is consistent with a refresh failure — most likely sandbox clock skew (the JWT's `iat`/`exp` outside Google's window), the temp config directory being cleaned, or the key disabled; the script never probes auth, never retries, and the `stop_vm` path (`|| true`, then a 10-minute `describe` loop that also needs auth) fails silently (`WARNING … stop it by hand`, exit 3). `setup-gcp.sh` prints the SA key as base64 for pasting into a plaintext env var `GCP_SA_KEY`, grants `compute.instanceAdmin.v1`, `compute.securityAdmin`, `iam.serviceAccountUser` project-wide with `--condition=None`, and has no rotation or expiry. | `deploy/gcp/complete-run.sh:5-6,39-43,47-59`; `deploy/gcp/setup-gcp.sh:47-51,62-70`; `docs/DECISIONS.md` D-139 "The GPU run" block | The one credential that can stop the VM is the one that expired; the key printed in a terminal and stored in an env var is the project's root for VMs and firewall rules. | §3 E: the VM authenticates with its **attached** service account (metadata server, auto-refreshed, scoped to one bucket) and does the work; the driver's auth window shrinks to minutes; drive from a user login with `--impersonate-service-account` or Workload Identity Federation; delete the JSON key; a clock-skew probe before any long run; retry `activate-service-account` from the key file on 401 if a key must stay. | M |
| D-32 | M | Cloud / design | The paid VM waits on a remote driver: `complete_run.py` on a laptop/sandbox calls `http://<vm>/judge/v1` over the public internet in plain HTTP with the API key in a header through nginx :80 (the firewall rule is not in the repo; `setup-gcp.sh` mentions one); the driver's network or sleep state governs the GPU's utilisation and cost. `complete-run.sh` is not restartable: a re-run makes a new key, re-starts the VM and re-runs every part; `complete_run.py` already writes `parts/<tag>.json` per part but has no `--resume`. | `deploy/gcp/complete-run.sh:87-121`; `tools/complete_run.py:475-512`; `deploy/gcp/gpu-pro6000-run.sh:28-37` | Driver-side hiccup → idle GPU at full price; a preemption or auth failure means paying for the whole run again. | §3 C/D: run on the VM, resume from `parts/*.json` in a bucket, bind nginx to 127.0.0.1 (or remove it) once the workload is local. | M |
| D-33 | M | Hosted demo | Exposed to the internet by design (Caddy on host network :80/:443, `https://<ip>.sslip.io`, auto-TLS). Password handling: one shared password for six roles read from instance metadata `tb-admin-password` — metadata is readable by anyone with `compute.instances.get` on the project and by any process on the VM without authentication; it is passed with `-e` (visible in `docker inspect`, root only); cookies are not Secure behind TLS (acknowledged). The startup script `git clone`s GitHub at every boot and applies an **unsigned patch from metadata** (`tb-patch`) → anyone who can edit instance metadata (the deployer SA key, D-31) gets code execution on the VM. A failed image build is only logged and the old image keeps serving. One shared account + lockout after 5 failures = trivial denial of service for every demo visitor. `demo-vm-startup.sh` is better (root-only env file, no trace). | `deploy/gcp/hosted-demo-startup.sh:16-17,32-36,47,50-53,65-66`; `deploy/gcp/demo-vm-startup.sh:24-37` | A shared password leaks (it is in a project-readable field and in `docker inspect`), or a visitor locks everyone out, or a compromised SA key becomes RCE on the demo host. | Secret Manager (`gcloud secrets versions access` with the VM's attached SA) instead of metadata; per-visitor passwords or IAP/Cloud Armor allowlist in front; pin `tb-base` to a commit and drop `tb-patch` in favour of a signed bundle; lockout per source IP for the demo; fail the boot on `BUILD FAILED`; set `TB_CONSOLE_SECURE_COOKIE=1` with Caddy's `X-Forwarded-Proto` (the demo's in-process seeding over http is the stated reason — seed first, then flip the flag). | M |
| D-34 | L | Cloud / secret in logs | `gpu-sim-startup.sh` and `gpu-fit-test.sh` run with `set -x` and pass `--api-key "$KEY"` on `docker run` lines, so the model API key is traced into `/var/log/tb-startup.log` and the serial console (`getSerialPortOutput` is readable project-wide). `gpu-pro6000-run.sh` and `gpu-swap-run.sh` avoid `set -x` for exactly this reason. `curl … get.docker.com | sh` and `nginx:1.27-alpine` are unpinned. | `deploy/gcp/gpu-sim-startup.sh:4,22-25,33-36`; `deploy/gcp/gpu-fit-test.sh:15-16` | A leaked key lets anyone on the internet use the GPU at the project's expense while the VM is up. | Remove `set -x` (or `{ set +x; } 2>/dev/null` around the `docker run` lines); pass the key via `--env-file` 0600; pin images. | S |

### 2.7 Release engineering

| ID | Sev | Area | Finding | Evidence | Failure scenario | Fix | Effort |
|---|---|---|---|---|---|---|---|
| D-35 | **H** | Versioning / identity | `pyproject.toml`, `tb_common.__version__`, `/healthz` `version`, and every image tag are the constant `1.0.0`; `git tag` is empty; there is no `CHANGELOG`; `make_bundle.sh --id` is free text with no schema; the release identity exists only as `bundle_id` lines in `deploy/updates/history.jsonl` and `update.applied` audit events. The console shows no release, image digest or bundle id. `docker image ls` on a box shows `trialbox-py:1.0.0` and `trialbox-py:rollback-<id>` and nothing else. | `pyproject.toml:3`; `libs/tb_common/__init__.py:3`; `libs/tb_common/http.py:65`; `deploy/docker-compose.yml:15`; `tools/make_bundle.sh:6,74`; `services/console/app.py` (no bundle/release reference) | An auditor or a support call asks "which version is this box on?" and the answer requires root and a JSON file; two boxes with the same `1.0.0` tag run different code; a CAPA cannot name the release. | A `release.json` generated at bundle build (release id `YYYY.MM-n`, `release_seq`, git sha, built_at, image digests, model hashes) baked into the images at `/app/release.json` and shipped as an `other` payload; `/healthz` and the admin page show it; image tags `trialbox-py:<release>` with `TB_IMAGE` written to `.env` by the update; a git tag and a `CHANGELOG.md` entry per release, checked by `doclint`. | M |
| D-36 | M | SBOM / reproducibility / signing | `deploy/requirements.lock` is pinned by version but has **no `--hash`** lines; the Python base image is a floating tag (D-05); no SBOM (CycloneDX/SPDX) is produced for the images or the bundle; no build provenance; `docker save` output is not reproducible and the manifest records no git sha or builder; CI runs `e2e_simple` and the backup drill only — nothing builds the images or a bundle and nothing checks pins. Vendor signing key custody (where the Ed25519 private key lives, who may sign, offline/HSM, how it is retired) is undocumented; the manifest has no key id (D-13). | `deploy/requirements.lock` (0 `--hash`); `deploy/docker/python.Dockerfile:7`; `.github/workflows/trialbox-e2e.yml`; `tools/make_bundle.sh`; `tools/sign_bundle.py` | A hospital security office asks for the SBOM and the vendor cannot say what is in the image; a compromised build host signs a bundle nobody can distinguish from a good one. | `uv pip compile --generate-hashes`; `pip install --require-hashes`; `syft`/`docker sbom` in `make images` → `sbom.cdx.json` as an `other` payload; a CI job that builds images, verifies digests and runs `make_bundle` with a CI-only key; a one-page `docs/handover/RELEASE-PROCESS.md` (key custody, who signs, release checklist). | M |
| D-37 | L | Docs vs code | `OFFLINE-MEDIA.md` promises `SHA256SUMS` + `SHA256SUMS.sig` (Ed25519) and "the installer compares both" vendor key copies; `install.sh` checks only `<bundle>.sha256` and one `TB_VENDOR_PUBKEY` path. | `docs/handover/OFFLINE-MEDIA.md:11,23`; `deploy/install.sh:134-137` | The engineer on site looks for a check that does not exist. | Implement `SHA256SUMS.sig` verification and the two-copy key comparison in `install.sh`, or correct the document. | S |

## 3. Proposed robust cloud-run design (proposal, not a commit)

Design rule: **the paid resource must be able to stop itself without any help from the driver**, and the driver
must never hold a credential for longer than it needs one. Five layers, outermost first: (A) a cloud-side hard cap
on the instance, (B) an on-VM watchdog, (C) the workload on the VM with results in a bucket, (D) idempotent parts
that resume, (E) auth that refreshes itself, plus (F) a budget alert with a kill switch as the last net.

### A. Cloud-side hard cap (set once; survives everything)

Flags verified in this container against `gcloud` 570.0.0 (`gcloud compute instances set-scheduling --help`):
`--max-run-duration=MAX_RUN_DURATION` ("Limits how long this VM instance can run … relative to the last time when
the VM began running"), `--instance-termination-action=STOP|DELETE` ("upon VM preemption (--provisioning-model=SPOT)
or automatic instance termination (--max-run-duration or --termination-time)"). The command "can only be called on a
VM instance that is stopped (TERMINATED)", which fits: `complete-run.sh` always starts a stopped VM. The
terminationTimestamp is recomputed at every start, so the cap is per boot.

```sh
# once, VM stopped; the cap stays on the instance for every later boot
gcloud compute instances set-scheduling tb-gpu-sim --zone asia-east1-a \
    --max-run-duration=5h --instance-termination-action=STOP
gcloud compute instances set-scheduling trialbox-demo --zone asia-east1-b \
    --max-run-duration=8h --instance-termination-action=STOP
# check
gcloud compute instances describe tb-gpu-sim --zone asia-east1-a \
    --format='value(scheduling.maxRunDuration.seconds,scheduling.instanceTerminationAction)'
```

STOP keeps the boot disk with the weights (the design in RUNBOOK §11); the VM shows `TERMINATED` and stops
billing for the machine. 5 h is D-139's own worst-case estimate (4.9 h); pass `--cap 6h` for a bigger run.

### B. On-VM self-shutdown watchdog (no network, no credential)

Add to the top of `deploy/gcp/gpu-pro6000-run.sh` (and the other startup scripts), after the `exec > >(tee …)` line:

```diff
 exec > >(tee -a /var/log/tb-pro6000.log /dev/ttyS0) 2>&1
+# --- watchdog: this VM stops itself. Hard deadline from metadata tb-max-minutes (default 300), and an idle
+# deadline: no judge/verifier request in nginx's log for tb-idle-minutes (default 20) once PRO6000-RUN-READY.
+MAXM=$(curl -sf -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/instance/attributes/tb-max-minutes || echo 300)
+IDLEM=$(curl -sf -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/instance/attributes/tb-idle-minutes || echo 20)
+systemd-run --unit tb-hard-cap --on-active="${MAXM}min" --description "TrialBox hard cap" \
+    /bin/sh -c 'echo "TB-WATCHDOG hard cap reached, powering off" >/dev/ttyS0; systemctl poweroff'
+cat >/usr/local/sbin/tb-idle-watch <<'EOS'
+#!/bin/sh
+# power off when no model request has been seen for $1 minutes after the servers are ready
+idle_min=$1; ready=/run/tb-ready
+while :; do
+  sleep 60
+  [ -f "$ready" ] || continue
+  last=$(docker logs front --since "${idle_min}m" 2>/dev/null | grep -c -E '"(POST|GET) /(judge|verifier)/')
+  if [ "${last:-0}" = 0 ]; then echo "TB-WATCHDOG idle ${idle_min} min, powering off" >/dev/ttyS0; systemctl poweroff; fi
+done
+EOS
+chmod 0755 /usr/local/sbin/tb-idle-watch
+systemd-run --unit tb-idle-watch --description "TrialBox idle watchdog" /usr/local/sbin/tb-idle-watch "$IDLEM"
 KEY=$(curl -s -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/instance/attributes/tb-key)
@@
-echo PRO6000-RUN-READY
+touch /run/tb-ready
+echo PRO6000-RUN-READY
```

`systemctl poweroff` on a Compute Engine VM ends in `TERMINATED` (compute billing stops, disk kept), which is
exactly what `stop_vm` tries to achieve from outside. The two timers run as systemd transient units, so a crash of
the startup script does not kill them. With (C) below, the workload itself ends with `poweroff` on success and on
failure, so the watchdogs are only the net.

### C. Run the workload on the VM, not from a laptop or sandbox

The complete run splits naturally: `prepare` (no GPU) and the four model parts (GPU), then walk/backup/update/scale
(no GPU). Only the model parts belong on the VM; they already run as separate processes
(`complete_run.py part …`). Proposed `deploy/gcp/complete-run-vm.sh` (startup script, replaces the role of
`gpu-pro6000-run.sh` for this run; the serving part of that script is kept as-is above the marker):

```sh
#!/bin/bash
# TrialBox complete run, GPU parts, ON the VM (D-139 revision). Inputs: metadata tb-base (commit), tb-bucket,
# tb-run-id, tb-patients. Output: gs://<bucket>/runs/<run-id>/parts/*.json and report/. Ends with poweroff.
exec > >(tee -a /var/log/tb-complete.log /dev/ttyS0) 2>&1
set -u
md() { curl -sf -H Metadata-Flavor:Google "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
BUCKET=$(md tb-bucket); RUN=$(md tb-run-id); BASE=$(md tb-base); PATIENTS=$(md tb-patients || echo 50000)
finish() { rc=$?; echo "TB-COMPLETE exit $rc"; gcloud storage cp -r /opt/tb/run/parts "gs://$BUCKET/runs/$RUN/" || true
           gcloud storage cp /var/log/tb-complete.log "gs://$BUCKET/runs/$RUN/vm.log" || true
           [ -n "$(md tb-keep-alive)" ] || systemctl poweroff; }
trap finish EXIT
# (1) serving: the body of gpu-pro6000-run.sh up to PRO6000-RUN-READY, unchanged, but nginx bound to 127.0.0.1
# (2) code at the measured commit; the synthetic hospital made here (4 s per 10,000 patients, D-139)
R=/opt/tb/src; [ -d $R/.git ] || git clone -q https://github.com/zandis/Auto-GPT.git $R
git -C $R fetch -q && git -C $R checkout -q -f "$BASE"
cd $R/trialbox && uv venv --python 3.12 .venv -q && uv pip install -q --python .venv/bin/python -e ".[dev]"
mkdir -p /opt/tb/run && gcloud storage rsync -r "gs://$BUCKET/runs/$RUN/parts" /opt/tb/run/parts 2>/dev/null || true  # resume
# (3) the model parts only, resumable; key read from the local file, never from the command line
export TB_GPU_KEY="$KEY" TB_ENV=DEV PYTHONPATH=libs:services:.
.venv/bin/python tools/serving_config.py measured rtxpro6000 /root/record/serving_config.json
for part in prepare install "hospital ja" "hospital zh-TW" "public ja" "public zh-TW"; do
  set -- $part
  .venv/bin/python -m tools.complete_run part "$1" ${2:+--lang "$2"} --dir /opt/tb/run --resume --model pair \
      --patients "$PATIENTS" --judge-url http://127.0.0.1/judge/v1 --verifier-url http://127.0.0.1/verifier/v1 \
      --live-record /root/record/serving_config.json
  gcloud storage cp -r /opt/tb/run/parts "gs://$BUCKET/runs/$RUN/"      # checkpoint after every part
done
curl -fsS -o /opt/tb/run/gpu_peak.json http://127.0.0.1/record/gpu_peak.json && gcloud storage cp /opt/tb/run/gpu_peak.json "gs://$BUCKET/runs/$RUN/"
echo COMPLETE-GPU-PARTS-DONE
```

The driver (`deploy/gcp/complete-run.sh`) shrinks to: set the cap once, write metadata, start, poll `describe
--format='value(status)'` every 60 s **without holding anything open**, and when the status is `TERMINATED` pull
`gs://$BUCKET/runs/$RUN/` and run the stub parts (`walk`, `backup`, `update`, `scale`) locally with
`complete_run.py --resume`, then build the report. Proposed diff of the driver's core:

```diff
-STARTED=0
-finish() { rc=$?; if [ "$STARTED" = 1 ]; then stop_vm || rc=3; fi; rm -f "$KEYF"; exit "$rc"; }
-trap finish EXIT INT TERM
-run gcloud compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file \
-  "startup-script=$ROOT/deploy/gcp/gpu-pro6000-run.sh,tb-serving-config=$ROOT/tools/serving_config.py,tb-key=$KEYF"
-STARTED=1
-run gcloud compute instances start "$VM" --zone "$ZONE"
-… wait for PRO6000-RUN-READY, curl the record, run complete_run.py here against http://$IP …
+RUN_ID="${TB_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$(git -C "$ROOT" rev-parse --short HEAD)}"
+auth_probe   # §E: fails fast on clock skew or a dead credential, before anything costs money
+# the cap is a property of the instance; setting it again is idempotent and only allowed while TERMINATED
+run gcloud compute instances set-scheduling "$VM" --zone "$ZONE" --max-run-duration="${TB_CAP:-5h}" --instance-termination-action=STOP
+run gcloud compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file \
+  "startup-script=$ROOT/deploy/gcp/complete-run-vm.sh,tb-serving-config=$ROOT/tools/serving_config.py,tb-key=$KEYF" \
+  --metadata "tb-base=$(git -C "$ROOT" rev-parse HEAD),tb-bucket=$BUCKET,tb-run-id=$RUN_ID,tb-patients=$PATIENTS,tb-max-minutes=${TB_MAX_MINUTES:-290},tb-idle-minutes=20"
+run gcloud compute instances start "$VM" --zone "$ZONE"
+rm -f "$KEYF"                                    # the VM has it; the driver no longer needs it
+echo "started $VM; it stops itself. Resume at any time with: $0 --collect $RUN_ID"
+[ "${TB_WAIT:-1}" = 1 ] || exit 0
+# polling needs auth only once a minute; each call is short-lived and retried through auth_probe
+while :; do s="$(gcloud_retry compute instances describe "$VM" --zone "$ZONE" --format='value(status)')"
+  echo "$(date -u +%H:%M) $VM $s"; [ "$s" = TERMINATED ] && break; sleep 60; done
+gcloud_retry storage rsync -r "gs://$BUCKET/runs/$RUN_ID" "$OUT"
+for part in walk backup update scale; do "$PY" -m tools.complete_run part $part --dir "$OUT" --resume; done
+"$PY" -m tools.complete_run report --dir "$OUT"
```

Why this is robust: killing the driver at any moment costs at most the time until the VM's own `poweroff`,
`tb-idle-watch` (20 min idle) or the cloud cap (5 h) — in that order; the model API never leaves the VM (nginx on
127.0.0.1; the firewall rule for :80 can be removed); the driver's credential is used for seconds at a time.

### D. Idempotent, restartable parts

`tools/complete_run.py` already runs each part in its own process and writes `parts/<tag>.json`
(`run_all`, lines 475-512). Proposed additions (pseudo-diff):

```diff
 ap.add_argument("--after-models", default="", help=…)
+ap.add_argument("--resume", action="store_true", help="skip a part whose parts/<tag>.json exists with every check passed")
@@ def run_all / run_part
+    f = a.dir / "parts" / f"{tag}.json"
+    if a.resume and f.exists():
+        prev = json.loads(f.read_text(encoding="utf-8"))
+        if all(c[1] for st in prev["stages"] for c in st["checks"]):
+            print(f"[{i + 1}/{len(todo)}] {tag}: done earlier, kept", flush=True); rows.append(prev); continue
+    tmp = f.with_suffix(".json.part")        # write-then-rename: a killed part never leaves a half JSON
```

The VM script's `gcloud storage rsync` of `parts/` before the loop plus `--resume` makes a spot preemption or a
watchdog power-off cost only the interrupted part. `prepare` already reuses its hospital. The startup script is
re-entrant (`docker rm -f`, `mkdir -p`, `git checkout -f`). The `tb-key` is regenerated only when absent in
metadata, so a resumed run keeps the same key.

### E. Auth refresh

On the VM: no key at all. Attach a dedicated service account with `roles/storage.objectAdmin` on the one bucket
(`gcloud compute instances set-service-account tb-gpu-sim --zone … --service-account tb-runner@… --scopes
storage-rw`, VM stopped); `gcloud storage` on the VM uses the metadata server, whose tokens refresh themselves.

On the driver, three changes:

```sh
auth_probe() {   # before anything is started: a dead or skewed credential must fail here, not at the stop
  local skew; skew=$(( $(date +%s) - $(date -d "$(curl -sI https://oauth2.googleapis.com | sed -n 's/^date: //Ip' | tr -d '\r')" +%s) ))
  [ "${skew#-}" -lt 60 ] || { echo "clock skew ${skew}s: Google rejects JWTs outside ±5 min; fix the clock first" >&2; exit 5; }
  gcloud auth print-access-token >/dev/null || { echo "no usable credential in $CLOUDSDK_CONFIG" >&2; exit 5; }
}
gcloud_retry() {  # one re-activation from the key file if a call returns 401/invalid credentials, then give up loudly
  if ! gcloud "$@" 2>/tmp/tb-gcloud.err; then
    if grep -qiE 'invalid authentication credentials|UNAUTHENTICATED|Reauthentication' /tmp/tb-gcloud.err && [ -n "${TB_SA_KEY_FILE:-}" ]; then
      gcloud auth activate-service-account --key-file "$TB_SA_KEY_FILE" -q && gcloud "$@"
    else cat /tmp/tb-gcloud.err >&2; return 1; fi
  fi
}
```

Longer term: drop the JSON key. From a human session, `gcloud auth login` once and drive with
`--impersonate-service-account trialbox-deployer@…` (short-lived tokens, no key on disk); from CI, Workload
Identity Federation. `setup-gcp.sh` should stop printing the key (lines 62-70) and instead grant
`roles/iam.serviceAccountTokenCreator` on `trialbox-deployer` to the operator's user. Keep `CLOUDSDK_CONFIG` private
but put it under `$XDG_RUNTIME_DIR` or the checkout's ignored `.cache/gcloud`, not `/tmp` of a sandbox that cleans
it.

### F. Budget alert and kill switch

Flags verified against `gcloud billing budgets create --help` (570.0.0): `--billing-account`, `--display-name`,
`--budget-amount`, `--filter-projects`, repeated `--threshold-rule=percent=…[,basis=forecasted-spend]`,
`--notifications-rule-pubsub-topic`, `--notifications-rule-monitoring-notification-channels`.

```sh
BA=$(gcloud billing projects describe trialbox-demo --format='value(billingAccountName)'); BA=${BA##*/}
gcloud pubsub topics create tb-budget --project trialbox-demo
gcloud billing budgets create --billing-account="$BA" --display-name="trialbox-demo monthly" \
    --budget-amount=30USD --filter-projects=projects/trialbox-demo \
    --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 \
    --threshold-rule=percent=1.0,basis=forecasted-spend \
    --notifications-rule-pubsub-topic=projects/trialbox-demo/topics/tb-budget
```

Billing data lags by hours, so a budget is a **net, not a cap** (A and B are the cap). Add the documented Google
pattern as the last line of defence: a small Cloud Run function subscribed to `tb-budget` that, when
`costAmount >= budgetAmount`, runs `compute.instances.stop` on every RUNNING instance in the project (service
account with `compute.instanceAdmin.v1` on that project only). Keep the owner on the default IAM e-mail recipients.

### Also for the demo VM

The same four lines apply to `trialbox-demo`: `set-scheduling --max-run-duration=8h --instance-termination-action=STOP`
once; a `tb-max-minutes` watchdog in `demo-vm-startup.sh` and `hosted-demo-startup.sh`; and `demo-vm-update.sh run`
should pass `TB_DEMO_WAIT_S` and end with the stop it currently only prints ("stop the VM when finished").

## 4. Not checked

- Anything that needs a Docker daemon, a GPU or GCP credentials: compose rendering (`docker compose config`),
  `install.sh` end to end, `apply_update.sh` on a compose or demo box, `pg_restore` behaviour on HAPI's schema,
  `network.sh apply`, the demo VM, the hosted demo's live firewall rules and current metadata, and the project's
  current budget/IAM state. The gcloud flags in §3 were checked in the local SDK's help text only, not executed.
- `deploy/windows/preflight.ps1` was read, not run (no PowerShell here); `preflight.sh` was shellchecked only.
- The correctness of the services' code, the console pages, the PHI scrubber's coverage, `tools/tiers.py` and the
  settings wizard beyond retention and the CT.gov question (other reviewers' areas).
- The unit tests were not executed; counts and claims are taken from D-138/D-139/D-140 as written.
- `deploy/gcp/gpu-swap-run.sh`, `gpu-fit-test.sh` and `capture-serving-config.sh` were read for secret handling and
  shellcheck only; their measurement logic was not reviewed.
- Whether the vendor's bundle-signing key exists, where it is kept and who holds it (not in the repository; see D-36).
