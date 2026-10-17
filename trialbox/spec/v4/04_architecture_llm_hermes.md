## 4. Architecture

v4 keeps the v3 deterministic core and its batch, filter-first design. It changes four things around that core:
- three deployment topologies (§4.1);
- a governed LLM control plane between every caller and every model (§8);
- Hermes Agent as the front door, behind a TrialBox-owned channel relay (§9);
- a staged data platform in place of the single adapter (§5).

This section fixes placement, interfaces and boundaries. Normative detail for another part's containers is in that part.

### 4.1 Deployment topologies

All topologies run the same signed image set. The site declares `deployment.topology: A | B | C` in `site_params.yaml`.

| Topology | Where the appliance runs | Model endpoints the gateway may call | Classes that may leave the perimeter to a model | Keys |
| --- | --- | --- | --- | --- |
| **A** On-prem appliance (default) | Hospital data centre, on one hardware profile (§4.8) | on-box serving only | none | TPM-sealed key service, or the hospital HSM/KMS (§14) |
| **B** Hospital cloud tenant | The hospital's own tenant, in-country, on private networking. Taiwan: AWS Asia Pacific (Taipei) `ap-east-2` or Google Cloud `asia-east1` (Azure Taiwan North not generally available, *uncertain*). Japan: Tokyo or Osaka regions. | self-hosted serving on the tenant's GPU instances. These count as internal: the hospital controls instance, keys and network. | none | customer-managed keys in the tenant KMS/HSM; no vendor access path |
| **C** Hybrid | A or B, plus a model egress policy | as A or B, plus external endpoints approved by the routing policy (§8.5) | D0; D1 only with the sponsor's written consent per protocol; D2 only with a re-identification risk assessment, PDPA cross-border analysis and IRB/DPO sign-off (§7). D1 and D2 are off by default. | as A or B |

D3 and D4 never reach an external model in any topology. Three independent controls enforce this:
1. the routing policy (§8.5);
2. the gateway's PHI tripwire (§8.6);
3. network egress rules that let only `tb-gateway` reach a model endpoint.

```
 Topology A
 ┌──────────────────────────────── Hospital data centre ────────────────────────────────────┐
 │ user VLANs ──HTTPS──▶ [signing-listener]     mgmt VLAN ──▶ [admin-listener] [host mgmt]   │
 │ Exchange ◀─IMAP/SMTP─▶ [channel-relay] ◀── DMZ reverse proxy + WAF ◀── Teams/LINE webhooks│
 │ HIS DB ─views/CDC─▶ ┐                                                                     │
 │ HL7 engine ─MLLP/TLS▶├─▶ [ TrialBox appliance zone: all containers, all models on box ]   │
 │ FHIR server ─Bulk──▶ ┘           ──syslog──▶ SIEM    NTP ──▶    ──▶ WORM backup           │
 └───────────────────────────────────────────────────────────────────────────────────────────┘
  egress allowlist: mail relay · NHI TWPAS · ClinicalTrials.gov/MOHW (GET) · Teams/LINE APIs (relay) · update mirror

 Topology B
 ┌──── Hospital campus ────┐  private link/IPsec  ┌──── Hospital tenant (in-country region) ────────┐
 │ HIS, HL7 engine, FHIR,  │══════════════════════│ private subnets, no public IP                   │
 │ Exchange, IdP, SIEM,    │  (no internet path)  │ [appliance containers]  [GPU instance: serving] │
 │ identity vault (D4) per │                      │ KMS/HSM (customer keys) · object-lock bucket    │
 │ §7                      │                      │ egress: NAT + allowlist proxy, same list as A   │
 └─────────────────────────┘                      └─────────────────────────────────────────────────┘

 Topology C (on A or B)
 [caller] ─▶ [tb-gateway] ─D0–D4─▶ [serving router] ─▶ on-box / tenant models
                  └─D0, D1*, D2* only─▶ [egress proxy: allowlisted FQDNs] ─▶ approved external endpoints
                   tripwire · redaction · budget · audit                  * conditions in §7 and §8.5
```

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-B6 | One signed image set and one configuration schema MUST serve topologies A, B and C. Topology differences MUST be expressed only in `site_params.yaml` (`deployment.*`, `routing.*`, `keys.*`), never in code branches. | I | MS0 |
| NFR-B7 | `trialbox doctor` MUST verify that the declared topology matches what it observes: egress rules, external routes, key-service type, and in B the absence of public addresses. A mismatch blocks start-up. | T | MS0 |
| NFR-B8 | In topology B, the appliance MUST run on private subnets with no public IP. It MUST use customer-managed keys and private endpoints for KMS and object storage, and reach the hospital only over private connectivity. Provider support access MUST be disabled or contractually excluded, and recorded in the install record. | I | MS4 |
| NFR-B9 | In every topology, only `tb-gateway` MAY connect to a model endpoint (on-box port, tenant port or external FQDN). Any other attempt MUST be dropped and raise an egress-drop alarm (§14). | T | MS0 |
| NFR-B10 | D3 and D4 MUST NOT reach an external model. Before any topology C route is enabled, the `redteam` suite MUST show zero class violations for that route across mislabelled-class, missing-label, fallback and header-forgery cases. | T | MS1 |
| NFR-B11 | A topology change, or the addition or removal of an external route, MUST be a G5 change with security sign-off (§14). Every run manifest MUST record the routing-policy version in force (§6). | I | MS1 |

### 4.2 System context (C4 level 1)

```
                   ┌───────────────────────────── Hospital ────────────────────────────────────┐
  CRC, PI, Sub-I,  │ email · Teams · LINE nudges        ┌──────────────────┐                   │
  research office, ┼───────────────────────────────────▶│                  │── NHI TWPAS ──────┼─▶ NHI (optional)
  steward, IRB/QA  │◀─ replies, packs, gate requests ───│                  │── GET ────────────┼─▶ ClinicalTrials.gov, MOHW
                   │   signing page · review page       │     TrialBox     │                   │
  Administrator ───┼── control plane + CLI (mgmt VLAN) ─▶│  topology A/B/C  │── C only ─────────┼─▶ approved external models
  HIS, LIS, RIS, ──┼── views, CDC, HL7 v2, FHIR Bulk ──▶│                  │                   │   (D0–D2)
  research DB/TRE  │                                    │                  │── syslog/CEF ─────┼─▶ SIEM
  IdP (Entra/AD) ──┼── OIDC (signers, admins) ─────────▶│                  │                   │
  EHR (optional) ──┼── CDS Hooks patient-view ─────────▶└──────────────────┘                   │
                   └────────────────────────────────────────────────────────────────────────────┘
   Sponsors and CROs never connect: a named site person sends released packs (§12).
   OpenRouter is reachable only from the development environment, for D0 bake-offs (§8.10).
```

| External system | Protocol | Highest class | Container |
| --- | --- | --- | --- |
| Hospital mail | IMAP/TLS, SMTP submission, DMARC results | D4 (packets to delegated staff) | channel-relay |
| Teams | Bot Framework endpoint via the DMZ proxy; Graph for proactive messages | Outbound D1 (cards, counts; no PHI, no study ids, §3). Inbound text PHI-tolerant: tokenised at the relay before any model (D3), stored redacted (§3.4.1, §7.2) | channel-relay |
| LINE Messaging API | signature-verified webhook via the DMZ proxy; push and reply APIs | D0/D1 nudges; inbound text gets a canned pointer and never reaches a model | channel-relay |
| HIS DB, HL7 engine, FHIR server | views and CDC; MLLP/TLS; Bulk `$export` with SMART Backend Services (§5) | D4 | ingest-workers, cdc-reader, hl7-listener |
| Research DB / TRE | de-identified SQL or CSV export | D2 | ingest-workers, TRE zone (§7) |
| IdP | OIDC; group export for allowlists | D1 | listeners, channel-relay |
| EHR (MS5, optional) | CDS Hooks 2.0 `patient-view` | D3 (card only) | signing-listener |
| SIEM | syslog/CEF | D1 | otel-collector, audit-ledger |
| NHI TWPAS | per M10 (§10) | D4 | orchestrator |
| ClinicalTrials.gov API v2, MOHW | HTTPS GET, no request body | D0 | registry-sync |
| External model endpoints (C only) | HTTPS via `tb-egress` | D2 | tb-gateway |

### 4.3 Containers (C4 level 2)

```
 ┌─ Channel DMZ namespace ────────────────────┐  ┌─ Application zone ──────────────────────────────────┐
 │ channel-relay ◀─▶ cdr-sandbox (no network) │  │ orchestrator: workflows, gates, outbox, passes,      │
 │   │ engine = hermes | native               │  │   intake; matching (cascade, registry match)         │
 │ hermes ──── or ──── converse-native        │  │ criteria-compiler · doc-parser · registry-sync       │
 └───┼──────────────────────┼─────────────────┘  │ frontdoor-mcp ◀── hermes (MCP over mTLS)             │
     │ MCP + LLM calls only │                    │ signing-listener · admin-listener (mgmt VLAN only)   │
     ▼                      ▼                    └──────────────────────────┬──────────────────────────┘
 ┌─ Model zone ──────────────────────────────────────────┐                  │ steps, T1/T2 tools
 │ tb-gateway ─▶ serving router ─▶ llm-serving (vLLM)     │◀─────────────────┤
 │   │  ▲        embed-service · guard-service            │  ┌─ Data zone ─────▼────────────────────────────────┐
 │   │  └── model-registry (alias → pinned build)         │  │ hl7-listener · cdc-reader · ingest-workers L0–L3 │
 │   └──▶ tb-egress (all topologies; models in C only)    │  │ pid-service + vault · terminology · atlas        │
 └────────────────────────────────────────────────────────┘  │ lake L4/L5 · fhir-store · omop-db · object store │
 ┌─ Assurance zone ───────────────────────────────────────┐  │ postgres (orch, intake, channel, gateway, ledger)│
 │ audit-ledger · lineage-store · otel-collector ·        │  └──────────────────────────────────────────────────┘
 │ trace-store · prometheus · backup-agent                │
 └────────────────────────────────────────────────────────┘
```

Each component is a supplier component to validate (§15), so v4 adds only what the owner's requirements need.

| Container | Responsibility | Tech | State | Highest class | Change from v3 |
| --- | --- | --- | --- | --- | --- |
| **channel-relay** | All transports (IMAP/SMTP, Teams bot, LINE webhook); sender auth; identity assertions; quote stripping; tokenisation; grammar diversion; LINE canned pointer; outbound DLP and delivery | Python, `services/channels/relay/` (`tb_relay`), from v1 `mail_gateway` | Postgres `channel`; object store | D4 | replaces mail-gateway and notify |
| **cdr-sandbox** | Attachments to text or PDF/A; hidden text, metadata and invisible Unicode removed; ClamAV | LibreOffice headless, PDF extraction; no network | ephemeral | D4 | new container |
| **hermes** | Conversation engine (§9) | Hermes Agent, pinned (§9.5); profiles (`tb-staff`, `tb-line`, `tb-admin`) and plugins in `integrations/hermes/` | encrypted `state.db` | D1, and D3 for tokenised conversation text (on-prem routes only, FR-CONV-8); storage treated as D4 | new |
| **converse-native** | Native engine: grammar, `classify_intent` proposals, deterministic status and help | `services/channels/native/` (`tb_converse`) | Postgres `intake` | D1, and D3 for tokenised text (on-prem routes only) | v3 intake refactored |
| **frontdoor-mcp** | The eight front-door tools (§9.3), run in the orchestrator's policy context | MCP SDK, spec 2026-07-28, `services/frontdoor_mcp/` (`tb_frontdoor`) | none | D1 out (T0/T1) | new |
| orchestrator | Durable workflows, gates G0–G6, outbox, schedules, pass scheduler (`passes.py`), intake grammar and confirmation | v3 code (§11) | Postgres `orch`, `intake` | D4 | extended |
| **matching** | Cascade S0–S5 with S2b; judgement cache; trial → patients and patient → trials; registry match from the TrialGPT port | `services/matching/` (`cascade/`, `registry_match/`) in orchestrator workers; calibration and abstention in `services/orchestrator/calibration/` | Postgres `matching` | D3 | new package |
| criteria-compiler | IR v3, criterion library ("match-then-draft"), CQL/SQL, equivalence gate, canonical hashes, filter classes | v3 code + IR v3 (§6) | Git, Postgres `library` | D1 | extended |
| doc-parser | PDF/DOCX/XLSX/ICH M11/USDM → canonical text, sections, tables; OCR for scanned zh-TW/ja | v3 code | none | D1 | kept |
| **signing-listener** | Level B signing page; optional review page; optional CDS Hooks service | FastAPI + Jinja2, no third-party JS; own port; `services/console/`, `services/cds_hooks/`; ASVS 5.0 L3 for the signing page, L2 for the review page and CDS card (§14.2.3) | via orchestrator | D3 | own listener |
| **admin-listener** | Admin control plane (§3): health, passes, registry and routes (propose → G5), kill switches, engine switch, audit integrity, DR drill | FastAPI + Jinja2, `services/console/`; mgmt VLAN; IdP OIDC with phishing-resistant MFA; ASVS 5.0 L3 (§14.2.3) | none | D1 | console → control plane |
| registry-sync | ClinicalTrials.gov and MOHW index | v3 worker | Postgres `registry` | D0 | kept |
| **hl7-listener** | MLLP/TLS for ADT, SIU, ORU, MDM; MSH-10 de-duplication; ACK; writes L0 | `services/dataplat/sources/hl7v2/` (MLLP listener entry point) | L0 | D4 | new (§5) |
| **cdc-reader** | Optional log-based CDC on DBA-approved tables; idempotent on (LSN/SCN, key) | Debezium Server without Kafka, or change-table polling (§5) | L0; offsets in Postgres | D4 | new (§5) |
| ingest-workers | L0 → L3 with contracts, reconciliation and the publish gate | v1 adapter, restaged (§5) | object store, Postgres `ingest` | D4 | restructured |
| **pid-service** + vault | MPI merges, pid derivation, purpose-logged lookups, erasure tombstones | Python: `services/vault/` (`tb-vault`, own PostgreSQL instance, §7.5) and the MPI client and linkage in `services/dataplat/mpi/`; vault key (§14) | Postgres `vault` (own role) | D4 | extended |
| **terminology** | `$validate-code`, `$lookup`, `$translate`, `$expand`; editions pinned per snapshot | `tb-terminology` facade over HAPI terminology, or Snowstorm where SNOMED CT is licensed (§5) | own volume | D0 | new |
| atlas | Profiling, mapping proposals, DQ scorecard, catalogue, lexicon mining | v3 module | Postgres `atlas` | D2 | extended |
| lake | L4 snapshots and L5 serving: guarded SQL, CJK FTS, sentence index for S2b, hybrid retrieval | DuckDB over Parquet (§5) | lake volume | D3 | extended |
| fhir-store | CQL verification sample; FHIR read API | HAPI FHIR JPA | fhir-db | D3 | kept |
| **omop-db** | OMOP CDM 5.4 per snapshot; read-only role for ATLAS, Achilles, DQD | PostgreSQL 16 | own volume | D3 (D2 views for TRE) | new (ADR-V4-10) |
| **lineage-store** | OpenLineage events per stage and step; lineage-id resolution | Postgres `lineage`; Marquez export optional (§5) | Postgres | D1 | new |
| **tb-gateway** | The only path to any model (§8.2) | FastAPI + httpx, `services/gateway/` (`tb_gateway`) | Postgres `gateway`; recorded outputs | D4 in transit | new |
| **model-registry** | Builds, cards, statuses, prompt registrations; alias map for the gateway | `services/registry/` (`tb_registry`); Git `models/` | Postgres `models` | D1 | new |
| **serving router** | Loads builds per pass; one endpoint per resident build; prefix-aware routing on multi-replica profiles | `services/gateway/serving.py` + pass scheduler | none | D4 in transit | new |
| llm-serving | Resident builds; JSON-schema constrained; salted prefix cache | vLLM; llama.cpp on P-Mac | read-only model volume | D4 in transit | extended |
| embed-service | bge-m3; bge-reranker-v2-m3 | v1 | none | D3 in transit | kept, behind the gateway |
| **guard-service** | Presidio with TW/JP recognisers, name dictionaries, injection classifier | `services/guard/` (`tb_guard`) | none | D4 in transit | new |
| **trace-store** | Redacted traces, 90 days, apart from the ledger | Langfuse v3 self-hosted (ADR-V4-14) | own Postgres, ClickHouse, bucket | D3 (redacted) | new |
| otel-collector | OTLP intake; pinned GenAI semconv; content drop outside the PHI zone | OpenTelemetry Collector | none | D3 in transit | new |
| audit-ledger | Hash-chained, append-only; external anchor (§14) | Postgres `ledger`, INSERT-only role | Postgres | D3 (no names) | kept |
| postgres, object store | Schemas above; landing, packets, recorded outputs; object-lock bucket | PostgreSQL 16; MinIO (A), tenant storage (B) | volumes | D4 | extended |
| prometheus | Metrics and alerts | pinned image | volume | D1 | made explicit |
| backup-agent | 3-2-1 backups with an immutable copy (§14, §18) | pinned image | none | D4 | new |
| **tb-egress** | Deny-by-default outbound proxy for every container in **all topologies** (SEC-40); host/SNI allowlist per topology; model endpoints in topology C only | pinned Envoy; policy `deploy/egress_policy.yaml` | none | D4 in transit (D0–D2 to model endpoints) | extends v1 `deploy/egress.py` |
| **keys** (K15) | Secrets, transit encryption, internal PKI (§14.5) | OpenBao, pinned; `services/keys/`, client `libs/tb_security/keys.py` | own volume | D4 (key material) | new |
| eval, bench, bake-off | `trialbox eval`, `trialbox bench`, `tools/bakeoff.py`, `tools/mlbench.py` | CLI | reports | D2 on site; D0 in dev | extended |

The following are deliberately **not** used:
- **LiteLLM, Portkey or Envoy AI Gateway** (ADR-V4-11).
- **Temporal, or DBOS as a service** (ADR-V4-02).
- **Kafka.** CDC runs without a message broker (§5).
- **OPA or Cedar** (ADR-V4-13).
- **An SSO broker.** Listeners use the hospital IdP directly, and the relay identifies conversing staff (§9.4).
- **Third-party MCP servers, the Hermes plugin catalogue, and Hermes' own platform adapters** (ADR-V4-08, ADR-V4-16).

### 4.4 Layering and the data-class boundary

The v3 layer numbers L1–L8 are retired, because L0–L5 now name the data-platform stages (§5). Layers are named.

```
 Layer         Containers                                         Classes held          Tools callable
 ────────────  ─────────────────────────────────────────────────  ────────────────────  ─────────────────────────
 Channels      channel-relay, cdr-sandbox                         D0–D4 (transport)     none
 ═════════ boundary 1: identifiers tokenised; grammar lines diverted to Intake ═══════════════════════════════
 Conversation  hermes | converse-native                           D0–D1, D3 tokenised   front-door MCP (T0, T1)
 Intake        orchestrator.intake (grammar, confirmation)        D0–D4 (deterministic) creates requests only
 Policy        tb_common.policy: sender auth, delegation, purpose, accountant, rate limits, routes
 Workflows     orchestrator, matching: steps, gates, outbox       D0–D4                 T0–T3 (T3 deterministic)
 Tools         T0 public/meta · T1 aggregates (accountant) · T2 patient-level (study + delegation) · T3 writes
 Data          L0–L5, lake, fhir-store, omop-db, vault            D0–D4 (D4 only in L0–L3 and the vault)
 ═════════ boundary 2: every model call carries a class label; the gateway decides ═════════════════════════
 Models        tb-gateway → serving router → serving, embed,      D0–D4 on box/tenant; D0–D2 external (C)
               guard; tb-egress (all; models C)
 Assurance     ledger, lineage, traces, collector, eval, backups  D3 at most (no names or MRNs)
```

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-B12 | A model MUST NOT hold a T3 tool. T2 data MUST reach a model only inside a workflow step for a study on which the requester is delegated, with step id, purpose and class on the gateway call. (Carries v3 SEC-11; controls allocated in §14.) | T | MS1 |
| NFR-B13 | The Conversation layer MUST NOT receive patient-level data from tools; staff text it receives is tokenised and is D3 in packet threads and PHI-tolerant channels, routed on-prem only (FR-CONV-8). Grammar lines carrying identifiers (`MATCH`, `FULLREVIEW`) MUST go from channel-relay to Intake directly. Identifiers in free text MUST first be replaced by message-scoped tokens. (Carries v3 SEC-12, revised.) | T | MS0 |
| NFR-B14 | Recipients, scope and release targets MUST come from the delegation log and the Study Card, never from model output or document content. (Carries v3 SEC-13.) | T | MS1 |
| NFR-B15 | Each container MUST declare its highest class and its `talks_to` list in `deploy/containers.yaml`. `trialbox doctor` MUST refuse a network policy that lets a container reach a higher-class container not on its list. | T | MS0 |
| NFR-B16 | Assurance containers MUST NOT store names, MRNs, national ids or free-text notes. They MAY store pids, hashes, counts and redacted text. The collector's drop rules MUST be tested with planted identifiers. | T | MS1 |

### 4.5 The filter-first cascade (normative)

The cascade decides which patient–criterion pairs need evidence, and spends model time only where nothing cheaper can
decide. v4 changes v3 in five ways (R3-02, R3-05, R3-06, R3-08):
1. S2 never excludes on zero hits, unless the criterion's lexicon recall is certified at ≥ 0.98.
2. A new **S2b semantic screen** sits between S2 and S3.
3. The judgement cache is keyed by the set of evidence sentences.
4. Evidence may cite up to three spans.
5. `potential` is split into `potential:data_gap` and `potential:uncertain`.

The same cascade serves trial → patients and patient → trials (§10.5). Registry trials without a compiled ruleset use the
TrialGPT-derived retrieval in `services/matching/registry_match/`, then the same judge, cache and evidence schema.

```
 population of scope
   │ S0  scope, consent scopes (FHIR Consent, §7), opt-outs, active status           SQL                cost ≈ 0
   ▼
   │ S1  IR v3 → SQL on the lake (CQL sample on fhir-store), three-valued;           SQL                cost ≈ 0
   │      excludes only on AFFIRMATIVE evidence; missing → unknown, passes on;
   │      absence of the index condition → S2/S2b rescue
   ▼
   │ S2  lexical pre-filter: approved bilingual lexicon, window-restricted FTS,       lexicon/FTS/rules  cost ≈ 0
   │      assertion rules (ML-6), typed-value patterns ("EF 35%", "eGFR 28")
   │      hits → S3 · zero hits → S2b (default) · zero hits → absence semantics
   │      ONLY where lexicon_recall lower bound ≥ 0.98 (CAS-13)
   ▼
   │ S2b semantic screen of zero-hit pairs: note_question vs sentence embeddings      embeddings, batch  small
   │      in the window; LTT threshold per criterion type × language stratum
   │      above → S3 · below → absence semantics, logged as stratum S2b-below
   ▼
   │ S3  judge (class J) on the residue; exclusion power ÷ cost order; lazy;          LLM, batch         budgeted
   │      stop at the first verified hard not_met; 1–3 verified spans
   ▼
   │ S4  second opinion (class V, other family, overnight) on would-be strong         LLM, overnight     budgeted
   │      candidates and above-threshold S3 judgements (§8.8)
   ▼
   │ S5  person: PI decision sheet (G3); five-minute review                           human              ≤ 10/week/CRC
   ▼
 tiers: strong · potential:data_gap · potential:uncertain · watchlist · excluded  (+ recall certificate)
```

The v3 identifiers are kept. *(v4: revised)* marks a change in substance.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| CAS-1 | Every screening, matching and feasibility run MUST execute S0, S1, S2, S2b, S3, S4, S5 in order. For each stage it MUST record, in the manifest's `cascade` block (§6), the patients and patient–criterion pairs entering and leaving. *(v4: revised.)* | T | MS1 |
| CAS-2 | A `structured` criterion MUST NOT be sent to any model. A `note` criterion MUST NOT be judged for a patient with a hard failure elsewhere, an opt-out, or a consent scope that excludes research use. *(v4: revised.)* | T | MS1 |
| CAS-3 | S3 MUST evaluate note criteria in descending `exclusion_power / expected_tokens` order. Exclusion power is the site's historical `not_met` share per canonical criterion, pooled across studies through the criterion library, with prior 0.5. Evaluation stops at the first verified hard `not_met`. *(v4: pooled.)* | T | MS2 |
| CAS-4 | **Budgets.** Each run has `max_llm_items` and `max_tokens` (defaults 2,000 items and 10M tokens per study per run), drawn from the gateway budget ledger (§8.11). If a run would exceed its budget, it MUST finish S0–S2b for everyone, spend the budget in next-appointment order, and emit a partial packet that names the unprocessed count. A run MUST never be silently truncated. | T | MS2 |
| CAS-4a | **Night budget.** The pass scheduler MUST hold a global `night_tokens` budget (default 50 % of the capacity `trialbox bench` measured per pass) and allocate per-study budgets from it by priority and next-appointment date. Exhaustion carries work over (NFR-B3) and is reported. | T | MS2 |
| CAS-5 | **Sentence-set cache.** Judgements MUST be keyed by `(pid, canonical_criterion_hash, evidence_sentence_set_hash, prompt_id@version, model_build_sha, window_hash)`. The evidence sentence set is the ordered set of hashes of canonical sentences in the window that hit the S2 lexicon or pass the S2b threshold. A new note MUST trigger re-judgement only if it changes that set. Each entry MUST carry the `origin_call_id` of its recorded output (§8.13). Entries are reused across studies and runs. *(v4: revised, R3-05.)* | T | MS2 |
| CAS-6 | **Incremental evaluation.** A nightly run MUST re-evaluate a pair only if: (a) its evidence sentence set or structured inputs changed, including corrections, late arrivals and deletions (§5); (b) a window boundary passed a record date; or (c) the ruleset, prompt, build, lexicon or S2b threshold changed. The compiler emits domain dependencies and next-flip dates (§6). *(v4: revised.)* | T | MS2 |
| CAS-7 | **Metrics.** The manifest MUST record `n_scope`, `n_after_S0..S4`, `pairs_S2_zero_hit`, `pairs_S2b_above`, `pairs_S2b_below`, `pairs_judged_S3/S4` (calls made, excluding cache hits), tokens in and out, `cache_hits`, `llm_share = pairs_judged_S3 / (n_after_S1 × note_criteria)` and GPU-seconds per pass. A `not_met` is **hard** for CAS-3 only if every span verifies, the assertion rules agree, and it is not abstained (§8.8). These metrics are reported per study in the control plane and the QA pack. *(v4: revised.)* | T | MS1 |
| CAS-8 | **Feasibility samples model stages.** S0–S2b run on the full population. S3–S4 run on a stratified sample (≤ 200 patients per stratum; strata = S2/S2b outcome × department). The estimate is Σ N_h p̂_h, with a normal interval on the total and the finite-population correction, and Wilson intervals per reported stratum. Results are reported as `{est, ci95_low, ci95_high, n_sampled}`. The estimate is control-rounded; interval endpoints are floored and ceiled to base 5. *(v4: S2b strata.)* | T | MS1 |
| CAS-9 | The v1 full-record fallback MUST NOT run on batch paths. It remains only for `FULLREVIEW <pid>` on ≤ 20 patients, arriving through Intake and never through the Conversation layer. | T | MS1 |
| CAS-10 | Every candidate packet, matching result and feasibility pack MUST carry the current recall certificate of its study and ruleset (§10 SAFE), computed with anytime-valid confidence sequences and including the `S2-zero_hit` and `S2b-below` strata. *(v4: revised.)* | T | MS2 |
| CAS-11 | **Affirmative exclusion** (IR ≥ 2.0.0). S1 MUST exclude only on a matching record in the window for an exclusion atom, or on a failing value for an inclusion threshold. It MUST log the evidence (code, value, date, source, lineage id). Missing data yields `unknown`. The one exception is absence of the index condition (`index: true`): the patient is excluded only if neither S2 nor S2b finds a mention in any note in the lookback. *(v4: S2b added.)* | T | MS1 |
| CAS-12 | Zero S2 hits MUST route the pair to S2b. Absence semantics MAY apply directly after S2 only for a canonical criterion certified under CAS-13 for the pair's language stratum. | T | MS1 |
| CAS-13 | **Lexicon-recall certification.** The `lexicon_recall` suite (`eval/lexicon_recall/`) MUST measure lexicon recall against judged positives per criterion type × language stratum. A stratum is certified only if the one-sided 95 % Clopper–Pearson lower bound of lexicon recall on judged positives is ≥ 0.98 (0 misses needs ≥ 149 positives, 1 miss ≥ 236, 2 ≥ 313, 3 ≥ 386; App. F.1). Strata: criterion type × language (zh-only, en-only, mixed, abbreviation-heavy; ja from MS6), each with ≥ 5 % of the site's sentences (FR-M0-25). Certification lapses on any lexicon change that removes or narrows a term. | T | MS2 |
| CAS-14 | **S2b.** S2b MUST compare the bilingual `note_question` with bge-m3 sentence embeddings from the L5 sentence index (§5) inside the window. The threshold per criterion type × language stratum MUST be set by Learn-then-Test, so that the miss rate among judged positives is ≤ 0.02 at confidence 0.95. Until a stratum has ≥ 100 judged positives, it MUST use the public-prior threshold fitted on the NCBI 1,015-annotation set and its translations (`eval/criterion_ml/`), lowered by a site safety margin. Code: `services/matching/cascade/s2b_semantic.py`. | T | MS1 |
| CAS-15 | S2b MUST call embeddings through `tb-gateway` as D3 batch requests (one audit record per batch). It MUST NOT call a generative model. | T | MS1 |
| CAS-16 | **Multi-span evidence.** A judgement MAY cite ≤ 3 spans, in different chunks. Every span MUST verify: quote at its offsets, chunk date in the window, assertion agreement, typed-value match. If any fails, the judgement is `insufficient`. Each conjunct of an IR conjunction (for example drug **and** date) MUST be covered by a verified span. | T | MS2 |
| CAS-17 | **Split `potential`.** `potential:data_gap` MUST list the missing items, their domain, and the date the gap expires. `potential:uncertain` MUST show the abstained or disagreeing judgements with their quotes. Packets and decision sheets MUST present the two separately. | T | MS2 |
| CAS-18 | Every patient kept by the CAS-11 rescue MUST be logged with the rescuing stage and sentence hash. The rescue yield MUST be reported per study. | T | MS1 |
| CAS-19 | CAS-11 and CAS-12 apply only to IR ≥ 2.0.0. Line-of-therapy, calculator and anchor semantics apply only to IR ≥ 3.0.0 (§6). Older rulesets keep byte-identical behaviour until their next G1. | T | MS1 |
| CAS-20 | Patient → trials matching MUST reuse S0–S4, the judgement cache, the evidence schema and the tier vocabulary. It MUST carry each study's recall certificate. | T | MS2 |

### 4.6 Batch execution and model passes

On P-GB10 and P-5090 the box keeps at most one large generative model resident, and schedules **passes**. On P-Scale and
in topology B the serving router may keep several builds resident when the bench shows memory allows it (ADR-V4-04).

v3's 19:00–21:00 ingest window could not hold a 3M-patient ingest (a round-2 defect). v4 splits ingest into three parts:
- continuous HL7 v2 and CDC capture into L0–L1;
- a daily delta publish;
- a weekly full reconciliation in a weekend window (§5).

| Window (default) | Data | Model resident (P-GB10/P-5090) | Work |
| --- | --- | --- | --- |
| all day | HL7/CDC micro-batches into L0/L1; SIU refreshes clinic-day lists | — | CPU only |
| 07:00–19:00 Day | — | J (`tb-judge`, `tb-frontdesk`), G-policy, E/R | Hermes front door; intake proposals; library match and first extraction; `ASK`; questionnaires; urgent re-checks on same-day SIU/ADT |
| 19:00–21:00 Publish | L2–L4 delta; publish gate; dirty set; sentence-index delta | E | front door in native mode |
| Night 1: on publish (≤ 5 min after, NFR-25), 21:15 at the latest – 01:30 | — | J | S3 for screens, feasibility samples and matching |
| 01:30–05:30 Night 2 | no ingest or Atlas | V | S4; second extraction; recall-audit judgements; shadow pass (§8.10) |
| 05:30–06:30 Night 3 | — | J | narrative drafting; five-minute review selection |
| 06:30–07:00 Assembly | — | J | deterministic rendering; outbox |
| Sat 21:00 – Sun 07:00 | weekly full reconciliation and rebuild (§5) | none, or J for carried-over work | night passes move to Sunday daytime if needed |

**Memory budget, P-GB10 (128 GB unified), in GB, all *(est.)*.**

| Component | Day | Publish | Night 1/3 (J) | Night 2 (V) |
| --- | --- | --- | --- | --- |
| OS, runtime, drivers | 8 | 8 | 8 | 8 |
| Postgres + omop-db | 8 | 8 | 6 | 4 |
| HAPI + terminology | 8 | 8 | 6 | paused |
| Application containers incl. Hermes | 6 | 5 | 4 | 4 |
| Trace store, collector, Prometheus | 5 | 5 | 4 | 4 |
| guard-service | 3 | 1 | 1 | 1 |
| embed + rerank | 3 | 4 | 3 | 1 |
| Lake (`TB_LAKE_MEMORY_LIMIT`) | 16 | 40 | 16 | 4 |
| Ingest and Atlas workers | 4 | 20 | 0 | 0 |
| J weights + KV (64k for `tb-frontdesk`) | 20 + 16 | — | 20 + 24 | — |
| G-policy (gpt-oss-safeguard-20b class) + KV | 13 + 3 | — | — | — |
| V weights + KV | — | — | — | 65 + 14 |
| **Total** | **113** | **99** | **92** | **105** |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-B1 | The pass scheduler MUST load each pass's builds through the serving router and drain the queue by priority: gate replies > interactive front door > feasibility > matching > pre-screen > recall audit > abstraction > drafting > shadow. It MUST unload at window end and record swap time. *(v4: revised.)* | T | MS1 |
| NFR-B2 | Grammar commands MUST be acknowledged within one relay poll. Free text MUST get its proposal ≤ 2 h after receipt between 07:00 and 17:00, otherwise by 08:00 the next day. Where `tb-frontdesk` stays resident (P-Scale, B), the conversational targets of §13 apply all day. *(v4: revised.)* | T | MS1 |
| NFR-B3 | A pass that cannot finish MUST carry the work over and show the backlog in the control plane. If a gate or deadline would be missed, it MUST email the research office. | T | MS1 |
| NFR-B4 | Windows, priorities and model classes MUST be site configuration. On P-5090, passes J and V share the GPU in sequence. | I | MS1 |
| NFR-B5 | **Memory budget.** Each window MUST declare per-container budgets, enforced through cgroup limits at window start. On unified-memory profiles, `TB_LAKE_MEMORY_LIMIT` MUST be ≤ 16 GB with J resident and ≤ 4 GB with V resident. No ingest or Atlas job may overlap a V pass. `trialbox bench` MUST record peak memory per window and container, and the measured table replaces the estimates in the install record. *(v4: revised.)* | T | MS1 |
| NFR-B20 | On P-GB10, the day pass MUST serve `tb-frontdesk` with ≥ 65,536 tokens of context (the Hermes minimum). If the bench cannot sustain this within budget, the site MUST bind a smaller build that passes the front-door suites, or run `channels.engine: native`. | T | MS1 |
| NFR-B21 | Batch model jobs MUST be idempotent and resumable per chunk (one durable step per ≤ 64 items). They MUST write to staging tables that become visible only when the step commits. | T | MS1 |

### 4.7 Main data flows

The v3 flows (v3 §4.6) are carried, with three changes:
- ingest is the L0–L5 pipeline with its publish gate (§5);
- every model call passes through `tb-gateway`;
- every output carries a lineage id (§5, §6).

Protocol to ruleset now starts with `match_criterion_library` and runs `extract_criteria` only for unmatched criteria,
with J in the day pass and V at night. Feasibility adds the recruitability model before the accountant (§10.3).
Pre-screening refreshes appointments intra-day from SIU.

The conversation flow is: channel-relay → Hermes or converse-native → front-door tool → orchestrator request → workflow →
outbox → channel-relay. No step of this flow returns patient-level data to the Conversation layer.

### 4.8 Hardware profiles, integration and the benchmark gate

#### 4.8.1 Profiles

| Profile | Hardware | Model classes that fit *(est.)* | Status |
| --- | --- | --- | --- |
| **P-GB10** (default) | One NVIDIA GB10 system, 128 GB unified memory (DGX Spark, or Dell Pro Max GB10, HP ZGX Nano, Lenovo ThinkStation PGX); 4 TB NVMe; 8 TB backup disk | J: 30–35B-class MoE at 4-bit (≈ 20 GB). V: 100–125B-class MoE at MXFP4/4-bit (≈ 65 GB), in its own pass. G-policy ≈ 13 GB by day. | MS1; v1 ships `docker-compose.gb10.yml` |
| **P-5090** | x86 workstation or 2U server, RTX 5090 32 GB, 128–256 GB RAM, 4–8 TB NVMe | J: 30–35B MoE or 27–32B dense at 4-bit, 32k context for judging. V: a second 27–31B family in a separate pass. `tb-frontdesk` at 64k needs a smaller build (gpt-oss-20b class) or native mode. | MS1, if the bench gate passes or IT refuses arm64 |
| **P-Scale** | x86 server with one RTX PRO 6000 Blackwell 96 GB, or two linked GB10 (256 GB) | V up to ≈ 230B-class MoE at 4-bit; J and V co-resident where the bench allows; `tb-frontdesk` all day | MS4, for sites with > 50 recruiting studies |
| **P-Mac** (experimental) | Mac Studio ≥ 128 GB as **LLM host only**, beside an x86 or GB10 box | very large V (MLX or llama.cpp) | MS6, behind a flag. The model server runs natively, outside the compose hardening, egress and disk-encryption model. The gateway reaches it over mTLS on the model VLAN. |

Reference prices (October 2026) are volatile because of the memory shortage, so quotes are needed:
- P-GB10: about US$4.7k (DGX Spark); OEM units €3.2k–5.8k excluding VAT *(est.)*.
- P-5090: card US$4k–7k street (MSRP US$1,999), plus the workstation.
- P-Mac: about US$5.5k (96 GB) to US$9.5k (256 GB).

**Topology B equivalents.** Regional availability and quota in Taipei and Tokyo/Osaka MUST be verified at design time.
*(All regional availability below is uncertain.)*

| Equivalent | Accelerator | Instance examples | Confidential computing |
| --- | --- | --- | --- |
| B-M ≈ P-GB10 | 1× H100 80 GB or H100 NVL 94 GB | Azure NC40ads H100 v5; Google Cloud a3-highgpu-1g; AWS single-GPU P5 size *(uncertain)* | Azure NCCads H100 v5 (SEV-SNP + H100 CC mode), generally available since Sept 2024 in limited regions; Google confidential A3 *(uncertain)*; no AWS GPU TEE known *(uncertain)* |
| B-S ≈ P-5090 | 1× L40S 48 GB | AWS g6e | none known |
| B-L ≈ P-Scale | H200 141 GB, 2× H100, or B200 | AWS p5e/p5en, p6-b200; Google a3-ultragpu; Azure ND H100 v5 | Blackwell TEE-I/O with inline NVLink protection (NVIDIA claim); cloud availability *(uncertain)* |

Confidential computing is optional in B, because the tenant is the hospital's own perimeter (§7). It becomes a
precondition only where §7 requires attestation before D3 is processed. GB10 is not documented as supporting GPU
confidential-computing mode *(uncertain)*. On-prem protection therefore relies on physical, OS and key controls (§14).

#### 4.8.2 Capacity model

```
D = Σ_studies pairs_S3 × (1 − cache_hit) × (tokens_in + tokens_out) + pairs_S4 × (…) + audit + extraction + shadow
```

At about 2,750 tokens per item, a 30-study centre should need 10³–10⁴ warm-cache S3 items per night, or 2.75M–27.5M
tokens *(est.)*. Community reports give 1,700–2,700 prefill tokens/s on GB10 for a 120B-class MoE *(est., unverified)*.
At those rates prefill takes 0.3–4.5 h, plus 0.5–1 h of decode at the top end. The cache, the dirty set, S2b and the
night budget are therefore requirements, not optimisations. The sentence-set cache targets a warm hit rate > 80 % after
four weeks in daily-note clinics *(est.; measured by CAS-7)*.

#### 4.8.3 Hardware integration

| Concern | Specification |
| --- | --- |
| Placement | Locked rack in the data centre: GB10 on a vented shelf, x86 rack-mounted. Never under a desk or in a clinic. An optional cold-standby unit of the same profile serves DR (§18). |
| Power | Online double-conversion UPS, ≥ 15 min at measured peak. Network UPS Tools runs on the host. After 2 min on battery, passes pause, steps commit, Postgres flushes, and the host shuts down before the low-battery threshold. |
| Network zones | (1) appliance VLAN; (2) management VLAN (admin-listener, SSH, x86 BMC); (3) integration paths to HIS, HL7 engine and FHIR, firewall-pinned by source and port; (4) channel DMZ, where the hospital reverse proxy and WAF forward only the Teams and LINE webhook paths. User VLANs reach only signing-listener, over HTTPS. |
| Remote management | x86: BMC on the management VLAN, default credentials removed. GB10: no documented BMC *(uncertain)*; SSH on the management VLAN, plus an IP-KVM or on-site access, recorded in the install record. |
| Platform pin | `deploy/platform.lock` pins the OS image (DGX OS on GB10, Ubuntu LTS on x86), kernel, NVIDIA driver branch, CUDA, container toolkit and vLLM image digest. Driver, firmware (fwupd/LVFS capsules only) and OS updates are G5 platform changes, followed by the bench and the E2 suites (§8.9). |
| Runtime | Rootless Podman with `podman-compose`; Docker Engine accepted only where the hospital mandates it, recorded as a deviation (§17.2). |
| Time | Two internal NTP sources; UTC audit timestamps; alarm at > 1 s offset. |
| Storage | NVMe with LUKS2 and TPM-sealed keys (§14); read-only, SHA-verified model volume; backups to the local disk and the hospital's immutable target (§18). |
| Topology B | Infrastructure as code in the site repository; private subnets; customer-managed keys; object-locked backup bucket; GPU quota reserved before go-live. |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-B22 | The install record MUST document placement, UPS model and runtime, network zones and firewall rules, the remote-management path and the `platform.lock` hashes. For B it MUST also record the infrastructure-as-code commit, region and instance type. `trialbox validate` (IQ) MUST check the record for completeness. | I | MS1 |
| NFR-B23 | The UPS shutdown sequence MUST be tested at installation and yearly. A simulated mains loss MUST leave all steps committed or resumable, the audit chain intact, and no outbox message sent twice. | T | MS3 |
| NFR-B24 | `trialbox doctor` MUST refuse to start serving if the driver branch, CUDA version or vLLM digest differs from `deploy/platform.lock`. | T | MS0 |

#### 4.8.4 Benchmark gate

These requirements carry v3 NFR-17…19 under this part's prefix.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-B17 | `trialbox bench` MUST measure, on the installed box or tenant: (a) J and V items/hour at the site's median prompt length, batch 16–64, JSON-constrained; (b) S2b sentences/hour; (c) extraction minutes per 100 protocol pages; (d) `tb-frontdesk` time to first token and tokens/s at 64k context; (e) quality on the `judge` suites per language stratum and on `criteria_extract` for the chosen quantisation, with a drop of ≤ 2 points against the reference; (f) peak memory per window and container; (g) peak power. *(was NFR-17, revised.)* | T | MS1 |
| NFR-B18 | **Capacity gate.** Planned weekly LLM items MUST be ≤ 50 % of measured night capacity. Otherwise the box reduces scope or cadence and tells the research office. The bench MUST be re-run after every G5 change to a build, quantisation, engine, driver or profile. *(was NFR-18.)* | T | MS1 |
| NFR-B19 | **Model choice by evidence.** For each profile, each role MUST bind to the **smallest** build that passes all gates of §8.9 on the site's de-identified evaluation set and on the public suites. *(was NFR-19.)* | A | MS1 |

### 4.9 Architecture decision records

| ADR | Decision | Alternatives | Reason |
| --- | --- | --- | --- |
| ADR-V4-01 | Deterministic CQL/SQL is the only source of counts and tiers; models fill note criteria with verified quotes. *(kept: V3-01)* | LLM-only matching | Reproducibility and audit |
| ADR-V4-02 | Durable workflows stay on PostgreSQL `jobs`, `steps`, `gates`, `outbox`. *(V3-02 reconsidered and kept)* | DBOS Transact; Temporal | One validated engine; the outbox gives exactly-once sends; Temporal adds a clustered system to validate. **Revisit** if topology B needs multi-node orchestration for availability, or if gate and timer volume at 300 studies breaks the §13 latency targets. DBOS comes first then, because it keeps Postgres as the only engine. |
| ADR-V4-03 | Lake SQL executes; HAPI CQL verifies a sample. *(kept: V3-03)* | HAPI-only | HAPI runs at ≈ 21 patients/s |
| ADR-V4-04 | Sequential passes on single-accelerator profiles; co-resident builds on P-Scale and B where the bench allows. *(revises V3-04)* | always concurrent; always sequential | A large V overnight on default hardware; all-day conversation where affordable |
| ADR-V4-05 | P-GB10 is the default; P-5090 is supported; P-Scale serves large sites; P-Mac is experimental. *(kept: V3-05)* | P-5090 default | Filter-first makes capacity matter more than throughput. The dissent is recorded: P-5090 has faster prefill and a mature x86 stack. The bench gate decides per site. |
| ADR-V4-06 | Minimal UI per C-5′: conversation, signing page, optional review page, admin control plane, optional CDS card. *(revises V3-06)* | portal; email only | Owner constraint. Part 11 re-authentication needs a signing ceremony (§3). |
| ADR-V4-07 | Hermes Agent is the governed front door, with front-door MCP tools only. *(reverses the Hermes half of V3-07)* | no agent; an agent in the core | Owner requirement 2 and C-10; capability separation (§9) |
| ADR-V4-08 | Hermes sits behind channel-relay. Its platform adapters, webhooks, dashboard, API server and cron are disabled. Messages arrive through the `tb_relay_adapter` plugin. | Hermes adapters exposed directly | Published Hermes vulnerabilities cluster in gateway, webhook and dashboard code: CVE-2026-14628 (public exploit, fix version not stated), CVE-2026-7112/7113, and the v0.21.6 email-allowlist bypass. Behind the relay, Hermes needs no internet egress, identity is minted outside it, and fallback is a relay switch. |
| ADR-V4-09 | External models are used only through class-based routing: D0–D2 under the conditions of §4.1 and §7, never D3 or D4. *(reverses the cloud half of V3-07)* | no cloud; cloud for all non-identified data | Owner requirement 1 and C-2′ |
| ADR-V4-10 | OMOP CDM 5.4 is a core analytics model in `omop-db`, beside FHIR R4. *(reverses V3-09)* | optional view | OHDSI DQD, Achilles, ATLAS and network studies (§5–§6) |
| ADR-V4-11 | `tb-gateway` is built in-house (≈ 2–3k lines), OpenAI-compatible, on the shared policy module. | LiteLLM; Envoy AI Gateway; Portkey | LiteLLM's PyPI releases **1.82.7 and 1.82.8 were trojaned on 2026-03-24** with a credential-stealing `.pth` file, via a compromised CI pipeline. That is a supply-chain reason to keep it off the PHI path. Its tag routing has a fail-open option, and team tag enforcement is Enterprise-only. Envoy AI Gateway 1.0 assumes Kubernetes. Palo Alto Networks announced its intent to acquire Portkey *(closing uncertain)*. The gateway's job is small enough to own and validate. |
| ADR-V4-12 | Two tiers: the policy gateway (north-south, and the only trust boundary) and the serving router (east-west: residency, loading, prefix-aware routing). | one proxy | Small, stable validated code, while serving changes with hardware |
| ADR-V4-13 | Policies are versioned tables in Git, evaluated by `libs/tb_common/policy/` and shared by the gateway, MCP server, Hermes plugin and relay. *(kept)* | OPA; Cedar | One engine and one test suite |
| ADR-V4-14 | Self-hosted Langfuse v3 (MIT core) receives redacted traces through the OTel Collector. It is never the Part 11 record. *(reverses v3 "no Langfuse")* | files (v3); Arize Phoenix | Disputed judgements must be inspectable (R3-24). Phoenix's Elastic License 2.0 adds licence review. On P-5090 the collector MAY export to Postgres trace tables instead. |
| ADR-V4-15 | Reproducibility rests on recorded outputs, not on GPU determinism. | temperature 0 + seed | vLLM batching is not bit-exact (R3-22) |
| ADR-V4-16 | The only production MCP server is the first-party `frontdoor-mcp`, on spec 2026-07-28. No third-party servers or catalogues. | MCP gateway with several servers | CVE-2026-82021; OWASP MCP Top 10 MCP03, MCP04, MCP09 |
| ADR-V4-17 | S2 excludes on zero hits only for certified criteria; S2b screens semantically; the cache is keyed by sentence set. | v3 zero-hit exclusion; chunk-set cache | R3-02, R3-05 |
| ADR-V4-18 | Recall is certified by anytime-valid confidence sequences (`libs/tb_common/recall.py`). In the reference simulation (`tools/recall_sim.py`, `python -m tools.recall_sim`, seed 11: p = 0.02, 12 monthly looks of 40, 300 ledgers), repeated Clopper–Pearson missed the true rate in 9.7 % of ledgers, against 0.3 % for the sequence. *(revises V3-10; the statistics are owned by §10 SAFE)* | repeated Clopper–Pearson | R3-03: optional stopping |

## 8. LLM platform

The LLM platform is the control plane for every model in TrialBox: generative, embedding, reranking and guard. It
replaces v3's direct calls through `tb_common.llm` (R3-20, R3-21). The role table (§8.15) links it to every function, so a
module cannot use a model without a registered role, data class and route.

### 8.1 Planes and principles

```
          ┌──────────────────────────── Control plane ───────────────────────────────┐
          │ model-registry (builds, cards, statuses) · prompt registry (Git)          │
          │ routing policy (Git, G5) · budgets · eval / bench / bake-off · G5 records │
          └─────────────┬───────────────────────────────────────────┬─────────────────┘
                        │ alias → build, routes, budgets             │ gates
 callers (orchestrator steps, matching, compiler, frontdoor-mcp, hermes, converse-native, eval)
   │ OpenAI-compatible request + X-TB-* headers over mTLS
   ▼
 [tb-gateway] authN · label · route · tripwire · injection screen · budget · cache · dispatch · output checks · audit
   ├─▶ serving router ─▶ llm-serving (J, V, F, G) · embed-service (E, R) · guard-service
   └─▶ tb-egress ─▶ approved external endpoints (model endpoints: topology C only; D0–D2)
 assurance: audit ledger (call records) · recorded-output store · trace store (redacted) · Prometheus
```

The platform follows five principles:
1. **One door.** Only `tb-gateway` reaches a model (NFR-B9).
2. **Label at the source.** The calling step sets the data class from the data it read. A call without a label fails.
3. **Fail closed.** A missing route, an unknown alias, a guard timeout or an exhausted budget is an error. It never falls
   back to a broader route.
4. **Record, then trust.** Outputs are recorded before use, and re-runs replay them (§8.13).
5. **Smallest sufficient model** (NFR-B19).

### 8.2 The gateway

`tb-gateway` (`services/gateway/`) exposes OpenAI-compatible `/v1/chat/completions`, `/v1/embeddings` and `/v1/rerank`.
It also exposes `/v1/batch` for chunked batch jobs, and `/v1/models`, which lists aliases only.

Callers use `libs/tb_llm/` (§17.1, S1-06); `libs/tb_common/llm.py` becomes an import shim to it for one milestone. It keeps the v3 signature `chat_json(prompt_id, variables, schema)` and
adds the headers below.

| Header | Content | Checked against |
| --- | --- | --- |
| `X-TB-Data-Class` | D0…D4 | the prompt's `allowed_classes`; the route |
| `X-TB-Purpose` | purpose code (§7) | the caller's allowed purposes |
| `X-TB-Study`, `X-TB-Step` | study id; workflow step id (or Hermes session id) | delegation log and live `steps` row, for D3/D4 |
| `X-TB-Prompt`, `X-TB-Role` | `prompt_id@version`; role (§8.15) | prompt registry (rendered hash must match); route table |
| `X-TB-Untrusted-Spans` | offsets of segments rendered from variables declared `trust: untrusted` | injection screen; spotlighting |
| `X-TB-Replay` | `origin_call_id` (re-runs only) | recorded-output store |

**Processing order.** Each step passes, transforms or rejects. Every rejection is audited.

| # | Step | Rejects when |
| --- | --- | --- |
| 1 | mTLS service identity (internal CA, §14) | unknown or revoked certificate |
| 2 | Header validation and prompt binding (the rendered request must equal `prompt_id@version` rendered with its variables) | missing header; template mismatch. Free-form prompts are allowed only for `frontdesk_converse`. |
| 3 | Route lookup: `(role, class, profile, topology, site flags, environment)` → ordered build list | no route |
| 4 | Replay, if `X-TB-Replay` is set: return the recording and stop | recording missing (an error; never a fresh call) |
| 5 | PHI tripwire (§8.6) on D0–D2 calls, external-bound calls and all Hermes traffic | external hit: block and alert. Internal D0–D2 hit: block, alert, and quarantine the step for steward review (the mislabel is the incident; the call is never re-run as D3 automatically). |
| 6 | Injection screen on untrusted spans | score above the role's threshold |
| 7 | Budget reservation (§8.11) | exhausted |
| 8 | Cache lookup (§8.12) | — |
| 9 | Dispatch: strict `json_schema` response format, registry sampling (MOD-4), prefix-cache salt | upstream failure after the route's retries and fallbacks |
| 10 | Output checks: schema (≤ 2 retries with error feedback, then `LlmSchemaError`); citation offsets (`cites: true`); `numbers_match` (`narrative: true`); policy classifier on staff-facing text; outbound PHI check on Conversation-layer replies | a declared blocking check fails |
| 11 | Record the output, append the call record to the ledger, emit the trace | write failure fails the call |

**Fallbacks** move only along the route's ordered list. Every build in the list is permitted for the call's class, so a
fallback never moves from on-box to external unless the route lists that external build for that class.

**Call record (ledger).** `{call_id, ts, caller_cert, step_id, study, purpose, role, class, prompt_id@version,
rendered_sha256, build_alias, build_sha, route_id, policy_version, endpoint and region, tokens_in, tokens_out, latency_ms,
cost, cache (hit | miss | replay), guard_verdicts, output_sha256, origin_call_id}`. It holds no prompt or response text.
Embedding, rerank and batch calls write one record per batch, with the item count and the input-set hash.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| LLM-1 | Every model call, including embeddings, rerankers, guards, Hermes and on-site evaluation, MUST pass through `tb-gateway`. Only `services/gateway/` may hold model endpoint addresses or provider credentials. | T | MS0 |
| LLM-2 | The gateway MUST reject a call without a valid class, purpose, role and prompt header. It MUST reject a D3/D4 call unless the orchestrator confirms the step as live for a study on which the requester is delegated. | T | MS0 |
| LLM-3 | The gateway MUST execute the processing order above and fail closed at every step. A guard-service timeout (default 5 s) MUST fail the call. | T | MS0 |
| LLM-4 | A property test MUST show that no reachable sequence of failures and fallbacks routes a D3 or D4 call to an external endpoint. | T | MS0 |
| LLM-5 | The call record MUST be appended to the hash-chained ledger before the response is returned. | T | MS0 |
| LLM-6 | Credentials for external routes MUST be short-lived where the provider supports it, held in the key service (§14), and readable only by `tb-gateway`. | I | MS4 |
| LLM-7 | The gateway MUST be built from source in the product repository with hash-pinned dependencies, be covered by the SBOM (§14), keep state only in Postgres and the object store, and expose `/healthz` and `/readyz`. | T | MS0 |

### 8.3 Serving tier

llm-serving runs vLLM on x86 and GB10, with the image digest pinned in `deploy/platform.lock`. P-Mac runs llama.cpp
server. The serving rules are:
- **Remote code** is off.
- **Model files** are mounted read-only and SHA-verified at load.
- **Structured output** uses xgrammar, or harmony-native output for gpt-oss builds.
- **Tool calling** (`--enable-auto-tool-choice` with the parser recorded in the registry) is enabled only for builds bound
  to `frontdesk_converse`.
- **Context length** is set per role from the registry: judge 32k, front desk ≥ 64k.
- **Prefix caching** is on, with a cryptographic block hash and a gateway-supplied `cache_salt` (§8.12).
- **The serving router** exposes one endpoint per resident build and loads builds at the pass scheduler's request. On
  multi-replica profiles, a prefix-aware router (vLLM production-stack or equivalent) MAY balance replicas.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| LLM-8 | llm-serving MUST refuse to load a build whose weight, tokenizer or chat-template hashes differ from its registry record. | T | MS0 |
| LLM-9 | Serving ports MUST accept only `tb-gateway`, apart from Prometheus scraping inside the model zone. | T | MS0 |
| LLM-10 | Engine version, serving flags, structured-output backend, tool parser and prefix-cache hash algorithm MUST be part of the build record. A change to any of them is a G5 change. | I | MS1 |

### 8.4 Model registry, model cards and classes

**Registry.** The source of truth is in Git:
- `models/registry.yaml` holds builds and bindings;
- `models/cards/<build_id>.yaml` holds model cards;
- `models/routing.yaml` holds the routing policy.

`model-registry` (`services/registry/`) verifies signatures and hashes, loads the files into Postgres schema
`models`, and serves the alias → build map, which is the only routing input the gateway reads. CLI:
`trialbox models list | show | card | propose | promote | retire | rollback`.

**Build record.** Each build carries:
- `build_id` and `alias@version`;
- repository and commit SHA;
- SHA-256 per weight file;
- tokenizer and chat-template hashes;
- quantisation recipe and calibration-data hash;
- engine image digest and serving flags;
- context length;
- licence manifest (MOD-2) and origin (MOD-1);
- status;
- approved roles × profiles × classes;
- evaluation and bench report ids;
- the G5 record.

External builds are also pinned to a dated provider model version with auto-upgrade off. They record `provider`,
`region`, `processing_geography`, `retention_terms`, `abuse_monitoring` and the contract reference.

**Model card.** The card is generated from the record and the latest passing evaluation reports, in the style of the
CHAI applied model card, and filed in the AI credibility file (§15). It covers:
- contexts of use;
- out-of-scope uses;
- per-language results (en, zh-TW, ja, mixed, abbreviation-heavy);
- maximum context and throughput per profile;
- known failure modes;
- quantisation effects;
- guardrail coverage;
- the date of the last re-evaluation.

**Statuses.** `candidate → qualified → shadow → champion → retired`. Any status can move to `suspended` (§8.10).

| Class | Use | P-GB10 | P-5090 | P-Scale / B | Non-PRC option (MOD-1) |
| --- | --- | --- | --- | --- | --- |
| J judge/workhorse | judging, extraction, intake, drafting | 30–35B-class MoE, 4-bit (e.g. Qwen3.6-35B-A3B, Gemma-4-26B-A4B) | same | same or larger if NFR-B19 shows gain | Gemma-4-26B-A4B, Gemma-4-31B; gpt-oss-20b for intake |
| V verifier | second opinion, second extraction | 100–125B-class MoE (gpt-oss-120b MXFP4, Qwen3.5-122B-A10B) | a second 27–31B family | up to ≈ 230B-class MoE | gpt-oss-120b; Nemotron 3.5 class (OpenMDW-1.1 review pending) |
| F front desk | `frontdesk_converse`, tools, ≥ 64k | the J build at 64k | gpt-oss-20b class, or native mode | resident all day | gpt-oss, Gemma-4 |
| G guard | policy and injection classifiers | gpt-oss-safeguard-20b class by day; small injection classifier | small classifier, or J with the policy prompt if the `guard` suite passes | gpt-oss-safeguard-20b/-120b | gpt-oss-safeguard (Qwen3Guard is PRC-origin, licence *uncertain*) |
| E / R | embeddings, S2b; reranking | bge-m3; bge-reranker-v2-m3 | same | same, or Qwen3-Embedding if NFR-B19 shows gain | bge-m3 (BAAI), multilingual-e5-large |
| X external | topology C, D0–D2 | — | — | — | per contract; origin recorded |

Names are candidates. The bench and the suites choose the build (NFR-B19). Leaderboards are not acceptance evidence.

The v3 rows MOD-1…6 are carried; MOD-7…11 are new.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| MOD-1 | Every role MUST have at least one qualified build from a non-PRC developer. The site flag `public_agency: true` restricts the registry to such builds. | T | MS1 |
| MOD-2 | Every model package MUST ship a licence manifest (SPDX id or name, gating, redistribution and flow-down, field-of-use limits, origin). `trialbox doctor` MUST refuse a build that conflicts with site policy flags. | T | MS1 |
| MOD-3 | No non-commercial or research-only weights may ship (for example the jina family under CC-BY-NC-4.0 or the Qwen Research License). MedGemma is allowed only as a customer-installed option under the customer's acceptance of the Health AI Developer Foundations terms, unless legal review clears redistribution. | I | MS1 |
| MOD-4 | Sampling MUST be temperature 0, a fixed seed and `top_p = 1`, with schema-constrained decoding. The exception is `frontdesk_converse`, whose parameters are fixed in its registry binding. | T | MS1 |
| MOD-5 | Changing a build, quantisation, engine, serving flag, prompt, schema, exemplar bank, lexicon, abstention or S2b threshold, guard policy or route is a G5 change. It re-runs the suites (§8.9) and the bench, and re-establishes recall evidence (§10 SAFE). | T | MS1 |
| MOD-6 | The served alias and build SHA MUST be echoed in every manifest and report footer from the gateway call record, fixing the v1 mismatch at `feas.py:87` and `screen.py:137`. | T | MS0 |
| MOD-7 | Builds MUST be immutable. Aliases MUST resolve only to `champion` builds for production roles, `shadow` builds for shadow roles, and `qualified` builds for evaluation roles. | T | MS0 |
| MOD-8 | Each champion MUST have a generated model card, re-generated on every status change, in the AI credibility file (§15). | I | MS1 |
| MOD-9 | External builds MUST be pinned to dated versions with auto-upgrade off. A provider deprecation notice MUST open a G5 change ≥ 60 days before retirement. | I | MS4 |
| MOD-10 | Within one working day of a security advisory or licence change affecting a build, the build MUST move to `suspended`. The gateway MUST then route to the next build, or put the role into its degraded mode (LLM-36). | T | MS1 |
| MOD-11 | Each binding to a profile MUST cite the bench report that shows fit. The control plane MUST show origin and licence flags per role. | D | MS1 |

### 8.5 Routing policy

`models/routing.yaml` maps `(role, class, topology, environment)` to an ordered build list with conditions. The shipped
default is below. Sites may narrow it. Widening needs G5 and the conditions of §7.

| Role group | Class | Topology A | Topology B | Topology C adds | Dev environment |
| --- | --- | --- | --- | --- | --- |
| `classify_intent`, `frontdesk_converse` | D1 (staff text with no patient content, outside a packet thread) | J / F on box | J / F tenant | **never** (cloud routes never receive conversation text) | OpenRouter on synthetic D0 |
| `classify_intent`, `frontdesk_converse` | D3 (tokenised text from PHI-tolerant channels; every authenticated staff message in a packet thread) | J / F on box only | J / F tenant only | **never** | — |
| `summarise_external` | D1 (documents) / D3 (forwarded mail about participants) | J / F on box | J / F tenant; D3 tenant only | X for D1 documents only, under the D1 conditions below; **never** for D3 | OpenRouter on synthetic D0 |
| `match_criterion_library`, `extract_criteria`, `extract_soa`, `concept_select`, `answer_protocol`, `map_questionnaire`, `draft_document` | D1 | J day, V night | same, tenant | X, only if the Study Card records sponsor consent | OpenRouter on public protocols (D0) |
| `propose_mapping` | D1 (schema and coded samples) | J | J | X | J |
| `judge`, `second_opinion`, `registry_match_patient`, `match_keywords`, `abstract_field`, `draft_query_answer` | D3 | J / V on box only | J / V tenant only | **never** | public suites only (D0) |
| `s2b_screen`, `embed`, `rerank` | D3 (D1 for protocol text) | E / R | E / R | never for D3 | E / R |
| `draft_narrative`, `summarise_aggregate` | D1 (released aggregates; input MUST be a `DisclosedDeliverable`, RPT-14) | J / F | J / F | X under the D1 conditions below | J / F |
| `ops_explain` | D1 | F | F | X | F |
| `guard_policy`, `guard_injection`, `phi_ner` | the guarded class | G | G | **never** | G |
| `shadow:<role>` | as the role | shadow build on box | tenant | never | — |
| `bakeoff`, `optimise_prompt` | D0 | — | — | — | OpenRouter, D0 only |

External routes must also meet these attribute conditions:

| Class | Processing geography | Retention | Further conditions |
| --- | --- | --- | --- |
| D0 | any approved region | standard | — |
| D1 | in-country, or a geography the site approves (for example Japan for a Japanese sponsor) | zero data retention, or modified abuse monitoring approved before first use | sponsor consent per protocol; no training use; regional endpoint, never "global" routing |
| D2 | in-country only | zero data retention | §7 risk assessment, cross-border analysis, IRB/DPO sign-off; confidential computing where offered |

At the research date, AWS Bedrock in Taipei served Claude only through Global routing, so it fails the in-country condition
for D1 and D2. Google Cloud Vertex AI lists in-region processing in `asia-east1` for some partner models *(uncertain)*. Each
route records its verified geography at approval time. A change in the provider's documentation is a G5 trigger.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| LLM-11 | The routing policy MUST be a versioned file under G5, evaluated only by `libs/tb_common/policy/`. The policy version MUST be recorded in every call record. | T | MS0 |
| LLM-12 | Property tests (`tests/policy/test_routing_props.py`) MUST show, for every generated role, class, topology, environment and failure sequence, that: (a) no D3/D4 route leads outside; (b) no external route lacks the attribute conditions; (c) no guard role is routed externally; (d) dev OpenRouter routes accept D0 only. | T | MS0 |
| LLM-13 | A site override MUST only remove builds or tighten conditions, unless a G5 change with security and DPO sign-off records the widening. `trialbox doctor` MUST show widenings in the control plane. | T | MS1 |
| LLM-14 | The control plane MUST show the routing table in force (class, route, build, status, last change) and accept change proposals into G5. A per-route and per-role kill switch (`trialbox routes disable`) MUST take effect within 60 s, be audited, and need no G5, because it only narrows. | T | MS1 |

### 8.6 Guardrails

| Layer | Controls | Runs on |
| --- | --- | --- |
| 1 Deterministic | schema validation; quote and citation offset verifier; `numbers_match`; identifier regexes; allowlisted recipients (NFR-B14); invisible-Unicode stripping | every call that declares it |
| 2 PHI detection | Presidio with Taiwan recognisers (national id with checksum, ARC/UI number, NHI card, chart/MRN formats, zh-TW addresses); Japanese recognisers from MS6; surname and given-name dictionaries; NER fallback. §7 owns the coverage gates. | tripwire; channel-relay; outbound DLP |
| 3 Policy classifier | G class with a hospital-written policy prompt: no eligibility determination, no dosing or treatment advice, no patient-level disclosure, no study identifiers on LINE, no advice to bypass a gate | staff-facing text: Conversation replies, narratives, drafted documents |
| 4 Injection screen | small classifier plus heuristics (instructions addressed to the model, role markers, encoded payloads, URLs) | untrusted spans: email bodies, sponsor documents, tool results returned to Hermes |
| 5 Structural | spotlighting; quarantined extractor (§9.8); capability containment | always |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| LLM-15 | The tripwire MUST block any external-bound request with a hit, whatever its label. On internal D0–D2 calls, a hit MUST block the call, raise an alert, and quarantine the step for steward review; the call MUST NOT be relabelled and continued as D3. External-bound hits have a target of 0 and are reported monthly. | T | MS0 |
| LLM-16 | Guard verdicts MUST be recorded in the call record and as span events. Output release MUST be gated on them, while generation MAY run in parallel. | T | MS1 |
| LLM-17 | The guard policy text MUST be a registered prompt (`prompts/guard_policy/`), owned by the hospital's QA and DPO and changed only through G5. Guards MUST be evaluated by the `guard` suite (§16) per language. A release MUST NOT raise the false-negative rate on the red-team corpus. | T | MS1 |
| LLM-18 | (carries AI-07, AI-08) Narratives MUST use template placeholders, and `numbers_match` MUST reject any digit sequence the template engine did not produce. Unmappable questionnaire fields MUST stay blank and be listed. | T | MS1 |
| LLM-19 | (carries AI-09, AI-13) Model-reported confidence MUST NOT be a decision threshold. Log-probabilities MAY enter only the calibrated score (§8.8). Any recall claim MUST quote the certificate's lower bound (§10 SAFE). | T | MS1 |

### 8.7 Prompt registry and structured output

Each prompt is `prompts/<prompt_id>/v<n>.md`: YAML front matter followed by `## system` and `## user` Jinja2 sections. Its
schema is `schemas/llm/<prompt_id>.v<n>.json`. The front matter declares:
- `id`, `version`, `owner`, `role`;
- `allowed_classes`;
- `context_of_use` and `risk_tier`;
- `variables`, each with `trust` and `class`;
- `cites` and `narrative` flags;
- `eval_suites`;
- `cache_layout`, with static blocks first;
- the approving G5 record.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| LLM-20 | Production MUST resolve `prompt_id@version` explicitly. The v1 "newest version" default MUST be removed. Every call MUST log the prompt id, version, template SHA and rendered SHA. | T | MS0 |
| LLM-21 | CI MUST fail if a prompt lacks `allowed_classes`, `context_of_use`, `risk_tier` or `eval_suites`, or if it references a suite that does not exist. | T | MS0 |
| LLM-22 | Every agent-to-system boundary MUST use schema-constrained decoding plus server-side validation. After two failed retries the step MUST escalate to a person. Identifiers and numbers MUST NOT be free-generated: they are template-injected from deterministic results. | T | MS0 |
| LLM-23 | Templates MUST keep their declared static prefix byte-stable across renders (checked in CI), so that prefix caching hits. | T | MS1 |

### 8.8 Evidence-anchored judging and calibrated abstention

v3 §8.3–8.4 are carried, with multi-span evidence (CAS-16) and the split `potential` (CAS-17). §10 SAFE owns the recall
ledger statistics.

The S3 judge receives:
- the bilingual `note_question`;
- the window's evidence sentences and their chunks (≤ 2,500 tokens, newest first, original language);
- up to 3 adjudicated exemplars for the criterion type and language stratum, from the public set until the site bank
  exists.

It returns `met | not_met | insufficient`, 1–3 spans, an assertion label and an extracted value. A deterministic verifier
checks each span. A nonconformity score `s` then combines:
- retrieval margin;
- verdict log-probability where available;
- assertion-rule outcome;
- language stratum and abbreviation density;
- note type;
- negation and uncertainty cues;
- span count.

Learn-then-Test thresholds per criterion type × language stratum control the selective error at α = 0.05 with confidence
0.95. Judgements above threshold go to S4. If S4 does not resolve them, they become `potential:uncertain`. Tiers are set
in code.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| LLM-24 | (carries AI-10) Scoring and LTT selection MUST be implemented in `services/orchestrator/calibration/abstain.py` (§17.1). Thresholds MUST be versioned (`aq_<yyyy-mm>`), recorded in manifests, and recomputed monthly, on drift alarms and after G5 changes. | T | MS2 |
| LLM-25 | (carries AI-11, revised by R3-41) Until a stratum has ≥ 100 site-adjudicated pairs, it MUST use the **public prior**: the nonconformity model and thresholds fitted on the 1,015 NCBI annotations and their zh-TW, ja and code-mixed renderings (`eval/criterion_ml/`). The QA pack MUST show which threshold is in force per stratum. At α = δ = 0.05 a threshold certifies only if accepted errors are ≤ 1 at n = 100, ≤ 4 at n = 200, and 0 at n = 59. | T | MS1 |
| LLM-26 | (carries AI-12; AI-15 is retired by SAFE-11) The QA pack MUST report, per stratum, the error of accepted judgements on held-out adjudications against α. Recall-audit samples MUST be drawn with probability increasing in `s` and the S2/S2b margin, with the floor `audit_floor` of SAFE-11 (default 0.5) and Horvitz–Thompson weights (§10 SAFE). | T | MS2 |
| LLM-27 | `second_opinion` MUST NOT receive the J output. J and V MUST be from different model families, enforced by the registry at binding time. | T | MS1 |

### 8.9 Evaluation tiers and gates

The tiers are named E1–E5, to avoid a clash with the tool tiers T0–T3. §16 owns the datasets, suites and annotation
protocol.

| Tier | Content | Tooling | Gate |
| --- | --- | --- | --- |
| E1 Unit | schema, parser and tool-call format per build × prompt; prefix stability | pytest; `trialbox eval --tier e1` | 100 % |
| E2 Task | §16 suites (`criteria_extract`, `judge_public`, `judge_ml`, `lexicon_recall`, `s2b_screen`, `assertion_ml`, `dates_numbers`, `match_registry`, `intent`, `guard`) per language stratum | `trialbox eval`; `tools/mlbench.py`; lm-evaluation-harness for quantisation smoke tests | §16 thresholds; no stratum below its floor; non-inferiority vs champion (lower 95 % bound of the difference ≥ −2 points) |
| E3 Agentic | Hermes and converse-native against a mock front-door server | Inspect AI (MIT), `eval/agentic/` | policy violations 0; proposal accuracy ≥ 0.95 |
| E4 Adversarial | `redteam`: injection in mail and documents, hidden text, Unicode tags, tool-result poisoning, exfiltration, label forgery; zh-TW, en, ja, mixed | Inspect AI; promptfoo in dev only, pinned (acquired by OpenAI, March 2026) | zero capability-bearing successes; every attempt logged with its blocking step |
| E5 Human | adjudication, five-minute reviews, blinded chart review | §16 protocol | when risk tier or context of use changes |

| Change | E1 | E2 | E3 | E4 | E5 | Bench | Recall re-established |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Build or quantisation | ✓ | ✓ | if F | ✓ | if risk tier changes | ✓ | if J, V or E |
| Engine, serving flags, driver | ✓ | smoke + judge suites | if F | — | — | ✓ | if replay-drift (LLM-34) shows change |
| Prompt or schema | ✓ | ✓ | if F | ✓ | if context of use changes | — | if judge or S2b |
| Exemplars, lexicon, S2b or abstention thresholds | ✓ | ✓ | — | — | — | — | ✓ |
| Guard policy or classifier | ✓ | `guard` | ✓ | ✓ | — | — | — |
| Route or routing policy | property tests | — | — | class violations | — | — | — |
| Hermes release, skills, SOUL | ✓ | `intent` | ✓ | ✓ | — | — | — |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| LLM-28 | `trialbox change check <change_id>` MUST refuse to mark a G5 change ready while the evidence required above is missing. | T | MS1 |
| LLM-29 | Evaluation reports MUST be archived under object lock and referenced from the registry and the G5 record. External benchmarks (for example MedHELM) MAY inform selection but MUST NOT replace context-of-use evaluation. | I | MS1 |
| LLM-30 | The public suites MUST run in CI on every change to `prompts/`, `models/`, `schemas/llm/` or `services/gateway/`. They run on the development GB10, or through OpenRouter on D0 data. | T | MS0 |

### 8.10 Shadow and champion lifecycle; bake-off intake

```
 candidate ─(public suites / bake-off pass; licence + origin OK)─▶ qualified ─(G5)─▶ shadow ─(evidence, G5)─▶ champion ─▶ retired
 any status ─(advisory, licence change, regression)─▶ suspended ─(fix + G5)─▶ previous status
```

**Bake-off intake.** `tools/bakeoff.py` (built on `tools/mlbench.py`) runs in the development environment through
OpenRouter, on D0 data only:
- the 1,015 NCBI annotations in en, zh-TW, ja and code-mixed;
- synthetic intent emails;
- public protocols and Chia criteria;
- synthetic assertion and date/number sets.

Each run uses fixed prompts and schemas, temperature 0 and three seeds. It reports per-task metrics with bootstrap CIs,
cost and latency per 1,000 items, and a composite score with per-language floors.

The reference row is GPT-4 on the 1,015 annotations: accuracy 0.873, false-block rate 0.014 (95 % upper bound 0.022), and
patient × trial false exclusion 0.101 (upper bound 0.175). Results for open-weight candidates are pending the API key, and
none is assumed here. The top two builds per role become `qualified`, then `shadow` on site. Nothing reaches production
from the bake-off alone.

**Shadow pass.** Spare night-pass-2 time runs the shadow build on the day's cached `(pid, criterion,
evidence_sentence_set)` pairs (AI-14). Its outputs never reach a list, packet or production cache.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| LLM-31 | (carries AI-14) The shadow pass MUST accumulate agreement against adjudications per stratum and record both SHAs. Shadow outputs MUST NOT reach any list, packet or production cache entry. | T | MS4 |
| LLM-32 | Promotion to champion MUST require all of: (a) E2 non-inferiority per stratum; (b) shadow evidence on ≥ 4 weeks of nights or ≥ 100 adjudicated pairs per active stratum, whichever comes later; (c) the capacity gate; (d) MOD-1/2/3; (e) re-established recall evidence. | T | MS4 |
| LLM-33 | The development gateway MUST refuse any OpenRouter-bound call not labelled D0. The bake-off corpus manifest MUST list each dataset's licence (§16). | T | MS0 |
| LLM-34 | After every engine, driver or build change, a **replay-drift check** MUST re-execute (not replay) 200 recorded calls per role and report the share of outputs that changed. | T | MS2 |
| LLM-35 | Rollback MUST be an alias re-point to the previous champion (`trialbox models rollback <role>`), as an audited G5 fast-track change (procedure in §18). | T | MS1 |
| LLM-36 | **Degraded modes.** Each role MUST declare a degraded mode for when no build is routable: `queue`, `deterministic_only` (for example S0–S2b only, residue marked `potential:uncertain`), `manual`, or a switch to native (front desk). The control plane MUST show every role in degraded mode. | T | MS1 |

### 8.11 Cost model and budgets

| Route | Cost per call |
| --- | --- |
| External | `tokens_in × price_in + tokens_out × price_out`, at the route's contract prices |
| On box or tenant | `GPU_seconds × rate`, where `rate = (amortised hardware + power + support) / productive GPU-seconds per month`. For P-GB10: ≈ US$4.7k over 36 months plus ≈ 150 kWh of power per month *(est.)*. GPU-seconds are measured latency × the call's batch share, as reported by the serving router. |

Budgets are a hierarchy: site per month → module → study → run → step. They are kept in tokens and GPU-seconds
internally, and in currency for external routes. CAS-4 and CAS-4a draw from this ledger.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| LLM-37 | The gateway MUST hold the budget ledger in Postgres (`gateway.budget_*`). It MUST reserve before dispatch, settle afterwards, and refuse a call that would exceed any level. | T | MS1 |
| LLM-38 | Alerts MUST fire at 80 % and 100 % of any monthly budget, to the administrator and, for study budgets, to the research office. External budgets MUST default to 0. | T | MS1 |
| LLM-39 | A monthly cost report MUST be part of the QA pack: tokens, GPU-seconds and external spend per module, study and role, plus cost per candidate presented and per feasibility pack. External D0/D1 batch work MUST use the provider's batch tier where one is listed. | T | MS2 |

### 8.12 Caching

| Layer | Key | Classes |
| --- | --- | --- |
| Judgement cache (CAS-5) | `(pid, criterion hash, evidence sentence set, prompt@version, build SHA, window)` | D3 |
| Gateway response cache | `(prompt@version, rendered SHA, build SHA, sampling)` | D0/D1 roles flagged `cacheable`; never `frontdesk_converse` or regulated outputs |
| vLLM prefix cache | block hash over parent hash, tokens and `cache_salt` | all |
| KV offload | — | not used on P-GB10 or P-5090; on P-Scale/B treated as D4 |

The gateway sets `cache_salt = HMAC(salt_key, class ‖ scope)`. The scope is the study id for D3/D4, the Hermes profile
for `frontdesk_converse`, and `global` for D0–D2. Front desk and PHI workflows therefore never share prefix blocks, and
studies do not share D3 blocks. The vLLM documentation notes that non-cryptographic block hashes can collide and leak
across tenants, and that `cache_salt` isolates tenants and reduces timing side channels.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| LLM-40 | Prefix caching MUST use a cryptographic block hash and the salts above. The salt key MUST live in the key service and rotate on the gateway key schedule (§14). | T | MS1 |
| LLM-41 | The response cache MUST be limited as in the table. KV offload storage MUST be encrypted, excluded from backups and wiped at unload. Cache hit rates per role and study MUST be exported as metrics. | T | MS1 |

### 8.13 Reproducibility through recorded outputs

Every raw output is stored, encrypted and class-tagged, in bucket `llm-recorded/`. D3/D4 recordings stay in the PHI zone.
Each model-calling step stores its `call_id`s. A re-run (`trialbox rerun --replay`, §11) sends `X-TB-Replay` and receives
the recorded bytes.

A judgement-cache hit carries the `origin_call_id` of the call that produced it, so later runs that used the cache also
replay exactly. This closes the gap R3-22 found. Manifests list `{call_id, build_sha, prompt@version, output_sha256}` per
call, or a batch digest (§6).

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| LLM-42 | `trialbox rerun --replay` MUST reproduce packets, manifests and files byte for byte. A missing recording MUST fail the re-run, never trigger a fresh call. | T | MS1 |
| LLM-43 | Recordings MUST be retained as long as the records they support (§15) and be covered by the immutable backup. | I | MS1 |

### 8.14 Observability and the trace store

OpenTelemetry with the GenAI semantic conventions is used. These conventions were all still "Development" in mid-2026, so
`deploy/platform.lock` pins:
- the semconv version (≥ 1.37.0, where `gen_ai.provider.name` replaced `gen_ai.system`);
- the collector and SDK versions.

The collector's `transform` processor maps older names to the pinned ones.

| Span | Emitted for |
| --- | --- |
| `chat`, `embeddings` | model calls |
| `execute_tool` | front-door MCP calls |
| `invoke_agent` | Hermes turns |
| `invoke_workflow` | orchestrator workflows |

`tb.*` attributes are added to every span: `tb.data_class`, `tb.study_id`, `tb.step_id`, `tb.workflow`,
`tb.context_of_use`, `tb.prompt_id`, `tb.prompt_version`, `tb.model_alias`, `tb.build_sha`, `tb.route_id`,
`tb.guard.verdicts`, `tb.cache`, `tb.call_id`.

**Content handling.** Content capture is off for every exporter except the trace store. The trace store receives
prompts and outputs redacted by the Presidio pipeline (PHI replaced by type tags). A reviewer of a disputed judgement
follows `tb.call_id` to the recording. That access requires a purpose and is audited (§7).

**Metrics per role** (Prometheus):
- items/hour, p50/p95 latency, time to first token;
- schema-violation, retry, abstention, S4-disagreement and citation-failure rates;
- `numbers_match` failures, guard blocks, tripwire hits and fallbacks;
- cache hit rates, GPU-seconds and cost;
- the G3 human-override rate, the strongest quality signal.

**Drift.** EWMA charts on override, block and abstention rates per role and stratum; input drift on language mix and note
types (§10 ML); a daily canary of 20 fixed D0 probes per resident build, and hourly per external route. A breach opens a
QMS deviation (§15) and MAY put the role into its degraded mode.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| LLM-44 | All containers MUST emit OTLP to `otel-collector` under the pinned semconv, with the `tb.*` attributes on every model and tool span. | T | MS0 |
| LLM-45 | A planted-identifier test MUST find zero identifiers in the trace store and in Prometheus labels. The trace store MUST keep traces 90 days, log every view with user and purpose, and be reachable only through admin-listener by roles granted `trace:read` (§14). | T | MS1 |
| LLM-46 | Traces MUST NOT be the audit trail. Each trace MUST carry `tb.call_id`, which resolves to the ledger record. | I | MS0 |
| LLM-47 | Canaries and drift monitors MUST run as described. A breach MUST alert, open a deviation record, and be shown per role in the control plane. | T | MS2 |

### 8.15 LLM functions by module

This is the registry's role table, which links each role to the modules that use it. The role names `extract_soa`,
`draft_document` and `summarise_external` are the ones §10–§11 use.

| Role | Input → output | Module(s) | Class | Degraded mode |
| --- | --- | --- | --- | --- |
| `classify_intent` | stripped, tokenised text → proposal + restatement | Intake, converse-native | D1 / D3 (tokenised); D3 on box only | `queue` |
| `frontdesk_converse` | conversation, skills, tool schemas → reply, front-door tool calls | Hermes (§9) | D1 / D3 (tokenised); D3 on box only | native |
| `summarise_external` | CDR text of an external document → typed fields only (the quarantined extractor, §9.8) | M1, M3, M7, M9, quarantine workflow | D1 (documents) / D3 (forwarded mail about participants); D3 on box only | `manual` |
| `match_criterion_library` | criterion + library candidates → match id or `none`, with diff | M1 | D1 | `queue` |
| `extract_criteria` | protocol sections, unmatched criteria → IR v3 with spans and ambiguities | M1 | D1 | `queue` |
| `extract_soa` | schedule-of-activities tables → visits, windows, procedures, kits as typed rows with spans (USDM-aligned, §6) | M1, M7 | D1 | `manual` |
| `concept_select` | phrase + terminology hits → choice with reasons | M1 | D1 | `manual` |
| `answer_protocol` | question + protocol passages → answer with citations, or "not stated" | M1, `tb.ask_protocol` | D1 | `queue` |
| `propose_mapping` | columns, types, de-identified coded samples → mapping proposals | M0 | D1 | `manual` |
| `judge`, `second_opinion` | note question + evidence + exemplars → verdict, 1–3 spans, assertion, value | M4, M5, SAFE | D3 | `deterministic_only` |
| `match_keywords` | pseudonymised patient summary → English registry search keywords (patient → trials, §10.5); never leaves the perimeter | M5 | D3 | `deterministic_only` |
| `registry_match_patient` | pseudonymised summary + registry criteria → criterion labels with spans | M5 | D3 | `queue` |
| `s2b_screen`, `embed`, `rerank` | sentences, protocol text → vectors, scores | M1, M4, M5, SAFE | D3 / D1 | S2b off: zero-hit pairs go to S3 |
| `abstract_field`, `draft_query_answer` | field definition or query + facts → value with lineage; draft with citations | M8 | D3 | `manual` |
| `map_questionnaire` | field labels → pack / profile paths | M3 | D1 | `manual` |
| `draft_narrative` | pack JSON → text with placeholders; input MUST be a `DisclosedDeliverable` (RPT-14) | M3, M6, M9, §12 | D1 (aggregates) | `queue` |
| `draft_document` | template + structured inputs → sections with placeholders, as a redline (IRB/CTA, IIT skeleton, close-out) | M2, M7, M9 | D1 or D2 | `manual` |
| `summarise_aggregate` | released aggregate table → explanation, numbers by placeholder; input MUST be a `DisclosedDeliverable` (RPT-14) | M6, M11, Hermes analyst | D1 (aggregates) | native table reply |
| `ops_explain` | ops summaries → explanation, drafted runbook action | admin copilot | D1 | none |
| `guard_policy`, `guard_injection`, `phi_ner` | text + policy → verdict | all | as guarded | fail closed |
| `shadow:<role>`, `bakeoff`, `optimise_prompt` | as role; public data | evaluation | as role; D0 | skip |

M10 (NHI navigation) uses no model role.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| LLM-48 | The gateway MUST refuse a role that is not in this table for the calling container's module. CI MUST check the map against `@role` annotations in callers. | T | MS0 |
| LLM-49 | Each role MUST have a context-of-use record (FDA–EMA Good AI Practice principles, January 2026) stating intended use, risk tier, evidence and life-cycle plan, filed in the AI credibility file (§15). | I | MS1 |

### 8.16 G5 change control for the LLM platform

§11 owns the G5 mechanics and §18 the rollback procedures. An LLM artefact change also needs the following:

| Element | Content |
| --- | --- |
| Record | `changes/<yyyy>/<change_id>.yaml`: artefact, from → to (ids and SHAs), reason, risk tier, affected roles and modules, evidence ids (§8.9), rollback target, approvers |
| Approvers | System owner and QA (§11.1); security also signs for routes, external builds, guard policy and Hermes; the DPO for any class widening. |
| Fast-track | Rollback to a previous champion or a route kill (reverts and narrowings, FR-SIG-15 A2): two Level A approvals, with the evidence completed within five working days. A Hermes or gateway security patch is a bundle change, not A2: it goes through §18.4 "Security patch" (expedited bundle, CCB). |
| Batching | Exemplar, lexicon and threshold changes go out monthly, unless a recall demotion needs them sooner (§10 SAFE) |
| Effect | Applied at the next pass boundary. Running runs keep their SHAs. |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| LLM-50 | No MOD-5 artefact may change in production except through a G5 record with the required evidence and approvals. `trialbox doctor` MUST detect drift from the last approved record. | T | MS1 |
| LLM-51 | A run MUST use one consistent set of builds, prompts and thresholds from start to end. Changes MUST apply only at pass boundaries and appear in the control plane's change history and the QA pack. | T | MS1 |

## 9. Hermes Agent

Hermes Agent (Nous Research, MIT licence) is a server-resident agent with multi-platform messaging, skills, memory, MCP
and self-improvement tooling. At the research date (2026-10-17) the latest release was v0.22.2 (2026-10-15). Releases
come about weekly, and the project had a significant 2026 vulnerability history (§9.5).

TrialBox uses Hermes as an **untrusted proposer behind a narrow, audited interface**: a concierge, not a clerk. It
converses, understands intent, collects parameters, and shows status and released results. It holds no PHI tool, owns no
schedule, approves nothing, and writes no record of the regulated core. The staff text it reads is tokenised; it is D3
in packet threads and PHI-tolerant channels and is served on-prem only (FR-CONV-8, §8.5).

### 9.1 Role

| Function | What Hermes does | What it never does | Tools (§9.3) |
| --- | --- | --- | --- |
| **Front door** | One persona over email, Teams and the admin TUI (LINE carries outbound nudges only; its inbound text gets a canned pointer, profile `tb-line` has no tools); multi-turn clarification; turns plain language into a typed request for the user to confirm | parse grammar lines (Intake does); see identifiers (the relay tokenises them) | `tb.submit_request`, `tb.status` |
| **Staff concierge** | "What is due this week", request status, protocol questions, how-to answers from signed SOP skills; drafts replies to sponsors from released material | send outside the thread; contact sponsors | `tb.status`, `tb.ask_protocol`, `tb.registry_search`, `tb.resend_released_file` |
| **Aggregate analyst** | Natural-language questions from the research office over a fixed metric catalogue, answered with accountant-checked, control-rounded numbers placed by template | free SQL; patient-level rows; computing numbers itself | `tb.aggregate_query`, `tb.atlas_describe` |
| **Admin copilot** | Explains health, queues, passes, bench and eval results, and denials; drafts runbook actions for the administrator | execute anything; change configuration; touch keys | `tb.ops_read`, `tb.status` |
| **Offline optimiser** | In the development environment only, proposes prompt and skill changes with DSPy/GEPA, as pull requests into G5 (§9.11) | run on site; learn online | none |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| HER-1 | Hermes MUST hold no tool other than the front-door tools of §9.3. Three independent layers MUST enforce this: Hermes configuration (`agent.disabled_toolsets`, MCP `tools.include`), the `tb_policy_audit` `pre_tool_call` plugin, and the front-door server's authorisation. A test MUST disable each layer in turn and show that the other two still block. | T | MS0 |
| HER-2 | Hermes MUST NOT own, create or change schedules for regulated work. Those belong to the orchestrator (§11). Hermes cron MUST be disabled (`cron.allow_agent_scheduling: false`, no jobs). | T | MS0 |
| HER-3 | Hermes MUST NOT approve, sign or release anything (§9.9). | T | MS0 |
| HER-4 | Every function above MUST also be reachable through grammar lines and converse-native (§9.10). The product MUST pass all acceptance tests with `channels.engine: native`. | T | MS0 |

### 9.2 Placement and message path

Hermes runs in the channel DMZ namespace, behind channel-relay (ADR-V4-08). The following Hermes components are disabled:
- its own platform adapters;
- the webhook gateway;
- the dashboard;
- the API server;
- ACP;
- cron and delegation.

Messages reach Hermes only through the `tb_relay_adapter` platform plugin, which channel-relay calls over mTLS. Replies
return the same way.

```
 Staff ─email/Teams/LINE─▶ [channel-relay]
          1 transport + sender auth (DMARC; Entra JWT; LINE signature) → directory principal
          2 strip quoted text, signatures, invisible Unicode; attachments → cdr-sandbox
          3 grammar line or gate reply? ── yes ──▶ Intake (deterministic) ─▶ orchestrator
          4 identifiers → message-scoped tokens ([MRN-1], [NAME-1]); 5 rate limit; mint identity assertion
                │
     engine = hermes ──▶ [hermes]  LLM ─▶ tb-gateway (alias tb-frontdesk, class D1 or D3 (tokenised), on box/tenant only)
     engine = native ──▶ [converse-native]   tools ─▶ frontdoor-mcp (mTLS, assertion, policy, audit)
                │
 reply ─▶ channel-relay: outbound DLP (PHI guard, class check, policy classifier) ─▶ same sender, same thread
```

Hermes has no egress except `tb-gateway`, `frontdoor-mcp` and channel-relay. It needs no internet access.

| Profile | Channels | Tools | Notes |
| --- | --- | --- | --- |
| `tb-staff` | internal email, Teams | all except `tb.ops_read` | default |
| `tb-line` | LINE | none (outbound templates only) | inbound LINE text never reaches a model; channel-relay answers it with the canned pointer to email or Teams (FR-UX-11) |
| `tb-admin` | admin TUI, management VLAN, IdP-authenticated | `tb.ops_read`, `tb.status`, `tb.atlas_describe` | drafts only; the `trialbox` CLI remains the only way to act |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| HER-5 | The components listed above MUST be disabled, and no Hermes port (including 8642 and 9119) may be reachable outside the DMZ namespace. `trialbox doctor` MUST verify this from the running configuration and the network policy. | T | MS0 |
| HER-6 | Messages MUST reach Hermes only through `tb_relay_adapter` (`integrations/hermes/tb_relay_adapter/`), after grammar diversion, tokenisation and sender authentication. Each channel class MUST use its own Hermes profile. | T | MS0 |
| HER-7 | Hermes' platform-plugin interface may change between releases *(stability uncertain)*. `tb_relay_adapter` MUST carry a contract test that runs on every upgrade (§9.12). If the test fails, the site stays on the pin or switches to native. | T | MS0 |

### 9.3 The front-door MCP server and its tools

`frontdoor-mcp` (`services/frontdoor_mcp/`) implements MCP spec 2026-07-28 over Streamable HTTP with mTLS. It is
stateless, validates `iss` (RFC 9207) where OAuth is used, does not accept dynamic client registration, and has sampling,
roots, logging and server-initiated elicitation disabled.

Each call does the following:
1. verifies the identity assertion (§9.4);
2. resolves the user's roles and delegations;
3. checks the tool's tier and the user's purpose;
4. applies the privacy accountant to aggregates;
5. writes the audit event before returning.

| Tool | Purpose | Tier | Output | Allowed roles | Default limit |
| --- | --- | --- | --- | --- | --- |
| `tb.submit_request` | Create a typed request (FEAS, SCREEN, MATCH, ASK, REPORT, CONFIG proposal, ABSTRACT and the other grammar types) in state `proposed` | T0 (creates only) | ticket id, restatement, confirmation instruction | delegated staff | 5/h per user |
| `tb.status` | Requests, pending gates, deadlines, pipeline counts | T0/T1 | state, next gate, due date; counts control-rounded | staff; study detail if delegated | 60/h |
| `tb.ask_protocol` | Protocol answer with section citations (`answer_protocol`) | T0 (D1) | answer, citations, or "not stated" | delegated on the study | 30/h |
| `tb.registry_search` | Local ClinicalTrials.gov/MOHW index | T0 (D0) | registry fields | staff | 60/h |
| `tb.atlas_describe` | Coverage, freshness, DQ scorecard, computability | T1 | catalogue and scorecard rows, rounded | steward, research office, admin | 30/h |
| `tb.aggregate_query` | Metrics from the versioned catalogue (`services/frontdoor_mcp/metrics.yaml`): enrolment vs target, screen-fail Pareto, funnel, accrual vs forecast | T1 | control-rounded table, suppression marks, accountant entry id | research office; PI/CRC for delegated studies | 20/h plus accountant budget (§7) |
| `tb.resend_released_file` | Resend a file already released at G2/G3 to the requester's directory address, through the outbox | T0 | "sent" or a reason | the release's original recipients | 10/day |
| `tb.ops_read` | Health, passes, queues, bench, eval, denials, budgets, changes | T0 (ops metadata) | summaries | administrator | 120/h |

`HELP` is served by signed SOP skills and the grammar reference (§3), not by a tool.

**Token resolution.** If a message says "which trials could [MRN-1] fit?", Hermes may call `tb.submit_request(type=MATCH,
params={subject: "[MRN-1]"})`. The server resolves the token from the relay's token map, which is bound to the original
message, its sender and a 24-hour expiry. The result goes to the sender as a packet through the outbox. Hermes receives
only the ticket id.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| HER-8 | The server MUST expose exactly these tools. CI MUST snapshot `tools/list`, require review of any diff, and lint descriptions for imperative instructions, URLs and invisible Unicode (OWASP MCP Top 10, MCP03/MCP04). | T | MS0 |
| HER-9 | No tool may return patient-level data, an identifier, a pid, a signing link or the content of a released file. Output schemas MUST contain no free-text field filled from patient-level data. | T | MS0 |
| HER-10 | `tb.aggregate_query` MUST accept only catalogue metric ids and their listed breakdowns, and MUST pass every result through the accountant and controlled rounding (§7). | T | MS2 |
| HER-11 | `tb.submit_request` MUST create requests in state `proposed`. Nothing executes until the user confirms through Intake (§3) and the workflow's gates pass. Its parameter schema MUST reject identifier patterns other than relay tokens. | T | MS0 |
| HER-12 | Relay tokens MUST be resolvable only by the front-door server, only for the message, sender and conversation they were minted for, and only until expiry. Hermes MUST never receive the token map. | T | MS0 |
| HER-13 | Tool results passed to the model MUST be marked as untrusted spans for the gateway's injection screen (§8.6). | T | MS1 |
| HER-14 | Each call MUST write its audit event (user, tool, arguments hash, decision, result size) before returning. A ledger write failure MUST fail the call. | T | MS0 |

### 9.4 Identity and rate limits

channel-relay mints an **identity assertion** for each message. It is a JWT, ES256-signed with a relay key held in the key
service, with these claims:
- `sub`: the directory principal;
- `channel`;
- `conv`: the conversation id;
- `msg`: the message hash;
- `aud`: `frontdoor-mcp`;
- `exp`: 5 minutes (§14.4).

The `tb_policy_audit` plugin attaches the current turn's assertion to each tool call. The server checks the signature,
audience, expiry, and that `conv` matches the calling session. Hermes cannot mint assertions.

The residual risk is that a compromised Hermes replays another active user's assertion within its 5-minute life. The
worst case is T0/T1 access at that user's permission, with aggregates still accountant-checked. This is recorded in the
threat model (§14).

| Channel | Authentication at the relay |
| --- | --- |
| Email | DMARC/SPF via `Authentication-Results` with pinned `authserv-id`; exact-address allowlist from the directory. The relay parses addresses itself, so the display-name bypass class fixed in Hermes v0.21.6 does not apply. |
| Teams | Bot Framework JWT validation; Entra tenant restriction; object id → directory principal |
| LINE | `X-Line-Signature` HMAC; LINE user id linked once to a principal through an authenticated enrolment email |
| Admin TUI | IdP OIDC with phishing-resistant MFA |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| HER-15 | Every tool call MUST carry a valid assertion bound to its conversation. Calls without one MUST be refused and alarmed. | T | MS0 |
| HER-16 | Allowlists MUST be generated from directory groups (`TB-Staff`, `TB-Research-Office`, `TB-Admin`), refreshed at least daily, and not editable in Hermes configuration. `GATEWAY_ALLOW_ALL_USERS` MUST be unset. | T | MS0 |
| HER-17 | Rate limits MUST apply at the relay (per sender), the gateway (per profile, tokens per minute and daily budget) and the server (per user and tool). A breach MUST produce a fixed reply and an audit event, never a silent drop. | T | MS1 |

### 9.5 Pinned release and vulnerability history

**Pin.** The initial pin is **v0.22.2** (2026-10-15), identified by tag, commit SHA and image digest
(`nousresearch/hermes-agent:<version>@sha256:<digest>`) and mirrored internally. The **floor is v0.21.6**. That release
fixed the quoted-display-name email allowlist bypass and the dashboard authentication bypasses, and it includes the fixes
listed below. v0.22.1 was built from the wrong commit, so every upgrade verifies the digest, not just the tag. Hermes
publishes SemVer and date tags (for example `v2026.7.20` for 0.19.0), and the registry records both.

| Advisory | Class | Affected → fixed | Severity | TrialBox posture |
| --- | --- | --- | --- | --- |
| CVE-2026-82021 | MCP catalogue referenced a mutable upstream branch; RCE (CWE-494) | 0.18.2 → 0.19.0 | Critical 9.0 (CVSS v4) | floor; catalogue off; first-party MCP only |
| CVE-2026-14628 | webhook `extract_media` path traversal; public exploit; vendor did not respond | ≤ 2026.5.16; fix not stated | 5.5 | webhook gateway off; no reachability outside the DMZ namespace |
| CVE-2026-53870 | DB and webhook files world-readable | < 0.16.0 | 6.8 *(secondary source)* | floor; encrypted `/opt/data`; permissions checked by `doctor` |
| CVE-2026-10222 | `.env` sanitiser injection | < 0.18.0 | Low | floor; no secrets in `.env` |
| CVE-2026-10224 | Feishu webhook resource exhaustion | ≤ 2026.4.30 | — | adapter off |
| CVE-2026-9366 | injection via the context scanner | < 0.15.0 | Moderate | floor; controls do not rely on Hermes' scanner (§9.8) |
| CVE-2026-9368 | `execute_code` leaked environment secrets | < 0.11.0 | Moderate | toolset off |
| CVE-2026-9369 | dashboard plugin discovery comparison (local) | 2026.4.23 | Low | dashboard off |
| CVE-2026-9353 | Skills Guard bypass | *(fix uncertain)* | — | signed read-only skills; staged writes (§9.7) |
| CVE-2026-7112/7113 | API-server key check; webhook auth bypass | 0.8.0 → *(uncertain)* | Moderate | API server and webhooks off |
| CVE-2026-7396/7397, 6829 | path traversal; symlink following; web UI traversal | 0.8.0 → 0.9.0 (7397); webui < 0.50.34 | 4.0–5.3 | adapters, file tools and web UI off |
| v0.21.6 fixes (no CVE) | dashboard rate-limit and auth fixes; git filter programs; email display-name bypass | → 0.21.6 | — | floor; dashboard and Hermes email adapter off |
| CSA audit of v0.8.0 | regex shell guard, no read denylist, container mode skipping approvals, skill injection, injectable LLM approval, unsandboxed hooks, unpinned dependencies | partly fixed | 4 Critical, 9 High | terminal and file off; manual approvals; signed read-only hooks; vendored, hash-pinned dependencies |

Most of these issues sit in gateway, webhook, dashboard and plugin code. TrialBox removes those surfaces rather than
relying on patches.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| HER-18 | The release MUST be pinned by tag, SHA and digest, mirrored internally, and ≥ v0.21.6. `trialbox doctor` MUST refuse to start Hermes on a digest mismatch or a version below the floor. | T | MS0 |
| HER-19 | `integrations/hermes/ADVISORIES.md` MUST track every advisory, with the control that makes it inapplicable or the release that fixes it, and MUST be reviewed at each upgrade. | I | MS0 |

### 9.6 Hardening checklist

Configuration lives in `integrations/hermes/profiles/<profile>/config.yaml` (`tb-staff`, `tb-line`, `tb-admin`), together
with `SOUL.md`, signed skills and a hash manifest. Key names not confirmed against the pinned release are marked, and are confirmed by the configuration-diff test
(§9.12).

| # | Area | Setting or control | Verified by |
| --- | --- | --- | --- |
| 1 | Version | tag + SHA + digest ≥ v0.21.6; never `main` | `doctor`, CI |
| 2 | Surfaces | adapters, webhooks, dashboard, API server, ACP, plugin catalogue, Connectors, lazy installs (`security.allow_lazy_installs: false`), external logins (`auth.adopt_external_logins: false`) off | config test; CI port scan |
| 3 | Tools | `agent.disabled_toolsets`: terminal, file, browser, web, code_execution, delegate, cronjob, skills_manage, memory, image_gen, tts *(names to confirm with `hermes tools`)* | E3; HER-1 |
| 4 | MCP client | one server; explicit `tools.include` per profile; `prompts: false`, `resources: false`; sampling and elicitation off; mTLS client certificate; 30 s timeout | config test; traffic capture |
| 5 | Approvals | `approvals.mode: manual`; `cron_mode`, `single_query_mode`, `unattended_mode: deny`; `approvals.deny: ["*"]`; never "always" | config test |
| 6 | YOLO | `HERMES_YOLO_MODE` absent | CI; `doctor` |
| 7 | Model | `base_url` = `tb-gateway`; alias `tb-frontdesk`; context ≥ 65,536; auxiliary models on gateway aliases (`tb-guard`, `tb-router-small`); `fallback_providers` only gateway aliases (a cloud fallback moves data off site) | config test; gateway accepts D1 and D3 from Hermes, both routed on box only; never D4 |
| 8 | Plugins and hooks | only `tb_relay_adapter` and `tb_policy_audit`, signed, read-only, hash-checked at start; project plugins off; `hooks_auto_accept` off | `doctor` |
| 9 | Policy hook | `pre_tool_call` calls `tb_common.policy`; blocks on deny, error or 5 s timeout (`plugins.hook_callback_timeout: 5`); block beats approve | E3 with policy-failure injection |
| 10 | Dispatch hook | `pre_gateway_dispatch` is unbounded, so the plugin enforces a 2 s internal timeout and fails closed, and it re-checks that the message came through the relay adapter with a valid assertion | unit test |
| 11 | Observers | gateway event hooks (errors swallowed) used for metrics only | code review |
| 12 | Delegation | toolset off; `delegation.max_spawn_depth: 0` *(acceptance of 0 uncertain; toolset removal is the control)* | config test |
| 13 | Memory, skills | per §9.7 | `doctor` |
| 14 | Runtime | UID 10000; read-only root; encrypted `/opt/data`; seccomp; `cap_drop: ALL`; `no-new-privileges`; no Docker socket; CPU, memory and PID limits | container policy test |
| 15 | Network | egress only to gateway, front-door server and relay; ingress only from relay | network policy test |
| 16 | Data at rest | `state.db` encrypted, 30-day purge, permissions checked; logs redacted before shipping | `doctor`; retention test |
| 17 | Supply chain | dependencies vendored and hash-pinned; SBOM; SCA, SAST and container scan before promotion | CI |
| 18 | Monitoring | hook audit events and logs to the SIEM; alerts on unknown senders, blocked tools, injection hits, assertion failures, volume spikes | alert tests |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| HER-20 | Every checklist item MUST have an automated check in `tests/hermes/test_hardening.py` or `trialbox doctor`. A deployment that fails any item MUST NOT start. | T | MS0 |
| HER-21 | `tb_policy_audit` (`integrations/hermes/tb_policy_audit/`) MUST implement `pre_tool_call` (decide, log, fail closed), `post_tool_call`, `pre_llm_call` and `post_llm_call` (hashes, not content), plus session start and end. It MUST emit OTel spans (§8.14) and append hash-chained events to the ledger over mTLS. | T | MS0 |
| HER-22 | Any change to Hermes configuration, `SOUL.md`, skills or plugins MUST be a G5 change. The deployed set MUST match the signed manifest. | T | MS0 |

### 9.7 Memory and skills governance

**Memory** is off by default. A site MAY enable it for staff preferences only: language, digest time and preferred
studies. Writes then need approval (`memory.write_approval: true`) and are rejected on any PHI detector hit. External
memory providers are never used.

**Transcripts.** `state.db` receives tokenised text, but detection can miss, so it is treated as a potential D4 store:
- encrypted;
- retained 30 days and purged by an operations-owned job;
- excluded from general backups;
- readable only by the Hermes container and by the administrator under a ticketed purpose.

`MEMORY.md`, `USER.md` and `state.db` are listed in the data inventory as operational, non-GxP records.

**Skills** are controlled documents. Each skill's front matter carries its owner, version, effective date and SOP
reference. Skills live in `integrations/hermes/skills/`, pass QA review, are signed, and are mounted read-only. Agent-proposed
edits are staged (`skills.write_approval: true`, `guard_agent_created: true`; project discovery and hub installs off). A
nightly job exports them as pull requests into G5.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| HER-23 | Memory MUST be off by default. If it is enabled, it MUST hold only staff preferences, with write approval and PHI rejection, and no external providers. | T | MS0 |
| HER-24 | `state.db` MUST be encrypted, retained ≤ 30 days, excluded from general backups and listed in the data inventory (§7). A purge test MUST show that older records are gone. | T | MS0 |
| HER-25 | Skills MUST load only from the signed read-only directory. Agent-written skills MUST reach production only as reviewed pull requests under G5. | T | MS0 |

### 9.8 Prompt-injection posture and the quarantined extractor

The defences are layered:
1. **Internal senders only.** External sponsor and CRO mail goes to the orchestrator's quarantine workflow, never to
   Hermes.
2. **Stripped text.** Hermes sees the sender's own text only: no quoted chains, signatures, HTML or invisible Unicode.
3. **Quarantined extractor.** Attachments pass through `cdr-sandbox` and then the role `summarise_external`, a J-class call
   with no tools. It returns only typed fields: document type, protocol number, sponsor, requested items as an enumeration,
   dates and page count. Free-text fields are capped at 200 characters and screened. Hermes and any planner see only these
   fields (the CaMeL / dual-LLM pattern).
4. **Spotlighting.** Untrusted content is placed in delimited, encoded blocks under an instruction hierarchy.
5. **Classifier screen.** The gateway screens untrusted spans and tool results (§8.6).
6. **Containment.** A successful injection can at worst file a `proposed` request, or read T0/T1 data the user may read
   anyway.
7. **Outbound control.** Replies pass DLP and go only to the authenticated sender in the same thread.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| HER-26 | Non-directory senders MUST NOT reach Hermes. Their messages MUST go to the quarantine workflow (§11). | T | MS0 |
| HER-27 | `summarise_external` MUST run without tools, under a strict schema of typed fields with capped free text. Its outputs MUST be injection-screened before any other use. | T | MS1 |
| HER-28 | E4 `redteam` MUST run against the Hermes front door in CI on every Hermes, skill, prompt, guard or gateway change, in zh-TW, en and code-mixed (ja from MS6). It MUST show zero capability-bearing successes, with every attempt logged with its blocking step. | T | MS0 |
| HER-29 | Hermes replies MUST go only to the authenticated sender, in the originating thread or chat. | T | MS0 |

### 9.9 Approval boundary

Approvals stay in the orchestrator (§3, §11):
- **Level A, A2 and A+** reply approvals are matched by channel-relay on the gate token and nonce, and go straight to
  Intake.
- **Level B** signatures happen only on the signing page, with IdP re-authentication.
- **Gate notifications** are rendered by the orchestrator and sent through the outbox.
- **Hermes' own approval endpoint** (`/v1/runs/{id}/approval`) is disabled and never serves as a signature.

Hermes may tell a user that an approval is pending, what it concerns (request type and study), and to reply to the gate
email or use the signing link sent to them. It never holds or repeats signing links.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| HER-30 | Gate replies MUST bypass Hermes in both engine modes. No Hermes configuration, plugin or tool may create, modify or answer a gate. A test MUST attempt each through every enabled tool and confirm refusal. | T | MS0 |

### 9.10 Native fallback

`channels.engine: hermes | native` switches the relay's conversation target. `converse-native` provides:
- the full grammar (§3, Appendix D);
- `classify_intent` proposals with confirmation;
- deterministic status and help;
- `answer_protocol`;
- an `AGG <metric> <study|portfolio> <period>` line over the same metric catalogue.

It calls the same tool implementations in-process, under the same policy and audit.

| Capability | Hermes mode | Native mode |
| --- | --- | --- |
| Grammar lines, gate replies | relay → Intake | relay → Intake |
| Free text → proposal | multi-turn clarification | one proposal per message (v3) |
| Status, help, protocol Q&A | conversational | templates; one answer per message |
| Aggregate analyst | natural language over the catalogue | `AGG` line |
| Admin copilot | `tb-admin` TUI | `trialbox` CLI and control plane |
| Teams and LINE nudges | yes | yes |

The switch is manual, from the control plane or with `trialbox channels engine native`. It is also automatic:
- during the publish window and night passes on single-accelerator profiles (§4.6);
- after Hermes fails its health check for more than 2 minutes;
- when the Hermes denial rate crosses its threshold (§18 defines the rollback trigger).

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| HER-31 | Switch times follow one rule: kill switch and automatic health-check fallback: engine switched ≤ 60 s (FR-UX-23); full channel rollback incl. verification ≤ 15 min (§18.5.5). A switch MUST lose no message (the relay queues inbound), and be audited. Open Hermes conversations MUST receive a fixed message that explains how to continue. | T | MS0 |
| HER-32 | CI MUST run the channel end-to-end and acceptance suites (§16) in both modes on every release. The control plane MUST show the current engine, the scheduled native windows and the reason for any automatic switch. | T | MS0 |

### 9.11 Offline optimisation

`hermes-agent-self-evolution` (DSPy, GEPA) runs only in the development environment. It works on D0 evaluation sets, or
on D2 sets on an on-box evaluation host. It optimises `frontdesk_converse` text and skills, `classify_intent`,
`answer_protocol` and other D1 prompts. Its output is a pull request with the diff and E1–E4 results against the champion,
and that pull request enters G5. Nothing is applied automatically, and nothing learns online.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| HER-33 | Optimisation MUST run only in development, on D0 data (or D2 on an on-box evaluation host), and MUST produce pull requests with E1–E4 results, never direct changes. | I | MS4 |

### 9.12 Upgrade policy

| Trigger | Action | Deadline |
| --- | --- | --- |
| High or Critical advisory affecting an **enabled** component | upgrade, disable the component, or switch to native, as a G5 fast-track change | ≤ 7 days |
| Advisory affecting only disabled components | record it; take it with the next upgrade | next quarter |
| Functional release | evaluate in dev; take only for a needed fix or feature | quarterly |
| Mis-built or withdrawn release (as v0.22.1 was) | stay on the pin | — |

Every upgrade runs these checks:
- SCA, SAST, container scan and SBOM diff;
- a **configuration-default diff** of new keys and changed defaults (new features have shipped enabled by default before:
  MCP sampling, for example);
- the `tb_relay_adapter` contract test;
- the `tools/list` snapshot;
- E1, `intent`, E3, E4 and the hardening tests;
- 48 hours on `tb-admin`, then promotion to `tb-staff` and `tb-line`.

Rollback is a re-pin of the previous digest, or native mode (§18).

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| HER-34 | Operations MUST subscribe to the repository's security advisories and triage each within 2 working days. Deadlines MUST follow the table above. | I | MS0 |
| HER-35 | No upgrade may be promoted before it passes all the checks above. Upgrades MUST NOT track `main` or an unsigned build. | T | MS0 |

### 9.13 Observability and tests

`tb_policy_audit` emits `invoke_agent` and `execute_tool` spans, with hashes in place of content outside the trace store.
The control plane's Hermes panel shows:
- sessions per profile;
- tool calls by decision;
- denials and their reasons;
- assertion failures;
- injection hits;
- the engine mode;
- the pinned version against the latest advisory.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| HER-36 | Alerts MUST fire on any assertion failure, on a denial rate above the site threshold (default 5 % of tool calls in an hour), and on any attempt to call a tool outside the profile's list. | T | MS1 |
| HER-37 | The Hermes test set MUST include: (a) the three-layer tool boundary; (b) relay-only ingress and DMZ egress; (c) assertion forgery, expiry, cross-conversation replay and absence; (d) token resolution across messages and senders; (e) PHI planted in text, attachments and tool results, checked absent from Hermes inputs, `state.db`, traces and replies; (f) gate replies bypassing Hermes; (g) native parity; (h) the configuration-default diff; (i) E3 policy tasks; (j) E4 `redteam` in all languages. | T | MS0 |
| HER-38 | When `tb-frontdesk` is resident, conversational response times over T0/T1 tools MUST meet the targets of §13. The bench (NFR-B17 (d)) MUST record them on the installed profile. | T | MS1 |
