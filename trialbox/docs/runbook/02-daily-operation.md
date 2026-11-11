# 2. Daily operation

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

## Logs (D-138)

| Log | Where | Kept | How |
| --- | --- | --- | --- |
| Service logs (JSON, pseudonyms only) | containers (`TB_LOG_MAX_SIZE` × `TB_LOG_MAX_FILE`, 100 MB × 10 each), then `TB_LOG_DIR/services/<day>/<service>.log.gz` | `logs_days` (365) | `trialbox logs daily` |
| Host logs `/var/log/trialbox-*.log` (retention and backup cron) | the host | 53 weeks | `/etc/logrotate.d/trialbox`, from `install.sh` (D-389) |
| Audit chain | volume `audit-data`, copied to `TB_AUDIT_ARCHIVE_DIR/<year>/<day>.jsonl.gz` | never deleted (10 years on the box) | copied, compressed and verified nightly |
| Mail logs | trial database, schemas `mail` and `site` | `mail_log_days` (JP 1,825, TW 2,555) | RETENTION job; an unfinished send stays |
| Job outputs, attachments | objects volume | 365 and 90 days | RETENTION job; hashes kept in the audit |

Set `TB_LOG_DIR` and `TB_AUDIT_ARCHIVE_DIR` in `deploy/.env` to the hospital share. By hand:
`sudo python3 -m tools.trialbox logs collect --day 2026-11-08`, `logs prune`, `logs archive-audit`. A chain that does
not verify is not archived: run `tools/audit_verify.py` first. Never use `rsync --delete` on the audit volume.
Held by `tests/unit/test_log_retention.py`.

**Log gaps (D-389, OPS-034).** Each collected day has `COVERAGE.json`: per service the day's bytes and lines, the share
of the container's cap it used and `gap`. A gap means docker had already rotated away the start of the day before the
00:20 collection, so lines are missing. `logs daily` then exits 1 (the cron log says `LOG GAP` and names the
services) and warns earlier, when a day used over three quarters of the cap. The fix: raise `TB_LOG_MAX_SIZE` or
`TB_LOG_MAX_FILE` in `deploy/.env` and run `docker compose up -d` (the containers are recreated with the new cap). The
caps of 100 MB × 10 are provisional and not measured: they rest on the review's estimate of the busiest night (about
300 MB). Re-size them from the `COVERAGE.json` of the first full night. Held by `tests/unit/test_log_caps.py`.

## EDC prefill (D-160)

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
