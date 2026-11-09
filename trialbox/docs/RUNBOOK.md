# TrialBox runbook

This is for the site operator (IT) and the CRC office. Users never log in: they send email to the box and get email
back. Every command below runs on the appliance host from the repository directory (`/opt/trialbox`) as root unless
noted. Section references (§) are to `SPEC.md`; D-numbers are entries in `docs/DECISIONS.md`.

## 1. Install a new site (≈ 1 day)

**One file.** With the vendor's signed release bundle on a USB stick, `sudo deploy/install.sh trialbox-<version>.tar`
does steps 2, 3, 5, 6 and 8 below in one run (verify and load the bundle, settings wizard, start with the GPU or stub
profile, first administrator, host check; `--answers site.yaml` for no questions, `--mode stub` for a box without a
GPU). The vendor builds the bundle with `tools/make_bundle.sh`. Hardware: `python -m tools.gpu_sizing` prints the
estimate table (no GPU is enough for feasibility, NAV and COHORT; a GPU serves protocol extraction and note criteria).

**Tiers** (D-138). The three boxes we sell install with `--tier`:

| Tier | `--gpu` profile | Box | Serving |
| --- | --- | --- | --- |
| `small` | `rtx5090` | one RTX 5090 (32 GB) | the pair with the sleep swap, 8k |
| `medium` | `gb10` | DGX Spark (GB10) | the pair resident, 16k |
| `large` | `rtxpro6000` | one RTX PRO 6000 (96 GB) | the pair resident, 32k |

`sudo deploy/install.sh trialbox-<version>.tar --tier large --answers site.yaml` installs only when the tier has a
serving record of its own uncapped card (`deploy/site/` or the vendor's `deploy/measured/serving_config.<gpu>.json`,
checked by `tools/serving_config.py measured`) and the machine's card is the tier's card; otherwise it stops before
anything is loaded (exit 3) and says what is missing. There is no override. `deploy/install.sh --tier large
--tier-check` asks the question alone. Today only `large` has a vendor record. To measure a card: a trial boot with
`TB_ACCEPT_UNMEASURED_GPU=1 deploy/install.sh <bundle> --gpu <profile>` (not a tier install), then on the box
`python3 tools/serving_config.py capture --container judge=trialbox-llm-service-1 --container
verifier=trialbox-llm-verifier-1 --models-dir deploy/models --out deploy/site/serving_config.<profile>.json`.

The installer also makes one token per service (`trialbox secrets init`, §5 "Secrets"), adds
`deploy/docker-compose.secrets.yml`, writes the site's network, port and secret sheet to
`deploy/site/network-sheet.{en,ja,zh-TW}.{md,html}` (print it for hospital IT), and installs the nightly log job
(`/etc/cron.d/trialbox-retention`, §2 "Logs"). On Windows the box runs in WSL2: `docs/handover/OFFLINE-MEDIA.md`,
`docs/handover/WINDOWS-INSTALL-CHECKLIST.md` and `deploy/windows/preflight.{ps1,sh}`.

1. **Host.** Ubuntu 24.04 LTS on LUKS2 with TPM2 unlock, swap off, Docker Engine 27+, nftables. Add the NVIDIA
   driver and container toolkit when there is a GPU (GB10: driver 580.142, held). See `docs/HARDENING.md`.
2. **Images.** Load the signed release bundle: `tools/apply_update.sh trialbox-<version>.tar` (images, models,
   approved rulesets). Development hosts can build instead with `make images`, or `make images-multiarch` for x86 + GB10.
3. **Settings.** `python -m tools.settings_wizard --out deploy/settings.yaml --env-out deploy/.env`. Answer the
   questions, or pass `--answers site.yaml` (see `tests/fixtures/onboarding/site_c_answers.yaml`). The wizard
   validates everything the services check at start-up. Re-check an edited file with
   `python -m tools.settings_wizard --check deploy/settings.yaml`.
   - Mail authentication. The hospital MTA must add an `Authentication-Results` header in front of the intake
     mailbox. Answer `mta_authserv_id` with its first token (e.g. `mx.hospital.tw`; written to
     `TB_MAIL_AUTHSERV_ID`), so that headers forged further down are ignored.
   - A command is accepted on `dmarc=pass`, or on an SPF/DKIM pass for the From: domain (or a parent/subdomain).
4. **Mapping.** Copy `services/adapter/mapping/templates/csv_site.yaml` (or `cgrd_sql_site.yaml`) to
   `services/adapter/mapping/tw_core/<site>.yaml`. Fill in its `tables:` block: `source`, `rename`
   (local → canonical columns, `templates/CANONICAL.md`) and `values` (local → canonical codes). Copy and edit the
   lab lookup CSV. Then check it against an export:
   `python tools/mapping_check.py --mapping services/adapter/mapping/tw_core/<site>.yaml --source csv --path <dir>`.
   It must report 0 missing columns and 0 structural errors; unmapped lab codes are listed for the lab team.
5. **Start.** `sudo python3 -m tools.trialbox secrets init`, then `cd deploy && docker compose -f
   docker-compose.yml -f docker-compose.secrets.yml --profile gpu up -d --wait`. Use `--profile stub` without a
   GPU, and add `-f docker-compose.gb10.yml` on GB10. Then apply the egress rules: `deploy/network.sh apply`.
6. **Vendor key.** Install `deploy/keys/vendor_ed25519.pub` (from the vendor, out of band).
7. **First ingest.** `docker compose exec adapter python -m adapter.cli run`, or wait for 02:00. Check
   `/data/lake/ndjson/<date>/ingest_report.json`: `passed: true`, validator errors < 0.5 %.
8. **Host check.** `deploy/check_host.sh [--gb10]`: no FAIL lines.
9. **Acceptance (§11.2)** before go-live: see section 6.

## 2. Daily operation

| When | What | Where to look |
| --- | --- | --- |
| 02:00 | INGEST (adapter → FHIR store + lake, 1 % HL7 validator sample, snapshot pruning) | job list, `ingest_report.json` |
| 00:20 | `trialbox logs daily` on the host (cron): collect yesterday's service logs, prune, archive the audit | `/var/log/trialbox-retention.log` |
| 05:00 | RETENTION (attachments 90 d, outputs 365 d, mail logs, retired pools 24 months) | `retention_<date>.json` output |
| Mon 03:00 | MICROBATCH per ruleset with a pool → `this_week_visit1.xlsx` to list recipients | mail |
| Mon 03:30 | NAV per approved NHI ruleset → lists, drafts, TWPAS bundles | mail |
| 1st 05:30 | CALIBRATION per ruleset with feedback | `calibration.json` |
| 1st of Jan/Apr/Jul/Oct 04:00 | COHORT per cohort ruleset (member boxes mail their table to the alliance root) | mail |

### Logs (D-138)

Retention per log type is in `deploy/settings.yaml` `retention` (the wizard's `jp` or `tw` defaults, changed in the
answers with `logs_days`, `mail_log_days`, `outputs_days`, `attachments_days`; `tb_common/retention.py` says why):

| Log | Where | Kept | How |
| --- | --- | --- | --- |
| Service logs (JSON, pseudonyms only) | containers (50 MB x 5 each), then `TB_LOG_DIR/services/<day>/<service>.log.gz` | `logs_days` (365) | `trialbox logs daily` collects and prunes |
| Audit chain | volume `audit-data`, copied to `TB_AUDIT_ARCHIVE_DIR/<year>/<day>.jsonl.gz` | never deleted (`audit_years` 10 on the box) | `trialbox logs daily` copies, compresses and verifies; nothing on the box is touched |
| Mail logs (intake, sent, morning mail) | trial database, schemas `mail` and `site` | `mail_log_days` (JP 1825, TW 2555) | RETENTION job; an unfinished send stays until a person resolves it |
| Job outputs, attachments | objects volume | `outputs_days` 365, `attachments_days` 90 | RETENTION job, hashes kept in the audit |

Set `TB_LOG_DIR` and `TB_AUDIT_ARCHIVE_DIR` in `deploy/.env` to the hospital share (install.sh writes local
defaults). By hand: `sudo python3 -m tools.trialbox logs collect --day 2026-11-08`, `... logs prune`,
`... logs archive-audit`. An audit chain that does not verify is not archived: run `tools/audit_verify.py` first.

Everything is a job. To see jobs, send `STATUS <job id>` by mail, or use the orchestrator API from the host:
`curl -s localhost:8010/jobs?limit=20` (the port is published only in the test profile; otherwise run
`docker compose exec orchestrator …`).

## 3. Mail commands (§5)

`<COMMAND> <ruleset> [key=value …] [-- comment]`. Allowed senders and groups are in `settings.permissions`.

| Command | Example | Result |
| --- | --- | --- |
| FEAS | `FEAS GZQO lookback=36` (attach the protocol the first time) | feasibility PDF + XLSX (aggregate) or the review package |
| APPROVE | reply to the review mail with the filled `review.xlsx` | approved ruleset (tag) or the next review round |
| SCREEN | `SCREEN GZQO version=1.0.0 pract=P12345` | encrypted candidate workbook to list recipients + summary PDF |
| FEEDBACK | `FEEDBACK GZQO` + `screen_feedback.csv` | stored for calibration |
| NAV | `NAV RA-BIO dept=RHEU` | four lists, application drafts, TWPAS bundles + validation |
| SUBMIT | `SUBMIT ONC-OSI pid=<pid> bundle=<NAV job id>` (physicians) | ClaimResponse (dry run unless `twpas.dry_run: false` and `NHI_TWPAS_BASE_URL` set) |
| COHORT | `COHORT GOUT-COH lookback=4` | alliance CSV, report PDF, trial simulation XLSX |
| COHORT MERGE | member box → root, `cohort_table_*.csv` attached | merged alliance table |
| STATUS / CANCEL | `STATUS 01J…` / `CANCEL 01J…` | job status / cancellation |
| CASE | `CASE GZQO mrn=10000001 lang=zh-TW` + the chart (PDF/DOCX/TXT/MD) | eligibility sheet (encrypted, to the study team's `list_to`); counts-only mail to a requester outside that list |

PHI attachments arrive as 7z (AES-256). The password comes in a separate mail to the same recipient.

### Console roles and the registry

The console (`services/console`) has three roles: administrator (ingest, users, updates, everything else), study
coordinator (requests, approvals, the candidate registry, consent drafts) and viewer (read only). Administrators add
accounts on **Users** (`/ops/users`): the one-time password is shown once; hand it over in person. With a hospital
reverse proxy that authenticates staff, set `TB_CONSOLE_SSO_HEADER` (e.g. `X-Forwarded-User`),
`TB_CONSOLE_SSO_TRUSTED_PROXIES` (the proxy addresses or CIDRs), optionally `TB_CONSOLE_SSO_ROLE_HEADER` and
`TB_CONSOLE_SSO_ROLE_MAP=ad-group:admin,crc-group:coordinator`; staff then sign in without a console password.
The **Registry** page keeps the per-study screening log (add by chart number, take over a SCREEN run's candidates,
record contact/consent/enrolment, export XLSX for the monitor). The **Single case** page uploads one chart (CASE).

## 4. Troubleshooting

| Symptom | Check | Fix |
| --- | --- | --- |
| No reply to a mail | mail-gateway logs: `docker compose logs mail-gateway --since 1h` | sender not in the allowlist, SPF/DKIM failed (`require_spf_dkim`), or the rate limit was reached; the gateway logs the reason (no PHI) |
| "Ruleset X has no approved version" | `ls /data/rulesets/X`, `git -C /data/rulesets tag` | attach the protocol to `FEAS X`, then approve the review workbook |
| Ingest `passed: false` | `ingest_report.json` → `errors`, `validation.messages` | mapping change on the HIS side: run `mapping_check.py` and fix the site mapping |
| Equivalence gate below 98 % | review workbook "equivalence" sheet | edit the flagged criteria in the workbook (APPROVE round), or reject them |
| TWPAS validation errors | `twpas_validation_<RS>.json` | missing record data (weight/height, gene report) shows as pre-check issues; complete the record and rerun NAV |
| SUBMIT refused | the reply names the failed check | NAV older than 14 days → rerun NAV; validator/pre-check not run → start fhir-store / install the validator |
| Lake queries slow or OOM | `docker stats`, lake logs | raise `TB_LAKE_MEMORY_LIMIT` (default 40 % of RAM; spills to `/data/lake/tmp`) |
| Containers lost egress after a restart | `deploy/network.sh status` | `deploy/network.sh apply` (systemd unit re-applies it automatically) |
| GB10 vLLM fails to start | `nvidia-smi`, `deploy/check_host.sh --gb10` | driver must be 580.142 |
| `CERTIFICATE_VERIFY_FAILED` to a model endpoint, the registry or the mail server | hospital TLS inspection re-signs outbound HTTPS | put the hospital CA (PEM) on the host and set `TB_EXTRA_CA=/abs/path/hospital-ca.pem` in `deploy/.env`, then `docker compose up -d`; gateway, criteria-compiler, orchestrator and mail-gateway trust it next to the public CAs (`tb_common.extra_ca`) |

Job errors always name the step (`received`, `parsing`, `compiling`, `running`, `reporting`) and come back to the
requester as a "Failed" mail with a plain-language message.

## 5. Updates, backup, restore, secrets

- **Updates** (D-138): `sudo tools/apply_update.sh trialbox-<version>.tar --dry-run`, then without `--dry-run`.
  1. The bundle is verified (vendor signature, every hash); a tampered or unsigned bundle is rejected and nothing
     changes.
  2. **Backup first** (D-126): the box's encrypted backup to `TB_BACKUP_TARGETS` with `deploy/secrets/backup.pub`.
     No key or no target: the update refuses and changes nothing. The services stop for the backup (the database
     stays up), so the backup is consistent.
  3. **Rollback point**: the images it replaces are tagged `<repo>:rollback-<bundle>`, overwritten model files kept,
     both databases dumped locally (`deploy/updates/<bundle>/rollback/`, 0600, removed after a good update).
  4. **Apply, migrate, restart**: images loaded, models copied, `docker compose up -d --wait` (each service runs its
     migrations at start), then the bundle's rulesets (approval and equivalence gates), then the health check
     (and `TB_UPDATE_CHECK_CMD` when set).
  5. **Success**: `update.applied` in the audit. **Failure** after step 3: images tagged back, models put back,
     databases restored from the local dump, restarted, checked again; `update.rolled_back` in the audit; exit 1.
  Every step is in `deploy/updates/history.jsonl`. `--no-backup` exists for a test box only and is audited. If the
  rollback itself fails, restore from the backup (below). The demo VM uses `--target demo` (`docs/DEMO_VM.md`).
- **Backup** (D-126): `python -m tools.trialbox backup-keygen --private /media/usb/trialbox-backup.key --public
  deploy/secrets/backup.pub` once, with hospital IT (the private key goes in their sealed envelope; the box keeps
  only the public key); then `trialbox backup --to <NAS share> --to <USB disk>`. Check one with `trialbox
  backup-verify <file> --key <private key>`.
- **Audit archive**: nightly by `trialbox logs daily` (§2 "Logs"); never use `rsync --delete` on the audit volume.
  Verify with `docker compose exec orchestrator python /app/tools/audit_verify.py /data/audit`.
- **Ruleset repository**: `/data/rulesets` is a git repository. Push it to the hospital git server, or tar it with
  the audit backup.
- **Restore**: reinstall (section 1), then `trialbox restore <file> --key <private key> --yes` (hospital IT brings
  the key). The lake and FHIR store rebuild from the next ingest if they were not in the backup.

### Secrets (D-128, D-138): the one place to rotate them

Each TrialBox service has its own token, and accepts only its own callers (`tb_common.service_auth.CALLERS`; a
doc-parser token is refused by the orchestrator). Where everything lives is on the network sheet
(`deploy/site/network-sheet.<lang>.html`); no value is ever printed or logged.

| Command (as root, in `/opt/trialbox`) | What it does |
| --- | --- |
| `python3 -m tools.trialbox secrets status` | each token's file, mode (0600) and age; whether the old shared token still works |
| `python3 -m tools.trialbox secrets rotate` | **at handover and then yearly**: every service token, the operator token and both database passwords; recreates the services; ends the old shared token |
| `python3 -m tools.trialbox secrets rotate --service orchestrator` | one service's token (repeat `--service` for more); only that service restarts |
| `python3 -m tools.trialbox secrets rotate --service db` | the two database passwords (`ALTER ROLE`, password on stdin), then every service that uses them |
| `python3 -m tools.trialbox secrets init` | make any missing token (install.sh runs it) |

The mail passwords and a cloud-model key are the hospital's: change them at their source, put the new value in
`deploy/.env`, then `docker compose --project-directory deploy up -d --force-recreate mail-gateway` (or `gateway`).
A box installed before step 8 keeps its one shared `TB_SERVICE_TOKEN` working, with a warning in the service logs,
until the first full `secrets rotate`. The administrator's own token for scripts on the host is
`deploy/secrets/services/operator.token` (send it as `X-TB-Service-Token`).

## 6. Go-live acceptance (§11.2)

`tools/acceptance.py` writes one result per criterion under `acceptance/` and a summary with
`tools/acceptance.py report`:

1. `ingest --report <ingest_report.json>`
2. `feas --system <FEAS raw json kept in the box> --manual manual_counts.csv`: the CRC's manual CGRD funnel.
3. SCREEN, in two steps:
   - `screen-sample --candidates <candidates.json> --ruleset rulesets/<ID> --scoped scoped.txt --n 120` produces
     the blinded `adjudication.xlsx` for the CRC (four strata; criterion labels from the ruleset).
   - When it is filled in, run `screen --candidates … --ruleset rulesets/<ID> --adjudication adjudication.xlsx
     --key adjudication_key.json` (criterion classes come from the ruleset's IR).
4. `nav --lake <lake> --ruleset rulesets/RA-BIO`: the 12-month retrospective against the NHI outcomes.
5. `twpas twpas_validation_*.json`
6. `reproduce --results rerun.jsonl`, after
   `docker compose exec orchestrator python -m orchestrator.rerun <job ids> > rerun.jsonl` (re-executes finished
   jobs on their snapshot in a sandbox and compares every output hash).
7. `audit --dir <audit copy>`

## 7. Contacts and escalation

- Box contact: `settings.site.contact`. Vendor support: per the support contract; send `ingest_report.json`,
  `docker compose ps` and the failing job id, **never** patient lists or the pid map.
- Security incident (suspected PHI exposure): stop mail egress (`docker compose stop mail-gateway`), keep the box
  running for the audit trail, and follow the hospital incident procedure. The audit chain shows every output file,
  its sha256 and its recipients.

## 8. DGX Spark end to end

One command brings up the whole stack on an NVIDIA GB10 box (DGX Spark class, aarch64, 128 GB unified memory) with
the local models behind tb-gateway, and checks it end to end on synthetic and open data:

```sh
make spark-e2e                       # GB10: two vLLM servers + the pinned judge and verifier
TB_LLM_MODE=stub make spark-e2e      # any Docker host without a GPU (x86 or arm64): deterministic stub
```

**Default models (the measured pair, D-124).** The judge is **Gemma 4 26B-A4B-it NVFP4** (`j-workhorse`, build
`gemma-4-26b-a4b-it-spark`, `llm-service`, endpoint `serving`) and the verifier **Qwen3.5-9B AWQ 4-bit**
(`v-verifier`, build `qwen3.5-9b-spark`, `llm-verifier`, endpoint `verifier`), both resident at 16k. These are the
same weights as the RTX PRO 6000 and RTX 5090 profiles, measured on the card on 2026-11-08; gpt-oss-120b is no longer
the Spark judge. The cascade runs the two-model `AgreementJudge`: every decided S3 answer is put to the verifier, and
a criterion blocks a patient only when both models agree; any disagreement becomes `unknown` (never an exclusion).
The front desk (`f-frontdesk`) on P-GB10 is the judge's weights at 16k (build `gemma-4-26b-a4b-it-frontdesk-spark`,
pinned separately). The builds are unpinned seeds: the site pins the weights it downloaded (below). Memory, as set
in `docker-compose.gb10.yml`, **not measured on a Spark** (measured when a site orders one): `JUDGE_GPU_MEM_UTIL`
0.30, `VERIFIER_GPU_MEM_UTIL` 0.15, the rest for HAPI (6 GB heap), Postgres, DuckDB, the embedder and the services.
`llm-verifier` starts only after `llm-service` is healthy (vLLM checks free memory at start). `install.sh` starts
this profile only on a record from `tools/serving_config.py measured gb10`, or with `TB_ACCEPT_UNMEASURED_GPU=1`.

**RTX PRO 6000 (P-PRO6000).** `install.sh` detects the card (`deploy/gpu_profile.sh`) and adds
`docker-compose.rtxpro6000.yml`: the same pair, both resident at 32k, 0.40 and 0.20 of the card, no swap. The
vendor's record ships in `deploy/measured/`; a site may capture its own (`deploy/gcp/capture-serving-config.sh`,
`deploy/site/serving_config.rtxpro6000.json`).

**Alternative: Qwen alone.** `JUDGE_MODEL_DIR=qwen3.5-35b-a3b-q4 JUDGE_MODEL=qwen3.5-35b-a3b-q4 JUDGE_MAX_LEN=32768
TB_PIN_BUILD=qwen3.5-35b-a3b-candidate TB_SPARK_VERIFIER=0 make spark-e2e` serves the 4-bit Qwen3.5-35B-A3B as the
only model (no `llm-verifier`, single-model judge). Qwen is PRC-origin: a `public_agency: true` site needs a non-PRC
build for every role (MOD-1), which the default pair is.

**Prerequisites (GB10 mode)**

- NVIDIA driver **580.142**, held (`apt-mark hold` on the driver packages; later 580.x builds regress vLLM on GB10,
  D-79). Docker Engine 27+ with `nvidia-container-toolkit` configured (`docker info | grep -i nvidia`).
- amd64 emulation for MailHog (test profile only; MailHog ships amd64 only): `ls /proc/sys/fs/binfmt_misc/qemu-x86_64`,
  else `docker run --privileged --rm tonistiigi/binfmt --install amd64` once.
- Model weights (safetensors or GGUF only) in `deploy/models/<JUDGE_MODEL_DIR>` (default
  `deploy/models/gemma-4-26b-a4b-it-4bit`, NVIDIA's NVFP4 release) and `deploy/models/<VERIFIER_MODEL_DIR>` (default
  `deploy/models/qwen3.5-9b-4bit`, the AWQ 4-bit build); `deploy/models/bge-m3` for the embedder when `TB_EMBED_MODE`
  is not `hash`. The directories must not contain pickle weights (`.bin`, `.pt`) or Python files: the pin refuses
  them. The vLLM served names are `JUDGE_MODEL` / `VERIFIER_MODEL` (defaults `gemma-4-26b-a4b-it`, `qwen3.5-9b`).
- Disk: about 19 GB (judge) + 9 GB (verifier) of weights, 15 GB for images (vLLM GB10 image included), 10 GB for
  volumes and runs.
- `.venv` (`make venv`) and, for `make images`, the build prerequisites of section 1 (`tools/fetch_jvm_deps.sh` needs
  network and Maven the first time). With images already loaded, set `TB_SPARK_SKIP_BUILD=1`.

**What it does** (`tools/spark_e2e.sh`): host check (`deploy/check_host.sh --gb10`; aarch64, driver and NVIDIA runtime
must pass, the appliance-hardening lines are reported only unless `TB_SPARK_STRICT_HOST=1`) → `make images` (native
arm64) → `tools/pin_model.py` pins both models into `deploy/site/registry.site.yaml` (site override, never the
committed registry; the judge on endpoint `serving`, the verifier on `verifier`) → compose `up --wait` with
`docker-compose.gb10.yml`, profiles `gpu` + `test` → gateway probe (site pins loaded, one call answered by each pinned
build) → `trialbox doctor` → ingest synthetic site A → `FEAS GZQO` mailed to
GreenMail, PDF reply checked in MailHog → `tools/cascade_e2e.py` through the gateway (two-model `AgreementJudge`,
`TB_GATEWAY_VERIFIER_URL`) → `make eval-public` through the
gateway (`TB_EVAL_LIMIT` judge pairs, default 300; 0 = all 1015) → outbox and recall-ledger tests on the compose
`workflow-db` (a separate `trialbox_wf_e2e` database).

Every model call goes `service → gateway → llm-service | llm-verifier`: only the gateway is on `model-net`. The stack
runs in the TEST environment with D0 labels, and callers ask for the alias `j-workhorse` (`TB_GATEWAY_MODEL`; the
cascade's verifier asks for `v-verifier`), which the gateway serves only from a pinned build; an unpinned build is
refused (`build_unpinned`), never replaced by the stub.

**PASS** means every step passed and every cascade and eval answer came from the build whose sha256 is in the site
override (`TB_GATEWAY_EXPECT_SHA`; verifier answers from `TB_GATEWAY_VERIFIER_EXPECT_SHA`). The report is printed and kept in `build/spark-e2e/<time>-<mode>/report.md`
(`report.json`, `logs/NN-<step>.log`, `logs/compose.log`, `cascade/e2e_summary.md`); exit status 0 only on PASS.
The judge suite in live mode passes on its floors (no refusals, ≥ 95 % valid labels), not on the recorded reference;
its accuracy is reported. The cascade reproducibility check is off in GB10 mode (`TB_SPARK_REPRO=1` turns it on).

In stub mode the pinned builds are placeholder directories pinned into a throwaway override in the run directory and
answered by llm-stub (network aliases `llm-service` and `llm-verifier`): it proves the pin → registry → gateway path,
not a model.

**Pinning by hand.**

```sh
python -m tools.pin_model --build gemma-4-26b-a4b-it-spark --model-dir deploy/models/gemma-4-26b-a4b-it-4bit \
    --served-name gemma-4-26b-a4b-it
python -m tools.pin_model --build qwen3.5-9b-spark --model-dir deploy/models/qwen3.5-9b-4bit \
    --served-name qwen3.5-9b --endpoint verifier
python -m tools.pin_model --build gemma-4-26b-a4b-it-frontdesk-spark --model-dir deploy/models/gemma-4-26b-a4b-it-4bit \
    --served-name gemma-4-26b-a4b-it      # front desk (f-frontdesk) on the judge server
# RTX PRO 6000: the same commands with the -rtxpro6000 builds
```

`--verify` re-checks the weights against the pin;
`--status champion` is needed before PRODUCTION roles route to it (a G5 decision, §8.16). Restart the gateway after a
new pin (`docker compose restart gateway`).

| Symptom | Check | Fix |
| --- | --- | --- |
| `host-check` FAIL on driver / runtime | `nvidia-smi`, `docker info` | install and hold 580.142; `nvidia-ctk runtime configure --runtime=docker` and restart Docker |
| `pin-model`: weights not found / refused file types | `ls deploy/models/<dir>` | place safetensors/GGUF weights; remove `.bin`/`.py` files (or convert) |
| `compose-up` times out on llm-service / llm-verifier | `docker compose logs llm-service llm-verifier` | first load takes up to 10 min; out of memory → lower `JUDGE_GPU_MEM_UTIL` (0.30) / `VERIFIER_GPU_MEM_UTIL` (0.15) or `JUDGE_MAX_LEN` / `VERIFIER_MAX_LEN`; verifier "free memory" error at start → the judge took more than planned, lower `JUDGE_GPU_MEM_UTIL`; unknown flag → check the vLLM version of `VLLM_GB10_IMAGE` (`--guided-decoding-backend` was renamed in newer vLLM) |
| `compose-up`: mailhog exits (`exec format error`) | `ls /proc/sys/fs/binfmt_misc` | install amd64 emulation (see prerequisites) |
| `gateway-probe`: `build_unpinned` | `curl 127.0.0.1:8020/registry/v1/builds` | the gateway started before the pin: `docker compose restart gateway` |
| `gateway-probe`: `served_model_mismatch` | vLLM `--served-model-name` | `JUDGE_MODEL` / `VERIFIER_MODEL` must equal the `--served-name` given to the pin |
| `gateway-probe`: `upstream_failed` | `docker compose logs gateway llm-service llm-verifier` | vLLM not healthy, or it rejected the `json_schema` response format (structured-output backend) |
| `cascade-e2e` FAIL `gateway_build_pinned` / `verifier_build_pinned` | `cascade/e2e_summary.md` (Gateway line) | some answers came from another build: check `TB_GATEWAY_MODEL`, `TB_GATEWAY_VERIFIER_MODEL` and the override |
| `eval-public` FAIL in live mode | archive JSON named in the log (`gateway`, `metrics`) | refusals (`phi_tripwire`, `upstream_failed`) or a valid-label rate under 95 % |
| `workflow-store` FAIL | `docker compose logs workflow-db` | port 5433 taken: set `TB_HOST_WORKFLOW_DB_PORT` in `deploy/.env` |

## 9. Proof of concept: admin console + e-mail in one command

`deploy/poc.sh` (`make poc`; Windows: `powershell -ExecutionPolicy Bypass -File deploy\poc.ps1`) runs the whole box
on synthetic data with the test mail servers and the admin console (`services/console`). It is a pilot, not a site
install: TB_ENV is TEST (DEV in OpenRouter mode) and every data class is D0.

**Modes** (`TB_LLM_MODE`): `stub` (default; deterministic stub, no GPU, no key), `openrouter` (TB_ENV=DEV;
`j-workhorse` is pinned to `TB_OPENROUTER_MODEL`, default `nvidia/nemotron-3-nano-30b-a3b`, in `deploy/poc/site`; the key
comes from `OPENROUTER_API_KEY` or `deploy/poc/secrets/openrouter_api_key` and is passed to the gateway container
only, never written to the repository; OpenRouter routes accept D0 only), `gpu` (vLLM; GB10 override on aarch64; needs
the site pin of §8 in `deploy/site/registry.site.yaml`).

**What it does**: Docker check → `deploy/.env` from `.env.example` with random MinIO/Postgres passwords (first run
only; an existing file is kept) → images (`make images`, or a throwaway `maven` builder container when the host has
no Maven/Python; `TB_POC_BUILD=1` forces a rebuild) → `deploy/poc/settings.yaml` (the example settings plus the
administrator's mailbox `TB_POC_ADMIN_EMAIL`, default `admin@hospa.test`, in senders, reviewers and internal domains)
→ compose up with `docker-compose.yml` + `docker-compose.test.yml` + `docker-compose.poc.yml` → console administrator
(random password printed once) → ingest synthetic site A → URLs. `deploy/poc.sh status|down|reset`.

**Console accounts.** No default password. Inside the container:
`docker exec -i trialbox-console-1 python -m console.cli <command>` with `bootstrap-admin`, `add-user NAME --role
admin|viewer [--mailbox ADDR] [--password-stdin]`, `reset-password NAME`, `disable NAME`, `list-users`, `ingest`.
Alternatively `TB_CONSOLE_ADMIN_PASSWORD_FILE` (a compose secret) creates the first administrator at first start.
scrypt hashes; 5 failed sign-ins lock an account for 15 minutes; sessions end after 30 min idle or 8 h; CSRF token on
every form; CSP without scripts. Administrators start requests; viewers read. Every action is a `console.*` event in
the audit chain (`console.request` carries the exact line and the mailbox it runs as).

**No side doors.** A console request is the exact e-mail subject (`FEAS GZQO lookback=36`, `APPROVE X version=1.0.0`,
shown on the job page) and the same `POST /jobs` the mail gateway makes, as the user's mailbox: `settings.permissions`,
the rate limit, job audit and the delivery routing rule apply, and results also go out by mail. Plain words go to
`classify_intent` through tb-gateway; the console shows the proposed line and runs it only after **Confirm**. Patient-
level outputs (`phi`) are never downloadable; counts 1–4 are shown as `<5`. The v4 cascade page runs the MS1 slice
(`tools/cascade_e2e`) in the console container and serves only its D1 outputs (DL-1 PDF/XLSX/JSON, recall
certificate).

**Surface rule.** The pilot workspace (`/pilot/...`) is not one of the C-5′ product surfaces: the console refuses to
start with `TB_CONSOLE_PILOT=1` unless TB_ENV is DEV/TEST and `TB_DATA_CLASS=D0`. With the pilot off (any production
compose), only the §3.8 control-plane routes exist: health, job list and audit (metadata only) and the ingest action.

**Use a real mailbox instead of GreenMail/MailHog.** In `deploy/.env` set `IMAP_HOST`, `IMAP_PORT=993`,
`IMAP_SSL=true`, `IMAP_USER`, `SMTP_HOST`, `SMTP_PORT=587`, `SMTP_STARTTLS=true`, `SMTP_USER`, `MAIL_INTAKE_ADDR` and
`MAIL_FROM_ADDR` (the box's mailbox), `TB_MAIL_AUTHSERV_ID` (first token of your provider's `Authentication-Results`
header, e.g. `mx.google.com`), and put the app passwords in `IMAP_PASS` / `SMTP_PASS` (Gmail/Microsoft 365: an *app
password* for the box's own mailbox; keep `deploy/.env` at mode 600, never commit it). Set `TB_POC_ADMIN_EMAIL` to the
address you will send from, and run `TB_POC_MAIL=real deploy/poc.sh`: GreenMail and MailHog are not started, the
Test mailbox page is hidden, and the mail gateway polls your mailbox.
Replies then arrive in your own inbox; the console still shows each job's thread from the mail gateway's index.

**Remote access.** The console binds to 127.0.0.1 (`TB_POC_BIND`). Do not publish it on 0.0.0.0. Put a TLS reverse
proxy in front and set `TB_CONSOLE_SECURE_COOKIE=1`, for example Caddy on the same host:

```
trialbox.example.org {
  reverse_proxy 127.0.0.1:8090
}
```

(nginx: `proxy_pass http://127.0.0.1:8090; proxy_set_header X-Forwarded-Proto https;`). Restrict the proxy to your
network or a VPN (Tailscale, Cloudflare Access) — the pilot holds synthetic data only, but the sign-in page is still a
target. On a cloud VM open only 443.

**Checks**: `make test-console` (unit, no Docker) and, with the POC running, `make test-console-e2e` (Playwright on
Node: web FEAS → result → PDF; e-mail FEAS → MailHog + console thread; test mailbox; protocol compile → approve →
resumed FEAS; plain words → proposal → confirm; cascade → DL-1 + certificate; viewer refused).
`TB_CONSOLE_SCREENSHOTS=<dir>` saves screenshots.

| Symptom | Fix |
| --- | --- |
| console restarts: `unable to open database file` | image older than the console: `TB_POC_BUILD=1 deploy/poc.sh` |
| sign-in page says no administrator exists | `docker exec -it trialbox-console-1 python -m console.cli bootstrap-admin` |
| "Refused: … not permitted" | the user's mailbox is not in `settings.permissions` groups: re-run `deploy/poc.sh` with the right `TB_POC_ADMIN_EMAIL` |
| FEAS fails "no snapshot" | Overview → **Ingest synthetic site A** (or `console.cli ingest`) |
| port 8090/8025/3025 taken | `TB_HOST_CONSOLE_PORT`, `TB_HOST_MAILHOG_PORT`, `TB_HOST_SMTP_PORT` |

## 10. One RTX 5090: model swap, night self-test, chat time limit

The 2026-11-07 survey (`docs/reviews/2026-11-07-open-llm-survey.md`) keeps Gemma 4 26B-A4B (judge) and Qwen3.5-9B
(verifier) for one RTX 5090. Side by side they need about 35 GiB, so `docker-compose.rtx5090.yml` runs them **one at
a time** (`TB_MODEL_SWAP=sleep`, the default there):

| What | How it works | Where |
|---|---|---|
| Start | judge loads and sleeps, verifier loads and sleeps, judge wakes (`judge-sleep-init`, `model-swap-init`, `judge-wake-init`) | `deploy/docker-compose.rtx5090.yml` |
| Day | judge awake: chat, protocol help, interactive CASE | |
| Screening run | judge answers every note question first; the gateway then sleeps the judge and wakes the verifier for the second opinions; the judge wakes again at the end. Same answers as the inline two-model run, in a different order | `services/orchestrator/twophase.py`, `services/gateway/swap.py` |
| Chat while the verifier is awake, or a model call over 30 s | the person gets "the model is busy, try again in a few minutes" in their language, at once; batch jobs keep the long limit | `TB_GATEWAY_INTERACTIVE_TIMEOUT_S` (30) |
| Before the night's LLM jobs | 54 known questions (EN/JA/zh-TW) to each model; MICROBATCH, NAV, COHORT and CALIBRATION start only when both pass (≥95% answered, ≤1 yes/no flip, ≥85% right) and the pair, scored as the box decides (a decided answer only when both models give it), agrees on a wrong decided answer in at most 1 case. Result in the audit log (`selftest.passed` / `selftest.failed`) and `/data/orchestrator/selftest.json` | `services/orchestrator/selftest.py`; `make selftest` by hand (in the box), `make canary` from a checkout; `TB_SELFTEST=off` to skip |
| Install | every pinned model's weight hashes are re-checked; a mismatch stops the install | `python -m tools.pin_model --verify-all deploy/models`, `make verify-models` |
| vLLM | `vllm/vllm-openai:v0.32.0`, the release the 2026-11-06 GPU run measured, with its flags (`--enforce-eager`, 4 sequences, 8k context, image inputs off, Qwen thinking off) | `VLLM_IMAGE` |

Check the swap by hand: `curl -s http://gateway:8020/v1/serving/status` (inside trialbox-net) shows which model is
awake and how long the last swap took.

**Measured 2026-11-08** on an RTX PRO 6000 capped to 32 GB (same caps): one model awake uses 27-29.6 GB of the
card in all, the sleeping one 1.3 GB; the second server starts while the first sleeps; sleep takes 0.4-3.7 s and
wake 0.3-0.5 s. Side by side the pair does not fit. Not yet run on a physical 5090. Host RAM must hold the sleeping
model (64 GB or more).

**Install guard (D-112).** `install.sh --gpu rtx5090` starts the pair only on a serving-config record taken on a
real 5090 with this profile (`deploy/site/serving_config.rtx5090.json`, checked by `python -m tools.serving_config
measured rtx5090 <file>`: complete, the card is a 5090 and not a capped larger card, sleep mode on both servers). For
the first boot on a new card set `TB_ACCEPT_UNMEASURED_GPU=1`, then capture the record
(`deploy/gcp/capture-serving-config.sh`, or `python3 tools/serving_config.py capture ...` on the box) and copy it there.

**After a host reboot** run `docker compose ... up -d --wait` again (or `deploy/install.sh --yes`): Docker restarts
the two vLLM containers together and the start-order helpers run only under compose, so the second model can fail
its start until the stack is brought up in order.
