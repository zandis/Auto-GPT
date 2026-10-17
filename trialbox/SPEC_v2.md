# SPEC — TrialBox v2: The Trial Agent

Version 2.0-draft · Oct 17, 2026 · @Changfu · supersedes nothing: v1.0 (`SPEC.md`, Oct 4, 2026) stays the build contract for the
v1 appliance; this document specifies what v2 adds and changes.

This is the single build specification for TrialBox v2. Like v1, it is written so that one engineer or one coding agent can
implement the system without further design decisions. Every requirement has an identifier, a verification method and a
release. Section 15 lists the first sprint as concrete tasks against the existing repository.

**How to read it**

| You are | Read |
| --- | --- |
| Hospital leadership, research office | §1 (where we are), §2 (product), §3 (the experience), §14 (positioning and value) |
| Investigator, coordinator | §3 (the experience), §6 (what the agent does at each lifecycle stage) |
| Engineer or coding agent | everything; build from §5–§13 and the first sprint in §15 |
| QA, IRB, information security | §2.4 (intended use), §10 (security, privacy, compliance), §11 (verification and validation) |

**Conformance language.** MUST, MUST NOT, SHOULD, MAY as in RFC 2119/8174. Requirements are numbered `FR-<module>-<n>`
(functional), `NFR-<n>` (non-functional), `SEC-<n>`, `CMP-<n>` (compliance), `AI-<n>`; each states its verification
(`T` test, `I` inspection, `A` analysis, `D` demonstration) and its release (`R1`–`R4`, §15).

**Companion documents.** `docs/LANDSCAPE.md` (competitive landscape, literature, brainstorm), `SPEC.md` (v1 build
contract), `docs/DECISIONS.md` (decision log, continued as ADRs here), the public research notes listed in Appendix F.

---

## 1. Where we are

### 1.1 The v1 proof of concept

TrialBox v1 is built and tested end to end. An audit against `SPEC.md` at commit `080d298` (Appendix F, `poc_status.md`)
gives:

| v1 goal | Built against spec | Verified on real data |
| --- | --- | --- |
| G1 FEAS (feasibility funnel, sensitivity, 12-month estimate) | ≈95 % | 0 % |
| G2 SCREEN / MICROBATCH (two-tier candidate list, weekly re-check) | ≈90 % | 0 % |
| G3 COHORT (quarterly tables, alliance merge, trial simulation) | ≈90 % | 0 % |
| G4 NAV + TWPAS (NHI navigation, prior-authorisation bundles) | ≈80 % | 0 % |
| G5 reproducibility and audit | ≈90 % | n/a |

What exists and works (synthetic data, stub LLM): ten services in docker compose; email intake with sender
authentication; a declarative HIS→FHIR adapter with pseudonymisation; a DuckDB lake with CJK note search; a criteria
compiler that turns protocol text into a Criterion IR, ValueSets, CQL and SQL from templates and proves CQL≡SQL on a
sample; a note judge with a verbatim-quote check; deterministic PDF/XLSX/DOCX reports; a hash-chained audit log;
byte-identical re-runs; egress firewall, signed updates, retention. Test state on the latest head: lint clean, 286 unit
tests, 59 integration, 6 end-to-end and the root egress test pass; a Windows (WSL2) rerun is pending.

What has never touched reality: real patients, a real LLM (all calls hit a deterministic stub), real protocols (GZQO is a
synthetic excerpt; RA-BIO and ONC-OSI are fictional NHI rules), full terminology tables (60 ICD codes, 25 drugs), the
Docling and bge-m3 images, a database driver for the CGMH HIS/CGRD, model change control (v1 §11.4) and the v1 §11.2
go-live checks.

### 1.2 What we learned

1. **The deterministic core is the asset.** Template-generated CQL/SQL with an equivalence gate, per-criterion evidence,
   quote-checked note judging, and an audit chain are exactly what regulators (ICH E6(R3) Annex 1 §4) and sponsors ask
   for. v2 keeps them and puts an agent in front of them, not in place of them.
2. **Email-only, batch-only was right for trust and wrong for reach.** Coordinators need to clarify criteria, approve
   mappings and confirm patients in seconds. v2 keeps email as the default channel and adds a conversational agent and a
   minimal approval console.
3. **Data onboarding is the real bottleneck.** Experience with external screening platforms in Taiwanese hospitals is
   that months go to EHR access, data exports, de-identification and remote-access arrangements, and that hospital data
   staff end up doing the extraction. v2 makes onboarding a first-class module (M0) that runs inside the hospital and learns
   the data itself.
4. **Feasibility and abstraction are where staff time goes.** Sites answer about 11 sponsor feasibility questionnaires a
   month at about 4 hours each, and 81 % call them redundant (ASCO/AACI 2020, Appendix F). eCRF abstraction for retrospective
   studies shows the same pain on the data-entry side: fields that are temporal or free-text still need manual review. v2 automates both, with provenance on every number.
5. **Validation needs real enrollment logs, which only the hospital holds.** v2 builds the validation study (historical
   enrollee capture, criterion-level accuracy, PI agreement) into the product (§11.4).

### 1.3 What v2 changes

| Area | v1 | v2 |
| --- | --- | --- |
| Interaction | Email commands with a strict subject grammar | Email in natural language plus the grammar; Teams/LINE notifications; a small web console for approvals, evidence and configuration |
| Orchestration | SQLite queue, 4 threads, APScheduler | Durable workflows on PostgreSQL (DBOS), with human gates as workflow signals; agent steps inside workflows |
| Lifecycle | Feasibility, screening, cohorts, NHI navigation | All of v1 plus protocol digitisation and optimisation, sponsor questionnaire autofill, portfolio-wide pre-screening, patient→trial matching, enrollment tracking with forecasting, start-up and conduct copilots, eCRF abstraction, safety and deviation surfacing, close-out and registry deadlines |
| Data onboarding | Hand-written mapping YAML | Data Atlas: automatic profiling of the HIS/CGRD, proposed mappings, coverage and computability scores, research-office confirmation |
| Criteria | IR v1 (no event anchors, sequences, trends or counted events) | IR v2 with event-anchored windows, temporal sequences, counts, trends, lines of therapy and value comparisons on every domain; CQL≡SQL kept |
| Models | One local model, stub in tests | Model registry with pinned weights, a portfolio (planner, verifier, router, extractor), dual-model verification, an evaluation gate on every change |
| Learning | Calibration from screening feedback | A site-learning loop: PI decisions, consent and randomisation outcomes recalibrate criteria, tiers and forecasts |
| Validation | Synthetic acceptance scripts | A built-in real-data validation study and an AI credibility file per AI function |

### 1.4 Design principles

P1 **The agent proposes, compiled rules execute, people sign.** LLMs interpret and draft; numbers, lists and regulated
records come from deterministic, versioned code and are released only after a named person approves.
P2 **Evidence or it did not happen.** Every count, tier and field carries its provenance: rule version, data snapshot,
source record, quote.
P3 **The hospital keeps the data.** PHI never leaves the box; sponsors see aggregates with small cells suppressed.
P4 **No new screen unless it saves a click.** Work arrives and leaves by email; the console exists for approval,
evidence and configuration.
P5 **Learn the site, not just the protocol.** The box gets better at this hospital with every study it runs.
P6 **Same answer twice.** Any output can be regenerated byte-for-byte from its manifest.
P7 **Standards in, standards out.** M11/USDM, FHIR R4/TW Core, OMOP, CDISC ODM/CDASH, CQL; no proprietary lock-in.

---

## 2. Product definition

### 2.1 Vision

An on-prem clinical-trial agent that a research coordinator can email a protocol to and get back, within the hour, a
sponsor-ready feasibility answer and, once the study is approved, a weekly list of candidate patients with chart evidence
for the investigator, followed by enrollment tracking and conduct support until close-out. It runs inside the hospital,
needs no new screens for daily use, and gets measurably better at the site over time.

### 2.2 Users and roles

| Role | Typical person | Main jobs with TrialBox | Access |
| --- | --- | --- | --- |
| Research coordinator (CRC) | Study coordinator, research nurse | Send protocols and feasibility questionnaires, approve criteria mappings, review candidate evidence, record contacts and consent | PHI for studies they are delegated on |
| Principal investigator (PI), sub-investigator | Attending physician | Confirm or reject candidates, approve outgoing feasibility answers, receive weekly lists | PHI for their studies |
| Research office / Clinical Trial Center | CTC manager, feasibility desk | Site profile, portfolio dashboard, sponsor communication, onboarding approvals | Aggregates across studies; PHI only with a delegation |
| Data steward | Medical-informatics staff (e.g. CGRD team) | Data Atlas confirmation, mapping, terminology, data-quality issues | Metadata and samples under IRB approval |
| Sponsor / CRO (external) | Feasibility manager, study manager | Receive questionnaire answers, enrollment summaries | Aggregates only, by email from the site |
| IRB / QA / information security | Reviewers, auditors | Audit trail review, validation evidence, access recertification | Read-only audit and reports |
| System administrator | Hospital IT | Install, update, monitor, back up | No PHI by default |
| Agent | TrialBox itself | Act on behalf of a named user within that user's permissions | Never more than the requesting user |

### 2.3 Scope by lifecycle stage

The agent covers the site-side clinical-trial lifecycle. Each stage maps to a module (§6) and a release (§15).

| # | Stage | What TrialBox does | Module | Release |
| --- | --- | --- | --- | --- |
| 0 | Site readiness | Learns the EMR (Data Atlas), keeps the site master profile, measures data freshness and coverage | M0 | R1 |
| 1 | Protocol intake | Parses protocol (PDF/DOCX/M11/USDM), extracts I&E and schedule of activities, flags ambiguity, asks clarifying questions | M1 | R1 |
| 2 | Protocol optimisation | Criterion impact, what-if relaxation, comparison with the site population (internal or sponsor request) | M2 | R2 |
| 3 | Feasibility | Per-criterion counts, funnel, enrollment projection, competing trials, investigator suggestions; autofills the sponsor questionnaire | M3 | R1 |
| 4 | Site selection support | Site profile, start-up timelines, past performance, ready-to-send qualification pack | M3 | R2 |
| 5 | Start-up | Activation checklist, schedule of activities → site calendar, NHI coverage analysis (standard of care vs research-only) | M7 | R3 |
| 6 | Pre-screening and recruitment | Nightly or weekly screening of every patient against every open study, tiers with evidence, appointment-aware routing to the PI, contact log | M4 | R1 |
| 7 | Patient→trial matching | For a given patient, which open studies fit, with evidence (clinician or tumour board request) | M5 | R2 |
| 8 | Consent and enrollment tracking | Pipeline states by signed actions, reasons for exclusion, forecast vs target, early warning | M6 | R2 |
| 9 | Conduct support | Visit windows and missed procedures, deviation candidates, adverse-event candidates for investigator review | M7 | R3 |
| 10 | Data capture | eCRF pre-fill from EHR with lineage (CDASH/ODM or EDC Excel templates), critical-field gaps | M8 | R3 |
| 11 | Close-out and reporting | Registry deadlines, IIT reports, archive export, study retrospective feeding site learning | M9 | R4 |
| 12 | Reimbursement | NHI navigation and TWPAS bundles (v1 NAV) | M10 | R1 (carried) |
| 13 | Networked research | Alliance cohorts and federated feasibility across hospitals, aggregate only (v1 COHORT) | M11 | R2 |

### 2.4 Intended use and regulatory position

**Intended use statement (normative, MUST appear in the user manual, the console footer and every report):**
"TrialBox supports research staff in identifying candidate participants for clinical trials, preparing feasibility
estimates and organising trial operations. All eligibility determinations are made and documented by the investigator.
TrialBox is not intended to diagnose, treat, mitigate or prevent disease or to inform an individual patient's clinical
management."

With this intended use TrialBox is most likely not a medical device in Taiwan (Medical Devices Act and TFDA
software-classification guidance), the US (FDA, 2026 CDS guidance), the EU (MDR, MDCG 2019-11 rev.1) or Japan; it is not
an EU AI Act high-risk system. It is a GCP computerised system and MUST meet ICH E6(R3) Annex 1 §4 (data governance,
audit trail, validation), 21 CFR Part 11-equivalent controls and Taiwan PDPA, Human Subjects Research Act and AI Basic Act
principles (§10). Features that would change this position are gated (CMP-28): inferring undiagnosed conditions or
staging, treatment recommendations, image or signal analysis, patient-facing triage, or setting eligibility without
investigator sign-off.

### 2.5 Non-goals for v2

- Randomisation, IP dispensing, unblinding or any access to treatment-arm data.
- Writing to the EHR or to a sponsor EDC without a signed human action (pre-fill files are produced; humans upload or
  submit).
- Patient-facing chat, eConsent signing, or direct patient outreach (the treating physician contacts patients, per IRB plan).
- Sending patient-level data outside the hospital.
- Multi-tenant cloud hosting. A hosted demo on synthetic data exists for evaluation only (Appendix E).

---

## 3. The experience

### 3.1 Five stages, one study card

Every study moves through the same five stages. Each stage is one email exchange with the agent; the coordinator never has
to open the console unless a signature is needed.

| Stage | The coordinator sends | The agent returns | Human gate |
| --- | --- | --- | --- |
| 1 Connect (once per site) | Nothing; IT points the box at the HIS/CGRD | Data Atlas: what data exists, how fresh, how complete, per department | Data steward confirms mappings (G0) |
| 2 Ask | Protocol PDF, I&E text, or a sponsor feasibility questionnaire, to `trialbox@` with any subject | The criteria as understood, each with how it will be computed and any questions | CRC confirms the criteria mapping (G1) |
| 3 Answer | "OK" or corrections | Feasibility packet: funnel, counts per criterion, projection, competing trials, suggested investigators, filled questionnaire | PI or research office approves release to the sponsor (G2) |
| 4 Find | Study approved; delegation log | Weekly (or nightly) candidate list per PI clinic, tiers with evidence, next appointment | PI confirms or rejects each candidate (G3); the box never decides eligibility |
| 5 Track | Contact, consent and randomisation updates, by reply or console | Weekly status: pipeline, reasons for exclusion, forecast vs target, early warning; conduct alerts | Signed state changes only (G4) |

Each study has one **Study Card**: a living record of the digitised protocol, the approved criteria, every feasibility
answer released, the candidate pipeline and the timeline. Every agent reply links to it and shows what changed since the
last message.

The synthetic online demo (Appendix E) implements stages 1–5 on 600 synthetic patients and is the reference for the
intended look and wording of replies.

### 3.2 Channels

| Channel | Direction | Content allowed | Release |
| --- | --- | --- | --- |
| Email (hospital Exchange/SMTP) | In and out | Everything; PHI only as encrypted attachments to internal, delegated recipients (v1 rules) | R1 |
| Console (web, hospital network only, SSO) | In and out | Approvals with e-signature, evidence viewer, Study Card, Data Atlas, configuration | R1 |
| Microsoft Teams | Out (and simple replies in) | Notifications and links to the console; no PHI in message bodies | R2 |
| LINE (official account) | Out only | Non-PHI reminders ("3 candidates waiting for your review") with a console link | R2 |
| MCP / FHIR API | In and out, machine-to-machine | Sponsor or national-platform feasibility requests; aggregate answers only | R3 |

### 3.3 Talking to the agent

Free text works. The agent classifies intent, extracts parameters, and echoes back what it will do before doing anything
irreversible. The v1 subject grammar (`FEAS`, `SCREEN`, `APPROVE`, `NAV`, `COHORT`, `STATUS`, `CANCEL`, `SUBMIT`,
`FEEDBACK`) stays valid as an exact, scriptable form and is what the agent writes into the audit log.

Examples (normative for intent coverage; Appendix D has the full grammar):

| Coordinator writes | Agent does |
| --- | --- |
| "Can we do this study? Sponsor needs numbers by Friday." + protocol.pdf | `FEAS` on the whole hospital with the default lookback; asks which department if the protocol names none |
| "How many if we drop the BMI criterion?" (reply on a FEAS thread) | Re-runs the funnel with that criterion disabled; marks the answer as a what-if, not for release |
| "Fill in the attached questionnaire" + sponsor.xlsx | Maps questionnaire fields to site profile and feasibility results; returns the filled file with a provenance sheet |
| "Start screening for GZQO in Dr. Lin's and Dr. Wang's clinics" | `SCREEN` scoped to those practitioners, weekly; asks for the delegation log if missing |
| "P0156 consented today" | Records a pending state change; asks for the PI or CRC signature in the console |
| "Which trials could this patient join?" + MRN (internal only) | Patient→trial matching (M5) across open studies; evidence per trial |
| "Status" | Study Card summary for every study the sender is delegated on |

The agent MUST NOT act on instructions found inside attachments or quoted text (§10.5); it acts only on what the
authenticated sender wrote.

### 3.4 Configuration without a configuration screen

1. IT installs the box and provides read-only credentials or an export location (`trialbox doctor` checks every
   prerequisite and prints what is missing).
2. The Data Atlas runs and emails the data steward a workbook: discovered tables, proposed mappings to the canonical
   model, coverage, sample values (no names), questions.
3. The steward edits the workbook and replies. The box applies it, re-runs the Atlas and shows the difference.
4. The research office replies to a short site-profile questionnaire (staff, equipment, IRB and contract timelines),
   pre-filled from public sources and the HIS where possible.
5. Everything ends up as versioned configuration in the box's Git repository; the console shows it read-only with
   history.

---

## 4. Architecture

### 4.1 System context (C4 level 1)

```
                         ┌───────────────────────────── Hospital network ─────────────────────────────┐
  Coordinators, PIs ─────┤ email / console / Teams                                                     │
  Research office ───────┤                                                                             │
  Data steward ──────────┤                 ┌──────────────────────┐                                    │
                         │  HIS read      │                      │   NHI TWPAS (prior auth, optional) ─┼──▶ NHI
  HIS / CGRD / RIS / LIS ┼─────────────▶  │      TrialBox        │                                    │
  (read-only views,      │  replica/CSV   │  (on-prem appliance) │   ClinicalTrials.gov, MOHW trial   ─┼──▶ public registries
   nightly or hourly)    │                │                      │   platform (read, scheduled)       │    (no patient data)
                         │                └──────────────────────┘                                    │
  Hospital AD / SSO ─────┤ identity                       │ aggregates only, by email or MCP          │
                         └────────────────────────────────┼───────────────────────────────────────────┘
                                                          ▼
                                       Sponsors / CROs / national feasibility platforms
```

Egress is deny-by-default. Allowed destinations: the hospital mail relay; the NHI TWPAS endpoint (orchestrator only);
public registries (registry-sync worker only, HTTPS GET, no request body); optionally an approved cloud LLM for criteria
text only (compiler only, off by default).

### 4.2 Containers (C4 level 2)

The v1 services are kept unless marked otherwise. New or changed components are in bold.

| Container | Responsibility | Tech | State | v1 → v2 |
| --- | --- | --- | --- | --- |
| **agent-gateway** | Channels (email, Teams, LINE, console chat), intent classification, request drafting, replies; holds no PHI tools | Python 3.12, FastAPI; optional hardened Hermes Agent profile (§4.5) | Conversation store (Postgres, 90-day retention) | new; absorbs v1 mail-gateway intake/outbound |
| mail-gateway | IMAP/SMTP transport, sender authentication, attachment store | v1 code | MinIO | kept as transport library under agent-gateway |
| **console** | Approvals and e-signatures, Study Card, evidence viewer, Data Atlas, configuration history | FastAPI + server-rendered HTML (Jinja2 + htmx), no SPA | none (reads APIs) | new |
| **workflow-engine** | Durable workflows, human gates, schedules, retries; agent steps run inside workflow steps | DBOS Transact (Python) on PostgreSQL; ADR-02 | Postgres `dbos` schema | replaces v1 SQLite queue + APScheduler |
| orchestrator | Scenario implementations (FEAS, SCREEN, COHORT, NAV, …) as typed tools; reports | v1 code, refactored to tool functions | Postgres (jobs, study cards), MinIO (outputs) | refactored |
| criteria-compiler | Protocol → Criterion IR v2 → ValueSets → CQL/SQL; equivalence gate; review package | v1 code + IR v2 | Git (rulesets) | extended |
| doc-parser | PDF/DOCX/XLSX/M11/USDM → text, sections, tables | v1 contract; Docling image + PaddleOCR for scanned zh-TW | — | image completed |
| adapter | HIS/CGRD → canonical FHIR NDJSON + lake; pseudonymisation | v1 code; streaming ingest; DB drivers | lake, pid map | extended |
| **data-atlas** | Source profiling, mapping proposals, coverage and computability, data-quality checks | Python, DuckDB, Great-Expectations-style checks | Postgres `atlas` | new |
| lake | DuckDB per snapshot; guarded SQL; CJK FTS; hybrid retrieval | v1 code | lake volume | kept; becomes primary engine for interactive queries |
| fhir-store | HAPI FHIR JPA with Clinical Reasoning; CQL verification | v1 | Postgres | kept |
| **registry-sync** | Scheduled pulls of ClinicalTrials.gov and the MOHW trial platform; competing-trial index | Python | Postgres `registry` | new |
| **model-gateway** | Single entry for all LLM calls: routing by role, quotas, logging, pinned model aliases | LiteLLM proxy (self-hosted) | Postgres (keys, spend) | new |
| llm-serving | Local models (§8.2) | vLLM and/or SGLang on DGX B200; GB10 for dev/eval | model volume | extended from one model to a portfolio |
| embed-service | Embeddings and reranking | v1 contract; bge-m3 or Qwen3-Embedding image | — | image completed |
| **eval-runner** | Evaluation sets, regression gate for any model/prompt/rule change, credibility file | Python, Inspect-AI-style harness | MinIO (reports) | new |
| **audit-ledger** | Append-only hash-chained audit events; signature records; WORM anchoring | Postgres table with trigger-enforced append-only + v1 `tb_common.audit` chain; MinIO Object Lock | Postgres, MinIO | v1 file chain → Postgres |
| observability | Traces, metrics, logs (PHI-redacted) | OpenTelemetry → Langfuse (self-hosted) + Prometheus/Grafana | own stores | new |
| identity | SSO and roles | Hospital AD/LDAP via Keycloak (OIDC) | Keycloak DB | new |
| minio, postgres | Object store; relational store | MinIO; PostgreSQL 17 | volumes | Postgres added |

### 4.3 Layering and the PHI boundary

```
 L1  Channels ── agent-gateway (email · Teams · LINE · console chat)     NO PHI TOOLS (tier T0/T1)
        │ typed Request (JSON Schema), sender identity, thread
 L2  Policy ── authN (SSO / mail auth) · authZ (study delegation) · injection screening · rate limits
        │
 L3  Workflows ── DBOS: Onboard · Compile · Feasibility · PreScreen · Match · Track · Abstract · Conduct · Close
        │   each step = deterministic function or recorded LLM call; gates = signals with e-signature
 L4  Tools (MCP servers, policy-checked, audited)
        ├─ tb.registry, tb.atlas.meta, tb.vocab             T0 public / metadata
        ├─ tb.lake.aggregate, tb.feas                       T1 aggregates, small cells suppressed
        ├─ tb.lake.patient, tb.fhir.read, tb.notes.search   T2 PHI, scoped to study + delegation
        └─ tb.write.*  (study card, pipeline state, files)  T3 only from deterministic steps after a gate
 L5  Data ── lake (DuckDB) · FHIR store · pid map (AES-GCM) · object store       ◀── PHI lives here only
 L6  Models ── model-gateway → vLLM/SGLang (local)  [cloud: criteria text only, off by default]
 L7  Assurance ── audit-ledger · eval-runner · observability · backups
```

Rules:
- An LLM never holds T3. T2 tools are callable only inside a workflow started for a study the requesting user is
  delegated on, and every T2 result is logged with purpose.
- The conversational layer (L1) sees request status and approved outputs; it never sees patient-level data. Patient lists
  reach people only as encrypted attachments or console views.
- PHI never enters prompts sent to a non-local model (v1 PHI guard kept; §10.4).

### 4.4 Main data flows

**Ingest (nightly; hourly delta in R2).** HIS/CGRD views → adapter (streaming, chunked by patient) → canonical FHIR NDJSON
with `pid = HMAC(site_key, MRN)` → HAPI load with deletion ledger and DuckDB lake rebuild → Data Atlas profile and quality
checks → snapshot published with an ingest report. A snapshot that fails quality thresholds is not published; the last
good snapshot stays current and the data steward is told why.

**Protocol to rules.** Document → doc-parser → `extract_criteria` (planner model) and independent `extract_criteria`
(verifier model) → reconciliation (agreements auto-accepted into the draft, disagreements become questions) → concept
mapping through vocabulary search tools → IR v2 → templates → CQL + SQL → equivalence gate on a stratified sample →
review package → G1 approval → frozen ruleset `<study>/v<semver>` (Git tag, SHA recorded).

**Feasibility.** Frozen ruleset × snapshot → lake SQL (aggregates) → funnel, per-criterion counts, sensitivity, projection
(§6.3) → registry overlap → packet assembly (numbers template-injected) → narrative drafting (LLM, numbers checked) → G2
→ release by email; questionnaire file filled.

**Pre-screening.** Frozen ruleset × snapshot → lake SQL for structured criteria over scope → CQL verification on a sample
→ note criteria via retrieval + judge with quote check (and verifier model for `strong` tier) → tiers → appointment
join → per-PI packets → G3 decisions recorded → calibration.

### 4.5 The agent layer

The agent is a set of LLM steps inside workflows plus a conversational front end. It does not own state.

- **Front end.** `agent-gateway` implements the channels and a small tool set: `submit_request`, `get_status`,
  `get_study_card_summary`, `ask_clarification`, `list_my_pending_approvals`. It runs the `router` model (§8.2).
- **Optional Hermes Agent profile.** Hermes Agent (Nous Research, MIT) MAY be used as the multi-channel front end once it
  passes the hospital security review. If used, it MUST be pinned to a reviewed release, run with terminal, file,
  browser, web, code-execution, delegation, skill-writing and memory-writing toolsets disabled, `approvals.mode: manual`,
  unattended/cron modes denied, and every tool call passing a `pre_tool_call` policy hook that calls the same policy
  engine and audit ledger as L2 and fails closed. Its only tools are the five above, exposed by an MCP server. It MUST NOT
  schedule regulated work (schedules live in the workflow engine). ADR-05 records the decision and the fallback (the
  in-house gateway, which is the R1 default).
- **Agent steps in workflows** use Pydantic AI with typed outputs and deferred-tool approvals; each LLM call is a DBOS
  step whose inputs and outputs are recorded, so a replay never calls the model again.
- **Skills.** Reusable procedures (for example "answer a TransCelerate site-profile questionnaire") are versioned files in
  the rulesets Git repository. New skills proposed by the agent become merge requests for engineering review; nothing
  self-modifies in production.

### 4.6 Deployment

| Profile | Hardware | Runtime | Use |
| --- | --- | --- | --- |
| **appliance** (default) | 1 × x86 server, 2× RTX PRO 6000 (96 GB) or 1× H200/B200 partition; 256 GB RAM; 8 TB NVMe | docker compose (v1 style), systemd units | Single hospital, R1–R2 |
| **cluster** | Hospital Kubernetes + shared DGX B200 (time-sliced by the hospital scheduler) | Helm chart; one namespace `trialbox`; no cluster-admin operators required | Large medical centre, R2+ |
| **dev/eval** | DGX Spark (GB10) 128 GB | compose, arm64 images | Model evaluation with the same pinned weights |
| **demo** | none (static) | Hosted page with synthetic data | Colleague and sponsor demos only (Appendix E) |

Installation MUST NOT require internet access at the site (offline bundle: images, wheels, model weights, terminology
packages, signed by the vendor key, v1 update mechanism). Remote vendor access is not required for operation; support
works through the hospital's own jump host if the hospital allows it.

### 4.7 Architecture decision records

| ADR | Decision | Alternatives | Reason |
| --- | --- | --- | --- |
| ADR-01 | Keep deterministic CQL/SQL as the only source of counts and tiers | LLM-only matching | Reproducibility, audit, regulator expectations; LLMs fill note criteria with quoted evidence |
| ADR-02 | DBOS Transact on PostgreSQL for durable workflows | Temporal (separate cluster), Celery | One database to operate in a hospital; durable steps and signals; Temporal remains the scale-out option if workflows exceed one database |
| ADR-03 | DuckDB lake is the primary query engine; HAPI CQL verifies | HAPI-only | v1 bench: per-patient `$evaluate` does not scale to interactive or whole-hospital use |
| ADR-04 | LiteLLM model gateway with role aliases (`planner`, `verifier`, `extractor`, `router`, `judge`) pinned to weight SHAs | Direct vLLM calls | Swapping a model is a config change gated by evaluation; per-role quotas and logs |
| ADR-05 | In-house agent-gateway as R1 default; Hermes Agent as optional front end after security review | Hermes as core; no agent | Hermes brings 25+ channels and fast iteration but has a 2026 CVE history and no structured audit; it must stay outside the regulated core |
| ADR-06 | Server-rendered console (Jinja2 + htmx) | React SPA | Minimal UI, fewer dependencies to validate, works on hospital browsers |
| ADR-07 | OMOP CDM 5.4 export as an optional lake view, not the internal model | OMOP-native | Keep v1 FHIR/lake contracts; OMOP view for OHDSI tools, national federated networks and TrialGPT-style matchers |
| ADR-08 | Criterion IR v2 is a superset of v1 (v1 rulesets load unchanged) | New IR | Approved v1 rulesets stay valid |

---

## 5. Data model and contracts

All contracts are JSON Schema 2020-12 files in `schemas/` (v1 convention), compiled into `libs/tb_contracts` by
`make contracts`, with `make contracts-check` failing CI on drift. v2 schemas live under `schemas/v2/` with `$id`
`https://trialbox.local/schemas/v2/<name>.schema.json`. Every persisted object carries `schema_version`.

### 5.1 New and changed schemas

| Schema | Purpose | New / changed |
| --- | --- | --- |
| `criterion_ir` v2.0.0 | Eligibility criterion (superset of v1) | changed (§5.2) |
| `study` | The Study Card: identity, protocol versions, rulesets, roles, scope, status, timeline | new |
| `protocol_digest` | Digitised protocol: sections, I&E list with source spans, schedule of activities (USDM-lite), objectives, population, arms | new |
| `request` | A typed request created by the agent-gateway from a message (intent, parameters, requester, thread, attachments, confidence) | new (replaces `job_create` as the external contract; `job` kept internally) |
| `evidence` | One piece of support for one criterion for one patient: source record ref, snippet, quote span, value, date, extractor, verifier | new |
| `candidate` | Patient × study evaluation: per-criterion status, tier, score, evidence ids, next appointment, routing, decision history | new (supersedes `candidate_list` rows) |
| `feasibility_packet` | Release object: funnel, per-criterion counts, projection with intervals, competing trials, investigators, questionnaire answers, provenance, suppression applied | new (wraps v1 `feasibility_result`) |
| `questionnaire_map` | Mapping from a sponsor questionnaire's fields to packet/site-profile paths | new |
| `site_profile` | Versioned site master profile (TransCelerate SIP-compatible fields) | new |
| `atlas_report` | Data Atlas output: tables, columns, mappings, coverage, freshness, quality checks, computability per IR atom type | new |
| `pipeline_event` | Enrollment pipeline state change: who, what, when, why, signature ref | new |
| `signature` | Electronic signature record bound to a record hash (meaning, signer, method, time) | new |
| `approval_gate` | Gate instance: type (G0–G4), object hash, required role, status, decision, signature | new |
| `model_registry` | Role → model id, weight SHA-256, engine, quantisation, context, eval report id | new (implements v1 `model_manifest`) |
| `eval_report` | Evaluation run: dataset version, metrics per task, thresholds, pass/fail, model/prompt/rule versions | new |
| `abstraction_request` / `abstraction_result` | eCRF pre-fill: target form (CDASH/ODM or EDC template), fields, values with lineage | new |
| `audit_event` v2 | v1 fields + `actor_type` (user/agent/system), `on_behalf_of`, `purpose`, `record_hash`, `prev_hash` | changed |

### 5.2 Criterion IR v2

IR v2 keeps every v1 field and adds the forms the v1 audit found missing. A v1 ruleset validates against v2 unchanged
(ADR-08). Additions (normative excerpts; full schema in `schemas/v2/criterion_ir.schema.json`):

```jsonc
// atom: v1 fields plus
{
  "domain": "condition | observation | medication | procedure | encounter | demographic | claim | report | note | registry | appointment",
  "id": "a3",                                   // NEW: local id so other atoms can anchor to it
  "window": {"from_days": -365, "to_days": 0,
             "anchor": "index | event",          // v1 rejected "event"; v2 implements it
             "event": "a1",                       // NEW: atom id whose matching date is the anchor
             "event_pick": "first | last | each"},// NEW: which occurrence anchors the window
  "count": 2, "count_unit": "records | days | episodes",   // NEW: episodes = distinct events ≥ episode_gap_days apart
  "episode_gap_days": 14,                       // NEW
  "trend": {"metric": "delta | slope | pct_change", "op": "<=", "num": -1.2,
            "baseline": "first_in_window | min | atom:a2"},  // NEW: lab or score change
  "line_of_therapy": {"op": ">=", "num": 2, "setting": "metastatic | any"},  // NEW: derived from medication regimens
  "attribute": {"path": "stage | grade | laterality | histology | biomarker:EGFR | ecog | nyha",
                "op": "in", "codes": ["IIIB", "IV"]}, // NEW: value comparison on non-observation domains
  "absence": "evidence_of_absence | absence_of_evidence"     // NEW: how 'none' is decided (default absence_of_evidence)
}

// boolean: v1 and/or/not plus
{"op": "seq", "args": [a1, a2], "gap": {"min_days": 0, "max_days": 180}}   // NEW: a2 occurs after a1 within gap
{"op": "atleast", "n": 2, "args": [...]}                                   // NEW: n of the args true

// criterion: v1 fields plus
{
  "arm": "ALL | <arm id>",                    // NEW: arm-specific criteria
  "data_requirements": ["lab:EGFR_MUTATION", "note:pathology"],   // NEW: filled by the compiler from the Atlas
  "computability": {"score": 0.0-1.0, "reason": "..."},          // NEW: §6.0
  "ambiguity": [{"span": "...", "question": "...", "resolved_by": "user|default", "resolution": "..."}],  // NEW
  "provenance": {"extractors": ["planner@sha", "verifier@sha"], "agreement": "full|partial|none"}       // NEW
}
```

Semantics that MUST hold (tests in `tests/unit/test_ir_v2_semantics.py`):
- Three-valued logic (true/false/unknown) as in v1; `seq` and `atleast` follow Kleene rules.
- `absence_of_evidence`: no matching record → false for inclusion atoms, true for `none`; flagged
  `missing_data` when the Atlas says the domain's coverage for this patient is below threshold, which makes the result
  unknown instead.
- `evidence_of_absence` requires an affirmative negative record (for example a negative test result) to be true.
- Event-anchored windows evaluate relative to each candidate anchor; `event_pick: each` is true if any anchor satisfies
  the window.
- Every construct compiles to both CQL and SQL from templates; the equivalence gate covers each new construct with
  dedicated fixtures (`rulesets/ATOMS_V2`).

### 5.3 Study Card

```jsonc
{
  "schema_version": "2.0.0",
  "study_id": "GZQO",                         // site short code, unique
  "titles": {"official": "...", "short": "..."},
  "registry_ids": {"nct": "NCT0...", "tw_mohw": "...", "irb": "CGMH-IRB-..."},
  "sponsor": {"name": "...", "cro": "...", "contacts": [{"role": "feasibility", "email": "..."}]},
  "phase": "3", "type": "industry | iit | academic | observational",
  "therapeutic_area": "rheumatology", "condition_codes": ["M10", "M1A"],
  "status": "inquiry | feasibility | selected | startup | recruiting | follow_up | closed | declined",
  "protocol_versions": [{"version": "Amendment 2", "date": "2026-08-01", "digest": "sha256:...", "ruleset": "GZQO/v1.2.0"}],
  "team": [{"user": "u_123", "role": "PI | SubI | CRC | pharmacist", "delegation_from": "2026-09-01", "clinic_ids": ["P12345"]}],
  "scope": {"departments": ["RHEU", "META"], "practitioners": ["P12345"], "sites": ["Linkou"]},
  "targets": {"site_randomized": 12, "fpi_planned": "2026-12-01", "enrollment_end": "2027-09-30"},
  "feasibility_packets": ["fp_01J..."], "screening": {"cadence": "weekly", "last_run": "...", "open_candidates": 14},
  "pipeline": {"prescreened": 31, "contacted": 18, "consented": 6, "screened": 6, "randomized": 4, "screen_failed": 2},
  "timeline": [{"at": "...", "event": "feasibility_released", "ref": "fp_01J..."}]
}
```

### 5.4 Evidence and candidate

```jsonc
// evidence
{"evidence_id": "ev_01J...", "pid": "<hmac>", "criterion_id": "GZQO-INC-05",
 "source": {"type": "note | lab | dx | med | proc | report | vital | appointment | claim", "ref": "DocumentReference/abc",
            "date": "2026-05-07", "department": "RHEU"},
 "value": {"num": 7.9, "unit": "mg/dL"} | {"code": "M10.9"} | null,
 "snippet": "…臨床診斷為急性痛風發作，給予秋水仙素…",       // ≤ 240 chars, stored in the box only
 "quote_span": [123, 141],                                   // offsets into the source text; verified verbatim
 "assertion": "affirmed | negated | historical | family | hypothetical",
 "extractor": {"kind": "rule | llm", "model": "extractor@sha", "prompt": "judge@v3"},
 "verifier": {"model": "verifier@sha", "agrees": true} | null}

// candidate
{"study_id": "GZQO", "ruleset": "GZQO/v1.2.0", "snapshot": "2026-10-04", "pid": "<hmac>",
 "per_criterion": [{"criterion_id": "GZQO-INC-03", "status": "pass | fail | unknown | pending_human | verify_at_screening",
                    "evidence_ids": ["ev_..."]}],
 "tier": "strong | potential | watchlist | excluded",
 "score": 0.0-1.0, "missing": ["GZQO-INC-05"],
 "next_appointment": {"at": "2026-10-18T09:40", "clinic": "RHEU", "practitioner": "P12345"},
 "route_to": "u_123",
 "decisions": [{"by": "u_123", "decision": "confirm | reject | defer", "reason_code": "R07", "comment": "...", "signature": "sig_..."}]}
```

Tier definitions (replacing v1 `high/review`, mapping kept for v1 outputs):
- **strong**: every structured inclusion passes, no exclusion matches, every note criterion affirmed with a verified quote;
  only `pending_human` criteria remain. (v1 `high`.)
- **potential**: no hard failure; at least one `unknown` criterion that a chart review can resolve. (v1 `review`.)
- **watchlist**: fails only time-dependent criteria that may change within the enrollment window (for example a washout
  ending, an upcoming lab, line-of-therapy progression). New in v2.
- **excluded**: a hard failure. Never shown to the PI; counted in feasibility.

### 5.5 Feasibility packet

```jsonc
{"packet_id": "fp_01J...", "study_id": "GZQO", "ruleset": "GZQO/v1.2.0", "snapshot": "2026-10-04",
 "scope": {"population": "whole_hospital | departments | practitioners", "lookback_months": 12},
 "funnel": [{"criterion_id": "...", "label": "...", "remaining": 412, "remaining_possible": 455}],
 "per_criterion": [{"criterion_id": "...", "alone_excludes": 120, "drop_one_gain": 35, "computable": true}],
 "headline": {"condition_seen_12m": 1840, "strong": 120, "potential": 85, "watchlist": 30},
 "projection": {"method": "site_calibrated_v1", "assumptions": {"approach": 0.7, "consent": 0.4, "screen_fail": 0.3,
                "source": "site history 2025–2026 (n=14 studies) | defaults"},
                "monthly": [{"month": 1, "p10": 0, "p50": 1, "p90": 2}], "total_12m": {"p10": 6, "p50": 11, "p90": 17}},
 "competing_trials": [{"nct": "...", "sponsor": "...", "phase": "...", "status": "...", "overlap_estimate": 0.4}],
 "investigators": [{"user": "u_123", "department": "RHEU", "candidates": 64, "past_trials_in_area": 5}],
 "questionnaire": {"template": "sponsor_x_v3.xlsx", "answers": [{"field": "Q12", "value": "...", "source": "headline.strong"}]},
 "suppression": {"rule": "n<5 → '<5'; complementary suppression on", "applied_cells": 3},
 "manifest": {"code_sha": "...", "ruleset_sha": "...", "snapshot_id": "...", "models": {"narrative": "planner@sha"}},
 "approval": {"gate": "G2", "by": "u_456", "signature": "sig_..."}}
```

Numbers in any narrative text MUST be template-injected from this object; a post-check (`numbers_match`) rejects a
narrative containing any number not present in the packet (AI-07).

### 5.6 Service APIs (internal)

All internal APIs are OpenAPI 3.1, generated from FastAPI, authenticated with mTLS between services and OIDC tokens for
user-facing calls. v1 endpoints stay. New endpoints:

| Service | Endpoint | Purpose |
| --- | --- | --- |
| agent-gateway | `POST /v2/messages` | Ingest a message from any channel (email transport calls it) |
| agent-gateway | `GET /v2/requests/{id}` | Request status for the requester |
| workflow-engine | `POST /v2/workflows/{type}` | Start a workflow from a validated `request` |
| workflow-engine | `POST /v2/gates/{gate_id}/decision` | Record an approval decision (requires fresh re-authentication and signature meaning) |
| orchestrator | `GET /v2/studies/{id}` / `PATCH` (deterministic steps only) | Study Card |
| orchestrator | `GET /v2/studies/{id}/candidates?tier=` | Candidate list (T2, delegated users only) |
| orchestrator | `POST /v2/studies/{id}/pipeline-events` | Pipeline state change (requires signature) |
| data-atlas | `POST /v2/atlas/run`, `GET /v2/atlas/report/{snapshot}` | Profile a source; read the report |
| registry-sync | `GET /v2/registry/search?condition=&location=` | Competing-trial search from the local index |
| eval-runner | `POST /v2/eval/runs`, `GET /v2/eval/runs/{id}` | Run and read evaluations |
| console | HTML routes `/studies`, `/approvals`, `/candidates/{study}`, `/atlas`, `/config` | Minimal UI |

### 5.7 MCP tool catalogue

All agent-accessible tools are exposed by MCP servers inside the box (`mcp` Python SDK), each checked by the policy engine
(OPA/Rego policies in `deploy/policy/`) against the caller's identity, the workflow and the study. Tool results are
logged to the audit ledger with purpose.

| Tool | Tier | Input | Output | Used by |
| --- | --- | --- | --- | --- |
| `tb.submit_request` | T0 | intent, params, attachments refs | request id | gateway |
| `tb.get_status` | T0 | request or study id | status text, links | gateway |
| `tb.registry.search` | T0 | condition, intervention, location, status | trials (public data) | feasibility, matching |
| `tb.vocab.search` | T0 | text, system (ICD-10-CM-TW, ATC, LOINC, NHI order, local) | concept candidates with scores | compile |
| `tb.atlas.describe` | T0 | domain or code | availability, coverage, freshness (no patient data) | compile, gateway |
| `tb.feas.run` | T1 | ruleset, scope, options (what-if) | aggregate funnel (suppressed) | feasibility |
| `tb.lake.aggregate` | T1 | parameterised SQL template id + params | aggregate table (suppressed) | feasibility, optimisation |
| `tb.notes.search` | T2 | pid list, query, window | chunks with refs | prescreen judge |
| `tb.lake.patient` | T2 | pid, domains, window | patient facts | prescreen, abstraction |
| `tb.fhir.read` | T2 | resource refs | FHIR resources | abstraction, verification |
| `tb.files.render` | T3 (deterministic only) | template id + data object | file ref (xlsx/pdf/docx) | packets |
| `tb.study.update` | T3 (deterministic only) | patch + gate ref | new card version | workflows |

---

## 6. Functional requirements by module

Format: `ID · requirement · verification · release`. "The box" means TrialBox. Every module also inherits the
cross-cutting rules of §10 (audit, access, disclosure).

### 6.0 M0 — Site onboarding and the Data Atlas

The Data Atlas is how the box learns a hospital. It answers, before anyone promises a sponsor a number: what data exists,
how complete and fresh it is, and which kinds of criteria can be computed from it.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M0-1 | The box MUST connect to a source as (a) a read-only SQL account on views (PostgreSQL, MSSQL, Oracle, Db2 via ODBC), (b) a scheduled CSV/Parquet drop, or (c) FHIR Bulk `$export`, configured in `site/sources.yaml`. | T | R1 |
| FR-M0-2 | `atlas run` MUST profile every configured table: row counts, column types, null rates, distinct counts, value histograms (top 50, values with fewer than 5 patients replaced by `<5`), date ranges, per-department and per-year coverage. Raw identifiers MUST NOT appear in the report. | T | R1 |
| FR-M0-3 | The Atlas MUST propose a mapping from source columns to the canonical model (`templates/CANONICAL.md` v1, extended) using column-name heuristics, value patterns (ICD-10, ATC, LOINC, NHI codes, MRN regex, dates) and an LLM proposal step that sees only column names, types and de-identified value samples. Each proposal carries a confidence and a reason. | T | R1 |
| FR-M0-4 | The Atlas MUST export the proposal as an XLSX workbook (one sheet per canonical table, with dropdowns) and ingest the steward's edited workbook back into `mapping/<site>.yaml`, producing a diff. Gate G0 approves. | T, D | R1 |
| FR-M0-5 | After each ingest the Atlas MUST compute **domain coverage** per patient (fraction of patients with ≥1 record per domain in the last 12/24/60 months) and **freshness** (lag between the latest source timestamp and the snapshot). | T | R1 |
| FR-M0-6 | The Atlas MUST compute a **computability score** per IR atom type and value set (for example "eGFR within 90 days: 63 % of active RHEU patients have a creatinine in the window"), used by M1 to mark criteria and by M3 to qualify counts. | T | R1 |
| FR-M0-7 | The Atlas MUST run data-quality checks (unit consistency per lab code, impossible values, future dates, duplicate encounters, orphan records, code-system validity against loaded terminology) and open a data-quality issue for the steward when thresholds are crossed. A snapshot with a blocking issue MUST NOT be published. | T | R1 |
| FR-M0-8 | The box MUST load full terminology packages: ICD-10-CM/PCS (Taiwan NHI edition), the NHI drug master with ATC, NHI order codes, LOINC, the site's local lab dictionary with LOINC mapping, department and practitioner tables. `tools/build_terminology.py` validates package versions and records them in the snapshot manifest. | T | R1 |
| FR-M0-9 | Ingest MUST stream: memory use bounded (≤ 8 GB) independent of patient count, by chunking on patient id; initial backfill MUST be restartable by chunk. | T | R1 |
| FR-M0-10 | Incremental ingest SHOULD run hourly for appointments and new notes (R2), with the nightly full refresh kept. | T | R2 |
| FR-M0-11 | The **site profile** (TransCelerate SIP-compatible: staff, equipment, IRB/contract timelines, past enrollment) MUST be versioned, editable by the research office by workbook or console, and pre-filled from the box's own data where possible (for example historical enrollment from M6). | T, I | R1 |
| FR-M0-12 | `trialbox doctor` MUST check host, GPU, models, mail, SSO, source connectivity, egress rules, clock sync, disk, backup and certificate expiry, printing each failure with the fix. | T | R1 |

### 6.1 M1 — Protocol intake and digitisation

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M1-1 | The box MUST accept protocols as PDF (text or scanned), DOCX, ICH M11 structured protocol, CDISC USDM JSON, ClinicalTrials.gov record, or pasted text; it MUST locate the I&E sections and the schedule of activities. | T | R1 (USDM R2) |
| FR-M1-2 | Criteria MUST be extracted independently by two models (`planner`, `verifier`, §8.2) into IR v2 with source spans; agreement is computed per criterion; disagreements and low-confidence items become clarification questions to the CRC. | T | R1 |
| FR-M1-3 | Concept mapping MUST use `tb.vocab.search` results only (no codes from model memory); every mapped code is checked to exist in the loaded terminology. | T | R1 |
| FR-M1-4 | Every criterion MUST be classified `structured / note / human` and annotated with `data_requirements` and `computability` from the Atlas; criteria with computability < 0.5 MUST be flagged in the reply ("we can count this only for 40 % of patients"). | T | R1 |
| FR-M1-5 | Ambiguities (undefined thresholds, unit-less values, "adequate organ function", "per investigator judgement") MUST be listed with a proposed default; the CRC confirms or edits by reply. | T, D | R1 |
| FR-M1-6 | The review package (v1) MUST show per criterion: text, source span, IR, ValueSets, CQL, SQL, computability, and the count of matching patients on the current snapshot (aggregate); G1 approval freezes the ruleset (Git tag + SHA). | T | R1 |
| FR-M1-7 | Protocol amendments MUST produce a criterion-level diff against the previous version and re-evaluate open candidates after re-approval. | T | R2 |
| FR-M1-8 | The schedule of activities MUST be digitised into a USDM-lite structure (visits, windows, procedures) for M7. | T | R3 |
| FR-M1-9 | Protocol text MAY be sent to an approved cloud model only when `cloud.allowed=true`, the PHI guard passes, and the protocol is not marked confidential by the sponsor; otherwise local models only. | T, I | R1 |

### 6.2 M2 — Protocol optimisation

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M2-1 | For any ruleset the box MUST compute per criterion: patients excluded by it alone, drop-one gain, and the criterion's position in the funnel. | T | R1 |
| FR-M2-2 | What-if: the user MAY disable a criterion or change a threshold by reply ("eGFR ≥ 25 instead of 30"); the box re-runs on the same snapshot and marks results as what-if (never released as feasibility without G2). | T | R2 |
| FR-M2-3 | The box SHOULD rank criteria by "cost" (patients lost) against a safety tag supplied by the sponsor or PI (criteria tagged safety-critical are never suggested for relaxation), following the Trial Pathfinder approach (Liu et al., Nature 2021). | A, T | R2 |
| FR-M2-4 | The box SHOULD report representativeness: the eligible population vs the condition population by age band, sex and comorbidity burden, to support diversity plans. | T | R3 |

### 6.3 M3 — Feasibility and the sponsor questionnaire

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M3-1 | `FEAS` MUST produce a feasibility packet (§5.5) within 1 hour of G1 for a ruleset of ≤ 40 criteria on ≤ 3 M patients (NFR-3). | T | R1 |
| FR-M3-2 | Counts MUST be reported as strong / potential / watchlist and as a funnel with "meets all so far" and "possible (data missing or note-based)" bands; note criteria are estimated on a stratified sample of ≤ 200 patients with the judge and reported with a 95 % interval. | T | R1 |
| FR-M3-3 | The enrollment projection MUST give p10/p50/p90 monthly and 12-month totals from: prevalent pool, incident flow (new qualifying diagnoses per month over the past 24 months), clinic visit cadence of candidates, and conversion rates (approach, consent, screen failure) taken from the site's history in M6 when ≥ 5 comparable studies exist, otherwise from configurable defaults clearly labelled as such. | T, A | R1 (site-calibrated R2) |
| FR-M3-4 | Competing trials MUST be listed from the registry index (ClinicalTrials.gov and the MOHW platform) filtered by condition, phase and location (site, then country), with an overlap estimate when the competing trial's criteria are available. | T | R1 |
| FR-M3-5 | Investigator suggestions MUST rank delegated or eligible investigators by candidate count in their clinics, past trials in the area (site profile) and current load (open studies, M6). | T | R1 |
| FR-M3-6 | **Questionnaire autofill.** Given a sponsor questionnaire (XLSX, DOCX or PDF form), the box MUST map each question to a packet or site-profile field using `questionnaire_map` (learned per sponsor template, confirmed by the CRC once), fill answers, and attach a provenance sheet listing for every answer its source path, data cut and rule version. Unmapped questions are listed for the CRC. | T, D | R1 |
| FR-M3-7 | Every released number MUST pass small-cell suppression (`<5` default, configurable per IRB policy) with complementary suppression so that suppressed cells cannot be recomputed from totals (v1 rule, kept). | T | R1 |
| FR-M3-8 | Releases outside the hospital MUST pass gate G2 (PI or research office) and be logged with recipient, content hash and packet id. | T | R1 |
| FR-M3-9 | The box SHOULD answer machine requests from national platforms or sponsor agents (MCP/FHIR `ResearchStudy` + `Group` with `EvidenceVariable` criteria) with the same packet, aggregate only, after G2 or a standing approval for a defined request type. | T | R3 |
| FR-M3-10 | Multi-site feasibility within a hospital system (for example several campuses) MUST be supported by running the same ruleset on each campus snapshot and merging aggregates (v1 COHORT merge rules). | T | R2 |

### 6.4 M4 — Pre-screening and recruitment

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M4-1 | For every study in status `recruiting`, the box MUST screen the scoped population on the configured cadence (weekly default, nightly allowed) and on demand. | T | R1 |
| FR-M4-2 | **Portfolio screening.** The box MUST support screening each patient with an upcoming appointment against all recruiting studies the patient's clinic participates in, producing one consolidated "clinic-day list" per practitioner per day (R2). | T | R2 |
| FR-M4-3 | Each candidate MUST carry per-criterion status and evidence (§5.4); note-criterion affirmations need a verbatim quote; `strong` tier needs verifier-model agreement on every note criterion. | T | R1 |
| FR-M4-4 | Candidates MUST be routed to the PI or sub-investigator who owns the next appointment (or last visit), with appointment date, clinic and a one-line summary; lists go by encrypted attachment and console link, never in an email body. | T | R1 |
| FR-M4-5 | The PI or CRC MUST be able to confirm, reject (with a reason code from a fixed list plus free text) or defer each candidate by console or by reply (`CONFIRM P0156`, `REJECT P0156 R07 on dialysis`). | T | R1 |
| FR-M4-6 | Patients who opted out of research contact (registry, NHI secondary-use opt-out where it applies, hospital do-not-contact flag) MUST be excluded before any list is produced and counted only in aggregates. | T | R1 |
| FR-M4-7 | Time-sensitive criteria MUST be re-evaluated for candidates with an appointment in the next 14 days (v1 MICROBATCH), and watchlist patients MUST be re-checked when the blocking condition can change (washout end date, new lab). | T | R1 |
| FR-M4-8 | The box MUST record the reason for every rejection and feed criterion-level precision estimates (calibration, §8.6); a criterion whose PI rejection rate exceeds 30 % over ≥ 20 decisions MUST be flagged for review. | T | R1 |
| FR-M4-9 | The box MUST NOT contact patients. Outreach materials (IRB-approved letters, scripts) MAY be attached to the PI packet. | I | R1 |

### 6.5 M5 — Patient → trial matching

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M5-1 | Given a patient (MRN, internal request by a delegated clinician) the box MUST rank the site's recruiting studies by fit using the frozen rulesets (deterministic part) and return per-trial criterion evidence. | T | R2 |
| FR-M5-2 | For studies without a site ruleset (registry trials not yet open at the site), the box MAY rank by a TrialGPT-style retrieval and LLM criterion assessment (port from `trialgpt/`), clearly labelled "not open here; registry match". | T | R2 |
| FR-M5-3 | Tumour-board mode: a batch of patients for a meeting date produces one summary per patient. | D | R3 |

### 6.6 M6 — Enrollment tracking and forecasting

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M6-1 | The pipeline states are `prescreened → contacted → consented → screened → randomized` with exits `declined`, `screen_failed (reason)`, `not_contactable`, `withdrawn`. Transitions after `prescreened` MUST be signed human actions (G4). | T | R2 |
| FR-M6-2 | A weekly status email per study MUST show the pipeline, reasons for exclusion and screen failure, forecast (p10/p50/p90) vs target, and an early warning when p50 falls below 80 % of plan for two consecutive weeks. | T | R2 |
| FR-M6-3 | A portfolio report for the research office MUST rank studies by risk of under-enrolment. | T | R2 |
| FR-M6-4 | The box MUST import enrollment from the hospital CTMS or the IRB system when available (read-only) and reconcile it with its own pipeline. | T | R3 |
| FR-M6-5 | Site history (consent rate, screen-failure rate, time-to-first-patient per therapeutic area) MUST be derived from closed studies and feed M3 projections. | T | R2 |
| FR-M6-6 | Sponsor-facing enrollment summaries MUST be aggregate only and pass G2. | T | R2 |

### 6.7 M7 — Start-up and conduct copilots

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M7-1 | Start-up checklist per study (IRB, contract, budget, SIV, pharmacy, lab kits, system access, delegation log) with due dates and reminders, configurable per hospital SOP. | D | R3 |
| FR-M7-2 | **Coverage analysis:** map each schedule-of-activities procedure to NHI fee codes and classify standard of care (NHI-billable) vs research-only (sponsor-paid), producing a draft budget table for the research office. | T | R3 |
| FR-M7-3 | **Visit windows:** for enrolled participants, compute visit due dates and windows from the SoA and the randomisation date; alert the CRC before a window closes; flag likely deviations (visit outside window, missed procedure) for CRC confirmation. | T | R3 |
| FR-M7-4 | **Adverse-event candidates:** for enrolled participants, surface new hospital events (ED visits, admissions, new diagnoses, lab abnormalities graded by CTCAE thresholds) to the investigator within 24 h of ingest, as candidates only; the investigator decides AE status. | T | R3 |
| FR-M7-5 | The box MUST NOT access treatment-arm data or IRT unblinding fields. | I, T | R3 |

### 6.8 M8 — Data abstraction and eCRF pre-fill

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M8-1 | Given a target form (CDASH/ODM v2 form definition, or an EDC bulk-upload template in XLSX), the box MUST map form fields to canonical data and produce a pre-filled file per participant and visit. | T | R3 |
| FR-M8-2 | Every pre-filled value MUST carry lineage: source record, timestamp, transformation, extractor (rule or model) and confidence; temporal, multivariable or open-ended fields MUST be marked "needs review" unless rule-derived. | T | R3 |
| FR-M8-3 | A critical-field gap report MUST list required fields with no source data per participant. | T | R3 |
| FR-M8-4 | The box MUST NOT submit to an EDC; humans upload. Exported files go only to delegated internal recipients. | I | R3 |
| FR-M8-5 | Retrospective studies: the same engine MUST support bulk abstraction for an approved cohort with an IRB reference, producing a de-identified dataset with a data dictionary and QC report. | T | R3 |

### 6.9 M9 — Close-out, reporting, learning

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M9-1 | Registry deadlines: for studies where the hospital is the sponsor (IIT), track registration ids and results-posting due dates (primary completion + 12 months) and remind the PI. | T | R4 |
| FR-M9-2 | Study retrospective at close: feasibility estimate vs actual enrollment, screen-failure reasons, criteria that caused most PI rejections; stored as site history (FR-M6-5). | T | R4 |
| FR-M9-3 | Archive export: Study Card, rulesets, packets, decisions and audit trail as PDF/A plus JSON with checksums. | T | R4 |

### 6.10 M10 — NHI navigation (v1 NAV, carried)

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M10-1 | v1 NAV, TWPAS bundle generation, validation and pre-check MUST keep working unchanged on IR v2 rulesets. | T | R1 |
| FR-M10-2 | TWPAS packages MUST be updated to the IG version NHI requires at go-live (1.2.5 or later) with the official pre-check CQL when published. | T | R2 |

### 6.11 M11 — Networked research (v1 COHORT, extended)

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M11-1 | v1 quarterly cohort tables and alliance merge MUST keep working. | T | R1 |
| FR-M11-2 | The box SHOULD expose an OMOP CDM 5.4 view of the lake (ADR-07) so that OHDSI tools and national federated networks can query it locally. | T | R3 |
| FR-M11-3 | Federated feasibility: the box MAY answer a federated query (same ruleset, aggregate result, small cells suppressed) from a trusted network coordinator after G2 or a standing approval. | T | R3 |
| FR-M11-4 | Trial-ready cohorts: a standing cohort definition (for example "early Alzheimer's disease with amyloid testing") MAY be maintained with consented-to-contact patients, refreshed on each snapshot, reported in aggregate. | T | R3 |

### 6.12 Agent behaviours (cross-module)

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-AG-1 | The agent MUST restate its understanding of any request before starting a workflow that releases data or changes a Study Card, unless the request used the exact v1 grammar. | T | R1 |
| FR-AG-2 | The agent MUST ask at most one clarification round before proceeding with documented defaults, and MUST list the defaults it used in the reply. | T | R1 |
| FR-AG-3 | The agent MUST answer status questions from the Study Card only, never from memory. | T | R1 |
| FR-AG-4 | The agent MUST reply in the language of the sender (Traditional Chinese or English); regulated outputs keep the template's language. | T | R1 |
| FR-AG-5 | The agent MUST refuse and explain when a request exceeds the sender's permissions, and MUST NOT reveal whether a named patient exists to a non-delegated user. | T | R1 |
| FR-AG-6 | Every agent action MUST be attributable: `actor_type=agent`, `on_behalf_of=<user>`, request id, workflow id. | T | R1 |

---

## 7. Workflows

Workflows are DBOS workflows in `services/workflows/` (new package). Every step is either a deterministic function
(idempotent, keyed by `(workflow_id, step)`) or a recorded LLM call. Gates are DBOS events waited on by the workflow and
set only by `POST /v2/gates/{id}/decision` after re-authentication. Timeouts produce reminders, not silent failures.

### 7.1 Gate catalogue

| Gate | Object | Who may decide | Meaning recorded with the signature | Timeout behaviour |
| --- | --- | --- | --- | --- |
| G0 | Site mapping / Atlas configuration | Data steward | "I confirm this mapping reflects the source system" | Reminder at 3 and 7 days |
| G1 | Criteria mapping (ruleset version) | CRC (and PI for studies marked high-risk) | "I confirm the criteria are represented as intended" | Reminder at 1 and 3 days |
| G2 | External release (feasibility packet, enrollment summary, questionnaire) | PI or research office | "I approve release of these aggregate results to <recipient>" | Reminder at 1 day; expires at the sponsor deadline |
| G3 | Candidate decision | PI or delegated sub-investigator | "Confirm / reject candidate for pre-screening follow-up" (never "eligible") | Candidate stays pending; listed in the next packet |
| G4 | Pipeline transition after pre-screening | CRC or PI | "Participant <state> on <date>" | none |
| G5 | Model, prompt or rule change to production | System owner + QA | "Change validated per evaluation report <id>" | none |

### 7.2 FeasibilityWorkflow

```
start(request: FEAS, study?, protocol_ref)
 ├─ ensure_study_card()                                  deterministic
 ├─ parse_document(protocol_ref)                         doc-parser
 ├─ extract_criteria[planner] ║ extract_criteria[verifier]   LLM, recorded, parallel
 ├─ reconcile_and_map()                                  deterministic + vocab search; questions list
 ├─ annotate_computability(atlas_snapshot)               deterministic
 ├─ reply_understanding(questions, defaults)             gateway email (FR-AG-1)
 ├─ ⏸ G1 criteria mapping                                CRC
 ├─ compile_ruleset() → equivalence_gate()               deterministic; fail → reply with diff, back to G1
 ├─ run_feasibility(ruleset, snapshot, scope)            lake SQL; note sample judge (LLM, recorded)
 ├─ project_enrollment(site_history)                     deterministic
 ├─ competing_trials(registry_index)                     deterministic
 ├─ assemble_packet() → suppress() → render_files()      deterministic
 ├─ draft_narrative[planner] → numbers_match()           LLM, recorded; deterministic check
 ├─ ⏸ G2 release                                         PI / research office
 └─ send(recipients) → study_card.timeline += released  deterministic
```

### 7.3 PreScreenWorkflow (per study, scheduled)

```
schedule(cadence) → snapshot_ready?
 ├─ scope = recruiting studies × clinics × appointments(next N days) − opt-outs
 ├─ structured_eval(ruleset, scope)                      lake SQL (bulk)
 ├─ cql_verify(sample 5 %)                               HAPI; mismatch → incident, study paused
 ├─ for patients without hard failure:
 │    note_criteria: retrieve → judge[extractor] → quote_verify → (strong?) verify[verifier]
 ├─ tier() → rank() → route_to_owner()                   deterministic
 ├─ render_packets(per PI) → send(encrypted) + console    deterministic
 ├─ ⏸ G3 decisions (async, per candidate)                PI
 └─ calibration_update(decisions)                        deterministic (§8.6)
```

### 7.4 Other workflows

| Workflow | Trigger | Key steps | Gates |
| --- | --- | --- | --- |
| OnboardWorkflow | install, new source, schema change | connect → profile → propose mapping → workbook → apply → re-profile | G0 |
| CompileWorkflow | protocol or amendment | as 7.2 up to frozen ruleset; amendment diff; re-evaluation of open candidates | G1 |
| MatchWorkflow | clinician request for a patient | rulesets of recruiting studies → registry match (optional) → summary | none (internal, delegated clinician only) |
| TrackWorkflow | weekly per study | reconcile pipeline (+CTMS import) → forecast → warning → status email | G2 for sponsor copies |
| ConductWorkflow | nightly per enrolled participant (R3) | visit windows → deviation candidates → AE candidates → CRC/PI notifications | none (candidates only) |
| AbstractWorkflow | request with form template | map fields → extract with lineage → gap report → files | G1-like confirmation of the field map |
| CloseWorkflow | study closed | retrospective → site history → archive export | none |
| ChangeWorkflow | model/prompt/rule change | eval-runner on all suites → report → G5 → registry update | G5 |

---

## 8. AI components

### 8.1 Roles and prompts

Every LLM call goes through `model-gateway` by role alias and a versioned prompt file in `prompts/` (v1 convention:
YAML front matter with id, version, schema, role). Output is always schema-constrained JSON.

| Prompt | Role | Input | Output schema | PHI | Notes |
| --- | --- | --- | --- | --- | --- |
| `classify_intent` | router | message text (sanitised) | `request` draft | no | v2 new |
| `extract_criteria` | planner, verifier | protocol sections | IR v2 list with spans | no | replaces v1 `ir_extract`; run twice |
| `concept_map` | planner | criterion phrase + vocab search hits | code selections with reasons | no | v1 kept, tool-grounded |
| `ask_clarification` | planner | ambiguity list | questions + defaults | no | v2 new |
| `judge` | extractor | criterion question + retrieved chunks | met / not met / insufficient + quote + assertion | yes, local only | v1 kept, adds `assertion` |
| `verify_judgement` | verifier | judge output + same chunks | agree / disagree + reason | yes, local only | v2 new |
| `draft_narrative` | planner | packet JSON | text with `{{placeholders}}` only | no (aggregates) | v2 new; numbers injected |
| `map_questionnaire` | planner | questionnaire field labels | field → packet path | no | v2 new |
| `abstract_field` | extractor | form field definition + patient facts/chunks | value + lineage + confidence | yes, local only | v2 new |
| `draft_doc` | planner | template + facts | DOCX sections | yes, local only | v1 kept |
| `propose_mapping` | planner | column names, types, de-identified samples | canonical mapping proposals | no | v2 new (Atlas) |

### 8.2 Model portfolio

The registry (`models/registry.yaml`, schema `model_registry`) binds each role to exactly one model build. Reference
portfolio for a DGX B200 (8 GPUs); the appliance profile uses the smaller column.

| Role | Reference (B200) | Appliance (2× 96 GB) | Why |
| --- | --- | --- | --- |
| planner | Qwen3.5-397B-A17B (FP8, TP4) or DeepSeek V4-Flash | gpt-oss-120b | Best open reasoning with native Chinese; protocol and narrative work |
| verifier | gpt-oss-120b | Qwen3.6-35B-A3B | A different model family for independent extraction and judgement checks |
| extractor (judge, abstraction) | Qwen3.6-35B-A3B or MedGemma 1.5 27B (licence check) | Qwen3.6-35B-A3B | Fast, Chinese-native, good structured output |
| router | Qwen3.6-35B-A3B (shared) | gpt-oss-20b | Low latency intent classification |
| embeddings / rerank | Qwen3-Embedding or bge-m3; reranker | bge-m3 | v1 contract |
| guard | gpt-oss-safeguard-20b or Qwen3Guard | same | Prompt-injection and policy classification of untrusted text |

Rules: weights are pinned by repository revision and SHA-256 recorded in the registry and every run manifest; sampling
`temperature=0`, fixed seed; a role change is a ChangeWorkflow (G5). Licences are recorded per model; models whose terms
restrict clinical or commercial use need a legal sign-off entry before activation.

### 8.3 Evidence-anchored judging

Implements the pattern with the strongest evidence in the literature (criterion-level judgement with quoted evidence and
deterministic aggregation; Appendix B):
1. Retrieve note chunks for the criterion (v1 hybrid retrieval, CJK bigram FTS + embeddings, RRF), restricted to the
   criterion window.
2. `judge` returns `met | not_met | insufficient`, a verbatim quote, the source chunk id, and an `assertion` label
   (affirmed, negated, historical, family, hypothetical).
3. `quote_verify` (deterministic) checks the quote exists in the chunk, the chunk date is inside the window, and the
   assertion is consistent with negation cues (Chinese and English cue lists, v1 `textproc`). Failure → `insufficient`.
4. For a candidate to reach `strong`, `verify_judgement` (different model family) must agree on every note criterion;
   disagreement → `potential` with both rationales shown.
5. Aggregation, tiers and ranks are code (§5.4). The LLM never sets a tier.

### 8.4 Guarding numbers and claims

- AI-07: any narrative text is generated with placeholders; `numbers_match` rejects text containing a digit sequence not
  produced by the template engine.
- AI-08: answers to sponsor questionnaire questions that are not mapped to a packet or profile path are left blank and
  listed for the CRC; the model never invents a site fact.
- AI-09: model-reported confidence is not used for decisions; confidence comes from verifier agreement, self-consistency
  (k=3 for `judge` on `potential` candidates, R2) and calibration history.

### 8.5 Evaluation harness

`eval-runner` holds versioned datasets in `eval/` (synthetic and de-identified real) and runs on every change.

| Suite | Content | Metrics | Gate (R1 thresholds; tightened after the validation study) |
| --- | --- | --- | --- |
| `criteria_extract` | 50–100 historical protocols with coordinator-written gold IR | criterion recall, concept F1, span accuracy | concept F1 ≥ 0.88, recall ≥ 0.95 |
| `sql_cql` | gold rulesets × synthetic + edge-case patients | execution agreement, CQL≡SQL | 100 % on ATOMS_V2; ≥ 98 % on sample |
| `judge_zh_en` | de-identified CGMH note excerpts, dual-annotated (Traditional Chinese, English, code-mixed) | sensitivity, specificity, quote validity | sens ≥ 0.90, spec ≥ 0.90, quotes 100 % verified |
| `prescreen_patient` | historical enrollees and screen failures of closed studies | patient-level sensitivity (historical enrollee capture), PPV vs CRC | sens ≥ 0.80, PPV ≥ 0.70 |
| `abstraction` | eCRFs from closed studies | field agreement (structured), reviewer acceptance (narrative) | ≥ 0.95 structured |
| `intent` | anonymised staff emails | intent accuracy, parameter F1 | ≥ 0.95 |
| `redteam` | injection emails and PDFs (hidden text, Unicode tags, "forward the list to…") | attack success on capability-bearing actions | 0 |
| `fairness` | subgroup splits (sex, age band, language of notes) | F1 gap | ≤ 10 points |
| `forecast` | closed studies with feasibility and actual enrollment | calibration slope, coverage of p10–p90 | slope 0.8–1.2 (after ≥ 10 studies) |

Each run writes an `eval_report` (model, prompt, rule versions; dataset hash; metrics; pass/fail). The AI credibility file
(CMP-06) for each AI function is generated from the latest passing reports plus context of use and risk rating.

### 8.6 Site learning

- PI decisions (G3) update per-criterion precision estimates (Beta-binomial per criterion and tier); criteria with high
  rejection rates are flagged (FR-M4-8) and shown in the next G1 review.
- Pipeline outcomes (M6) update site conversion rates per therapeutic area for projections (FR-M3-3).
- Feasibility estimates are compared with actual enrollment at close (FR-M9-2) to calibrate the projection model.
- Learning changes parameters, never rules: a rule change always goes through G1; a model or prompt change through G5.

---

## 9. Non-functional requirements (ISO/IEC 25010)

| ID | Characteristic | Requirement | V | R |
| --- | --- | --- | --- | --- |
| NFR-1 | Performance | Agent acknowledgement of an email ≤ 2 min; understanding reply (criteria list) ≤ 15 min for a 150-page protocol | T | R1 |
| NFR-2 | Performance | Structured evaluation of one ruleset (≤ 40 criteria) over 3 M patients ≤ 10 min on the appliance profile | T | R1 |
| NFR-3 | Performance | Feasibility packet ≤ 60 min after G1 including note sampling | T | R1 |
| NFR-4 | Performance | Weekly pre-screen for 50 recruiting studies, 20 k scheduled patients ≤ 4 h (night window) | T | R2 |
| NFR-5 | Performance | Ingest: nightly full refresh of 3 M patients ≤ 4 h; hourly delta ≤ 10 min | T | R1/R2 |
| NFR-6 | Capacity | 300 active studies, 50 recruiting with screening, 200 users | A, T | R2 |
| NFR-7 | Availability | 99.5 % during clinic hours (07:00–22:00 local) for console and email intake; workflows resume after restart with no lost steps | T | R1 |
| NFR-8 | Recoverability | RPO ≤ 1 h for Postgres and the audit ledger; RTO ≤ 8 h; restore tested quarterly | T | R1 |
| NFR-9 | Reproducibility | Any released output regenerates byte-identically from its manifest (v1 G5 kept) | T | R1 |
| NFR-10 | Usability | A CRC completes stage 2–3 for a new protocol with no training beyond a 1-page guide; console tasks ≤ 3 clicks to sign | D | R1 |
| NFR-11 | Usability | Replies and console available in Traditional Chinese and English | I | R1 |
| NFR-12 | Maintainability | Unit test coverage ≥ 85 % for deterministic code; mypy --strict clean; every module documented with a C4 component view | I, T | R1 |
| NFR-13 | Portability | Runs on x86 and arm64 (GB10); no internet at runtime | T | R1 |
| NFR-14 | Security | See §10; no critical/high vulnerabilities open > 30 days in shipped images | T | R1 |
| NFR-15 | Observability | Every workflow step traced (OpenTelemetry) with PHI redaction; dashboards for queue depth, latency, model throughput, gate backlog | I | R1 |
| NFR-16 | Cost | All inference local; GPU budget per role enforced by the model gateway | I | R1 |

---

## 10. Security, privacy and compliance

### 10.1 Access model

Identity comes from the hospital directory through Keycloak (OIDC). Authorisation is attribute-based: role × study
delegation × purpose, evaluated by OPA policies shared by the console, the APIs and the MCP servers.

| Capability | CRC | PI / Sub-I | Research office | Data steward | Sponsor (external) | Admin | Agent |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Submit protocol / FEAS | ✓ | ✓ | ✓ | – | – | – | on behalf |
| Approve G1 | ✓ (delegated) | ✓ | – | – | – | – | ✗ |
| Approve G2 (external release) | – | ✓ | ✓ | – | – | – | ✗ |
| See candidate list (PHI) | delegated studies | delegated studies | with delegation | – | ✗ | ✗ | inside T2 workflow steps only |
| Decide G3 | – | ✓ | – | – | – | – | ✗ |
| Record G4 transitions | ✓ | ✓ | – | – | – | – | ✗ |
| Approve G0 | – | – | – | ✓ | – | – | ✗ |
| Receive aggregates | ✓ | ✓ | ✓ | ✓ | after G2 | – | – |
| Configure system | – | – | – | mapping only | – | ✓ (no PHI) | ✗ |
| Read audit trail | own actions | own studies | ✓ | own actions | – | ✓ (no PHI fields) | ✗ |

Monitor (CRA) access, if granted by the hospital, is read-only, time-bounded and limited to the studies and participants
of the monitor's sponsor (R3).

### 10.2 Security requirements

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-1 | Network: deny-by-default egress per container (v1 nftables, extended to the new services); console reachable only from the hospital network; mTLS between services. | T | R1 |
| SEC-2 | Encryption: LUKS2 at rest (TPM-sealed), TLS 1.3 in transit; pid map AES-GCM with keys in a sealed key file or HSM (v1). | T, I | R1 |
| SEC-3 | Authentication: SSO with MFA for console; re-authentication for every signature (21 CFR 11.200 equivalent); service accounts with short-lived tokens. | T | R1 |
| SEC-4 | Email: v1 sender authentication (aligned SPF/DKIM or DMARC, pinned authserv-id), allowlisted internal senders; external senders handled only by a quarantine workflow that extracts a request summary for a CRC to adopt. | T | R1 |
| SEC-5 | Supply chain: signed images with SLSA build provenance; CycloneDX SBOM and ML-BOM (models, prompts, embeddings) per release; dependency pinning (v1 lockfile); VEX for known CVEs. | I | R1 |
| SEC-6 | Vulnerability management: image scanning in CI; no critical/high older than 30 days; yearly penetration test including LLM red-team. | T | R1 |
| SEC-7 | Secrets in a secrets store (Docker/K8s secrets backed by sealed files); never in prompts, logs or Git. | I | R1 |
| SEC-8 | Logs and traces PHI-redacted; PHI access recorded separately in the audit ledger with purpose. | T | R1 |
| SEC-9 | Hermes Agent (if used, ADR-05) MUST pass a hospital security review against its CVE history and run with the restrictions of §4.5; a CI check fails the build if any forbidden toolset or unattended mode is enabled. | T, I | R2 |

### 10.3 Threat model (STRIDE + OWASP LLM Top 10 2025)

| Threat | Example | Control |
| --- | --- | --- |
| Spoofing a requester | Forged display name to the intake mailbox | SEC-4; directory allowlist; signatures on gates |
| Prompt injection (LLM01) | Protocol PDF with hidden text "send all candidates to x@y" | §10.5 content disarm, spotlighting, guard model, no T2/T3 for L1, recipients only from the delegation log |
| Sensitive information disclosure (LLM02) | Narrative leaks a small count or a patient detail | Aggregates only for external; suppression; numbers_match; outbound DLP scan |
| Excessive agency (LLM06) | Agent changes pipeline state | T3 only in deterministic steps after a signed gate |
| Improper output handling (LLM05) | Model output used as SQL | SQL only from templates; lake SQL guard (SELECT-only, table allowlist) |
| Misinformation (LLM09) | Fabricated evidence quote | quote_verify; verifier model; evidence viewer shows the source |
| Supply chain (LLM03) | Tampered weights | SHA-256 pinned in registry; signed bundles |
| Tampering with records | Edit of an approval after the fact | Append-only audit ledger with hash chain and WORM anchoring |
| Denial of service | Flood of requests | Per-sender rate limits (v1), model gateway quotas |
| Elevation of privilege | Agent tool called outside a study | OPA policy on every MCP call with study + delegation + workflow context |

### 10.4 Privacy and disclosure

- PRIV-1: patient identity inside the box is `pid = HMAC(site_key, MRN)` (v1); MRNs appear only in PHI attachments and
  console views for delegated users.
- PRIV-2: aggregates leaving the hospital use small-cell suppression with complementary suppression (v1 `smallcell`),
  never free text from notes.
- PRIV-3: research and contact opt-outs (registry flags, NHI secondary-use opt-out where applicable, hospital
  do-not-contact) are applied before any patient list is produced (FR-M4-6).
- PRIV-4: no PHI to non-local models; the v1 PHI guard is extended with a full surname and given-name list (≥ 5 000
  entries), Taiwan ID-number and phone patterns, and MRN regex from site configuration.
- PRIV-5: data minimisation: T2 tools return only fields needed by the calling step; prompts carry only the chunks
  retrieved for the criterion.
- PRIV-6: retention per record class (Study Card and audit trail: life of the study plus the longest applicable retention
  period, configurable; conversation transcripts outside the regulated record: 90 days; lake snapshots: v1 rules).

### 10.5 Prompt-injection defences

1. Untrusted inputs: inbound email bodies (except the authenticated sender's own text), attachments, protocol documents,
   sponsor questionnaires, EHR notes.
2. Attachments are converted in a network-isolated container; hidden text, comments, metadata, zero-width and Unicode tag
   characters are stripped; files are virus-scanned.
3. Untrusted text enters prompts only inside delimited data blocks with an instruction that it is data; the guard model
   screens every chunk; flagged chunks are excluded and reported.
4. Steps that read untrusted text have no tools that send, write or read PHI outside their scope (dual-LLM pattern: the
   reading model returns structured fields only).
5. Outbound recipients come from the study's delegation log or the original sender, never from document content.

### 10.6 Compliance mapping

Appendix C maps each compliance requirement (CMP-01 … CMP-33, derived from ICH E6(R3) Annex 1 §4, 21 CFR Part 11, EU
Annex 11, GAMP 5 / FDA CSA, ICH M11, CDISC, HL7 FHIR/TW Core, OMOP, Taiwan PDPA, Human Subjects Research Act, NHI rules,
the Taiwan AI Basic Act, ISO/IEC 27001, 42001, OWASP LLM Top 10 and others) to the functional and security requirements
that implement it and to the test that verifies it. The intended-use position is in §2.4; CMP-28 gates any feature that
would change it.

---

## 11. Verification and validation

### 11.1 Test layers (CI must pass all; v1 layers kept)

| Layer | What | Tooling | Gate |
| --- | --- | --- | --- |
| Unit | Deterministic functions, IR v2 semantics, suppression, projection maths, policies | pytest, hypothesis | every commit |
| Contract | Schema drift, OpenAPI compatibility, MCP tool schemas | `make contracts-check`, schemathesis | every commit |
| Integration | Services against the compose test stack (v1 harness, movable ports) | pytest `-m integration` | every merge request |
| End-to-end | Email and console scenarios for stages 1–5 on synthetic data; workflow restart and replay | pytest `-m e2e`, Playwright for console | every merge request |
| Evaluation | §8.5 suites against pinned models on the GB10 dev box | eval-runner | every model/prompt/rule change (G5) and nightly |
| Security | Egress test (root), dependency and image scans, injection red-team suite | v1 `test-egress`, Trivy/Grype, `redteam` suite | nightly, release |
| Performance | §9 targets on the reference profile with a 3 M-patient synthetic population | `tools/bench.py` (extended) | release |

### 11.2 Validation package (risk-based, GAMP 5 2nd ed. / FDA CSA)

Deliverables per release: user requirements (this document, IDs), risk assessment (ISO 14971-style, per function),
traceability matrix (requirement → design → test → result, generated from test markers `@req("FR-M3-6")`), test evidence
from CI, AI credibility files, supplier assessment for models and third-party components, validation summary report.
Change control (G5) re-runs the affected suites and regenerates the matrix.

### 11.3 Go-live acceptance (per site, per scenario)

| Area | Criterion |
| --- | --- |
| Data | Atlas shows coverage ≥ 90 % of active patients for diagnoses, labs and medications in the last 24 months; no blocking quality issues |
| Feasibility | For 5 closed studies: the box's funnel within ±15 % of a manual CRC funnel on the same snapshot (v1 criterion, kept) |
| Pre-screening | `prescreen_patient` gate passed on ≥ 5 closed studies (historical enrollee capture ≥ 0.80, PPV ≥ 0.70) |
| Note judging | `judge_zh_en` gate passed on ≥ 300 dual-annotated items |
| Safety of release | Red-team suite: zero successful capability-bearing attacks |
| Operations | Restore test passed; audit-trail review report produced; access recertification done |

### 11.4 Built-in real-data validation study

TrialBox ships the protocol and tools for its own validation at the site (Appendix B lists the literature anchors):
1. **Retrospective (month 1–2):** for N ≥ 10 closed studies across at least three therapeutic areas, run the frozen
   rulesets on the snapshot at each study's recruitment start; measure historical enrollee capture, criterion-level
   accuracy against CRC adjudication of a random sample (≥ 100 patient–criterion pairs per study), PPV of `strong` and
   `potential`, and time per candidate review.
2. **Silent prospective (month 3–4):** run alongside current practice for recruiting studies; compare lists with CRC
   pre-screening logs; no change to care or contact.
3. **Stepped-wedge or randomised by clinic (month 5–10):** measure eligible-identified rate and enrollment rate with and
   without TrialBox, following the design of the 2025 randomised pre-screening trial (Appendix B); report with
   DECIDE-AI, TRIPOD-LLM and CONSORT-AI.
Requires IRB approval; the box produces the analysis datasets (de-identified) and pre-specified analysis scripts.

---

## 12. Engineering standards

| Topic | Standard |
| --- | --- |
| Languages | Python 3.12 (services), Java 17 (HAPI, cql-translator); TypeScript only if the console ever needs it (not planned) |
| Style and types | ruff (format + lint), mypy --strict, pydantic v2 for every contract (v1 conventions) |
| Repository | Monorepo `trialbox/`; new packages: `services/agent_gateway`, `services/workflows`, `services/console`, `services/data_atlas`, `services/registry_sync`, `services/eval_runner`, `services/mcp_servers`; `libs/tb_policy` (OPA client), `libs/tb_ledger` (audit v2) |
| Requirements traceability | `@req("<ID>")` pytest marker on every test that verifies a requirement; `tools/trace_matrix.py` builds the matrix |
| Architecture docs | C4 views as Structurizr DSL in `docs/architecture/`; ADRs in `docs/adr/NNNN-title.md` (MADR format); this spec is the URS (ISO/IEC/IEEE 29148 structure) |
| Versioning | SemVer for services, rulesets, prompts, schemas; Conventional Commits; signed tags |
| CI/CD | Lint, type, unit, contract on every commit; integration and e2e on merge requests; evaluation nightly on GB10; release builds produce signed images, SBOM, ML-BOM, provenance, offline bundle |
| Security | OWASP ASVS 5.0 Level 2 for console and APIs; OWASP LLM Top 10 2025 controls (§10.3); secrets scanning in CI |
| Quality model | ISO/IEC 25010 characteristics mapped in §9 |
| AI management | ISO/IEC 42001-aligned AI inventory and impact assessment; NIST AI RMF profile; credibility file per AI function |
| Documentation | User guide (zh-TW, en), CRC 1-page guide, admin runbook (v1 RUNBOOK extended), validation package |
| Definition of done | Code + tests (+`@req`) + docs + ADR if architectural + passing eval suites if AI-related + audit events emitted + i18n strings |

---

## 13. Operations

- **Install:** `trialbox install --profile appliance|cluster` from the signed offline bundle; `trialbox doctor` before
  and after.
- **Schedules (defaults):** ingest 02:00, Atlas 03:00, pre-screen per study cadence 04:00, registry sync 05:00, weekly
  status Monday 06:30, evaluation nightly on the dev box, retention 05:30, backup hourly WAL + nightly full.
- **Monitoring:** Grafana dashboards (ingest lag, workflow backlog, gate backlog per approver, model latency and
  throughput, GPU memory, error budget); alerts to the hospital SOC for security events.
- **Updates:** signed bundles (v1 mechanism); model updates only through ChangeWorkflow (G5); rollback to the previous
  bundle and registry entry in ≤ 30 min.
- **Support:** remote support only through the hospital's jump host with MFA and session recording, if the hospital
  allows it; no standing vendor access.
- **Audit-trail review:** monthly report generated for QA (CMP-02).

---

## 14. Positioning and value

The full landscape is in `docs/LANDSCAPE.md`. The points that shape this specification:

1. **Nobody occupies the sovereign, site-side, whole-lifecycle corner.** Hospital-side screening vendors (Triomics,
   Lind, BEKhealth, Trially, Deep 6/Tempus) are cloud or EHR-marketplace products, mostly US and oncology-first.
   Sponsor platforms (IQVIA.ai, Medidata Plus, Veeva AI, ConcertAI, Advarra Site ID) went agentic in 2026 but sit outside
   the hospital. Epic and Oracle are building screening into their EHRs, which does not reach hospitals running their
   own HIS, as most Taiwanese medical centres do. Japan's sovereign-LLM pilots (NTT tsuzumi 2 with Kindai and Chugai;
   Fujitsu with Nagoya and Gifu) show the on-prem pattern in Asia.
2. **Accuracy is not the moat.** Open baselines are strong: TrialGPT (Nature Communications 2024) and its 2026
   multicentre successor, locally hosted TrialGPT variants, Yale's OMOP-based matcher. Value moves to workflow,
   integration, local knowledge, governance and sponsor-grade outputs, which is where this specification spends its
   requirements.
3. **The funnel leaks after the list.** In published deployments only a small fraction of eligible patients enroll; most
   value is lost at approach and consent. M4 routing to the next appointment, M6 tracking with reasons, and M7 conduct
   support target that loss.
4. **Feasibility questionnaires are a measurable burden.** About 11 questionnaires a month per site at about 4 hours each,
   mostly redundant (ASCO/AACI). M3 autofill with provenance turns hours into minutes and makes the answers auditable.
5. **Taiwan has tailwinds and no incumbent product.** The national alliance of trial centres (launched December 2025) runs
   feasibility by hand; MOHW plans FHIR exchange and federated patient and site finding; the NHI data act adds opt-out
   rights. A hospital-owned box that speaks FHIR, OMOP and email fits all three.
6. **Payer logic is a unique wedge.** NHI reimbursement rules, prior authorisation (TWPAS) and the standard-of-care vs
   research billing split are unoccupied by every competitor reviewed; v1 already implements the first two.

**Value to the hospital** (to be measured by §11.4, not assumed): coordinator hours saved per questionnaire and per
pre-screen; sponsor studies won through faster, evidence-based feasibility; enrollment per study; fewer screen failures;
a validated capability the hospital owns and can offer to other sites.

---

## 15. Delivery plan

### 15.1 Releases

| Release | Weeks | Scope | Exit criteria |
| --- | --- | --- | --- |
| **R1 — Agent on real data** | 1–10 | M0 Atlas + streaming ingest + terminology; M1 dual extraction + IR v2 core (event anchors, counts, seq); M3 packet + questionnaire autofill + registry sync; M4 tiers + routing + decisions; DBOS workflows + gates G0–G3 + G5; agent-gateway (email); console (approvals, Study Card, evidence); model registry + gateway; eval-runner with suites; audit ledger v2; v1 NAV/COHORT carried | §11.3 data, feasibility and judging criteria met on real data for ≥ 5 closed studies; retrospective validation (§11.4 step 1) analysed |
| **R2 — Recruitment engine** | 11–20 | M2 what-if and relaxation; M4 portfolio clinic-day lists; M5 patient→trial; M6 tracking + forecasting + site history; Teams/LINE notifications; hourly delta; TWPAS IG update; optional Hermes front end after security review | Silent prospective study complete; weekly status emails in use for ≥ 10 studies |
| **R3 — Conduct and data** | 21–34 | M7 start-up checklist, coverage analysis, visit windows, deviation and AE candidates; M8 abstraction and eCRF pre-fill; M11 OMOP view, federated feasibility, trial-ready cohorts; MCP/FHIR machine interface for sponsor and national requests | Abstraction field agreement ≥ 0.95 on 3 closed studies; stepped-wedge study started |
| **R4 — Close the loop** | 35–44 | M9 retrospectives, registry deadlines, archive export; forecast calibration report; packaging for other hospitals | Calibration report; second site installed from the offline bundle |

### 15.2 First sprint (weeks 1–2): immediately codeable tasks

Paths are relative to `trialbox/` on the current branch. Each task ends with tests carrying `@req` markers.

| # | Task | Files | Done when |
| --- | --- | --- | --- |
| S1-1 | Add v2 schemas: `criterion_ir` v2 (superset), `study`, `request`, `evidence`, `candidate`, `feasibility_packet`, `approval_gate`, `signature`, `model_registry`, `eval_report`; regenerate contracts | `schemas/v2/*.schema.json`, `libs/tb_contracts/v2/` | `make contracts-check` passes; all v1 rulesets validate against IR v2 |
| S1-2 | IR v2 semantics: event-anchored windows, `count_unit: episodes`, `seq`, `atleast`, `absence`; CQL and SQL templates; ATOMS_V2 fixtures through the equivalence gate | `services/criteria_compiler/semantics.py`, `compile_cql/templates/`, `compile_sql/templates/`, `rulesets/ATOMS_V2/` | CQL≡SQL 100 % on ATOMS_V2; `semantics.py:52` event-anchor rejection removed |
| S1-3 | PostgreSQL + DBOS: add `postgres` service, `services/workflows/` with `FeasibilityWorkflow` wrapping the existing FEAS scenario, gates as DBOS events, `POST /v2/gates/{id}/decision` | `deploy/docker-compose.yml`, `services/workflows/` | e2e: FEAS by email pauses at G1, resumes after decision; kill -9 mid-run resumes without duplicate steps |
| S1-4 | Agent gateway: move mail intake behind `POST /v2/messages`; `classify_intent` prompt + router role; restate-before-act reply; v1 grammar passthrough | `services/agent_gateway/`, `prompts/classify_intent.yaml`, `services/mail_gateway/` | e2e: free-text "can we do this study?" with PDF starts FEAS; v1 subjects unchanged |
| S1-5 | Console skeleton: SSO stub (Keycloak dev realm), approvals list, sign with re-auth, Study Card view, candidate evidence view | `services/console/` (FastAPI + Jinja2 + htmx) | Playwright test signs G1 and G3 |
| S1-6 | Data Atlas v0: profile tables of the canonical lake, coverage per domain, computability per atom type, XLSX export | `services/data_atlas/` | Atlas report on synthetic site A; computability attached to compiled criteria |
| S1-7 | Model registry + gateway: `models/registry.yaml`, LiteLLM config with role aliases, `tb_common.llm` resolves roles; manifest records weight SHA | `models/`, `deploy/litellm.yaml`, `libs/tb_common/llm.py` | Footer/audit show the actually served model (fixes v1 mismatch) |
| S1-8 | Eval-runner v0 + suites `sql_cql`, `redteam`, `intent` (synthetic) | `services/eval_runner/`, `eval/` | Suite reports written; CI job on GB10 profile defined |
| S1-9 | Audit ledger v2 in Postgres (append-only trigger, hash chain, migration of v1 day files, WORM anchoring to MinIO Object Lock) | `libs/tb_ledger/`, migration tool | `audit_verify` passes across migrated and new events |
| S1-10 | Questionnaire autofill v0: XLSX questionnaire → field map (CRC-confirmed) → filled file + provenance sheet | `services/orchestrator/scenarios/questionnaire.py` | e2e on two sample sponsor templates |
| S1-11 | Registry sync: ClinicalTrials.gov API v2 pull for configured conditions/locations into a local index; competing-trial section in the packet | `services/registry_sync/` | Packet lists competing trials from the local index; no outbound call at packet time |
| S1-12 | Streaming ingest: chunked adapter with bounded memory | `services/adapter/pipeline.py` | 3 M-patient synthetic ingest under 8 GB RSS |

### 15.3 Team and effort (reference)

R1 needs about 4 engineers (backend ×2, data/terminology ×1, ML/eval ×1), 0.5 QA/validation, a CRC champion (20 %),
a data steward (30 %) and an investigator sponsor per pilot study. A coding agent can execute the sprint tasks against
this specification; humans own gates, validation and the site relationship.

---

## 16. Open decisions

| # | Decision | Options | Owner | Needed by |
| --- | --- | --- | --- | --- |
| OD-1 | Primary data source for R1 | HIS read replica views; research database (CGRD-type) export; both (research DB for feasibility, HIS for screening) | Data steward + IT | Week 1 |
| OD-2 | Relationship to third-party screening vendors at the site | Independent; complementary scope (for example internal, IIT and non-oncology studies); integrated as one engine behind TrialBox gates | Research office + legal | Week 2 |
| OD-3 | Hardware profile | Appliance server; time-share of an existing DGX; both (dev on GB10) | IT | Week 2 |
| OD-4 | Hermes Agent as front end | Not in R1; evaluate for R2 after security review | Information security | Week 10 |
| OD-5 | Default small-cell threshold and suppression policy | n<5; n<10; per IRB | IRB | Week 4 |
| OD-6 | IRB pathway for pre-screening on identified data | Umbrella approval for pre-screening as research operations; per-study approval | IRB + legal | Week 4 |
| OD-7 | Sponsor-facing pricing for feasibility packets and screening | Free (internal service); per-study fee invoiced by the hospital | Research office | R2 |
| OD-8 | Planner model licence | Apache/MIT models only; allow models with custom licences after legal review | Legal | Week 3 |

---

## Appendix A — Lifecycle coverage matrix

● covered · ◐ partial · ○ not in scope. Release in brackets.

| Stage | v1 | v2 | Main requirements |
| --- | --- | --- | --- |
| Site readiness / data | ◐ | ● [R1] | FR-M0-* |
| Protocol intake | ● | ● [R1] | FR-M1-* |
| Protocol optimisation | ◐ | ● [R2] | FR-M2-* |
| Feasibility + questionnaire | ● | ● [R1] | FR-M3-* |
| Site selection support | ○ | ◐ [R2] | FR-M0-11, FR-M3-5 |
| Start-up | ○ | ◐ [R3] | FR-M7-1, FR-M7-2 |
| Pre-screening | ● | ● [R1–R2] | FR-M4-* |
| Patient → trial matching | ○ (TrialGPT separate) | ● [R2] | FR-M5-* |
| Consent / eConsent | ○ | ○ (tracked only) | FR-M6-1 |
| Enrollment tracking | ◐ | ● [R2] | FR-M6-* |
| Visits, deviations | ○ | ◐ [R3] | FR-M7-3 |
| Safety (AE candidates) | ○ | ◐ [R3] | FR-M7-4 |
| Data capture (EHR→eCRF) | ○ | ● [R3] | FR-M8-* |
| Close-out, registry, archive | ○ | ● [R4] | FR-M9-* |
| NHI reimbursement / TWPAS | ● | ● [R1–R2] | FR-M10-* |
| Networked / federated research | ● (alliance) | ● [R3] | FR-M11-* |

## Appendix B — Evidence base (selected)

| Design choice | Evidence |
| --- | --- |
| Criterion-level judgement with quoted evidence, deterministic aggregation | Jin et al., TrialGPT, *Nat Commun* 2024, doi:10.1038/s41467-024-53081-z (42.6 % less screening time); Unlu et al., RECTIFIER, *NEJM AI* 2024, doi:10.1056/AIoa2400181; Wornow et al., *NEJM AI* 2025, doi:10.1056/AIcs2400360 (plausible rationales for wrong answers → verify quotes) |
| AI pre-screening raises identification and enrollment | Unlu et al., randomised trial, *JAMA* 2025;333(12):1084–7, doi:10.1001/jama.2024.28047 (eligible identified 20.4 % vs 12.7 %) |
| LLM extracts, rules decide | Loaiza-Bonilla et al., *ESMO Real World Data Digit Oncol* 2026, doi:10.1016/j.esmorw.2026.100706 (prospective, 3 804 patients; F1 0.82 vs 0.47 for zero-shot GPT-4); Lee et al., *JMIR Med Inform* 2025, doi:10.2196/71252 (LLM-generated OMOP SQL hallucination 21–50 %) |
| Local open-weight models are adequate | Syed et al., *JAMIA* 2026, doi:10.1093/jamia/ocag006 (local TrialGPT: sensitivity 81.8 %, specificity 97.8 %); Nievas et al., *JAMIA* 2024, doi:10.1093/jamia/ocae073 |
| Criteria parsing quality targets | Park et al., Criteria2Query 3.0, *J Biomed Inform* 2024, doi:10.1016/j.jbi.2024.104649; Datta et al., AutoCriteria, *JAMIA* 2024, doi:10.1093/jamia/ocad218 |
| Data-driven criterion relaxation | Liu et al., Trial Pathfinder, *Nature* 2021, doi:10.1038/s41586-021-03430-5 |
| Calibrated feasibility, not PI guesses | Benjamin et al., *PLoS One* 2022, doi:10.1371/journal.pone.0262862 (PI forecasts poorly calibrated); Carlisle et al., *Clin Trials* 2015, doi:10.1177/1740774514558307 |
| Track the funnel after matching | Verhagen et al., *Surgery* 2026, doi:10.1016/j.surg.2025.109915 (73.5 % of AI matches did not enroll, with reasons) |
| Open matching baselines | Abdallah et al., TrialMatchAI, *Nat Commun* 2026, doi:10.1038/s41467-026-70509-w; Fang et al., arXiv:2609.01202 (2026, preprint) |
| Feasibility questionnaire burden | ASCO/AACI Clinical Research Initiative 2020 abstract "Reducing burdens of site feasibility assessments" |
| Reporting of evaluations | DECIDE-AI (Vasey et al., *Nat Med* 2022), TRIPOD-LLM (Gallifant et al., *Nat Med* 2025), CONSORT-AI (Liu et al., *Nat Med* 2020) |

`docs/LANDSCAPE.md` carries the full reference list.

## Appendix C — Compliance traceability

| CMP | Source | Requirement summary | Implemented by | Verified by |
| --- | --- | --- | --- | --- |
| CMP-01 | 21 CFR 11.10(e); ICH E6(R3) A1 §4; EU Annex 11 §9 | Audit trail: who, what (old/new), when (UTC), why; append-only, hash-chained, cannot be disabled; exportable | §5.1 `audit_event` v2, S1-9 ledger, FR-AG-6 | ledger tests, `audit_verify` |
| CMP-02 | E6(R3) §4.2 | Periodic audit-trail review with evidence | §13 monthly report | D |
| CMP-03 | 21 CFR 11.10(d),(g); ISO 27001 A.5.15–5.18 | Unique accounts, SSO, MFA, RBAC/ABAC by study, recertification | §10.1, SEC-3 | policy tests, recertification report |
| CMP-04 | 21 CFR 11.50–11.200; Taiwan Electronic Signatures Act | E-signature with meaning, bound to record hash, re-authentication | §5.1 `signature`, §7.1 gates | console e2e |
| CMP-05 | E6(R3) §4.3; GAMP 5 2nd ed.; FDA CSA | Risk-based validation, traceability, change control | §11.2, ChangeWorkflow (G5) | validation package |
| CMP-06 | FDA AI credibility draft; EMA reflection paper; FDA–EMA AI principles 2026 | AI credibility file per AI function | §8.5 | eval reports |
| CMP-07 | FDA CDS 2026; AI Basic Act transparency | Evidence and uncertainty shown for every output | FR-M4-3, §5.4 | e2e evidence view |
| CMP-08 | E6(R3) investigator responsibility | Box never sets eligible/enrolled; investigator signs | G3/G4, FR-M4-5, FR-M6-1 | e2e, I |
| CMP-09 | E6(R3) §4.1 | No unblinding data | FR-M7-5 | I, T |
| CMP-10 | ICH M11; CDISC USDM | Protocol versioning; amendment re-evaluation | FR-M1-1, FR-M1-7 | T |
| CMP-11 | HL7 FHIR R4; TW Core; SMART; CDS Hooks | FHIR conformance, pinned IG versions | adapter (v1), FR-M3-9 | validator runs |
| CMP-12 | CDISC CDASH, ODM v2 | eCRF export with lineage | FR-M8-1, FR-M8-2 | T |
| CMP-13 | OMOP CDM 5.4; ICH M14 | Counts carry data cut, query hash, logic | §5.5 manifest, FR-M11-2 | T |
| CMP-14 | Taiwan PDPA; Human Subjects Research Act; HIPAA §164.514 | Aggregates only, suppression, no free text out | PRIV-2, FR-M3-7 | T |
| CMP-15 | PDPA amendments | Breach detection and notification workflow | §13 SOC alerts, runbook | D |
| CMP-16 | PDPA; MOHW EMR rules | Data residency; no PHI to external models | PRIV-4, SEC-1 | egress test |
| CMP-17 | NHI secondary-use opt-out; hospital policy | Opt-outs honoured before lists | FR-M4-6, PRIV-3 | T |
| CMP-18 | E6(R3); FDA eConsent Q&A | eConsent out of scope; consent state tracked by signed action | FR-M6-1 | I |
| CMP-19 | ICH E2A; Taiwan SUSAR rules | AE candidates surfaced within 24 h; investigator decides | FR-M7-4 | T |
| CMP-20 | E6(R3) deviations | Deviation candidates for CRC confirmation | FR-M7-3 | T |
| CMP-21 | 21 CFR 312.62; Medical Care Act | Retention schedule, legal hold, archive export | PRIV-6, FR-M9-3 | T |
| CMP-22 | E6(R3) §4.3; ISO 27001 A.8.13–14 | Backup, restore, RPO/RTO | NFR-8 | restore test |
| CMP-23 | ISO 27001; ASVS 5.0 L2 | Security controls | SEC-1…SEC-8 | scans, pen test |
| CMP-24 | OWASP LLM Top 10 2025 | LLM controls | §10.3, §10.5 | redteam suite |
| CMP-25 | SLSA; CycloneDX/SPDX | Signed builds, SBOM, ML-BOM | SEC-5 | release checklist |
| CMP-26 | OpenTelemetry; ISO 25010 | Observability separate from audit | NFR-15 | I |
| CMP-27 | ISO/IEC 42001; NIST AI RMF; Taiwan AI Basic Act | AI inventory, impact assessment, owner, training | §12 | I |
| CMP-28 | MDR/TFDA intended use; MDCG 2019-11 | Intended-use control; gate on drift features | §2.4 | design review |
| CMP-29 | ISO/IEC/IEEE 42010; C4 | Architecture documentation, ADRs | §4, §12 | I |
| CMP-30 | ISO 25010; ISO/IEC/IEEE 29148 | Quantified NFRs traceable to tests | §9, §11 | trace matrix |
| CMP-31 | 42 CFR 11; EU CTR Art. 37 | Registry deadlines for hospital-sponsored studies | FR-M9-1 | T |
| CMP-32 | NHI / TWPAS | Coverage analysis; research items not billed to NHI | FR-M7-2, FR-M10-* | T |
| CMP-33 | TransCelerate SIP; ASCO FQ practice | Site profile reused across questionnaires; releases logged | FR-M0-11, FR-M3-6, FR-M3-8 | T |

## Appendix D — Email grammar (v2 additions)

The v1 ABNF (`SPEC.md` §5) is unchanged. v2 adds these commands; free text is classified into the same commands.

```
command   =/ "QFILL" SP study                    ; fill the attached questionnaire
command   =/ "WHATIF" SP study SP change *(";" change)
change    = ("drop" SP criterion-id) / ("set" SP criterion-id SP param "=" value)
command   =/ "CONFIRM" SP pid *(SP pid)          ; G3, PI only, reply on a candidate packet
command   =/ "REJECT" SP pid SP reason-code [SP free-text]
command   =/ "DEFER" SP pid [SP date]
command   =/ "STATE" SP pid SP state [SP date]   ; G4 pending signature in console
state     = "contacted" / "consented" / "screened" / "randomized" / "declined" / "screen_failed" / "withdrawn"
command   =/ "MATCH" SP mrn                      ; patient → trial, delegated clinicians only
command   =/ "ATLAS" [SP domain]                 ; data availability summary
```

Reason codes for REJECT: R01 does not meet inclusion on chart review · R02 meets exclusion · R03 clinically
inappropriate · R04 patient preference known · R05 enrolled elsewhere · R06 data outdated · R07 other (free text required).

## Appendix E — Online demo

A hosted demo on fully synthetic data (600 patients generated for v1 tests; names, ID numbers and phone numbers removed)
shows stages 1–6: EMR connection summary, criteria intake with live parsing by a Claude model for pasted text, feasibility
with funnel, drop-one analysis, enrollment projection and a filled sponsor questionnaire, candidate list with per-criterion
evidence, delivery to the PI behind an approval gate, and a simulated enrollment tracker. It uses the same three-valued
criterion logic and tier rules as §5.4 in simplified form. It is for demonstration only and is not the product; no real
patient data is ever loaded into it.

## Appendix F — References

Regulatory and standards sources (selection): ICH E6(R3) Principles and Annex 1 (Step 4, 6 Jan 2025) and Annex 2 (3 Jun
2026); ICH M11 (Step 4, 19 Nov 2025); ICH M14 (4 Sep 2025); CDISC USDM v4.0; HL7 FHIR R4, TW Core IG 1.0.0, TWPAS; HL7
Vulcan Schedule of Activities and RWD IGs (STU1); OMOP CDM 5.4; 21 CFR Part 11 and FDA Part 11 Q&A (Oct 2024); FDA
Computer Software Assurance guidance (Sep 2025); FDA CDS guidance (Jan 2026); FDA–EMA good AI practice principles (Jan
2026); EU AI Act and Digital Omnibus (2026); Taiwan Personal Data Protection Act (amended Nov 2025), Human Subjects
Research Act, Medical Care Act, AI Basic Act (Jan 2026), NHI data provisions; GAMP 5 2nd ed. and ISPE GAMP AI Guide
(2025); ISO/IEC 27001, 42001, 25010, ISO/IEC/IEEE 29148, 42010; OWASP ASVS 5.0 and LLM Top 10 2025; SLSA; CycloneDX.

Literature: Appendix B and `docs/LANDSCAPE.md` §6.

Code: TrialBox v1 (`trialbox/`, this repository), TrialGPT local port (`trialgpt/`, this repository), Hermes Agent
(github.com/NousResearch/hermes-agent), DBOS Transact, LiteLLM, vLLM, SGLang, HAPI FHIR, DuckDB.
