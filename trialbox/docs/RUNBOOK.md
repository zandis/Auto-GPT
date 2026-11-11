# TrialBox runbook

*Owner: Aimedics engineer. Status: living; changed in the same pull request as the code it describes. History: the git log of this file; the merge into eight documents is D-139.*

For the site's IT. Commands run on the box from `/opt/trialbox` as root unless noted. D-numbers are in
[DECISIONS](DECISIONS.md). Host hardening is in [Security](SECURITY.md); data sources in [Data](DATA.md).

## 1. Install a new site (about one day)

**Pick the tier.** The three boxes we sell install with `--tier` (D-138):

| Tier | `--gpu` profile | Box | Serving |
| --- | --- | --- | --- |
| `small` | `rtx5090` | one RTX 5090 (32 GB) | the pair with the sleep swap, 8k |
| `medium` | `gb10` | DGX Spark (GB10) | the pair resident, 16k |
| `large` | `rtxpro6000` | one RTX PRO 6000 (96 GB) | the pair resident, 32k |

A tier installs only when its profile has a serving record of its own uncapped card (`deploy/site/` or the vendor's
`deploy/measured/serving_config.<gpu>.json`, checked by `tools/serving_config.py measured`) and the machine's card
is that card. Otherwise the installer stops before it touches anything (exit 3) and says what is missing. There is no
override. `deploy/install.sh --tier large --tier-check` only asks. Today only `large` has a vendor record. To measure a
new card: a trial boot with `TB_ACCEPT_UNMEASURED_GPU=1 deploy/install.sh <bundle> --gpu <profile>`, then on the box
`python3 tools/serving_config.py capture --container judge=trialbox-llm-service-1 --container
verifier=trialbox-llm-verifier-1 --models-dir deploy/models --out deploy/site/serving_config.<profile>.json`.
`python -m tools.gpu_sizing` prints the hardware estimate. Feasibility needs no GPU; notes need one. The tier
rule is held by `tests/unit/test_install_tiers.py`.

**One command.** With the vendor's signed bundle on a USB stick:
`sudo deploy/install.sh trialbox-<version>.tar --tier large --answers site.yaml`. It verifies and loads the bundle,
runs the settings wizard, makes one token per service, starts the stack, creates the first administrator, writes the
site's network sheet to `deploy/site/network-sheet.{en,ja,zh-TW}.{md,html}` (print it for hospital IT), installs the
nightly log job and runs the host check. `--mode stub` installs a box without a GPU. The vendor builds the bundle with
`tools/make_bundle.sh` (`make release-bundle`: only images that passed the release gates). The image vulnerability
gate blocks for our images and is in report mode for the third-party ones for now; their open findings are in
`deploy/security/known-image-findings.md` (SECURITY.md §8). On Windows the box runs in WSL2: `docs/handover/OFFLINE-MEDIA.md`,
`docs/handover/WINDOWS-INSTALL-CHECKLIST.md` and `deploy/windows/preflight.ps1`.

**The same, step by step.**

1. **Host.** Ubuntu 24.04 LTS on LUKS2 with TPM2 unlock, swap off, Docker Engine 27+, nftables; the NVIDIA driver
   and container toolkit when there is a GPU (GB10: driver 580.142, held). See [Security §1](SECURITY.md#1-the-host).
2. **Images.** `tools/apply_update.sh trialbox-<version>.tar` loads images, models and approved rulesets. A
   development host can build instead: `make images` (or `make images-multiarch` for x86 and GB10).
3. **Settings.** `python -m tools.settings_wizard --out deploy/settings.yaml --env-out deploy/.env`, or
   `--answers site.yaml` (example: `tests/fixtures/onboarding/site_c_answers.yaml`). Re-check an edited file with
   `--check deploy/settings.yaml`. Mail: the hospital MTA must add an `Authentication-Results` header; answer
   `mta_authserv_id` with its first token (for example `mx.hospital.tw`). A mail command is accepted on `dmarc=pass`,
   or on an SPF or DKIM pass for the From: domain.
4. **Mapping.** Copy a template from `services/adapter/mapping/templates/` and check it against an export with
   `tools/mapping_check.py` ([Data §2](DATA.md#2-mapping-a-site)). It must report 0 missing columns.
5. **Start.** `sudo python3 -m tools.trialbox secrets init`, then `cd deploy && docker compose -f docker-compose.yml
   -f docker-compose.secrets.yml -f docker-compose.<gpu>.yml --profile gpu up -d --wait` (`--profile stub` without a
   GPU). Then `deploy/network.sh apply`.
6. **Vendor key.** Install `deploy/keys/vendor_ed25519.pub`, received out of band.
7. **First ingest.** `docker compose exec adapter python -m adapter.cli run`, or wait for 02:00. Check
   `/data/lake/ndjson/<date>/ingest_report.json`: `passed: true`, validator errors under 0.5 %.
8. **Host check.** `deploy/check_host.sh [--gb10]`: no FAIL line.
9. **Backup key.** With hospital IT, once (§5).
10. **Acceptance** before go-live (§6).

**Sign-in.** Local accounts, or the hospital's single sign-on behind its reverse proxy: set `TB_CONSOLE_SSO_HEADER`
(for example `X-Forwarded-User`), `TB_CONSOLE_SSO_TRUSTED_PROXIES` (addresses or CIDRs), optionally
`TB_CONSOLE_SSO_ROLE_HEADER` and `TB_CONSOLE_SSO_ROLE_MAP=ad-group:admin,crc-group:coordinator`. Behind TLS set
`TB_CONSOLE_SECURE_COOKIE=1`; the doctor check fails without it in PRODUCTION (D-121).

## 2. Daily operation

| When | What | Where to look |
| --- | --- | --- |
| 00:20 | `trialbox logs daily` (cron on the host): collect yesterday's service logs, prune, archive the audit | `/var/log/trialbox-retention.log` |
| 02:00 | INGEST: adapter to FHIR store and lake, 1 % validator sample, snapshot pruning | job list, `ingest_report.json` |
| 03:00 | REDCap read-back (console timer) | the study's Sources page |
| before the night's model jobs | the pair canary (54 questions); model jobs start only when it passes | `selftest.passed` in the audit |
| 05:00 | RETENTION: attachments 90 days, outputs 365 days, mail logs by country | `retention_<date>.json` |
| 07:00, 07:30 | morning mail N1 (coordinator) and N2 (investigator), console timers | Notices received |
| Mon 03:00, 03:30 | MICROBATCH and NAV per ruleset | mail |
| 1st of the month 05:30 | CALIBRATION | `calibration.json` |
| quarterly 04:00 | COHORT tables | mail |

The console's timers run when `TB_ENV` is VALIDATION or PRODUCTION (`TB_CONSOLE_TIMERS=on|off` forces it;
`TB_NOTICE_N1_AT`, `TB_NOTICE_N2_AT`, `TB_REDCAP_READ_AT` move them). Everything is a job: see it on the
administrator's Jobs page, or `docker compose exec orchestrator` with the operator token.

### Logs (D-138)

| Log | Where | Kept | How |
| --- | --- | --- | --- |
| Service logs (JSON, pseudonyms only) | containers (5 × 50 MB each), then `TB_LOG_DIR/services/<day>/<service>.log.gz` | `logs_days` (365) | `trialbox logs daily` |
| Audit chain | volume `audit-data`, copied to `TB_AUDIT_ARCHIVE_DIR/<year>/<day>.jsonl.gz` | never deleted (10 years on the box) | copied, compressed and verified nightly |
| Mail logs | trial database, schemas `mail` and `site` | `mail_log_days` (JP 1,825, TW 2,555) | RETENTION job; an unfinished send stays |
| Job outputs, attachments | objects volume | 365 and 90 days | RETENTION job; hashes kept in the audit |

Set `TB_LOG_DIR` and `TB_AUDIT_ARCHIVE_DIR` in `deploy/.env` to the hospital share. By hand:
`sudo python3 -m tools.trialbox logs collect --day 2026-11-08`, `logs prune`, `logs archive-audit`. A chain that does
not verify is not archived: run `tools/audit_verify.py` first. Never use `rsync --delete` on the audit volume.
Held by `tests/unit/test_log_retention.py`.

### EDC prefill (D-160)

Prefill is per study and **off by default**. Before a PI turns it on, check that the sponsor's acknowledgement is on
file (WS-07.7) and the site's blind re-entry record exists (WS-16.4). The REDCap target is an S36 connection (Admin,
REDCap); the token needs export and import rights on the CRF project. Data lives in schema `edc` of the trial
database (in every backup). Each step writes an `edc.*` event to the audit chain (`edc.switch`, `edc.dictionary`,
`edc.map`, `edc.drafts`, `edc.decide`, `edc.sign`, `edc.sent`, `edc.export`); a failed signing password writes
`console.edc_reauth_failed` and counts toward the account lock. If REDCap reports a conflict, the CRC settles it in
REDCap; TrialBox never overwrites a value it did not write. A `readback` result means REDCap stored something else
than was sent: stop sending for the study (switch off) and call the vendor. Note items use the gateway prompt
`crf_prefill` (role `abstract_field`); without a model, note items stay unknown with "no_model" and the rest works.
The orchestrator takes the person from the console's signed assertion (D-162); a call without one is refused with
403 `edc.actor` or `edc.role`. Signing needs the person's own delegation-log entry, and switching on needs the PI on
the log. A project with repeating instruments is refused (`edc.repeating`). Held by `tests/unit/test_edc.py`,
`tests/console/test_edc_pages.py` and e2e stage 16.

## 3. Accounts

Administrators add accounts on **Users** (`/ops/users`). The one-time password shows once, in a read-only field; hand
it over in person or by phone (D-133). Five failed sign-ins lock an account for 15 minutes; sessions end after 10
minutes idle or 8 hours; local accounts give a TOTP code after the password ([§12](#12-identity-and-tls-d-192-d-193)). Roles and the work they do: [User guide](USER_GUIDE.md). In the POC container:
`docker exec -i trialbox-console-1 python -m console.cli bootstrap-admin|add-user NAME --role ROLE|reset-password
NAME|disable NAME|list-users`.

### Build gate: the data-handling scan (D-203)

Real patient data never enters the repository, CI, a log or a support bundle (TB-SITE-03). `make data-scan` scans
every tracked file (patterns in `tools/data_scan_patterns.yaml`) for chart numbers after their label or in an HL7 PID
segment, Taiwan IDs and マイナンバー with valid check digits, Japanese insurer numbers, Taiwanese and Japanese phone
numbers, and Chinese, Japanese or katakana names beside a date (western, compact, ROC or wareki; on the same line or
up to three lines apart). Full-width characters, invisible characters, other dashes and numbers split by spaces,
dots or hyphens are normalised first; tables (`.csv`, `.tsv`, `.xlsx`, `.parquet`) are also read with each value
labelled by its column header; archives and office files are read member by member, by content as well as by name;
other encodings (UTF-16, Big5, Shift-JIS, EUC-JP, GB18030) are decoded. A binary of an unknown kind is reported as
`unscanned`. A data file type (`.csv`, `.xlsx`, `.ndjson`, `.parquet`, `.duckdb`, `.hl7` ...) outside
`tests/fixtures/`, `eval/`, `catalogue/`, `refdata/` and the reference tables `.gitattributes` names is refused. Exit
2 on a hit; the output gives the file, the line, the pattern and at most two characters at each end, never the value.
The same scan runs on a log (`python -m tools.data_scan --log make-test.log`), on a support bundle or any archive
(`python -m tools.data_scan bundle.tgz`), as the pre-commit hook (`pre-commit install --config
trialbox/.pre-commit-config.yaml`, from the repository root) and as the `data-scan` CI job. A synthetic value that
looks real goes into `tools/data_scan_allow.txt` with its reason; a real one is an incident (TB-SITE-03 §1.7).

### Build gate: the CI jobs (D-206)

`.github/workflows/trialbox-ci.yml` runs on every pull request and every push to master; its first job, `changes`,
skips the others (reported as skipped, which satisfies a required check) when a pull request touches neither
`trialbox/` nor a TrialBox workflow. `make ci` runs the same list locally. Each job has at most 15 minutes; a newer
push to a pull request cancels the older run (pushes to master are never cancelled). The required checks on master
(set by the owner in GitHub): `unit`, `lint`, `contracts`, `goldens`, `data-scan`, `e2e-simple`.

| Job | What it runs | Gates |
| --- | --- | --- |
| `lint` | ruff check and format; actionlint on the TrialBox workflows | yes |
| `types` | mypy strict on libs, services, tools, tests | yes |
| `docs` | `tools/doclint.py` | yes |
| `contracts` | `make contracts-check` (no hand-edited generated file) | yes |
| `trace` | `tools/gen_traceability.py --check` | yes |
| `unit` | `make test PYTEST_N=auto` on throwaway clusters from the runner's own PostgreSQL (`tools/pglocal.py`, server and client tools one version), `TB_DATA_DIR` in the runner's temp, then the data scan of its log | yes |
| `e2e-simple` | `make e2e-simple` (D-111) | yes |
| `goldens` | `make goldens-check` (T-006, D-205) | yes |
| `data-scan` | `make data-scan` (D-203) | yes |
| `shell` | shellcheck: errors gate, warnings listed (2026-11-09: ten in `deploy/`) | errors |
| `images` | hadolint on the three Dockerfiles | listed only (2026-11-09: first runs to triage) |

`trialbox-e2e.yml` is the nightly (and on demand): `public_e2e`, the backup drill and the update drill. The
supply-chain gates (lock current, allow-list, pip-audit, licences) are the `lock` job of `trialbox-supply-chain.yml`
(D-185, D-186), not repeated in `trialbox-ci.yml`.

## 4. Troubleshooting

| Symptom | Check | Fix |
| --- | --- | --- |
| No reply to a mail | `docker compose logs mail-gateway --since 1h` | sender not allowed, SPF/DKIM failed, or the rate limit; the log says which (no PHI) |
| "Today's limit is reached" on the console | `settings.yaml`: `rate_limit_per_sender_per_day`, `rate_limits_per_day` | the limit counts each heavy run type (FEAS, SCREEN, COHORT, NAV, MICROBATCH, CALIBRATION) per sender per 24 h; raise it, or set `rate_limits_per_day: {SCREEN: 40}` (0 = no limit) and restart the orchestrator (D-146) |
| "Ruleset X has no approved version" | `git -C /data/rulesets tag` | paste the protocol, then the investigator approves on S20 |
| Ingest `passed: false` | `ingest_report.json` → `errors` | the hospital changed its export: run `mapping_check.py`, fix the site mapping |
| Equivalence gate under 98 % | the review sheet "equivalence" | edit or reject the flagged criteria |
| SUBMIT refused | the reply names the check | NAV older than 14 days: rerun NAV |
| Lake slow or out of memory | `docker stats` | raise `TB_LAKE_MEMORY_LIMIT` (default 40 % of RAM; spills to `/data/lake/tmp`) |
| A job fails with `LAKE-LIMIT` | the job's error; `df -h /data` | the query hit its spill cap (`TB_LAKE_MAX_TEMP`, default a quarter of the free disk, at most 50 GB; `TB_LAKE_TEMP_DIR` moves the spill) and was stopped before it filled the disk. Usually a join that multiplies rows: report it; raise the cap only for data that really is that large |
| Containers lost egress after a restart | `deploy/network.sh status` | `deploy/network.sh apply` |
| `CERTIFICATE_VERIFY_FAILED` | hospital TLS inspection | put the hospital CA on the host, set `TB_EXTRA_CA=/abs/path/ca.pem` in `deploy/.env`, `docker compose up -d` |
| Many patients "need information" with "a result is in a unit that cannot be compared" | the lab's unit in the feed against the criterion's unit (`mapping_check.py`; `unit_defaults` in the site mapping) | declare the site's unit for that analyte, or ask the vendor for a tested factor (D-275); the patients are never excluded for it |
| Many orders or results read as unknown after an ingest | `mapping_check.py` lists status codes outside the map; the lake's `medication.status` = `unknown` | the HIS sends a status code the site mapping does not know: add it to the `status` / `result_status` map (an unknown code never counts as given or as final; D-275) |
| Many patients "need information" with "a medicine order has no end date" | the feed's order rows: no end date, or no date at all | map the order's end (or days of supply) in the site mapping (D-275) |
| Notes never exclude | `selftest.failed` in the audit, the admin health tile | the pair canary failed: check the models (§8, §10) |
| Notes never exclude; the run says "the verifier is not a second model" | `llm.pair.same_model` in the audit, `trialbox doctor` (`note_block` FAIL) | the verifier is the judge again (the same model name, alias, build or weights), or its endpoint does not say which weights it serves (`/models`). A note answer needs two different models (D-276): name a different verifier (`TB_GATEWAY_VERIFIER_MODEL`, or `LLM_VERIFIER_BASE_URL` with its own `LLM_VERIFIER_MODEL`), or set `TB_NOTE_BLOCK=never` on purpose |
| A screening run fails "the model did not answer"; rows say "not checked (system busy)" | the gateway log (`upstream_failed` on a judge call), `llm.gateway.call` with `fallbacks` | the judge's server is down or erroring. A judge call is never answered by the verifier build instead (D-276, LLM-002): bring the judge back, then send the request again |
| A tool imports the wrong code | the venv has another checkout installed | set `PYTHONPATH=libs:services:.` (the Makefile does) |
| Test ports taken | | `TB_HOST_<NAME>_PORT` in `deploy/.env` |

A failed job names its step (received, parsing, compiling, running, reporting) and the requester gets a plain
"Failed" mail.

## 5. Updates, backup, restore, secrets

**Updates** (D-138, D-210): `sudo tools/apply_update.sh trialbox-<version>.tar --dry-run`, then without `--dry-run`.

The order of a release across the acceptance box and the sites (three working days apart), who applies it on site
and what is filed: `docs/validation/change-control.md` §4 (D-344).

1. **Checked before anything changes.** The bundle is verified with a vendor key the box trusts (the signature,
   `key_id`, every sha256 and size), `not_after` (an expired bundle is refused), `release_seq` above the installed one,
   `min_installed_version`, the compatibility table `compat.json` (schema versions, vocabulary release, model pin,
   prompt registry), the image digests of `release.json` against `images.lock` (a digest not pinned is refused), and
   the free space on every disk it writes, with the numbers (`needs 13.5 GB …, free 4.2 GB`). Any refusal: exit 1,
   nothing changed.
2. **Backup first** to `TB_BACKUP_TARGETS` with `deploy/secrets/backup.pub`. No key or no target: the update refuses.
3. **Rollback point:** replaced images tagged `<repo>:rollback-<bundle>`, overwritten models kept, both databases
   dumped locally and encrypted with a key made for this update, the rulesets repository tagged.
4. **Apply:** images loaded, models copied, `docker compose up -d --wait` (services migrate at start), rulesets
   (approval and equivalence gates), health check, then the reference data pack as its own step (if only that fails,
   the new release stays and the pack waits in `deploy/refdata/pending`).
5. `update.applied` in the audit; the rollback point (dumps and key) deleted. A failure in step 4 before the reference
   data puts images, models, databases and rulesets back, restarts, checks and writes `update.rolled_back`; exit 1. If
   the backup or the rollback point fails, the stopped services are started again and nothing else changed.

**After the update that brings D-275, run one ingest** (the nightly one is enough). Until then the lake still holds records the new rule leaves out (a result entered in error, a cancelled order, a sex of `other` / `unknown` as text), and orders with no date that the old ingest dropped are only read again when the source sends them. Approved rulesets need no new approval: their SQL runs guarded by the current rules (`criteria_compiler/compile_sql/overlay.py`) until they are next compiled.

**While an update runs** `deploy/updates/IN_PROGRESS.json` names the bundle and the step. It is removed only when the
update or its rollback completed; while it exists no other update starts. After a power cut or a killed update:

| Command | What it does |
| --- | --- |
| `tools/apply_update.sh status` | the bundle, the step it stopped at, running or interrupted, the installed `release_seq`, the trusted keys |
| `tools/apply_update.sh rollback <bundle>` | puts the box back as before that update (or only restarts the services, if it stopped before the rollback point), audits it, removes the marker |
| `tools/apply_update.sh clean` | removes left-over rollback points of finished updates |
| `python3 -m tools.update_status check` | exit 3 while an update is unfinished (a start guard) |

**Older releases.** A bundle with a `release_seq` not above the installed one is refused. Only on the vendor's written
instruction: `tools/apply_update.sh <bundle> --allow-downgrade "<ticket and reason>"`; the audit gets
`update.downgrade`. A bundle that does not know the box's schema version is refused even then.

**Vendor keys.** The box trusts at most two keys (`deploy/updates/trust.json`; before the first update,
`deploy/keys/vendor_ed25519.pub` and `vendor_ed25519.next.pub`). The vendor changes keys with a rotation bundle, signed
by a trusted key, applied like any update and accepted once; a retired key is never trusted again.

Every step is in `deploy/updates/history.jsonl`; `deploy/updates/installed.json` records what is installed.
`--no-backup` is for a test box only and is audited. If the rollback itself fails, the marker stays: restore from the
backup. Driver updates are outside the bundle and need a change request. Held by `tests/unit/test_update_path.py`,
`tests/unit/test_update_safety.py` and `tools/update_drill.py`.

**Backup** (D-126, D-187, D-188). Once, with hospital IT: `python -m tools.trialbox backup-keygen --private
/media/usb/trialbox-backup.key --public deploy/secrets/backup.pub`. The private key goes in their sealed envelope; the
box keeps only the public key and cannot read its own backups. A backup (`.tbbak`) holds the trial and HAPI
databases, every data folder and a manifest, compressed with zstd level 3 on every core and then encrypted
(AES-256-GCM to an X25519 key). The box keeps running: each database is dumped and counted in one database snapshot,
and a file that changes while it is read is read again. Left out on purpose: the vendor reference pack's rows (public;
the pack file is kept in `deploy/refdata/loaded` and loaded again by the restore; the hospital's own reference rows
are in the backup), the lake's NDJSON except that of `CURRENT` and the two newest snapshots (every Parquet and DuckDB
file and every report is kept), the lake's `tmp/` spill and half-built snapshots. The manifest lists what was left
out, the sha256 and size of every file and the rows of every table. `<file>.sha256` beside each backup marks it
complete (`sha256sum -c` works on it). The ruleset repository `/data/rulesets` is in it; it is also a git repository
you may push to the hospital's git server.

1. **Targets.** In `deploy/.env`, `TB_BACKUP_TARGETS=<NAS share> <USB disk>` (keep the newest `TB_BACKUP_KEEP`, 14,
   of this box's files; other boxes' files on the same share are never touched). At least one must be **off-box**:
   an NFS or SMB share, a USB disk, or a path hospital IT names in `TB_BACKUP_OFFBOX` (e.g. an iSCSI volume in
   another room; on Windows/WSL2 a share mapped as a drive letter). A named path counts only on another device than
   the box's own disk, or when hospital IT puts a file `.trialbox-offbox` in it. In PRODUCTION a box whose targets
   are all on its own disks still writes the backup, but the run fails and stays red.
2. **Schedule.** `deploy/install.sh` installs it (D-274): as root in the install folder it runs `python3 -m
   tools.trialbox backup-install --deploy deploy`, which writes `/etc/cron.d/trialbox-backup`, turns WAL archiving
   on when it can (below), and runs the first backup once the backup key is there (run the command again after
   `backup-keygen`). In PRODUCTION it refuses without an **alert route**: `TB_BACKUP_ALERT_CMD` (a command that
   reads the message on stdin), or `TB_BACKUP_MAILTO` on a host with a mail transfer agent. The cron runs
   `backup-nightly` at 04:45 (move it after the night's jobs) and `backup-status --quiet` every hour. A run checks
   free space first, never runs twice at once, and pauses every service but `db` while it reads, so the databases
   and the files are of one point in time (`TB_BACKUP_QUIESCE=off` leaves them running). Each backup also holds a
   `host` part: `deploy/.env`, the settings file, `deploy/site`, `deploy/secrets` (the pgBackRest cipher) and the
   Authelia and Caddy volumes. The result is in `deploy/site/backup-last.json` and the audit (`backup.done`,
   `backup.failed`). `trialbox doctor --env-file deploy/.env` FAILs in PRODUCTION without an off-box target, an
   alert route or the cron file, and when the newest good backup is missing or too old.
3. **Age alert.** `python3 -m tools.trialbox backup-status` shows the newest good off-box backup (the one
   `backup-last.json` records, with the same name, size and sha256 on the share) and its age. It turns red (exit 1)
   when that backup is older than `TB_BACKUP_MAX_AGE_HOURS` (36) or dated in the future, when the last nightly run
   or its pgBackRest step failed, or when WAL archiving fails, is off on the server, or has archived nothing for 26
   hours. Red is audited (`backup.alert`, again every 24 h, `backup.alert_cleared` when it ends), mailed by cron to
   `MAILTO`, and piped to `TB_BACKUP_ALERT_CMD` when set (a command that reads the message on stdin, e.g. the
   hospital's mail tool). The message holds no patient data. Fix the cause, then run `backup-nightly` by hand.
4. **Check a backup** with hospital IT: `trialbox backup-verify <file> --key <private key>` (reads it all, checks
   every hash and the sidecar). A backup made before D-187 (layout 1, gzip or zstd) still verifies and restores.

**Point-in-time restore (pgBackRest).** On by default (D-274): `backup-install` does steps 2 to 4 below by itself
when the db image carries pgBackRest and a target is off the box (the repository goes to `TB_PGBACKREST_REPO`, else
`pgbackrest-<site>` on the first off-box target), unless `deploy/.env` says `TB_PG_ARCHIVE_MODE=off`; when the check
fails it turns archiving off again. The default db image has no pgBackRest yet, so step 1 is still needed; `doctor`
warns while archiving is off. The `db` service compresses WAL with zstd and TOAST with lz4 and
gives new databases data checksums. Three weekly full backups are kept, so the database restores to any second of at
least the last two weeks:

1. Build the image with pgBackRest: `docker build -t trialbox-db-pitr:16 deploy/pgbackrest`; in `deploy/.env` set
   `POSTGRES_IMAGE=trialbox-db-pitr:16` and `TB_PGBACKREST_REPO=<a folder on the hospital share>`.
2. The repository key: `install -d -m 700 deploy/secrets/pgbackrest; (umask 077; printf '[global]\nrepo1-cipher-pass=%s\n'
   "$(openssl rand -base64 48)" > deploy/secrets/pgbackrest/cipher.conf)`, then give the file and the repository
   folder to the container's postgres user (`docker compose --project-directory deploy exec db id -u postgres`, then
   `chown -R <uid> ...`). Hospital IT keeps a copy of the key with the backup key: the box holds this one, unlike the
   `.tbbak` key, and without it the repository cannot be read.
3. `docker compose --project-directory deploy up -d db`, then `docker compose --project-directory deploy exec -u
   postgres db pgbackrest --stanza=trialbox stanza-create`.
4. Only now set `TB_PG_ARCHIVE_MODE=on` in `deploy/.env`, run `docker compose --project-directory deploy up -d db`
   (it recreates `db` with the new setting; a plain restart keeps the old one) and run `... pgbackrest
   --stanza=trialbox check` (it must say the WAL segment was archived). Never turn archiving on before: with
   archiving on and no working pgBackRest, Postgres keeps every WAL file until the disk is full (`backup-status`
   turns red first). `backup-nightly` then takes a full backup on Sundays (`TB_PGBACKREST_FULL_DAY`, the box's local
   day) and a differential on other days.
5. **To restore to a time:** stop the services, then `docker compose --project-directory deploy stop db`, `docker
   compose --project-directory deploy run --rm -u postgres db pgbackrest --stanza=trialbox --delta --type=time
   "--target=2026-11-08 14:05:00+09" --target-action=promote restore`, and start everything again. Then run
   `backup-nightly` so a new full chain starts.

**Restore.** Bring three things: the backup file, the private key (hospital IT) and **the vendor reference data
pack** the backup names. A backup holds no vendor pack rows (layout 2, above), so a restore onto a fresh box is not
whole without the pack (DATA-018). To see which pack: `trialbox backup-verify <file> --key <private key>` lists it
under `refdata_packs` (`pack_id`, e.g. `trialbox-refdata-20261109`; a pack of `origin: site` is the hospital's own
and comes back with the database). The vendor pack is a `.tar` file (usually `<pack_id>.tar`; the restore reads the
`pack_id` inside it), in the update bundle that installed it (its `refdata:` items), in `deploy/refdata/loaded` of the
old box, or from the vendor. Keep a copy of `deploy/refdata/loaded` beside the off-box backups. Then:

1. Reinstall (§1) and put each `<pack_id>.tar` in `deploy/refdata/loaded` (or a folder you give as `--refdata`).
2. `trialbox restore <file> --key <private key> --yes [--refdata <folder>]`. Every hash is checked first; a
   backup of another site (`--other-site`) or older than 14 days (`--older-ok`) is refused before anything changes.
   A box that holds data is first kept whole as one more encrypted backup in `--keep-to` (default
   `deploy/pre-restore`, with the box's public key `--public`; `--no-copy` skips it): if the restore then fails,
   the message names that file, and `trialbox restore <it>` puts the box back. Each database is emptied, restored
   and its rows checked before any folder moves; replaced folders are moved aside, not deleted. The restore is a
   `backup.restored` event in the restored audit log. Add `--dir host=<folder>` to get the `host` part back. The
   restore loads the packs the backup names from that folder.
3. If a pack is not there the restore says which (`refdata.missing`, e.g. `['trialbox-refdata-20261109']`) and exits
   3 (`ok=False`; the database rows themselves are already restored and equal): put that pack file in the folder and
   run the restore again. Rows that do not match the backup fail the restore; a backup made before
D-187 or by the update path, counted on a running box, gives a warning instead. Held by `tests/unit/test_backup.py`,
`tests/unit/test_backup_schedule.py` and `tools/backup_drill.py` (`make backup-drill`: the nightly run, layout,
status and alert, wipe, restore with the pack loaded again, an old-format restore, the Postgres settings and a
point-in-time recovery).


### Secrets (D-128, D-138): the one place to rotate them

| Command (as root, in `/opt/trialbox`) | What it does |
| --- | --- |
| `python3 -m tools.trialbox secrets status` | each token's file, mode and age; never a value |
| `python3 -m tools.trialbox secrets rotate` | **at handover, then yearly**: every service token, the operator token and both database passwords |
| `... secrets rotate --service orchestrator` | one service's token; only it restarts |
| `... secrets rotate --service db` | the two database passwords (`ALTER ROLE`, on stdin) |
| `... secrets init` | make any missing token and the orchestrator's actor key (the installer runs it; run it once on a box updated past D-143, else chart-number reveals and exports are refused) |

The mail passwords and a cloud-model key are the hospital's: change them at their source, put the new value in
`deploy/.env`, then `docker compose --project-directory deploy up -d --force-recreate mail-gateway` (or `gateway`). A
box installed before step 8 keeps its shared `TB_SERVICE_TOKEN` (with a warning) until the first full rotation. The
administrator's token for scripts is `deploy/secrets/services/operator.token` (header `X-TB-Service-Token`).

## 6. Go-live acceptance

`tools/acceptance.py` writes one result per criterion under `acceptance/`; `tools/acceptance.py report` sums them.

1. `ingest --report <ingest_report.json>`
2. `feas --system <FEAS raw json> --manual manual_counts.csv` (the CRC's own funnel)
3. `screen-sample --candidates <candidates.json> --ruleset rulesets/<ID> --scoped scoped.txt --n 120` makes the
   blinded `adjudication.xlsx`; when the CRC has filled it: `screen --candidates … --adjudication adjudication.xlsx
   --key adjudication_key.json`
4. `nav --lake <lake> --ruleset rulesets/RA-BIO` (12 months against NHI outcomes)
5. `twpas twpas_validation_*.json`
6. `reproduce --results rerun.jsonl`, after `docker compose exec orchestrator python -m orchestrator.rerun <job ids>
   > rerun.jsonl`
7. `audit --dir <audit copy>`

Also run `make test-egress` (§1 of [Security](SECURITY.md)) and keep the host check output.

## 7. Contacts and escalation

- Box contact: `settings.site.contact`. Vendor support: send `ingest_report.json`, `docker compose ps` and the failing
  job id, **never** patient lists or the pid map.
- Suspected PHI exposure: stop mail (`docker compose stop mail-gateway`), keep the box running for the audit, follow the
  hospital's incident procedure. The audit shows every output file, its sha256 and its recipients.

## 8. DGX Spark end to end

```sh
make spark-e2e                       # GB10: the pinned judge and verifier
TB_LLM_MODE=stub make spark-e2e      # any Docker host, no GPU: the stub
```

`tools/spark_e2e.sh` runs: host check (`deploy/check_host.sh --gb10`) → `make images` → `tools/pin_model.py` pins both
models into `deploy/site/registry.site.yaml` → compose up with `docker-compose.gb10.yml` → gateway probe → `trialbox
doctor` → ingest → `FEAS GZQO` by mail → `tools/cascade_e2e.py` through the gateway → `make eval-public` → workflow
store tests. PASS means every step passed and every answer came from the pinned build (sha256). The report is in
`build/spark-e2e/<time>-<mode>/report.md`.

**Prerequisites.** Driver 580.142 held (`apt-mark hold`; later 580.x builds break vLLM on GB10, D-79);
`nvidia-container-toolkit`; amd64 emulation for MailHog (test profile only); weights (safetensors or GGUF, never
pickle or Python files) in `deploy/models/gemma-4-26b-a4b-it-4bit` and `deploy/models/qwen3.5-9b-4bit`; about 55 GB of
disk. Spark memory as set, not yet measured on a Spark: `JUDGE_GPU_MEM_UTIL` 0.30, `VERIFIER_GPU_MEM_UTIL` 0.15.

**Pinning by hand.**

```sh
python -m tools.pin_model --build gemma-4-26b-a4b-it-spark --model-dir deploy/models/gemma-4-26b-a4b-it-4bit \
    --served-name local/gemma-4-26b-a4b-nvfp4
python -m tools.pin_model --build qwen3.5-9b-spark --model-dir deploy/models/qwen3.5-9b-4bit \
    --served-name local/qwen3.5-9b-awq --endpoint verifier
# RTX PRO 6000: the same with the -rtxpro6000 builds
```

`deploy/install.sh` does this for the GPU profile's pair (`python -m tools.pin_model --install <gpu>`, D-142): the
sha256 of the weights under deploy/models, the served names compose gives vLLM, and status `champion`, the only status
a PRODUCTION route accepts (a pin by hand without `--status champion` routes in DEV and TEST only). A build already
pinned is kept; missing weights are reported and that model routes nothing until install runs again.

`--verify` re-checks the weights. Restart the gateway after a new pin. `make verify-models` checks every pin at
install.

| Symptom | Fix |
| --- | --- |
| host check fails on driver or runtime | install and hold 580.142; `nvidia-ctk runtime configure --runtime=docker` |
| pin refuses the files | safetensors or GGUF only; remove `.bin` and `.py` files |
| llm-service or llm-verifier times out | first load takes up to 10 min; out of memory: lower `JUDGE_GPU_MEM_UTIL` or `JUDGE_MAX_LEN` |
| gateway `build_unpinned` | the gateway started before the pin: `docker compose restart gateway` |
| gateway `served_model_mismatch` | `JUDGE_MODEL` / `VERIFIER_MODEL` must equal the pin's `--served-name` |
| mailhog `exec format error` | install amd64 emulation (`tonistiigi/binfmt --install amd64`) |

A `public_agency: true` site needs non-PRC builds for every role; the default pair qualifies.

## 9. Proof of concept with Docker

`deploy/poc.sh` (`make poc`; Windows: `powershell -ExecutionPolicy Bypass -File deploy\poc.ps1`) runs the whole box on
synthetic data with test mail servers. It builds images when missing, writes random passwords, starts the stack,
creates the administrator (password printed once), ingests a 600-patient synthetic site and prints the URLs:
console <http://127.0.0.1:8090>, web mail (MailHog) <http://127.0.0.1:8025>, mail to the box on SMTP port 3025
(`tools/send_test_mail.py "FEAS GZQO" --sender admin@hospa.test`). `deploy/poc.sh status|down|reset`.

- **Modes** (`TB_LLM_MODE`): `stub` (default, no GPU), `openrouter` (DEV, D0 data only, key in `OPENROUTER_API_KEY`
  or `deploy/poc/secrets/openrouter_api_key`, given to the gateway only), `gpu` (needs the pin of §8).
- **A real mailbox:** set `IMAP_*`, `SMTP_*`, `MAIL_INTAKE_ADDR`, `MAIL_FROM_ADDR`, `TB_MAIL_AUTHSERV_ID` and app
  passwords in `deploy/.env` (mode 600), then `TB_POC_MAIL=real deploy/poc.sh`.
- **Remote access:** the console binds to 127.0.0.1. Put a TLS proxy in front (Caddy: `reverse_proxy 127.0.0.1:8090`;
  nginx: `proxy_set_header X-Forwarded-Proto https`), set `TB_CONSOLE_SECURE_COOKIE=1`, and limit it to a VPN.
- **Checks:** `make test-console`, and with the POC up `make test-console-e2e`.
- **The developer test stack** (Docker 27+, about 15 GB): `make images`, `make up-test` (box, stub, GreenMail on
  IMAP 3143 and SMTP 3025, MailHog on 8025), `make ingest-test`, then `.venv/bin/python tools/send_test_mail.py "FEAS
  GZQO"`; the reply with the PDF and XLSX shows in MailHog within seconds. `make test-integration` and `make test-e2e`
  run against it; `make down` stops it.
- Ports taken: `TB_HOST_CONSOLE_PORT`, `TB_HOST_MAILHOG_PORT`, `TB_HOST_SMTP_PORT`. "No snapshot": run the ingest
  (`console.cli ingest`).

## 10. One RTX 5090: the swap and the night check

The pair needs about 35 GiB side by side, so `docker-compose.rtx5090.yml` runs one model at a time
(`TB_MODEL_SWAP=sleep`, D-116).

- **Start:** judge loads and sleeps, verifier loads and sleeps, judge wakes (`judge-sleep-init`, `model-swap-init`,
  `judge-wake-init`).
- **Screening run:** the judge answers every note question, the gateway swaps to the verifier for the second
  opinions, then back. Same answers as the two models side by side.
- **Chat while the verifier is awake**, or a call over 30 s: "the model is busy, try again in a few minutes", in the
  user's language (`TB_GATEWAY_INTERACTIVE_TIMEOUT_S`).
- **The night check:** the pair canary (54 questions in EN, JA, zh-TW) before MICROBATCH, NAV, COHORT and
  CALIBRATION; they start only when both models pass and the pair agrees on a wrong answer at most once
  (`selftest.passed` / `selftest.failed`; `make selftest` in the box, `make canary` from a checkout).
- `curl -s http://gateway:8020/v1/serving/status` (inside the network) shows which model is awake.
- Measured 2026-11-08 on a PRO 6000 capped to 32 GB: one model awake uses 27–29.6 GB, the sleeper 1.3 GB; sleep
  0.4–3.7 s, wake 0.3–0.5 s. Not yet on a physical 5090. Host RAM must hold the sleeping model (64 GB or more).
- After a host reboot run `docker compose ... up -d --wait` again: the start-order helpers run only under compose.

## 11. Cloud runs (owner's OK first)

Qualifying a model pair on a card (G1b runs through it): [the qualify section](runbook/11-qualify.md) (D-313).

GCP project `trialbox-demo`. Always use a private `CLOUDSDK_CONFIG` (and unset `CLOUDSDK_AUTH_ACCESS_TOKEN`), stop
every VM after use and check that it shows `TERMINATED`.

**The demo VM** (`trialbox-demo`, e2-standard-4, asia-east1-b, about US$0.15 an hour). `make demo-bundle` writes
`dist/trialbox-demo.tar.gz`; copy it to a bucket, add `deploy/gcp/demo-vm-startup.sh` and the image as metadata, start
the VM, and the console answers on port 80 (plain http, `TB_CONSOLE_SECURE_COOKIE=0`: put https in front before
sharing widely). A restart resets the demo. The update path on it: `deploy/gcp/demo-vm-update.sh build <bucket>`,
then `run <bucket>` (a good bundle applied and checked with `e2e_simple`, a broken one rolled back; about one hour,
US$0.15).

**The GPU VM** (`tb-gpu-sim`, g4-standard-48 spot, one RTX PRO 6000, asia-east1-a, about US$2.74 an hour; the disk
with the weights is kept, so boot to serving is about 10–15 minutes).

| Run | Script | About |
| --- | --- | --- |
| PRO 6000 profile, serving record, `public_e2e`, canary (done 2026-11-08) | `deploy/gcp/gpu-pro6000-run.sh` as startup script | 0.6 h, US$1.50 |
| 32 GB-capped pair (the 5090 stand-in) | `deploy/gcp/gpu-sim-startup.sh` (the usual startup script) | per run |
| serving record with hashes | `deploy/gcp/capture-serving-config.sh prepare`, start, `fetch`, stop | 0.5 h |
| N-12 on the deployed files (done 2026-11-08) | `tools/trec_ct_eval.py` against the VM | 0.85 h, US$2.30 |
| the complete-platform run with the scenario matrix (step 9) | `deploy/gcp/complete-run.sh` | `--estimate`; D-141 |
| the same on four VMs, with the embedding and profile benches | `deploy/gcp/complete-run.sh --vms 4 --parts g1,embed,profile` | about 2.8 h, US$30; D-148 |

**The complete run is fail-safe** (D-141, after the 2026-11-09 incident: a killed driver left the VM on for an hour;
D-150, after the independent review of the four failed runs of that day). The workload runs on the VM; the VM stops
itself; the driver only uploads, polls and collects.

**Gate before any paid launch: the rehearsal** (D-150). `make rehearse` runs the real driver and the real VM script,
on the exact commit to be launched (it uploads `git archive` of HEAD, as the paid run does), in an Ubuntu 24.04
container that stands in for `tb-gpu-sim`: real apt, PyPI, Node.js, Playwright, the data downloads and nginx; strict
vLLM stand-ins (the API key is checked, any but the served name is a 404); fakes only for gcloud, the metadata
server, systemd, docker and the GPU (`tests/rehearsal/rehearse.sh` says what each is). About an hour, US$0. It must
end with `REHEARSAL PASSED`; no paid launch without it, and none from a commit it did not pass on. Its cases:

| Case | What it shows |
| --- | --- |
| `run-a` | a fresh disk, a bounded run at 500 patients (hospital-ja, public-ja, the gateway probe, emr-fhir, it-dump, MedTxt, TREC), driven with `--no-wait` and repeated `--collect`: setup, the data, both model servers' check, every part reported, no 404 or 401 at the servers, the report's HEAD = the commit, power-off once collected |
| `run-b` | the same disk, a new run: nothing kept from `run-a`, a fresh log |
| `served` | the judge serves a wrong name: `TB-SERVING-FAILED` before any part, the servers' logs in `results.tgz` |
| `no-upload` | nobody uploads: `TB-NO-CODE`, power-off after the grace |
| `hang` | a stuck, silent part and no driver: the idle watchdog powers off; `--collect` then gets the results from the stopped VM |
| `busy` | a part silent for 5 minutes but working (idle limit 2): it is never powered off as idle; it finishes; `--collect` gets it |

It needs docker (it starts a private `dockerd` when none answers and stops it afterwards), about 4 GB of disk and
the ports 80 and 8080 free; the evidence of each case stays in `$TB_REHEARSAL_DIR/evidence/<case>/`. Model quality
is not rehearsed (the stand-ins answer with the deterministic stub, so the canary may fail there): plumbing, names,
keys, setup, state and timing are, the layer every failure of 2026-11-09 was in.

1. `deploy/gcp/complete-run.sh --estimate --patients 50000` prints the hours and US$ per scenario (`--only TAG,TAG`
   for a bounded run). `--dry-run` prints every command and starts nothing.
2. The run: `export CLOUDSDK_CONFIG=<private folder> TB_SA_KEY_FILE=<key file, in place>`, activate the service
   account once, then `deploy/gcp/complete-run.sh --patients 50000 --no-wait` (or `--detach`). It:
   * probes the credential (`gc_probe`), reads the GPU and CPU quota (read-only) and refuses when the VMs cannot run,
     and refuses unless every VM is `TERMINATED`;
   * sets the **cloud-side hard cap**: `gcloud compute instances set-scheduling tb-gpu-sim --zone asia-east1-a
     --max-run-duration=<estimate x 1.3, rounded up>h --instance-termination-action=STOP` (`--hours N` to change);
   * puts `deploy/gcp/complete-run-vm.sh` on the VM as its startup script with a fresh key (0600 file, metadata,
     never printed) and the sha256 of the code, starts it, and uploads the code (`git archive` of HEAD with
     `TB_HEAD.json`: local changes are not in the run; the VM refuses an archive with another sha256).
3. On the VM: a systemd hard cap and a watchdog start first; then a pre-flight (docker with the NVIDIA runtime, the
   weights in `/models`, 50 GB free: else `TB-PREFLIGHT-FAILED`); then both model servers, which must be healthy,
   list exactly their served names, answer one chat call and refuse a call without the key, else
   `TB-SERVING-FAILED` and their logs in the results; only then `PRO6000-RUN-READY`. Setup installs git, the venv,
   Node.js, Playwright (Chromium must launch) and fetches the data git does not carry (`tools/fetch_run_data.py`: the
   CQL translator's `quick-5.4.0.jar`, MedTxt, TREC CT; a dataset it cannot fetch is named `TB-DATA-MISSING`, and
   its parts fail at once as "data missing" without using the card). The watchdog limits each phase (serving and
   setup 45 minutes, the code 35) and, in the run, powers off when no part has worked for 20 minutes (the run's own
   heartbeat follows the part's CPU, so a long silent SCREEN stays alive and a stuck one does not), and 30 minutes
   after the done marker (at once when the driver has collected). The model parts run in the run's own directory
   (`/var/lib/tb/runs/<run id>`) with `--resume --ocr tesseract`, through the gateway built as an installed box builds
   it; `results.tgz` is re-packed after every part.
4. Collect: `deploy/gcp/complete-run.sh --collect <run id>`, as often as wanted (each call is short: one look, the
   results so far, the report so far, "still running"; `--follow` polls to the end). The driver need not live through
   the run: the operator's shell may be capped at two hours, the run is not. When the VM has stopped with its
   results not yet collected, `--collect` starts it once in a **results-only** mode (no models, no run, a 20-minute
   cloud cap; it powers off as soon as the results are here; about US$0.20). Once every VM is done, it runs the walk,
   backup, update and scale on the stub here (at the run's `--patients`, OCR tesseract) and writes the report, whose
   head, host and run id are the VM's. A restart of the same run (`TB_RUN_ID=<run id> --shard i`) keeps the parts
   passed in that run at that HEAD; a new run never keeps anything.
5. Every gcloud call goes through `gc` (`deploy/gcp/gcloud-auth.sh`): an authentication error re-activates the
   service account from `TB_SA_KEY_FILE` and retries once.
6. Afterwards: `gcloud compute instances describe tb-gpu-sim --zone asia-east1-a --format='value(status)'` must say
   `TERMINATED`; `deploy/gcp/complete-run.sh --stop` stops it by hand and puts the usual startup script back (a VM
   started by hand after that runs both model servers with no watchdog: only its cloud cap stops it). Read
   `report.md`: a part that "crashed or never ran" is named in the headline, and a `profile` row whose path says
   "direct (the gateway refused...)" is a failed check, whatever else passed.

**The first launch after a failed one is bounded**: `deploy/gcp/complete-run.sh --patients 5000 --only
install,hospital-ja,scenario-gateway,scenario-emr-fhir --no-wait`, then `--collect <run id>`; read `report.md`, and only
then the full plan.

**Several VMs at once** (D-148). `--vms N` splits the run into N shards of whole parts (no part is split, so the
merged report is the single-VM report); VM 1 is `tb-gpu-sim` in the first zone, VM i is `tb-gpu-sim-i` in zone i of
`--zones` (one zone per region where the GPU quota is 1 per region). Each VM gets its own cap (its estimate × 1.3),
key, watchdog and results; the driver waits for all, merges, runs the stub parts and writes one report. `--parts`
adds the benches: `embed` (`tools/bench_embed.py`) and `profile` (`tools/bench_profile.py`).

The project had one GPU in all (`GPUS_ALL_REGIONS = 1`, `PREEMPTIBLE_CPUS = 0`: Spot VMs then draw on the regular
quota) when D-150 was written, so `--vms N > 1` is refused until the owner has the quota raised; the driver checks
it before any start or `--provision` and makes nothing it could not run.

1. The owner checks the zones and the quota (read-only; `--dry-run` prints these commands for the chosen zones):
   `gcloud compute accelerator-types list --filter='name~rtx'`, `gcloud compute regions describe <region>
   --flatten=quotas --filter='quotas.metric~RTX|CPUS'` and `gcloud compute project-info describe --flatten=quotas
   --filter='quotas.metric~GPUS_ALL_REGIONS'`.
2. `deploy/gcp/complete-run.sh --estimate --patients 50000 --vms 4 --parts g1,embed,profile` prints hours and US$
   per VM and in all; `--dry-run` with the same flags and `--zones` prints the plan and every command.
3. Once: `--provision --vms 4 --zones <z1,z2,z3,z4>` makes a machine image of `tb-gpu-sim` and the clones from it (a
   clone boots, powers itself off at once, and has a 30-minute cap in case it does not; its disk is kept and costs
   until `--teardown`).
4. The run: the same flags without `--dry-run`. `--collect <run id>` collects every VM; a VM that was preempted is
   started again with `TB_RUN_ID=<run id> deploy/gcp/complete-run.sh --shard <i>`; `--stop --collect <run id>` stops
   them all.

Optional `TB_BUCKET=gs://<bucket>` moves code and results through a bucket (the VM's service account needs storage
access); without it they go over plain HTTP to the VM with the key in a header. A billing budget with a kill switch
is the last net; it needs billing permissions this project's service account does not have: the owner sets it.

## 12. Identity and TLS (D-192, D-193)

The console is reached at `https://<TB_TLS_HOSTNAME>` through Caddy on 443; its own port is no longer published.
Local accounts sign in with a password and a TOTP code. The hospital account (AD through Authelia, OIDC) is optional
and off by default. All settings are in `deploy/.env`; the list with comments is
`deploy/identity/identity.env.example`.

**Ask hospital IT on day one** (lead time 2 to 6 weeks): a DNS name for the console (and one for Authelia when the
site uses the hospital account), the firewall rule for 443 from the clinic PCs, and either a certificate for those
names or permission to install Caddy's root certificate on the staff PCs. For the hospital account: a read-only AD
bind account, the AD groups to map (below) and LDAPS (636) from the box to a domain controller.

**TLS.**

1. Put `TB_TLS_HOSTNAME` (and `TB_TLS_MODE`) in `deploy/.env`. With the hospital's certificate set
   `TB_TLS_MODE=hospital`, `TB_TLS_CERT_FILE` (certificate and chain, PEM) and `TB_TLS_KEY_FILE` (key, PEM, 0600
   root), then check them with `python -m console.cli check-tls` (in the console container, or on the host with the
   same variables). It fails on a missing file, a key that is not the certificate's, a name the certificate does not
   carry, or a certificate that is not valid today, and warns 30 days before it ends.
2. Add the overlay: append `:deploy/docker-compose.identity.yml` to `COMPOSE_FILE` in `deploy/.env` (after the
   secrets overlay), then `docker compose up -d --wait`.
3. Internal CA only: copy the root certificate out once (`docker compose cp
   caddy:/data/caddy/pki/authorities/local/root.crt deploy/secrets/tls/caddy-root.crt`) and have hospital IT install
   it as a trusted root on the staff PCs (group policy). Never copy anything else out of the `caddy-data` volume: it
   holds the CA's private keys.
4. Open `https://<TB_TLS_HOSTNAME>/login` from a clinic PC: no certificate warning.

**Local accounts (TOTP, the default).** `TB_CONSOLE_MFA=totp` is the default and can be turned off only in DEV and
TEST. An account sets up its authenticator only with a one-time **enrolment code** from an administrator (valid 24
hours, works once): after the password the console shows a key, the person adds it to an authenticator app (or a
hospital device) and types the enrolment code and the app's code. Without a valid enrolment code an account with no
authenticator cannot sign in at all, so knowing a password is never enough to register a device. Every later sign-in
asks for the current code; a code works once. A wrong or reused code, or a wrong enrolment code, counts as a failed
sign-in: five failures in 15 minutes lock the account for 15 minutes, and the lock is in the audit trail
(`console.lockout`).

- **After the upgrade, and for every new account**: **Sign-in and recovery** (`/ops/identity`) lists the accounts
  without an authenticator at the top. For each, check who it is and choose **Enrolment code**; hand the code over in
  person or read it out on a call back to the extension in the staff directory. The code is shown once and never
  written to a log or the audit (`console.enrol_code` records who issued one for whom).
- **The first administrator** (no other administrator can issue a code): on the box,
  `python -m console.cli enrol-code admin` in the console container prints the code. This shell step is the
  supervised path; record it in the install checklist.
- **Lost phone**: on the same page choose **Reset authenticator** for that person, after the same identity check. The
  account is signed out everywhere and the page shows the enrolment code for the new device. An administrator's own
  authenticator is reset by another administrator, or with `console.cli reset-totp NAME` (prints the code).
- **Locked out**: wait 15 minutes, or an administrator chooses **Unlock** on the same page (`console.cli unlock
  NAME`). All actions are audited (`console.totp_reset`, `console.enrol_code`, `console.unlock`;
  `console.totp_enrolled` says whether it was a first device or one after a reset).
- **Sessions** end after `TB_CONSOLE_IDLE_MINUTES` without activity (default 10; set the hospital's policy for shared
  clinic PCs, at most 60) and after `TB_CONSOLE_SESSION_HOURS` in all (default 8). A page that refreshes itself (a
  running job) does not count as activity. Cookies are Secure, HttpOnly and SameSite=Strict; an explicit
  `TB_CONSOLE_SECURE_COOKIE=0` is refused in PRODUCTION.
- The trusted-header SSO (`TB_CONSOLE_SSO_HEADER`, D-93) runs only with TOTP off (DEV, TEST) and OIDC off, never signs
  in a local account, and Caddy strips identity headers from every request: a hospital uses the OIDC sign-in below.
- The TOTP secrets are stored encrypted, with the key `totp.key` on the `console-data` volume, not in the database.
  Back up both; with the database but without the key, every person sets up a new authenticator (an administrator
  resets them all).

**Hospital account (OIDC through Authelia, optional).**

1. Copy `deploy/identity/authelia/configuration.example.yml` to `deploy/site/authelia/configuration.yml` and fill in
   the values marked `SITE` (domain controller, base DN, bind account, the two host names).
2. Make the secrets in `deploy/secrets/authelia/` (0600, root): `jwt_secret`, `session_secret`, `storage_key`,
   `oidc_hmac` (each 64 random characters), `ldap_password` (the bind account's), `oidc_jwks.pem` (an RSA 2048 key,
   `openssl genrsa -out oidc_jwks.pem 2048`) and `oidc_client_secret.txt` (the client secret; its digest goes into
   the configuration, as the comment at its top says).
3. In `deploy/.env`: `TB_OIDC_ENABLED=1`, `TB_AUTH_HOSTNAME`, `TB_OIDC_ISSUER=https://<TB_AUTH_HOSTNAME>`,
   `TB_OIDC_CLIENT_SECRET`, `TB_OIDC_LOGOUT_URL=https://<TB_AUTH_HOSTNAME>/logout`, `TB_OIDC_CA` (the internal root
   from TLS step 3, or the hospital's CA chain) and `TB_OIDC_GROUP_ROLES`, for example
   `TB-Coordinators:coordinator,TB-Investigators:investigator,TB-Monitors:cro,TB-Admins:admin`.
4. Open LDAPS for Authelia only: add `authelia=<domain controller>:636` to `EGRESS_EXTRA` and run
   `deploy/network.sh apply` ([Security §2](SECURITY.md#2-network)).
5. `docker compose --profile oidc up -d --wait`. The sign-in page shows **Sign in with the hospital account**.

Only the groups in `TB_OIDC_GROUP_ROLES` give a role. A person in no mapped group, or in groups that map to two
different roles, is refused, and the refusal is audited (`console.login_failed`, `via: oidc`); a `role` claim or any
other group is ignored. The role is read again at every sign-in, so removing someone from a group takes effect at
their next sign-in. Authelia asks for the second factor (TOTP or a security key), and the console refuses a sign-in
the provider did not report as two-factor. A hospital account never takes over a local account of the same name.
Sign-out also signs out of Authelia. Add the `authelia-data` volume to the backup (the authenticators registered by
directory users). Authelia's OIDC provider is certified but still called beta by its makers (D-192).

The overlay is checked in CI (`.github/workflows/trialbox-identity.yml`: `caddy validate` in both TLS modes,
`docker compose config` of the merged files, and Caddy run in front of a stand-in console: HSTS on 443, identity
headers stripped, 80 and 8090 closed, no query strings in its log). The whole stack with Authelia has not been started
on a box yet. Run the four TLS steps and one sign-in of each kind at IQ.

## 13. Working in parallel on one machine (D-201)

For developers and agent sessions that run the suite side by side on one machine; not for a box.

- **One temp root per branch.** `make` sets `TB_TEST_ROOT` to `$TB_SCRATCH/tb-tests-<branch>` (`TB_SCRATCH`: your
  scratchpad, default `/var/tmp/trialbox-<uid>`; a detached checkout is `detached-<sha>`) and exports it. Under it:
  pytest's `--basetemp` (`pytest/`), the test `TMPDIR` (`tmp/`, emptied after each run), one PostgreSQL cluster per
  xdist worker (`pg-gw0` ...), the shared cluster of `e2e_simple` and the drills (`pglocal/`), `e2e-simple/` and
  `backup-drill/`. `make test` marks the root (`.tb-test-root`) and holds `flock` on it for the whole run: a second
  run on the same root stops at once and touches nothing. `/`, a top-level directory, `/tmp`, `/var/tmp`, the home
  directory, a system directory or a folder directly in one, and an existing folder of other files (no marker) are
  refused as a root; links are resolved first. `make e2e-simple` marks the root too, so it passes on a fresh root;
  it names a missing CQL translator jar (`quick-*.jar`, FHIRHelpers) before it starts (`make jvm-deps`; exit 2).
- **Tools run by hand** (`tools.demo`, `tools.e2e_simple`, the drills, `public_e2e`, `complete_run`, `omop_parity`
  and the other demos) default to a folder under `$TB_SCRATCH` (`/var/tmp/trialbox-<uid>/tb-<tool>`), never a fixed
  `/tmp/tb-*` path; `--dir` or the tool's `TB_*_DIR` variable still wins.
- **One venv per branch, exactly the lock.** `make venv` runs `uv sync --frozen --group test --extra dev`: it
  installs `uv.lock` and removes anything installed by hand; the venv has no pip. `make test` first checks that the
  venv still matches the lock (`venv-check`). To change a dependency, edit `pyproject.toml`, run `uv lock`, commit
  both. The test plugins are pinned in `[dependency-groups] test` (pytest, pytest-timeout, pytest-cov,
  pytest-xdist); `addopts` blocks `randomly` and the cache provider, and a guard test fails a run in which
  `-p randomly` brought it back. Random order is a nightly job, not a default: `make test-random` (the nightly
  workflow's `random-order` run) lays `pytest-randomly` over the venv for that run only (`uv run --with`) and sets
  `TB_TEST_RANDOM=1`; the seed is in the header, and `make test-random RANDOM_SEED=<n>` repeats a failing order.
- **The suite in parallel.** `make test` runs `pytest -n auto` (`PYTEST_N=0` for serial, `PYTEST_N=4` to cap).
  pytest keeps one basetemp and, of it, only the failed tests' folders; a green run removes it.
- **Disk.** `make check-disk` first (fails under `TB_MIN_FREE_GB`, default 20 GB; reports the branch root against
  its 10 GB budget). `make clean-tmp` (`DRY=1` to list only) removes what earlier runs left and nobody uses now:
  `/tmp/pytest-of-*` run folders without a live `.lock`, stopped `/tmp/tb-pgtest-*` and `/tmp/tb-pglocal-*`
  clusters, `/tmp/tb-backup-drill*`, `/tmp/tb-drill`, `/tmp/tb-e2e-simple*`, the rehearsal's `runs/` (not while a
  rehearsal runs), and the `src.tgz`/`results.tgz` of every `.cache/complete-run` run but the two newest by time
  (reports stay). It never stops a running server, never follows a link, never touches another user's files or a
  folder a running process names (working directory, open file, command line, environment). The rehearsal keeps the
  newest two evidence folders per case.
- **After a crash.** `python -m tools.pglocal --gc` stops and removes every cluster whose `.owner` process is gone (a
  `kill -9`, a lost session); a cluster without an owner file, an unreadable owner file or a folder that is not a
  cluster is never touched by it. A server is signalled only when the pid file names the postmaster running in that
  data directory, so a stale pid file signals nobody.
- **As root** the throwaway server runs as `postgres`, which must reach the cluster: `pglocal` adds the search bit
  (`o+x`, never `o+r`) to a parent that lacks it and says so on stderr; a socket path too long for Unix (about 100
  characters) moves to a short private folder under the scratch root (under `/tmp` only when that root is long
  too) that `<cluster>/run` links to.

## 14. Judge bake-off: the current judge against Gemma 4 31B (D-181)

`tools/judge_bakeoff.py` runs a labelled set through any OpenAI-compatible endpoint with the box's own judge prompt
and parser, and gates on wrong exclusions. It needs a GPU only for the real model; a dry run uses its stub:
`python -m tools.judge_bakeoff --stub --sources synthetic --require-sources synthetic --out /tmp/jb-stub` (no
network, about 10 s).

**Before the GPU** (on any machine):

1. Fetch the public sets: `python -m tools.medtxt_eval fetch` and `python -m tools.trec_ct_eval fetch` (they stay in
   `.cache`, never committed).
2. Freeze one item set for both models: `python -m tools.judge_bakeoff --write-set /tmp/jb-set.jsonl`. It prints the
   item count and the SHA-256; check that no source was skipped. Copy the file to the VM, never into the repository
   (it holds MedTxt and TREC text). Both runs pass `--set /tmp/jb-set.jsonl --expect-set-sha <sha>`.

**On the GPU VM** (owner's OK first, section 11 rules: a cap, stopped and `TERMINATED` after). One model at a time on
the same VM, same set, same `--workers`; every run also takes `--max-upper-ci 0.05` (Study A's bound):

1. The current judge, as the box serves it (the PRO 6000 run serves `nvidia/Gemma-4-26B-A4B-NVFP4` as
   `local/gemma-4-26b-a4b-nvfp4`):
   `python -m tools.judge_bakeoff --base-url http://127.0.0.1:8000/v1 --served-name local/gemma-4-26b-a4b-nvfp4
   --expect-root nvidia/Gemma-4-26B-A4B-NVFP4 --revision <commit> --model-dir <weights folder>
   --set /tmp/jb-set.jsonl --expect-set-sha <sha> --max-upper-ci 0.05 --out /tmp/jb-current`
2. The candidate, **official weights only**: the `google/gemma-4-31B-it` repository on Hugging Face, no community
   quantisation or fine-tune. Download it at a fixed commit into a folder, serve that folder with
   `vllm serve <folder> --served-model-name gemma-4-31b-it --max-model-len 32768` (the full-record path sends up to
   28,000 tokens; bf16 weights are about 62 GB, so it fits on the 96 GB card alone), then the same command with
   `--served-name gemma-4-31b-it --expect-root <folder> --revision <commit> --model-dir <folder>
   --out /tmp/jb-gemma31`. A run that dies (preempted VM) continues with `--resume` and the same `--out`.
3. Side by side: `python -m tools.judge_bakeoff --compare /tmp/jb-current /tmp/jb-gemma31` (exit 1 when the sets or
   prompt versions differ). Copy the two result folders off the VM before it stops.

**Served-name pinning, and what it does not prove.** `--expect-root` is required for a real endpoint. Before the
first item and again after the last, the tool reads `/v1/models`: the `--served-name` must be listed with `root`
equal to `--expect-root` (else exit 3, nothing sent), and the entry must be the same at the end (a restart or a swap
during the run fails the gate). `root` is only the name vLLM was started with. What identifies the weights is the
manifest hash `--model-dir` writes into `metrics.json` (`tools/pin_model.py` format), with the commit from
`--revision`; `--expect-manifest <sha>` refuses a folder with other weights. vLLM copies the requested name into each
answer, so the per-answer name check only catches a proxy that renames. Run nothing else on the port during the run.
A key, if the endpoint needs one, goes in `TB_BAKEOFF_API_KEY` (or `--key-env`): sent only to `--base-url`, over
https or to loopback, never printed or written.

**How to read the gate** (`metrics.md`, first lines; exit 0 passed, 1 failed). Each gated set (synthetic hospital,
MedTxt) is checked on its own, so the larger set cannot hide a failure on the other:

* **wrong exclusions <= 2 %** per set: of the judge's exclusions, the share the label does not exclude (Study A's
  measure), compared without rounding; the 95 % intervals are beside it, and `--max-upper-ci 0.05` gates the pooled
  upper bound;
* **at least 20 exclusions and 50 answers per set, at most 10 % unanswered**: a judge that never decides, or a model
  that fails on the long records, fails instead of passing on 0 of 0;
* both sets present, the pin held at the start and the end;
* `product:unknown_never_excludes` is a check of the product, not of the model: if it fails, stop and report a bug.

Not in the gate, but compare them: precision of "fits", gold-unknown excluded and abstained (a judge that never
abstains excludes on silence), quote found and dated right (an invalid quote turns the answer into unknown, so a low
rate costs recall, not safety), latency per call and per item and tokens per call (night window and cost), and TREC
CT eligible pairs lost (pair labels, about 40 % of the misses are label noise: compare models, do not gate). The
synthetic set has 300 items, 39 of them without a note in the window (not put to the model), and at most 62 correct
exclusions, so its upper bound alone cannot reach 5 %: that is why the bound is gated on the pooled sets.

A candidate replaces the judge only if it passes the gate on the same frozen set and is no worse than the current
judge on wrong exclusions; the change then goes through the full qualify command as a CC1 model change.

## 15. Operations screens (D-178)

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

## 16. Box-install rehearsal: the gate before a site's IQ

Before any site's installation qualification (IQ), and before a release goes on a site's media, run
`make rehearse-box` on any Docker host (no GPU; the network only to build the images; D-176). A
FAIL stops the release: no site visit until it passes. Keep `report.md` with the release record.

**What it does.** It makes offline media the way the vendor does: a bundle signed with a throwaway vendor key
(`tools/make_bundle.sh` with the images, placeholder weights for the large tier's pair and the reference data pack),
the release tree, the vendor key and `SHA256SUMS`. It removes the box images from the Docker host, so only the media
can bring them back. Then it runs the real `deploy/install.sh --tier large` inside a clean Ubuntu 24.04 container
(`tools/rehearse_box/host.Dockerfile`: Docker CLI and compose, python3, nftables, cron). An `nvidia-smi` stand-in
names one RTX PRO 6000. The two model servers are the strict vLLM stand-in `tools/vllm_standin.py`
(`tools/rehearse_box/standins.yml`, given as `TB_COMPOSE_OVERRIDE`). The stand-in takes vLLM's command line from the
profile's compose file. It answers only the exact served name (404 otherwise, as vLLM) and refuses every `/v1` call
without the key (401). It never starts without a key (D-177).

**What must pass** (each is a step in the report):

| Step | Proves |
| --- | --- |
| `wsl2` | `deploy/windows/preflight.sh` passes on a WSL2-like host (WSL2 kernel, systemd, Windows build through a `cmd.exe` stand-in) and fails on plain Linux. Windows itself (`preflight.ps1`, BitLocker, `wsl --import`) cannot run here: do it on a Windows test machine before a Windows site. |
| `media-negative` | missing media ("no such bundle"), a forged bundle ("not a valid signed TrialBox release") and a missing vendor key each stop the installer, and nothing is written |
| `install` | the installer exits 0: bundle verified and loaded, settings, the model key, the pins, the stack healthy, the serving check |
| `doctor` | `trialbox doctor --live` passes, with the `serving` check (below) |
| `served` | the pinned served names in `deploy/site/registry.site.yaml` are exactly what the two servers serve |
| `offline` | every running container runs an image the bundle loaded, the third-party ones (`postgres`, `hapi`) too, and the Docker daemon pulled nothing; the CQL translator jars in `criteria-compiler` are byte for byte the vendor's and translate; the media's reference data pack is loaded; ClinicalTrials.gov is offline; the box has no route out |
| `egress-override` | no route out of the box **with the rehearsal's own internal `egress-net`** (`tools/rehearse_box/standins.yml`). The shipped `egress-net` with `deploy/network.sh` is not rehearsed (no `NET_ADMIN`): check it at the site's IQ |
| `guard` | on `model-net` only `model-guard` answers to the model servers' names: `/invocations`, `/tokenize`, `/collective_rpc`, `/metrics` and the rest are 404 with or without the key, `/v1` needs the key, nothing reached the stand-ins' open routes, and the servers are only on `trialbox-model-backend` |
| `console` | the console answers `/healthz` and its sign-in page; inside it no outside name resolves and no outside address answers, while the box's own names do (`console-net`, below) |
| `screen` | SCREEN GZQO on synthetic hospital A ends `done`, its model calls go through the gateway to both pinned builds, with no 401 and no 404, and it mails its results to the site's relay (a plain SMTP sink, `tools/rehearse_box/smtp_sink.py`, stands in for it) |
| `power-cycle`, `after-restart` | every box process killed (as in a power loss), the host restarted: the box comes back healthy with its data, the doctor passes, the console answers, a second SCREEN runs |
| `wrong-name` | a server that serves another name than the pin: the doctor (the installer's check) FAILs and names both, and the gateway refuses the call |
| `missing-key` | the gateway without the key: the doctor FAILs with "refused the key (HTTP 401)", and both calls are refused |
| `no-registry-pull` | the Docker daemon's image events, from the moment the images were removed to the end of the run: every bundle image loaded, no pull |

**Knobs.** `TB_REHEARSE_DIR` (default a fresh private `mktemp` folder; a given one must be absolute, three levels
deep, not a system folder, and new or this user's earlier rehearsal folder; the report and logs stay there),
`TB_REHEARSE_SKIP_BUILD=1` (use the images already built), `TB_REHEARSE_KEEP=1` (leave the box running for a look),
`TB_EXTRA_CA` (a PEM for apt and pip behind a TLS proxy). It needs a Docker host with no other TrialBox stack and port
8090 free. The box container uses the host's Docker through its socket, so the work folder has the same path inside.
`DOCKER_HOST=unix:///path/docker.sock` rehearses on another daemon. Run it on both Docker image stores before a
release: the containerd store (the default of new Docker installs) and the classic `overlay2` store (older hosts,
and hosts upgraded from them). The classic store keeps no image digests (below).
At the end it removes the box, its volumes and the media, and loads the images back from the media if a failed run
left them removed.

**Not rehearsed** (do these at the site's IQ): a real GPU, driver and model weights (the canary and the serving
record, §8); the egress rules (`deploy/network.sh apply` needs `NET_ADMIN`, which the rehearsal does not give: the
rehearsal makes the outbound network internal instead); LUKS, TPM, swap and the other host hardening lines of
`deploy/check_host.sh`; the bge-m3 embedder (the hash embedder runs instead); the hospital's mail server (a sink without TLS stands in).

**Images come only from the bundle** (D-176). `install.sh` starts the stack with `--pull never` and first checks
that every image of the stack is on the box: a missing one stops the install with its name, and nothing is pulled.
The compose files pin `postgres` and `hapi` by digest. Docker's containerd image store keeps that digest when the
bundle is loaded; the classic `overlay2` store does not, so `tools/image_pins.py` points the image's compose variable
(`POSTGRES_IMAGE`, `HAPI_IMAGE`) in `deploy/.env` at the image id the signed bundle names (`image-pins.json`; an
image id is its content). Updates do the same before they restart the box. A site that mirrors the third-party
images itself (`make_bundle.sh --no-third-party`) sets `TB_INSTALL_PULL=missing`, and a variable it set to its own
mirror is left alone.

**`console-net`** (D-176). Docker publishes no port of a container that is only on internal networks, so the
console is also on `trialbox-console`, which is not internal. It is closed by hand: no NAT out (no reply ever comes
back from outside), no IPv6, published ports on 127.0.0.1 unless `TB_CONSOLE_BIND` says otherwise, and the console
sends outside names to an address that is never assigned (`dns: 192.0.2.53`; the box's own names still resolve).
Without NAT a packet from the console can still leave the host, though no answer comes back: `deploy/network.sh
apply` (run by `install.sh` as root) drops it. Keep the egress rules applied on every box. `network.sh` also drops
every connection into a box network that is not to a published port (a neighbour on the hospital LAN that routes to
a container address directly, possible on Docker before 28).

**`model-guard`** (D-177). vLLM checks its key only on paths under `/v1` (and `/v2`, `/inference`, `/cohere`).
`POST /invocations` (chat), `/tokenize`, `/score`, `/pooling`, `/metrics` and, in dev mode, `/collective_rpc` answer
without it. So the vLLM servers are only on `trialbox-model-backend`, and `model-guard` (`services/model_guard`) is
what `llm-service` and `llm-verifier` mean on `trialbox-model-net`. It passes, with the key only, `GET /v1/models`,
`POST /v1/chat/completions` and `POST /v1/completions`; on the RTX 5090 profile also the gateway's `/sleep`,
`/wake_up` and `/is_sleeping`; and `/health` without the key. Everything else is 404. `trialbox doctor --serving`
also checks that `/invocations` and `/tokenize` refuse a call without the key.

**The host itself.** `deploy/network.sh apply` also drops every new connection from a box network to the host
(sshd, a database), except an allowed destination that is on the host.

**The model key** (D-177). In GPU mode `install.sh` writes `TB_LLM_API_KEY` to `deploy/.env` once. Compose gives it to
vLLM as `VLLM_API_KEY`, and only the gateway sends it (`models/routing.yaml`, endpoints `serving` and `verifier`). The
secrets overlay clears it in every other service. After the stack starts, the installer runs `trialbox doctor
--serving` on the model network and stops when a server is down, refuses the key, does not serve a pinned name, or
answers without the key in PRODUCTION. An update (`trialbox update`) makes the key on a GPU box that has none and runs
the same check after the restart; a FAIL rolls the update back. To change the key: set a new value in
`deploy/.env`, then `docker compose --project-directory deploy up -d gateway model-guard llm-service llm-verifier`
(`trialbox secrets rotate` does not rotate it yet).

## 17. On a hospital platform

For a hospital that runs TrialBox on its own shared GPU platform (CGMH's B200) or, in the interim, on its private
cloud with GPU (D-211). The same images as the appliance; no `install.sh`. The platform team applies the manifests in
TrialBox's own namespace; Aimedics runs the install checks there; the hospital witnesses (IT pack §A.6).

**What the platform team gives TrialBox** (before the first apply; survey questions 49 to 53):

| Item | What | Checked by |
| --- | --- | --- |
| Namespace | TrialBox's own; nothing else runs in it | the isolation probe |
| Quota | a ResourceQuota with two GPU devices (two MIG instances on the shared card: the judge and the verifier each hold one; `nvidia.com/gpu` with the `single` MIG strategy or `nvidia.com/mig-<profile>` with `mixed`), and CPU and memory at least the minimum `doctor --platform` prints | `quota` |
| Storage | an encrypted storage class with ReadWriteMany; its specification and encryption setting as evidence | `storage_encryption` (evidence reference) |
| Network | a CNI that enforces NetworkPolicy; the console's TLS proxy or ingress controller in a namespace labelled `trialbox.io/console-ingress=true` | `network_policy`, the isolation probe |
| Services | NTP, the directory (LDAP or OIDC), the SMTP relay, the backup share | `ntp`, `directory`, `mail_relay`, `backup_target` |
| Secrets | `trialbox-db` (`POSTGRES_PASSWORD`, `POSTGRES_WF_PASSWORD`, `TB_DB_URL`), `trialbox-mail` (optional), `trialbox-cloud` (optional), `trialbox-actor`, `trialbox-token-<service>` (key `token`) and the ConfigMap `trialbox-service-tokens`, made with `python3 -m tools.trialbox secrets init` on an admin workstation and created with `kubectl create secret`; **never** the key-encryption key, the `pid_map.key` or the `site_hmac.key` (WS-13.11: a hospital KMS or the steward's unseal; T-210) | `kek_custody` |
| Weights | the model folders in the `models-data` claim (read-only to the servers) | `gpu_serving`, `canary` |

**Apply.** A site overlay sits on top of `deploy/platform/overlays/shared-quota` (or `interim-cloud`): it sets the
namespace and the storage class, replaces `trialbox-settings` with the site's `settings.yaml`, merges the site's
values into `trialbox-env` (as `deploy/.env` on a box: `SMTP_HOST`, `TB_SITE_ID` ...) and `trialbox-platform`
(the platform's declarations: `TB_PLATFORM_STORAGE_CLASS` (required in VALIDATION and PRODUCTION),
`TB_PLATFORM_STORAGE_ENCRYPTED=yes`, `TB_PLATFORM_STORAGE_EVIDENCE`, `TB_BACKUP_TARGETS`,
`TB_PLATFORM_BACKUP_EVIDENCE`, `TB_PLATFORM_BACKUP_HOST`, `TB_NTP_SERVER`, `TB_DIRECTORY_URL`,
`TB_PLATFORM_API_SERVER` (the API server's endpoint addresses, `kubectl -n default get endpoints kubernetes`),
`TB_MIG_PROFILE`), and adds the egress policies:

1. `python -m tools.trialbox platform-egress --env-file <site.env> > egress.yaml` renders the egress allowlist of
   `deploy/egress.py` as NetworkPolicies (the same hosts as the appliance's nftables table; resolved now, so re-run
   it when an address changes) and the install-check job's own policy `trialbox-egress-doctor` (only the declared
   API server, NTP, directory, mail relay and backup hosts; an undeclared one gets no rule). Add `egress.yaml` to
   the site overlay's resources.
2. `kustomize build <site overlay> | kubeconform -strict -summary` (pinned: kustomize v5.4.3, kubeconform v0.6.7),
   then `python -m tools.trialbox doctor --platform --manifests <build output>` before anything is applied: it
   prints the quota minimum and refuses a `latest` tag.
3. `kustomize build <site overlay> | kubectl apply -f -`. The judge and the verifier do not start while
   `serving.env` reads `unmeasured`: that is on purpose (below).

**The `shared-quota` serving record.** The pair's context, sequences and memory fraction on a MIG instance are
measured, never assumed: from the cloud B200 qualification (T-114, WS-02.7), then on CGMH's own partition at IQ with
`tools/serving_config.py`. The record goes into the ConfigMap `trialbox-serving-record` (key `serving_config.json`),
its values into the overlay's `serving.env`; the record must name the MIG profile in `card.mig_profile`. A partition
change is a CC6 change: measure again, re-run the checks and the canary. The Docker form of the same profile is
`deploy/docker-compose.shared-quota.yml` (the MIG instance UUIDs and every serving value required, none defaulted).

**The install checks (IQ).** `kubectl -n <ns> delete job trialbox-doctor trialbox-canary --ignore-not-found`, apply
again, then `kubectl -n <ns> logs job/trialbox-doctor`. The doctor job writes `iq-evidence.json` to the
`iq-evidence` claim; the IQ protocol attaches it (TST-IQ-03). Every check is PASS, WARN, FAIL or SKIP; the job fails
on any FAIL. Re-run both jobs after every platform change (host OS, runtime, GPU driver, quota: RSK-37). Then the
isolation probe from a second namespace: `TB_INTEGRATION=1 TB_PLATFORM_NAMESPACE=<ns> pytest -m integration
tests/platform` (every TrialBox port refused, no volume mountable; `TB_PROBE_IMAGE` names an image the platform holds).

**The compose platform form** (a Docker host the platform team runs): `python -m tools.trialbox platform-images
--env >> deploy/.env`, then the appliance files with `deploy/docker-compose.shared-quota.yml` and
`deploy/platform/docker-compose.platform.yml` last; `docker compose ... config --format json >
deploy/site/compose.json`; `docker compose ... --profile doctor run --rm doctor` writes
`deploy/site/iq-evidence.json`. There the egress rule is the platform's firewall (`TB_PLATFORM_NETWORK_POLICY_EVIDENCE`
names it) and the quota its declaration (`TB_PLATFORM_QUOTA`, e.g. `gpu=2,cpu=16,memory=96Gi`).

**A release.** `release.json` names every image and its digest; `python -m tools.trialbox platform-images` writes the
component that pins them (`--check` in review). Until T-110's `release.json` lands, `deploy/platform/release.json` is
the provisional one, with no digest for the images not yet released: the doctor then fails `image_digests` in
VALIDATION and PRODUCTION.

**On a test cluster (no GPU).** `make images`, then `deploy/platform/kind-check.sh`: a kind cluster, the release's
images loaded, throw-away Secrets and a ResourceQuota, the overlay applied with `TB_ENV=TEST` and
`TB_PLATFORM_NO_GPU=1` (refused in VALIDATION and PRODUCTION) and the doctor's egress to the API server, every
non-GPU workload rolled out, the doctor job's report read (every check present, the GPU ones `skipped: no device`),
the isolation probe, the cluster deleted. It is what the CI job is to run; the job itself is not wired yet (the
workflow file is owned elsewhere).

## 18. Developing a site mapping without the site's data

The steward's procedure (T-011; TB-SITE-03). No row of the site's data leaves the hospital, and none is needed to
write the mapping. (The card named this §13; §13 was already taken by D-201.)

1. **Write the schema from the survey.** Copy `tests/fixtures/site_schema/tw-sample.yaml` (a CSV or SQL export) or
   `tests/fixtures/site_schema/jp-sample.yaml` (SS-MIX2) and fill it from the signed survey (TB-SITE-01, questions
   24 to 38; the field names are listed in `docs/plan/sites/site-survey.md` §2.3): the input, character set, date
   format and delimiter, the header row of each table, the code lists (departments, the lab table with units,
   diagnoses, drugs), the provider field, the appointment source and the note types. Structure and codes only: a
   key that would hold a value (`sample`, `rows`, `value`, `examples`, ...) is refused with "no values in a schema
   file", and so is a code-list name the site's character set cannot hold.
   `python -m tools.synth_site_from_schema validate <schema.yaml>` checks it against
   `schemas/site_schema.schema.json`.
2. **Build the synthetic site.** `python -m tools.synth_site_from_schema build <schema.yaml> --out <dir>` writes 500
   synthetic patients in the site's layout (CSV files, an SQLite database with its SQL dump, or SS-MIX2 storage),
   in its encoding and date format, with the planted faults of `plants`: lab codes no lookup knows and results in a
   unit the lookup does not expect. Chart numbers are `SYNT-0001` and so on and patients have no names, so a real
   chart number or name in the folder is something the data scan finds.
3. **Write the mapping against it.** Start from `services/adapter/mapping/templates/csv_site.yaml` (or
   `services/adapter/mapping/templates/cgrd_sql_site.yaml`, or `services/adapter/mapping/jp_core/ssmix2_site.yaml`),
   then run `python -m tools.synth_site_from_schema check <schema.yaml> --out <dir> --mapping <mapping.yaml>` until
   it passes and the unmapped codes it lists are the planted ones only. A unit-mismatch line means those results get
   no value (unknown, never a wrong number): fix the lookup's `source_unit` or `factor`, never the result.
4. **Scan the folder.** `python -m tools.data_scan <dir>` must be clean.
5. **On the hospital's hardware**, after the data-processing agreement, the steward runs the same `check` on the
   10-patient sample (question 41) with the finished mapping, then `adapter run`. Only the report leaves: per table
   the rows read, the resources, the missing columns, the unmapped codes and the unit-mismatch counts, and a parse
   error with its value cut out. Never a row, a value or a chart number.

The adapter reads UTF-8 comma-separated CSV with ISO dates (or `YYYY/MM/DD`, `YYYYMMDD`) and SS-MIX2 storage. A
site whose export is Big5 or Shift_JIS, tab-separated, or has ROC 7-digit dates is read by `check` through a staging
copy (UTF-8, ISO dates, the same headers) until the adapter's sources read those forms themselves; the nightly feed
needs the same conversion until then.

**The data scan and the site's chart number.** When the signed survey states the chart number's form (question 26),
put it in the schema's `identifiers.chart_number` and run `python -m tools.synth_site_from_schema scan-pattern
<schema.yaml>`. A form with letters or a check digit gives a pattern for a bare chart number (no label), to add to
`tools/data_scan_patterns.yaml` with its planted positive (D-203). A form of digits only, with no check digit, gives
none: such a pattern would hit every date and count, and the labelled `chart_number` pattern stays the control.
