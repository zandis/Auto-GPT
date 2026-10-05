# TrialBox runbook

This is for the site operator (IT) and the CRC office. Users never log in: they send email to the box and get email
back. Every command below runs on the appliance host from the repository directory (`/opt/trialbox`) as root unless
noted. Section references (§) are to `SPEC.md`; D-numbers are entries in `docs/DECISIONS.md`.

## 1. Install a new site (≈ 1 day)

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
5. **Start.** `cd deploy && docker compose --profile gpu up -d --wait`. Use `--profile stub` without a GPU, and add
   `-f docker-compose.gb10.yml` on GB10. Then apply the egress rules: `deploy/network.sh apply`.
6. **Vendor key.** Install `deploy/keys/vendor_ed25519.pub` (from the vendor, out of band).
7. **First ingest.** `docker compose exec adapter python -m adapter.cli run`, or wait for 02:00. Check
   `/data/lake/ndjson/<date>/ingest_report.json`: `passed: true`, validator errors < 0.5 %.
8. **Host check.** `deploy/check_host.sh [--gb10]`: no FAIL lines.
9. **Acceptance (§11.2)** before go-live: see section 6.

## 2. Daily operation

| When | What | Where to look |
| --- | --- | --- |
| 02:00 | INGEST (adapter → FHIR store + lake, 1 % HL7 validator sample, snapshot pruning) | job list, `ingest_report.json` |
| 05:00 | RETENTION (attachments 90 d, outputs 365 d, retired pools 24 months) | `retention_<date>.json` output |
| Mon 03:00 | MICROBATCH per ruleset with a pool → `this_week_visit1.xlsx` to list recipients | mail |
| Mon 03:30 | NAV per approved NHI ruleset → lists, drafts, TWPAS bundles | mail |
| 1st 05:30 | CALIBRATION per ruleset with feedback | `calibration.json` |
| 1st of Jan/Apr/Jul/Oct 04:00 | COHORT per cohort ruleset (member boxes mail their table to the alliance root) | mail |

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

PHI attachments arrive as 7z (AES-256). The password comes in a separate mail to the same recipient.

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

Job errors always name the step (`received`, `parsing`, `compiling`, `running`, `reporting`) and come back to the
requester as a "Failed" mail with a plain-language message.

## 5. Updates, backup, restore

- **Updates**: `tools/apply_update.sh bundle.tar --dry-run`, then without `--dry-run`. Tampered or unsigned
  bundles are rejected and nothing changes. Every application is audited (`update.applied`).
- **Audit backup**: nightly `rsync -a /var/lib/docker/volumes/trialbox_audit-data/_data/ <hospital share>/trialbox-audit/`.
  Never use `--delete`. Verify with `docker compose exec orchestrator python /app/tools/audit_verify.py /data/audit`.
- **Ruleset repository**: `/data/rulesets` is a git repository. Push it to the hospital git server, or tar it with
  the audit backup.
- **Restore**: reinstall (section 1, steps 1–6) and restore the volumes `rulesets-data`, `orch-data`, `audit-data`,
  `tb-secrets` (sealed keys) and `minio-data`. The lake and FHIR store rebuild from the next ingest.

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
