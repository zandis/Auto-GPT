# 2. Daily operation

**Reader:** the box owner.

| When | What | Where to look |
| --- | --- | --- |
| 00:20 | `trialbox logs daily` (cron on the host): collect yesterday's service logs, prune, archive the audit | `/var/log/trialbox-retention.log` |
| after it | `trialbox audit-sign` (the same cron line; D-562): checks the audit chain against every earlier signed head, then signs where the chain stands and writes the signed head, write-once, to every folder of `TB_AUDIT_ANCHOR_TARGETS` (a folder off the box, such as the hospital's share). A chain that does not agree is not signed again: the log says so, and `tools/audit_verify.py <audit folder> --heads <anchor folder>` shows where. `trialbox doctor` (check `audit_heads`) FAILs in PRODUCTION when no folder is set, the audit key is missing or the newest signed head is older than `TB_AUDIT_HEAD_MAX_AGE_H` (36 hours), or when the last night was refused. A box installed before D-562 gets the cron line and the audit key when `deploy/install.sh` (or `sh deploy/hardening/seal_keys.sh --secrets <the secrets volume>`) runs again | `/var/log/trialbox-retention.log`; `deploy/logs/audit-sign.json`; event `audit.head_signed` |
| 02:00 | INGEST: adapter to FHIR store and lake, validator sample (1 % of each resource type, at least 3 and at most a cap: 4,975 at the default limit, `TB_VALIDATION_SAMPLE_CAP`; D-457), snapshot pruning | job list, `ingest_report.json` (`validation.sample_cap`, `validation.capped`) |
| 03:00 | REDCap read-back (console timer) | the study's Sources page |
| before the night's model jobs | the pair canary (54 questions); model jobs start only when it passes | `selftest.passed` in the audit |
| 07:00, 07:30 | morning mail N1 (coordinator) and N2 (investigator), console timers | Notices received |
| after the ingest has passed, in this order, each when the one before it has ended (D-492) | the night's chain: MICROBATCH per study with a pool (the weekly one on Monday, else the one for new booked patients; never both), then on Monday NAV per ruleset, then RETENTION (attachments 90 days, outputs 365 days, mail logs by country; the lists an open study's next micro-batch reads are kept whatever their age: `kept_for_open_studies`, D-458). `schedule.microbatch`, `.nav` and `.retention` name the day only; their hour is not read. A Monday whose ingest failed is made up on the next night that passes | mail; `retention_<date>.json`; each job's record names its night (`options.night`) |
| Mon 06:00 | the weekly PI sample of ten "criteria not matched" patients per study (orchestrator, `schedule.not_matched_sample`; D-446) | `notmatched.sample` in the audit |
| 1st of the month 05:30 | CALIBRATION | `calibration.json` |
| quarterly 04:00 | COHORT tables | mail |

**The last full night (D-1254).** A delta night (one run with `--since`) cannot see a record re-filed to another
patient, a merged chart filed again, or an SS-MIX2 file back-filed with an old time; only a full night corrects them.
The data-operations page (`/data-ops`, the *Sources* card) says when the last full night completed and how many
nightly updates ran since (`<lake>/full_nights.json`, written only when a night ends published). It turns to a warning
when that is more than 7 days ago with nightly updates since, or not known with nightly updates since (a lake from
before this record): run the night once without `--since`. A failed, refused or held night does not move it.

**The console reads the same folders (D-638).** The installer mounts each folder of `TB_AUDIT_ANCHOR_TARGETS` into the
console, read-only (`deploy/site/compose.anchors.yml`), so the audit page's Verify checks the chain against the
signed heads. The folder must be there before the install (mount the hospital's share first) and readable by the
console's user; the installer stops with the folder's name when it is not. After the folders change in
`deploy/.env`, run `deploy/install.sh` again; `trialbox doctor` (`anchor_mount`) warns until then. From then on the
console needs the folder at every start: with the share not mounted, the console does not start (docker does not
make the folder: an empty folder on the box's own disk would take the night's signed heads and no one would see
it). Mount the share at boot, before docker. Name a folder below the share's mount point, one that holds the signed
heads only.

The console's timers run when `TB_ENV` is VALIDATION or PRODUCTION (`TB_CONSOLE_TIMERS=on|off` forces it;
`TB_NOTICE_N1_AT`, `TB_NOTICE_N2_AT`, `TB_REDCAP_READ_AT` move them). Everything is a job: see it on the
administrator's Jobs page, or `docker compose exec orchestrator` with the operator token.

`TB_IRB_TEXT_GATE` (D-395): the whole-hospital candidate pages wait for the study's IRB-text record. `auto` (default)
is on in VALIDATION and PRODUCTION; `on` forces it in DEV or TEST; `off` is refused in VALIDATION and PRODUCTION.

`TB_NOT_MATCHED_GATE` (D-446): a study's "criteria not matched" list and its weekly sample wait for the data
steward's record that the site's check (the dry run) passed (`/studies/{rs}/not-matched/check`). `auto` (default) is
on in VALIDATION and PRODUCTION; `on` forces it in DEV or TEST; `off` is refused in VALIDATION and PRODUCTION. Set it
the same for the console and the orchestrator.

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
