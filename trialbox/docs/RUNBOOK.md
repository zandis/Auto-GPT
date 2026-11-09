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
`tools/make_bundle.sh`. On Windows the box runs in WSL2: `docs/handover/OFFLINE-MEDIA.md`,
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

## 3. Accounts

Administrators add accounts on **Users** (`/ops/users`). The one-time password shows once, in a read-only field; hand
it over in person or by phone (D-133). Five failed sign-ins lock an account for 15 minutes; sessions end after 30
minutes idle or 8 hours. Roles and the work they do: [User guide](USER_GUIDE.md). In the POC container:
`docker exec -i trialbox-console-1 python -m console.cli bootstrap-admin|add-user NAME --role ROLE|reset-password
NAME|disable NAME|list-users`.

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
| Notes never exclude | `selftest.failed` in the audit, the admin health tile | the pair canary failed: check the models (§8, §10) |
| A tool imports the wrong code | the venv has another checkout installed | set `PYTHONPATH=libs:services:.` (the Makefile does) |
| Test ports taken | | `TB_HOST_<NAME>_PORT` in `deploy/.env` |

A failed job names its step (received, parsing, compiling, running, reporting) and the requester gets a plain
"Failed" mail.

## 5. Updates, backup, restore, secrets

**Updates** (D-138): `sudo tools/apply_update.sh trialbox-<version>.tar --dry-run`, then without `--dry-run`.

1. The bundle is verified (vendor Ed25519 signature, every sha256). A bad bundle changes nothing.
2. **Backup first** to `TB_BACKUP_TARGETS` with `deploy/secrets/backup.pub`. No key or no target: the update refuses.
3. **Rollback point:** replaced images tagged `<repo>:rollback-<bundle>`, overwritten models kept, both databases
   dumped locally (0600, removed after success).
4. **Apply:** images loaded, models copied, `docker compose up -d --wait` (services migrate at start), rulesets
   (approval and equivalence gates), health check.
5. `update.applied` in the audit. A failure after step 3 puts images, models and databases back, restarts, checks
   and writes `update.rolled_back`; exit 1.

Every step is in `deploy/updates/history.jsonl`. `--no-backup` is for a test box only and is audited. If the rollback
itself fails, restore from the backup. Driver updates are outside the bundle and need a change request. Held by
`tests/unit/test_update_path.py` and `tools/update_drill.py`.

**Backup** (D-126). Once, with hospital IT: `python -m tools.trialbox backup-keygen --private
/media/usb/trialbox-backup.key --public deploy/secrets/backup.pub`. The private key goes in their sealed envelope; the
box keeps only the public key and cannot read its own backups. Then `trialbox backup --to <NAS share> --to <USB
disk>` (keeps the newest 14 per target). Check one with `trialbox backup-verify <file> --key <private key>`. A
backup holds both databases, every data folder and a manifest of hashes and row counts, encrypted (AES-256-GCM to an
X25519 key). The ruleset repository `/data/rulesets` is in it; it is also a git repository you may push to the
hospital's git server.

**Restore.** Reinstall (§1), then `trialbox restore <file> --key <private key> --yes` (hospital IT brings the key).
Every hash is checked first; replaced folders are moved aside, not deleted. Held by `tests/unit/test_backup.py`
and `tools/backup_drill.py`.

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
    --served-name gemma-4-26b-a4b-it
python -m tools.pin_model --build qwen3.5-9b-spark --model-dir deploy/models/qwen3.5-9b-4bit \
    --served-name qwen3.5-9b --endpoint verifier
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

**The complete run is fail-safe** (D-141, after the 2026-11-09 incident: a killed driver left the VM on for an hour).
The workload runs on the VM; the VM stops itself; the driver only uploads, polls and collects.

1. `deploy/gcp/complete-run.sh --estimate --patients 50000` prints the hours and US$ per scenario. `--dry-run` prints
   every command and starts nothing.
2. The run: `export CLOUDSDK_CONFIG=<private folder> TB_SA_KEY_FILE=<key file, in place>`, activate the service
   account once, then `deploy/gcp/complete-run.sh --patients 50000`. It:
   * probes the credential (`gc_probe`) and refuses unless the VM is `TERMINATED`;
   * sets the **cloud-side hard cap**: `gcloud compute instances set-scheduling tb-gpu-sim --zone asia-east1-a
     --max-run-duration=<estimate x 1.3, rounded up>h --instance-termination-action=STOP` (`--hours N` to change);
   * puts `deploy/gcp/complete-run-vm.sh` on the VM as its startup script with a fresh key (0600 file, metadata,
     never printed), starts it, and uploads the code (`git archive` of HEAD: local changes are not in the run).
3. On the VM: a systemd hard cap and a watchdog start first. The watchdog powers off when the heartbeat is not
   touched for 20 minutes (the run touches it as its log grows; the driver touches it over HTTP), when setup takes
   more than an hour, or 30 minutes after the done marker (at once when the driver has collected). The model parts
   run there with `--resume --ocr tesseract` (tesseract with `jpn`, `chi_tra`, `eng` is installed by the script) and
   through the gateway built as an installed box builds it.
4. The driver polls once a minute with short calls only, downloads `results.tgz`, runs the walk, backup, update and
   scale on the stub here and writes the report. If the driver dies, nothing is lost:
   `deploy/gcp/complete-run.sh --collect <run id>` picks the run up; a stopped VM keeps its disk, and starting it
   again resumes the parts not yet passed.
5. Every gcloud call goes through `gc` (`deploy/gcp/gcloud-auth.sh`): an authentication error re-activates the
   service account from `TB_SA_KEY_FILE` and retries once.
6. Afterwards: `gcloud compute instances describe tb-gpu-sim --zone asia-east1-a --format='value(status)'` must say
   `TERMINATED`; `deploy/gcp/complete-run.sh --stop` stops it by hand and puts the usual startup script back.

**Several VMs at once** (D-148). `--vms N` splits the run into N shards of whole parts (no part is split, so the
merged report is the single-VM report); VM 1 is `tb-gpu-sim` in the first zone, VM i is `tb-gpu-sim-i` in zone i of
`--zones` (one zone per region where the GPU quota is 1 per region). Each VM gets its own cap (its estimate × 1.3),
key, watchdog and results; the driver waits for all, merges, runs the stub parts and writes one report. `--parts`
adds the benches: `embed` (`tools/bench_embed.py`) and `profile` (`tools/bench_profile.py`).

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
