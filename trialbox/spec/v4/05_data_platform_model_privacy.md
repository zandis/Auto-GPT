## 5. Data platform

v3 had one adapter that read SQL views, CSV or FHIR Bulk and wrote NDJSON and a DuckDB lake in one step (`services/adapter/pipeline.py`). v4 replaces it with a staged data platform. Every stage has an owner, contracts, controls and a lineage event. Every published snapshot is reconciled against its sources, is replayable, and carries a lineage id through to every deliverable. This section is normative for findings R3-09 to R3-15. Data classes, topologies and legal bases are defined in §7. Schemas are in §6. Module-level functional requirements for onboarding and the Data Atlas (M0) are in §10.0. Throughput and latency NFRs are in §13.

**Conventions in this section.**

- *SI* is the **standardised intermediate**: the TrialBox canonical tables at L2. Both FHIR and OMOP are written from it.
- *Snapshot T* is one published, immutable, as-of state of the curated lake.
- "Source" means one configured feed in `site/sources.yaml`.
- Times are UTC in every manifest, lineage event and audit record (ICH E6(R3) §4.2.2). The source's local time and zone are kept alongside.

### 5.1 Roles

Each L-stage control and each release is assigned to one of these roles. The vendor has no standing access to D3 or D4 data in any topology.

| Role | Typical holder | Data-platform duties |
| --- | --- | --- |
| Data controller (data owner) | The hospital | Approves sources, purposes and releases. Accountable under PDPA, the EMR regulation and (Japan) APPI. |
| Data steward | Research-informatics staff, one per source | Owns the source's data contract, mapping spec, code maps, DQ thresholds and publish-gate decisions. Gate G0 approver. |
| Data custodian | Hospital IT, or TrialBox operations under contract | Runs the platform, keys, backups and provisioning. Makes no content decisions. |
| Honest broker | Hospital research office or de-identification unit | Holds research-ID ↔ MRN link tables and the PPRL keys (§7.10). Performs linkage on request. Never part of the TrialBox processing role. |
| Terminology steward | Medical-records / coding unit | Approves local code maps (NHI → ATC/LOINC/SNOMED) and calculator versions. |
| DPO / privacy officer | Hospital | DPIA, D2 release sign-off, cross-border assessment, erasure tickets, breach handling (§14). |
| PI / delegate | Investigator, delegated CRC | Consumes candidate lists inside the delegation scope. Approves re-identification. |
| Processor (vendor) | TrialBox supplier | Software and support only. Remote access is break-glass, time-boxed and audited (§14). |

### 5.2 Zones

A **zone** is a storage and processing compartment with one maximum data class, its own database roles, its own encryption keys and its own egress rules. A row never moves to a zone of lower class except through a registered **declassification transform** (§7.1), which leaves a certificate behind.

| Zone | Max class | Contents | Stores | Readers | Egress |
| --- | --- | --- | --- | --- | --- |
| **Z-REF** Reference | D0 | Terminologies, public registry trials (ClinicalTrials.gov), open datasets, NHIRD-derived published priors | Postgres `tb_ref`, Iceberg `ref.*` | All services | Free |
| **Z-IDN** Identified | D4 | L0 raw batches of identified sources; L1–L2 working sets; identity vault (MPI, MRN, name, national ID, phone, address); tokenisation vault | Object store bucket `l0-idn` (write-once), Postgres `tb_vault` (separate cluster or instance), working Parquet on an encrypted scratch volume | `tb-ingest` (L0–L3 only), `tb-vault` | None. Re-identification only through `tb-vault` (§7.5) to delegated recipients. |
| **Z-PSN** Pseudonymised clinical | D3 | L4 curated lake, FHIR store, OMOP schema, FTS and embedding indexes, judgement cache, candidates, evidence | Iceberg `psn.*`, HAPI FHIR `tb-fhir`, Postgres `tb_omop`, DuckDB read engines | Workflow steps with T2 tools (§4), `tb-omop`, matching engine | Only to Z-REL through the privacy accountant, or to Z-TRE through the de-identification pipeline |
| **Z-TRE** Research and evaluation (trusted research environment) | D2 | CGRD-type research DB snapshots; validation-replay lakes; evaluation and calibration sets; D2 exports awaiting release; synthetic twins | Iceberg `tre.*`, Postgres `tb_tre` (own role), separate object-store prefix and key | Steward-approved project roles only (Five Safes, §7.12) | No network egress. Outputs only through steward output review (§7.12). |
| **Z-REL** Release | D1 | Aggregates after the privacy accountant; signed packs; questionnaires; certificates | Object store `rel/`, Postgres `tb_release` | Outbox, Hermes (aggregate tools, §9) | Email and sponsor exchange after G2 |
| **Z-DEV** Development | D0 | Synthea, MIMIC-IV demo, NCBI cohorts, bake-off inputs | Separate environment (§16) | Developers, CI | Free (OpenRouter permitted for D0 only, §8) |

Free text is a special case inside Z-PSN. Notes are keyed by pid, but their bodies still contain names, phone numbers and addresses. They are **D3 with residual direct identifiers**: they follow D3 location rules, they never leave the perimeter, and they are never part of a D2 export unless the text de-identification pipeline (§7.6) has run and passed its gate. Evidence quotes are shown verbatim to delegated recipients only.

### 5.3 Stages L0–L5

Each stage is a job type in `services/dataplat/` (§5.19) with a stable OpenLineage job name. Each stage emits START and COMPLETE (or FAIL) run events (§5.15). Stages run per source batch (L0–L2) or per publish cycle (L3–L5).

| Stage | Owner (role) | Input contract | Output contract | Controls | Failure handling | Lineage job | Retention |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **L0 Landing** | Custodian | Connector output (rows, NDJSON, ER7 messages, change events, files) plus source control totals | `l0_batch_manifest` (§6.14): `{batch_id, source, kind, extract_start, extract_end, rows, bytes, sha256 per object, schema_fingerprint, watermark_from, watermark_to, control_totals, encoding, data_class}`; immutable objects | Write-once (object lock or `chattr +i` on A); sha256 per object; no transformation; encoding detected and recorded; source control totals captured in the same transaction as the extract | Connector error → batch `FAILED`, no partial batch visible; retry with backoff; after 3 failures, steward alert. HL7 v2: persist before ACK, else NAK. | `tb.l0.land.<source>` | 90 days, then crypto-shred; legal hold overrides; erasure purges (§5.14.4) |
| **L1 Validation** | Steward | L0 batch + data contract version (§5.8) | `validation_report` (pass/warn/block per rule with Kahn label), `accepted` set, `quarantine` set with reason codes, reconciliation record | Data contract (schema, types, keys, nullability, enumerations, code systems, patterns); referential integrity; reconciliation L0 vs source totals (§5.9); Kahn/GX rules (§5.10); schema and distribution drift (§5.8.3) | Blocking finding → batch held, nothing downstream runs for this source, previous snapshot stays current, steward emailed with the diff. Quarantined rows never silently dropped: counted and reported. | `tb.l1.validate.<source>.<table>` | Reports 5 years; quarantine sets 30 days |
| **L2 Standardise** | Steward (mapping), terminology steward (codes) | L1 accepted set + mapping spec (hash) + terminology release | SI tables (Parquet, §5.12.3) with bitemporal and provenance columns; FHIR R4 NDJSON (TW Core / JP Core); OMOP staging tables; canonical text (§6.4); terminology coverage and unit reports | Mapping spec hash pinned; ROC and Japanese-era dates → ISO 8601 with the original kept; UCUM units; terminology `$validate-code` and `$translate` through `tb-terminology` (§5.11); edition-aware coding; profile validation of a sample (≥ 1 % and ≥ 1,000 resources) | Unmapped codes are kept with `concept_id = 0` and counted; coverage below the contract floor → blocking; validator error rate > 0.5 % → blocking (v1 rule kept) | `tb.l2.standardise.<source>` | Working sets 7 days (rebuildable from L0) |
| **L3 Pseudonymise** | Custodian (keys), DPO (policy) | SI tables with identifiers | SI tables keyed by `pid` with direct identifiers removed; vault upserts; consent and opt-out application record; MPI events | MPI resolution (MRN → `mpi_id`, §5.14); `pid = HMAC(K_pid, mpi_id)`; identifiers to `tb-vault` only; tombstone blocklist applied; consent scopes applied (§7.13); free-text left verbatim (D3 rule, §5.2) | Unresolvable identity → row quarantined with reason `IDN-*`; vault unavailable → stage fails closed (no fallback to unkeyed ids) | `tb.l3.pseudonymise` | Vault: while the patient relationship lasts, subject to erasure; L3 working sets 7 days |
| **L4 Curated lake** | Steward | L3 output for all sources in the cycle | Iceberg table snapshots under the publish manifest; snapshot manifest (signed); OMOP CDM 5.4 tables; FHIR store load | Write-audit-publish (§5.13.2); DQD on OMOP; reconciliation L3 → L4 and snapshot-level balance; publish gate (§5.9.3); snapshot signature (Ed25519, v1 `tb_common.crypto`) | Gate fails → Iceberg commits are not referenced by any manifest and are rolled back; previous snapshot stays `CURRENT` | `tb.l4.publish` | Last 3 nightly + each month-end for 36 months (v1 rule), plus every snapshot referenced by a signed output until that output's retention ends; erasure overrides |
| **L5 Serving** | Custodian | Published snapshot manifest | Read paths: DuckDB over pinned snapshots; OMOP in Postgres for OHDSI tools; FHIR read API; FTS and embedding indexes; aggregate API through the privacy accountant; intraday overlay (§5.7.2) | Row-level scoping by study and delegation; query guard (v1 `sqlguard`); class check on every tool (§4); accountant on every aggregate (§7.8) | Index build failure → snapshot stays published, the affected tool reports `stale_index` and the run manifest records it | `tb.l5.serve.<path>` | Indexes follow their snapshot; judgement cache 24 months *(est.)*, purged on erasure |

### 5.4 End-to-end data flow

```
 HOSPITAL SOURCES                                        TRIALBOX PERIMETER (topology A appliance or B tenant)
 ───────────────────                                     ─────────────────────────────────────────────────────────────────────────────
                                                          Z-IDN (D4)                                    Z-PSN (D3)
 HIS DB (Oracle/MSSQL/  ─ db_view: RO account, views ─┐   ┌──────────┐  ┌──────────┐  ┌───────────┐    ┌────────────┐   ┌──────────────┐
 Postgres/Db2)          ─ cdc: Debezium / change tbl ─┤──▶│ L0       │─▶│ L1       │─▶│ L2        │─┐  │ L3         │──▶│ L4 Curated   │
 Interface engine (OIE ─ hl7v2: MLLP/TLS copy feed  ─┤   │ Landing  │  │Validation│  │Standardise│ │  │Pseudonymise│   │ Iceberg psn.*│
  or hospital engine)    ADT SIU ORU MDM             │   │ write-   │  │contracts │  │ SI → FHIR │ ├─▶│ MPI → pid  │   │ OMOP 5.4     │
 FHIR server           ─ fhir_bulk: $export 3.0.0 ───┤   │ once,    │  │reconcile │  │ SI → OMOP │ │  │ vault      │   │ FHIR store   │
                         SMART Backend Svcs 2.2.0    │   │ manifest │  │DQ, drift │  │ terminol. │ │  │ consent/   │   │ snapshot     │
                       ─ fhir_rest: per patient only ┤   │ sha256   │  │quarantine│  │ canon text│ │  │ opt-out    │   │ manifest     │
 SFTP drop (registry,  ─ file_drop: manifest+.sha256 ┘   └──────────┘  └────┬─────┘  └───────────┘ │  └─────┬──────┘   └──────┬───────┘
  cancer registry long                                                     │ block               │        │ identity        │ PUBLISH GATE
  form, consent, CTMS)                                                     ▼                     │        ▼                 │ (L1+L2+L3+L4
                                                                      steward email              │   ┌──────────┐           │  checks, §5.9)
                                                                      (diff, reasons)            │   │ tb-vault │◀─ resolve(pid, purpose,
 Research DB (CGRD-type) ─ file_drop / db_view ──────────────────────────────────────────────┐   │   │ MPI, MRN │   approval) after G3
  de-identified at source                                                                     │   │   │ tokens   │           │
                                                                      Z-TRE (D2)              ▼   │   └──────────┘           ▼
                                                                      ┌──────────────────────────┐│              ┌──────────────────────────┐
 Honest broker ◀── PPRL tokens / enrolment list ───────────────────── │ tre.* L0–L4 (same stages,││              │ L5 Serving               │
  (hospital, holds link table)                                        │ own keys, no egress)      ││              │ DuckDB (pinned snapshot) │
                                                                      │ validation replay, eval,  │◀── de-id ─────│ OMOP (Postgres) → DQD,   │
                                                                      │ D2 exports, synth twins   │   pipeline    │   Achilles, ATLAS        │
                                                                      └────────────┬─────────────┘   (§7.6)      │ FHIR read API, CDS Hooks │
 Cohort / alliance ◀──── signed aggregates, DP answers ◀──────────────────────────┼──────────────────────────────│ FTS + embeddings         │
 NHIRD/HWDC publications ── aggregate priors (D0/D1) ──▶ Z-REF                    │ output review              │ T2 tools (cascade S0–S5) │
 Terminologies (ICD-10-CM TW, NHI, ATC, LOINC-TW, UCUM, SNOMED*) ──▶ tb-terminology│                            │ aggregate API ──▶ privacy│
                                                                                  ▼                            │   accountant (§7.8)      │
                                                                      Z-REL (D1): packs, questionnaires, certificates ◀────────────────┘
                                                                                  │ G2
 Lineage: every stage ─▶ OpenLineage events (Postgres) + FHIR Provenance ─▶ lineage_id on every deliverable ─▶ outbox (email, sponsor)
```

\* SNOMED CT only where the site holds a licence (§5.11).

### 5.5 Connector framework

All sources implement one interface in `services/dataplat/connectors/base.py`. It replaces the v1 `Source` protocol (`services/adapter/sources/base.py`), which streamed rows only.

```python
class Connector(Protocol):
    kind: Literal["db_view", "cdc", "hl7v2", "fhir_rest", "fhir_bulk", "file_drop"]
    def plan(self, contract: DataContract, since: Watermark | None) -> ExtractPlan: ...
    def control_totals(self, plan: ExtractPlan) -> ControlTotals: ...      # same transaction or snapshot as extract
    def extract(self, plan: ExtractPlan, sink: LandingSink) -> L0BatchManifest: ...
    def full_keys(self, table: str) -> Iterator[KeyHash]: ...              # for weekly key reconciliation
    def health(self) -> ConnectorHealth: ...
```

| Kind | Mechanism | Increment | Deletes | Default latency class |
| --- | --- | --- | --- | --- |
| `db_view` | JDBC/ODBC (SQLAlchemy) with a read-only account on DBA-owned views, on a replica or reporting DB where one exists | Watermark column per view (`>=` last watermark minus an overlap of 1 h, deduplicated on key + version) | Invisible; weekly full-key reconciliation tombstones missing keys | daily |
| `cdc` | Debezium Server (Apache-2.0) reading the transaction log, or native change tables (SQL Server CDC) read as a `db_view` with LSN watermark | Log position (LSN/SCN) | Captured | intraday (≤ 5 min micro-batches) |
| `hl7v2` | MLLP over TLS listener (`tb-hl7`), copy feed from the hospital's interface engine | Per message | Via cancel and delete events (A11, A13, S15, S17, T11) | real time |
| `fhir_bulk` | Bulk Data Access `$export` (Group, Patient, system level) | `_since` = previous manifest `transactionTime` | `deleted` array in the manifest | daily |
| `fhir_rest` | Per-patient read and `$everything` | n/a | n/a | on demand |
| `file_drop` | SFTP or SMB landing share with manifest and `.sha256` sidecar per file | Per file set | Full replacement per declared scope, or explicit delete file | periodic or static |

**Planner rule.** `fhir_rest` is limited to per-patient retrieval (chart review, `FULLREVIEW`, CDS). The planner refuses a population query on a `fhir_rest` source.

**Latency class.** Every source declares one of `real_time`, `intraday`, `daily`, `periodic` or `static`. Every feasibility packet and candidate list prints the data cut of each contributing source (§6.9 `data_cut_per_source`).

### 5.6 Per-source data streams

#### 5.6.1 Summary

| Source | Transport | Cadence | Identity | Zone | Data class (at L0 → after L3) | Control totals | SLO *(targets, est.; normative values in §13)* |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HIS DB views | JDBC/ODBC, TLS, RO account, DBA views on replica | Nightly delta at the 19:00 cut; weekly full-key reconciliation (Sun) | MRN → MPI | Z-IDN → Z-PSN | D4 → D3 | `count(*)`, `count(distinct patient_key)`, `min/max(watermark)`, `sum(keyhash mod 2^31)`, per-day counts over the delta window | Extract + L0–L4 delta ≤ 120 min at 3M patients; reconciliation delta 0 |
| HIS log-based CDC | Debezium Server → durable queue → `tb-ingest`; or native change tables | Micro-batches ≤ 5 min | MRN → MPI | Z-IDN → Z-PSN | D4 → D3 | Per micro-batch: events by op (c/u/d), LSN range continuity, per-table counts; nightly view-count cross-check | Event → intraday overlay ≤ 10 min p95; no LSN gap |
| CGRD-type research DB | `file_drop` (CSV/Parquet export) or `db_view` on the research DB | Per release (typically quarterly; per approval) | Research ID only; honest-broker link outside TrialBox | Z-TRE only | D2 → D2 | Per table rows, distinct research IDs, per-year counts, sha256 per file; data dictionary version | Onboarding of a new release ≤ 2 working days after files land |
| FHIR server | HTTPS, Bulk Data 3.0.0 (2.0.0 accepted), SMART Backend Services 2.2.0 | Nightly `_since` incremental; monthly full Group export | `Patient.identifier` (MRN system) → MPI | Z-IDN → Z-PSN | D4 → D3 | Manifest `output[].count` per type vs NDJSON lines; `deleted` count; `transactionTime` continuity | Kick-off to L4 ≤ 4 h at 3M patients *(server-dependent)* |
| HL7 v2 feeds | MLLP over TLS 1.2+ (TLS 1.3 preferred), copy feed | Real time | PID-3 (MRN, assigning authority) → MPI | Z-IDN → Z-PSN | D4 → D3 | Per hour: messages by type, ACK codes, MSH-10 duplicates, sequence gaps; nightly cross-check against `db_view` counts for the same day | Durable write + ACK ≤ 1 s p99; to intraday overlay ≤ 5 min p95 |
| CSV / registry drops | SFTP (key auth) with manifest + `.sha256` | Per publication (cancer registry monthly or quarterly; consent registry daily) | MRN or registry ID → MPI | Z-IDN → Z-PSN | D4 → D3 | Declared rows per file, column count, quote balance, sha256 | Validation report ≤ 30 min after drop |
| Cohort / alliance | Signed COHORT tables by email (v1), OHDSI study packages (Strategus) run locally | Quarterly or per request | None (aggregates) | Z-REL in, Z-REL out | D1 | Signature, cell count, suppression flags, ε spent | Answer within the alliance SLA (§10.11) |
| NHI MediCloud (gated) | Per-patient query through the hospital's authorised workstation integration *(mechanism uncertain)* | On care events only | MRN + national ID (in vault) | Z-IDN → Z-PSN | D4 → D3 | Query log count vs evidence items created | n/a (disabled by default) |
| NHIRD / HWDC | None (manual import of published or HWDC-reviewed aggregate tables) | Yearly | None | Z-REF | D0 (publication) or D1 (collaborator output) | Row count, sum of counts, source reference | n/a |

#### 5.6.2 HIS database views and log-based CDC

**Views (default route).** The DBA owns the views. TrialBox gets a read-only account and never issues DDL. Each view in the data contract declares a key, a watermark column (or `none`), a patient key and a numeric checksum expression. The extract and its control-total query run in one read-consistent transaction (Oracle `SET TRANSACTION READ ONLY`; SQL Server `SNAPSHOT` isolation where enabled; PostgreSQL `REPEATABLE READ`; Db2 `RS` or `RR`, or a point-in-time replica, never `UR`). Both statements are also bounded by `watermark < cut`, so rows committed after the cut are excluded from both sides. The v1 `cgrd_sql` source and its identifier validation carry over into `connectors/db_view.py`.

Views cannot see deletes and their watermark columns are often wrong. Two compensating controls are mandatory:

1. An **overlap window**: each delta re-reads one hour before the last watermark and deduplicates on (key, version hash).
2. A **weekly full-key reconciliation**: the connector streams `keyhash = sha256(key)` for every row and compares the set with L4. Keys missing at source are tombstoned (`deleted_at`, reason `source_absent`). Keys present at source but missing in L4 trigger a targeted re-extract.

**CDC (upgrade, per table, DBA approval).** CDC exists for the three domains where same-day freshness matters: appointments, encounters and lab results. Notes and medications stay on views unless the DBA asks otherwise.

| Engine | Mechanism | Prerequisites (stated to the DBA before approval) |
| --- | --- | --- |
| Oracle | Debezium Oracle connector, LogMiner, **uncommitted mode** (default; lowest database load) | ARCHIVELOG mode, supplemental logging on captured tables, a LogMiner user. XStream needs an Oracle GoldenGate licence and is not used. Initial snapshots take `ROW SHARE` locks and risk ORA-01555 beyond `UNDO_RETENTION`, so TrialBox seeds from the view extract instead and starts CDC at the extract SCN. |
| SQL Server | Native CDC tables (preferred: read as `db_view` with LSN watermark), or Debezium SQL Server connector | CDC enabled on the database and on each table; SQL Server Agent running. Offsets commit periodically, so duplicates after outages are expected. |
| PostgreSQL | Debezium PostgreSQL connector (`pgoutput`) | Logical replication slot and publication; slot lag monitored (alarm at 1 GB *(est.)*). |
| **Db2 (LUW)** | Debezium Db2 connector over **SQL Replication (ASN capture)** | **Needs a separate IBM InfoSphere Data Replication (IIDR) licence.** Debezium's z/OS support is incubating. Without the licence, a Db2 site uses views plus the HL7 v2 feed for same-day events. This is the expected configuration at a CGMH-type Db2 data platform. |

Every CDC consumer is idempotent on `(source, table, primary key, LSN/SCN)`. Debezium may redeliver after a restart. Change events land at L0 as append-only NDJSON segments, one per micro-batch, each with its LSN range. L1 checks that consecutive segments have contiguous ranges. A gap is blocking for the intraday overlay but not for the nightly snapshot, because the nightly view extract covers it.

#### 5.6.3 CGRD-type research database (TRE zone)

A CGRD-type database is "a de-identified database derived from original medical records" (Tsai et al., *Biomed J* 2017). It differs from the HIS in identity, freshness and lawful basis. TrialBox therefore handles it as a separate zone.

| Property | Rule |
| --- | --- |
| Zone and class | Z-TRE, D2. Its own Iceberg namespace (`tre.<release>`), database role, encryption key and object-store prefix. No join with Z-PSN is possible in SQL, because the engines run under different roles and catalogs. |
| Approval | Each release records its IRB reference and the research-database access approval. Its project record (§7.12) carries the purpose codes `feasibility`, `validation` or `evaluation`. |
| Forbidden use | **Never used to form pre-screening candidate lists.** Lists need re-identification, which the source does not allow. The planner refuses a `SCREEN` or `MATCH` workflow whose scope resolves to a Z-TRE dataset. |
| Permitted use | Feasibility estimates (labelled with the source and its data cut), validation replay of closed studies (§16), evaluation and calibration sets, OMOP characterisation. |
| Data cut per domain | Recorded separately for encounters, labs, notes and registry. Lags differ by domain (internal pilot notes: registry about 1.5 years, outpatient oncology notes about 6 months, general exports 3–6 months behind the EHR *(internal, uncertain)*). Feasibility outputs print the **oldest** contributing cut. |
| Linkage | Only through the honest broker (§7.10). The research-ID ↔ MRN link table stays with the broker. TrialBox never holds it. Linked results return as aggregates or as research-ID-keyed labels inside Z-TRE. |
| Onboarding | The `onboard` job (§5.17). |

#### 5.6.4 FHIR server: Bulk Data Access and SMART Backend Services

**Versions pinned.** FHIR R4 4.0.1; TW Core IG 1.0.0 (`tw.gov.mohw.twcore#1.0.0`); JP Core for the Japan profile *(version pinned at MS6; uncertain)*; **Bulk Data Access IG 3.0.0** (STU3, published 2025-12-11), with servers implementing 2.0.0 accepted; **SMART App Launch 2.2.0 Backend Services**. A 4.0.0 Bulk Data ballot exists (2026-08-07) and is not used.

**Authentication (SMART Backend Services 2.2.0).**

1. Discovery: `GET [base]/.well-known/smart-configuration` for `token_endpoint` and supported signing algorithms.
2. The client is registered with the server out of band. TrialBox publishes its public JWKS. The private key (ES384 preferred, RS384 accepted) lives in the secrets store (§14) and is rotated at least yearly with overlapping `kid`s.
3. Token request: `grant_type=client_credentials`, `client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer`, `client_assertion` = a JWT with `iss = sub = client_id`, `aud = token_endpoint`, a unique `jti` and `exp` ≤ 5 minutes after issue (private_key_jwt).
4. Scopes are `system/<Type>.rs` (SMART v2 syntax), limited to the resource types the data contract declares.
5. Access tokens are expected to live ≤ 300 s. No refresh tokens are requested or accepted. The client re-authenticates per kick-off and per long download.
6. TLS 1.2 or later; TLS 1.3 preferred.

**Export.**

1. Kick-off: `GET [base]/Group/[id]/$export?_type=<declared types>&_since=<last transactionTime>` with `Prefer: respond-async` and `Accept: application/fhir+json`. Group-level export is the default, with a hospital-maintained Group for the scoped population. System-level export is used only where the server offers no Group.
2. 202 Accepted with `Content-Location`. Poll with exponential back-off that honours `Retry-After`.
3. Completion manifest: `transactionTime`, `requiresAccessToken`, `output[] {type, url, count}`, `deleted[]`, `error[]`.
4. Downloads are resumable (HTTP range requests where supported, otherwise per-file restart). Each file is checked against `count` and hashed into the L0 manifest.
5. `deleted[]` entries (transaction Bundles of DELETE requests) become tombstones at L4.
6. The next `_since` is the manifest's `transactionTime`, never the client clock.
7. `_typeFilter` and `_elements` are experimental in the IG. They are used only when the server's CapabilityStatement declares them, and never to drop elements that the data contract marks as required.

NDJSON lands at L0 unchanged. L2 maps TW Core resources into SI and back out as canonical FHIR, so FHIR-sourced and table-sourced data take the same path. v1 `pseudonymise_bulk` (rewrite of references to pseudonyms) moves into L3. FHIR facades often omit notes and pathology narrative. The data contract records which domains a FHIR source does not cover, and the Data Atlas (§5.16) reports them as coverage gaps.

#### 5.6.5 HL7 v2 feeds

HL7 v2 is the only route that brings same-day appointments, admissions and results to TrialBox without a CDC licence. TrialBox **receives a copy feed** from the hospital's existing interface engine. It does not replace that engine. Where a site has no engine, or needs one for routing, the bundled option is **Eclipse Open Integration Engine** (MPL-2.0), the community fork of Mirth Connect 4.5.2. Mirth Connect is proprietary from 4.6 (March 2025) and is used only if the hospital already licenses it.

| Item | Rule |
| --- | --- |
| Versions | v2.3 to v2.5.1 accepted; v2.5.1 is the reference. |
| Transport | MLLP framing over TLS 1.2+ (mutual TLS with the engine's client certificate). Plain MLLP is allowed only on a dedicated VLAN between the engine and the box, as a documented site deviation. |
| Messages | ADT A01, A02, A03, A04, A05, A08, A11, A13, A28, A31, **A40** (merge patient, patient identifier list), A37 (unlink); SIU S12, S13, S14, S15, S17, S26; ORU R01 (OBR/OBX with result status P/F/C); MDM T02, T08, T11; optional ORM O01 / OML O21. Other types are acknowledged and discarded with a count. |
| Character sets | MSH-18 honoured (`UNICODE UTF-8`, `BIG-5`, `CNS 11643-1992`, ISO IR 87 for Japanese). Bytes are stored raw at L0; decoding happens at L1 and the decoder is recorded. |
| Durability | The raw message is written to L0 (append-only segment plus Postgres index row with MSH-10) and fsynced **before** the ACK. Failure to persist → AE/AR with an error, so the engine retries. |
| Acknowledgement | Original mode: AA on durable write. AE for a parse failure (the message is still persisted to quarantine). AR only for transport or authentication failure. |
| Deduplication | On (MSH-4 sending facility, MSH-10 control id). Duplicates are counted and not re-processed. |
| Ordering | Per patient by (MSH-7, arrival sequence). An out-of-order update older than the stored version is kept as history and does not overwrite it. |
| Replay | Any time window can be replayed from L0 into L1 (`trialbox data replay --source hl7 --from … --to …`), for example after a mapping fix. |
| Z-segments | Mapped per site in the data contract. Unknown Z-segments are kept raw and reported. |
| Merge | A40 writes to the MPI merge table (§5.14.2). |

#### 5.6.6 CSV and registry drops (including the cancer registry long form)

Every `file_drop` set carries a manifest (`{files[], rows per file, columns, encoding, delimiter, quote, produced_at, producer, scope}`) and a `.sha256` sidecar per file. Encodings are declared (Big5/CP950, UTF-8, Shift_JIS for Japan) and checked by detection. The recurring defects seen in pilot exports are each an explicit L1 check: numbers stored as text, junk in join keys, truncated files and unquoted delimiters *(internal)*. A file whose row count, column count or quote balance fails the contract is quarantined whole.

**The hospital cancer registry (癌症登記) long form** is a first-class source. It is the most valuable structured oncology source for eligibility: stage, biomarkers through site-specific factors (SSF), and prior treatment lines. It also lags by up to about 1.5 years *(internal)*.

| Registry content | SI target | OMOP CDM 5.4 | FHIR (TW Core; mCODE informative) |
| --- | --- | --- | --- |
| Primary site and histology/behaviour (ICD-O-3), grade, laterality, date of diagnosis | `condition` + `condition_attribute(path = histology | grade | laterality)` | `CONDITION_OCCURRENCE` (ICD-O-3 source) + `EPISODE` (disease episode) | Condition (+ bodySite, stage) |
| Clinical and pathological TNM and stage group (AJCC edition recorded) | `condition_attribute(path = stage.clinical | stage.pathological | tnm.*)` | `MEASUREMENT` linked through `EPISODE_EVENT` | Observation (stage) referenced from Condition.stage |
| Site-specific factors (for example ER, PR, HER2, EGFR, ALK, PD-L1 where abstracted) | `condition_attribute(path = biomarker:<code>)` | `MEASUREMENT` | Observation (laboratory / tumour marker) |
| First-course treatment (surgery, radiotherapy, chemotherapy, hormone, targeted, immunotherapy; dates) | `treatment_course` → input to `episode_lot` (§6.2.2) | `EPISODE` (treatment regimen) + `EPISODE_EVENT` | Procedure, MedicationStatement |
| Vital status, last contact, registry last-update date | `registry_case.last_update`, `death` | `DEATH`, `OBSERVATION_PERIOD` hint | Patient.deceased, Observation |

The registry's diagnosis date and last-update date are always carried. Where the registry has not yet abstracted a case, a criterion that depends on it reports `potential:data_gap` with the expected availability (§6.5), not `fail`.

Other drops use the same contract: the consent and opt-out registry (§7.13), CTMS enrolment exports (for M6 and the known-positive line of the recall certificate), catastrophic-illness lists and departmental registries (dialysis, stroke, transplant).

#### 5.6.7 Cohort and alliance aggregates

v1 signed COHORT tables continue (FR-M11-1, §10.11). Inbound aggregates are verified (Ed25519 signature, schema, suppression flags) and land in Z-REL as D1. Outbound answers leave only through the privacy accountant: controlled rounding, small-cell rules with complementary suppression, and, for machine and federated answers, DP noise with ε accounted (§7.9). OHDSI network-study packages (ATLAS cohort JSON, Strategus) run against the local OMOP schema, and only their aggregate results leave, after G2. Five Safes is applied at the alliance root (§7.12).

#### 5.6.8 NHI MediCloud (gated)

NHI MediCloud (健保醫療資訊雲端查詢系統) is a point-of-care query service, not a research source. It stays disabled by default (FR-M0-12, §10.0). It may be enabled only with written NHIA permission and an IRB-approved purpose on file. When enabled, it is queried per patient, on care events only, never for population scans. Results land with `provenance.source = nhi_cloud`, data class D4 at L0, and their retention is bound to the approved purpose. The legal basis for any TrialBox use is *(uncertain)* and is an open decision (§21).

#### 5.6.9 NHIRD and HWDC (aggregate priors only)

The Health and Welfare Data Science Center (HWDC) allows analysis on site only; individual-level data may not leave; outputs are reviewed by custodians; and data lag about two years (Hsieh et al. 2019). TrialBox therefore has **no row-level NHIRD connector**. It imports **aggregate prior tables**:

`prior_incidence(concept_set_ref, code_system_edition, age_band, sex, year, region, n_or_rate, denominator, suppression, source_kind: publication | hwdc_output, source_ref: DOI | HWDC project id, imported_by, imported_at)`

Publication-derived tables are D0. HWDC outputs from an academic collaborator are D1. Feasibility (§10.3) uses them as priors and representativeness denominators. Their ICD-10-CM codes after 2016 had "not been validated yet" when the cited review was written, so every use carries that caveat in the pack.

### 5.7 Sequences

#### 5.7.1 Nightly run (default windows, Asia/Taipei; normative windows in §13)

```
 time   actor                    action                                                             lineage / record
 ─────  ───────────────────────  ─────────────────────────────────────────────────────────────────  ─────────────────────────────
 19:00  scheduler (tb-orch)      open publish cycle C; data cut = 19:00 local (stored as UTC)        cycle C START
 19:00  connectors (per source)  plan(); control_totals() and extract() in one RO transaction;       tb.l0.land.<src> START
                                 file_drop: wait for manifest; fhir_bulk: kick-off $export _since
 19:40  L0                       write-once objects + l0_batch_manifest (sha256, fingerprint,        tb.l0.land.<src> COMPLETE
                                 control totals, watermark range)
 19:45  L1                       contract checks; reconcile source totals vs landed (exact);         tb.l1.validate.<src>.<tbl>
                                 volume band vs trailing same-weekday median; drift; GX suites;
                                 quarantine; Kahn-labelled report
        ├─ block  ─────────────▶ source held; steward email (diff, top reasons, sample keys);        FAIL event; cycle continues for
        │                        downstream uses previous batch of this source, marked stale          other sources (contract decides
        │                                                                                              whether stale is allowed)
 20:00  L2                       SI mapping (spec hash); dates, units, canonical text;               tb.l2.standardise.<src>
                                 tb-terminology $validate-code/$translate (bulk); FHIR NDJSON;
                                 OMOP staging; coverage + unit reports
 20:20  L3                       MPI resolve (MRN → mpi_id, merge table), pid = HMAC(K_pid, mpi_id); tb.l3.pseudonymise
                                 identifiers → tb-vault; tombstone blocklist; consent scopes
 20:30  L4                       Iceberg commits (not yet referenced); OMOP load to staging schema;   tb.l4.publish START
                                 DQD (pinned) on OMOP staging; reconciliation L3→L4 and snapshot
                                 balance (prev + inserts − deletes = new, per table)
 20:50  PUBLISH GATE             all blocking checks pass? ─ yes ─▶ sign snapshot manifest; swap      gate record (§6.14);
                                 CURRENT; OMOP staging → tb_omop (schema swap)                         tb.l4.publish COMPLETE
                                                      └─ no ──▶ rollback commits; CURRENT unchanged;  tb.l4.publish FAIL
                                                                steward + research office email
 21:00  L5                       FTS + embedding increments; dirty set (CAS-6) from changed pids ×   tb.l5.serve.*
                                 dependent domains; Data Atlas coverage/freshness/DQ scorecard
 21:00  cascade passes (§4)      screening and feasibility runs pin snapshot T in their manifests     run manifest lineage_id
```

Timings are illustrative for a 3M-patient site on profile P-GB10 *(est.)*. The full rebuild (all tables from L0 or a fresh full extract) runs at the weekend and is not bound to the 19:00–21:00 window; this resolves the v3 conflict between NFR-5 and the ingest window noted in the round-3 review.

#### 5.7.2 Same-day HL7 v2 appointment event (SIU^S12)

```
 engine (OIE / hospital)     tb-hl7 listener            L0 / L1 / L2 / L3 (stream path)          L5 + workflows
 ───────────────────────     ───────────────            ───────────────────────────────          ─────────────────────────────
 SIU^S12 (new appt, PID-3 ─▶ TLS session; MLLP frame;
  = MRN, SCH-11 start,       parse MSH; dedupe (MSH-4,
  AIP = practitioner,        MSH-10); write raw bytes
  AIL = clinic)              to L0 segment; fsync;
                             index row in Postgres
                ◀─ ACK AA ── (≤ 1 s p99)
                                                        L1: message contract (required
                                                        segments, SCH-11 timestamp, PID-3
                                                        authority); decode MSH-18 charset
                                                        L2: map → SI appointment row
                                                        (status booked, dept, practitioner,
                                                        start; source_recorded_at = MSH-7)
                                                        L3: PID-3 → MPI → pid; consent scope
                                                        `contact` checked; opted-out → dropped
                                                        with count
                                                        L4 stream table psn.appointment_intraday
                                                        (append-only; keyed by appt id + version)
                                                                                                  overlay view = snapshot T
                                                                                                  (clinical domains) ∪ intraday
                                                                                                  appointments ≤ event time
                                                                                                  rule: pid on any study's
                                                                                                  candidate or watchlist with
                                                                                                  status ≠ excluded and the appt
                                                                                                  in the next 14 days?
                                                                                                    ├─ yes → clinic-day list
                                                                                                    │  delta to the delegated CRC
                                                                                                    │  (§10.4): email with list;
                                                                                                    │  Teams/LINE nudge carries
                                                                                                    │  no PHI (§3)
                                                                                                    └─ no  → pid queued for the
                                                                                                       next night's dirty set
                                                                                                  manifest: overlay = {appointment:
                                                                                                  "hl7v2 ≤ <UTC ts>"}
```

Clinical facts in the overlay are those of snapshot T, never the intraday feed. Only the appointment, encounter (ADT) and result-status domains have intraday overlays, and every output that uses one records it in its manifest (`overlay`). The nightly snapshot T+1 supersedes the intraday table, and the intraday rows are reconciled against the nightly view extract: each intraday appointment must appear in the view or in a cancellation event, otherwise a reconciliation warning is raised.

### 5.8 Data contracts and schema drift

#### 5.8.1 Contract content

One contract per (source, table or message type). Contracts are YAML files in `site/contracts/<source>/<table>.yaml`, validated against `schemas/v4/data_contract.schema.json` (§6.14). They follow the structure of the Open Data Contract Standard (Bitol) *(version to pin at MS0; uncertain)*.

| Block | Content |
| --- | --- |
| Identity | `contract_id`, `version` (semver), source, kind, owner (controller), steward, change channel (email of the source DBA or engine team) |
| Schema | Per column: name, physical type, logical type, nullable, unique, primary key, enumeration or code system and edition, regex pattern, unit or unit column, **privacy class** (`direct_identifier | quasi_identifier | sensitive | free_text | none`), data class |
| Keys | Primary key, patient key, foreign keys (for referential integrity), watermark column, version column |
| Volume | Expected rows per batch (band, by weekday), growth rate, maximum quarantine share |
| Freshness | Latency class, maximum age of the newest record at cut, data-cut semantics |
| Control totals | The SQL or rule for each total (§5.9.1) |
| Quality | References to GX expectation suites and DQ rule ids with severity (blocking, warning) |
| Change policy | Additive changes auto-accept; breaking changes need a new major version and G0 |

#### 5.8.2 Schema fingerprint

`schema_fingerprint = sha256(JCS([[name, physical_type, nullable] for each column sorted by name]))`, using the JSON Canonicalization Scheme (RFC 8785). It is computed at L0 from the batch itself (database metadata, CSV header plus type inference, FHIR resource types plus the profiles claimed, HL7 v2 segment and field presence). It is compared with the contract's expected fingerprint.

#### 5.8.3 Drift detection

| Drift | Detection | Default action *(thresholds are site parameters; defaults est.)* |
| --- | --- | --- |
| Schema, additive (new nullable column, new enumeration value in a non-critical column) | Fingerprint diff | Accept; steward notified; Data Atlas updated |
| Schema, breaking (dropped or renamed column, type narrowing, key change, nullability tightened, new value in a critical enumeration) | Fingerprint diff | **Block** the source until a new contract major version is approved at G0 |
| Volume | Rows per table per day vs the trailing median of the same weekday over 8 weeks | Warn outside ±25 %; block outside ±40 % or on zero rows for a table expected to be non-empty |
| Distribution | Population stability index per contract-flagged column (categorical, or numeric in deciles) vs the trailing 8 batches | Warn at PSI > 0.25; block at PSI > 0.5 for columns flagged `critical` |
| Null rate | Absolute change > 5 percentage points vs trailing 8 batches | Warn; block for required columns |
| Code-system mix | Share per code-system edition (for example ICD-10-CM-TW 2014 vs 2023) and share of unmapped local codes | Warn on a jump > 10 points; expected at edition switch dates |
| Unit mix | Share of each unit per lab code | Warn on any new unit; block when the new unit is not UCUM-convertible to the contract unit |
| Text | Mean note length, language-tag mix, abbreviation density per note type (ML-11 monitor, §10) | Warn; feeds recalibration |

### 5.9 Reconciliation and the publish gate

ICH E6(R3) §4.2.5 requires that transferred data "retains its integrity" and that "data reconciliation" is performed "to avoid data loss and unintended modifications". The reconciliation below is the documented control for every EHR → TrialBox transfer (§15). The v3 gap it closes is R3-10: a silent 30 % drop in a lab view must not become a published snapshot.

#### 5.9.1 Control totals

| Level | Equation | Tolerance |
| --- | --- | --- |
| Source → L0 | Source totals (same transaction) = landed totals: `count`, `count distinct patient_key`, `min/max watermark`, `Σ keyhash mod 2^31`, per-day counts | Exact. Any difference is blocking. The 0.5 % tolerance of the round-3 design is kept only as a site-configurable ceiling for sources whose totals cannot be taken in the same transaction (documented per contract). |
| L0 → L1 | landed = accepted + quarantined | Exact (internal invariant) |
| L1 → L2 | accepted = mapped (+ explicit drops with reason, for example undated medication orders, as in v1) | Exact |
| L2 → L3 | mapped = pseudonymised + opted-out + identity-quarantined | Exact |
| L3 → L4 | Per table: `rows(T−1) + inserts − deletes − tombstones = rows(T)`; per-pid counts for changed pids | Exact |
| Cross-source | HL7 v2 ORU result count vs `db_view` lab count for the same day; SIU appointments vs view appointments | Warn above 2 % *(est.)* |
| Source volume | Volume band (§5.8.3) | As configured |
| Key completeness (weekly) | Full-key reconciliation: source key set = L4 key set | Every difference explained (tombstone or re-extract) |

#### 5.9.2 Reconciliation record

Each batch and each publish cycle writes a `reconciliation_record` (§6.14) with every equation, its two sides, the difference and the verdict. It is part of the snapshot manifest and the monthly QA pack.

#### 5.9.3 Publish gate

The **publish gate (PG)** is one decision per publish cycle, recorded as a gate record at L4. It is the conjunction of:

1. no blocking L1 finding for any source the contract marks `required_for_publish`;
2. all reconciliation equations of §5.9.1 hold;
3. terminology coverage per domain ≥ the contract floor (§5.11.4);
4. profile-validation error rate ≤ 0.5 % on the L2 sample;
5. no identity-quarantine share above 0.1 % *(est.)*;
6. DQD on the OMOP staging schema shows no failed check that the scorecard marks blocking (§5.10);
7. snapshot balance (L3 → L4) exact.

| Outcome | Effect |
| --- | --- |
| `PUBLISH` | Snapshot manifest signed; `CURRENT` pointer swapped atomically; downstream runs pin it |
| `PUBLISH_WITH_WARNINGS` | As above; warnings listed in the manifest and the Data Atlas |
| `HOLD` | Nothing published; previous snapshot stays `CURRENT`; the steward and the research office receive the diff, the failed rules and up to 20 example keys (pseudonymised); the run manifests of the next passes record `snapshot_age_days` |
| `OVERRIDE` | A held cycle may be published only through G0 with assurance A2: the data steward plus a second approver from the research office or QA. The override text and the failing rules are written into the manifest and every pack built on it. Overrides are counted in the QA pack. |

Rolling back a published snapshot (`lake pin T-1`) is an operations procedure in §18.

### 5.10 Data-quality framework and scorecard

**Framework.** Every rule is labelled with a category from the harmonised framework of Kahn et al. (*eGEMs* 2016): **conformance** (value, relational, computational), **completeness**, **plausibility** (atemporal, temporal, uniqueness). Each rule is also labelled with a context: **verification** (against internal expectations and the contract) or **validation** (against external truth, for example registry vs EHR stage, CTMS vs EHR enrolment). Timeliness (freshness and lateness) is reported as an operational dimension next to the Kahn categories.

**Engines.**

| Layer | Engine | Licence | Notes |
| --- | --- | --- | --- |
| L1 (source batches) | **Great Expectations** expectation suites, one per contract, versioned with the contract | Apache-2.0 | Results stored as JSON with the validation report |
| L2/L3 (SI) | TrialBox rules in SQL (DuckDB) from `services/dataplat/dq/rules/*.yaml` | in-house | Carries the v3 FR-M0-7 checks: unit consistency per lab code, impossible values, future dates, duplicate encounters, orphan records, code validity per ICD edition, ROC date parse failures |
| L4 (OMOP) | **OHDSI Data Quality Dashboard** (pinned version; DQD is tested against CDM 5.3 and 5.4; about 4,000 checks from 24 check types) and **Achilles** for characterisation | Apache-2.0 *(uncertain; verify at MS0)* | Run in the `tb-omop` container (R runtime) against the Postgres OMOP staging schema |
| Not bundled | Soda Core v4 | **Elastic License 2.0** (not OSI-approved) | Must not be bundled into the redistributed appliance |

**Scorecard.** Each snapshot gets a `dq_report` (§6.14) and a scorecard in the Data Atlas and the monthly QA pack:

- rows: domain (person, visit, condition, drug, measurement, procedure, note, registry, appointment);
- columns: Kahn category × context, plus timeliness;
- cells: checks run, failed, pass rate, and the trend over the last 12 snapshots;
- a terminology-coverage row and a unit-normalisation row per domain;
- the list of blocking rules and their status.

Thresholds are per check and per site, with the DQD defaults as a starting point. Changing a threshold is a G0 change with ALCOA++ history: who, when, why and the previous value.

**Planted-defect suite.** The `pipeline_dq` test suite (§16) plants defects in Synthea and MIMIC-IV demo data. Each defect must be detected, by the rule named in the test: a 30 % row drop in one view, a truncated CSV, an unquoted delimiter, a unit switch (mg/dL → µmol/L) on creatinine, ROC dates shifted by one year, duplicated encounters, an MRN merge, a deleted patient and a late-arriving lab. The detection rate must be 100 %.

### 5.11 Terminology service

#### 5.11.1 Service

`tb-terminology` is a thin facade (`services/terminology/`) in front of a self-hosted FHIR terminology server:

- **HAPI FHIR JPA server** (Apache-2.0) by default;
- **Snowstorm** (Apache-2.0) only at sites with a SNOMED CT licence that need ECL. Its Elasticsearch dependency has its own licence terms, which must be checked against the site licence policy *(uncertain)*.

It exposes the FHIR operations `$validate-code`, `$lookup`, `$translate`, `$expand` and `$subsumes`, plus a bulk API `POST /map-column` used by L2. The bulk API takes `{system, edition, codes[], target}` and returns per-code targets with the ConceptMap equivalence. Every terminology release is pinned per snapshot (`terminology_version` in the manifest). The HL7 validator used at L2 runs with this server, so bindings are resolved; this closes v1 defects D-26 and D-64.

#### 5.11.2 Content

| Domain | Source code systems | Target | Rules |
| --- | --- | --- | --- |
| Diagnosis | NHI Chinese-edition **ICD-10-CM 2014, 2021 and 2023** (TW Core CodeSystems); ICD-9-CM 2001 before 2016 | OMOP `ICD10CM` / `ICD9CM` source concepts → SNOMED standard concepts | The edition is stored **per record**, chosen by visit date from a site table of NHIA switch-over dates (v3 recorded the 2014 → 2023 switch on 2025-01-01). Official NHIA edition mappings are loaded as ConceptMaps. TW-only codes absent from the US release get local concepts *(extent uncertain)*. |
| Procedure | NHI ICD-10-PCS 2014/2021/2023; NHI medical-service payment codes | `ICD10PCS`; local vocabulary for NHI service codes | NHI payment codes mix procedure and billing meaning; they are mapped only where the terminology steward approves. |
| Drug | NHI drug codes (not hierarchical); TFDA licence codes; **TFDA ATC** CodeSystem | ATC → RxNorm / RxNorm Extension | NHI → ATC is many-to-one. Ingredient and strength come from TFDA licence data where available *(open-data availability uncertain)*. |
| Laboratory | Hospital local codes; NHI lab payment codes; **LOINC** with the MOHW Taiwan LOINC mapping (LOINC-TW) | LOINC | The TWPAS ConceptMap from NHI lab payment codes to LOINC uses R4 `equivalence = relatedto`, **not** `equivalent`. It is a candidate generator, never an equality (§5.11.3). |
| Units | Source unit strings | **UCUM** | Conversion table per LOINC code; unconvertible → quarantine at L1 if the contract makes the unit required. |
| Clinical findings | Free text; local problem lists | **SNOMED CT where licensed** | MOHW promoted SNOMED CT in 2025 under the Next-Generation Digital Health Platform programme. Taiwan's national licence terms are *(uncertain)*. Without a licence, findings stay as text and local codes. |
| Oncology | ICD-O-3 topography and morphology; AJCC TNM | OMOP ICDO3 and Cancer Modifier concepts | Edition of AJCC recorded per case |
| Japan profile | MEDIS standard disease names (標準病名マスター), ICD-10 (JP), YJ and HOT drug codes, JLAC10/JLAC11 lab codes | As above | Loaded where licensed (ML-10, §10). JP Core bindings resolved by the same service. |
| OMOP vocabularies | ATHENA download | — | `vocabulary_version` = ATHENA release id, recorded in `CDM_SOURCE` and every manifest |

Local code systems (NHI drug, NHI service, hospital lab) are loaded as **local OMOP vocabularies** with `concept_id ≥ 2,000,000,000` and `Maps to` relationships, each with `valid_start_date`, reviewer and confidence.

#### 5.11.3 Mapping quality rule

A ConceptMap relationship weaker than `equivalent` or `equal` (R4 `relatedto`, `wider`, `narrower`, `inexact`) MUST NOT be used as an equality in eligibility logic. Such a mapping sets `map_quality = inexact` on the SI row. The compiler (§10.1) then:

- requires an explicit specimen and unit check in the generated SQL and CQL;
- sets the affected atom's `filter_class` to `soft` (SAFE-1, §10);
- and reports the share of inexactly mapped rows in the criterion's computability.

#### 5.11.4 Coverage

Per snapshot and domain, the coverage report gives the share of source codes resolved to a standard concept, weighted by record count, and the top 50 unmapped codes by volume (values seen in fewer than 5 patients are shown as `<5`). Each contract sets a floor (defaults: diagnosis 0.98, drug 0.95, laboratory 0.90, procedure 0.85 *(est.)*). Coverage below the floor is blocking.

### 5.12 Canonical models

#### 5.12.1 Two canonical models, one per job

| Layer | Model | Role |
| --- | --- | --- |
| Exchange and evidence | **FHIR R4 4.0.1** with **TW Core IG 1.0.0** (Taiwan) and **JP Core** (Japan, version pinned at MS6) | Evidence references, chart review, CDS Hooks cards, eSource packets, exchange with hospital systems, the per-patient read API |
| Analytics core | **OMOP CDM 5.4** with OHDSI standardised vocabularies | Feasibility characterisation, representativeness, DQD and Achilles, ATLAS cohort JSON import and export, OHDSI network studies, federation, public benchmarks on OMOP |
| Sponsor boundary | CDISC ODM v2.0, Dataset-JSON, CDASH, SDTM TI, USDM 4.x | Export and import only, never storage (§12) |

Both FHIR and OMOP are written at L2 from the same SI rows. Neither is derived from the other's output, because each loses information the other keeps. The cascade's IR → SQL templates (§10.1) target the SI lake tables, as in v1, so the CQL ≡ SQL equivalence gate stays unchanged. OMOP is the analytics core beside it. A nightly `si_omop_balance` check confirms that per-domain × year counts agree between SI and OMOP within the mapped coverage. ATLAS cohort definitions can be imported, and each imported cohort is compiled to IR v3 where expressible, or run natively on OMOP and labelled as such.

#### 5.12.2 FHIR → OMOP transform

The HL7 **Vulcan FHIR-to-OMOP IG 1.0.0** is **Informative** (2026-04-30) and is built on FHIR R5; its 2.0.0 ballot (2026-08-07) is the first STU ballot. TrialBox cites it as a reference for field semantics only. It maintains its own **TW Core R4 → SI → OMOP 5.4** mapping (`services/omop/transform/`), validated by its own suite:

- round-trip counts per domain;
- 50 golden patients with hand-checked OMOP rows *(est. count)*;
- agreement with the PhysioNet MIMIC-IV demo OMOP release on agreed counts per domain (§16).

#### 5.12.3 Standardised intermediate (SI) tables

The SI extends the v1 lake tables (v1 SPEC §3.2). Every SI table carries these common columns:

| Column | Meaning |
| --- | --- |
| `pid` | Pseudonym (after L3) |
| `src_system`, `src_record_key`, `src_version` | Source identity of the row (key hashed where it embeds an identifier) |
| `effective_start`, `effective_end` | Clinical (valid) time |
| `source_recorded_at` | When the source made the fact available (report verified, note signed, order entered); `null` when unknown |
| `known_at_imputed` | `true` when `source_recorded_at` was imputed from effective time plus the domain's lag distribution |
| `tb_ingested_at` | First L0 arrival (UTC) |
| `l0_batch_id`, `lineage_run_id` | Lineage keys |
| `map_quality` | `exact | inexact | unmapped` |
| `deleted_at`, `delete_reason` | Tombstone (source delete, erasure, merge) |

Tables: `patient`, `encounter`, `appointment` (+ `appointment_intraday`), `condition`, `condition_attribute`, `observation`, `medication_order`, `medication_admin`, `procedure`, `report`, `document`, `document_chunk`, `claim`, `registry_case`, `treatment_course`, `episode_lot` (§6.2.2), `consent`, `death`. The bitemporal columns make two kinds of as-of possible (§5.13.3).

### 5.13 Storage formats and engines

#### 5.13.1 Formats

| Store | Technology | Licence | Use |
| --- | --- | --- | --- |
| Curated lake (L4) | **Apache Parquet** files in **Apache Iceberg** tables (format v2; v3 features such as deletion vectors and row lineage only once the writer and DuckDB both support them) | Apache-2.0 | SI tables, OMOP staging, intraday tables |
| Writer and catalog | **PyIceberg** with its SQL catalog in PostgreSQL *(version and SQL-catalog maturity to verify at MS0)* | Apache-2.0 | All L4 commits |
| Read engine | **DuckDB** with the `iceberg` extension | MIT | Cascade SQL, Atlas, feasibility; reads a pinned snapshot by id (`snapshot_from_id`) |
| FHIR store | **HAPI FHIR** JPA server (`tb-fhir`) | Apache-2.0 | Pseudonymised FHIR resources for evidence, CDS and chart review |
| OMOP serving | PostgreSQL schema `tb_omop` loaded from L4 | PostgreSQL licence | OHDSI tools (DQD, Achilles, ATLAS/WebAPI) |
| Fallback | Immutable per-snapshot Parquet directories plus a Postgres manifest table (the v1 layout) | — | Used if the Iceberg writer fails qualification at MS0; keeps as-of semantics without a catalog |

Iceberg selects columns by field id, so renames are safe, and partitions can evolve without rewrites. Tables are partitioned by domain-appropriate time (`effective_start` month) and bucketed by `pid`.

#### 5.13.2 Write-audit-publish

Readers never see an Iceberg table's "latest" state. They see only the per-table snapshot ids listed in a signed **snapshot manifest** (§6.14). The publish cycle commits new Iceberg snapshots, audits them (§5.9.3) and then publishes by inserting the manifest and moving `CURRENT`. A held cycle's commits are rolled back with Iceberg's rollback-to-snapshot and later expired. This gives atomic multi-table publication without a catalog-level transaction.

#### 5.13.3 As-of queries and replay

| Mode | Question answered | Mechanism | Used by |
| --- | --- | --- | --- |
| `system_asof(snapshot_id)` | "What did TrialBox know at publish T?" | Per-table Iceberg snapshot ids from the manifest; DuckDB `iceberg_scan(…, snapshot_from_id => …)` | Byte-identical re-runs; audit replays; rollback |
| `business_asof(date D)` | "What would the hospital have known on date D?" | Latest snapshot, filtered to `source_recorded_at ≤ D` (or imputed `known_at ≤ D`, flagged) | Validation replay of closed studies (§16); recruitability back-testing |

A business-time replay that depends on imputed availability reports the share of imputed rows. Its results are labelled `business_asof (imputed availability x %)`.

### 5.14 Identity lifecycle

#### 5.14.1 Master patient index

The MPI lives in `tb-vault` (Z-IDN) and follows IHE PIX/PDQ semantics without necessarily implementing those actors.

| Table | Columns | Notes |
| --- | --- | --- |
| `mpi_person` | `mpi_id` (random 128-bit), `status (active | merged | erased)`, `created_at` | `mpi_id` is random. It is never derived from the MRN or any attribute of the person. |
| `mpi_identifier` | `mpi_id`, `system` (assigning authority), `value_enc` (AES-256-GCM), `value_hmac` (lookup), `valid_from`, `valid_to` | MRN, national ID, ARC, research ID (Z-TRE only, held by the broker) |
| `mpi_merge` | `from_mpi_id`, `to_mpi_id`, `source_event` (A40 MSH-10 or steward ticket), `effective_utc`, `undone_utc` | Append-only |
| `pid_alias` | `old_pid`, `new_pid`, `reason (merge | key_rotation | v1_migration)`, `effective_utc` | Lets old artefacts resolve |
| `tombstone` | `pid`, `reason (erasure | opt_out_all | deceased_purge)`, `ticket`, `effective_utc` | Blocklist applied at L3 |

`pid = hex(HMAC-SHA-256(K_pid, mpi_id))[:32]`. Because `mpi_id` is random, the pid is not derived from information about the person, and an MRN change does not change the pid. v1 installations migrate once: each v1 pid (`HMAC(site_key, MRN)`) gets a `pid_alias` row to its v4 pid, and v1 artefacts resolve through it.

#### 5.14.2 Merges (ADT A40) and unmerges

1. A40 (or a steward ticket) arrives. `mpi_merge(from → to)` is written, and `from` gets `status = merged`.
2. The next publish cycle re-keys every L4 row of `pid(from)` to `pid(to)` (Iceberg row-level update), and writes `pid_alias`.
3. Candidates, evidence and judgement-cache entries of both pids join the dirty set. Cache entries are re-keyed, not reused blindly: the sentence-set key (§10.4) is recomputed for the merged record.
4. Any open candidate in either pid is re-evaluated. If a packet was already sent, the next packet marks the row `merged` with the surviving list position.
5. An erroneous merge (A37 unlink, or a steward ticket) is undone by `undone_utc`. Rows are split back by `src_record_key` ownership recorded at L0, and both pids are re-evaluated.

#### 5.14.3 Corrections and late-arriving data

| Event | Detection | Effect |
| --- | --- | --- |
| Source correction (ORU result status C, ADT A08, MDM T08, changed `db_view` row) | New `src_version` for an existing `src_record_key` | L4 MERGE; the old version stays in history; the pid enters the dirty set (CAS-6) for the dependent domains |
| Evidence on a corrected record | Evidence `source.ref` + `src_version` no longer current | The quote is re-verified on the new canonical text. If it fails, the evidence is invalidated and the pair is re-judged. A sent packet is followed by a `regenerated` notice. |
| Late arrival | `tb_ingested_at − effective_start` exceeds the domain's lateness threshold (default: labs 3 days, notes 7 days, registry 180 days *(est.)*) | Row flagged `late`; window evaluations that include its effective time are re-opened for the affected pid × criteria; lateness distribution reported in the DQ scorecard (timeliness) |
| Cancellation (A11, A13, S15, S17, T11) | Event type | Tombstone with reason `source_cancel` |

#### 5.14.4 Erasure and the replay-break policy

A data subject may ask for erasure or may object to research use (PDPA rights; §7.3). The hospital's medical record retention duties are unaffected. Erasure applies to **TrialBox's copies** only.

1. The DPO opens an erasure ticket. `tb-vault` resolves the person to `mpi_id` and pid(s), including aliases.
2. A `tombstone` row is written. From then on, L3 drops every incoming row of that person. The tombstone holds only the pid and the ticket, and is kept as the minimum needed to honour the request.
3. Within the policy SLA (default 30 days), a purge job removes the person's rows from **all retained** Iceberg snapshots (rewrite of the affected data files, then expiry of every snapshot that still references the old files), the FHIR store, OMOP, indexes, the judgement cache, evaluation sets and L0 objects. Identity-vault rows are deleted, except the tombstone.
4. Run manifests whose snapshots were rewritten are marked `replay_degraded: {reason: "erasure", ticket, rows_removed_per_table}`. Aggregates already released stay as released: they passed the accountant and are non-personal. Lists already delivered to PIs cannot be recalled; the ticket records which deliveries contained the person.
5. A replay of a degraded run does not fail silently. It runs and reports the delta in every count against the original manifest.
6. **Byte-identical re-runs (§4, §16) are guaranteed for runs not marked `replay_degraded`.** This exception is documented in the validation plan.
7. A purge certificate (§6.14) is signed and retained for at least 5 years (EMR regulation and MOHW destruction-record practice).

Opt-outs that do not demand erasure (for example `contact` only) do not purge. They are applied as consent scopes (§7.13).

### 5.15 Lineage and provenance

**OpenLineage.** Every stage run emits OpenLineage run events (`START`, `COMPLETE`, `FAIL`, `ABORT`) with job, run, input and output datasets and facets. Spec version is pinned at MS0 *(OpenLineage 2.x; exact schema URL to confirm)*.

| Element | Convention |
| --- | --- |
| Job namespace | `trialbox://<site_id>` |
| Job names | `tb.l0.land.<source>`, `tb.l1.validate.<source>.<table>`, `tb.l2.standardise.<source>`, `tb.l3.pseudonymise`, `tb.l4.publish`, `tb.l5.serve.<path>`, `tb.cascade.<workflow>`, `tb.render.<artefact>` |
| Dataset namespaces | `his-db://<host>/<db>`, `hl7v2://<listener>`, `fhir://<base>`, `file://<drop>`, `iceberg://tb/<zone>`, `postgres://tb_omop`, `outbox://` |
| Standard facets | `schema`, `dataSource`, `columnLineage` (L2 mappings), `dataQualityMetrics`, `dataQualityAssertions` |
| TrialBox facets (each with `_producer` and `_schemaURL`) | `tb_controlTotals`, `tb_dataClass`, `tb_snapshot` (manifest id, Iceberg snapshot ids), `tb_contract` (contract id and version), `tb_mappingSpec` (hash), `tb_terminology` (release) |

Events are stored in PostgreSQL (`lineage.events`, append-only, JSONB). A Marquez-compatible export is optional. Lineage events carry no PHI: datasets are named by table, and patient-level references never appear.

**FHIR Provenance.**

- Source-mapped resources carry `meta.source = urn:tb:batch:<l0_batch_id>` and a `meta.tag` with the lineage run id, which avoids one Provenance resource per row.
- A **Provenance** resource is written for every derived resource (calculated scores, `episode_lot`, registry-derived attributes, note-extracted values) and every evidence item. It records `target`, `recorded`, `agent` (device = TrialBox component and version, plus the model alias and SHA for model-extracted values), `entity` (role `source`, the source resource references and versions), and `policy = urn:tb:lineage:<lineage_run_id>`.

**Lineage id on every deliverable.** Every pack, list, certificate, questionnaire answer and export carries `lineage_id = lin_<ULID>`. `trialbox lineage show <lineage_id>` resolves the full graph: source batches → L-stage runs → snapshot manifest → ruleset and library versions → model routes → run → rendered files. The graph is assembled from OpenLineage events and run manifests. It is included, without PHI, in the validation pack.

### 5.16 Catalog: the Data Atlas

The Data Atlas (M0, §10.0) becomes the catalog. To avoid confusion with OHDSI ATLAS, the spec always says "Data Atlas" for the TrialBox component. It holds, per source, table and column: the contract and its version history, owner and steward, privacy and data class, coverage per domain and scope (12, 24 and 60 months), freshness and data cut, terminology coverage, the DQ scorecard trend, drift alarms, and lineage links. It is shown in the admin control plane (C-5′) and the steward workbook. An optional export to DCAT or OpenMetadata JSON is available for a hospital catalog *(format choice uncertain)*.

### 5.17 Research-database onboarding job

`trialbox data onboard --source <id>` automates the OHDSI ETL method (design, code mapping, implementation, quality control) for a CGRD-type database or a new HIS feed.

| Step | Output | Model use |
| --- | --- | --- |
| 1. Profile | White-Rabbit-compatible scan report (DuckDB): types, null rates, distinct counts, ranges, k-suppressed top values (k ≥ 11), candidate keys. Free-text columns are profiled only by length and language mix. | None |
| 2. Dictionary alignment | Parsed data dictionary joined to the profile | None |
| 3. Semantic typing and mapping proposal | Rules detect ROC dates, NHI codes, ICD-9/10-CM editions, national-ID patterns (flagged as identifiers first). A model proposes table → SI domain and column → field mappings as a YAML **mapping spec** with confidence and reasons. | `propose_mapping` role through `tb-gateway` (§8), D1 inputs only: names, dictionary text, k-suppressed profiles |
| 4. Code mapping | Usagi-style candidates plus `tb-terminology` lookups → a `SOURCE_TO_CONCEPT_MAP` delta | Retrieval and reranking only; the model never invents codes |
| 5. Human approval | Steward and terminology steward approve at G0 (workbook round trip) | None |
| 6. Code generation | Deterministic SQL and transform config from the spec: the same spec gives byte-identical SQL | None |
| 7. Quality control | DQ scorecard, Achilles characterisation, source-vs-SI-vs-OMOP counts per domain × year | None |

Mapping specs and approved code maps are versioned artefacts with hashes. Every snapshot manifest references the mapping-spec hash it used.

### 5.18 Retention per zone

The stage table (§5.3) gives retention for L0–L5 working data. The remaining object classes are:

| Object | Default | Basis and override |
| --- | --- | --- |
| Z-TRE releases | Per research-database approval; deleted at its expiry | Approval record |
| Identity vault | While the patient relationship lasts; erasure on request; tombstones kept 5 years after erasure *(est.)* | PDPA |
| Snapshots pinned by signed outputs | Retention of the regulated record that pins them (PRIV-6) | Overrides the L4 rolling rule |
| Lineage events, gate records, snapshot manifests | As long as the longest run that references them | Audit trail (§14, §15) |
| Purge and destruction certificates | ≥ 5 years | EMR regulation and MOHW destruction-record practice |
| Intraday tables | Until reconciled by the next nightly snapshot, then 14 days | — |

### 5.19 Code locations

| Package (relative to `trialbox/`) | Content | Replaces / reuses |
| --- | --- | --- |
| `services/dataplat/connectors/{db_view,cdc,hl7v2,fhir_rest,fhir_bulk,file_drop}.py` | Connectors (§5.5) | v1 `services/adapter/sources/*` (identifier validation of `cgrd_sql` reused) |
| `services/dataplat/l0_landing/` | Landing sink, batch manifest, object lock | — |
| `services/dataplat/l1_validation/{contracts,reconcile,drift,gx}.py` | Contracts, reconciliation, drift, GX runner | v1 `adapter/validate/validator.py` (sampling) |
| `services/dataplat/l2_standardise/{si_mapper,dates,units,canon_text,fhir_writer,omop_writer}.py` | SI mapping and writers | v1 `adapter/mapping/engine.py`, `adapter/ndjson.py`, `load_fhir.py` |
| `services/dataplat/l3_pseudonymise/{mpi_client,pseudonym,consent}.py` | L3 | v1 `adapter/pidmap.py`, `pipeline.pseudonymise_bulk` |
| `services/dataplat/l4_curated/{iceberg_store,snapshot,publish_gate,purge}.py` | L4 | v1 `prune_snapshots` logic via `tb_common.retention` |
| `services/dataplat/l5_serving/{duck,overlay,accountant_api}.py` | L5 | v1 `services/lake` |
| `services/dataplat/dq/` | Rules YAML, scorecard builder | — |
| `services/dataplat/lineage/` | OpenLineage emitter and store, Provenance writer | — |
| `services/dataplat/onboard/` | §5.17 job | v1 `tools/mapping_check.py` |
| `services/hl7_listener/` | `tb-hl7` MLLP/TLS listener | — |
| `services/terminology/` | `tb-terminology` facade | v1 terminology loaders (FR-M0-8) |
| `services/vault/` | `tb-vault`: MPI, identity, tokenisation, erasure | v1 `pidmap.py` (AES-GCM scheme kept) |
| `services/omop/` | OMOP transform, loader, DQD/Achilles runner (`tb-omop`) | — |
| `site/contracts/`, `site/sources.yaml` | Site configuration | v1 `site/sources.yaml` |
| `schemas/v4/` | Contracts (§6) | `schemas/v2/` |

The v1 `services/adapter/` stays runnable for v1-compatibility tests until MS1 and is then retired.

### 5.20 Requirements

R refers to the milestones of §20: MS0 foundations, MS1 feasibility on de-identified data, MS2 silent pre-screening, MS3 first live wave, MS4 recruitment engine and start-up, MS5 conduct and data, MS6 second site and Japan profile.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| DP-01 | The platform MUST implement stages L0–L5 as in §5.3: owner role, input and output contracts, controls, failure handling and OpenLineage job name per stage. | T, I | MS0 |
| DP-02 | Storage MUST be split into the zones of §5.2, each with its own database role and key. A row MUST NOT move to a lower-class zone except through a §7.1 declassification transform that writes its certificate. | T | MS0 |
| DP-03 | All six connector kinds MUST implement the `Connector` interface (§5.5) and emit the same `l0_batch_manifest`. | T | MS0 (`db_view`, `file_drop`, `fhir_bulk`); MS2 (`hl7v2`, `cdc`) |
| DP-04 | L0 MUST be write-once per batch with sha256 per object and a schema fingerprint, MUST NOT transform data, and MUST crypto-shred raw objects after 90 days unless a legal hold applies. | T | MS0 |
| DP-05 | `db_view` connectors MUST use a read-only account on DBA-owned views, MUST NOT issue DDL, MUST take control totals in the extract's read-consistent transaction, MUST re-read a 1-hour overlap, and MUST run a full-key reconciliation at least weekly (tombstone absent keys, re-extract missing ones). | T | MS0; full-key MS1 |
| DP-06 | CDC MUST be optional per table and DBA-approved, with the per-engine prerequisites of §5.6.2 (including the IBM IIDR licence for Db2) stated in the site runbook. Consumers MUST be idempotent on (source, table, key, LSN/SCN) and detect LSN gaps. A Db2 site without IIDR MUST be fully supported by views plus HL7 v2. | T, I, D | MS2 |
| DP-07 | A CGRD-type research database MUST be ingested only into Z-TRE as D2, with IRB and access references and a data cut per domain. Feasibility outputs MUST print the oldest cut. The planner MUST refuse `SCREEN` or `MATCH` scopes that resolve to Z-TRE. | T | MS1 |
| DP-08 | `fhir_bulk` MUST implement Bulk Data Access 3.0.0 and accept 2.0.0 servers (§5.6.4): Group and Patient level, `_since` from the previous `transactionTime`, `deleted` processing, resumable downloads, per-file count checks. | T | MS0 |
| DP-09 | FHIR authentication MUST use SMART Backend Services 2.2.0: private_key_jwt (ES384 or RS384), contract-limited `system/<Type>.rs` scopes, assertion lifetime ≤ 5 min, no refresh tokens, re-authentication when the access token (≤ 300 s expected) expires. | T | MS0 |
| DP-10 | `fhir_rest` MUST serve per-patient retrieval only; the planner MUST refuse population queries on it. | T | MS0 |
| DP-11 | The HL7 v2 listener MUST meet §5.6.5: v2.3–v2.5.1, MLLP over TLS, the listed message types, MSH-18 character sets, raw persistence before ACK, deduplication on (MSH-4, MSH-10), and replay of any window from L0. | T | MS2 |
| DP-12 | TrialBox MUST NOT require the hospital to change its interface engine. A bundled engine MUST be OSI-licensed (Eclipse Open Integration Engine, MPL-2.0); Mirth Connect ≥ 4.6 MUST NOT be bundled. | I | MS2 |
| DP-13 | `file_drop` MUST require a manifest, a `.sha256` sidecar per file and a declared, detected encoding, and MUST quarantine whole files that fail the row-count, column-count or quote-balance contract. | T | MS0 |
| DP-14 | The cancer-registry long form MUST be a first-class source mapped as in §5.6.6, with diagnosis date, AJCC edition and registry last-update date. A criterion depending on a case not yet abstracted MUST yield `potential:data_gap`, not `fail`. | T | MS1 |
| DP-15 | NHIRD/HWDC MUST be supported only as imported aggregate prior tables with source kind, reference and year (§5.6.9); there MUST be no row-level NHIRD connector. | I | MS1 |
| DP-16 | NHI MediCloud MUST be disabled by default, enabled only with a recorded NHIA permission and IRB purpose, and never queried for population scans. | T, I | MS5 |
| DP-17 | Every source MUST declare a latency class. Every packet, candidate list and match answer MUST print each contributing source's data cut and any intraday overlay. | T | MS1 |
| DP-18 | Every (source, table or message type) MUST have a versioned data contract (§5.8.1); a batch without one MUST be blocked. Schema drift MUST be classified additive or breaking by fingerprint (§5.8.2), breaking drift blocking until a new major version passes G0. The monitors of §5.8.3 MUST run with contract-recorded thresholds. | T | MS0; monitors MS1 |
| DP-19 | Every equation of §5.9.1 MUST be evaluated per batch and cycle and stored as a `reconciliation_record`. Internal equations (L0 → L4) MUST hold exactly. | T | MS0 |
| DP-20 | The publish gate MUST be the conjunction of §5.9.3. On `HOLD` the previous snapshot MUST stay current and the steward and research office MUST receive the diff, failed rules and pseudonymised example keys. An override MUST pass G0 at A2 and be printed in the snapshot manifest and every pack built on it. | T | MS0; override MS1 |
| DP-21 | Reconciliation and the publish gate MUST be documented in the validation pack as the ICH E6(R3) §4.2.5 control for EHR → TrialBox transfers. | I | MS1 |
| DP-22 | Every DQ rule MUST carry a Kahn category with subtype and a context (verification or validation). L1 MUST run Great Expectations suites versioned with the contract. Pinned OHDSI DQD MUST run on the OMOP staging schema before every publish, its JSON stored with the snapshot. | T | MS1 |
| DP-23 | Bundled DQ and lineage components MUST be OSI-licensed; Elastic-licensed components (Soda Core v4) MUST NOT be bundled. | I | MS0 |
| DP-24 | Each snapshot MUST produce the DQ scorecard of §5.10 with a 12-snapshot trend. Threshold changes MUST pass G0 with who, when, why and the previous value. | T | MS1 |
| DP-25 | The `pipeline_dq` suite MUST detect 100 % of the planted defects of §5.10 on Synthea and the MIMIC-IV demo. | T | MS0 |
| DP-26 | `tb-terminology` MUST be self-hosted, pinned per snapshot, expose `$validate-code`, `$lookup`, `$translate`, `$expand`, `$subsumes` and bulk map-column, and back L2 profile validation. Coverage per domain (record-weighted) MUST be reported per snapshot; coverage below the contract floor MUST block publication. | T | MS0 |
| DP-27 | Every coded value MUST keep source value, source concept and code-system edition (for example `ICD-10-CM-TW-2023`), chosen per record from the site's switch-over table, with edition mappings applied as ConceptMaps. | T | MS0 |
| DP-28 | NHI drug, NHI service and hospital lab codes MUST be local OMOP vocabularies (concept_id ≥ 2,000,000,000) with `Maps to` relationships recording reviewer, confidence and validity dates. | T, I | MS1 |
| DP-29 | A mapping weaker than `equivalent`/`equal` (including NHI → LOINC `relatedto`) MUST set `map_quality = inexact` and MUST NOT compile as an equality without explicit specimen and unit checks. | T | MS1 |
| DP-30 | L2 MUST write FHIR R4 (TW Core 1.0.0; JP Core for Japan) and OMOP CDM 5.4 from the same SI rows. The TW Core R4 → OMOP transform MUST be TrialBox's own artefact, validated by round-trip counts, golden patients and the MIMIC-IV demo OMOP release; Vulcan is cited as informative. `CDM_SOURCE`/`METADATA` MUST record release date, ETL SHA, mapping-spec hash and ATHENA release. | T, I | MS1 |
| DP-31 | ATLAS cohort JSON MUST be importable and exportable; every exported count MUST carry the cohort-definition hash and snapshot id. | T | MS4 |
| DP-32 | Curated tables MUST be Parquet in Iceberg v2 committed by write-audit-publish (or the qualified fallback of §5.13.1). Readers MUST resolve tables only through a signed snapshot manifest. | T | MS0 |
| DP-33 | Every run MUST be replayable `system_asof` its manifest. Validation replay MUST use `business_asof` on `source_recorded_at` and report the share of imputed availability. | T | MS1 |
| DP-34 | SI tables MUST carry the common columns of §5.12.3. | T | MS0 |
| DP-35 | The MPI MUST assign a random `mpi_id` per person; `pid` MUST be `HMAC(K_pid, mpi_id)`; v1 pids MUST resolve through `pid_alias`. | T | MS0 |
| DP-36 | Merges and unmerges MUST follow §5.14.2: re-keying at the next publish, `pid_alias`, cache re-keying or invalidation, re-evaluation of open candidates, splitting by L0 record ownership on unmerge. | T | MS2 |
| DP-37 | Corrections and late arrivals MUST follow §5.14.3: new `src_version` with history, re-verification of affected quotes, re-judgement of failed pairs, a `regenerated` notice after a sent packet, per-domain lateness flags and re-opened windows, lateness in the scorecard. | T | MS2 |
| DP-38 | Erasure MUST follow §5.14.4: L3 tombstone, purge from all retained snapshots and derived stores within the SLA (default 30 days), `replay_degraded` manifests, delta-reporting replays, a signed purge certificate kept ≥ 5 years. | T | MS2 |
| DP-39 | Every stage run MUST emit OpenLineage events with the facets of §5.15, stored append-only without PHI. Every derived resource and evidence item MUST have a FHIR Provenance; every source-mapped resource MUST carry `meta.source`. | T | MS0; Provenance MS1 |
| DP-40 | Every deliverable MUST carry a `lineage_id` that `trialbox lineage show` resolves from source batches to rendered files. | T | MS1 |
| DP-41 | The Data Atlas MUST act as the catalog with the content of §5.16. | T, D | MS1 |
| DP-42 | `trialbox data onboard` MUST run the steps of §5.17 in order. Its model step MUST see only D1 metadata (k ≥ 11). The same spec MUST generate byte-identical code. | T, I | MS1 |
| DP-43 | Retention MUST follow §5.3 and §5.18 per object class, with legal hold; destruction certificates MUST be kept ≥ 5 years. | T, I | MS1 |
| DP-44 | Every TrialBox copy of EMR data MUST keep access, edit, view and copy logs meeting EMR regulation Art. 13 (who, when, what). | T, I | MS0 |
| DP-45 | The intraday overlay MUST follow §5.7.2: snapshot T for clinical domains, intraday feeds only for appointment, encounter and result-status domains, recorded in the manifest, reconciled against the next nightly extract. | T | MS2 |
| DP-46 | The publish cycle MUST fit the nightly window of §5.7.1 for daily deltas at the capacity targets of §13, with full rebuilds outside it. | T, A | MS1 |

## 6. Data model and contracts

The v3 conventions carry over:

- All contracts are JSON Schema 2020-12.
- `make contracts` compiles them into `libs/tb_contracts`, and `make contracts-check` fails CI on drift.
- Every persisted object carries `schema_version`.

v4 schemas live in `schemas/v4/` with `$id` `https://trialbox.local/schemas/v4/<name>.schema.json`. Hashes use SHA-256 over the RFC 8785 canonical JSON (JCS) of the object without its own hash field. Timestamps are UTC (`…Z`); a local offset is added only where a regulation requires it, as in signatures. Every object that reaches a person or a sponsor carries `data_class` (§7.1) and `lineage_id` (§5.15).

### 6.1 Schema inventory

| Schema | Purpose | Status vs v3 |
| --- | --- | --- |
| `criterion_ir` 3.0.0 | Criterion IR v3 | changed (§6.2) |
| `criterion_library_record` | Approved, reusable criterion | new (§6.3) |
| `calculator` | Derived-calculator definition and version | new (§6.2.3) |
| `lot_rules` | Line-of-therapy derivation rules | new (§6.2.2) |
| `canonical_text` 3.0 | Canonical note text with sentence hashes | changed (§6.4) |
| `evidence` 3.0, `candidate` 3.0 | Multi-span evidence; split `potential` | changed (§6.5) |
| `feasibility_estimate`, `recruitability_model`, `forecast_ledger_entry` | Feasibility data objects behind the packs of §12 | new / changed (§6.6) |
| `recall_certificate` 3.0, `recall_ledger_entry` | Anytime-valid certificate and its ledger | changed (§6.7) |
| `study` 4.0 | Study Card | changed (§6.8) |
| `run_manifest` 3.0 | Lineage, routes, classes, cascade | changed (§6.9) |
| `gate`, `approval`, `signature` | Unchanged from v3 §5.9 plus `data_class` and `lineage_id` | changed (§6.10) |
| `site_lexicon_entry` 3.0 | Lexicon row with recall link | changed (§6.11) |
| `privacy_ledger_entry` 2.0, `release_certificate`, `epsilon_budget` | Disclosure control records | changed / new (§6.12) |
| `model_build`, `model_card`, `routing_rule`, `eval_report`, `bench_report`, `bakeoff_record` | LLM platform records (§8) | new / changed (§6.13) |
| `data_contract`, `l0_batch_manifest`, `reconciliation_record`, `dq_report`, `snapshot_manifest`, `publish_gate_record`, `purge_certificate`, `lineage_event` | Data platform records (§5) | new (§6.14) |
| `consent` (FHIR profile `TBResearchConsent`) | Patient-level consent and opt-out scopes | new (§6.15) |
| `project` | Access project (purpose, IRB, classes, zones, expiry) | new (§7.12) |
| All other v3 schemas (`proposal`, `decision_sheet`, `answer_memory`, `outbox_message`, `atlas_report`, `site_profile`, `pipeline_event`, `calendar_item`, `audit_event` v2) | | carried over; moved to `schemas/v4/` unchanged except `data_class` where they hold patient data |

### 6.2 Criterion IR v3

IR 3.0.0 is a strict superset of IR 2.0.0 (v3 §5.2). Every IR 2 field and semantic rule is kept, except that the S2 zero-hit rule now routes to S2b (§4, §10.4). Rulesets below 3.0.0 run unchanged and are recompiled at their next G1, as v3 did for IR 1 → 2. Every construct compiles to CQL and SQL from templates and is covered by the equivalence gate with fixtures in `rulesets/ATOMS_V3/` (§10.1).

```jsonc
{
  "id": "LUNG7-INC-06", "ruleset": "LUNG7/v1.0.0", "ir_version": "3.0.0",
  "kind": "inclusion", "class": "mixed",               // structured | note | human | mixed
  "text": {"source": "Progressed on ≥ 1 prior platinum-based line for metastatic disease; EGFR/ALK wild type; ECOG 0–1; adequate organ function within 14 days before randomisation.",
           "lang": "en", "source_ref": "protocol v2.0 §5.1 item 6"},
  "library_ref": {"lib_id": "cl_01JB7…", "match": "variant", "diff": ["m1.params.alt_ast_max_uln 3.0 → 2.5"]},
  "logic": {"op": "and", "args": ["a1", "a2", "a3", "m1"]},
  "atoms": [
    {"id": "a1", "domain": "line_of_therapy",
     "lot": {"regimen_classes": [{"label": "platinum", "atc": ["L01XA"]}], "match": "any",
             "line_number": {"op": ">=", "num": 1}, "setting": "metastatic",
             "ended_by": ["progression"], "progression_sources": ["registry", "report_span", "note"],
             "rules": "lot_rules@tw-onc-1.0.0"},
     "window": {"from_days": -3650, "to_days": 0, "anchor": "index"}},
    {"id": "a2", "domain": "condition", "valueset": "vs_nsclc",
     "attribute": {"path": "biomarker:EGFR", "op": "in", "codes": ["negative", "wild_type"],
                   "source_priority": ["registry", "structured_pathology", "report_span", "note"],
                   "conflict": "highest_priority", "max_age_days": null}},
    {"id": "a3", "domain": "observation",
     "attribute": {"path": "ecog", "op": "<=", "num": 1,
                   "source_priority": ["structured_form", "note"], "max_age_days": 30},
     "window": {"from_days": -30, "to_days": 0, "anchor": "screening"}}
  ],
  "macros": [
    {"id": "m1", "macro": "organ_function@onc-std-1.0.0",
     "params": {"anc_min": 1.5, "plt_min": 100, "hgb_min": 9.0, "alt_ast_max_uln": 2.5,
                "alt_ast_max_uln_if": {"liver_mets": 5.0}, "tbil_max_uln": 1.5,
                "renal": {"calc": "egfr_ckd_epi_2021@1.0.0", "op": ">=", "num": 45}},
     "window": {"from_days": -14, "to_days": 0, "anchor": "randomization"},
     "expanded": ["m1.anc", "m1.plt", "m1.hgb", "m1.alt", "m1.ast", "m1.tbil", "m1.renal"]}
  ],
  "canonical_hash": "sha256:9c1e…", "filter_class": "soft",
  "depends_on": ["episode_lot", "condition_attribute", "observation", "note:pathology"],
  "flip_rule": null,
  "note_question": {"key": "nq_ecog_0_1", "en": "Is the patient's most recent ECOG performance status 0 or 1?",
                    "zh-TW": "病人最近一次的 ECOG 體能狀態是否為 0 或 1？", "ja": "直近の ECOG PS は 0 または 1 か？"},
  "lexicon_keys": [{"entry_id": "lx_0142", "surface": "ECOG"}, {"entry_id": "lx_0907", "surface": "體能狀態"}],
  "computability": {"score": 0.58, "basis": "ECOG structured in 31 % of active CHEST patients; notes in 92 %",
                    "inexact_map_share": 0.0},
  "human": null,
  "safety_critical": false, "index": false,
  "provenance": {"drafted_by": "library_match", "model_route": "extract_criteria@V-on-prem", "agreement": "library+gold"}
}
```

#### 6.2.1 Atom extensions

| Field | Values | Semantics |
| --- | --- | --- |
| `domain` | IR 2 domains plus `line_of_therapy`, `registry`, `specimen`, `genomic` | `genomic` atoms read `condition_attribute` rows with `biomarker:` paths (HGVS or local codes); no genomic file ingest in v4 |
| `attribute` on **any** domain | `path`, `op`, `codes`/`num`, `source_priority[]`, `conflict: highest_priority | most_recent | any_pass | all_pass`, `max_age_days` | Sources are tried in priority order. The first source with a value in the window decides under `highest_priority`. Every value read is logged as evidence with `resolved_from`. No value in any source → `unknown` (data gap). A lower-priority value that contradicts a higher one is reported as a conflict in the candidate. Source kinds: `registry`, `structured_pathology`, `structured_form`, `report_span` (structured extraction from reports, §10), `note` (S3 question). |
| `value.ref` | `{"kind": "uln | lln", "multiple": 2.5}` | Compared with the observation's own reference range (`Observation.referenceRange`, OBX-7). If it is absent, the versioned site default table is used. If neither exists → `unknown`. |
| `window.anchor` | `index | event | screening | randomization` | See §6.2.4 |
| `derived` | `{"calc": "<calc_id>@<semver>", "op", "num", "inputs_window_days"}` | Pinned calculator version (§6.2.3). Any missing input → `unknown`. Comparisons are unrounded (v1 D-17). |

#### 6.2.2 Line of therapy (regimen model)

`line_of_therapy` atoms evaluate against the SI table `episode_lot`, which L4 derives deterministically from medication orders and administrations, registry first-course treatment and procedures:

`episode_lot(pid, line_no, regimen_id, drug_classes[], drugs[], start, end, cycles, max_gap_days, setting: metastatic | adjuvant | neoadjuvant | maintenance | unknown, ended_by: progression | toxicity | completion | death | unknown, progression_date, progression_source, rules_version, evidence_ids[])`

The derivation rules are a versioned `lot_rules` artefact approved at G0 by the oncology and terminology stewards:

```yaml
id: lot_rules@tw-onc-1.0.0
regimen_window_days: 28        # drugs first given within this window form one regimen (est.)
new_line_gap_days: 90          # a gap longer than this starts a new line (est.)
new_line_on_added_class: true  # a new non-equivalent class after the regimen window starts a new line
maintenance_classes: [ {atc: ["L01XC07"], continues_line: true} ]   # illustrative: bevacizumab maintenance
switch_requires_progression: false
progression_sources: [registry, report_span, note]   # report_span = RECIST/radiology conclusion spans
setting_from: [registry_stage, metastasis_attribute, note]
```

Progression comes from the first available source in `progression_sources`. When a line's end cannot be attributed, `ended_by = unknown`. An atom that requires `ended_by: progression` then yields `unknown`, never `pass`. Every `episode_lot` row has a FHIR Provenance (§5.15) and maps to OMOP `EPISODE` and `EPISODE_EVENT`.

#### 6.2.3 Derived-calculator library

Calculators live in `libs/tb_common/calculators/` (one module per calculator plus `registry.py`). The v1 `libs/tb_common/derived.py` constants are re-exported unchanged. Each calculator has an id, a semantic version, inputs (LOINC or TrialBox score codes with UCUM units), a default input window, a formula reference, a constants hash and ≥ 20 published or hand-checked test vectors. CQL (`TB_Common`) and DuckDB SQL are rendered from the same constants. A new version never changes an old one; a ruleset pins `calc_id@version`.

| Calculator | Kind | Inputs | Default window | Notes |
| --- | --- | --- | --- | --- |
| `bmi@1.0.0` | formula | weight, height | 365 d | v1 |
| `bsa_mosteller@1.0.0` | formula | weight, height | 365 d | new |
| `egfr_ckd_epi_2021@1.0.0` | formula | creatinine, age, sex | 365 d | v1 (race-free) |
| `crcl_cockcroft_gault@1.0.0` | formula | creatinine, age, sex, weight | 90 d | new |
| `child_pugh@1.0.0` | score | bilirubin, albumin, INR (structured); ascites, encephalopathy (`attribute` with `source_priority: [structured_form, note]`) | 30 d | Returns score and class A/B/C. A missing note-derived component gives a score range; the comparison is decided only if the whole range is on one side, else `unknown`. |
| `das28_esr@1.0.0`, `das28_crp@1.0.0`, `basdai@1.0.0`, `asdas_crp@1.0.0` | formula | as v1 | 90 d | v1 |
| `qtcf_fridericia@1.0.0` | formula | QT, RR (or heart rate) | 30 d | new |
| `ecog@1.0.0`, `nyha@1.0.0` | extracted | `attribute` paths `ecog` (0–5) and `nyha` (I–IV), `source_priority: [structured_form, note]` | 30 d | Note values come from S3 with a fixed bilingual question and value schema; they are evidence-backed, never computed |

#### 6.2.4 Anchors

- `index`: the run's index date (v1 rule, `run_date | month_end`).
- `event`: per matching event of another atom (v3 rule, `event_pick: first | last | each`).
- `screening` and `randomization`: **future** dates supplied at run time. The default is the patient's next appointment in the study clinic, plus the study's `planned_randomization_offset_days` for `randomization`. Both are recorded in the candidate.

For a future anchor, the part of the window that lies in the past is evaluated on recorded data. The part that lies in the future is not observable:

| Situation | Result |
| --- | --- |
| A past record already fails and stays inside the window at the anchor | `fail`, with a `flip_rule` of kind `window_slide` and its flip date (watchlist) |
| A past record passes and stays inside the window at the anchor | `pass` |
| The decision depends on data not yet collected (for example, labs "within 14 days before randomisation") | `verify_at_screening`; the latest value is shown as context, never as a pass |

#### 6.2.5 The organ-function macro

`organ_function@<panel>-<semver>` expands at compile time into ordinary atoms with ULN-relative and absolute thresholds. The expansion is stored in `expanded`, so the compiled CQL and SQL are inspectable and covered by the equivalence gate. The default panel `onc-std-1.0.0` covers ANC, platelets, haemoglobin, ALT, AST, total bilirubin, renal function (eGFR or creatinine clearance) and INR, with conditional thresholds (for example liver metastases). Its seed list follows the core laboratory set proposed in the round-3 review *(source set uncertain; panel contents approved at G1 per study)*. Parameters override defaults per study. Unset parameters take the panel defaults, and the G1 workbook lists each one.

#### 6.2.6 Human criteria

`class: human` criteria never evaluate to `pass` or `fail` by machine. They are always `pending_human` or `verify_at_screening`, and carry a structured checklist that the decision sheet and the screening-visit checklist (§10.7) render:

```jsonc
"human": {"checklist": [
  {"item": {"en": "Patient is willing and able to comply with study visits", "zh-TW": "病人願意且能配合研究訪視"},
   "who": "investigator | crc", "when": "prescreen_call | screening_visit", "evidence_hint": "documented in the screening note",
   "blocks_enrollment": true}]}
```

#### 6.2.7 Canonical hash

`canonical_hash = sha256(JCS(normalise(criterion)))`, where `normalise`:

- renames atom ids positionally;
- replaces ValueSet names by content hashes;
- keeps calculators and macros as `id@version` with their parameters, and LoT rules by version;
- normalises windows to days;
- replaces the note question by its `key`;
- drops all free text, language variants, provenance and computability.

Two studies that use the same criterion therefore share the hash. The judgement cache, the recall ledger and the criterion library are all keyed by it.

### 6.3 Criterion library record

```jsonc
{"schema_version": "1.0.0", "lib_id": "cl_01JB7…", "canonical_hash": "sha256:9c1e…", "status": "approved",  // draft | approved | deprecated
 "kind": "inclusion", "class": "mixed", "ir": { /* IR 3 criterion without study-specific fields */ },
 "texts": [{"lang": "en", "text": "…", "source": "NCT05…/protocol v2"}, {"lang": "zh-TW", "text": "…", "source": "site translation"}],
 "valuesets": [{"id": "vs_nsclc", "sha": "sha256:…", "terminology_version": "term_2026-10"}],
 "lexicon_keys": ["lx_0142", "lx_0907"],
 "note_question": {"key": "nq_ecog_0_1", "en": "…", "zh-TW": "…", "ja": "…"},
 "lexicon_recall": {"n_judged": 200, "point": 0.990, "lower95": 0.965, "strata": {"zh": 0.99, "en": 1.0, "mixed": 0.98},
                    "suite_run": "er_01J…", "zero_hit_exclusion_allowed": false},   // rule in §10.4
 "computability_history": [{"snapshot": "snap_2026-10-17", "scope": "CHEST active 24m", "score": 0.58}],
 "precision_history": [{"period": "2026-Q3", "ppv_strong": 0.81, "n": 120}],
 "recall_ledger": "rl_9c1e…", "used_by": ["LUNG7/v1.0.0", "LUNG9/v1.1.0"],
 "seed_source": "chia | ctgov | site", "approved": {"gate": "G1-0412", "approval": "ap_…"},
 "supersedes": null, "data_class": "D1"}
```

The library holds no patient data (D1). The extractor's first step is retrieval over the library ("match then draft", §10.1). `match` in the IR records whether the criterion is an exact library match, a variant (with a diff) or new.

### 6.4 Canonical text

v3 §5.3 is kept: NFKC, full-width folding, whitespace collapse, CJK and Latin sentence segmentation, language tags and typed spans without rewriting the text. v4 adds a canonicaliser version and per-sentence hashes, which the sentence-set judgement cache uses (§10.4):

```jsonc
{"doc_ref": "DocumentReference/7f3…", "src_version": 3, "canon_version": "canon@2.1.0", "canon_sha": "sha256:…",
 "text": "…", "sentences": [{"i": 0, "start": 0, "end": 41, "lang": "mixed", "abbr_density": 0.18, "s_sha": "sha256:…"}],
 "spans": [{"start": 12, "end": 19, "type": "date", "value": "2024-03-05", "source_form": "113/3/5"}],
 "data_class": "D3"}
```

### 6.5 Evidence and candidate

Evidence becomes **multi-span**: a judgement may cite up to three spans, possibly from different documents, each verified byte-for-byte against its canonical text. This handles criteria that need two facts, such as a drug and a date.

```jsonc
{"evidence_id": "ev_01J…", "pid": "<pid>", "criterion_id": "LUNG7-INC-06", "canonical_hash": "sha256:9c1e…", "atom": "a3",
 "spans": [
   {"role": "fact", "source": {"type": "note", "ref": "DocumentReference/7f3…", "src_version": 3, "date": "2026-10-02", "department": "CHEST", "note_type": "progress"},
    "sentence": "PS: ECOG 1，可自行步行…", "quote": {"start": 0, "end": 10, "canon_sha": "sha256:…", "verified": true}, "lang": "mixed"},
   {"role": "date", "source": {"type": "note", "ref": "DocumentReference/7f3…", "src_version": 3}, "sentence": "…",
    "quote": {"start": 44, "end": 52, "canon_sha": "sha256:…", "verified": true}}],
 "combination": "all_required",                       // every span must verify, or the evidence is invalid
 "resolved_from": "note",                              // attribute source_priority result
 "assertion": {"model": "affirmed", "rules": "affirmed", "final": "affirmed"},
 "value": {"num": 1, "code": "ecog"}, "stage": "S3",
 "extractor": {"kind": "llm", "route": "judge@J-on-prem", "model_sha": "…", "prompt": "judge@v6"},
 "second_opinion": null, "provenance": "Provenance/ev_01J…", "data_class": "D3"}
```

The `potential` tier is split so that a CRC can triage the two kinds differently:

```jsonc
{"study_id": "LUNG7", "ruleset": "LUNG7/v1.0.0", "snapshot": "snap_2026-10-17", "pid": "<pid>",
 "anchors": {"index": "2026-10-17", "screening": "2026-10-24", "randomization": "2026-11-07"},
 "per_criterion": [{"criterion_id": "LUNG7-INC-06", "status": "pass | fail | unknown | pending_human | verify_at_screening",
                    "stage": "S3", "evidence_ids": ["ev_…"], "abstained": false, "conflict": null}],
 "tier": "strong | potential:data_gap | potential:uncertain | watchlist | excluded",
 "data_gaps": [{"criterion_id": "LUNG7-INC-04", "missing": "registry stage (case not yet abstracted)", "domain": "registry",
                "expected_available": "2027-03 (est., registry lag)", "action": "check pathology report at visit",
                "expires": "2026-11-07"}],
 "uncertain": [{"criterion_id": "LUNG7-EXC-02", "reason": "abstained | assertion_disagreement | quote_unverified | second_opinion_disagree",
                "evidence_ids": ["ev_…"]}],
 "flip": null, "next_appointment": {"at": "2026-10-24T01:40Z", "clinic": "CHEST", "practitioner": "P12345"},
 "route_to": "u_123", "decisions": [], "lineage_id": "lin_01J…", "data_class": "D3"}
```

Tier rules (normative; v3 rules otherwise kept):

- `potential:data_gap`: no hard failure, no uncertain criterion, and at least one `unknown` caused by missing data, each listed in `data_gaps` with a reason, an action and an expiry.
- `potential:uncertain`: no hard failure and at least one criterion where a model abstained or a verification failed, each listed in `uncertain`. Data gaps, if any, are listed too.

### 6.6 Feasibility objects

The packs and their rendering are specified in §12. Their data objects are:

```jsonc
// feasibility_estimate (one per study × ruleset × snapshot × scope; v3 §5.5 fields kept)
{"fe_id": "fe_01J…", "study_id": "LUNG7", "ruleset": "LUNG7/v1.0.0", "snapshot": "snap_2026-10-17",
 "sources": [{"source": "his_views", "data_cut": "2026-10-17T11:00Z"}, {"source": "cancer_registry", "data_cut": "2025-04-30"}],
 "funnel": [{"criterion_id": "…", "remaining": "410", "stage": "S1"}],
 "estimates": {"strong": {"est": "65", "ci95": ["40", "90"], "n_sampled": 200},
               "potential:data_gap": {"est": "50", "ci95": ["30", "75"], "n_sampled": 200},
               "potential:uncertain": {"est": "35", "ci95": ["20", "55"], "n_sampled": 200}},
 "recruitability": "rm_01J…", "recall_certificate": "rc_01J…", "privacy_ledger_entry": "pl_01J…",
 "lineage_id": "lin_01J…", "data_class": "D1"}

// recruitability_model (eligible → reachable → approachable → consented → screen-passed)
{"rm_id": "rm_01J…", "method": "hier_beta_binomial@1.0.0", "stages": [
   {"stage": "reachable", "definition": "alive, visit in last 12 m, appointment in enrolment window",
    "rate": {"a": 41.2, "b": 18.9}, "prior_source": "site history (n=9 studies)"},
   {"stage": "approachable", "definition": "contact scope allowed, not allocated to a competing trial",
    "rate": {"a": 12.0, "b": 4.0}, "prior_source": "published prior (ref)"},
   {"stage": "consent", "rate": {"a": 6.1, "b": 9.3}, "prior_source": "site history"},
   {"stage": "screen_pass", "rate": {"a": 8.4, "b": 3.6}, "prior_source": "therapeutic-area prior"}],
 "monthly": [{"month": 1, "p10": 0, "p50": 1, "p90": 3}], "total_12m": {"p10": 6, "p50": 11, "p90": 18},
 "assumptions_hash": "sha256:…"}

// forecast_ledger_entry (scored at study close)
{"fl_id": "fl_01J…", "study_id": "LUNG7", "issued": "2026-10-20", "rm_id": "rm_01J…",
 "forecast": {"total_12m": {"p10": 6, "p50": 11, "p90": 18}}, "actual": {"total_12m": null},
 "scores": {"crps": null, "brier_p50_band": null, "pit": null}, "closed": null}
```

The numbers above are illustrative only.

### 6.7 Recall certificate and ledger

The certificate's statistics are implemented in `libs/tb_common/recall.py` and specified in §10 (SAFE). The schema carries everything needed to recompute every printed number:

- per stratum, the anytime-valid confidence-sequence bound (Waudby-Smith & Ramdas betting) at α/K;
- a reference to the stored, resumable sequence state;
- the single-look Clopper–Pearson figure, for information only;
- two known-positive lines.

In the project's simulation, repeated monthly Clopper–Pearson looks over 12 months missed the true rate in 9.7 % of ledgers, against 0.3 % for the sequence. That is the reason the sequence bound is the one quoted.

```jsonc
// example produced by recall.certificate(strata, known_positive=(61, 0), alpha=0.05, anytime=True, observations=…)
{"schema_version": "3.0.0", "rc_id": "rc_01J…", "study_id": "LUNG7", "ruleset": "LUNG7/v1.0.0", "period": "2026-10",
 "alpha": 0.05, "k_strata": 5,
 "method": "confidence sequence (WSR 2024 betting), alpha 0.05 split over 5 strata (Bonferroni)",
 "strata": [
   {"stage": "S1-affirmative",    "excluded": 15100, "ledger_sampled": 600, "found": 0, "upper_cs": 0.015,  "upper_cp_single_look": 0.0076},
   {"stage": "S2-absence(index)", "excluded": 2900,  "ledger_sampled": 450, "found": 1, "upper_cs": 0.023,  "upper_cp_single_look": 0.0147},
   {"stage": "S2-zero_hit(note)", "excluded": 1800,  "ledger_sampled": 300, "found": 0, "upper_cs": 0.030,  "upper_cp_single_look": 0.0152},
   {"stage": "S2b-screen_out",    "excluded": 950,   "ledger_sampled": 300, "found": 0, "upper_cs": 0.030,  "upper_cp_single_look": 0.0152},
   {"stage": "S3-not_met",        "excluded": 240,   "ledger_sampled": 120, "found": 0, "upper_cs": 0.0725, "upper_cp_single_look": 0.0376}],
 // every stratum also carries: "weighting": "uniform | horvitz_thompson", "cs_state": {"ref": "cs_…", "sha": "sha256:…", "n": …},
 //                             "observation_seq_sha": "sha256:…", "looks": 7, "first_look": "2026-04"
 "missed_point": 6.4, "missed_upper": 393, "per_1000_excluded_upper": 18.7,
 "known_positive": [
   {"line": "historical_enrollees", "biased": true, "population": "patients enrolled in any thoracic-oncology study 2023–2026, pooled per criterion type",
    "r": 61, "missed": 0, "recall_lower": 0.952, "method": "Clopper–Pearson, single look"},
   {"line": "blinded_chart_review", "biased": false, "population": "CRC-confirmed candidates from blinded review, cumulative",
    "r": 34, "missed": 1, "recall_lower": 0.809, "method": "1 − confidence-sequence upper bound on the miss rate"}],
 "auditor": {"pipeline": "S4@V-sha", "human_blinded": 30, "human_agreement": 0.93},
 "demotions": [], "seed": 912733, "lineage_id": "lin_01J…", "data_class": "D1",
 "statement": {"en": "…quotes recall_lower of each line with its population, and per_1000_excluded_upper…", "zh-TW": "…"}}
```

The values above are the actual outputs of `recall.py` for these inputs (one positive placed at sample 200 in `S2-absence(index)`; one miss among 34 chart-review positives). They show the price of anytime validity: the sequence bounds are about twice the single-look bounds.

Two items need code changes in `recall.py` (owned by §10 SAFE; listed here because the schema depends on them):

1. The blinded-chart-review line uses `1 − ConfidenceSequence.upper` over the miss indicators, because that line accumulates. `certificate()` currently computes only the single-look `cp_lower`.
2. A Horvitz–Thompson weighted variant is needed for importance-weighted strata. Until it exists, `weighting` MUST be `uniform` and sampling within a stratum MUST be uniform.

`ConfidenceSequence` state (a grid of 2,001 log-capital values and rejection flags, plus `n`, `total`, `sq_dev` and `upper`) is stored per (canonical_hash, stratum, α) in `recall_ledger_entry`, together with the ordered observation list and its hash, so any certificate can be recomputed exactly.

### 6.8 Study Card additions

The v3 fields are kept. v4 adds:

```jsonc
{"sources_in_scope": [{"source": "his_views", "zone": "Z-PSN"}, {"source": "cancer_registry", "zone": "Z-PSN"}],
 "anchors": {"planned_randomization_offset_days": 14},
 "library_refs": {"matched": 21, "variant": 4, "new": 3},
 "consent_scope_required": ["research_use", "contact"],
 "project": "prj_01J…",                     // access project (§7.12)
 "forecast_ledger": ["fl_…"], "recall_certificates": ["rc_…"],
 "deliverables": [{"kind": "feasibility_pack", "id": "fp_…", "lineage_id": "lin_…", "data_class": "D1"}]}
```

### 6.9 Run manifest v3

The v1 and v3 fields are kept (code SHA, ruleset SHA, settings hash, outputs, `cascade`, `passes`, `parameters`). v4 adds lineage, data versions, routes and classes:

```jsonc
{"schema_version": "3.0.0", "manifest_id": "rm_01J…", "lineage_id": "lin_01J…", "workflow": "PreScreenWorkflow", "bundle": "4.0.3",
 "code_sha": "…", "settings_sha": "…",
 "snapshot": {"snapshot_id": "snap_2026-10-17", "manifest_sha": "sha256:…", "publish_gate": "pg_01J…",
              "tables": {"condition": {"iceberg_snapshot_id": 6110473920175812331, "rows": 18233410}, "…": {}},
              "data_cut_per_source": {"his_views": "2026-10-17T11:00Z", "cancer_registry": "2025-04-30"},
              "overlay": {"appointment": "hl7v2 ≤ 2026-10-18T02:14Z"}, "snapshot_age_days": 0,
              "override": null},
 "data_versions": {"terminology": "term_2026-10", "athena_release": "v5.0 …", "mapping_spec": "sha256:…",
                   "contracts": {"his_views/lab": "3.1.0"}, "lot_rules": "lot_rules@tw-onc-1.0.0",
                   "calculators": ["egfr_ckd_epi_2021@1.0.0"], "lexicon": "lex_2026-10-12"},
 "ruleset": {"id": "LUNG7/v1.0.0", "sha": "…", "ir_version": "3.0.0", "library_refs": ["cl_01JB7…"]},
 "routes": [{"role": "judge", "data_class": "D3", "route": "judge@J-on-prem", "model_alias": "j@4", "model_sha": "…",
             "prompt": "judge@v6", "calls": 1830, "cache_hits": 1210, "tokens": {"in": 4.6e6, "out": 4.1e5}, "cost": {"gpu_s": 2950}}],
 "data_classes": {"max_input": "D3", "outputs": [{"file": "LUNG7_candidates.xlsx.7z", "class": "D4"}, {"file": "summary.txt", "class": "D1"}]},
 "cascade": {"n_scope": 412000, "n_after": {"S0": 51000, "S1": 2900, "S2": 820, "S2b": 610, "S3": 140, "S4": 65},
             "pairs_judged": {"S3": 1830, "S4": 260}, "llm_share": 0.21, "zero_hit_exclusions": {"allowed_criteria": 3, "pairs": 410}},
 "replay": {"mode": "system_asof", "replay_degraded": null}}
```

`replay_degraded` takes the form `{"reason": "erasure", "ticket": "…", "rows_removed_per_table": {…}}` after a purge (§5.14.4).

### 6.10 Gate, approval and signature

v3 §5.9 is kept unchanged, with assurance levels A, A2, A+ and B. Each gate record adds `object.data_class` and `object.lineage_id`. The publish gate (§5.9.3) writes a `publish_gate_record` (§6.14), and its overrides are G0 gates at A2.

### 6.11 Site lexicon

v3 §5.10 is kept. Each row adds:

- `lang` including `ja`;
- `entry_id`;
- `pack_origin` (null, or the imported alliance pack id, ML-12);
- `recall_suites` (the lexicon-recall runs in which the row was used);
- `data_class: "D1"`.

Only `approved` rows feed S2, S2b query expansion and retrieval.

### 6.12 Privacy ledger and release records

```jsonc
// privacy_ledger_entry 2.0
{"pl_id": "pl_01J…", "requester": "sponsor:X", "project": "prj_…", "study": "LUNG7", "snapshot": "snap_2026-10-17",
 "query_fingerprint": "sha256:…", "cells": 42,
 "mechanism": "suppress+complementary+controlled_round(base5)",   // or "+geometric(eps)" / "+discrete_gaussian(rho)"
 "small_cell_threshold": 11, "suppressed_primary": 3, "suppressed_complementary": 2,
 "epsilon_spent": 0.0, "budget": {"period": "2026-Q4", "epsilon_total": 1.0, "epsilon_remaining": 1.0},
 "differencing_check": {"against": ["pl_01H…"], "result": "pass"}, "five_safes": "fs_…", "release_gate": "G2-0193"}

// release_certificate (every D2 row-level release, §7.6)
{"cert_id": "dc_01J…", "dataset": "tre/eval_lung_2026q4", "variant": "D2-L | D2-K", "rows": 1840,
 "quasi_identifiers": ["age_band", "sex", "county", "dx_month"], "sensitive": ["hiv_status"],
 "k_min": 7, "l_min": 2, "date_shift_days": "±182 per patient", "top_code_age": 90, "text": "removed | scrubbed@ner-v3 (recall 0.985)",
 "method": "safe_harbor_equivalent | expert_determination", "risk": {"model": "prosecutor", "max": 0.09, "avg": 0.02, "threshold": 0.09},
 "context": {"recipient": "…", "settings": "TRE | external", "iso27559_assessment": "doc_…"},
 "approvals": ["steward", "dpo", "irb:…"], "lineage_id": "lin_…"}
```

### 6.13 LLM platform records

The lifecycle, routing and gates are in §8. These are the stored objects:

| Schema | Key fields |
| --- | --- |
| `model_build` | `alias@version`; origin (repo, revision); SHA-256 of every weight file; tokenizer and chat-template hashes; quantisation recipe and calibration-data hash; engine version and container digest; serving flags; licence; family and origin country; status `candidate | shadow | champion | retired`; approved `roles × data_classes × topologies × profiles`; G5 record; retirement date |
| `model_card` | Build ref; intended roles and contexts of use; languages with per-language scores; maximum context; known failure modes; evaluation reports; bias and subgroup results; data classes permitted; out-of-scope uses; change log (CHAI-style fields where applicable) |
| `routing_rule` | `(role, data_class, profile, topology, site_flags) → ordered build list`; fallbacks never cross a data class; G5 reference; effective dates |
| `eval_report` | Suite, dataset ids and licences, build, prompt version, metrics with bootstrap CIs per language stratum, thresholds, pass/fail, seeds |
| `bench_report` | Profile, hardware, build, throughput, latency, peak memory, swap time, pass/fail against the bench gate |
| `bakeoff_record` | Candidate builds; tasks; languages (en, zh-TW, ja, mixed); data class (MUST be D0); prompts and schemas (hashes); seeds; metrics with CIs; cost and latency per 1,000 items; per-language floors; composite; result status `pending | complete` (results stay `pending` until runs exist; none are invented) |

### 6.14 Data-platform records

```yaml
# data_contract (site/contracts/his_views/lab.yaml)
contract_id: his_views/lab
version: 3.1.0
source: his_views
kind: db_view
owner: "Hospital (controller)"
steward: "u_steward_lab"
change_channel: "dba-team@hosp.example"
latency_class: daily
keys: {primary: [lab_no], patient: mrn, watermark: updated_at, version: row_version}
columns:
  - {name: lab_no,          type: varchar(20), nullable: false, unique: true, privacy: none}
  - {name: mrn,             type: varchar(12), nullable: false, privacy: direct_identifier}
  - {name: local_code,      type: varchar(16), nullable: false, code_system: "urn:site:lab", privacy: none}
  - {name: result_value,    type: varchar(40), nullable: true,  logical: decimal_or_text, privacy: none}
  - {name: unit,            type: varchar(16), nullable: true,  ucum_map: "units/lab_units.csv"}
  - {name: sample_datetime, type: timestamp,   nullable: false, tz: Asia/Taipei, plausibility: {not_future: true}}
volume: {weekday_rows: [18000, 30000], weekend_rows: [2000, 9000], max_quarantine_share: 0.005}
control_totals: [count, count_distinct_patient, min_max_watermark, keyhash_sum, per_day_counts]
quality: {gx_suite: "gx/his_views_lab@3.1.0", blocking: [lab_unit_ucum, lab_value_numeric_share]}
coverage_floor: {laboratory: 0.90}
required_for_publish: true
change_policy: {additive: auto, breaking: g0_major}
```

| Record | Key fields |
| --- | --- |
| `l0_batch_manifest` | `batch_id`, source, kind, `extract_start/end`, objects `[{key, bytes, sha256}]`, rows, `schema_fingerprint`, `watermark_from/to`, `control_totals`, encoding, `data_class` |
| `reconciliation_record` | Batch or cycle id; equations `[{level, lhs, rhs, diff, tolerance, verdict}]` |
| `dq_report` | Snapshot; checks `[{rule_id, engine (gx | sql | dqd), kahn_category, kahn_subtype, context, table, field, threshold, result, severity}]`; DQD JSON ref; scorecard aggregates |
| `snapshot_manifest` | `snapshot_id`; per-table Iceberg snapshot ids and row counts; contract versions; mapping-spec hash; terminology release; data cut per source; publish-gate record; Ed25519 signature |
| `publish_gate_record` | Cycle; conditions 1–7 of §5.9.3 with results; outcome `PUBLISH | PUBLISH_WITH_WARNINGS | HOLD | OVERRIDE`; override gate id |
| `purge_certificate` | Ticket; pids (hashed again for the certificate); stores purged with counts; snapshots rewritten and expired; manifests marked `replay_degraded`; deliveries that contained the person; completion time; signature |
| `lineage_event` | OpenLineage RunEvent JSON with the TrialBox facets of §5.15 |

### 6.15 Consent (FHIR `TBResearchConsent`)

Consent and opt-out are patient-level records (FHIR R4 `Consent`, profile `TBResearchConsent`). They are ingested from the hospital's consent registry (CSV drop or FHIR) and replace the v3 site-level flag.

| Element | Content |
| --- | --- |
| `status` | `active | inactive | rejected` |
| `scope` | `research` (HL7 consentscope) |
| `category` | LOINC `59284-0` (patient consent) or a site code |
| `patient` | Pseudonymised reference after L3 |
| `dateTime`, `provision.period` | When given and how long it applies |
| `policyRule` | Site policy URI (for example the hospital's research-use notice version) |
| `provision.type` | `permit | deny` |
| `provision.purpose` | TrialBox scope codes (CodeSystem `https://trialbox.local/fhir/CodeSystem/consent-scope`) with v3-ActReason equivalents where they exist |
| `sourceAttachment` / `sourceReference` | Pointer to the signed form in the HIS (never copied) |

| Scope code | Meaning | Applied at |
| --- | --- | --- |
| `research_use` (≈ `HRESCH`) | The patient's data may be used for research screening and feasibility | L3 (deny → rows excluded from Z-PSN research tables, counted) |
| `contact` | The patient may be contacted about trials | S0 and list rendering (deny → never listed to a PI; still counted in aggregates when `research_use` permits) |
| `nhi_secondary_use` | Objection to secondary use of NHI-derived data (§7.3.1) | L3 for NHI-origin rows (claims, MediCloud) |
| `export_d2` | Inclusion in de-identified exports beyond the TRE | De-identification pipeline (§7.6) |

The default when no record exists is a site policy (`research_use: permit`, `contact: permit` by default, matching v3 PRIV-8's `all_research_use` opt-out semantics). The default is set at G0 and printed in the validation pack. The latest active record per scope wins.

### 6.16 Requirements

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| DM-01 | All v4 contracts MUST be JSON Schema 2020-12 files in `schemas/v4/`, compiled into `libs/tb_contracts`, with `make contracts-check` failing CI on drift. Every persisted object MUST carry `schema_version`, and every object that reaches a person or sponsor MUST carry `data_class` and `lineage_id`. | T | MS0 |
| DM-02 | IR 3.0.0 MUST be a superset of IR 2.0.0 with the extensions of §6.2. Rulesets below 3.0.0 MUST run unchanged until recompiled at their next G1. | T | MS1 |
| DM-03 | Every IR 3 construct (line of therapy, attribute with `source_priority`, `value.ref`, derived calculators, screening and randomisation anchors, the organ-function macro, human checklists) MUST compile to CQL and SQL from templates and pass the equivalence gate on `rulesets/ATOMS_V3` fixtures. | T | MS1 |
| DM-04 | `attribute` resolution MUST follow `source_priority` and the declared conflict rule, MUST log `resolved_from` in the evidence, and MUST yield `unknown` (data gap) when no source has a value. | T | MS1 |
| DM-05 | `episode_lot` MUST be derived deterministically by a versioned `lot_rules` artefact approved at G0. An atom requiring `ended_by: progression` MUST yield `unknown` when the end is unattributed. | T | MS2 |
| DM-06 | Each calculator MUST have an id, semantic version, constants hash and ≥ 20 test vectors. CQL and SQL MUST be rendered from the same constants. A ruleset MUST pin `calc_id@version`. Published versions MUST be immutable. | T | MS1 |
| DM-07 | Future anchors (`screening`, `randomization`) MUST follow the evaluation table of §6.2.4. Data not yet collectable MUST yield `verify_at_screening`, never `pass`. | T | MS1 |
| DM-08 | The organ-function macro MUST expand at compile time into stored atoms. The G1 workbook MUST list every parameter and its value. | T | MS1 |
| DM-09 | `class: human` criteria MUST never evaluate to `pass` or `fail`, and MUST carry a checklist rendered on the decision sheet and the screening-visit checklist. | T | MS2 |
| DM-10 | `canonical_hash` MUST be computed by the normalisation of §6.2.7 and MUST be identical for semantically identical criteria across studies and languages. | T | MS1 |
| DM-11 | Criterion library records MUST follow §6.3, hold no patient data, and record `lexicon_recall` with the suite run that measured it. | T | MS1 |
| DM-12 | Canonical text MUST carry `canon_version` and per-sentence hashes. A canonicaliser version change MUST trigger re-canonicalisation and re-verification of stored evidence quotes. | T | MS1 |
| DM-13 | Evidence MUST support up to three spans with `combination: all_required`. Every span MUST verify byte-for-byte against its canonical text, or the evidence is invalid. | T | MS2 |
| DM-14 | Candidates MUST use the tiers `strong`, `potential:data_gap`, `potential:uncertain`, `watchlist` and `excluded` with the rules of §6.5. Every data gap MUST name what is missing, an action and an expiry. | T | MS2 |
| DM-15 | Feasibility objects MUST follow §6.6 and record the data cut of every contributing source. Every recruitability forecast MUST create a forecast-ledger entry that is scored at study close. | T | MS1 |
| DM-16 | The recall certificate MUST follow §6.7: confidence-sequence bounds per stratum at α/K, the single-look figure for information only, two known-positive lines (historical enrollees labelled biased; blinded chart review with a sequence-based bound), and stored sequence state and observation hashes sufficient to recompute every number. | T | MS2 |
| DM-17 | Run manifest v3 MUST contain the fields of §6.9, including per-table snapshot ids, data cut per source, overlays, data versions, routes with data class and model SHA, and `replay_degraded`. | T | MS0 |
| DM-18 | Gate, approval and signature records MUST keep v3 §5.9 semantics and add `data_class` and `lineage_id` of the object. | T | MS0 |
| DM-19 | Privacy-ledger entries and release certificates MUST follow §6.12 and be written for every release from Z-PSN or Z-TRE. | T | MS1 |
| DM-20 | `model_build`, `model_card`, `routing_rule`, `eval_report`, `bench_report` and `bakeoff_record` MUST follow §6.13. A `bakeoff_record` MUST declare data class D0 and MUST keep result status `pending` until runs exist. | T, I | MS0 |
| DM-21 | Data contracts and data-platform records MUST follow §6.14. Snapshot manifests MUST be signed. | T | MS0 |
| DM-22 | Consent MUST be stored per patient as `TBResearchConsent` with the scopes of §6.15. The site default for patients without a record MUST be set at G0 and printed in the validation pack. | T | MS2 |

## 7. Privacy architecture

v3 privacy was pseudonymisation, rounding and a differencing check (PRIV-1…9). The hybrid requirement (C-2′) makes a data-class model and explicit boundary rules mandatory (R3-16). This section defines the classes, the boundaries per topology, the legal basis, and the privacy-enhancing technologies with a named use for each. Security controls (keys, network, identity, breach response) are in §14. The compliance trace is in §15. Gateway enforcement of model routes is in §8.

**Principle.** The **data class, not the network location, decides what may happen to data.** Every dataset, column, document, prompt, tool result, message and file carries a class. A class can be lowered only by a registered transform that leaves a certificate. **D3 and D4 never reach any external model, in any topology.**

### 7.1 Data classes

| Class | Definition | Examples | Personal data? |
| --- | --- | --- | --- |
| **D0** public | Published or open data with no personal data | ClinicalTrials.gov records, published protocols, terminologies, open benchmarks (MIMIC-IV demo under ODbL, NCBI TrialGPT data), Synthea output | No |
| **D1** confidential, no PHI | Business-confidential content with no patient-level data | Sponsor protocol drafts, questionnaires, site profile, lexicon, prompts, mapping specs, k-suppressed profiles (k ≥ 11), aggregates **after** the privacy accountant | No (after accountant) |
| **D2** de-identified patient-level | Patient-level rows that passed the de-identification pipeline (§7.6) with a release certificate. Two variants: **D2-K** (keyed: project-scoped pseudonyms, the hospital can re-link through the vault) and **D2-L** (de-linked: random surrogates, no mapping kept anywhere) | CGRD-type research DB, evaluation sets, validation-replay datasets, synthetic cohort twins | D2-K: yes under PDPA. D2-L: possibly not, case by case (§7.3) |
| **D3** pseudonymised patient-level | Patient-level data keyed by `pid`; direct identifiers removed from structured fields; free text verbatim | Curated lake, FHIR store, OMOP, notes, evidence, judgements, candidate lists keyed by pid, **unreleased** aggregates | Yes |
| **D4** identified | Data with direct identifiers | Identity vault, MRNs, names, national IDs, L0 raw batches, PI candidate lists with MRN | Yes |

**Special-category flag.** Independently of class, a dataset or column may carry `sc` for genetic data, psychiatric, HIV/STI, substance-use, sexual and reproductive health, and minors. `sc` data needs a dedicated model pool with per-study cache salt, reduced trace retention (§8), a stricter small-cell threshold (default 20 *(est.)*), and an extra DPO approval for any D2 release.

**Propagation and declassification.** A derived object takes the highest class of its inputs. The only transforms that lower a class are:

| Transform | From → to | Certificate | Owner |
| --- | --- | --- | --- |
| Privacy accountant (§7.8) | D3 aggregate → D1 | `privacy_ledger_entry` | Research office at G2 |
| De-identification pipeline (§7.6) | D3 → D2-K or D2-L | `release_certificate` | Steward + DPO (+ IRB where required) |
| Synthetic-twin generator (§7.11) | D2 / aggregates → D2 (synthetic) | `release_certificate` with synthetic flag | Steward |
| Publication | D1 → D0 | Publication record (sponsor consent where needed) | Research office |

The class label is assigned at the **source**, by the workflow step or the zone. Models never infer it (§8).

### 7.2 Boundaries per topology

| Data | A: on-prem appliance | B: hospital cloud tenant (in-country, customer-managed keys) | C: hybrid, A or B plus model egress | Developer / bake-off (Z-DEV) |
| --- | --- | --- | --- | --- |
| D0 | Process and store | Process and store | Any approved model route, including vendor cloud | OpenRouter and other public endpoints allowed |
| D1 | Process and store | Process and store | Vendor cloud model only under contract with zero data retention, no training use, an approved region, and (for sponsor-confidential content) the sponsor's written consent per protocol; **default off** | Not allowed |
| D2-L | Process and store in Z-TRE | Z-TRE in the tenant | Vendor cloud model only with a release certificate, a cross-border assessment (§7.15), IRB and DPO sign-off, an in-country endpoint where one exists; **default off** | Not allowed |
| D2-K | Z-TRE only | Z-TRE only | **Never** (the key exists, so the data are personal data and not de-linked) | Not allowed |
| D3 | Process and store | Process and store only if the tenant is attested as the hospital's own perimeter: Taiwan region, certified provider (EMR regulation Art. 8), customer-managed keys, no vendor access | **Never** to an external model | Not allowed |
| D4 | Vault and L0 only | Vault in HSM-backed storage in the tenant, or kept on-prem if the HIS is on-prem | **Never** | Not allowed |
| Released aggregates (D1) | Email to sponsor after G2 | Same | Same | n/a |

**Channels and agent.**

| Surface | Highest class it may carry |
| --- | --- |
| Email | D4 only as encrypted attachments to delegated internal recipients (SEC-10, §14). D1 to sponsors after G2. Body text D1 at most. |
| Microsoft Teams | D1 (nudges, aggregate status). No patient references. No approvals (FR-SIG-8). |
| LINE | D0/D1 nudges only. No study-patient references. |
| Hermes Agent (§9) | D0/D1 context only. Aggregate tools return D1 after the accountant. It has no PHI tools in any topology. |
| Trace store (§8) | D3 only in redacted form, on the perimeter. 90-day retention. |
| Logs and SIEM export | Hashes, ids, policy decisions and metadata. No PHI. |

The gateway (§8) and L5 enforce this table in code. The `redteam` and `egress` suites (§16) prove that D3/D4 content cannot reach a non-perimeter endpoint, including through fallbacks, retries, caches and traces.

### 7.3 Legal basis

This subsection states the legal texts the design relies on. It is not legal advice. The lawful basis for each purpose is fixed per site by the hospital's counsel and IRB (§15, §21).

#### 7.3.1 Taiwan

| Instrument | Text relied on | Consequence for TrialBox |
| --- | --- | --- |
| **Personal Data Protection Act (個人資料保護法), as amended and promulgated 2025-11-11** | Medical records, treatment, genetic and health-examination data are special-category data (Art. 6). Art. 6(1)(4) permits processing by government agencies or academic research institutions for medical, health or crime-prevention statistics or research, where the data, as processed or as disclosed, "may not lead to the identification of a specific data subject". The amendments create the **Personal Data Protection Commission (PDPC)** as competent authority (Art. 1-1) and require **breach notification** to the data subjects and to the authority (Art. 12). Art. 21 lets the competent authority restrict cross-border transfers. The commencement of the PDPC provisions depends on an Executive Yuan order *(uncertain in October 2026)*. | D3 and D2-K are personal data. Released aggregates are designed to fall under "cannot identify". The breach workflow (SEC-14, §14) notifies both the authority and data subjects. Cross-border transfers need the §7.15 analysis. |
| **PDPA Enforcement Rules, Art. 17** | "無從識別特定當事人" means that personal data, through codes, anonymisation, hiding part of the data or other means, can no longer identify the specific individual. | This is a **list of methods, not a risk threshold**. TrialBox therefore adds a measured risk threshold (§7.6) and records the methods used in every release certificate. |
| **Human Subjects Research Act (人體研究法)** | Art. 4(3) defines **去連結 (de-linking)**: processing so that the materials can "永久不能以任何方式連結、比對" (permanently never be linked or matched by any means) with identifying data. Art. 19 requires written consent, a foreign institution's guarantee, IRB approval and competent-authority approval before non-de-linked research materials go abroad. | **A keyed pseudonym is not de-linked** while TrialBox or the hospital holds the key. D3 and D2-K are not de-linked. Only D2-L (random surrogates, no mapping kept, plus generalisation) is a candidate for 去連結, and the IRB decides. |
| **Regulations on Medical Institutions' Electronic Medical Records (醫療機構電子病歷製作及管理辦法, last amended 2022-07-18)** | Art. 8: cloud-stored EMR data "應設置於我國境內" (must be located in Taiwan) unless the central authority approves otherwise, and the cloud provider must hold a security certification recognised by the authority. Art. 13: complete records of access, edits, viewing and copying (who, when, what). | Topology B MUST use a Taiwan region and a certified provider. Every TrialBox copy of EMR data keeps Art. 13 logs (DP-44). |
| **Constitutional Court Judgment 111-Hsien-Pan-13 (2022-08-12)** and the **NHI Act** | The Court upheld PDPA Art. 6(1)(4), found that the storage and provision of NHI data for secondary use lacked a sufficient legal basis and independent oversight, and required a mechanism to stop secondary use within three years. It also ordered that, if no legislation follows, data subjects may request that such use stop. The NHI Act has not been amended since 2023-06-28 and contains no opt-out article, and the three-year deadline has passed. | NHI-derived data (claims, MediCloud) are subject to patient objection, applied through the `nhi_secondary_use` scope (§7.13). **Whether NHIA keeps an administrative opt-out list that hospitals can import is *(uncertain)*.** TrialBox therefore supports importing such a list but does not assume it exists. |

#### 7.3.2 Japan (profile `locale: ja-JP`)

| Instrument | Text relied on | Consequence |
| --- | --- | --- |
| **APPI (個人情報保護法)** and the PPC guidelines on pseudonymously and anonymously processed information | **仮名加工情報** (pseudonymously processed information) cannot identify a person unless collated with other information. Processing requires deleting or replacing identifying descriptions, deleting all individual identification codes, and deleting descriptions that could cause financial harm. Third-party provision is prohibited, except for outsourcing, business succession and joint use. Re-identification and contacting the person are prohibited, and the replacement keys must be secured. **匿名加工情報** (anonymously processed information) cannot be restored. It also requires deleting linking codes and unique descriptions, and may be provided to third parties once its categories are published. A further APPI amendment (Law No. 56) was promulgated on 2026-07-17 *(secondary source)*. | D3 in a Japanese deployment is handled as 仮名加工情報 at most, never provided to third parties, never used to contact people outside the clinical relationship. D2-L corresponds to 匿名加工情報 when processed to its rules. |
| **Next-Generation Medical Infrastructure Act** (Act No. 28 of 2017, 医療分野の研究開発に資するための匿名加工医療情報及び仮名加工医療情報に関する法律) | Covers anonymised **and pseudonymised** medical information through certified creators and users, with utilisation types for on-premises, cloud, on-site and remote access. | The Japan profile supports operating as, or with, a certified creator or user in the on-premises usage type. |
| **MHLW Guidelines for the Security Management of Medical Information Systems** (医療情報システムの安全管理に関するガイドライン) | Security baseline for a Japanese deployment; the edition is pinned at MS6 (7.0, June 2026, per the research note *(uncertain)*). | Mapped in §15. |

#### 7.3.3 Reference: HIPAA

HIPAA does not apply to Taiwanese or Japanese hospitals. Sponsors use it as a vocabulary, so TrialBox uses it only as a reference:

- 45 CFR 164.514(b)(1) **Expert Determination**: a qualified expert finds that the risk of re-identification is very small.
- 164.514(b)(2) **Safe Harbor**: the 18 identifiers removed, dates reduced to year, ages over 89 aggregated, and 3-digit ZIP only for areas with more than 20,000 people.
- 164.514(c): a re-identification code must not be derived from information about the individual. **An HMAC of the MRN is therefore not a valid re-identification code.** TrialBox's `pid` is an HMAC of a random `mpi_id` (§5.14.1). Any release described to a sponsor as "HIPAA-style" uses random surrogates from the tokenisation vault.
- The wording above is taken from the research note; the eCFR page could not be fetched *(uncertain wording)*.

### 7.4 Roles

ISO 25237 (health informatics pseudonymisation; edition pinned at MS1 *(uncertain)*) separates the data source, the pseudonymisation service and the data user. TrialBox maps them as follows:

| ISO 25237 role | TrialBox |
| --- | --- |
| Data source | Hospital HIS, registries, research DB (data controller: the hospital) |
| Pseudonymisation service (trusted) | `tb-vault` (L3, MPI, keys) operated by the hospital custodian; the honest broker for research-ID linkage |
| Data user | Workflow steps in Z-PSN; projects in Z-TRE; sponsors (D1 only) |
| Re-identification authority | PI-approved re-identification through `tb-vault` (Level A/B approval) |

### 7.5 Pseudonymisation design

**Key hierarchy.** Keys never leave the HSM, TPM or KMS boundary in plaintext (§14).

| Key | Derivation | Use | Rotation |
| --- | --- | --- | --- |
| `K_root` | Generated in an HSM, or TPM-sealed on topology A | Root of the HKDF tree; never used directly | Never in place; replacement is a re-pseudonymisation event |
| `K_pid` | `HKDF-SHA-256(K_root, salt = site_id, info = "tb/pid/v1")` | `pid = hex(HMAC-SHA-256(K_pid, mpi_id))[:32]` | Planned key-version change only, with a `pid_alias` table (reason `key_rotation`) |
| `K_proj(p, n)` | `HKDF-SHA-256(K_root, salt = site_id, info = "tb/proj/" + project_id + "/v" + n)` | `pid_p = HMAC(K_proj, pid)` for project-scoped extracts (D2-K, evaluation sets, alliance studies), so that datasets of different projects cannot be joined | Per project version; destroyed at project end (which turns a D2-K extract into a candidate for D2-L) |
| `K_vault_dek` | Random data key wrapped by a KMS/HSM key | AES-256-GCM encryption of identifiers in `tb-vault` (associated data = pid, as v1) | Yearly re-wrap |
| `K_link` | Held by the honest broker, never by TrialBox | PPRL tokens (§7.10) | Per linkage project |

**Tokenisation vault.** `tb-vault` is a separate service with its own PostgreSQL instance and volume. Its API is:

- `resolve(pid, purpose, approval_id, requester)` returns the MRN for rendering a list to a delegated recipient;
- `surrogate(project, pid)` issues a random D2 surrogate, keeping the mapping only for D2-K;
- `erase(ticket)`;
- `merge(event)`.

Every call is audited in the hash-chained ledger with purpose and approval. `resolve` is callable only from deterministic workflow steps after the gate that authorises the list (G3 or a Level A/B approval). No model and no Hermes tool can reach it (§4, §9). The vendor has no standing access.

### 7.6 De-identification pipeline and risk assessment

The pipeline (`libs/tb_common/privacy/deid/`) produces every D2 dataset. It uses technique names from ISO/IEC 20889:2018 and the context-based risk assessment of ISO/IEC 27559:2022 (editions *(uncertain)*).

| Step | Technique (ISO/IEC 20889 terms) | Default |
| --- | --- | --- |
| 1. Scope | Data minimisation: only the columns the project record allows | Project record (§7.12) |
| 2. Direct identifiers | Suppression (removal): names, MRN, national ID/ARC, phone, address, e-mail, photos, device ids, free-text identifiers | Always |
| 3. Pseudonyms | D2-K: `HMAC(K_proj, pid)`. D2-L: random surrogates, mapping never stored | Per variant |
| 4. Dates | Per-patient random shift with intervals preserved; or generalisation to month | Shift ±182 days *(est.)*; month generalisation for external releases |
| 5. Quasi-identifiers | Generalisation: age bands, top-coding at ≥ 90, county or region only (no area under 20,000 people), rare diagnoses rolled up to 3-character ICD | Declared per project |
| 6. Free text | Removed by default. If text is needed: code-mixed NER plus pattern scrubbing (§7.14), with residual-identifier sampling | Recall gate ≥ 0.98 for names and IDs |
| 7. Risk measurement | k-anonymity and l-diversity (§7.7); prosecutor and journalist risk | Thresholds below |
| 8. Context assessment | ISO/IEC 27559 style: recipient, settings, contracts, motivation and capacity to re-identify | Template `docs/privacy/context_assessment.md` |
| 9. Certificate | `release_certificate` (§6.12) with methods, measured risk, context, approvals | Always |

**Risk thresholds** (site parameters; defaults *(est.)*):

| Release setting | Maximum prosecutor risk | Equivalent k |
| --- | --- | --- |
| Inside Z-TRE (Five Safes controls in place) | 0.20 | k ≥ 5 |
| External release, or topology C model route | 0.09 (the threshold used in EMA Policy 0070 guidance for clinical-report anonymisation) | k ≥ 11 |

**Method label.** The certificate names its method: `safe_harbor_equivalent` (Safe Harbor-style rules adapted to Taiwan or Japan identifiers plus the measured k) or `expert_determination` (a named expert's report attached).

### 7.7 k-anonymity and l-diversity checks

Every D2 dataset declares its quasi-identifiers (at least age or age band, sex, geography, admission and diagnosis dates or months) and its sensitive attributes. `libs/tb_common/privacy/kanon.py` computes:

- equivalence classes over the quasi-identifiers and the minimum class size **k**;
- distinct **l** of each sensitive attribute within each class;
- the share of records in classes below the threshold.

The release is blocked until generalisation or record suppression meets the threshold. Suppressed records are counted on the certificate (default maximum 5 % *(est.)*). For longitudinal data, the quasi-identifiers include the number of encounters and the first and last encounter months, because visit patterns identify.

### 7.8 Aggregate disclosure control

Every aggregate that leaves Z-PSN or Z-TRE passes the **privacy accountant** (`libs/tb_common/privacy/sdc.py` and `accountant.py`, extending v1 `tb_common.smallcell`).

| Rule | Default | Notes |
| --- | --- | --- |
| Small-cell threshold | **11** for external releases (site parameter, minimum 5); 5 inside the research office | Counts 1–10 are not published directly, and neither are values they can be derived from (CMS cell-size policy). `sc` data: 20 *(est.)*. |
| Primary suppression | Cells 1 to threshold−1 become `<threshold` | 0 is published only when the zero is structural (for example, sex-specific criteria) |
| **Complementary suppression** | For every table with margins, additional cells are suppressed until no suppressed cell can be recomputed from totals or other cells | Greedy choice of the smallest complementary cells, then an exact audit (below) |
| **Controlled rounding** | Remaining counts rounded to base 5 (v1 `round_count`), so differences between published counts are multiples of 5; interval endpoints floored and ceiled to base 5 (CAS-8) | Kept from v3 PRIV-2 |
| Rates | Published only if numerator, denominator and complement all pass (v1 `rate_publishable`) | |
| Per-investigator counts | Bands only (`≥10`, `5–9`, `<5`) | Kept from v3 PRIV-2 |
| Audit | A linear-programming check (HiGHS through SciPy) computes, for every suppressed cell, the feasible interval implied by everything published in this release and in earlier releases to the same requester for the same snapshot and study. The release is blocked if any interval is narrower than the threshold. | Covers the v3 differencing check |
| What-ifs | Internal only, capped (FR-M2-2) | Kept |

Text generated around numbers uses placeholders filled from the released table and is checked by `numbers_match` (§8). Figures are rendered only from the already-suppressed table (§12).

### 7.9 Differential privacy and the ε ledger

Machine-readable count APIs and federated answers face repeated queries, so they get DP noise on top of suppression and rounding. Human-reviewed, one-off feasibility reports use suppression and rounding only, because those are easier to explain to a sponsor and an IRB.

| Item | Rule |
| --- | --- |
| Mechanism | Geometric (discrete Laplace) noise on integer counts, sampled with integer arithmetic from a cryptographic RNG (avoiding floating-point attacks). The discrete Gaussian under zCDP is optional. The library is in-house (`privacy/dp.py`) or OpenDP *(licence and version to verify)*. |
| Sensitivity | 1 per patient per count cell, enforced by counting distinct pids |
| Default ε | 0.1 per query cell set; budget 1.0 per requester per project per quarter *(est.; site parameters)* |
| Composition | Basic sequential composition (sum of ε), which is conservative |
| Post-processing | Rounding and suppression after noise are allowed and do not consume budget |
| Federated | Pairwise-cancelling masks between alliance members (v3 FR-M11-3), with each member's ε accounted at the member |
| Exhaustion | Request refused with an explanation; the research office can raise the budget only at G2, recorded in the ledger |
| Ledger | `privacy_ledger_entry.epsilon_spent` and `epsilon_budget` (§6.12), per requester × project × period |

### 7.10 Privacy-preserving record linkage for enrolment lists

Validation replay (§16) and the known-positive line of the recall certificate need to know which research-database patients enrolled in which study. The enrolment list is MRN-keyed (CTMS, Z-IDN). The research database is keyed by research IDs (Z-TRE). TrialBox never holds a link between them.

1. The research office sends the enrolment list (MRN, study, enrolment date) to the **honest broker**, not to Z-TRE.
2. The broker maps MRN → research ID with its own link table. Where it has none (for example across institutions), it computes **PPRL tokens**: `HMAC-SHA-256(K_link, normalise(national_id))`, or `HMAC(K_link, normalise(name) ‖ birth_date ‖ sex)` as a fallback. Tokens from both sides are matched exactly.
3. Fuzzy matching with Bloom-filter encodings is allowed only inside the broker's environment, with hardening (salting, balancing) because plain Bloom-filter encodings are vulnerable to frequency attacks.
4. The broker returns to Z-TRE only research-ID-keyed labels (`research_id, study, enrolled_month`) and linkage quality figures: match rate and duplicate-token rate.
5. Z-TRE uses the labels for replay metrics and certificate known-positive lines. Labels inherit D2.

### 7.11 Synthetic cohort twins

A **synthetic cohort twin** is a generated dataset that reproduces the marginals of a scoped cohort, so that sponsors and cloud evaluations can see the shape of the data without real patients.

| Item | Rule |
| --- | --- |
| Inputs | Only D2 data or DP-noised marginals computed in Z-TRE. Never raw D3. |
| Method | A marginal-based DP synthesiser (for example the MST method of McKenna et al. 2021) over the IR-relevant variables *(library choice uncertain; ε recorded)* |
| Utility test | Funnel agreement with the real (accountant-released) funnel within the rounding base at each step; marginal error per variable |
| Privacy test | Distance-to-closest-record against a held-out real sample; membership-inference AUC ≤ 0.60 *(est.)* |
| Label | Every file and row is flagged `synthetic: true`. Twins never appear in a pack as real counts. |
| Class | D2 (synthetic) with a release certificate. Cloud use under topology C only per the D2-L row of §7.2. |

### 7.12 Five Safes and the TRE (Z-TRE)

Z-TRE follows the Five Safes framework, the same model as the HWDC (on-site analysis, output review).

| Safe | Control |
| --- | --- |
| Safe projects | Every access is a `project` record: purpose code (`feasibility`, `validation`, `evaluation`, `qa`, `prescreen:<study>` for Z-PSN), IRB reference, data classes, sources and zones, expiry, approvers (steward + PI, plus IRB where needed). Requests without an active project are refused. |
| Safe people | Named project members only. Training record current (M7 calendar). Hospital staff or contracted researchers under the hospital's confidentiality terms. Vendor staff never. |
| Safe settings | Z-TRE database role and object prefix; no network egress; hospital network only; sessions logged (EMR regulation Art. 13); exports only through output review. |
| Safe data | D2 only, with release certificates; project-scoped keys (`K_proj`), so cross-project joins are impossible. |
| Safe outputs | Steward output review against the §7.8 rules (thresholds, complementary suppression, LP audit); outputs land in Z-REL with a ledger entry. |

The checklist is stored with every release record (`five_safes` in the privacy ledger).

### 7.13 Consent and opt-out

Consent is patient-level (`TBResearchConsent`, §6.15) with the scopes `research_use`, `contact`, `nhi_secondary_use` and `export_d2`.

| Point of application | Scope | Effect |
| --- | --- | --- |
| L3 | `research_use: deny` | Rows excluded from research tables in Z-PSN and from Z-TRE extracts; counted as opted out |
| L3 | `nhi_secondary_use: deny` | NHI-origin rows (claims, MediCloud) excluded |
| S0 (cascade) and list rendering | `contact: deny` | Never listed to a PI or CRC. Still in aggregates if `research_use` permits. |
| De-identification pipeline | `export_d2: deny` | Excluded from D2 releases beyond Z-TRE |
| Erasure request | — | Tombstone and purge (§5.14.4) |

An imported NHIA opt-out list, if one becomes available, is a `file_drop` source mapped to `nhi_secondary_use: deny` *(availability uncertain)*. A consent change takes effect at the next L3 run (nightly), or within one hour for `contact: deny` through an intraday update of the consent table.

### 7.14 PHI guard coverage gates

The PHI guard (`libs/tb_common/phi_guard.py`, about 100 surnames in v1) becomes a layered detector used at every outbound boundary. It is an independent tripwire: it runs whatever the class label says, and a hit blocks the call and raises an alert.

| Component | Coverage |
| --- | --- |
| Dictionaries | Every Taiwan surname in the Ministry of the Interior household-registration surname statistics; a given-name character model; for the Japan profile, at least the top 10,000 Japanese surnames *(est.)*; the hospital's staff directory |
| Patterns | Taiwan national ID `[A-Z][12]\d{8}` and ARC (old `[A-Z][A-D]\d{8}` and new `[A-Z][89]\d{8}`) with checksum validation; NHI card numbers; site MRN regex; phone (mobile and landline, with and without +886); addresses (縣/市/區/路/段/巷/弄/號 grammar); e-mail; dates of birth in Western, ROC and Japanese-era forms; Japanese My Number (12 digits with check digit) and insurance numbers for the Japan profile |
| Model | A small on-prem NER model for code-mixed zh-TW/en and ja text (§8), used as a fallback after the dictionaries and patterns |

| Boundary | Gate |
| --- | --- |
| Gateway → any model outside the perimeter (topology C) | Guard on every request; any hit blocks the request whatever its label |
| Teams, LINE, Hermes context, email bodies to sponsors | Guard on every message |
| Trace store and logs | Redaction before write |
| D2 text release | Full NER pipeline plus a sample of 200 records checked by a person |

**Test gate.** A 1,000-item de-identification test set (site-built under IRB, D2, code-mixed zh-TW/en, plus ja for the Japan profile; the JMIR 2024 code-mixed corpus serves as a pattern reference *(licence uncertain)*) MUST show recall ≥ 0.98 for names and for identifiers, overall and per language stratum, and precision ≥ 0.80 *(est.)*. The gate re-runs on every change to the guard, its dictionaries or its model (G5).

### 7.15 Cross-border analysis for topology C

Topology C sends D0, D1 and, by exception, D2-L prompts to an external model. Each route is approved at G5 with this analysis on file:

| Question | Basis | Rule |
| --- | --- | --- |
| Is the content personal data? | PDPA; APPI | D0/D1: no. D2-L: assessed in the release certificate. D2-K, D3, D4: yes, so the route is refused. |
| Where is it processed and stored? | PDPA Art. 21; EMR regulation Art. 8 (for EMR content); APPI Art. 28 (provision to a third party in a foreign country) | Prefer an in-country region with a processing-location guarantee. Some providers' Taiwan-region endpoints process model calls globally (the current provider table is in §8), so the route records the actual processing geography. |
| Is it de-linked? | HSRA Art. 4(3), Art. 19 | Only D2-L can be. Without an IRB finding of 去連結, research materials do not go abroad. |
| What does the provider keep? | Contract | Zero data retention or an approved abuse-monitoring exemption, no training use, deletion terms, sub-processor list, breach notice period — recorded in the route's evidence |
| Sponsor confidentiality (D1) | CDA or contract | Sponsor's written consent per protocol before protocol text goes to a cloud model |
| Japan | APPI; PPC guidance on cloud services *(uncertain applicability)* | 仮名加工情報 is never provided. 匿名加工情報 only after publication of its categories. |

Rollback of a cloud route (revert to on-prem only) is an operations procedure in §18.

### 7.16 Requirements

v3 PRIV-5, PRIV-6 and PRIV-9 are kept unchanged. The others are superseded as shown:

| v3 ID | Disposition |
| --- | --- |
| PRIV-1 (`pid = HMAC(site_key, MRN)`) | Superseded by PRIV-10 and DP-35 |
| PRIV-2 (rounding base 5, bands) | Superseded by PRIV-20 (threshold 11 externally; rounding and bands kept) |
| PRIV-3 (opt-outs at S0) | Superseded by PRIV-27 |
| PRIV-4 (no PHI to non-local models; PHI guard) | Superseded by PRIV-15, PRIV-29 and PRIV-30 |
| PRIV-7 (privacy accountant) | Superseded by PRIV-21 and PRIV-23 |
| PRIV-8 (site-level opt-out scope) | Superseded by PRIV-27 and DM-22 |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| PRIV-5 | Minimisation: T2 tools MUST return only the fields the calling step needs; prompts carry only retrieved chunks; exemplars are sentence-level with identifiers removed. (v3, unchanged) | T | MS1 |
| PRIV-6 | Retention defaults per record class: regulated study records and the audit trail for the longest of the sponsor requirement, TFDA GCP record rules and the EU CTR 25-year rule when the study is EU-regulated; intake text that is not a regulated record for 90 days with identifiers redacted at storage; lake snapshots per §5.18. Legal hold supported. (v3, unchanged except the cross-reference) | T | MS1 |
| PRIV-9 | Before any identifiable-patient run, an IRB approval or waiver (umbrella or per study) MUST be on file in the Study Card. The box refuses `SCREEN` without it. (v3, unchanged) | T | MS2 |
| PRIV-10 | Patient identity inside Z-PSN MUST be `pid = HMAC(K_pid, mpi_id)` with a random `mpi_id` and `K_pid` derived by HKDF from an HSM- or TPM-held root (§7.5). MRNs MUST appear only in `tb-vault`, L0 and encrypted attachments to delegated users. | T | MS0 |
| PRIV-11 | Project-scoped extracts MUST use `HMAC(K_proj, pid)` with per-project HKDF keys, so that datasets of different projects cannot be joined. Project keys MUST be destroyed at project end. | T | MS1 |
| PRIV-12 | Re-identification MUST go only through `tb-vault.resolve`, carrying purpose, approval id and requester, callable only from deterministic workflow steps after the authorising gate, and audited. No model or Hermes tool may reach it. | T | MS2 |
| PRIV-13 | Every dataset, column, prompt, tool result, message and file MUST carry a data class assigned at the source. Derived objects MUST take the highest input class. Classes MUST be lowered only by the transforms of §7.1, each writing its certificate. | T | MS0 |
| PRIV-14 | Special-category (`sc`) data MUST use a stricter small-cell threshold, a dedicated model pool, reduced trace retention and an extra DPO approval for D2 release. | T, I | MS2 |
| PRIV-15 | The boundary table of §7.2 MUST be enforced in code at `tb-gateway` and L5. D3 and D4 MUST NOT reach any external model in any topology, including through fallbacks, retries, caches or traces; the `egress` and `redteam` suites MUST prove it on every release. | T | MS0 |
| PRIV-16 | Topology B MUST store EMR-derived data only in a Taiwan region with a provider certified as EMR regulation Art. 8 requires, with customer-managed keys and no vendor access. | I | MS4 |
| PRIV-17 | Every D2 release MUST pass the de-identification pipeline of §7.6 and produce a `release_certificate` that names its variant (D2-K or D2-L), techniques, measured risk, context assessment and approvals. | T | MS1 |
| PRIV-18 | D2 releases MUST meet the risk thresholds of §7.6 (defaults: k ≥ 5 inside Z-TRE; k ≥ 11 and prosecutor risk ≤ 0.09 externally or on a topology C route) and l ≥ 2 on declared sensitive attributes, with longitudinal quasi-identifiers included. | T | MS1 |
| PRIV-19 | The spec, the validation pack and every D2-K certificate MUST state that keyed pseudonyms are personal data under PDPA, are not 去連結 under HSRA Art. 4(3), and are not HIPAA 164.514(c) re-identification codes. | I | MS1 |
| PRIV-20 | Aggregates released outside the research office MUST use the small-cell threshold (default 11, minimum 5), controlled rounding to base 5, per-investigator bands, and never free text from notes. | T | MS1 |
| PRIV-21 | Every table with margins MUST receive complementary suppression. An LP audit across this release and earlier releases to the same requester, snapshot and study MUST block any release in which a suppressed cell's feasible interval is narrower than the threshold. | T | MS1 |
| PRIV-22 | Machine-readable count APIs and federated answers MUST add geometric (or discrete Gaussian) noise from a cryptographic RNG with integer sampling, and MUST account ε per requester × project × period in the ledger. Human-reviewed reports MAY use suppression and rounding only. | T | MS5 |
| PRIV-23 | Every released aggregate MUST be recorded in the privacy ledger (§6.12) with mechanism, thresholds, suppressed cells, ε and the differencing result. | T | MS1 |
| PRIV-24 | Enrolment-list linkage to Z-TRE MUST go through the honest broker as in §7.10. TrialBox MUST NOT hold a research-ID ↔ MRN link. Bloom-filter linkage, if used, MUST run only inside the broker environment with hardening. | T, I | MS1 |
| PRIV-25 | Synthetic cohort twins MUST be generated only from D2 data or DP marginals, MUST pass the utility and privacy tests of §7.11, and MUST be labelled synthetic in every file and row. | T | MS4 |
| PRIV-26 | Z-TRE MUST implement the Five Safes controls of §7.12. Every access MUST be through an active project record. The Five Safes checklist MUST be stored with every D2 and aggregate release. | T, I | MS1 |
| PRIV-27 | Consent and opt-out MUST be applied per patient and per scope at the points of §7.13. `contact: deny` MUST take effect within one hour. Opt-outs MUST be applied before any candidate list is formed. | T | MS2 |
| PRIV-28 | The platform MUST be able to import an NHI secondary-use opt-out list as a `file_drop` source mapped to `nhi_secondary_use: deny`, without assuming that such a list exists. | T | MS2 |
| PRIV-29 | The PHI guard MUST have the coverage of §7.14 and run as an independent tripwire at every boundary listed there; a hit MUST block the call whatever its class label. | T | MS0 |
| PRIV-30 | The PHI guard MUST reach recall ≥ 0.98 for names and for identifiers, overall and per language stratum, on the 1,000-item code-mixed test set (plus ja for the Japan profile), re-run on every guard change through G5. | T | MS2 (zh-TW/en); MS6 (ja) |
| PRIV-31 | Free text MUST NOT be part of any D2 release unless the text de-identification pipeline has run, met PRIV-30, and passed a 200-record human check. | T | MS1 |
| PRIV-32 | Every topology C route MUST have the cross-border analysis of §7.15 on file before its G5 approval, including the actual processing geography and provider retention terms. | I | MS4 |
| PRIV-33 | The Japan profile MUST handle D3 as 仮名加工情報 (no third-party provision, no contact through the data, secured replacement keys) and MUST support operating with a certified creator or user under the Next-Generation Medical Infrastructure Act in the on-premises usage type. | I | MS6 |
| PRIV-34 | A breach involving D2–D4 data MUST trigger the SEC-14 workflow (§14), including notification to the competent authority and to data subjects as the amended PDPA (Art. 12) requires. | T (tabletop) | MS2 |
| PRIV-35 | Erasure requests MUST be executed per §5.14.4 and confirmed to the requester through the DPO, with the purge certificate as evidence. | T | MS2 |
