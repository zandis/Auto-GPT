# SPEC — TrialBox: On-Prem Patient Finding & NHI Navigation Appliance (v1.0)

Oct 4, 2026 · @Changfu

This document is the single build specification for TrialBox. It is written so that one engineer or one coding agent can implement the system end-to-end without further design decisions. Export as Markdown and hand it to the implementer together with the site-specific parameter file in section 12.

## 1. Scope, goals, non-goals, conventions

**Product**: a single on-prem appliance ("the box") that turns eligibility rules (trial protocols, NHI reimbursement rules) into auditable patient screens, and returns results by email. No UI. No real-time. Batch only.

**Goals (v1.0)**

- G1 Feasibility (`FEAS`): from a protocol or question list, produce a criterion funnel, sensitivity variants and a 12-month enrollment estimate over the whole hospital or a department, aggregate only.
- G2 Site screening (`SCREEN`): from a final protocol, produce a two-tier candidate list over the PI/co-PI clinics within an enrollment window, with per-criterion evidence, then re-evaluate time-sensitive criteria weekly for candidates with an appointment in the next 14 days.
- G3 Cohort tables (`COHORT`): quarterly "major criteria × count" tables per disease, mergeable across alliance sites, plus enrollment simulation against recruiting trials.
- G4 NHI navigation (`NAV`): weekly lists for a department (likely eligible, renewal due, documentation gaps, possibly no-longer eligible) with pre-filled application drafts; for drug programs covered by NHI TWPAS, produce a validator-clean TWPAS Bundle and run NHI's published CQL pre-check.
- G5 Everything reproducible: every output carries ruleset version, model version, data snapshot date, and is logged append-only.

**Non-goals (v1.0)**: web UI, user accounts, real-time EHR hooks, automatic submission to NHI without physician sign-off, clinical recommendations, OMOP CDM support, multi-tenant cloud.

**Glossary**

| Term | Meaning |
| --- | --- |
| Ruleset | One protocol or one reimbursement rule set compiled into Criterion IR + CQL + SQL + ValueSets + tests; semver versioned; stored in Git |
| Criterion IR | JSON representation of one eligibility criterion (section 3.3) |
| Class | `structured` (computable from coded data), `note` (needs free text), `human` (needs patient/clinician input) |
| Index date | Reference date for windows; `FEAS`/`COHORT`: each month-end in the lookback; `SCREEN`/`NAV`: the run date |
| Scope | The patient set a run evaluates: whole hospital, department, or practitioner list ∩ appointment window |
| Tier | `high` (all structured pass, no note fail, human pending) / `review` (any unknown) / `excluded` |
| Snapshot | Date of the FHIR/lake data used by a run |

**Conventions**

- Language: Python 3.12 for all services except fhir-store (Java, HAPI) and cql-translator (Java). Type hints mandatory; `pydantic` v2 models for every contract in section 3; `ruff` + `mypy --strict`.
- IDs: ULIDs for jobs and runs; patient identity inside the box is the FHIR `Patient.id` (hospital MRN mapped by the adapter); outputs never contain names.
- Time: all timestamps ISO-8601 with offset; hospital local zone configured in `settings.yaml`.
- Terminology: ICD-10-CM (NHI edition) for conditions, NHI drug code + ATC for medications, LOINC for labs/vitals, NHI order codes for procedures, SNOMED CT where TW Core requires it. ValueSets are FHIR `ValueSet` resources with explicit `compose.include.concept` lists (no implicit expansions).
- Determinism: SQL and CQL generation is template-based, never LLM-generated. LLM output is always JSON constrained by a schema.
- Errors: no silent failures; every job ends in `done` or `failed` with a reply email.

## 2. System context, deployment, repository

**Context**: the box sits on the hospital VLAN. Inputs: (a) nightly data drop from HIS/CGRD (SQL read-replica, CSV export, or FHIR Bulk `$export`), (b) emails to the intake mailbox. Outputs: emails to internal mailboxes; optionally HTTPS to the NHI TWPAS endpoint. Egress is deny-by-default.

**Deployment topology (docker compose, single host)**

| Service | Image base | Ports (internal only) | Volumes | Notes |
| --- | --- | --- | --- | --- |
| `mail-gateway` | python:3.12-slim | none | `inbox/` (MinIO bucket `attachments`) | polls IMAP every 60 s; sends via SMTP |
| `doc-parser` | python:3.12 + docling | 8011 | `attachments` | HTTP POST /parse |
| `criteria-compiler` | python:3.12 + JRE 17 (cql-translator) | 8012 | `rulesets/` (git repo) | HTTP POST /compile, /diff, /approve |
| `fhir-store` | hapiproject/hapi:latest (jpaserver-starter with CR module) | 8080 | pg data | FHIR R4; CQL evaluate |
| `fhir-db` | postgres:16 | 5432 | pg data | for fhir-store only |
| `lake` | python:3.12 + duckdb | 8013 | `lake/` parquet | HTTP POST /query (parameterized SQL only) |
| `adapter` | python:3.12 | none | source mounts | CLI, runs nightly from orchestrator |
| `llm-service` | vllm/vllm-openai (x86) or eugr/spark-vllm (GB10) | 8000 | `models/` | OpenAI-compatible; `--guided-decoding-backend outlines` |
| `embed-service` | python:3.12 + sentence-transformers | 8014 | `models/` | bge-m3, POST /embed |
| `orchestrator` | python:3.12 | 8010 | `jobs.sqlite`, `audit/` | APScheduler + job queue; owns reports |
| `minio` | minio/minio | 9000 | `minio/` | object store for attachments/outputs |

All services on a private compose network `trialbox-net`; only `mail-gateway` has outbound to the hospital mail server; only `criteria-compiler` may reach the cloud LLM endpoint (via explicit `CLOUD_LLM_BASE_URL`, disabled by default); only `orchestrator` may reach `NHI_TWPAS_BASE_URL`. Enforce with iptables/nftables rules in `deploy/network.sh` (container-level egress allowlists by destination).

**Repository layout (monorepo `trialbox/`)**

```
trialbox/
  README.md
  SPEC.md                      # this document, exported
  deploy/
    docker-compose.yml
    docker-compose.gb10.yml    # overrides for DGX Spark (arm64 images, driver pin)
    network.sh                 # egress allowlists
    settings.example.yaml
  schemas/                     # JSON Schema, single source of truth
    criterion_ir.schema.json
    ruleset_manifest.schema.json
    job.schema.json
    feasibility_result.schema.json
    candidate_list.schema.json
    nav_lists.schema.json
    screen_feedback.schema.json
    llm_extract_output.schema.json
    llm_judge_output.schema.json
  libs/
    tb_contracts/              # pydantic models generated from schemas/
    tb_common/                 # config loader, logging, audit, ulid, crypto
  services/
    mail_gateway/
    doc_parser/
    criteria_compiler/
      ir_extract/              # LLM prompts + post-processing
      terminology/             # ValueSet build, code mapping tables
      compile_cql/             # templates + translator call
      compile_sql/             # templates for DuckDB
      equivalence/
    adapter/
      sources/{cgrd_sql,csv,fhir_bulk,ssmix2}/
      mapping/{tw_core,jp_core}/
      validate/
    lake/
    orchestrator/
      scenarios/{feas,screen,cohort,nav}.py
      reports/{feasibility_pdf,candidate_xlsx,nav_xlsx,twpas_bundle,docx_draft}/
      scheduler.py
    llm_service/               # compose config + model manifest only
  rulesets/                    # git submodule; one dir per ruleset
    GZQO/
      manifest.yaml
      ir/*.json
      valuesets/*.json
      cql/*.cql
      sql/*.sql
      tests/{patients.ndjson,expected.json}
  tests/
    unit/ integration/ e2e/ fixtures/synthetic_patients/
  tools/
    make_fixtures.py  export_spec.py  bench.py
```

**Environment variables (`.env`, loaded by `tb_common.config`)**: `TB_SITE_ID`, `TB_TZ=Asia/Taipei`, `IMAP_HOST/PORT/USER/PASS`, `SMTP_HOST/PORT/USER/PASS`, `MAIL_INTAKE_ADDR`, `MAIL_FROM_ADDR`, `FHIR_BASE_URL=http://fhir-store:8080/fhir`, `LAKE_URL`, `LLM_BASE_URL=http://llm-service:8000/v1`, `LLM_MODEL`, `CLOUD_LLM_BASE_URL` (optional), `CLOUD_LLM_API_KEY` (optional), `EMBED_URL`, `MINIO_*`, `NHI_TWPAS_BASE_URL` (optional), `ATTACH_PASSWORD_MODE=smime|zip`, `LOG_LEVEL`.

**settings.yaml** (schema in section 10): site, allowlists, routing, scopes (practitioner lists, departments), data source type, retention, thresholds.

## 3. Data contracts

### 3.1 FHIR minimal profile (what the adapter MUST produce)

FHIR R4 NDJSON, one file per resource type, TW Core 1.0.0 profiles where they exist (JP Core 1.2.x for Japan). Elements below are required for the engine; anything else is optional.

| Resource | Required elements | Coding |
| --- | --- | --- |
| Patient | id (= MRN hash, stable), birthDate, gender, deceasedBoolean/DateTime | — |
| Encounter | id, subject, class, period.start, serviceType (department code), participant.individual (Practitioner) | NHI department code |
| Appointment | id, participant(Patient, Practitioner), start, status (booked/arrived/cancelled), serviceType | — |
| Condition | id, subject, code, onsetDateTime or recordedDate, clinicalStatus, encounter | ICD-10-CM |
| Observation | id, subject, code, effectiveDateTime, valueQuantity (value, unit UCUM) or valueCodeableConcept, category (laboratory/vital-signs/survey) | LOINC; local code allowed in second coding |
| MedicationRequest | id, subject, medicationCodeableConcept, authoredOn, dispenseRequest.validityPeriod or dosageInstruction.timing.repeat.boundsPeriod, status | NHI drug code + ATC |
| MedicationStatement (optional, for patient-reported) | subject, medication, effectivePeriod | ATC |
| Procedure | id, subject, code, performedDateTime | NHI order code |
| DiagnosticReport (imaging/pathology) | id, subject, code, effectiveDateTime, conclusion (text) | LOINC |
| DocumentReference | id, subject, date, type (note type), context.encounter, content.attachment.contentType=text/plain, content.attachment.data (base64 full text) | LOINC doc type |
| Claim / ClaimResponse (NHI prior-auth history) | subject, created, item.productOrService, outcome, disposition, extension: approval period | NHI codes |
| Practitioner | id, identifier (hospital staff id) | — |

Adapter output is validated by the HL7 validator on a 1% sample per nightly run; validation errors above 0.5% fail the run.

### 3.2 Lake tables (Parquet, flattened from the same NDJSON)

`patient(pid, birth_date, sex, deceased_date)`; `encounter(eid, pid, start, dept, practitioner_id, class)`; `appointment(aid, pid, start, practitioner_id, dept, status)`; `condition(pid, code, system, onset, recorded, status, eid)`; `observation(pid, code, system, effective, value_num, unit, value_code, category)`; `medication(pid, nhi_code, atc, start, end, status)`; `procedure(pid, code, performed)`; `report(pid, code, effective, conclusion)`; `document(did, pid, date, type, eid)`; `document_chunk(did, chunk_no, text, embedding FLOAT[1024])`; `claim(pid, created, product, outcome, approval_start, approval_end)`. Partition by snapshot date. DuckDB FTS index on `document_chunk.text`.

### 3.3 Criterion IR (`schemas/criterion_ir.schema.json`)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "CriterionIR",
  "type": "object",
  "required": ["id","ruleset","text","kind","class","logic"],
  "properties": {
    "id": {"type":"string","pattern":"^[A-Z0-9]+-(INC|EXC|REN|DOC)-[0-9]{2,3}$"},
    "ruleset": {"type":"string"},
    "text": {"type":"string"},
    "source_ref": {"type":"string", "description":"section/page in source document"},
    "kind": {"enum":["inclusion","exclusion","renewal","documentation"]},
    "class": {"enum":["structured","note","human"]},
    "time_sensitive": {"type":"boolean","default":false},
    "logic": {"$ref":"#/$defs/expr"},
    "fallback": {"type":"string"},
    "note_question": {"type":"string","description":"for class=note: the yes/no question put to the LLM"},
    "human_question": {"type":"string"},
    "review": {"type":"object","properties":{"status":{"enum":["draft","approved","rejected"]},"by":{"type":"string"},"at":{"type":"string","format":"date-time"},"comment":{"type":"string"}}}
  },
  "$defs": {
    "expr": {"oneOf":[{"$ref":"#/$defs/atom"},{"$ref":"#/$defs/bool"}]},
    "bool": {"type":"object","required":["op","args"],"properties":{"op":{"enum":["and","or","not"]},"args":{"type":"array","items":{"$ref":"#/$defs/expr"}}}},
    "atom": {"type":"object","required":["domain","valueset"],"properties":{
      "domain": {"enum":["condition","observation","medication","procedure","encounter","demographic","claim","report"]},
      "valueset": {"type":"string","description":"ValueSet id in ruleset/valuesets"},
      "quantifier": {"enum":["any","none","count>=","latest","all"],"default":"any"},
      "count": {"type":"integer"},
      "value": {"type":"object","properties":{"op":{"enum":[">",">=","<","<=","=","between","in"]},"num":{"type":"number"},"num2":{"type":"number"},"unit":{"type":"string"},"codes":{"type":"array","items":{"type":"string"}}}},
      "window": {"type":"object","properties":{"from_days":{"type":"integer"},"to_days":{"type":"integer"},"anchor":{"enum":["index","event"]}}},
      "duration": {"type":"object","description":"for medication: continuous exposure","properties":{"min_days":{"type":"integer"},"gap_days":{"type":"integer","default":30}}},
      "age": {"type":"object","properties":{"min":{"type":"number"},"max":{"type":"number"}}},
      "sex": {"enum":["male","female"]},
      "derived": {"enum":["bmi","egfr","das28","basdai","asdas"],"description":"computed observation"}
    }}
  }
}
```

Semantics: `window.from_days/to_days` are relative to the index date (negative = past). `quantifier=latest` means the most recent observation in the window is compared. `duration.min_days` with `gap_days` defines continuous medication exposure allowing gaps ≤ gap\_days. `derived` observations are computed by the compiler from components (BMI from latest height+weight within 365 d; eGFR CKD-EPI 2021 from latest creatinine, age, sex; DAS28 from TJC28, SJC28, ESR or CRP, patient global).

### 3.4 Ruleset manifest (`manifest.yaml`)

```yaml
id: GZQO
kind: trial | nhi
title: "J1I-MC-GZQO retatrutide gout phase 3"
version: 1.0.0
source_documents: ["protocol_v3.pdf"]
protocol_version: "3.0"
language: zh-TW
index_date_rule: run_date | month_end
scopes:
  feas: {population: hospital, lookback_months: 36}
  screen: {practitioners: ["P12345","P23456"], appointment_window_days: 180, departments: ["RHEU","META"]}
  nav: {departments: ["RHEU"], appointment_window_days: 14, renewal_lead_days: 42}
routing:
  aggregate_to: ["crc@hosp.tw"]
  list_to: ["pi@hosp.tw","crc@hosp.tw"]
  referral_to: {"META": "meta-head@hosp.tw"}
thresholds: {tier_high_confidence: 0.75, small_cell: 5}
models: {judge: "qwen3.5-35b-a3b-q4", judge_prompt: "judge_v3"}
review: {approved_by: "crc@hosp.tw", approved_at: "2026-10-20T09:00:00+08:00"}
```

### 3.5 Job (`schemas/job.schema.json`)

`{job_id, type(FEAS|SCREEN|COHORT|NAV|APPROVE|STATUS|MICROBATCH|INGEST), ruleset, ruleset_version, requested_by, received_at, state(received|parsing|compiling|awaiting_approval|running|reporting|done|failed), snapshot_date, inputs:[{filename, sha256, minio_key}], outputs:[{filename, sha256, minio_key, recipients}], error, metrics{patients_scoped, llm_calls, tokens_in, tokens_out, wall_seconds}}`.

### 3.6 Output contracts

- `feasibility_result`: `{ruleset, version, snapshot, population, funnel:[{criterion_id, label, remaining, dropped, pct}], sensitivity:[{criterion_id, variant, remaining}], monthly_new:[{month, n}], simulation:{reach_rate, accept_rate, capacity_per_month, months, low, mid, high}, notes:[string]}`.
- `candidate_list`: `{ruleset, version, snapshot, scope, rows:[{pid, tier, next_appointment, practitioner_id, criteria:[{id, verdict(pass|fail|unknown|pending_human), evidence:{resource_refs:[…], quote, quote_date, confidence}}], actions:[string]}], summary:{high, review, excluded}}`.
- `nav_lists`: `{ruleset, version, snapshot, department, lists:{likely_eligible:[row], renewal_due:[row], doc_gaps:[row], maybe_ineligible:[row]}}` with `row = {pid, next_appointment, practitioner_id, criteria:[…], missing:[{item, suggested_order}], draft_doc_key, twpas_bundle_key, precheck:{passed, issues:[…]}}`.
- `screen_feedback` (CRC reply CSV): `pid, outcome(enrolled|screen_fail|declined|not_contacted), reason_code, note`.

## 4. Service specifications

Each service: FastAPI (or CLI), `/healthz`, structured JSON logs to stdout, pydantic request/response models from `libs/tb_contracts`, idempotent operations keyed by `job_id`.

### 4.1 mail-gateway

- Poll IMAP `INBOX` every 60 s (`UNSEEN`). For each message: verify sender ∈ `settings.allowlist.senders` and SPF/DKIM pass (header `Authentication-Results`); else move to `Rejected` and reply with reason.
- Parse subject with grammar in section 5. Save raw `.eml` and each attachment to MinIO `attachments/{job_id}/`. Compute sha256.
- Create Job via `POST orchestrator:8010/jobs` with `{type, ruleset, options, requested_by, inputs}`. Move message to `Processed`.
- Outbound: `POST /send` from orchestrator with `{to[], subject, body_md, attachments[{minio_key, filename}], encrypt: bool}`; render body Markdown → HTML+text; if `encrypt`, build 7z AES-256 with per-job password (password mailed separately to the same recipient only when `ATTACH_PASSWORD_MODE=zip`; with `smime`, sign+encrypt using recipient certs from `settings`). Enforce routing: recipients outside `settings.internal_domains` may only receive outputs tagged `aggregate`.
- Rate limit: 20 jobs/sender/day; replies to unknown senders never include system details.

### 4.2 doc-parser

- `POST /parse {minio_key}` → `{sections:[{title, level, text}], tables:[{caption, rows}], ie_block:{inclusion:[text], exclusion:[text]}, language}`.
- Pipeline: Docling for PDF/DOCX (layout + tables); fallback PaddleOCR for scanned PDFs (detect by text density < 50 chars/page). Extract I/E block by heading heuristics (`Inclusion Criteria|納入條件|選択基準`, `Exclusion|排除條件|除外基準`) then by LLM if heuristics fail (section 7.1 prompt `ie_locate`).
- Deterministic output: same file → same sha of output JSON.

### 4.3 criteria-compiler

- `POST /compile {job_id, ruleset, parsed_doc_key, options}` → creates `rulesets/{id}/` draft on a Git branch `draft/{job_id}`: runs IR extraction (7.1), classification, terminology mapping (4.3.1), CQL + SQL compilation (section 6), equivalence test on `tests/patients.ndjson`, writes `manifest.yaml`, returns `{ruleset, version, criteria:[IR], tests:{equivalence_pct}, review_html_key}`.
- `POST /diff {ruleset, new_doc_key}` → list of changed/added/removed criteria vs current tag; only changed criteria are re-extracted.
- `POST /approve {ruleset, version, by, decisions:[{id, status, edited_ir?}]}` → applies edits, re-compiles affected criteria, tags Git `v{version}`, returns final manifest.
- 4.3.1 Terminology mapping: tables in `services/criteria_compiler/terminology/` (`icd10cm_tw.parquet`, `nhi_drug.parquet` with ATC, `loinc_tw.parquet`, `nhi_order.parquet`, local lab code → LOINC map provided by site). Mapping steps: exact name match → synonym table → LLM-proposed candidates (7.1 `concept_map`) which are always marked `needs_review`. Output `ValueSet` JSON with `compose.include[].concept[]` only.
- Cloud LLM use is allowed only in this service and only after the PHI guard (7.4) passes on the input text.

### 4.4 fhir-store

- HAPI JPA Server Starter with Clinical Reasoning enabled (`hapi.fhir.cr.enabled=true`), R4, Postgres backend, `max_page_size=1000`, bulk import via `$import` or NDJSON upload script in `adapter/load_fhir.py` (batch transactions of 500).
- Libraries loaded as FHIR `Library` with ELM (base64 `content`) plus the `.cql`; ValueSets loaded as resources; evaluation via `Library/{id}/$evaluate?subject=Patient/{pid}&parameters=...` returning a `Parameters` with one named expression per criterion (`C_<ID>` → boolean|null) plus `E_<ID>` (evidence references list).
- Patient scoping is done by the orchestrator (list of pids); fhir-store evaluates one patient per call; orchestrator runs up to 8 concurrent calls.

### 4.5 lake

- `POST /query {sql, params}`: only `SELECT` (parsed with sqlglot; anything else rejected); timeouts 300 s; results Arrow IPC.
- `POST /chunks/search {pid, query, k}`: hybrid retrieval over `document_chunk` restricted to `pid` and a date window: BM25 (DuckDB FTS) ∪ cosine (embedding from embed-service), reciprocal rank fusion, return top-k `{did, chunk_no, text, date, score}`.
- Nightly `rebuild` from NDJSON: flatten, partition by snapshot, chunk documents (500 chars, 100 overlap), embed new chunks only (cache by sha).

### 4.6 adapter (CLI, nightly)

- `adapter run --source {cgrd_sql|csv|fhir_bulk|ssmix2} --since <date>`: extract delta → map to FHIR via site mapping YAML (`mapping/tw_core/*.yaml`: source table/column → FHIR path, code system, unit) → write NDJSON to `lake/ndjson/{snapshot}/` → load fhir-store and lake → validate 1% sample with HL7 validator → write `ingest_report.json` (counts per resource, validation errors, missing required elements).
- MRN pseudonymization: `pid = HMAC-SHA256(site_key, MRN)`; the reverse table `pid → MRN` is kept only in the box (`secrets/pid_map.sqlite`) and used solely when rendering lists for internal recipients.

### 4.7 llm-service and embed-service

- vLLM OpenAI-compatible server, model from `models/manifest.yaml` (`name, path, quant, max_model_len=32768, gpu_memory_utilization`), `--guided-decoding-backend outlines`, `--max-num-seqs 64`. On GB10 use the `deploy/docker-compose.gb10.yml` image and pinned driver.
- embed-service: `POST /embed {texts[]}` → bge-m3 dense vectors (1024-d), batch 64.
- Client wrapper `tb_common.llm.chat_json(prompt_id, variables, schema)`: loads prompt template by id and version, enforces JSON schema via `response_format`, retries once on schema violation, records `{prompt_id, prompt_version, model, input_sha, output_sha}` to audit.

### 4.8 orchestrator and reports

- Job queue in SQLite (`jobs` table mirrors section 3.5); worker pool size 4; APScheduler jobs: `ingest` (02:00 daily), `microbatch` (Mon 03:00), `nav` (Mon 03:30), `cohort` (1st of quarter), `retention` (daily).
- Scenario modules implement `run(job) -> OutputBundle` (section 8). Reports modules render outputs (section 9) and return MinIO keys; orchestrator calls mail-gateway `/send` with routing from the ruleset manifest.
- Audit: every state change appended to `audit/{date}.jsonl` with hash chain (`prev_hash`), see section 10.

## 5. Email protocol

**Subject grammar (ABNF)**

```
subject   = cmd SP ruleset *(SP option) [SP "--" SP comment]
cmd       = "FEAS" / "SCREEN" / "COHORT" / "NAV" / "APPROVE" / "STATUS" / "CANCEL"
ruleset   = 1*16(ALPHA / DIGIT / "-" / "_")
option    = key "=" value
key       = "window" / "pract" / "dept" / "lookback" / "version" / "variant" / "since"
value     = 1*32(ALPHA / DIGIT / "-" / "," / ".")
```

Examples: `FEAS GZQO lookback=36 variant=bmi:24,25,27` · `SCREEN GZQO version=1.0.0 window=180 pract=P12345,P23456` · `NAV RA-BIO dept=RHEU` · `APPROVE GZQO version=1.0.0` · `STATUS 01JB…`.

**Attachments**: any of PDF/DOCX/XLSX/CSV/TXT; for `APPROVE`, the reviewed `review.xlsx` returned by the compiler (one row per criterion with columns `id, decision(approve|reject|edit), edited_text, edited_class, comment`).

**Approval loop**

1. Compile produces `review.html` (inline) + `review.xlsx` (attachment) + `ruleset_v{ver}-draft.zip` (IR, ValueSets, CQL, SQL, test results). Sent to `routing.aggregate_to`.
2. Reviewer replies `APPROVE <ruleset> version=<ver>` with the edited `review.xlsx`. Reply-to-thread also accepted (In-Reply-To header matched to job).
3. Compiler applies decisions; if any `edit`, recompiles those criteria and re-sends review (max 3 rounds); when all `approve`, tags the version and emails `Ruleset <id> v<ver> approved` with the final manifest.
4. Runs (`SCREEN`, `NAV`) refuse rulesets without an approved tag.

**Replies**: every job gets `Received <job_id>` within 5 minutes, then `Done <job_id>` with outputs or `Failed <job_id>` with a plain-language reason and the step that failed. `STATUS` returns the job record.

**Routing enforcement**: outputs carry a tag `aggregate` or `phi`. `phi` outputs may only be sent to addresses in `routing.list_to` or `routing.referral_to` that are inside `settings.internal_domains`. Violations fail the job.

## 6. Compilation rules

### 6.1 Shared conventions

- One ruleset → one CQL Library `TB_<RULESET>_v<major>_<minor>` and one SQL file with one CTE per criterion. Criterion expression names `C_<ID>` (boolean or null) and `E_<ID>` (evidence list).
- Parameters: `IndexDate` (Date), `LookbackMonths` (Integer). Defaults from manifest.
- Unknown handling: a criterion evaluates to `null` when required data is absent in the window (e.g. no creatinine for eGFR). `null` never counts as pass or fail; tiering treats it as `unknown`.
- Exclusion criteria are compiled as positive predicates and negated at aggregation (`eligible_structured = all(C_INC) and none(C_EXC)`), never inside the criterion.

### 6.2 IR → CQL templates (per atom)

| domain / quantifier | CQL template |
| --- | --- |
| condition, any | `exists ([Condition: "VS_<vs>"] C where C.onset in Interval[IndexDate - <from>days, IndexDate - <to>days])` |
| observation, latest + value | `Last([Observation: "VS_<vs>"] O where O.effective in <win> sort by effective) O1 where O1.value as Quantity <op> <num> '<unit>'` |
| observation, any + value | `exists ([Observation: "VS_<vs>"] O where O.effective in <win> and O.value as Quantity <op> <num> '<unit>')` |
| medication, any | `exists ([MedicationRequest: "VS_<vs>"] M where M.authoredOn in <win>)` |
| medication, duration | `TB.ContinuousExposureDays([MedicationRequest: "VS_<vs>"], <win>, <gap_days>) >= <min_days>` (helper in `TB_Common` library: merges validity periods allowing gaps) |
| procedure, any | `exists ([Procedure: "VS_<vs>"] P where P.performed in <win>)` |
| encounter, count>= | `Count([Encounter: "VS_<vs>"] E where E.period.start in <win>) >= <count>` |
| demographic, age | `AgeInYearsAt(IndexDate) between <min> and <max>` |
| derived bmi | `TB.LatestBMI(IndexDate, 365)` then compare |
| derived egfr | `TB.LatestEGFR(IndexDate, 365)` (CKD-EPI 2021) |
| derived das28 | `TB.LatestDAS28(IndexDate, 90)` from components; null if any component missing |
| claim, any | `exists ([Claim: "VS_<vs>"] K where K.created in <win>)` |

`<win>` = `Interval[IndexDate + <from_days> days, IndexDate + <to_days> days]`. Bool nodes map to `and/or/not`. Evidence `E_<ID>` returns the matched resources' ids and dates.

Translate with cql-translator to ELM JSON; fail compile on any translator error or warning of type `semantic`.

### 6.3 IR → SQL templates (DuckDB)

Each atom becomes a CTE returning `(pid, index_date, hit BOOLEAN, evidence VARCHAR)`; the ruleset CTE joins all criteria on `(pid, index_date)`; `FEAS` evaluates `index_date` = each month-end in the lookback, `SCREEN/NAV` = run date. Example for `observation latest value`:

```sql
WITH obs AS (
  SELECT pid, index_date, value_num, unit, effective,
         row_number() OVER (PARTITION BY pid, index_date ORDER BY effective DESC) rn
  FROM observation o CROSS JOIN idx
  WHERE o.system = ? AND o.code IN (SELECT code FROM vs WHERE vs_id = ?)
    AND o.effective BETWEEN idx.index_date + INTERVAL (?) DAY AND idx.index_date + INTERVAL (?) DAY)
SELECT pid, index_date, (value_num >= ?) AS hit, effective::VARCHAR AS evidence FROM obs WHERE rn = 1
```

Medication continuous exposure: gaps-and-islands over `medication(start,end)` with `gap_days`. Derived values computed in SQL with the same formulas as CQL helpers (shared constants file).

### 6.4 Equivalence test (gate)

On every compile: sample 200 patients (stratified: 100 random, 100 with any hit), evaluate each criterion by CQL (fhir-store) and SQL (lake) at the same index date; require per-criterion agreement ≥98% treating `null` as a distinct value; print disagreements with evidence. Failing criteria are flagged `needs_review` and block approval.

## 7. LLM prompts, schemas, guards

Prompts live in `services/*/prompts/<id>_v<n>.md` with YAML front matter `{id, version, model_class: cloud|local, output_schema}`. All calls go through `tb_common.llm.chat_json`. Temperature 0. Max output 2k tokens except `ir_extract` (8k).

### 7.1 `ir_extract` (cloud or local 120B; no PHI)

System: "You convert clinical eligibility text into CriterionIR JSON. Output only JSON matching the schema. For each criterion decide `class`: `structured` if it can be decided from coded diagnoses, labs, medications, procedures, demographics or claims; `note` if it needs free-text clinical narrative (e.g. clinician-assessed flare, radiographic description); `human` if it needs patient or clinician input not in records (willingness, ability to self-inject, plans). Prefer `structured` with a `fallback` over `note`. Use windows relative to index date. Mark `time_sensitive=true` when the criterion depends on events within 90 days of index. Never invent codes; put candidate concept names in `concept_candidates`."

User: the I/E block text + ruleset id + language. Output schema: `llm_extract_output.schema.json` = `{criteria:[CriterionIR without valueset ids, plus concept_candidates:[{domain, name, synonyms[]}]]}`.

### 7.2 `concept_map` (cloud or local; no PHI)

Input: concept name + domain + top-20 candidates from terminology tables (code, display). Output: `{choices:[{code, system, confidence}], needs_review: bool}`. Any choice with confidence <0.9 or any multi-choice is `needs_review`.

### 7.3 `judge` (local only; PHI)

System: "You decide one eligibility criterion for one patient from note excerpts. Answer only from the excerpts. If the excerpts do not contain enough information, answer `unknown`. Quote the exact sentence that supports your verdict and give its date. Do not infer from absence."

User: `{criterion_text, note_question, index_date, excerpts:[{date, note_type, text}]}`. Output schema `llm_judge_output.schema.json`:

```json
{"type":"object","required":["verdict","confidence"],
 "properties":{
  "verdict":{"enum":["pass","fail","unknown"]},
  "quote":{"type":"string","maxLength":400},
  "quote_date":{"type":"string","format":"date"},
  "confidence":{"type":"number","minimum":0,"maximum":1},
  "reason":{"type":"string","maxLength":300}}}
```

Post-processing: `quote` must be a substring of one excerpt (exact match after whitespace normalization) else verdict forced to `unknown` with reason `quote_not_found`. Confidence < `thresholds.tier_high_confidence` → tier `review`.

### 7.4 PHI guard (before any cloud call)

Regex + dictionary scan of the full text: Taiwan ID `^[A-Z][12]\d{8}$`, MRN patterns from `settings.mrn_regex`, dates of birth near name-like tokens, phone numbers, ROC/Japanese name dictionaries (top 5k surnames + given-name heuristics), `病歷號|身分證|姓名`. Any hit → cloud disabled for this job, local 120B used, and audit records `phi_guard_hit=true`. Protocols rarely trip; sponsor question lists sometimes include example patients and must.

### 7.5 RAG for note criteria

For each candidate and each `note` criterion: query = `note_question` + criterion keywords (from IR `text`, translated to zh-TW/ja terms table); window = `[index-365d, index]` unless IR window narrower; retrieve k=5 via lake `/chunks/search`; drop chunks older than window; order by date desc; total context ≤ 2,500 tokens. Full-record fallback: if candidates ≤100, send all notes in window (truncate to 28k tokens, newest first) instead of chunks.

### 7.6 `draft_doc` (local only; PHI)

Fills an application template (Jinja2 docx) with structured fields; the LLM is used only to produce the free-text "clinical course" paragraph (≤150 words) from provided facts, with the constraint to mention only facts in the input JSON. Output schema `{paragraph: string}`; post-check that every number in the paragraph appears in the input facts.

## 8. Scenario workflows

All scenarios are implemented as `orchestrator/scenarios/<name>.py` with `run(job: Job) -> OutputBundle`, pure functions over services; every step writes `job.state` and an audit line. Pseudocode below is normative.

### 8.1 FEAS

```
parse = doc_parser.parse(inputs)                       # state parsing
if ruleset has approved tag and no new doc: ir = load(tag) else:
    draft = compiler.compile(job, parse, options)       # state compiling
    send review; state awaiting_approval; return        # resumes on APPROVE
scope = population(manifest.scopes.feas)                # hospital|dept, lookback
funnel = lake.run_sql(ruleset.sql, index=month_ends(lookback), scope)   # state running
   # ordered by manifest criterion order; remaining/dropped per step
sens = for variant in options.variant: rerun with overridden thresholds
monthly_new = count(patients first meeting all structured criteria in month m)
sim = simulate(monthly_new, reach=cal.reach or 0.6, accept=cal.accept or 0.35,
               capacity=sum(practitioner capacity) or None, months=12)  # low/mid/high via beta draws, 1000 iters
result = FeasibilityResult(...); apply small_cell suppression (<5 → "<5")
outputs = [feasibility_pdf, feasibility_xlsx, feasibility_result.json]   # tag aggregate
send(routing.aggregate_to)
```

### 8.2 SCREEN (one-shot) and MICROBATCH (weekly)

```
require approved ruleset tag
scope_pids = lake.sql("SELECT DISTINCT pid FROM appointment WHERE practitioner_id IN ? AND start BETWEEN run_date AND run_date+window AND status='booked'")
        ∪ (encounter in last 12 months with those practitioners)      # include recent patients without booking yet
structured = for pid in scope_pids (8 workers): fhir.evaluate(library, pid, IndexDate=run_date)
   # returns C_<ID>, E_<ID>
candidates = [p for p in scope if all(C_INC structured in {true,null}) and none(C_EXC structured == true)]
for p in candidates, for c in note_criteria:
    excerpts = lake.chunks_search(p, c.note_question, window(c))
    verdict = llm.judge(c, excerpts)                                    # 7.3
if len(candidates) <= 100: rerun note criteria with full-record fallback for verdicts == unknown
tier(p) = high if all(C_INC in {true}) and none(C_EXC true) and all(note verdict pass with conf>=t) and human pending
        = review if any unknown / low confidence
        = excluded otherwise (not listed)
rows sorted by next_appointment asc, then tier
outputs = [candidate_xlsx (phi), referral_xlsx per external dept (phi), candidate_list.json (phi), summary.pdf (aggregate)]
send lists to routing.list_to; referrals to routing.referral_to[dept]; summary to aggregate_to
persist candidate pool to jobs.sqlite (ruleset, pid, tier, last_eval)
```

MICROBATCH (Mon 03:00, for every ruleset with an active pool): `pool ∩ appointments in next 14 days` → re-evaluate only criteria with `time_sensitive=true` (structured via CQL; note via judge) → output `this_week_visit1.xlsx` (phi) with changed verdicts highlighted → send to `list_to`. Incident patients (new in scope since last run) are appended to the pool monthly (first Monday).

FEEDBACK: CRC replies with `screen_feedback.csv`; orchestrator ingests to `feedback` table; monthly `calibration.py` recomputes `reach_rate`, `accept_rate`, screen-fail reasons per criterion → `calibration.json` used by FEAS simulation and attached to the monthly sponsor summary.

### 8.3 COHORT

```
for disease in manifest.diseases: ruleset = cohort ruleset (approved)
   table = lake.sql(counts per criterion and per criterion-combination, index=quarter_end, population=disease cohort)
   registry = join with consent registry (settings.registry_source) → contactable counts
   recruiting = clinicaltrials.gov API v2: /studies?query.cond=<disease>&filter.overallStatus=RECRUITING&query.locn=Taiwan|Japan
   for top-N trials: ir = compiler.compile(eligibilityModule text)  # cloud ok, no PHI; cached by NCT id + lastUpdate
                     sim = FEAS.simulate(...)
outputs = [cohort_table.csv (alliance schema v1), cohort_report.pdf, trial_sim.xlsx]  # aggregate
merge: alliance root box accepts cohort_table.csv from member boxes by email (COHORT MERGE), validates schema, outputs merged table
```

Alliance schema v1: `site_id, disease, quarter, criterion_id, criterion_label, n, n_contactable, definition_version`. Small-cell suppression before leaving the box.

### 8.4 NAV (weekly)

```
for ruleset in nhi rulesets (approved): 
  scope = patients with appointment in next 14 days in departments
  structured + note evaluation as in SCREEN with IndexDate=run_date
  lists:
    likely_eligible = eligible_structured (and note pass) and no active approval (claim.approval_end >= today) and no application in last 90 days
    renewal_due     = active approval with approval_end within renewal_lead_days; evaluate renewal criteria (kind=renewal)
    doc_gaps        = for both lists: documentation criteria (kind=documentation) that are unknown → missing items with suggested orders
    maybe_ineligible= active approval and renewal criteria fail with confidence >= t
  for each row in likely_eligible ∪ renewal_due:
    draft = reports.docx_draft(template(ruleset), facts)                 # 7.6
    if ruleset.twpas: bundle = reports.twpas_bundle(facts); validate (HL7 validator, 0 errors); precheck = fhir.evaluate(NHI CQL library)
outputs = [nav_lists.xlsx (phi), drafts/*.docx (phi), bundles/*.json (phi), nav_summary.pdf (aggregate)]
send to routing.list_to (nurse, physician)
```

TWPAS upload is never automatic: physician replies `SUBMIT <ruleset> pid=<pid> bundle=<key>` (allowed senders = physicians in settings); orchestrator posts the bundle to `NHI_TWPAS_BASE_URL` and stores `ClaimResponse`.

## 9. Report and document specifications

All documents carry a footer: `TrialBox <site> · ruleset <id> v<ver> · model <name> · snapshot <date> · job <id>`. Fonts: Noto Sans CJK TC/JP embedded. Templates in `orchestrator/reports/templates/`.

### 9.1 Feasibility PDF (`feasibility_pdf`)

1. Cover: trial alias, sponsor, site, run date, population and lookback, contact.
2. One-paragraph answer: estimated 12-month enrollment range (low/mid/high) and the two biggest barriers.
3. Funnel table and horizontal bar chart (matplotlib, PNG): rows in criterion order, columns remaining / dropped / % of start; small cells shown as `<5`.
4. Sensitivity table: each variant with remaining count and delta vs base.
5. Monthly new-eligible line chart (24 months).
6. Simulation assumptions table: reach, accept, capacity, source (calibrated or default).
7. Criterion definitions appendix: id, protocol text, how computed (data source, codes, window, fallback), class; `human` and `note` criteria listed as "not applied in counts".
8. Site capability section: static text from `settings.site_capabilities` (lab, imaging, pharmacy, injection training, eDiary support).

Excel companion: sheets `funnel`, `sensitivity`, `monthly`, `criteria`, `assumptions`.

### 9.2 Candidate Excel (`candidate_xlsx`, tag phi)

Sheet `candidates` columns: `MRN` (resolved from pid map, internal only), `tier`, `next_appointment`, `practitioner`, `department`, then one column per criterion `C_<ID>` with values `pass|fail|unknown|pending` and cell comment holding the evidence quote and date, `n_unknown`, `actions` (e.g. "confirm flare date", "order creatinine", "ask injection willingness"), `last_evaluated`. Conditional formatting: tier high = green, review = yellow. Sheet `criteria` = definitions. Sheet `feedback` = pre-filled template for `screen_feedback.csv`. Sheet `changes` (microbatch only) = verdict changes since last run.

### 9.3 NAV lists (`nav_xlsx`, tag phi)

One workbook per department: sheets `likely_eligible`, `renewal_due`, `doc_gaps`, `maybe_ineligible`, each with `MRN, next_appointment, practitioner, approval_end (if any), criteria columns, missing_items, suggested_orders, draft_file, bundle_file, precheck_result`. Row order: appointment date ascending.

### 9.4 Application draft (`docx_draft`)

Jinja2-docx template per ruleset (e.g. `RA-BIO/附表十五.docx`) with named fields: patient identifiers (internal), diagnosis and date, DMARD table (name, dose, start, end, duration), prednisolone dose, DAS28 at required time points with component values and dates, infection/TB/HBV screening results and dates, exclusions checklist, clinical course paragraph (7.6). Unknown fields rendered as highlighted `[待補]`. Never auto-signed.

### 9.5 TWPAS Bundle (`twpas_bundle`)

Build per IG `tw.gov.mohw.nhi.pas` version pinned in `settings.twpas_version` (default 1.2.5): `Bundle(type=collection)` containing `Claim` (prior-auth request, `priority` per application category), `Patient`, `Coverage`, `Practitioner`/`Organization`, `MedicationRequest` (apply item), `Condition`, supporting `Observation` (staging, assessment items from the IG's CodeSystem), `DiagnosticReport`/`DocumentReference` as the IG requires. Use `fhir.resources` models; validate with the HL7 validator against the IG package (`-ig tw.gov.mohw.nhi.pas#<ver>`), require 0 errors; run NHI's published CQL pre-check library when available for the drug; store bundle + validator output + precheck result in MinIO. Reference implementation to port from: `tm731531/nhi-pas-fhir`.

### 9.6 Review package (`review_html`, `review_xlsx`)

HTML table per criterion: id, source text, IR summary in plain language ("Latest BMI within 90 days ≥ 27"), class, codes with display names, window, fallback, equivalence result, flags (`needs_review`). Excel with decision columns for the approver.

## 10. Security, audit, retention, configuration

### 10.1 Security controls (all mandatory)

| Control | Implementation |
| --- | --- |
| Network egress | nftables on host: default DROP for all containers; allow `mail-gateway` → `SMTP_HOST:587/465` and `IMAP_HOST:993`; allow `criteria-compiler` → `CLOUD_LLM_BASE_URL` host only when set; allow `orchestrator` → `NHI_TWPAS_BASE_URL` only when set; everything else (package registries, model hubs) blocked at runtime |
| Updates | Offline bundles signed with the vendor Ed25519 key: `models/*.safetensors`, `rulesets/*.zip`, container images as tar; `tools/apply_update.sh` verifies signature + sha256 before loading; no auto-update |
| Secrets | `.env` readable by root only; S/MIME certs and site HMAC key in `secrets/` with 0600; `pid_map.sqlite` encrypted with SQLCipher key from TPM-sealed file |
| Disk | LUKS full-disk encryption; swap disabled |
| Mail | Sender allowlist + SPF/DKIM; replies never echo attachment contents; outbound PHI attachments encrypted (7z AES-256 or S/MIME); recipient domain check |
| Data minimisation | Lists carry MRN only inside the box's internal routing; aggregate outputs suppress cells <5; note excerpts never leave the box |
| LLM isolation | `llm-service` has no network except from internal services; cloud calls only through the PHI guard in `criteria-compiler` |
| Logging | No PHI in logs (pids only); log retention 180 d |
| Users | None. Authorisation = sender address + command permissions in `settings.permissions` (e.g. only physicians may `SUBMIT`) |

### 10.2 Audit log

`audit/YYYY-MM-DD.jsonl`, one line per event: `{ts, event, job_id, ruleset, ruleset_version, model, prompt_version, snapshot, actor (sender), input_sha, output_sha, recipients, prev_hash, hash}` where `hash = sha256(prev_hash + line_without_hash)`. Daily file hash chained to previous day. `tools/audit_verify.py` recomputes the chain. Export is a plain copy of the files.

### 10.3 Retention

| Data | Retention | Mechanism |
| --- | --- | --- |
| Inbound attachments | 90 d | `retention` job deletes MinIO objects; audit keeps sha |
| Outputs (reports, lists, drafts) | 365 d | same |
| FHIR store and lake | rolling snapshots: keep last 3 nightly, plus month-end for 36 months | adapter prunes |
| Candidate pools and feedback | life of ruleset + 24 months | sqlite |
| Audit | 10 years | append-only, backed up to hospital share nightly |
| Rulesets | forever (git) | — |

### 10.4 `settings.yaml` schema (abridged)

```yaml
site: {id: CGMH-LK, name: "林口長庚", tz: Asia/Taipei, locale: zh-TW}
internal_domains: ["cgmh.org.tw", "adm.cgmh.org.tw"]
allowlist:
  senders: ["crc1@cgmh.org.tw", "pi@cgmh.org.tw"]
  physicians: ["pi@cgmh.org.tw"]          # may SUBMIT
permissions: {FEAS: [senders], SCREEN: [senders], NAV: [senders], APPROVE: [reviewers], SUBMIT: [physicians]}
reviewers: ["crc1@cgmh.org.tw"]
data_source: {type: cgrd_sql, dsn_env: CGRD_DSN, mapping: mapping/tw_core/cgmh.yaml, nightly_at: "02:00"}
mrn_regex: "^\\d{8}$"
profiles: {tw_core: "1.0.0", twpas_version: "1.2.5"}
models: {judge: qwen3.5-35b-a3b-q4, extract_local: gpt-oss-120b-mxfp4, embed: bge-m3, cloud_enabled: false}
thresholds: {tier_high_confidence: 0.75, small_cell: 5, equivalence_min_pct: 98}
schedule: {ingest: "02:00", microbatch: "MON 03:00", nav: "MON 03:30", cohort: "1st 04:00"}
site_capabilities: {fundus_photography: true, injection_training: true, cold_chain: true, ediary_support: true}
registry_source: {type: sql, dsn_env: REGISTRY_DSN}   # consent-to-contact
attachment_encryption: zip   # zip|smime
```

Schema file `schemas/settings.schema.json`; `tb_common.config.load()` validates at startup and refuses to start on error.

## 11. Testing, acceptance, performance

### 11.1 Test layers (CI must pass all; `make test`)

| Layer | What | Fixtures |
| --- | --- | --- |
| Unit | IR schema validation; IR→CQL and IR→SQL snapshot tests for every atom type and bool combination; derived calculators (BMI, eGFR CKD-EPI 2021, DAS28-ESR/CRP) against published examples; subject grammar parser; PHI guard; routing enforcement; small-cell suppression | `tests/fixtures/ir/*.json` |
| Integration | compile → translate (cql-translator) → load Library into a test HAPI → `$evaluate` on synthetic patients; lake rebuild from NDJSON; equivalence gate; mail-gateway against a local IMAP/SMTP (GreenMail or MailHog) | `tests/fixtures/synthetic_patients/*.ndjson` (≥500 synthetic patients generated by `tools/make_fixtures.py` to cover every criterion branch, zh-TW notes included) |
| LLM | `judge` on a labelled set of 300 (excerpt, criterion, verdict) triples; `ir_extract` on 5 public protocols (ClinicalTrials.gov eligibility text) with gold IR; `concept_map` on 200 concepts | `tests/fixtures/llm/` |
| E2E | send `FEAS GZQO` email → receive PDF; `APPROVE` loop; `SCREEN` → candidate Excel; `NAV RA-BIO` → lists + docx + bundle validated | docker compose test profile |
| Performance | section 11.3 targets on reference hardware | `tools/bench.py` |

### 11.2 Acceptance criteria (site go-live, per scenario)

| Scenario | Criterion | Target |
| --- | --- | --- |
| Ingest | Nightly run completes; HL7 validator sample errors | <0.5% |
| FEAS | Funnel vs manual CGRD count for a reference protocol (GZQO) | each step within ±15% and every difference explained by a documented definition choice |
| SCREEN | Trial-level vs blinded CRC adjudication (≥100 pairs, 4-strata sampling) | sens ≥75% / spec ≥95% at default tier; sens ≥95% at review tier |
| SCREEN | Criterion-level agreement (structured / note separately) | structured ≥98%; note ≥90% |
| SCREEN | CRC verification time per candidate | ≤10 min |
| NAV | Retrospective 12 months: system verdict vs actual NHI outcome | agreement ≥85% on approvals; zero cases where system says eligible while a hard exclusion is coded |
| NAV | TWPAS bundles | 0 validator errors; NHI CQL pre-check passes on test set |
| All | Reproducibility: same inputs + same versions → identical output hashes | 100% |
| All | Audit chain verifies | pass |

### 11.3 Performance targets (reference: x86, 1× 32 GB GPU; GB10 within 2×)

| Job | Size | Target |
| --- | --- | --- |
| Ingest | 50k patients delta/night | ≤2 h |
| FEAS | hospital 300k patients × 36 month-ends × 25 criteria | ≤30 min |
| SCREEN | 1,000 scoped × 25 criteria (CQL) + 300 × 5 note criteria | ≤3 h |
| MICROBATCH | 100 patients × 5 time-sensitive criteria | ≤10 min |
| NAV | 500 patients × 15 criteria + 50 drafts + 50 bundles | ≤1 h |
| Compile | 25-criterion protocol incl. equivalence test | ≤20 min |

### 11.4 Model/ruleset change control

Any change to `models/manifest.yaml`, a prompt version, or a ruleset tag triggers the LLM layer and the acceptance subset (SCREEN 100 pairs, NAV retrospective) and blocks deployment if any target regresses by more than 3 points.

## 12. Implementation order and Definition of Done

Build in this order; each phase is independently runnable and tested before the next starts. A coding agent should treat each phase as one task with the DoD as its acceptance test.

| Phase | Deliverable | Definition of Done |
| --- | --- | --- |
| 0 Skeleton | Monorepo layout, `schemas/` with all JSON Schemas, `libs/tb_contracts` generated (datamodel-code-generator), `tb_common` (config, logging, audit hash chain, ulid), compose file with all services stubbed (`/healthz`), `make up/test/lint` | `docker compose up` healthy; `make test` runs unit tests for config and audit chain |
| 1 Data | `adapter` with `csv` and `cgrd_sql` sources, `mapping/tw_core/*.yaml`, NDJSON writer, HAPI loader, HL7 validator sampling, `lake` rebuild + `/query` + `/chunks/search` with embed-service | 500 synthetic patients ingested; validator sample 0 errors; `/chunks/search` returns correct chunk for 20 seeded queries |
| 2 Compiler | `doc-parser` (Docling + I/E heuristics), `criteria-compiler` IR extraction via `ir_extract` (local 120B or cloud flag), terminology tables + `concept_map`, IR→CQL + translator, IR→SQL, equivalence gate, Git ruleset repo, review package | GZQO protocol compiles to ≥20 criteria; equivalence ≥98% on synthetic set; `review.xlsx` round-trips through `/approve` |
| 3 FEAS | `mail-gateway` (IMAP/SMTP, grammar, allowlist, routing), orchestrator job queue, `feas.py`, feasibility PDF/XLSX, simulation | E2E: email `FEAS GZQO` → PDF received within 30 min on synthetic data; manual-vs-system funnel test harness in place |
| 4 SCREEN | `screen.py` with CQL per-patient evaluation, RAG + `judge`, tiers, candidate Excel, referral split, pool persistence, `MICROBATCH`, feedback ingest, `calibration.py` | E2E on synthetic: candidate list produced; judge test set agreement ≥90%; microbatch changes sheet correct on seeded changes |
| 5 NAV | `nav.py`, RA-BIO ruleset (criteria from NHI 給付規定 + 附表十五), renewal timers from `claim`, docx drafts, lists | Retrospective harness runs on synthetic claims; drafts open in Word with `[待補]` markers |
| 6 TWPAS | `twpas_bundle` builder for one cancer-drug program, validator integration, NHI CQL pre-check loader, `SUBMIT` command (dry-run mode) | 10 synthetic bundles validate with 0 errors against `tw.gov.mohw.nhi.pas#1.2.5` |
| 7 COHORT | `cohort.py`, alliance schema, ClinicalTrials.gov fetch + compile cache, merge command | Two synthetic sites merge into one table; trial simulation for 3 NCT ids |
| 8 Hardening | nftables egress script, signed offline update tool, retention job, LUKS/TPM notes, `docker-compose.gb10.yml` with pinned images and driver note, bench script | Egress test: all blocked except allowlist; `apply_update.sh` rejects tampered bundle; bench meets 11.3 on x86 |
| 9 Site onboarding kit | `settings.yaml` wizard (CLI), mapping YAML template per source, runbook `docs/RUNBOOK.md`, acceptance test scripts for 11.2 | A new site can be configured without code changes |

**Non-negotiables for the implementer**: no LLM-generated SQL/CQL at runtime; no PHI to any endpoint outside the box except NHI on explicit `SUBMIT`; every output file hashed and audited; schemas are the contract — change a schema only by bumping its version and regenerating models.

### 12.1 Site-specific parameter file (to be filled before phase 1)

```yaml
# site_params.yaml — fill in before implementation
his:
  source_type: cgrd_sql | csv | fhir_bulk | ssmix2
  dsn: "<read-replica DSN>"
  tables: {patient: ..., encounter: ..., appointment: ..., diagnosis: ..., lab: ..., medication: ..., procedure: ..., note: ..., claim: ...}
  code_systems: {diagnosis: ICD10CM-TW, drug: NHI, lab_local_to_loinc: "<csv path>", order: NHI}
  note_types_available: ["progress", "admission", "discharge", "consult", "nursing"]
  height_weight_source: "<table/column>"
mail: {imap_host: ..., smtp_host: ..., intake_addr: ..., from_addr: ...}
people:
  reviewers: [...]
  physicians: [...]
  practitioner_ids_by_name: {"郭昶甫": "P12345"}
nhi:
  twpas_enabled: false
  twpas_test_env: "<url>"
  rule_documents: ["RA生物製劑給付規定_2026.pdf", "附表十五.pdf"]
hardware: {gpu: "RTX 5090 32GB" | "GB10", ram_gb: 128, disk_tb: 4}
```

### 12.2 Open decisions deliberately left to the implementer

- Exact Docling vs marker choice after testing on 5 Chinese PDFs (pick the one with better table recall).
- HAPI CR `$evaluate` vs `Measure/$evaluate-measure` for batch evaluation (choose whichever meets 11.3; keep the other behind a flag).
- 7z vs S/MIME default (site mail policy decides).

## Appendix: references used by this spec

- [NHI TWPAS IG v1.2.5 (production spec)](https://nhicore.nhi.gov.tw/pas/) · [TWPAS CI build 1.2.6 notes](https://build.fhir.org/ig/TWNHIFHIR/pas/) · [NHI pre-check rules IG (CQL) v0.0.1](https://build.fhir.org/ig/TWNHIFHIR/cql/index.html) · [nhi-pas-fhir reference implementation](https://github.com/tm731531/nhi-pas-fhir)
- [TW Core IG 1.0.0](https://build.fhir.org/ig/TU9IVy1UV0NvcmVJRw/VFcgQ29yZSBJRyBJVFJJ/) · [JP Core MedicationRequest (CLINS)](https://jpfhir.jp/fhir/core/latest/StructureDefinition-JP_MedicationRequest)
- [NHI RA biologics application form 附表十五](https://www.nhi.gov.tw/ch/dl-42665-a6866a208a9d411ba3660d732626fbc5-1.pdf) · [MOHW: RA biologic tapering threshold DAS28 <2.6](https://www.mohw.gov.tw/cp-16-46524-1.html)
- [cqf-ruler / HAPI Clinical Reasoning](https://github.com/cqframework/cqf-ruler) · [cql\_engine 2.4.0](https://github.com/dbcg/cql_engine) · [Firely CQL SDK 2.9.0](https://github.com/FirelyTeam/firely-cql-sdk)
- [Criteria2Query 3.0](https://pmc.ncbi.nlm.nih.gov/articles/PMC11129920/) · [TrialGPT 2.0](https://github.com/TrialGPT2/TrialGPT2.0) · [RECTIFIER RCT, JAMA 2025](https://jamanetwork.com/journals/jama/fullarticle/2830514)
- [DGX Spark 2026 guide (vLLM 0.24, MoE vs dense)](https://ai-muninn.com/en/blog/dgx-spark-2026-current-guide) · [spark-vllm-docker wheels (NVIDIA forum)](https://forums.developer.nvidia.com/t/running-a-full-llm-stack-on-dgx-spark-gb10-your-application-litellm-llama-swap-vllm-llama-cpp-ollama/367580) · [GB10 driver regression note](https://github.com/r0b0tlab/deepseek-v4-flash-nvfp4-gb10-benchmark)
- [Open-weight model landscape 2026 (Qwen3.5/3.6, Gemma 4, gpt-oss)](https://www.contextstudios.ai/guides/best-open-weight-llms-2026) · [GPT-OSS-Swallow-20B](https://huggingface.co/tokyotech-llm/GPT-OSS-Swallow-20B-RL-v0.1)
- Companion documents: [深度規劃書](https://claude.ai/code/artifact/5704b7d2-c78d-45dc-b498-7902f1d7c535) · [架構 v2](https://claude.ai/code/artifact/4631478f-bad5-4f91-8154-99c6fe8ce0b3) · [技術評估 vs Lind](https://claude.ai/code/artifact/45a9e2b7-5f1c-4242-8b81-661058aadb0d)
