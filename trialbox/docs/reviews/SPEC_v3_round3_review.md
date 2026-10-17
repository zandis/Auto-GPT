# Adversarial review, round 3: `SPEC_v3.md` against the v4 requirements

Reviewer: adversarial review agent · 17 Oct 2026 · Inputs: `SPEC_v3.md` (3.0-rc1), the two earlier review reports, `docs/LANDSCAPE.md`, `SPEC.md` (v1), the v1 code, the TrialGPT port and its local copy of the NCBI criterion annotations, and the research notes behind the drafts. Severity: **B** blocker for v4, **M** major, **m** minor. Facts I could not verify are marked *(uncertain)*. Nothing in the repository was modified. Resolutions: `spec/v4/` Appendix I.

**Reading guide.** §1 is the verdict and the fifteen weaknesses. §2 gives findings and a v4 design per area (a)–(k). §3 ranks twenty innovations. §4 is the v4 table of contents with the requirements each section must carry.

---

## 1. Verdict

v3 is a defensible *pre-screening appliance* specification. It is not a specification for the product the owner now describes: a hybrid (on-prem-first, cloud-capable) clinical-trial agent with an industrial data platform, a governed LLM platform, a hardened Hermes front door, sponsor-grade deliverables and a rollout/rollback plan. Three of the nine binding constraints (C-2 "no cloud path", C-5 "no end-user UI", ADR-V3-07 "no Hermes") are now inverted by the owner, and about a third of the document (§4.1, §4.2, §4.3, §8.2, §10.2, §15.2 S1-0) is written to enforce them. v4 is a rewrite, not an amendment.

The deterministic core (IR → CQL/SQL with the equivalence gate, quote-verified judging, hash-chained audit, byte-identical re-runs, controlled rounding) remains the asset and must be carried over unchanged. Everything around it is thinner than it looks. The fifteen weaknesses, in order of damage:

1. **Criteria understanding cannot represent the protocols sponsors actually send (B).** IR v2 (§5.2) still lacks line of therapy (deferred to R3, FR-M7-12), measurable attributes without a registry feed (FR-M0-13, R2, computability 0 otherwise), value comparisons outside the observation domain (v1 `semantics.py:52–79`, not lifted anywhere in v3), relative anchoring to a *future* screening or randomisation date (windows anchor on `index | event` only), derived scores beyond the v1 fixed set (BMI, eGFR, DAS28), and the "adequate organ function" expansion family. Concept normalisation, the weakest step in every published system (C2Q entity normalisation 0.51; Lee et al. GPT-4 OMOP mapping 48.5 %), has no per-domain accuracy target; `criteria_extract` gates concept F1 ≥ 0.88 on five shipped gold rulesets, four of which are fictional (poc_status §3.10). There is no criterion library, so every protocol is extracted from scratch.
2. **The S2 note pre-filter is a silent, cost-free excluder (B).** §5.2 and CAS-11: zero approved-lexicon hits in the window ⇒ `fail` under `absence_of_evidence`. The lexicon is 93 synonym rows plus a paren-pattern miner (ML-5). A code-mixed abbreviation the miner has not seen excludes the patient with no model ever reading the note. The `S2-zero_hit(note)` stratum (SAFE-2) only *measures* this after the fact; nothing bounds the S2 miss rate before go-live and no suite tests lexicon recall against a judged sample.
3. **The recall certificate is statistically invalid under its own operating rule (B).** SAFE-2 accumulates samples month over month and SAFE-3 re-issues Clopper–Pearson bounds at fixed α each month. Fixed-sample intervals re-computed on an accumulating sample at every look are not valid at the stated confidence (optional stopping); demotion (SAFE-4) triggers on exactly these repeated looks. v4 needs anytime-valid confidence sequences (betting or Howard–Ramdas style) or pre-registered looks. The known-positive claim remains built on historical enrollees that the spec itself labels biased.
4. **Feasibility stops at counts (M).** FR-M3-1…12 deliver a funnel and sampled tier estimates, but the sponsor's question is "recruitable per month at this site". Attrition modelling (reachability, refusal, competing-trial allocation), the hierarchical forecast (R2), representativeness (FR-M2-4, R3) and site-performance metrics are deferred or absent. There is no deliverable standard: no figure set, no CONSORT-style attrition diagram, no machine-readable package before R3.
5. **Patient → trial matching is an afterthought (M).** M5 is R2/R3 and two lines long, although the TrialGPT port, the open cohorts, and the CGRD harness are the only parts of the codebase with a real-model result. A hospital agent that cannot answer "which trials fit this patient" at a tumour board is not best in class; Lind, Triomics and TrialGPT 2.0 all do it.
6. **Data management is one adapter, not a platform (B).** FR-M0-1 names three source kinds; the v1 adapter streams rows from SQL views, CSV or FHIR Bulk through a declarative mapping. There is no landing zone, no data contracts, no schema-drift detection, no reconciliation of row counts and sums, no quarantine, no handling of MRN merges, deletes or late-arriving records, no HL7 v2 feeds (needed for same-day appointments and ADT), no CDC, no OMOP core (ADR-V3-09 makes it an optional view in R3), no lineage model, and the quality checks (FR-M0-7) are seven rules rather than a framework (Kahn/OHDSI DQD). CGRD-type research databases and HIS replicas are treated as interchangeable although they differ in identity, freshness and lawful basis.
7. **Privacy is rounding plus HMAC (M).** PRIV-1…9 give pseudonymisation, rounding, a differencing check and opt-outs. There is no data-class model, no de-identification standard (HIPAA 164.514 Safe Harbor / Expert Determination, ISO 25237), no re-identification risk assessment for exports, no Five Safes / TRE separation between the de-identified evaluation zone and the identified screening zone, and no statement of what may cross which boundary, which the hybrid requirement now makes mandatory. The PHI guard is still ~100 surnames (poc_status §3.6).
8. **No LLM platform (B).** §4.2 rejects a gateway, a registry service, an observability store and a workflow engine. With cloud models under policy, shadow passes, OpenRouter bake-offs and multiple profiles, model governance becomes the control plane of the product. v3 has `models/registry.yaml` (never built in v1), `tb_common.llm` (one endpoint plus the cloud branch S1-0 was meant to delete) and `trialbox eval`. No routing policy, no per-call data-class check, no budget ledger, no model cards, no prompt registry, no red-team CI, no cost model.
9. **Hermes is excluded; it must now be included and made safe (B).** ADR-V3-07 and §4.2 remove it; the research note (`hermes_agents.md`) already gives the pattern: untrusted proposer behind an MCP boundary. v3 contains no channel abstraction, so adding Hermes means re-specifying L1/L2.
10. **"No end-user UI" produced a heavy UX, not a minimal one (M).** PIs are asked to learn a 25-command grammar (Appendix D), return locked XLSX sheets, and open one PDF per strong candidate. Teams and LINE carry nothing (FR-UX-6). The owner now wants *minimal* UI with *strong* admin control: a different design point. The admin console (§3.6) is a health page, not a control plane.
11. **Cybersecurity is a list, not an allocation (M).** SEC-1…14 and §10.3 are sound for a sealed box. There is no per-component control allocation, no identity architecture beyond mailboxes and local TOTP, no key-management design, no SIEM/SOC integration contract, no secure-SDLC statement, no threat model for cloud or Hermes, no MITRE ATLAS coverage, no backup immutability, no vulnerability-disclosure process.
12. **Pharma deliverables are not specified (M).** Sponsors receive "a feasibility packet" and a filled questionnaire. No report standard, no figure specification, no site-metrics vocabulary (TransCelerate/Site Profile, ASCO/AACI), no accrual reporting during conduct, no diversity/representativeness section, no machine-readable exchange before R3.
13. **Lifecycle coverage is wide and shallow where coordinators spend time (M).** Appendix A says ● for everything, but screening-visit eligibility checklists, IP accountability prompts, lab-kit and sample logistics, participant payments, retention, RBQM key risk indicators, TMF/ISF document completeness, DSMB support, investigator-initiated-trial protocol drafting, IRB e-submission and sponsor-query SLAs are absent or one line.
14. **Testing and calibration depend on data that does not exist yet (M).** Every quality gate in §8.5 and §11.3 needs site notes, CRC adjudication or CTMS enrolment lists. There is no open-data strategy, no public-benchmark CI, no multilingual bake-off, and no plan for pre-training the nonconformity model before site data arrives. The 1,015 expert criterion annotations are sitting unused in the sibling repo.
15. **The plan is a sprint plus five release names (M).** §15 has no milestones with go/no-go criteria, no WBS, no RACI, no environments (dev/test/validation/production), no rollback plan at all (§13 says "rollback in ≤ 30 min" without a procedure), no site-wave rollout, no training or hypercare, no risk register.

Carried-over defects from round 2 that remain open in rc1: the example certificate in §5.6 still mixes "recall ≥ 95 %" with a biased population in the same sentence (N-05.5 only partly fixed); the pass table (§4.5) and NFR-5 (ingest of 3M patients ≤ 4 h) do not fit the 19:00–21:00 ingest window; CAS-10 is numbered after CAS-11.

---

## 2. Findings and v4 designs by area

### (a) Core functions

| ID | Sev | Finding |
| --- | --- | --- |
| R3-01 | B | IR expressiveness (weakness 1). Literature: only 51 % of inclusion criteria are fully implementable in OHDSI ATLAS; the v1 IR is narrower than ATLAS. |
| R3-02 | B | S2 zero-hit exclusion (weakness 2). No pre-deployment bound on lexicon recall. |
| R3-03 | B | Certificate under optional stopping (weakness 3). |
| R3-04 | M | Two-model extraction (FR-M1-2) reconciles J and V but neither is anchored to a criterion library; agreement is measured, correctness is not. |
| R3-05 | M | CAS-3 orders criteria by `exclusion_power / expected_tokens` with prior 0.5; with the cache keyed on `chunk_set_hash` (CAS-5), any new note invalidates every cached judgement for the patient, so the cache hit target "> 80 % after 4 weeks" (D2) is unsupported for inpatients and oncology clinics that write daily. |
| R3-06 | M | Tiers are deterministic but the `potential` tier mixes "unknown because data missing" with "abstained because model unsure"; the CRC cannot triage them differently (FR-M4-10 only partly). |
| R3-07 | M | M5 thin; the TrialGPT port's retrieval (BM25 + MedCPT, recall@500 0.93 on SIGIR) and aggregation scoring are not reused. |
| R3-08 | m | The quote verifier accepts a quote in one chunk; criteria that need two facts (drug *and* date) have no multi-span evidence model. |

**v4 design — what makes the core clearly superior.**

*Criteria understanding.* Define **IR v3** as a superset with: `line_of_therapy` (regimen model: drug-class sets, cycle/gap rules, progression events from pathology/radiology report spans and registry fields), `attribute` on any domain with a `source_priority` list (registry → structured pathology → report span → note), `derived` atoms with a versioned calculator library (CKD-EPI 2021, Child-Pugh, ECOG from notes, NYHA, RECIST status), `anchor: screening | randomization | event | index` with the screening date supplied at run time, `organ_function` macro expanding to a sponsor-standard lab panel (the ELaPro 55-lab core set as seed), and `human` criteria with a structured "what the investigator must check" field. Ship a **criterion library**: every approved criterion (canonical hash, IR, ValueSets, lexicon keys, note question, computability history, precision history) is stored once and proposed to the extractor as a candidate; the extractor's first job becomes "match to library, else draft". Seed the library from the Chia corpus (12,409 criteria, 1,000 trials) and ClinicalTrials.gov eligibility text, so the J/V agreement check (FR-M1-2) is replaced by "agreement with library + gold". Target: on the Chia-derived gold set, criterion-level structure F1 ≥ 0.85 and concept-normalisation accuracy per domain ≥ 0.80 (drug), ≥ 0.70 (condition), ≥ 0.65 (measurement), reported separately. Normalisation uses retrieval over loaded terminologies plus a cross-encoder reranker, never model memory (FR-M1-3 kept).

*Cascade.* Keep S0–S5. Change S2 to **"pre-filter, never exclude"** by default: zero hits route the pair to a cheap **S2b lexical-semantic screen** (bge-m3 similarity of the criterion question against sentence embeddings of the window, threshold calibrated per criterion type with LTT) before any `fail`; only criteria whose lexicon recall on a judged sample is ≥ 0.98 (measured in a new `lexicon_recall` suite, 200 judged pairs per criterion type and language stratum) may use zero-hit exclusion. Replace the chunk-set cache key with a **sentence-set key**: cache per (pid, canonical_hash, evidence_sentence_hashes); a new note only re-judges if it adds sentences that hit the criterion's lexicon or S2b screen. Split `potential` into `potential:data_gap` (what is missing and when it expires) and `potential:uncertain` (model abstained; quotes shown). Add multi-span evidence: a judgement may cite ≤ 3 spans across chunks, each verified.

*Matching (both directions).* One **matching engine** with two entry points: trial → population (cascade) and patient → trials (`MATCH`, tumour board). Patient → trial reuses the cascade's compiled rulesets for open studies and the TrialGPT retrieval + criterion-level judgement for registry trials, with the same judge prompt, cache and evidence schema. The TrialGPT port's `core.py/retrieval.py` become `services/matching/registry_match/`. Bring M5 to R1b (open studies) and R2 (registry).

*Feasibility.* A funnel is necessary but not the deliverable. v4 computes a **recruitability model**: eligible pool → reachable (alive, active in the last 12 months, local follow-up, next appointment within the enrolment window) → approachable (opt-outs, competing-trial allocation by PI) → consent (site prior) → screen pass (site prior), with the hierarchical Beta-Binomial in R1a, not R2, seeded with published priors until the site has history. Every estimate is stored with its later actual in a **forecast ledger** scored at close (Brier/CRPS), and the packet shows the site's own calibration plot once ≥ 5 studies closed.

*Recall certificate.* Keep the ledger, strata and importance weighting. Replace fixed-α Clopper–Pearson under accumulation with **anytime-valid confidence sequences** for each stratum's elusion rate (binomial betting CS, with the Horvitz–Thompson weights), so the bound printed on any day is valid regardless of how many months have been looked at; demotion (SAFE-4) uses the same sequence. Keep Bonferroni across strata or use the sequence's union bound. The known-positive population gets two lines on every certificate: historical enrollees (biased, labelled) and **blinded chart-review positives** (unbiased, cumulative, r reported). `recall_cert` suite: planted misses, monthly looks for 12 simulated months, coverage ≥ 95 % *over the whole sequence*.

### (b) Data management and data flows

| ID | Sev | Finding |
| --- | --- | --- |
| R3-09 | B | No pipeline stages, controls or lineage model (weakness 6). The adapter writes NDJSON and a DuckDB lake in one step (`adapter/pipeline.py`); a bad mapping or a truncated export becomes the snapshot unless one of seven quality rules fires. |
| R3-10 | B | No reconciliation: nothing compares source row counts, distinct MRNs, max dates and checksums with what landed; a silent 30 % drop in the LAB view produces a published snapshot and wrong feasibility counts. |
| R3-11 | M | MRN merges, patient deletions (PDPA erasure), record corrections and late-arriving results are unhandled; the pid is `HMAC(site_key, MRN)` so a merged MRN splits one patient into two forever. |
| R3-12 | M | No HL7 v2 or CDC path; same-day appointments (SIU) and admissions (ADT) arrive a day late via views, which breaks clinic-day lists (FR-M4-2) and hospital-flagged events (FR-M7-8). |
| R3-13 | M | OMOP as an optional R3 view (ADR-V3-09) blocks OHDSI DQD, Achilles, ATLAS cohort reuse, TNet/TACTC federation and OMOP-based open benchmarks. |
| R3-14 | M | CGRD-style research databases are de-identified at source, have no appointments and sit under a different IRB regime; v3 treats them as "a source" (OD-1) without a zone model. |
| R3-15 | m | Terminology versioning: FR-M0-8 loads editions, but there is no terminology *service* (FHIR `$validate-code`, `$translate`), so the HL7 validator runs without bindings (v1 D-26/D-64). |

**v4 design — the data platform.**

Zones and stages (every stage has an owner, an input contract, an output contract, controls and a lineage event):

```
 S0 Landing     raw, immutable, per source × batch; manifest {source, extract_time, rows, bytes, sha256, schema_fingerprint}
 S1 Validation  data contract (schema, types, keys, nullability, enumerations), referential integrity, reconciliation vs
                source control totals, DQ rules (Kahn: conformance / completeness / plausibility; OHDSI DQD categories),
                drift detection (schema and distribution); quarantine with reason codes; steward email; no partial publish
 S2 Standardise canonical model → FHIR R4 (TW Core 1.0.0 / JP Core) and OMOP CDM 5.4 side by side; terminology
                normalisation through a terminology service (ICD-10-CM TW 2014/2023 + map, NHI drug/ATC, LOINC-TW, local lab
                → LOINC, SNOMED where licensed); UCUM units; ROC/era dates (ML-3); canonical text (§5.3); NDJSON per resource
 S3 Pseudonymise identity vault (MRN, name, national id, phone, DOB) separated; pid = HMAC(site_key, MPI_id) with an MRN→MPI
                merge table; optional date shifting and generalisation for the de-identified zone; ISO 25237 roles
 S4 Curated lake immutable snapshot T (DuckDB/Parquet, partitioned by domain × year; FHIR store; OMOP schema; FTS and
                embedding indexes; `condition_attribute`; appointments; claims); snapshot manifest with lineage graph
 S5 Serving     T0/T1/T2 tools (§5.12) over snapshot T; judgement cache; feature store for calibration; aggregate
                serving through the privacy accountant; OMOP read-only endpoint for OHDSI tools; FHIR read API for CDS
```

Per-source streams:

| Source | Transport | Cadence | Identity | Zone | Notes |
| --- | --- | --- | --- | --- | --- |
| HIS DB views (Oracle/MSSQL/Postgres/Db2) | read-only account, DBA views, `delta` columns; optional **CDC** (Debezium-class log reader into a Kafka-compatible queue or plain change tables) for appointments, encounters, labs | nightly full-delta + intra-day CDC micro-batches | MRN → MPI | identified → pseudonymised | v1 `cgrd_sql` source kept; add control-total query per view (`count(*)`, `max(delta)`, `count(distinct mrn)`) |
| CGRD-style research DB | SQL/CSV export, de-identified at source | quarterly or per approval | research id; honest-broker link table held by the broker, never by the box | de-identified (TRE) | feasibility, validation replay, evaluation sets; **never** pre-screening lists |
| FHIR server | **Bulk Data Access** `$export` (system, group, patient) with `_since` and `_typeFilter`; **SMART Backend Services** (client_credentials + private_key_jwt, scopes `system/*.rs`); `$everything` for `FULLREVIEW` | nightly incremental | FHIR `Patient.identifier` | pseudonymised | TW Core profile validation with a terminology server; NDJSON lands as-is in S0 |
| HL7 v2 feeds | MLLP listener (TLS); ADT A01/A04/A08/A40 (merge), SIU S12–S15 (scheduling), ORU R01 (results), MDM T02 (documents); dedupe on MSH-10; ACK | real time | PID-3 | identified → pseudonymised | drives clinic-day lists and hospital-flagged events same day; A40 feeds the MPI merge table |
| CSV / registry (cancer registry 癌登 with SSF, consent registry, CTMS exports, training records) | SFTP drop with `.sha256` sidecar and schema contract | per publication | MRN or research id | per file class | contract violation ⇒ quarantine; registry feeds `condition_attribute` |
| Cohort / alliance data | signed COHORT tables (v1), OMOP aggregate exports | quarterly | none (aggregates) | aggregate | Five Safes applied at the alliance root |
| NHI MediCloud (optional, FR-M0-12) | per-patient query | on care events only | MRN | identified | provenance `nhi_cloud`; legal basis gate kept |

Controls per stage: S0 immutability and retention (raw 90 days, then delete unless legal hold); S1 **publish gate** (any blocking rule, or reconciliation delta > 0.5 % on any control total, blocks the snapshot and emails the steward with the diff; previous snapshot stays current); S2 terminology coverage report (share of codes resolved, per domain) and unit-normalisation report; S3 vault access only through the pid service, every lookup audited with purpose; S4 snapshot signature and manifest; S5 row-level scoping by study and delegation, query guard (v1 `sqlguard`), accountant.

Lineage: emit **OpenLineage** events for every stage run (job, inputs, outputs, facets with row counts and schema), store them in Postgres, and write FHIR `Provenance` for every derived resource and every evidence item; every packet carries a lineage id that resolves to the full graph (source batch → snapshot → ruleset → run → file). Quality: a **data-quality scorecard** per snapshot (DQD-style, per domain, with trend) in the Atlas workbook and the monthly QA pack. Data catalog: the Atlas becomes the catalog (tables, columns, coverage, freshness, owners, contracts); exported as a DCAT/OpenMetadata JSON for the hospital's catalog *(optional)*.

Identity lifecycle: MPI merge table; erasure requests (PDPA) remove vault rows and tombstone the pid; corrections re-run the dirty set (CAS-6); late-arriving records re-open the window evaluation for the affected pairs.

Standards named normatively in v4: FHIR R4 4.0.1, TW Core 1.0.0, JP Core, Bulk Data Access 2.0.0, SMART App Launch 2.x Backend Services, HL7 v2.5.1 messages above, IHE PIX/PDQ semantics for MPI *(use the semantics, not necessarily the actors)*, OMOP CDM 5.4 + OHDSI DQD + Achilles, CDISC ODM v2.0 / Dataset-JSON / CDASH / SDTM-TI / USDM 4.x, ICH M11, Vulcan SoA and RWD IGs, mCODE for oncology, UCUM, LOINC, ICD-10-CM TW editions, ATC, NHI code systems, OpenLineage 2.x, ISO 25237, ISO 8000-61 (data quality process) *(reference only)*.

### (c) Privacy architecture

| ID | Sev | Finding |
| --- | --- | --- |
| R3-16 | B | No data-class model and no boundary rules; "hybrid" cannot be specified without them. |
| R3-17 | M | De-identification is undefined: FR-M8-7 promises "a de-identified dataset" and §11.4 uses "de-identified research database" with no standard, no risk threshold, no expert determination. |
| R3-18 | M | PHI guard coverage (≈ 100 surnames; no given names; no address or employer patterns) makes PRIV-4 unenforceable on outbound text. |
| R3-19 | m | Opt-out semantics (PRIV-8) are a site flag; no patient-level consent model (FHIR `Consent`), no dynamic research-use permission, no NHI opt-out import. |

**v4 design.** Define five data classes and bind every tool, prompt, model route and channel to a class:

| Class | Content | On-prem | Hospital cloud tenant (in-country, hospital-controlled keys) | Vendor cloud LLM (zero-retention, DPA) | Public cloud (OpenRouter, bake-offs) |
| --- | --- | --- | --- | --- | --- |
| D0 public | registry records, public benchmarks, open data | ✓ | ✓ | ✓ | ✓ |
| D1 confidential, no PHI | protocol text, sponsor questionnaires, site profile, lexicon, prompts | ✓ | ✓ | policy: only with the sponsor's written consent per protocol (default off) | ✗ |
| D2 de-identified patient-level | expert-determined or Safe-Harbor sets, synthetic twins, evaluation sets | ✓ | ✓ (TRE controls) | policy: only with a documented re-identification risk ≤ threshold, PDPA Art. 21 cross-border analysis, and IRB/DPO sign-off (default off) | ✗ |
| D3 pseudonymised patient-level | lake, evidence, judgements, candidate lists | ✓ | ✓ only if the tenant is attested as the hospital's own perimeter (same controls as on-prem; confidential-computing attestation where offered) | ✗ | ✗ |
| D4 identified | vault, MRNs, names, attachments to PIs | ✓ | ✗ unless the HIS itself lives there | ✗ | ✗ |

Three deployment topologies, all from one image set: **A on-prem appliance** (default); **B hospital cloud tenant** (the whole appliance in the hospital's own Taiwan-region tenant: private networking, customer-managed keys in KMS/HSM, no vendor access; D3 allowed, D4 vault stays on-prem or in HSM-backed storage); **C hybrid** (A or B plus an outbound **model egress policy** that lets D0/D1/D2 prompts reach approved cloud models through the gateway, with per-call class checks, redaction, logging and budget). Topology C is where "cloud LLMs under policy" live; PHI (D3/D4) never leaves the perimeter in any topology.

Privacy-enhancing technologies, each with a named use: de-identification pipeline (Safe Harbor rules + Presidio-class NER with Taiwan recognisers + expert-determination report template, ISO 25237 roles); k-anonymity/l-diversity check on any D2 export; differential privacy (geometric noise, ε ledger) for machine and federated answers (kept from FR-M11-3); **PPRL** (Bloom-filter or hashed-token linkage through the honest broker) for enrolment-list ↔ research-db linkage (§11.4); **synthetic cohort twins** (Synthea-style generator fitted to the site's marginals) for sponsor previews and cloud evaluation; federated analytics for the alliance; confidential computing attestation for topology B/C *(availability per cloud, uncertain)*. Five Safes applied as a checklist for every D2 release (safe projects, people, settings, data, outputs) and the TRE pattern for the evaluation zone: separate database role, no outbound, output review by the steward.

Consent: ingest FHIR `Consent` (or the registry CSV) per patient with scopes `research_use`, `contact`, `nhi_secondary_use`; S0 reads scopes, not a site flag.

PHI guard: ship ≥ 5,000 surnames, a given-name dictionary, national id/ARC/passport/phone/address/employer patterns, and a classifier fallback; measure on a 1,000-item de-identification test set (the JMIR code-mixed corpus as a pattern reference *(licensing uncertain)*); gate recall ≥ 0.98 for names and ids.

### (d) LLM platform

| ID | Sev | Finding |
| --- | --- | --- |
| R3-20 | B | No gateway, registry service, routing policy or budget ledger (weakness 8). |
| R3-21 | M | `tb_common/llm.py` still routes `model_class: cloud` to `CLOUD_LLM_BASE_URL` with a PHI guard; under the new requirement this becomes the seed of the gateway, but as written it has no policy table, no audit of the *class* of data sent, no retries/fallbacks, and no cost. |
| R3-22 | M | MOD-4 fixes temperature 0 and seed but the spec admits vLLM batching is not bit-exact; reproducibility (NFR-9) must rest on recorded outputs, which §7.0 gives for steps but not for cache entries re-used across runs. |
| R3-23 | M | No guardrail classifiers (injection, policy, PHI) despite the research note; `redteam` is a suite, not a runtime control. |
| R3-24 | m | §4.2 rejects Langfuse; §9 NFR-15 sends OTel to files; nobody can inspect a prompt trace for a disputed judgement without grepping files. |

**v4 design.** An **LLM control plane** of four services, all on the box (or in the tenant):

1. **Gateway** (`tb-gateway`, an OpenAI-compatible proxy; LiteLLM is acceptable as the engine, or ~2k lines in-house): every model call from every component passes through it. It enforces: caller identity (mTLS service + workflow step id), the prompt's declared **data class** (D0–D4) and the route's allowed classes, model alias → pinned build (SHA), structured-output enforcement, redaction of D4 patterns, token and cost budgets per study/workflow/month, fallbacks (on-prem J → on-prem V → cloud, only where class permits), caching keyed by (prompt sha, model sha), and an audit record (prompt sha, model sha, class, tokens, latency, cost, purpose). Egress rules allow only the gateway to reach any model endpoint, on-prem or cloud.
2. **Registry** (`models/registry.yaml` promoted to a Postgres-backed service with a CLI): per build: SHA-256, repo revision, quantisation, licence manifest (MOD-2), origin (MOD-1), **model card** (contexts of use, eval reports, known failure modes, languages, max context), approved roles × profiles × data classes, status (candidate / shadow / champion / retired), and the G5 record that approved it. Prompts and exemplar banks are registered the same way (versioned, hashed, evaluated).
3. **Routing policy** (table, property-tested, like §10.1): `(role, data_class, profile, topology, site flags) → ordered list of builds`. Examples: `judge, D3, P-GB10, A → [J-on-prem]`; `extract_criteria, D1, any, C → [V-on-prem, cloud-X if sponsor consent]`; `classify_intent, D1 → [J-on-prem]`; `bakeoff, D0, dev → [openrouter/*]`. The admin edits it in Git; changes are G5.
4. **Evaluation and observability**: `trialbox eval` extended with public suites (§2(j)), a nightly shadow run (AI-14), drift monitors (ML-11) and a self-hosted trace store (Langfuse or Phoenix, PHI-redacted, 90-day retention, separate from the audit ledger). Prometheus metrics per role: items/hour, abstention rate, schema-violation rate, cost per candidate.

Guardrails at the gateway: inbound injection classifier and policy classifier on untrusted text (D1 documents, email bodies), schema validation and `numbers_match` outbound, citation verifier (offsets), refusal on class mismatch. Cost model: per-call cost = tokens × (cloud price or on-prem amortised GPU-second × measured tok/s); monthly cost report per study and per module; NFR-16 becomes a budget with alerts.

How LLM functions link to modules (the registry's role table):

| Role | Module(s) | Data class | Default route (topology A) | Hybrid option (C) |
| --- | --- | --- | --- | --- |
| `classify_intent` | intake / Hermes | D1 | J on-prem | none |
| `extract_criteria`, `concept_select`, `answer_protocol` | M1 | D1 | J day, V night | cloud frontier with sponsor consent |
| `propose_mapping` | M0 | D1 (schema only) | J | cloud allowed |
| `judge`, `second_opinion`, `abstract_field`, `draft_query_answer` | M4, M5, M8, SAFE | D3 | J / V on-prem only | never |
| `map_questionnaire`, `draft_narrative`, IRB/CTA drafting | M3, M7, M9 | D1 / aggregates | J | cloud allowed |
| guard classifiers, embeddings, reranker | all | D1–D3 | small on-prem | never for D3 |
| `bakeoff`, prompt optimisation | eval | D0/D2 | OpenRouter | yes, by policy |

### (e) Hermes Agent: role and hardening

| ID | Sev | Finding |
| --- | --- | --- |
| R3-25 | B | No channel abstraction in v3; intake is a module inside the orchestrator (§4.2). Hermes cannot be slotted in without re-cutting L1/L2. |
| R3-26 | M | Hermes' own email allowlist, approvals and memory would duplicate and conflict with SEC-4, FR-SIG-* and PRIV-6 unless explicitly subordinated. |

**Where Hermes adds value.** (1) The multi-channel **front door**: email, Teams, LINE and a CLI/TUI for admins, with one persona and one conversation model, replacing the v3 "proposal by email only" loop with real multi-turn clarification (FR-AG-2's one round becomes a conversation). (2) **Staff concierge**: `STATUS`, `HELP`, protocol Q&A (`ASK`), "what is due this week", drafting replies to sponsors, all over T0/T1 tools. (3) **Research-office analyst**: natural-language questions over *aggregate* study data (T1, accountant-checked). (4) **Admin copilot**: reads health, queues, bench and eval reports and drafts runbook actions, executing none. (5) **Offline optimisation**: Hermes' self-evolution tooling (DSPy/GEPA) runs *offline* on evaluation sets to propose prompt and skill changes that enter through G5. Hermes does **not** hold PHI tools, schedules, gates or writes.

**Hardening (normative for v4).**
- Pinned, vendored release (tag + SHA); SCA/SAST on every upgrade; upgrades are G5 changes; a thin in-house gateway implements the same channel interface so the product passes all tests with Hermes disabled (`channels.engine: hermes | native`).
- Toolsets: everything disabled except the **TrialBox MCP front-door server** (`tb.submit_request`, `tb.status`, `tb.help`, `tb.ask_protocol`, `tb.registry.search`, `tb.atlas.describe`, `tb.aggregate.query` (T1, accountant), `tb.fetch_released_file`). No terminal, file, browser, web, code execution, delegate, skill-write or memory-write tools. `approvals.mode: manual`, `cron_mode/unattended_mode: deny`, MCP sampling and elicitation off, `security.allow_private_urls: false`, no cloud sandboxes, YOLO checked for in CI.
- **MCP tool boundary**: tools run in the orchestrator's policy context: caller identity from the channel's authenticated sender (DMARC for email, Entra identity for Teams, LINE only for nudges), delegation, purpose, class. Every call writes the audit event before returning. T2/T3 tools are not exposed on the front-door server at all.
- **Approvals**: Hermes never approves. Level A replies and Level B signing stay with the orchestrator; Hermes may *deliver* the gate email/card and *relay* a reply verbatim to intake, which parses it deterministically. A `pre_tool_call` plugin calls the policy module and fails closed.
- **Memory and skills governance**: `memory_enabled: false` by default; if enabled, `MEMORY.md`/`USER.md` hold staff preferences only with `write_approval: true`; no external memory providers; `state.db` on the encrypted volume with 30-day retention and PHI redaction at write (inbound bodies may carry MRNs, FR-UX-2). Skills are signed `SKILL.md` files from the product Git repo (`skills.write_approval: true`, `project_discovery: false`, hub installs disabled); agent-proposed skills become PRs through G5.
- **Prompt-injection posture**: Hermes sees only stripped sender text (SEC-9) and attachments are converted by the isolated CDR container; untrusted content enters prompts inside delimited blocks; a quarantined extractor with no tools summarises external documents (CaMeL pattern); the `redteam` suite runs against the Hermes front door in CI with zero capability-bearing successes.
- Observability: Hermes traces go to the same redacted trace store; a `hermes` dashboard panel shows sessions, tool calls, denials.

### (f) UX per role with minimal UI

| ID | Sev | Finding |
| --- | --- | --- |
| R3-27 | M | Grammar burden on PIs (Appendix D, 25 commands); decision sheets require Excel discipline; one PDF per strong candidate is heavy for a 20-candidate clinic day. |
| R3-28 | M | Teams/LINE carry nothing actionable (FR-UX-6) although Taiwanese teams live in LINE and Teams; the owner now allows minimal UI. |
| R3-29 | M | The admin console is read-only health; "strong admin control" needs policy editing, kill switches, approvals and simulations. |
| R3-30 | m | No accessibility, mobile or localisation acceptance beyond ML-9. |

**v4 design — one surface per role, nothing more.**

| Role | Primary surface | Minimal UI allowed | Never |
| --- | --- | --- | --- |
| PI / Sub-I | Weekly packet email (one XLSX, one consolidated evidence PDF with bookmarks); replies in plain words to Hermes, which proposes `CONFIRM/REJECT` lines; Teams adaptive card "3 candidates waiting" (no PHI) | **Signing page** (Level B); optional **CDS Hooks card** in the EHR patient view ("possible trial match, see packet", R3, opt-in per site) | portal, dashboards |
| CRC | Hermes conversation (email or Teams) for requests, status, five-minute reviews; decision sheets | signing page; one **review page** reachable from the packet that renders the same decision sheet with evidence inline and writes back through the same hash-bound approval (replaces Excel discipline; R2, optional per site) | EDC upload, patient contact |
| Research office | Monthly portfolio report; Hermes analyst over aggregates; G2 by reply | none | PHI |
| Data steward | Atlas workbook round trip; DQ scorecard email | none | PHI |
| IRB / QA | Monthly QA pack; audit export on request | read-only audit search page on the admin listener *(optional)* | — |
| Sponsor / CRA | PDF/XLSX/JSON by email from a named site person; monitor-visit pack | none | any link into the box |
| Administrator | **Admin console** (control plane): health, schedules, passes, bench/eval, registry and routing policy (read + propose change → G5), feature flags and per-module kill switches, channel settings (Hermes on/off, Teams/LINE), egress policy, delegation log import, approvals queue view (no content), audit integrity, backups, DR drill button; everything also as `trialbox` CLI | — | PHI |

Rules: every message passes FR-UX-1 (what, action, deadline); every action is expressible both as a grammar line and as plain language to Hermes; a message that needs no action is not sent; ja/zh-TW/en per ML-9; WCAG 2.2 AA for the three pages; mobile-readable emails (Noto CJK, ≤ 600 px tables).

### (g) Cybersecurity across components

| ID | Sev | Finding |
| --- | --- | --- |
| R3-31 | B | No control allocation per component and no threat model for Hermes, cloud topology or supply chain of models beyond SHA pinning. |
| R3-32 | M | Identity: mailboxes + local TOTP; no IdP integration except Level B2; no privileged-access management; the `/jobs` API has no auth (poc_status §5.2). |
| R3-33 | M | Keys: `site_key`, pid-map key, signing key, TOTP seeds "in the key class of the pid map" (SEC-7) with no KMS/HSM, rotation or escrow design. |
| R3-34 | M | Backups are not immutable; ransomware on the box takes the audit ledger and its "anchor" on the file share with it (§10.5). |
| R3-35 | m | No SIEM contract, no vulnerability disclosure policy, no patch SLA for the OS and drivers (D-79 pin), no DLP on outbound attachments. |

**v4 design — allocation table (excerpt; the full table is a v4 appendix).**

| Component | Controls |
| --- | --- |
| Host | LUKS2 + TPM sealing, Secure Boot, swap off, CIS benchmark, EDR agent if the hospital mandates, patch SLA (critical ≤ 14 d), driver pin checked by `doctor` |
| Network | deny-by-default egress per container; management VLAN; mTLS between services; hospital firewall rules documented; topology B/C: private endpoints, no public IPs, egress through the gateway only |
| Identity | hospital IdP (Entra/AD) for admins and signers (OIDC, phishing-resistant MFA), local break-glass accounts sealed; delegation log is the authorisation source; quarterly access recertification; service identities = mTLS certs from an internal CA |
| Keys and secrets | KMS/HSM where the hospital has one, else a sealed software vault with TPM-bound unseal; key hierarchy (site key, vault key, signing key, channel secrets); rotation schedule; dual-control for the site key; escrow documented |
| Mail gateway | SPF/DKIM/DMARC with pinned authserv-id; allowlists; rate limits; CDR container for attachments (no network); ClamAV; outbound DLP (PHI guard + class check) on bodies and attachments; S/MIME or 7z |
| Hermes | §2(e) hardening; separate container, read-only filesystem, no network except the MCP server and the mail/Teams endpoints; its state on the encrypted volume |
| Gateway / models | class policy; model files read-only, SHA verified at load; vLLM with no remote code; cloud routes with private DNS, pinned TLS, short-lived credentials, zero-retention terms recorded |
| Lake / stores | row-level scoping, SELECT-only guard, Postgres roles (INSERT-only audit), encryption at rest, no direct admin SQL on PHI without a ticketed purpose |
| Signing page / console | OWASP ASVS 5.0 L2, CSP, no third-party JS, WebAuthn, session hardening, FR-SIG-4 negative tests, logging |
| CI/CD and supply chain | SLSA L3 provenance, signed images and bundles (Ed25519 vendor key in HSM), SBOM + ML-BOM + VEX, dependency pinning, secret scanning, model-weight hash manifests, reproducible builds *(target)* |
| Backups | 3-2-1 with one **immutable** copy (object lock in the tenant, or WORM/offline disk on-prem), encrypted, quarterly restore test; ledger anchor also sent to an external immutable store (email to QA + hospital WORM share) |
| Monitoring | Prometheus + alert rules; syslog/CEF to the hospital SIEM; egress-drop alarms; audit-anomaly rules; Hermes denial rate |
| Process | secure SDLC (threat modelling per release, code review, SAST/DAST), yearly pen test incl. LLM red team (MITRE ATLAS techniques), vulnerability disclosure policy, incident response runbook (SEC-14) with tabletop, DR plan (RPO 24 h / RTO 1 day on-prem; RPO 1 h in topology B) |

Threat model additions: Hermes compromise (goal: exfiltrate PHI → impossible by construction: no PHI tools; verify by test), cloud model prompt leakage (class policy + redaction + contract), model supply chain (poisoned weights → eval regression gate + SHA), insider admin (no PHI in console, ticketed SQL, dual control on keys), ransomware (immutable backup), sponsor document injection (CDR + quarantined extractor), differencing (accountant).

### (h) Pharma analysis and report deliverables

| ID | Sev | Finding |
| --- | --- | --- |
| R3-36 | M | No report standard, figure specification or metrics vocabulary (weakness 12). |
| R3-37 | M | No during-conduct deliverables (accrual, screen-fail analysis, site metrics) although M6/M9 compute the data. |
| R3-38 | m | Sponsor exchange formats (FR-M3-12) are "JSON"; sponsors' tools read ODM/Dataset-JSON, USDM, FHIR `Group`/`EvidenceVariable`. |

**v4 design — the sponsor deliverable set.** Four packs, each with fixed sections, figures, formats and provenance.

1. **Feasibility pack** (per protocol, after G2): executive summary (one page: eligible pool band, projected enrolment p10/p50/p90 over 12 months, start-up timeline, top three risks); site profile (SIP fields, PI experience, staffing, equipment, IRB/CTA timelines); **attrition waterfall** (CONSORT-style: population → each criterion in protocol order → eligible, with per-criterion computability and data completeness); prevalence and incidence (monthly new index-condition patients over 24 months, with seasonality); eligible pool by department and investigator (bands); **recruitability model** and projection with assumptions and the site's calibration record; competing trials and allocation; standard of care and NHI reimbursement context (comparator coverage, biomarker testing availability and turnaround); representativeness (age bands, sex, comorbidity burden, language, versus the condition population; aligned with FDA diversity action plan headings); criterion-impact and relaxation panel (drop-one gain, safety-proxy change, Pathfinder-style, safety-critical locked); data and methods (data cut, snapshot id, ruleset version and hash, cascade metrics, recall certificate statement, AI disclosure, privacy mechanism); appendix (ValueSets, hidden CQL/SQL hashes, glossary zh/en).
   Figures: waterfall bar chart; funnel; incidence line with 12-month moving average; cumulative enrolment fan chart (p10–p90); tornado chart for criterion impact; department × month heatmap; representativeness dumbbell plot. Formats: PDF/A (sponsor language), XLSX (every table), PPTX summary slide *(optional)*, machine-readable: FHIR `Group` + `EvidenceVariable` (criteria), USDM eligibility items, Dataset-JSON tables, JSON manifest with hashes.
2. **Accrual pack** (monthly during recruitment, after G2): pipeline by state with reasons (Pareto of screen-fail and decline reasons mapped to criteria), actual vs projected curve with the forecast's intervals, early-warning flags, candidates presented vs approached, pre-screening blind spots (FR-M4-11), time-to-consent, diversity of enrolled vs eligible.
3. **Site performance pack** (per sponsor request or at close): TransCelerate-style site metrics (time to first patient, enrolment vs target, screen-fail rate, query rate and resolution time, deviation rate, visit-window adherence), all rounded; past performance per therapeutic area.
4. **Data deliverables** (R3): eCRF pre-fill files (CDASH/ODM v2 or EDC template), SDV source packets, query answer drafts, retrospective de-identified datasets (FR-M8-7) with data dictionary, DQ report and de-identification certificate.

All packs: numbers from deterministic code, narratives through placeholders (AI-07), bilingual term rendering, lineage id, approval block, accountant entry.

### (i) Lifecycle coverage gaps

| ID | Sev | Finding |
| --- | --- | --- |
| R3-39 | M | Missing stages or thin ones (weakness 13). Appendix A marks ● for stages whose only content is one FR row. |

**v4 additions (deterministic, playbook-driven unless noted):** screening-visit eligibility checklist pre-filled from the cascade's evidence for the investigator to confirm per criterion (the box never marks "eligible"; CMP-08); IP accountability prompts (dispensing log reconciliation reminders, temperature-excursion acknowledgements) without touching randomisation; lab-kit and sample logistics (kit expiry, shipment windows from the SoA); participant reimbursement tracking (reminders only); retention and visit adherence (missed-visit risk from appointment data); **RBQM** key risk indicators per study (deviation rate, query rate, SAE reporting lateness, consent version lag) in the Monday digest; TMF/ISF completeness against the E6(R3) essential-records list with expiry tracking; DSMB/safety-report support (listing of hospital-flagged events, FR-M7-8); investigator-initiated-trial support (M11-template protocol skeleton drafting from a concept sheet, R3, LLM drafting under G1-like review); IRB e-submission package assembly to the hospital IRB system's import format; sponsor-query SLA tracking; study-level financial reconciliation (visits completed × budget table) at close. Stages remaining out of scope (randomisation, IP dispensing, unblinding, eConsent signing, patient contact) stay explicit non-goals.

### (j) Testing with open data and calibration

| ID | Sev | Finding |
| --- | --- | --- |
| R3-40 | B | No open-data strategy; every gate waits for site data (weakness 14). |
| R3-41 | M | The nonconformity model (§8.4) starts from zero at each site; AI-11's conservative default means months of "everything to S4". |
| R3-42 | M | No multilingual bake-off; MOD-1/NFR-19 choose "the smallest model that passes" but no procedure produces candidates. |

**v4 design — open-data test and calibration programme.**

| Dataset | Licence / access | Use in v4 | Suite and gate |
| --- | --- | --- | --- |
| NCBI TrialGPT cohorts (SIGIR 2016, TREC CT 2021, 2022): synthetic patients, labelled trials, keyword files | public (already in `trialgpt/data/ncbi`) | patient → trial retrieval and ranking (M5); regression against the paper (recall@500 0.93, NDCG@10 0.73 GPT-4) | `match_registry`: recall@500 ≥ 0.90; NDCG@10 ≥ 0.60 for the chosen J model *(target, est.)* |
| NCBI 1,015 expert criterion annotations (`data/ncbi/criterion_annotations/data.parquet`: note, criterion, expert sentences, labels) | public domain (NCBI) | **judge** evaluation and **evidence-span** verification (expert sentences as gold quotes); first training set for the nonconformity model; calibration of abstention before site data | `judge_public`: criterion accuracy ≥ 0.85 (GPT-4 0.873, experts 0.887–0.900); gold-sentence overlap ≥ 0.80; abstention model AUROC ≥ 0.75 on held-out |
| Chia corpus (1,000 trials, 12,409 criteria) + ClinicalTrials.gov eligibility text (API v2) | public | criterion extraction, structure and normalisation gold; criterion-library seed; registry-sync e2e | `criteria_extract_public`: structure F1 ≥ 0.85 |
| MIMIC-IV demo (100 patients, open) and MIMIC-IV-on-FHIR demo (NDJSON) | PhysioNet open demo | end-to-end ingestion through **FHIR Bulk NDJSON** and CSV paths; note judging on real English notes; DQ scorecard sanity | `ingest_fhir_demo`: 0 blocking DQ errors; lineage complete |
| Synthea (FHIR R4, CSV, C-CDA; configurable population) | Apache-2.0 | 300k–3M patient scale tests (NFR-4/5); HL7 v2 feeds synthesised from Synthea events; MPI-merge and late-arrival tests; privacy-accountant tests | `bench` and `pipeline_scale`: ingest ≤ 4 h at 3M; reconciliation detects planted 0.5 % drop |
| Chinese CHIP datasets (CHIP-CTC criterion classification, CHIP-STS, CBLUE) | research licences, Simplified Chinese | criterion-type classification and zh text handling; converted to Traditional Chinese (OpenCC) and labelled *synthetic-TW*; code-mixed synthetic variants by scripted substitution of English abbreviations | `criteria_zh`: macro-F1 within 5 points of the en suite; `judge_ml` synthetic strata until site data exist |
| n2c2 2018 cohort selection | DUA required *(uncertain for a company)* | patient-level selection baseline, English | optional |
| TW/JP public terminologies (ICD-10-CM TW, NHI codes, LOINC-TW map, MANBYO/JMED) | open government / academic | terminology service tests; `code_versions` suite | load 100 %; `$translate` round-trip |

Calibration: pre-train the nonconformity logistic model on the 1,015 annotations plus synthetic zh/mixed variants; at a site, LTT thresholds start from the public prior and are replaced per stratum as adjudications accrue; the QA pack shows the transition. The five-minute review and the recall ledger supply site labels. Report everything with TRIPOD-LLM headings.

**Multilingual small-model bake-off (OpenRouter, D0 data only).** Procedure, as code (`tools/bakeoff.py`): candidate list from the registry's `candidate` status (≤ 35B, both PRC and non-PRC families: Qwen3.x small, Gemma 4 12B/26B-A4B/31B, gpt-oss-20b, Mistral Small, Breeze/Llama-Taiwan, TAIDE, Nemotron nano; exact names from the registry, not the spec); tasks: criterion extraction (en + zh), judge (1,015 + zh/mixed synthetic), intent classification (bilingual synthetic emails), assertion (synthetic), date/number normalisation, protocol Q&A; fixed prompts and schemas; temperature 0; three seeds; per-task metrics with bootstrap CIs; cost and latency per 1k items; a composite score with per-language floors (no stratum below the floor). Output: a bake-off report in the registry; the top two per role become `shadow` builds for on-site evaluation under NFR-19; nothing enters production from the bake-off alone. Policy: OpenRouter routes accept D0 only; the gateway refuses anything else.

### (k) Plan, milestones, rollout and rollback

| ID | Sev | Finding |
| --- | --- | --- |
| R3-43 | B | No rollback plan; no milestones with exit criteria; no environments; no site-wave rollout (weakness 15). |
| R3-44 | M | 52 weeks with 4 engineers for the v3 scope was already optimistic (round 2 accepted 14/22 weeks for R1a/R1b); v4 adds a data platform, an LLM platform, Hermes and deliverables. |

**v4 plan (industrial structure).** Governance: a steering committee (owner, hospital research office, IT security, QA); a change-control board for G5; a risk register reviewed fortnightly; RACI per workstream (data platform, core, LLM platform, channels/Hermes, security, validation/QA, site enablement). Environments: dev (synthetic + open data, OpenRouter allowed), test (CI stack), validation (site de-identified zone, TRE), production (site). GAMP V-model: URS (v4 spec) → functional/design specs per workstream → IQ/OQ/PQ generated by `trialbox validate`.

| Milestone | Week *(est.)* | Exit criteria |
| --- | --- | --- |
| M0 Foundations | 6 | data platform S0–S5 on Synthea 300k with reconciliation and lineage; gateway + registry + routing policy; Hermes front door with native fallback passing `redteam`; public suites green in CI |
| M1 Feasibility on de-identified data (R1a) | 16 | IR v3 core; criterion library seeded; feasibility pack v1 with figures; validation replay on ≥ 10 closed studies (de-identified zone); bake-off report; bench gate on the chosen profile |
| M2 Pre-screening silent mode (R1b) | 24 | IRB approval; HL7 v2 or CDC feed live; clinic-day lists in shadow; recall ledger with confidence sequences; Level B signing; `judge_ml` per stratum ≥ 100 items |
| M3 Pre-screening live (wave 1: one department) | 30 | silent-mode agreement with CRC logs ≥ 0.80 capture; zero PHI incidents; CRC time −40 % on the pilot |
| M4 Recruitment engine + start-up (R2) | 40 | waves 2–3 (three departments); accrual packs; M6/M7 playbooks; Teams nudges; hybrid topology C exercised for D1 workloads at one sponsor's request |
| M5 Conduct and data (R3) | 52 | eSource packets accepted by a CRA; matching both directions; OMOP endpoint used by one OHDSI study; federated answer to a TACTC request |
| M6 Second site and Japan profile (R4) | 64 | second hospital installed from the bundle in ≤ 30 days; JP Core adapter and ja suites; validation paper submitted |

Rollout per site: install → `doctor`/`bench`/`validate` → Atlas and G0 → shadow (no emails to PIs) → silent prospective (packets to the CRC champion only) → wave 1 department → waves by department, each with a two-week soak and a go/no-go against KRIs (PHI incidents = 0; `uncertain` sends = 0; recall lower bound ≥ 0.90; abstention error ≤ α; gate backlog < 48 h; CRC satisfaction ≥ 4/5) → full → hypercare 4 weeks → steady state with monthly QA packs.

**Rollback plan (normative).** Every change class has a rollback unit, a trigger, a procedure and a verification:

| Change class | Rollback unit | Trigger (any) | Procedure | Verify |
| --- | --- | --- | --- | --- |
| Software bundle | previous signed bundle (blue/green directories; `trialbox rollback --bundle`) | failed `doctor`/`validate`, critical defect, security advisory | stop passes; switch symlink; restore config from Git tag; restart; outbox stays paused until verified | smoke e2e; audit chain continuous; ≤ 30 min |
| Model / prompt / lexicon / threshold (G5) | previous registry entry and exemplar/lexicon Git tag | eval regression, drift alarm, recall demotion storm, abstention error > α for 2 weeks | registry `champion` → previous build; recompute dirty set; re-issue affected packets flagged "regenerated" | shadow comparison; recall re-established (SAFE-8) |
| Ruleset (G1) | previous frozen version `<study>/v<semver>` | PI rejection rate flag, screen-fail blind spots, amendment withdrawn | re-approve previous tag; re-evaluate open candidates; note in Study Card | CQL≡SQL gate; candidate diff emailed |
| Data snapshot | previous snapshot T−1 (immutable) | post-publish DQ finding, source correction | `lake pin T-1`; re-run affected workflows; steward informed | reconciliation report; packets regenerated carry snapshot id |
| Channel (Hermes) | native gateway | security advisory, denial-rate anomaly, injection success in production red-team | `channels.engine: native`; Hermes container stopped; sessions archived | intake e2e; no lost requests (outbox) |
| Cloud route (topology C) | on-prem-only policy | contract change, leakage suspicion, cost overrun | routing policy revert (G5 fast-track with two Level A approvals); gateway blocks class | egress test; cost report |
| Whole site | restore from immutable backup to a spare box or the tenant | ransomware, hardware loss | DR runbook; RPO/RTO as NFR-8; comms plan to research office and IRB | restore test record; audit verify |

Each rollback is itself an audited change with a post-rollback review within five working days. Communication templates (zh-TW/en) for PIs and sponsors ship with the product.

---

## 3. Twenty innovations, ranked

Each: what · build path · metric. Items 1–6 are what make the product unmatched; 7–14 widen the moat; 15–20 are cheap wins.

1. **Anytime-valid recall ledger.** Elusion bounds as confidence sequences per canonical criterion, pooled across studies, valid under continuous monitoring and demotion. *Build:* `tb_common/recall/cs.py` (betting CS with HT weights), ledger tables, certificate renderer. *Metric:* coverage ≥ 95 % over 12 simulated looks; share of new studies certified at first packet.
2. **Criterion library and "match-then-draft" extraction.** Approved criteria reused across protocols; extraction becomes retrieval plus diff. *Build:* library tables keyed by canonical hash; Chia/CT.gov seed; extractor prompt with candidates. *Metric:* share of criteria matched to library (> 60 % after 20 protocols); extraction minutes per protocol; structure F1.
3. **Two-direction matching engine** sharing cache, judge and evidence (trial → patients, patient → trials, tumour board). *Build:* `services/matching/` from v1 cascade + TrialGPT port. *Metric:* `match_registry` NDCG; tumour-board minutes per patient.
4. **Data platform with reconciliation and lineage as a product feature.** Control totals, DQ scorecard, OpenLineage graph on every packet. *Build:* §2(b). *Metric:* planted-defect detection rate 100 %; days to onboard a new source (≤ 10).
5. **Class-based hybrid LLM control plane.** Gateway + registry + routing policy where data class, not network, decides what a model may see. *Build:* §2(d). *Metric:* zero class violations in `redteam`; cost per candidate; time to swap a model (≤ 1 day incl. G5).
6. **Hermes front door with capability separation.** Natural conversation in email/Teams/LINE, zero PHI reach by construction. *Build:* §2(e). *Metric:* proposal accuracy ≥ 0.95; injection success 0; CRC requests per week handled without grammar.
7. **Recruitability model with a forecast ledger.** Projection scored against actuals; the site's calibration shown to sponsors. *Build:* hierarchical Beta-Binomial R1a; ledger; calibration plot. *Metric:* calibration slope 0.8–1.2 after 10 studies; Brier vs PI estimates.
8. **S2b semantic pre-filter with lexicon-recall gating.** Zero-hit exclusion allowed only for criteria with measured lexicon recall ≥ 0.98. *Build:* sentence-embedding screen; `lexicon_recall` suite. *Metric:* `S2-zero_hit` elusion bound; llm_share change.
9. **Sentence-set judgement cache.** Invalidate on relevant new sentences, not on any new note. *Build:* cache key change; dirty-set rules. *Metric:* cache hit rate > 80 % in daily-note clinics.
10. **Sponsor deliverable standard** (four packs, fixed figures, FHIR/USDM/Dataset-JSON exchange). *Build:* §2(h); renderers from data objects. *Metric:* sponsor acceptance without rework; % questionnaire auto-answered; days from request to pack (≤ 2).
11. **Open-data CI and public calibration prior.** Every model change gated on public suites; nonconformity model pre-trained on the 1,015 annotations. *Build:* §2(j). *Metric:* weeks to first certified LTT threshold at a new site (target ≤ 8).
12. **Bake-off as code via OpenRouter** with per-language floors and cost; winners enter shadow. *Build:* `tools/bakeoff.py`; registry statuses. *Metric:* bake-off to shadow to champion cycle time; stratum gap ≤ 5 points.
13. **Champion/challenger shadow pass** (kept from round 2, now fed by 12). *Metric:* weeks of site evidence before a G5 model change.
14. **Alliance language packs and federated feasibility node** (ML-12, FR-M11-3) positioned as the TACTC/TNet responder. *Metric:* alliance requests answered automatically; ε spent per quarter.
15. **Privacy-by-class PET kit:** de-identification pipeline with expert-determination report, PPRL linkage, synthetic cohort twins for sponsor previews. *Metric:* re-identification risk ≤ threshold on every D2 export; synthetic preview requests served.
16. **Watchlist flips, clinic-day portfolio lists and QBCB review depth** (kept). *Metric:* watchlist → strong conversions; review depth k.
17. **Five-minute review and exemplar bank** (kept). *Metric:* PPV lift per 100 labels.
18. **eSource packets with lineage** (kept, structured domains first). *Metric:* SDV minutes per visit; field agreement ≥ 0.95.
19. **NHI-aware recruitment and coverage analysis at feasibility** (kept). *Metric:* budget-table acceptance; NHI-signal enrolments.
20. **Offline prompt and skill optimisation** (GEPA/DSPy on evaluation sets, outputs through G5). *Metric:* suite gains per cycle with no production exposure.

---

## 4. What v4 must contain (table of contents with key requirements)

0. **Binding constraints (revised).** C-1 independence (kept); C-2′ *on-prem first, hybrid under policy* with the data-class table; C-3 filter first; C-4 batch first, interactive where cheap; C-5′ minimal UI (signing page, review page, admin control plane, optional CDS card); C-6 lifecycle; C-7 cost balance; C-8 multilingual; C-9 codeable; **C-10 Hermes as governed front door**; **C-11 open-data verifiability**.
1. **Where we are.** Verified v1 facts (corrected N-13 items); TrialGPT port and the 1,015-annotation asset; what has never touched reality.
2. **Product definition.** Vision; roles (add administrator-as-controller, sponsor machine recipient, alliance root); lifecycle table with the §2(i) additions; intended use (unchanged); non-goals (unchanged plus "no PHI to cloud models in any topology").
3. **Experience.** Role surfaces (§2(f)); message rules FR-UX-1…8; conversation model with Hermes (multi-turn, proposal, confirmation); decision sheets and the optional review page; approvals Level A/B (kept, with the one-page signing ceremony); admin control plane.
4. **Architecture.** Topologies A/B/C; C4 views; containers (add gateway, registry, terminology service, OMOP, HL7 v2 listener, CDC, lineage store, trace store, Hermes, native channel); layering with the data-class boundary; cascade S0–S5 with S2b; passes and budgets; hardware profiles and bench gate (kept); ADRs revised (ADR-V3-02 workflow engine reconsidered: keep Postgres durable steps, or adopt DBOS/Temporal if gates outgrow it; ADR-V3-07 reversed; ADR-V3-09 OMOP core).
5. **Data platform.** Zones; stages S0–S5 with controls; per-source streams (HIS views, CDC, CGRD/TRE, FHIR Bulk + SMART Backend, HL7 v2, CSV/registry, cohort, NHI); data contracts; reconciliation and publish gate; DQ framework and scorecard; terminology service and editions; identity lifecycle (MPI, merges, erasure, corrections, late data); lineage (OpenLineage + Provenance); catalog (Atlas); retention per zone.
6. **Data model and contracts.** IR v3; canonical text; evidence (multi-span) and candidate (split `potential`); feasibility pack objects; recall certificate with confidence sequences; Study Card; manifest v3 (lineage id, routes, classes); gate/approval/signature; lexicon; privacy ledger; registry/model card/eval/bench/bake-off; data contract and DQ report; `Consent`.
7. **Privacy architecture.** Data classes D0–D4; boundary table per topology; de-identification standard and risk assessment; PET kit; Five Safes/TRE for the evaluation zone; opt-out and consent scopes; PHI guard coverage gates; PDPA/HSRA basis and cross-border analysis.
8. **LLM platform.** Gateway; registry and model cards; routing policy; guardrails; evaluation suites (site + public); observability and trace store; cost model and budgets; role → module → class table; shadow and bake-off lifecycle; G5 change control; reproducibility via recorded outputs.
9. **Hermes Agent.** Role, allowed tools (front-door MCP server), hardening checklist, memory and skills governance, approval boundary, injection posture, native fallback, upgrade policy, tests.
10. **Functional requirements by module.** M0 onboarding/Atlas (+ DQ, contracts); M1 intake and criterion library; M2 optimisation; M3 feasibility and deliverable packs; M4 pre-screening; M5 matching both directions; M6 tracking and forecast ledger; M7 start-up/conduct (+ §2(i) items); M8 data/eSource; M9 close-out; M10 NHI; M11 network/federation; AG agent behaviours; ML multilingual; SAFE recall (revised statistics).
11. **Workflows and gates.** Durable steps and outbox (kept); gate catalogue G0–G6; feasibility, pre-screen, match, recall-audit, active-learning, lifecycle, abstraction, close, change, validation-replay, **ingest/publish**, **bake-off**, **rollback** workflows.
12. **Pharma deliverables.** Four packs with sections, figures, formats, exchange standards, provenance and disclosure.
13. **Non-functional requirements.** Batch SLOs (kept) plus interactive targets for Hermes answers over T0/T1 (≤ 60 s), ingestion SLOs per stream, availability per topology, RPO/RTO per topology, cost ceilings, capacity for 300 studies and 3M patients, portability.
14. **Security.** Component control allocation; identity and key management; threat model (STRIDE, OWASP LLM Top 10, MITRE ATLAS) incl. Hermes and cloud; supply chain; monitoring and SIEM; incident response and breach; backup immutability; secure SDLC; pen test and disclosure.
15. **Compliance.** Trace matrix to 21 CFR 11, E6(R3) Annex 1, EMA computerised-systems guideline, GAMP 5, FDA CSA, PDPA 2025, HSRA, ESA 2024, EMR regulation, AI Basic Act, ISO/IEC 42001, 27001, 25237; intended-use analyses; AI credibility files.
16. **Verification, validation and open data.** Test layers; public suites and datasets with licences; site suites; annotation protocol; calibration programme; bake-off procedure; validation as a feature (IQ/OQ/PQ); go-live acceptance per site with KRIs.
17. **Engineering standards.** Monorepo layout for the new packages; `@req` tracing; ADR/C4; CI/CD with SLSA; DoD.
18. **Operations.** Install per topology; schedules; monitoring; updates and **rollback procedures per change class**; support model; QA pack; DR drills.
19. **Positioning and commercial principles.** Differentiators mapped to the 20 innovations with metrics; head-to-head table refreshed (Lind Asia, Triomics, Tempus/Deep 6, Paradigm, TriNetX, Epic/Oracle, IQVIA.ai/Medidata/Veeva, TrialGPT-class baselines, NTT/Fujitsu); pricing principles.
20. **Delivery plan.** Governance, RACI, risk register, environments, milestones M0–M6 with exit criteria, site-wave rollout, hypercare, training, and the first sprint in dependency order (starting with the data-platform stages, the gateway and the Hermes front door rather than S1-0's deletion of the cloud path).
21. **Open decisions.** Topology for the first site; cloud provider and region; Hermes vs native as default; OMOP core timing; IRB pathway and PDPA basis; signing method; model origin policy; opt-out default; pricing.
22. **Appendices.** Lifecycle matrix; evidence base; compliance trace; grammar (reduced to the lines Hermes proposes); seed tables; statistics (sample sizes and confidence-sequence parameters); data-class boundary table; control allocation table; open-data licence table; disposition of rounds 1–3.

*End of report.*
