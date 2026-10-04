# TrialBox v1.0 — implementation plan

This plan is written against `SPEC.md` v1.0 before any service code. Section numbers (§) refer to the spec.
Open decisions (§12.2) and every deviation are recorded in `docs/DECISIONS.md` (D-numbers below).

## 1. Module list

| Module | Kind | Port | Responsibility | Key libraries |
| --- | --- | --- | --- | --- |
| `schemas/` | JSON Schema 2020-12 | — | single source of truth for every contract in §3, §5, §7, §10.4 and the inter-service API messages | — |
| `libs/tb_contracts` | generated pydantic v2 | — | `datamodel-codegen` output from `schemas/` + thin re-export `__init__` | pydantic |
| `libs/tb_common` | library | — | `config` (env + settings.yaml validated against schema), `logging` (JSON, PHI-safe), `audit` (hash chain), `ulid`, `crypto` (sha256, HMAC pid, Ed25519, AES-GCM), `llm` (`chat_json`), `phi_guard`, `objstore` (MinIO / filesystem), `http` (service app factory + typed client), `timeutil`, `derived` (shared constants + BMI/eGFR/DAS28/BASDAI/ASDAS reference formulas) | httpx, fastapi, cryptography, jsonschema |
| `services/mail_gateway` | FastAPI + poller | 8015 | IMAP poll, sender allowlist + SPF/DKIM, subject grammar (§5), MinIO attachments, job creation, `/send` (Markdown→HTML, 7z/S-MIME, routing enforcement, rate limit) | imaplib, smtplib, py7zr, cryptography |
| `services/doc_parser` | FastAPI | 8011 | `/parse`: Docling (prod) / pypdf+python-docx (lite) → sections, tables, I/E block, language; deterministic output | docling (optional), pypdf, python-docx |
| `services/criteria_compiler` | FastAPI | 8012 | `/compile`, `/diff`, `/approve`; `ir_extract/` (prompts + post-processing), `terminology/` (tables + ValueSet build + `concept_map`), `compile_cql/` (Jinja2 templates + TB_Common.cql + cql-to-elm 5.4.0 JVM), `compile_sql/` (DuckDB templates), `equivalence/` (CQL-vs-SQL gate), review package, git ruleset repo | jinja2, openpyxl, git CLI, JRE 17 |
| `services/adapter` | CLI + tiny trigger API | 8016 | `adapter run --source {csv,cgrd_sql,fhir_bulk,ssmix2}`: extract → mapping YAML → FHIR NDJSON → load HAPI (tx of 500) → lake rebuild → 1 % validator sample → `ingest_report.json`; HMAC pid + encrypted pid map | sqlalchemy, httpx |
| `services/lake` | FastAPI | 8013 | `/query` (sqlglot SELECT-only, 300 s timeout, Arrow IPC), `/chunks/search` (BM25 via DuckDB FTS ∪ cosine, RRF), `/rebuild` (NDJSON → Parquet by snapshot, chunking, embedding cache) | duckdb, duckdb-extension-fts, pyarrow, sqlglot |
| `services/embed_service` | FastAPI | 8014 | `/embed` bge-m3 (sentence-transformers) or deterministic `hash` mode for CPU CI | sentence-transformers (optional) |
| `services/llm_service` | config only | 8000 | vLLM compose config + `models/manifest.yaml` | vllm image |
| `services/llm_stub` | FastAPI | 8000 | OpenAI-compatible deterministic stub (`TB_LLM_MODE=stub`): cassettes + rule-based judge/concept_map/draft_doc for CPU CI and macOS | — |
| `services/orchestrator` | FastAPI + workers + APScheduler | 8010 | SQLite job queue (§3.5 mirror), 4 workers, state machine + audit, scenarios `feas/screen/cohort/nav` (+ microbatch, approve, status, submit, feedback, ingest, retention, calibration), reports (`feasibility_pdf`, `candidate_xlsx`, `nav_xlsx`, `docx_draft`, `twpas_bundle`, `cohort`), routing + `/send` | apscheduler, reportlab, matplotlib, openpyxl, docxtpl, fhir.resources |
| `fhir-store` | HAPI JPA starter 8.12 (CR on) | 8080 | FHIR R4 store, `Library/$evaluate` | — |
| `fhir-db`, `minio` | upstream images | 5432, 9000 | storage | — |
| `tools/` | scripts | — | `make_fixtures.py`, `gen_contracts.py`, `audit_verify.py`, `bench.py`, `export_spec.py`, `build_terminology.py`, `settings_wizard.py`, `sign_bundle.py`, `apply_update.sh`, `fetch_*.sh` | — |

## 2. Interfaces (all bodies are `tb_contracts` models)

| Caller → callee | Endpoint | Request model | Response model |
| --- | --- | --- | --- |
| mail-gateway → orchestrator | `POST /jobs` | `JobCreate` | `Job` |
| any → orchestrator | `GET /jobs/{id}` | — | `Job` |
| orchestrator → mail-gateway | `POST /send` | `SendRequest` | `SendResult` |
| orchestrator → doc-parser | `POST /parse` | `ParseRequest` | `ParsedDoc` |
| orchestrator → compiler | `POST /compile`, `/diff`, `/approve` | `CompileRequest`, `DiffRequest`, `ApproveRequest` | `CompileResult`, `DiffResult`, `ApproveResult` |
| orchestrator/compiler → lake | `POST /query` | `LakeQuery` | Arrow IPC stream |
| orchestrator → lake | `POST /chunks/search` | `ChunkSearchRequest` | `ChunkSearchResult` |
| lake → embed | `POST /embed` | `EmbedRequest` | `EmbedResponse` |
| orchestrator → adapter | `POST /run` | `IngestRequest` | `IngestReport` |
| orchestrator/compiler → fhir-store | `Library/{id}/$evaluate` | FHIR `Parameters` | FHIR `Parameters` (`C_<ID>`, `E_<ID>`) |
| any → llm | `tb_common.llm.chat_json(prompt_id, variables, schema)` | prompt front-matter + variables | schema-validated dict, audited |

## 3. Data flow per scenario

* **INGEST (02:00)**: adapter → NDJSON snapshot → HAPI + lake rebuild → validator sample → report → audit.
* **FEAS**: mail → job → doc-parser → (compile → review → `awaiting_approval` → `APPROVE`) or approved tag → lake SQL at month-ends → funnel / sensitivity / monthly / simulation → PDF + XLSX + JSON (`aggregate`) → `aggregate_to`.
* **SCREEN**: approved tag required → scope pids (lake) → CQL per patient (fhir-store, 8 concurrent) → candidates → RAG + `judge` → tiers → candidate XLSX / referral XLSX / JSON (`phi`), summary PDF (`aggregate`) → pool persisted.
* **MICROBATCH (Mon 03:00)**: pool ∩ appointments next 14 d → time-sensitive criteria only → `this_week_visit1.xlsx` with `changes` sheet.
* **NAV (Mon 03:30)**: per NHI ruleset → four lists → docx drafts (+ TWPAS bundles, validator, pre-check when `twpas_enabled`).
* **COHORT (quarterly)**: per-disease counts → alliance CSV → report → trial simulation from ClinicalTrials.gov (cached) ; `COHORT MERGE` merges member CSVs.

## 4. Test plan

| Layer | Location | Runs in CPU CI | Content |
| --- | --- | --- | --- |
| Unit | `tests/unit` | yes (`make test`) | schemas valid + every IR fixture validates; contracts regenerate identically; config load/refusal; audit chain append/verify/tamper; ULID; IR→CQL and IR→SQL snapshots for every atom/quantifier/derived/bool; derived calculators vs published examples; subject grammar; PHI guard; routing; small-cell suppression; simulation; lake SQL guard; chunker/tokenizer; mapping engine; tiering; xlsx/pdf/docx renderers |
| Integration (in-process) | `tests/integration` (no marker) | yes | adapter csv/sqlite → NDJSON → lake rebuild; `/chunks/search` 20 seeded queries; SQL ruleset evaluation vs `expected.json`; compile pipeline with stub LLM; scenarios with in-process lake and fake fhir evaluator |
| Integration (services) | `tests/integration` `@integration` | yes, with `make up-test` | HAPI load + translator + `$evaluate`; equivalence gate ≥98 %; mail-gateway against GreenMail/MailHog |
| E2E | `tests/e2e` `@e2e` | yes, with compose test profile | `FEAS GZQO` → PDF+XLSX; `APPROVE` round trip; `SCREEN` → candidates; microbatch; `NAV RA-BIO`; `COHORT` merge |
| LLM | `tests/llm` `@llm` | no (GPU/cloud) | judge 300 triples, ir_extract 5 protocols, concept_map 200 concepts |
| Perf | `tools/bench.py` `@perf` | no | §11.3 targets |

Fixtures: `tools/make_fixtures.py --seed 42 --patients 600` writes HIS-like CSV + SQLite exports for site A and site B,
and the per-ruleset `tests/patients.ndjson` + `expected.json` (generator ground truth), so every structured criterion
has pass / fail / null cases and every note criterion has pass / fail / unknown narratives in zh-TW.

## 5. Phase map

Phases 0→9 follow §12 exactly; each ends with `make lint test`, the phase DoD, a `phase-N:` commit and a
`docs/PROGRESS.md` entry.

## 6. Open decisions resolved (details in DECISIONS.md)

* §12.2 Docling vs marker → **Docling** (D-02).
* §12.2 `$evaluate` vs `$evaluate-measure` → **`Library/$evaluate`**; measure path behind `TB_CQL_EVAL_MODE=measure` (D-03).
* §12.2 7z vs S/MIME → **7z AES-256 (`zip`)** default, S/MIME selectable (D-04).
