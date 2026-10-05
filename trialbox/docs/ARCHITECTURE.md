# TrialBox architecture (as built)

TrialBox is one on-prem appliance driven by e-mail. It compiles eligibility rules (trial protocols, NHI
reimbursement rules, cohort definitions) into auditable, deterministic patient screens over the hospital's data:
- Email in, email out; nightly, weekly and quarterly batches.
- No UI, no accounts, no real-time hooks.

This document describes the code in this repository. `SPEC.md` is the requirement, `docs/DECISIONS.md` (D-nn) the
deviations and choices, and `docs/PROGRESS.md` the build log.

## 1. Services (docker compose project `trialbox`)

| Service | Code | Image | Port | Networks | State (volume) |
| --- | --- | --- | --- | --- | --- |
| mail-gateway | `services/mail_gateway` | trialbox-py | 8015 | trialbox-net, **trialbox-egress** | `mail-data` (intake/sent index), `audit-data` |
| orchestrator | `services/orchestrator` | trialbox-jvm | 8010 | trialbox-net, **trialbox-egress** | `orch-data` (SQLite jobs, pools, feedback, submissions, cohort tables, trial cache), `rulesets-data` (ro), `tb-secrets`, `audit-data` |
| criteria-compiler | `services/criteria_compiler` | trialbox-jvm | 8012 | trialbox-net, **trialbox-egress** | `rulesets-data` (git repository), `audit-data` |
| doc-parser | `services/doc_parser` | trialbox-py | 8011 | trialbox-net | — |
| adapter | `services/adapter` | trialbox-jvm | 8016 | trialbox-net | `lake-data` (NDJSON), `tb-secrets` (site key, pid map), `audit-data` |
| lake | `services/lake` | trialbox-py | 8013 | trialbox-net | `lake-data` (DuckDB per snapshot, parquet, embeddings cache) |
| embed-service | `services/embed_service` | trialbox-py | 8014 | trialbox-net | models (ro) |
| llm-service / llm-stub | vLLM (`gpu` profile) / `services/llm_stub` (`stub`) | vllm / trialbox-py | 8000 | trialbox-net | models (ro) |
| fhir-store + fhir-db | HAPI JPA 8.12 (CR) + Postgres 16 | pinned digests | 8080 | trialbox-net | `fhir-pg` |
| minio | object store (attachments, outputs, review packages, CT.gov cache) | pinned digest | 9000 | trialbox-net | `minio-data` |

`trialbox-net` is `internal: true`, so it has no route out. Only the three services on `trialbox-egress` can leave
the box, and the host's nftables table (`deploy/network.sh`, D-76) limits each of them to its allowlisted
destinations:
- mail-gateway → SMTP/IMAP;
- criteria-compiler → cloud LLM (when enabled) and ClinicalTrials.gov;
- orchestrator → NHI TWPAS (SUBMIT only).

The test profile adds GreenMail (IMAP) and MailHog (SMTP sink). `docker-compose.gb10.yml` switches every service
to arm64 and pins the GB10 vLLM build (D-79).

## 2. Libraries

- `schemas/*.schema.json` is the single source of truth for every contract (SPEC §3, §5, §7, §10.4 and every
  inter-service message). `libs/tb_contracts` holds the pydantic v2 models generated from it (`make contracts`;
  `make lint` fails when they are stale). Services exchange only these models (`tb_common.http` typed
  client/server).
- `libs/tb_common` modules:

| Module | Responsibility |
| --- | --- |
| `config` | `.env` and `settings.yaml` (schema-validated; services refuse to start on error) |
| `audit` | append-only hash chain: daily JSONL files, each line hashed with its predecessor; `verify` |
| `llm` | `chat_json` with schema-constrained output and prompt/version metadata; the only path to a model (§7) |
| `phi_guard` | MRN / national-id / name / date patterns; the cloud LLM is used only when this guard passes (§7.4) |
| `routing`, `authz`, `subject` | the PHI routing rule (§5), sender permissions, the mail-subject grammar |
| `deterministic` | OOXML normalisation (fixed zip times, no core timestamps) |
| `smallcell` | small-cell suppression |
| `crypto` | HMAC pseudonyms, AES-GCM pid map, sha256 |
| `ruleset` | approved-ruleset loading |
| `retention` | snapshot keep rule |
| `derived` | BMI, eGFR CKD-EPI 2021, DAS28 |
| `fhir` | `Library/$evaluate` client |
| `objstore` | MinIO / filesystem object store |

## 3. Data path

```
HIS export (csv | SQL)                         consent registry (csv | SQL)
   │  adapter: site mapping (extends tw_core/demo_his.yaml; rename/values; D-84)
   ▼
FHIR R4 NDJSON snapshot (pseudonymised: pid = HMAC(site key, MRN); name / national id only in the AES-GCM pid map)
   ├──► fhir-store (HAPI) ── CQL $evaluate (SCREEN, compile equivalence, TWPAS pre-check)
   └──► lake rebuild: DuckDB per snapshot (patient, encounter, condition, observation, medication, procedure,
        report, document, claim, consent, appointment, practitioner) + note chunks (BM25 ∪ embeddings, RRF)
        queries: SELECT-only (sqlglot guard), read-only, memory-capped with spill, snapshot-pinned
```

The nightly ingest adds these steps:
- an HL7 validator sample (1 %, TW Core); the ingest report fails above 0.5 % errors;
- fhir-store mirrors the snapshot: resources that left the source are deleted, from a ledger of loaded ids (D-86);
- medication orders without any date are dropped and reported (D-86);
- snapshot pruning (3 nightly + 36 month-ends, D-78).

## 4. Rule path (determinism)

```
protocol / NHI rule / cohort definition / CT.gov text
   │ doc-parser: lite (pypdf / python-docx heuristics; Docling when installed, D-02) → ParsedDoc (sections, I/E)
   │ criteria-compiler:
   │   ir_extract (LLM, schema-constrained; local model, or cloud only after the PHI guard)
   │   → CriterionIR → terminology (concept_map) → ValueSets
   │   → CQL (Jinja2 templates + TB_Common, cql-to-elm 5.4.0) and SQL (DuckDB templates)   ← never LLM-generated
   │   → equivalence gate: CQL on HAPI vs SQL on the lake for a stratified synthetic sample, ≥ 98 % (§6.4)
   │   → review package (HTML + review.xlsx) → APPROVE by e-mail → git tag <ID>/v<ver> (vendor rulesets
   │     arrive through signed updates)
   ▼
approved ruleset: manifest.yaml, ir/*.json, valuesets/*.json, cql/*.cql + elm, sql/*.sql, tests/{patients,expected}
```

Scenarios evaluate structured criteria in one of two ways. CQL `$evaluate` per patient on HAPI is the SCREEN default.
The ruleset SQL in the lake is used for FEAS month-ends, COHORT quarter-ends, NAV retrospection, and SCREEN when
`TB_SCREEN_ENGINE=sql`.

Note criteria go through RAG over the patient's chunks and then the `judge` (LLM, schema-constrained). The judge
must quote verbatim; the quote is checked against the record, with a fallback to the full record. Human criteria
are never decided by the box.

## 5. Orchestrator

- **Jobs.** SQLite queue (§3.5 mirror) with 4 workers; `STATUS`/`CANCEL` take a fast lane.
  - Every state change and every output file goes into the audit chain (`job.state`, `output` with sha256 and
    recipients).
  - The job's `run_date` is fixed at start; evaluation stamps use the job's receipt time. A re-run is therefore
    byte-identical (`python -m orchestrator.rerun`, D-82).
- **Scenarios** (`orchestrator/scenarios`):

| Scenario | Purpose |
| --- | --- |
| `feas` / `feas_compute` | month-end funnel, variants, monthly incidence, Monte-Carlo enrolment |
| `review` / `approve` | compile, review package, approval rounds |
| `screen` / `evaluate` / `microbatch` / `feedback` / `calibration` | candidates, tiers, pool, weekly re-evaluation, CRC feedback, reach/accept rates |
| `nav` / `facts` / `twpas` / `submit` | four NHI lists, docx drafts, TWPAS bundles + HL7 validation + pre-check, SUBMIT |
| `cohort` / `trials` | alliance tables, merge, ClinicalTrials.gov trial simulation |
| `admin` / `retention` | STATUS, CANCEL, INGEST, RETENTION |

- **Reports** (`orchestrator/reports`), all deterministic:
  - PDFs (reportlab invariant, embedded Noto Sans TC/JP, metadata-free matplotlib PNGs);
  - XLSX and DOCX normalised (docxtpl templates with highlighted `[待補]`);
  - TWPAS bundles (TW PAS IG 1.2.0).
- **Delivery.** The routing rule is checked for every delivery before anything is sent:
  - `phi` outputs go only to the ruleset's internal list/referral recipients, as 7z AES-256 with the password in a
    separate mail;
  - `aggregate` outputs (small cells suppressed) may go to `aggregate_to`.
- **Scheduler** (APScheduler, `settings.schedule`): INGEST 02:00, MICROBATCH Mon 03:00, NAV Mon 03:30,
  COHORT quarterly, RETENTION daily, CALIBRATION monthly.

## 6. Mail gateway

IMAP poll → `Authentication-Results` check (the MTA's header, `TB_MAIL_AUTHSERV_ID`; DMARC pass or an SPF/DKIM pass
aligned with the From: domain, D-86) → sender allowlist + per-command
permissions → per-sender daily rate limit → subject grammar → attachments to MinIO → `JobCreate` to the
orchestrator.

Replies to review mails are matched through `In-Reply-To`. Outbound mail is Markdown → HTML. PHI is wrapped in
7z/S-MIME, and recipients outside `internal_domains` never receive PHI.

## 7. Security and operations

- Audit chain verification: `tools/audit_verify.py`; acceptance: `tools/acceptance.py audit`.
- Egress allowlist: `deploy/network.sh`.
- Host checks (LUKS, swap, TPM, permissions, egress, GB10 driver): `deploy/check_host.sh`.
- Signed offline updates: `tools/sign_bundle.py` → `tools/apply_update.sh` (Ed25519, per-file hashes, network-less
  verification, audited).
- Retention: daily job plus adapter snapshot pruning.
- Onboarding without code changes: `tools/settings_wizard.py`, `services/adapter/mapping/templates/`,
  `tools/mapping_check.py`.
- Go-live acceptance (§11.2): `tools/acceptance.py`.
- Bench (§11.3): `tools/bench.py`.
- Operations: `docs/RUNBOOK.md`; host hardening: `docs/HARDENING.md`.

## 8. Tests

| Layer | Command | What |
| --- | --- | --- |
| unit + in-process integration | `make test` | contracts, IR→CQL/SQL, calculators, grammar, guards, every scenario in process against a synthetic lake with the stub LLM, ruleset oracles (planted states), onboarding of a new site, byte-identical re-runs |
| services | `make up-test && make test-integration` | HAPI CQL, equivalence gate, HL7 validator (TW Core, TWPAS IG), mail against GreenMail/MailHog |
| end to end | `make test-e2e` | FEAS → PDF, APPROVE loop, SCREEN, NAV RA-BIO, NAV ONC-OSI + SUBMIT, COHORT + alliance merge — all by e-mail |
| host | `sudo make test-egress` | nftables default deny with the allowlist on the running stack |
| LLM | `TB_LLM_EVAL_URL=… TB_JUDGE_LLM_URL=… pytest -m llm` | real model: judge on 300 items (≥ 90 %), ir_extract on 5 eligibility texts vs gold IR, concept_map on 200 concepts |
| bench | `make bench` | §11.3 (docs/BENCH.md) |
