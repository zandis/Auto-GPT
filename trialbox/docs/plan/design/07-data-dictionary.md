# TB-DS-07 Data Dictionary and Data Model Specification

| Field | Value |
| --- | --- |
| Document | TB-DS-07 Data Dictionary and Data Model Specification |
| Version | 0.6 (reference; frozen for the build stage) |
| Date | 2026-11-07 |
| Owner | Aimedics (author: Claude, for Changfu Kuo) |
| Status | Frozen reference for the build stage (TB-DS-20). Closes review finding M-01 (TB-REV-006) and the data-model gap in TB-DS-02 §8.10–8.12. |
| Approvals | Product owner: — · Engineering: — · Hospital privacy office (JP): — · Hospital privacy office (CGMH): — |
| Canonical values | TB-DS-00 (baseline decisions). Where this document gives a number, TB-DS-00 wins if they differ. |
| Code baseline | `master` at `a1e55fa`, repository `zandis/Auto-GPT`, directory `trialbox/` |

## 1. Purpose and scope

This document lists every data store that TrialBox owns, every table and field in it, and for each field: type, data class, source, retention and whether it holds personal information (PII). It also lists the FHIR resources and profiles TrialBox uses, with the elements it relies on, and the lake tables built from them.

It is the reference for: the privacy impact assessment (TB-DS-03 DPIA), erasure and data-subject requests, backup scope (TB-DS-04 §10), engineer onboarding, and the hospital IT review.

It does **not** cover data inside REDCap, the EMR, or CGRD. Those are the hospital's stores; TrialBox only reads from them (and, later [L], writes accepted values to REDCap through the External Module, BD-05).

Status tags: **[built]** = present in `a1e55fa`; **[S1]**…**[S5]** = delivered in that build step (TB-DS-20); **[H]** = hospital stage, only when a hospital uses real data; **[L]** = later. The one legend is TB-DS-00 §2.

## 2. Conventions

### 2.1 Data classes (BD-02)

The code-enforced classes in `libs/tb_contracts/dataclass.py` are the only classification. Network zones are a separate concept (TB-DS-02 §7.2).

| Class | Meaning | Examples | May reach an external model? |
| --- | --- | --- | --- |
| D0 | Public | ClinicalTrials.gov text, code, published rulesets | Yes |
| D1 | Confidential, no PHI | Aggregates after small-cell suppression (feasibility funnels, consortium sums, sponsor packs; code: `privacy_accountant` D3 → D1), configuration, metrics, container logs, model manifests | Only under topology C (default off) |
| D2 | De-identified | Date-shifted record-level exports (L); CGRD extracts | No (default) |
| D3 | Pseudonymised | pid instead of chart number; scrubbed notes; lake tables; FHIR store | Never |
| D4 | Identified | Chart number, name, national ID, insurer number; original (unscrubbed) notes | Never |

Rule (built, `libs/tb_common/policy/classes.py`): D3 and D4 never reach an external model in any topology. A container that is not allowed a class fails closed when it receives one.

### 2.2 PII flag

| Flag | Meaning |
| --- | --- |
| **DI** | Direct identifier (name, chart number, national ID, phone, address, insurer number, e-mail of a patient) |
| **QI** | Quasi-identifier (birth date, sex, postcode, rare diagnosis, exact dates) |
| **PS** | Pseudonym (pid, pid alias, GUID encoding) |
| **ST** | Staff personal data (username, staff ID, mailbox) |
| **—** | No personal data |

### 2.3 Retention references (TB-DS-00 §4)

| Code | Rule |
| --- | --- |
| R-AUD | 10 years (N-02) |
| R-GCP | Each study's GCP retention, at least 5 years after study end (N-03) |
| R-SNAP | 3 nightly + 36 month-end snapshots (N-04, D-78) |
| R-OPS | Operational: kept while the account or job is live, then 1 year |
| R-CACHE | Rebuildable cache; deleted with the snapshot it belongs to |
| R-SET | Site setting (`attachments_days`, `outputs_days`; defaults 90 / 365 days) |

### 2.4 Types

SQLite types are as declared in the DDL (`TEXT`, `INTEGER`, `REAL`, `BLOB`). Timestamps in SQLite are ISO 8601 text in UTC unless noted. DuckDB types are as in `services/lake/flatten.py` (`VARCHAR`, `DATE`, `TIMESTAMP`, `DOUBLE`, `BOOLEAN`, `FLOAT[1024]`). Lake timestamps are naive local time in the hospital time zone (`Asia/Tokyo` or `Asia/Taipei`), by design (built, `Flattener.ts`).

### 2.5 One column set for every field table (TB-REV-006g Q-23)

Every table that lists fields in §4 uses the same columns:

| Column | Meaning |
| --- | --- |
| Table | Table (or file record) name in the store |
| Field | Column name; several fields with identical attributes share a row |
| Type | SQLite / PostgreSQL / JSON type as built, or the target type |
| Key | **PK** primary key (several fields: composite); **FK → x** foreign key or logical reference to table or store x; **U** unique; — none |
| Null | **no** = required by the code or target schema; **yes** = may be empty; — = not fixed yet (target tables) |
| Class | Data class D0–D4 or ST (§2.1) |
| PII | §2.2 flag |
| Retention | §2.3 rule for the row; "(proposed)" where the code does not yet enforce it |
| Notes | Values, source, build tag |

Listings that are not field tables keep their own columns: the store inventory (§3), the object-store prefixes (§4.8), the summary of other stores (§4.9) and the status mapping in §4.1. Keys and references across tables are collected in §4.12.

## 3. Store inventory

| # | Store | Engine | Container / volume | Classes | Backup | Status |
| --- | --- | --- | --- | --- | --- | --- |
| S-01 | Orchestrator job DB | SQLite (`orch-data/orchestrator.db`) | orchestrator / `orch-data` | D1, D3 | Nightly | [built] |
| S-02 | Mail gateway store | SQLite (`mail-data/mail.db`) | mail-gateway / `mail-data` | D1, ST | Nightly | [built] |
| S-03 | pid map (vault) | SQLite, AES-GCM blobs (`tb-secrets/pidmap.db`) | adapter / `tb-secrets` | D4 | Nightly, encrypted, offline copy | [built] |
| S-04 | Patient index (alias table `pid_alias`) | PostgreSQL schema `pidmap` | adapter | D3, PS | Nightly, encrypted | [built] |
| S-05 | Console accounts and sessions | SQLite (`console-data/console.db`) | console / `console-data` | ST | Nightly | [built] |
| S-06 | Console site store | SQLite (`console-data/site.sqlite`) | console / `console-data` | D3, ST | Nightly | [built] (`site_profile` and the built registry views). The new study, screening-number, contact-outcome, notification and reconciliation tables are **not** here: they live in S-28 (TB-REV-006f F6-14) |
| S-07 | FHIR snapshot | NDJSON files per resource type | adapter / `lake-data/snapshots/<id>/` | D3 | Covered by snapshot retention; month-ends to backup | [built] |
| S-08 | FHIR store | HAPI JPA 8.12 on Postgres 16 | fhir-store, fhir-db / `fhir-pg` | D3 | Rebuildable from S-07; not backed up separately | [built] |
| S-09 | Lake | DuckDB per snapshot + parquet | lake / `lake-data` | D3 | Rebuildable from S-07 | [built] |
| S-10 | Embedding cache | DuckDB table `cache` | lake / `lake-data` | D3 (vectors of note text) | Not backed up (cache) | [built] |
| S-11 | Audit chain | JSONL day files, hash-chained | all writers / `audit-data` | D1, PS, ST | Nightly + offline; never deleted by the box | [built] |
| S-12 | Object store | Filesystem object store `FsStore` (replaces MinIO, BD-09) | orchestrator, console / `objects` | D1–D4 by prefix | Nightly for `outputs/`, `reviews/` | FsStore [built] (tests/dev); production object store on FsStore and MinIO removal from `deploy/docker-compose.yml` [H] |
| S-13 | Rulesets repository | git repository | criteria-compiler / `rulesets-data` | D0, D1 | Nightly + vendor origin | [built] |
| S-14 | Criterion library | SQLite | criteria-compiler | D0, D1 | Nightly | [built] |
| S-15 | Recall ledger | Tables in S-27 (PostgreSQL in deployment; SQLite in unit tests, same SQL via `SqlBackend`) | orchestrator / `workflow-pg` | D3 | With S-27 | [built] |
| S-16 | Trace store | SQLite | tracestore | D3 (redacted model traces) | Not backed up; 90 days | [built] |
| S-17 | Front-door tokens and requests | Tables in S-27 (PostgreSQL in deployment; SQLite in tests) | frontdoor_mcp / `workflow-pg` | D1, ST | With S-27 | [built] (not exposed in the pilot) |
| S-18 | Configuration | `.env`, `settings.yaml`, site mapping YAML, site rule book | all / `config` | D1 | Nightly + git | [built] (rule book [H]) |
| S-19 | Secrets | site HMAC key, AES key, Ed25519 vendor public key, TLS keys | `tb-secrets` | D4-equivalent (keys) | Split shares, offline (TB-DS-03 §7) | [built] keys; split-share custody [H] |
| S-20 | PHI pass store | SQLite + files | phi-pass / `lake-data/scrub/` | D3 (scrubbed), D4 (span offsets to originals) | Nightly | [H] (rules layer S1) |
| S-21 | TOTP secrets and recovery codes | SQLite columns in S-05 | console | ST (secret) | Nightly, encrypted | [H] |
| S-22 | Proposal store (EDC pre-fill, AE suggestions) | SQLite | prefill-engine, conduct-service | D3, D4 (`record_ref`) | Nightly | [L] |
| S-23 | rc-bridge store | SQLite | rc-bridge | D1, D4 (`record_ref`) | Nightly | [S3] read connector; [L] writes |
| S-24 | Consortium store | SQLite + envelope files | fed-agent | D1, D2, PS (CLK) | Nightly | [L] |
| S-25 | EDC-lite data | FHIR QuestionnaireResponse in the FHIR store in use: HAPI (or Medplum after the ADR-14 spike, L) | fhir-store | D3/D4 per study | Nightly | [L] (TB-DS-00 §2) |
| S-26 | OMOP export | DuckDB / CSV | omop-export | D2 or D3 per profile | Per export | [L] |
| S-27 | Workflow DB: durable steps, transactional outbox, recall ledger (S-15), front-door tables (S-17) | PostgreSQL 16 `trialbox_wf` (`services/orchestrator/db_pg.py`) | workflow-db / `workflow-pg` | D1, D3, ST | Nightly `pg_dump`, encrypted | [built] |
| S-28 | Orchestrator study store | SQLite (`orch-data/studies.db`) | orchestrator / `orch-data` | D1, D3, D4 (`screening_no` link), ST | Nightly | [build steps 2–3] tables of §4.11; the console edits them only through the orchestrator API, as it does for jobs; the night jobs (N1/N2 mail, SCREEN, REDCap read) read them in place |

## 4. Tables and fields

### 4.1 S-01 Orchestrator job DB (`services/orchestrator/db.py`) [built]

#### `jobs`

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| jobs | job_id | TEXT | PK | no | D1 | — | R-OPS† | Source: ULID generated at intake |
| jobs | type | TEXT | — | no | D1 | — | R-OPS† | Source: mail subject cmd / console. FEAS, SCREEN, COHORT, NAV, APPROVE, STATUS, CANCEL, SUBMIT, FEEDBACK, CONSENT, RELEASE, CASE, REVIEW, RETENTION, MICROBATCH … |
| jobs | state | TEXT | — | no | D1 | — | R-OPS† | Source: orchestrator. queued, running, waiting, done, failed |
| jobs | ruleset | TEXT | FK → S-13 ruleset | yes | D0 | — | R-OPS† | Source: request |
| jobs | ruleset_version | TEXT | — | yes | D0 | — | R-OPS† | Source: approved manifest |
| jobs | requested_by | TEXT | — | no | D1 | ST | R-OPS† | Source: sender address or console username |
| jobs | received_at | TEXT | — | no | D1 | — | R-OPS† | Source: intake time (UTC). Fixes `run_date` (D-82) |
| jobs | updated_at | TEXT | — | yes | D1 | — | R-OPS† | Source: orchestrator |
| jobs | message_id | TEXT | — | yes | D1 | — | R-OPS† | Source: mail Message-ID |
| jobs | parent_job_id | TEXT | FK → S-01 jobs.job_id | yes | D1 | — | R-OPS† | Source: orchestrator |
| jobs | queued | INTEGER | — | no | D1 | — | R-OPS† | Source: orchestrator. 0/1 |
| jobs | cancel | INTEGER | — | no | D1 | — | R-OPS† | Source: CANCEL command. 0/1 |
| jobs | data | TEXT (JSON) | — | no | **D3** | PS | R-OPS† | Source: job parameters and step results. May contain pids and counts; never chart numbers (BD-04) |

† R-OPS; a job referenced by the candidate registry is kept for R-GCP (the study's GCP retention, N-03).

#### `mails`

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mails | message_id | TEXT | PK | no | D1 | — | R-OPS | outgoing Message-ID |
| mails | job_id | TEXT | FK → S-01 jobs.job_id | — | D1 | — | R-OPS |  |
| mails | kind | TEXT | — | — | D1 | — | R-OPS | result, review, error, status |
| mails | subject | TEXT | — | — | D1 | — | R-OPS | outcome-first subject (D-88/D-99); contains study code, never patient data |
| mails | sent_at | TEXT | — | — | D1 | — | R-OPS |  |

Retention R-OPS.

#### `pool` (screening candidate pool per ruleset)

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pool | ruleset | TEXT | PK | no | D0 | — | while the ruleset is active, then R-GCP |  |
| pool | pid | TEXT | PK | no | D3 | PS | while the ruleset is active, then R-GCP |  |
| pool | version | TEXT | — | — | D0 | — | while the ruleset is active, then R-GCP | ruleset version evaluated |
| pool | tier | TEXT | — | — | D3 | — | while the ruleset is active, then R-GCP | high, review, excluded tiers of the cascade |
| pool | next_appointment | TEXT | — | — | D3 | QI | while the ruleset is active, then R-GCP | local date-time |
| pool | practitioner_id | TEXT | — | — | D3 | ST | while the ruleset is active, then R-GCP | treating doctor, staff pseudonym or code |
| pool | department | TEXT | — | — | D3 | — | while the ruleset is active, then R-GCP |  |
| pool | verdicts | TEXT (JSON) | — | — | D3 | PS | while the ruleset is active, then R-GCP | per-criterion verdict, quote reference (document id + offsets), model, prompt version |
| pool | added_at, last_eval | TEXT | — | — | D3 | — | while the ruleset is active, then R-GCP |  |
| pool | job_id | TEXT | FK → S-01 jobs.job_id | — | D1 | — | while the ruleset is active, then R-GCP |  |

Retention: while the ruleset is active; then R-GCP with the screening log.

#### `feedback`

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| feedback | ruleset, pid | TEXT | PK (composite); ruleset: FK → S-13 ruleset; pid: FK → S-03 pid_map.pid | no | D0, D3 | PS | R-GCP (proposed, with the screening log) |  |
| feedback | outcome | TEXT | — | — | D3 | — | R-GCP (proposed, with the screening log) | CRC outcome code |
| feedback | reason_code | TEXT | — | — | D3 | — | R-GCP (proposed, with the screening log) |  |
| feedback | note | TEXT | — | — | **D3** | possible free text | R-GCP (proposed, with the screening log) | Free text from staff. Must not contain names; the console strips chart-number patterns with `phi_guard` [built] |
| feedback | job_id, received_at | TEXT | job_id: FK → S-01 jobs.job_id | — | D1 | — | R-GCP (proposed, with the screening log) |  |

#### `candidates` and `candidate_events` (screening log, ICH E6(R3) 3.16)

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| candidates | ruleset, pid | TEXT | PK (composite); ruleset: FK → S-13 ruleset; pid: FK → S-03 pid_map.pid | no | D0, D3 | PS | R-GCP |  |
| candidates | status | TEXT | — | — | D3 | — | R-GCP | Seven registry statuses (D-91): identified, pre-screened, contacted, consented, screen-failed, enrolled, withdrawn |
| candidates | reason | TEXT | — | — | D3 | — | R-GCP | coded reason, optional free text |
| candidates | updated_at / at | TEXT | — | — | D3 | — | R-GCP |  |
| candidates | updated_by / by | TEXT | — | — | D1 | ST | R-GCP | username |
| candidates | source | TEXT | — | — | D1 | — | R-GCP | screen, case, manual |
| candidates | source_job | TEXT | FK → S-01 jobs.job_id | — | D1 | — | R-GCP |  |
| candidates | tier | TEXT | — | — | D3 | — | R-GCP |  |
| candidates | screening_no | TEXT | — | — | D4 (identified side) | DI-linkable | R-GCP | [S2] per-study screening-log number assigned at the first Approach mark (BD-18, FR-STUDY-08); unique per study; also written by the CRC into the REDCap field `tb_screening_no`; shown only on on-prem pages after login and in exports kept inside the box, **never in mail, push or notices** (BD-18, TB-REV-006d D-03) |
| candidates | first_listed_at, site_screened_at | TEXT | — | — | D3 | — | R-GCP | [S2] ICH E6(R3) screening-log dates |
| candidates | consent_date, enrol_date, withdraw_date | TEXT | — | — | D3 | — | R-GCP | [S3] read from REDCap through the project link (FR-RC-16); never typed into TrialBox |
| candidates | reason_category | TEXT | — | — | D3 | — | R-GCP | [S2] declined · not approached (physician decision) · screen-failed on criterion · lost contact · other (see mapping below) |
| candidates | events | INTEGER | — | — | D1 | — | R-GCP | count |
| candidates | seq (events) | INTEGER | PK (candidate_events) | no | D1 | — | R-GCP |  |
| candidates | previous (events) | TEXT | — | — | D3 | — | R-GCP | previous status |

Retention R-GCP. The XLSX export resolves chart numbers only inside the box (built, `candidates.py`). The screening-log export columns (TB-TMPL-03, held in TB-TMPL-07) are: screening_no, pseudonym (or chart number after reveal, inside the box), date first listed, date screened, contact outcomes with dates, status, reason category and text, consent date, enrolment date, withdrawal date.

**Contact-outcome events and status mapping [S2] (TB-REV-006c C-06).** A contact outcome is an event in `candidate_events` with `source = manual`; it changes the status only as below. Consent, enrolment, screen-fail and withdrawal come from REDCap where the study is linked (FR-RC-16); without a link the coordinator records them on the row.

| Event (who) | Status before | Status after | reason_category |
| --- | --- | --- | --- |
| PI mark Approach (investigator) | identified / pre-screened | unchanged (mark is an event, D-104); `screening_no` assigned | — |
| PI mark Not suitable (investigator) | identified / pre-screened | unchanged; leaves the list | not approached (physician decision), with the per-study reason (FR-STUDY-09) |
| PI mark Ask treating doctor (investigator) | identified / pre-screened | unchanged; coordinator item created | — |
| Reached – visit booked (coordinator) | pre-screened | contacted | — |
| Reached – declined (coordinator) | pre-screened / contacted | screen-failed | declined |
| Not reached, retry date (coordinator) | any open | unchanged; retry date set | — |
| Lost contact (coordinator, after the study's retry limit) | pre-screened / contacted | screen-failed | lost contact |
| REDCap consent date present | contacted | consented | — |
| REDCap screen-fail field set | consented | screen-failed | screen-failed on criterion (REDCap choice mapped via the project link) |
| REDCap enrolment field set | consented | enrolled | — |
| REDCap withdrawal field set | enrolled | withdrawn | REDCap reason |

"Screen-failed" in the registry therefore always carries a reason category, so a declined patient is never reported as failing a criterion.

#### `submissions` (Taiwan NHI TWPAS, NAV/SUBMIT)

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| submissions | job_id | TEXT | PK | no | D1 | — | R-GCP; TW reimbursement ≥ 7 y (hospital rule) |  |
| submissions | ruleset, pid | TEXT | ruleset: FK → S-13 ruleset; pid: FK → S-03 pid_map.pid | — | D0, D3 | PS | R-GCP; TW reimbursement ≥ 7 y (hospital rule) |  |
| submissions | nav_job_id | TEXT | FK → S-01 jobs.job_id | — | D1 | — | R-GCP; TW reimbursement ≥ 7 y (hospital rule) |  |
| submissions | bundle_sha | TEXT | — | — | D1 | — | R-GCP; TW reimbursement ≥ 7 y (hospital rule) | sha256 of the submitted FHIR bundle (the bundle itself is D4, object store `submissions/`) |
| submissions | dry_run | INTEGER | — | — | D1 | — | R-GCP; TW reimbursement ≥ 7 y (hospital rule) |  |
| submissions | outcome | TEXT | — | — | D1 | — | R-GCP; TW reimbursement ≥ 7 y (hospital rule) |  |
| submissions | submitted_by, submitted_at | TEXT | — | — | D1 | ST | R-GCP; TW reimbursement ≥ 7 y (hospital rule) |  |

Retention R-GCP (reimbursement records: per hospital rule, at least 7 years in Taiwan; the hospital decides). Not used at the Japan site.

#### `cohort_tables`

Aggregates per site, disease, quarter and criterion: `site_id`, `disease`, `quarter`, `criterion_id`, `definition_version`, `criterion_label`, `n` (TEXT, may be "<10"), `n_contactable`, `received_from`, `job_id`. Class D2 (after suppression), PII —. Retention R-GCP.

#### `cohort_stored`, `cohort_stored_since`

D-648. `cohort_tables` holds each site's latest table; `cohort_stored` keeps every table as it was stored, one row per table, written in the transaction that stores it: `seq` (the order), `job_id`, `site_id`, `received_from`, `table_sha256`, `rows` (the table as JSON, the same cells as `cohort_tables`). A re-run of a merge reads the tables as they stood from it. `cohort_stored_since` holds one number, the last job from before the record (a box updated in place). Class D2 (after suppression), PII —. Retention R-GCP.

#### `trial_cache`

`nct_id`, `last_update`, `version`, `draft_zip_key`, `equivalence_pct`, `compiled_at`. Class D0. Retention R-OPS.

### 4.2 S-02 Mail gateway store (`services/mail_gateway/store.py`) [built]

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| intake | message_id | TEXT | PK | no | D1 | — | R-OPS |  |
| intake | sender | TEXT | — | — | D1 | ST | R-OPS | allowlisted staff address |
| intake | received_at | TEXT | — | — | D1 | — | R-OPS |  |
| intake | action | TEXT | — | — | D1 | — | R-OPS | job, reject, pending |
| intake | job_id | TEXT | FK → S-01 jobs.job_id | — | D1 | — | R-OPS |  |
| intake | reason | TEXT | — | — | D1 | — | R-OPS | rejection reason |
| sent | message_id | TEXT | PK | no | D1 | — | R-OPS |  |
| sent | job_id | TEXT | FK → S-01 jobs.job_id | — | D1 | — | R-OPS |  |
| sent | subject | TEXT | — | — | D1 | — | R-OPS |  |
| sent | recipients | TEXT | — | — | D1 | ST | R-OPS |  |
| sent | tag | TEXT | — | — | D1 | — | R-OPS |  |
| sent | sent_at | TEXT | — | — | D1 | — | R-OPS |  |

Message bodies and attachments are not stored here; outputs are in the object store `outputs/`. Retention R-OPS.

### 4.3 S-03 pid map (`services/adapter/pidmap.py`) [built]

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pid_map | pid | TEXT | PK | no | D3 | PS | while in any snapshot or registry (R-GCP) | `HMAC-SHA256(site_key, normalised MRN)`, 32 hex |
| pid_map | mrn | BLOB | — | — | **D4** | DI | while in any snapshot or registry (R-GCP) | AES-256-GCM ciphertext of the chart number |
| pid_map | first_seen, last_seen | TEXT | — | — | D3 | — | while in any snapshot or registry (R-GCP) |  |
| identity | pid | TEXT | PK | no | D3 | PS | while in any snapshot or registry (R-GCP) |  |
| identity | blob | BLOB | — | — | **D4** | DI | while in any snapshot or registry (R-GCP) | AES-GCM JSON of name and national ID; read only to build TWPAS bundles (Taiwan) |

File mode 0600 (built). Key: `tb-secrets/pidmap.key` (AES), site HMAC key `tb-secrets/site_hmac.key`. Retention: while the patient is in any snapshot or any registry within R-GCP; erasure through MPI status `erased` (§4.4) [H] erasure pipeline, TB-DS-03 §11.

### 4.4 S-04 Patient index as an alias table (`services/adapter/pidmap.py`, schema `pidmap`) [built]

D-370, D-381 (T-659b): the retired data platform's master patient index (`mpi_person`, `mpi_identifier`,
`mpi_merge`, a random `mpi_id` under `K_pid`) is gone with `services/dataplat`. The pid stays HMAC(site key, chart
number); a chart-number merge adds one append-only row.

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pid_alias | old_pid | TEXT | PK | no | D3 | PS | as S-03 | the pid of the chart number merged away |
| pid_alias | pid | TEXT | — | no | D3 | PS | as S-03 | the surviving pid |
| pid_alias | reason, ticket, merged_at | TEXT | — | no | D3 | — | as S-03 | `adapter pid-merge`; never changed or removed |

### 4.5 S-05 Console accounts (`services/console/auth.py`) [built; 2FA H]

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| users | username | TEXT | PK | no | D1 | ST | R-OPS after disabling | lower-case `[a-z0-9._-]` |
| users | role | TEXT | — | — | D1 | — | R-OPS after disabling | `admin`, `coordinator`, `investigator`, `viewer`, `cro`; `auditor` [H] (BD-03) |
| users | pw_hash | TEXT | — | — | D1 | ST (secret) | R-OPS after disabling | scrypt N=2^14, r=8, p=1, 16-byte salt |
| users | mailbox | TEXT | — | — | D1 | ST | R-OPS after disabling | staff e-mail |
| users | created | TEXT | — | — | D1 | — | R-OPS after disabling |  |
| users | disabled | INTEGER | — | — | D1 | — | R-OPS after disabling |  |
| users | affiliation | TEXT | — | — | D1 | ST | R-OPS after disabling | D-104 (hospital, SMO company, CRO) |
| users | studies | TEXT | — | — | D1 | — | R-OPS after disabling | comma list of ruleset IDs; null = hospital-wide (legacy) |
| users | expires | TEXT | — | — | D1 | — | R-OPS after disabling | account end date (SMO/CRO) |
| users | totp_secret | BLOB | — | — | D1 | ST (secret) | R-OPS after disabling | AES-GCM encrypted [H] |
| users | totp_enrolled_at | TEXT | — | — | D1 | — | R-OPS after disabling | [H] |
| users | recovery_hashes | TEXT | — | — | D1 | ST (secret) | R-OPS after disabling | scrypt hashes of 10 one-time codes [H] |
| users | last_login | TEXT | — | — | D1 | — | R-OPS after disabling | for access review (FR-AUTH-09) [H] |
| sessions | token_sha | TEXT | PK | no | D1 | — | until expiry | sha256 of the session cookie |
| sessions | username | TEXT | FK → S-05 users.username | — | D1 | ST | until expiry |  |
| sessions | csrf | TEXT | — | — | D1 | — | until expiry |  |
| sessions | created, last_seen | TEXT | — | — | D1 | — | until expiry | timeout 30 min idle, 8 h absolute (N-05) |
| sessions | lang | TEXT | — | — | D1 | — | until expiry | ja, zh-TW, en |
| login_failures | username, at | TEXT | username: FK → S-05 users.username | — | D1 | ST | 90 days | lockout 5 failures → 15 min (N-06) |

Retention: accounts R-OPS after disabling; sessions deleted at expiry; login failures 90 days.

### 4.6 S-06 Console site store (`services/console/sitestore.py`) [built]

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| site_profile | ruleset | TEXT | PK | no | D0 | — | R-GCP |  |
| site_profile | body | TEXT (JSON) | — | — | D1 | — | R-GCP | site study profile: competing trials, screen-fail rate assumption, visit schedule |
| site_profile | entered_by, entered_at | TEXT | — | — | D1 | ST | R-GCP |  |
| pi_marks | ruleset, pid | TEXT | ruleset: FK → S-13 ruleset; pid: FK → S-03 pid_map.pid | — | D0, D3 | PS | R-GCP |  |
| pi_marks | mark | TEXT | — | — | D3 | — | R-GCP | built values `approach`, `need_info`, `not_suitable` (registry events, never statuses, D-104); [S2] add `not_now` (with `recheck_on`, FR-SCR-07); [L] add `ask_treating` (FR-SCR-07b) |
| pi_marks | recheck_on | TEXT | — | — | D3 | — | R-GCP | [S2] date for `not_now` |
| pi_marks | reason, note | TEXT | — | — | D3 | possible free text | R-GCP |  |
| pi_marks | by, at | TEXT | — | — | D1 | ST | R-GCP |  |
| pi_marks | job_id | TEXT | FK → S-01 jobs.job_id | — | D1 | — | R-GCP |  |
| weekly_seen | ruleset, pid | TEXT | PK (composite); ruleset: FK → S-13 ruleset; pid: FK → S-03 pid_map.pid | no | D3 | PS | R-GCP | first time a patient appeared on a weekly list |
| weekly_seen | first_job, first_at | TEXT | first_job: FK → S-01 jobs.job_id | — | D3 | — | R-GCP |  |

Retention R-GCP.

#### 4.6.1 Study tables: moved to §4.11

The study set-up, team, ethics, REDCap link, notification and reconciliation tables are in the orchestrator study store S-28, §4.11 (TB-REV-006f F6-14).

### 4.7 S-11 Audit chain (`libs/tb_common/audit.py`) [built]

One JSON object per line in `audit/YYYY-MM-DD.jsonl`; `hash = sha256(prev_hash + canonical_json(line_without_hash))`, genesis = 64 zeros; writers serialise through `flock`.

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| audit line | ts | string (ISO 8601, local zone) | — | — | D1 | — | R-AUD (10 years) |  |
| audit line | event | string | — | — | D1 | — | R-AUD (10 years) | e.g. `job.state`, `output`, `reveal`, `login`, `account.change`, `mark`, `release`, `config.change`, `update.apply` |
| audit line | job_id | string | FK → S-01 jobs.job_id | — | D1 | — | R-AUD (10 years) |  |
| audit line | ruleset, ruleset_version | string | ruleset: FK → S-13 ruleset | — | D0 | — | R-AUD (10 years) |  |
| audit line | model, prompt_version | string | — | — | D1 | — | R-AUD (10 years) |  |
| audit line | snapshot | string | — | — | D1 | — | R-AUD (10 years) |  |
| audit line | actor | string | — | — | D1 | ST | R-AUD (10 years) | username, service name or sender |
| audit line | input_sha, output_sha | string | — | — | D1 | — | R-AUD (10 years) |  |
| audit line | recipients | array | — | — | D1 | ST | R-AUD (10 years) |  |
| audit line | detail | object | — | — | D1/D3 | PS | R-AUD (10 years) | pids allowed; chart numbers, names and note text **not allowed** (FR-AUD-02) |
| audit line | prev_hash, hash | string | — | — | D1 | — | R-AUD (10 years) |  |

Target additions: `chain.head` and `chain.countersign` events (consortium, [L]); `prefill.accept|edit|reject` with proposal id ([L]); `phi.review` ([H]). Retention R-AUD (10 years).

### 4.8 S-12 Object store layout [built]

| Prefix | Content | Class | Retention |
| --- | --- | --- | --- |
| `attachments/<job_id>/` | inbound mail attachments (protocols, criteria) | D0–D1 (D4 possible if a sender attaches a chart; `phi_guard` flags) | R-SET `attachments_days` |
| `outputs/<job_id>/` | reports (PDF, XLSX, HTML), candidate lists | D1 (suppressed aggregates) or D3 (lists with pids) | R-SET `outputs_days`; screening outputs R-GCP |
| `reviews/<ruleset>/<round>/` | review packages, approval records | D0–D1 | R-GCP |
| `consent/<ruleset>/<version>/` | consent explainer drafts, and committee-approved uploaded files with their SHA-256 and file version (BD-15) | D0–D1 | R-GCP |
| `submissions/<job_id>/` | TWPAS FHIR bundles | D4 | hospital rule |
| `ctgov/` | ClinicalTrials.gov cache | D0 | R-OPS |
| `support/<ts>.tar` | diagnostics bundles (no PHI, TB-DS-04 §10.5) | D1 | 30 days |

### 4.9 Other built stores (summary)

| Store | Tables | Class | Notes |
| --- | --- | --- | --- |
| S-14 Criterion library | `criterion_library`, `_text`, `_valueset`, `_lexicon_key`, `_usage`, `_meta` | D0/D1 | Reusable compiled criteria |
| S-15 Recall ledger | `recall_cell`, `recall_observation`, `recall_sequence_state`, `recall_run_cell`, `recall_registration`, `recall_known_positive` | D3 | Calibration of reach and accept rates; pids only |
| S-16 Trace store | `traces`, `access_log` | D3 | Redacted model prompts/outputs; 90 days |
| S-17 Front door | `relay_token`, `conversation_request` | D1 | Not exposed at pilot sites |

### 4.10 Target stores

#### S-20 PHI pass store [H; the rules layer used by `e2e_simple` is S1]

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| scrub_doc | did | TEXT | PK | no | D3 | — | R-SNAP | DocumentReference id |
| scrub_doc | pid | TEXT | FK → S-03 pid_map.pid | — | D3 | PS | R-SNAP |  |
| scrub_doc | source_sha | TEXT | — | — | D1 | — | R-SNAP | sha256 of original text |
| scrub_doc | scrubbed_key | TEXT | — | — | D1 | — | R-SNAP | object-store key of scrubbed text (D3) |
| scrub_doc | detector_versions | TEXT (JSON) | — | — | D1 | — | R-SNAP | rules, NER, LLM tagger versions (FR-DEID-09) |
| scrub_doc | scrubbed_at | TEXT | — | — | D1 | — | R-SNAP |  |
| scrub_span | did, span_no | TEXT, INTEGER | PK (composite); did: FK → FHIR DocumentReference | no | D3 | — | R-SNAP |  |
| scrub_span | start, end | INTEGER | — | — | **D4** | — | R-SNAP | offsets into the original; together with the original they reveal the identifier |
| scrub_span | category | TEXT | — | — | D1 | — | R-SNAP | person, id, phone, address, hospital, age, date, job, insurer_no, care_insurance_no, national_id … |
| scrub_span | detectors | TEXT | — | — | D1 | — | R-SNAP | which detector(s) fired |
| scrub_span | surrogate | TEXT | — | — | D3 | — | R-SNAP | replacement text; consistent per patient and entity |
| surrogate_map | pid, category, entity_hmac | TEXT | PK (composite); pid: FK → S-03 pid_map.pid | no | D3 | PS | R-SNAP | keyed hash of the original entity |
| surrogate_map | surrogate | TEXT | — | — | D3 | — | R-SNAP |  |
| review_sample | sample_id, did, reviewer, verdict, missed_spans, at | — | did: FK → FHIR DocumentReference | — | D3/D1 | ST | R-AUD | monthly 50-note review (FR-DEID-10) |

Retention: follows the snapshot of the note (R-SNAP); review samples R-AUD.

#### S-22 Proposal store [L]

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| proposal | proposal_id | TEXT (ULID) | PK | no | D1 | — | R-GCP |  |
| proposal | kind | TEXT | — | — | D1 | — | R-GCP | prefill, ae_suggestion, conmed_flag, visit_window |
| proposal | record_ref | TEXT | FK → REDCap record (external) | — | **D4** | DI-linkable | R-GCP | `redcap_project_id:record_id:event:instance` (written with `:` separators), or EDC-lite id (L) |
| proposal | pid | TEXT | FK → S-03 pid_map.pid | — | D3 | PS | R-GCP |  |
| proposal | instrument, field_name | TEXT | — | — | D1 | — | R-GCP |  |
| proposal | proposed_value | TEXT | — | — | D3 | — | R-GCP |  |
| proposal | final_value | TEXT | — | — | D3 | — | R-GCP |  |
| proposal | decision | TEXT | — | — | D3 | — | R-GCP | accepted, edited, rejected, dismissed, expired |
| proposal | decided_by, decided_at | TEXT | — | — | D1 | ST | R-GCP |  |
| proposal | quote_did, quote_start, quote_end | TEXT, INTEGER | quote_did: FK → FHIR DocumentReference | — | D3 | — | R-GCP | evidence location |
| proposal | source_kind | TEXT | — | — | D1 | — | R-GCP | rule, model |
| proposal | model, prompt_version | TEXT | — | — | D1 | — | R-GCP |  |
| proposal | validator_result | TEXT (JSON) | — | — | D1 | — | R-GCP |  |
| proposal | ctcae_term, ctcae_grade | TEXT | — | — | D3 | — | R-GCP | AE suggestions (CTCAE v5.0) |
| proposal | dismiss_reason | TEXT | — | — | D3 | — | R-GCP | AE dismissal by investigator only (BD-08) |

Retention R-GCP.

#### S-23 rc-bridge store [S3 read; L write]

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rc_project | project_id, redcap_url, redcap_version, last_logged_event | TEXT | — | — | D1 | — | R-OPS (proposed) |  |
| rc_project | read_token_ref | TEXT | — | — | D1 | — | R-OPS (proposed) | reference to the secret store entry (project-level read token, BD-05); token itself in `tb-secrets` |
| rc_project | det_secret_ref | TEXT | — | — | D1 | — | R-OPS (proposed) | DET shared secret reference |
| rc_dictionary | project_id, fetched_at, sha, body | TEXT | project_id: FK → rc_project.project_id | — | D0/D1 | — | R-OPS (proposed) | cached data dictionary |
| rc_link | record_ref, screening_no, pid, linked_at, link_mode | TEXT | record_ref: FK → REDCap record (external); pid: FK → S-03 pid_map.pid | — | D4 / D3 | DI-linkable / PS | R-GCP (proposed) | [S3] created by reading the `tb_screening_no` field (or MRN where the study chose that mode); no person types it (BD-18) |
| rc_user_map | redcap_username, tb_username, linked_at | TEXT | — | — | D1 | ST | R-OPS (proposed) | [L] |
| rc_det_seen | project_id, record, instrument, event, bucket | TEXT | project_id: FK → rc_project.project_id | — | D1 | — | R-OPS (proposed) | DET de-duplication |

#### S-24 Consortium store [L]

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fed_msg | msg_id, type, from_site, to_site, created_at, expires_at, payload_sha256, status | TEXT | — | — | D1 | — | R-OPS (proposed) | replay protection |
| fed_query | query_id, ruleset, requester, approvals (per-site PI), steering_ref, purpose | TEXT | ruleset: FK → S-13 ruleset | — | D1 | ST | R-GCP (proposed) | governance record (FR-FED-07) |
| fed_funnel | query_id, site, step, n, suppressed | TEXT | query_id: FK → fed_query.query_id | — | D2 | — | R-GCP (proposed) | k=10 (N-01) |
| fed_clk | query_id, site, clk (base64), candidate_ref | TEXT | query_id: FK → fed_query.query_id | — | PS | PS | 90 days after the query closes | encodings only; deleted 90 days after the query closes |
| chain_head | site, day, head_hash, countersign | TEXT | — | — | D1 | — | R-AUD |  |

### 4.11 S-28 Orchestrator study store (`orch-data/studies.db`) [S2–S3; ethics record H]

This section was §4.6.1 (nested under S-06) until v0.4; the tables moved from S-06 to S-28 by TB-REV-006f F6-14 (TB-REV-006c C-02, C-05, C-06, C-07, C-10, C-17, C-18).

Built in steps 2 and 3 (`20-build-map.md`): `study_settings`, `study_team`, `rc_project_link`, `notify_settings` (delivery day and time only), `notify_log`, the screening-number and contact-outcome fields. `ethics_record` is created but only consulted when `ethics_gate` is on. `recon_decision` and `import_meta` are L.

| Table | Field | Type | Key | Null | Class | PII | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| study_settings | ruleset (study) | TEXT | PK | no | D0 | — | R-GCP | one row per study, edited on S21 (FR-STUDY-07); supersedes nothing: `site_profile` stays and S21 shows it as its "Forecast" section |
| study_settings | study_type, cohort_kind, consent_scope | TEXT | — | — | D1 | — | R-GCP | trial / registry / observational; enrolled / dynamic (FR-STUDY-02); opt-in / opt-out / waiver |
| study_settings | protocol_version, sponsor_flag | TEXT, BOOL | — | — | D1 | — | R-GCP | protocol version pinned to the ruleset; industry-sponsored flag (FR-CON-10) |
| study_settings | screening_no_format, screening_no_next | TEXT, INTEGER | — | — | D1 | — | R-GCP | e.g. `AD01-{0000}`, or the site's own sequence starting number (BD-18) |
| study_settings | not_suitable_reasons | TEXT (JSON) | — | — | D1 | — | R-GCP | per-study reason list (FR-STUDY-09), seeded by study type |
| study_settings | introduce_rule | TEXT | — | — | D1 | — | R-GCP | who may introduce the study (BD-19): `treating_physician` or `treating_or_investigator_after_agreement` (主治医の了承 / 主治醫師同意), recorded as the approved protocol states; default unset until the coordinator records it and the investigator confirms (FR-SCR-07b) |
| study_settings | explainer_on, immediate_notice_on | BOOL | — | — | D1 | — | R-GCP | FR-CON-07; FR-NOTIF-03 in-hours notice (default off) |
| study_settings | entered_by/at, confirmed_by/at | TEXT | — | — | D1 | ST | R-GCP | coordinator enters; investigator confirms approval record and team |
| study_team | ruleset, username, role_in_study, expires_at | TEXT | ruleset: FK → S-13 ruleset; username: FK → S-05 users.username | — | D1 | ST | R-GCP | investigators, coordinators, SMO expiry; `office` flag lives on the account (FR-STUDY-10) |
| study_physicians | ruleset, practitioner_ref, is_investigator | TEXT, BOOL | ruleset: FK → S-13 ruleset; practitioner_ref: FK → FHIR Practitioner | — | D1 | ST | R-GCP (proposed) | treating-physician list for list grouping (FR-UI-15) |
| ethics_record | ruleset, record_no, committee, approval_no, approval_date, expires_at, icf_version, covers_identified_screening | TEXT, BOOL | ruleset: FK → S-13 ruleset | — | D1 | — | R-GCP | FR-CON-06, FR-STUDY-06 gate |
| ethics_record | explainer_file_ref, explainer_sha256, file_version, letter_date | TEXT | — | — | D1 | — | R-GCP | uploaded committee-approved file (object store `consent/`); hash computed by the system (BD-15 (b), (c)) |
| ethics_record | sponsor_approved_at, sponsor_contact | TEXT | — | — | D1 | ST | R-GCP | FR-CON-10 |
| ethics_record | entered_by/at, confirmed_by/at, live_from, withdrawn_at, withdraw_reason | TEXT | — | — | D1 | ST | R-GCP | automatic go-live / withdrawal (BD-15 (e)) |
| rc_project_link | ruleset, project_id, dag, link_mode, link_field, consent_field, consent_event, enrol_field, screenfail_field, screenfail_choice_map, withdraw_field, subject_no_field | TEXT | ruleset: FK → S-13 ruleset; project_id: FK → rc_project.project_id | — | D1 | — | R-GCP (proposed) | per-study REDCap field map (FR-RC-16, TB-DS-08 ICD-04 "Project link"); link_mode = `tb_screening_no` (default) or `mrn` |
| notify_settings | username, channel, deliver_mode, deliver_time, clinic_days, clinic_days_source, clinic_days_confirmed_at, on_duty_date, quiet_from, quiet_to, snooze_until, deputy | TEXT | username: FK → S-05 users.username | — | D1 | ST | while the account exists (proposed) | FR-NOTIF-04; deliver_mode = clinic_day (default where appointments exist) / monday; `clinic_days` (weekday list) proposed from the appointment source (practitioner schedule, FR-ING-03b, `clinic_days_source` = appointments) and confirmed once by the PI, or typed by the PI (`= manual`) only where no source exists (TB-REV-006d D-10); `on_duty_date` = the date the coordinator's S8 "I'm on duty today" toggle was last on (default on), used for FR-UI-18 and FR-NOTIF-03 (D-16) |
| notify_log | id, username, kind, items, sent_at, channel, read_at | TEXT | username: FK → S-05 users.username | — | D1 | ST | 1 year | counts only, no patient content; feeds FR-NOTIF-05 de-duplication and the FR-NOTIF-08 budget page |
| recon_decision | ruleset, pid, variable, emr_value, registry_value, decision, by, at | TEXT | ruleset: FK → S-13 ruleset; pid: FK → S-03 pid_map.pid | — | D3 | PS | R-GCP | FR-STUDY-03: EMR right / Registry right / Leave |
| import_meta | import_id, owner, source_kind, consent_scope, mapping_ref, rows, imported_by/at, purpose | TEXT | — | — | D1 | ST | R-GCP | FR-ING-19/21 personal-database and CRC-log imports (FR-SCR-13); identifiers matched to pid, then dropped |

Retention: R-GCP for `ethics_record`, `study_settings`, `study_team`, `recon_decision`; `notify_log` 1 year; `import_meta` R-GCP.

### 4.12 Keys and relationships

Generated from the Key column of every field table above. The built schemas declare `REFERENCES` only in S-14 (criterion library, enforced with `PRAGMA foreign_keys = ON`) ; every other reference below is logical, kept by the code, not by the database; references to another store or to FHIR are by identifier only and are never joined in SQL across containers. Every `pid` reference resolves through S-03 and, after merges, through `pid_alias` (S-04).

| Store | Table | Reference |
| --- | --- | --- |
| S-01 | jobs | FK → S-13 ruleset |
| S-01 | jobs | FK → S-01 jobs.job_id |
| S-01 | mails | FK → S-01 jobs.job_id |
| S-01 | pool | FK → S-01 jobs.job_id |
| S-01 | feedback | ruleset: FK → S-13 ruleset |
| S-01 | feedback | pid: FK → S-03 pid_map.pid |
| S-01 | feedback | job_id: FK → S-01 jobs.job_id |
| S-01 | candidates | ruleset: FK → S-13 ruleset |
| S-01 | candidates | pid: FK → S-03 pid_map.pid |
| S-01 | candidates | FK → S-01 jobs.job_id |
| S-01 | submissions | ruleset: FK → S-13 ruleset |
| S-01 | submissions | pid: FK → S-03 pid_map.pid |
| S-01 | submissions | FK → S-01 jobs.job_id |
| S-02 | intake | FK → S-01 jobs.job_id |
| S-02 | sent | FK → S-01 jobs.job_id |
| S-05 | sessions | FK → S-05 users.username |
| S-05 | login_failures | username: FK → S-05 users.username |
| S-06 | pi_marks | ruleset: FK → S-13 ruleset |
| S-06 | pi_marks | pid: FK → S-03 pid_map.pid |
| S-06 | pi_marks | FK → S-01 jobs.job_id |
| S-06 | weekly_seen | ruleset: FK → S-13 ruleset |
| S-06 | weekly_seen | pid: FK → S-03 pid_map.pid |
| S-06 | weekly_seen | first_job: FK → S-01 jobs.job_id |
| S-28 | study_team | ruleset: FK → S-13 ruleset |
| S-28 | study_team | username: FK → S-05 users.username |
| S-28 | study_physicians | ruleset: FK → S-13 ruleset |
| S-28 | study_physicians | practitioner_ref: FK → FHIR Practitioner |
| S-28 | ethics_record | ruleset: FK → S-13 ruleset |
| S-28 | rc_project_link | ruleset: FK → S-13 ruleset |
| S-28 | rc_project_link | project_id: FK → rc_project.project_id |
| S-28 | notify_settings | username: FK → S-05 users.username |
| S-28 | notify_log | username: FK → S-05 users.username |
| S-28 | recon_decision | ruleset: FK → S-13 ruleset |
| S-28 | recon_decision | pid: FK → S-03 pid_map.pid |
| S-11 | audit line | FK → S-01 jobs.job_id |
| S-11 | audit line | ruleset: FK → S-13 ruleset |
| S-20 | scrub_doc | FK → S-03 pid_map.pid |
| S-20 | scrub_span | did: FK → FHIR DocumentReference |
| S-20 | surrogate_map | pid: FK → S-03 pid_map.pid |
| S-20 | review_sample | did: FK → FHIR DocumentReference |
| S-22 | proposal | FK → REDCap record (external) |
| S-22 | proposal | FK → S-03 pid_map.pid |
| S-22 | proposal | quote_did: FK → FHIR DocumentReference |
| S-23 | rc_dictionary | project_id: FK → rc_project.project_id |
| S-23 | rc_link | record_ref: FK → REDCap record (external) |
| S-23 | rc_link | pid: FK → S-03 pid_map.pid |
| S-23 | rc_det_seen | project_id: FK → rc_project.project_id |
| S-24 | fed_query | ruleset: FK → S-13 ruleset |
| S-24 | fed_funnel | query_id: FK → fed_query.query_id |
| S-24 | fed_clk | query_id: FK → fed_query.query_id |

## 5. FHIR resources and profiles

FHIR R4 4.0.1. Japanese site profiles: JP Core 1.2.0 (BD-12). Taiwan: TW Core as pinned in `services/adapter/mapping/tw_core/`. "MS" = elements TrialBox relies on (must support for the reader and the mapping).

| Resource | JP profile | TW profile | MS elements | Lake table | Status |
| --- | --- | --- | --- | --- | --- |
| Patient | JP_Patient | TWCorePatient | identifier (system `https://trialbox.local/fhir/sid/pid`, value = pid), gender, birthDate, deceased[x] | `patient` | [built] TW; JP [H] |
| Practitioner | JP_Practitioner | TWCorePractitioner | identifier (staff id) | `practitioner` | [built] |
| Encounter | JP_Encounter | TWCoreEncounter | identifier, class, period.start, serviceType / department extension, participant.individual | `encounter` | [built] |
| Appointment | — | — | start, status, participant (practitioner), serviceType | `appointment` | [built] |
| Condition | JP_Condition | TWCoreCondition | code.coding (ICD-10, 標準病名 code, ICD-10-CM), clinicalStatus, verificationStatus (`provisional` for 「疑い」, `confirmed`), onsetDateTime, recordedDate, encounter, extension `tb-insurance-only` (保険病名 flag, JP) [H], extension `tb-main-diagnosis` (主病名) [H] | `condition` | [built]; JP extensions [H] |
| Observation | JP_Observation_LabResult, JP_Observation_VitalSigns | TWCoreObservationLaboratoryResult, vital signs | code.coding (JLAC10/11, local code, LOINC), category, effective[x], valueQuantity (value, unit, code UCUM), valueCodeableConcept, interpretation | `observation` (value_num, unit, value_code, local_code) | [built] |
| MedicationRequest | JP_MedicationRequest | TWCoreMedicationRequest | medicationCodeableConcept (YJ, HOT, NHI drug code, ATC), authoredOn, dosageInstruction (text, timing bounds), status | `medication` | [built] TW; JP [H] |
| MedicationAdministration | JP_MedicationAdministration | — | medication, effective[x] | `medication` | [H] (injections from SS-MIX2) |
| Procedure | JP_Procedure | TWCoreProcedure | code, performed[x] | `procedure` | [built] |
| DiagnosticReport | JP_DiagnosticReport_Radiology | TWCoreDiagnosticReport | code, effective[x], conclusion, presentedForm | `report` | [built] |
| DocumentReference | JP_DocumentReference | TWCoreDocumentReference | type, date, context.encounter, content.attachment (text or data, contentType) | `document`, `document_chunk` | [built] |
| Consent | JP_Consent | TWCoreConsent | status, scope (research), provision.type, dateTime; extension `contact_ok` | `consent` | [built] |
| Claim | — | TWCoreClaim | created, item.productOrService, extension NHI approval period | `claim` | [built] (Taiwan only) |
| Organization | JP_Organization | TWCoreOrganization | identifier (site id), name | — | [built] |
| Questionnaire / QuestionnaireResponse | SDC | SDC | item.linkId = REDCap `field_name`, item.type, answerOption, enableWhen | — | [L] EDC-lite |
| Provenance | — | — | target (accepted value), entity (source resource + offsets), agent (user, model id) | — | [L] |
| AuditEvent | — | — | Medplum built-in | — | [L] if Medplum |

Identifiers: pid system `https://trialbox.local/fhir/sid/pid` (built, `demo_his.yaml`). Chart numbers never appear in FHIR resources (D3 store).

## 6. Lake tables (DuckDB, one database per snapshot) [built]

From `services/lake/flatten.py` and `services/lake/store.py`. All D3. Retention R-SNAP.

| Table | Columns (type) |
| --- | --- |
| patient | pid VARCHAR, birth_date DATE, sex VARCHAR, deceased_date DATE |
| practitioner | practitioner_id VARCHAR, staff_id VARCHAR |
| encounter | eid VARCHAR, pid VARCHAR, start TIMESTAMP, dept VARCHAR, practitioner_id VARCHAR, class VARCHAR |
| appointment | aid VARCHAR, pid VARCHAR, start TIMESTAMP, practitioner_id VARCHAR, dept VARCHAR, status VARCHAR |
| condition | cid VARCHAR, pid VARCHAR, code VARCHAR, system VARCHAR, onset DATE, recorded DATE, status VARCHAR, eid VARCHAR |
| observation | oid VARCHAR, pid VARCHAR, code VARCHAR, system VARCHAR, effective TIMESTAMP, value_num DOUBLE, unit VARCHAR, value_code VARCHAR, category VARCHAR, local_code VARCHAR |
| medication | mid VARCHAR, pid VARCHAR, nhi_code VARCHAR, atc VARCHAR, authored DATE, start DATE, end DATE, status VARCHAR, name VARCHAR, dose VARCHAR |
| procedure | prid VARCHAR, pid VARCHAR, code VARCHAR, system VARCHAR, performed DATE |
| report | rid VARCHAR, pid VARCHAR, code VARCHAR, system VARCHAR, effective DATE, conclusion VARCHAR |
| document | did VARCHAR, pid VARCHAR, date TIMESTAMP, type VARCHAR, eid VARCHAR, text VARCHAR |
| document_chunk | did VARCHAR, chunk_no INTEGER, pid VARCHAR, date TIMESTAMP, type VARCHAR, text VARCHAR, tok VARCHAR, embedding FLOAT[1024], chunk_key VARCHAR |
| claim | kid VARCHAR, pid VARCHAR, created DATE, product VARCHAR, outcome VARCHAR, approval_start DATE, approval_end DATE |
| consent | consid VARCHAR, pid VARCHAR, status VARCHAR, contact_ok BOOLEAN, date DATE |
| lake_meta | snapshot VARCHAR, built_at TIMESTAMP |
| cache (embedding cache) | sha VARCHAR, model VARCHAR, vec FLOAT[1024], … |

Target changes for Japan [H]:

| Table | New column | Type | Reason |
| --- | --- | --- | --- |
| condition | verification | VARCHAR | 「疑い」 → `provisional` (TB-DS-10 §3, rule 2) |
| condition | insurance_only | BOOLEAN | 保険病名 rule (TB-DS-10 §3, rule 5) |
| condition | main_dx | BOOLEAN | 主病名 flag |
| condition | local_code, local_system | VARCHAR | 標準病名 code kept beside ICD-10 (FR-ING-09) |
| medication | yj_code, hot_code, ingredient | VARCHAR | Japanese drug codes (the `nhi_code` column stays for Taiwan) |
| observation | jlac_code | VARCHAR | JLAC10/11 code (until then held in `local_code`) |
| document | text_source | VARCHAR | original, scrubbed, ocr |

The `document.text` column holds **scrubbed** text once the PHI pass is live [H]; original text stays only in the identified-zone object store (FR-DEID-08).

## 7. Configuration items (S-18)

| File | Class | Owner | Change control |
| --- | --- | --- | --- |
| `.env` | D1 | hospital IT | TB-DS-12 configuration management (change type CC6, significance B; TB-DS-04 §9.3, TB-DS-12 §5.1) |
| `settings.yaml` (schema `settings.schema.json`) | D1 | hospital IT + Aimedics | services refuse to start on schema errors (built) |
| site mapping YAML (`mapping/<profile>/<site>.yaml`) | D1 | Aimedics + hospital IT | versioned; reviewed like a ruleset (change type CC6, significance B; TB-DS-04 §9.3, TB-DS-12 §5.1) |
| lookup CSVs (e.g. `lab_local_to_loinc.csv`) | D1 | Aimedics + laboratory | versioned with the mapping |
| site rule book (`rulebook/<site>.md`, ≤ 2,000 characters) [H] | D1 | site PI | versioned; shown to the model per task |
| `models/registry.yaml`, model manifests | D1 | Aimedics | model change control |
| rulesets (`rulesets/<ID>/manifest.yaml`, `ir/`, `valuesets/`, `cql/`, `sql/`, `tests/`) | D0/D1 | Approval by the study's `investigator`; the coordinator prepares and submits (SRS AM-01, FR-AUTH-13; TB-DS-00 BD-13, proposed; built code also lets admin and coordinator approve) | git tag per approval |

## 8. Data-subject requests and erasure

| Request | Handling | Status |
| --- | --- | --- |
| Access (開示 / 查詢) | Hospital handles from the EMR; TrialBox exports the registry rows and audit events for the pid on admin request | [H] |
| Opt-out of research use | Consent registry entry `contact_ok=false` or opt-out list → S0 excludes from all lists at next snapshot; existing list rows are struck | [built] S0; opt-out list import [H] |
| Erasure / correction | MPI status `erased`; pid removed from pool, weekly_seen and future snapshots; registry rows kept only where GCP requires, with the reason recorded; audit events kept (pseudonymous, legal obligation) | [H] |

## 9. Open items

| ID | Item |
| --- | --- |
| DD-01 | Closed 2026-11-07 against `trialbox/deploy/docker-compose.yml` at `a1e55fa`: volumes `orch-data`, `mail-data`, `tb-secrets`, `lake-data`, `audit-data`, `rulesets-data`, `traces-data` (S-16 at `/data/traces/traces.sqlite`, gateway container), `fhir-pg`, `minio-data` match; found a second PostgreSQL, `workflow-db` (`trialbox_wf`, volume `workflow-pg`), now S-27, holding S-15 and S-17; `console-data` (S-05, S-06) is defined only in `docker-compose.poc.yml`, so the production compose needs a console service [H]; `minio` is still in the production compose (S-12). |
| DD-02 | Taiwan reimbursement record retention for `submissions` to be set by CGMH. |
| DD-03 | Whether `feedback.note` and `pi_marks.note` free text should run through the PHI pass. Default: yes, rules layer only [H]. |
| DD-04 | Medplum (L, ADR-14 spike) would replace S-08 and parts of S-05; this dictionary must be revised then. |

## 10. References

| Ref | Document |
| --- | --- |
| [D1] | ISO/IEC 11179-3:2023 Metadata registries — registry metamodel (data element attributes used in §2.5) |
| [D2] | HL7 FHIR R4 (4.0.1); JP Core 1.2.0; TW Core as pinned in the repository (TB-DS-00 BD-12) |
| [D3] | ICH E6(R3) Good Clinical Practice, screening-log content (§4.1 `candidates`) |
| [D4] | 個人情報の保護に関する法律 (APPI) and Taiwan 個人資料保護法 (PDPA): data classes and erasure (§2.1, §8; detail TB-DS-03) |
| [D5] | TB-DS-00 (§4 retention N-02..N-04), TB-DS-01, TB-DS-02 §8.10–8.16, TB-DS-03, TB-DS-08, TB-DS-20 |
| [D6] | Repository `zandis/Auto-GPT`, `trialbox/` at `a1e55fa` (store code paths named in each §4 heading) |

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | 0.1 | 2026-11-07 | Claude for Aimedics | First draft, from code at `a1e55fa` and TB-DS-00/02/03. |
| 2 | 0.1a | 2026-11-07 | Claude for Aimedics | TB-REV-006b: S-12 wording (R2-20); S-25 on the FHIR store in use (R2-06); ruleset approval per AM-01/BD-13 (R2-02); DD-01 closed against the compose file; §2.1 suppressed aggregates are D1 as in the code and TB-DS-03 §2.1; S-27 workflow DB added, S-15/S-17 moved into it. |
| 3 | 0.2 | 2026-11-07 | Claude for Aimedics | TB-REV-006c: screening-log fields (`screening_no`, ICH E6(R3) dates, reason_category) and the contact-outcome → status mapping table (C-06); `pi_marks` values corrected to the built `approach` / `need_info` / `not_suitable`, plus `ask_treating`, `not_now` (C-10, C-13); new S-06 tables §4.6.1 for study set-up S21, team, treating physicians, ethics record with approved explainer file and sponsor approval, REDCap project link and field map, notification settings and log, reconciliation decisions, import metadata (C-02, C-05, C-07, C-17, C-18); `rc_link` keyed on screening_no (BD-18). |
| 4 | 0.3 | 2026-11-07 | Claude for Aimedics | TB-REV-006d: `screening_no` never in mail (D-03); `introduce_rule` values per BD-19 (D-04); `notify_settings` adds `clinic_days` with source and confirmation (D-10) and `on_duty_date` (D-16); EDC-lite tagged C (D-14). |
| 5 | 0.4 | 2026-11-07 | Claude for Aimedics | TB-REV-006f F6-14: the §4.6.1 tables move from the console site store S-06 to a new orchestrator study store S-28 (`orch-data/studies.db`); console edits via the orchestrator API; build-step note. Frozen as reference. |
| 6 | 0.5 | 2026-11-07 | Claude for Aimedics | TB-REV-006g Q-23, Q-24, S-02, S-06, S-08: one column set for every field table with Key, Null and Retention (§2.5); keys and relationships §4.12; S-28 promoted to §4.11 (pointer left at §4.6.1); inventory ordered (S-28 after S-27); malformed `record_ref` row repaired; tags S1–S5 / H / L replace M1 / M2 / C; References §10; Seq column; history table rejoined. |
| 7 | 0.6 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §R R-25..R-27: §4.12 relationship rows for the study tables filed under S-28; §6 cites TB-DS-10 §3 rules 2 and 5; DD-04 tag L; `jobs` retention as one footnote; Status as frozen build-stage reference. |
