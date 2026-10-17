## 10. Functional requirements by module

This section says what each module does. It is written as requirement rows that a coding agent can build and a tester
can verify. Part D1 covers M0–M5, the multilingual requirements (ML) and the false-negative safety requirements (SAFE).
M6–M11, the agent behaviours and the workflows are in §10.6–§10.12 and §11.

Each module subsection gives, in order: purpose; inputs and outputs with their data class (§7); the LLM functions it
uses (roles of §8, with declared class and what the model may decide); requirements; and acceptance metrics, each with
a target, the best published comparator (Appendix B), the measuring suite (§16) and a milestone.

**Rules that apply to every module**

| Rule | Statement |
| --- | --- |
| Inheritance | Every module inherits, without restatement: audit and access (§14); the data-class policy, controlled rounding and the privacy accountant (§7); lineage (§5); disclosure (§15); durable steps and the outbox (§11). |
| Model calls | A module never calls a model endpoint. Every generative, embedding and reranking call goes through `tb-gateway` (§8) with a declared role, data class and purpose; the routing policy picks the build; a class the route does not allow is refused, never silently downgraded. |
| Determinism | Models propose; code decides. Tiers, counts, ranks, forecasts and certificates come from deterministic code over recorded model outputs; a re-run on the same inputs is byte-identical (§13). |
| IDs | A v3 ID that appears here is kept unchanged (milestone re-mapped only). A revised requirement has a new ID and names, in *(Replaces …)*, the v3 ID it retires. A v3 ID of M0–M5, ML or SAFE that appears nowhere in this part is retired by the row that names it. |
| Milestones | R names the milestone (§20) at which the requirement must pass verification. Unchanged v3 rows map R0 → MS0, R1a → MS1, R1b → MS2, R2 → MS4, R3 → MS5, R4 → MS6; rows brought forward say so. |
| Estimates | *(est.)* marks an engineering target that `trialbox bench` or `trialbox eval` must confirm before it is quoted to anyone. |

**LLM roles used by M0–M5, ML and SAFE** (names from the §8 role table; † = introduced here and MUST be added to §8
with routes). A D3 role never routes off the perimeter (§7). `embed` and `rerank` are model roles and pass through the
gateway too.

| Role | Used by | Declared class | May decide | May never decide |
| --- | --- | --- | --- | --- |
| `propose_mapping` | M0 | D1 (schema and de-identified coded samples only) | The proposed column → canonical mapping, with a reason | The mapping in force (G0 decides) |
| `match_criterion_library` † | M1, M5 (registry criteria) | D1 (protocol text); D0 for registry text | Which library entry a protocol criterion matches, or "none" | Parameter values (code substitutes them and checks them) |
| `extract_criteria` | M1 | D1 | A draft IR v3 for criteria with no library match | Codes (FR-M1-3); the frozen ruleset (G1) |
| `concept_select` | M1 | D1 | A choice among terminology-service hits | Any code not in the hit list |
| `answer_protocol` | M1 | D1 | The wording of an answer built from retrieved passages | Any claim without a cited passage |
| `draft_narrative` | M2, M3 | D1 (aggregates) | Prose with `{{placeholders}}` | Any digit (AI-07) |
| `map_questionnaire` | M3 | D1 | Question → packet path, profile field or answer memory | An answer value |
| `classify_intent` | M4 decisions, M5 requests (through Hermes or the native intake, §9) | **D3** for every authenticated staff message in a packet thread and for tokenised text from PHI-tolerant channels; otherwise D1. On-prem routes only for both; cloud routes never receive conversation text (FR-CONV-8, §8.5) | Proposed grammar lines for the sender to confirm | Applying a decision (only deterministic intake applies confirmed lines) |
| `judge` | M4, M5, SAFE | D3 | met / not_met / insufficient, with quote offsets, assertion and value | The tier, the rank or any count |
| `second_opinion` | M4, M5, SAFE | D3 | An independent judgement with the same schema | The same as `judge` |
| `match_keywords` † | M5 | D3 | English search keywords from a patient summary, on-prem only | Anything that leaves the perimeter |
| `embed` (bge-m3; MedCPT query/article encoders) | M1, M4 (S2b), M5, ML | D0–D3 | Similarity scores | Exclusion (only a calibrated, gated threshold in code may act on a score) |
| `rerank` (bge-reranker-v2-m3; MedCPT cross-encoder) | M1, M5 | D0–D3 | Re-ordering | The same as `embed` |

---

### 10.0 M0: Site onboarding, Data Atlas and data contracts

**Purpose.** M0 brings a hospital's data sources into the data platform and keeps an account of the data that people
can read: what exists, how complete and fresh it is, who owns it, which contract governs it, and which criteria can be
computed from it.

M0 is the functional face of the platform: the source-onboarding playbook, contract authoring, the steward's workbook
round trip (G0), the Atlas, the DQ scorecard as the steward receives it, terminology and lexicon onboarding, the site
profile and `trialbox doctor`. The stages L0–L5, transports, reconciliation, MPI and lineage stores are §5; the contract
and DQ-report schemas are §6.

**Inputs and outputs**

| Direction | Item | Class | Notes |
| --- | --- | --- | --- |
| In | Source connection definitions (`site/sources.yaml`); credentials held in the secrets store | D1 | One entry per stream kind of §5 |
| In | Profiling queries over the sources (counts, types, histograms) | D3 at source → D1 after aggregation | Free text is never sampled |
| In | The steward's returned workbook | D1 | Covers mapping, contract, lexicon and owners |
| In | Terminology packages and editions | D0 | Covers ICD-10-CM TW 2014/2023 and the mapping, NHI drug/fee, ATC, LOINC-TW, the site lab dictionary, and JP masters (MS6) |
| Out | `mapping/<site>.yaml`, `site/contracts/<source>.yaml`, the lexicon diff | D1 | All are Git-versioned and G0-approved |
| Out | The Atlas: catalogue, coverage, freshness, computability, note-language profile, DQ scorecard | D1 (aggregates, controlled rounding) | It is the data catalogue of the site |
| Out | `tb.atlas_describe` (front-door T0 tool, §9.3) and the internal function `atlas.computability()` | D1 | Used by M1, M3 and, through `tb.atlas_describe`, Hermes (§9) |
| Out | Site profile (SIP-compatible) | D1 | Feeds M3 and the answer memory |

**LLM functions.** Only `propose_mapping` (D1). Its input is limited to column names and types, histograms of coded
columns with cells ≥ 5 patients, unit strings and the canonical field descriptions; the gateway runs the PHI guard and
class check on it. Under topology C it MAY use a cloud route if §8 allows D1 for the role. No model in M0 sees patient
rows, notes or identifiers; lexicon mining, profiling and DQ are deterministic.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M0-2 | `atlas run` MUST profile every configured table: row counts, types, null rates, distinct counts, top-50 value histograms (values seen in fewer than 5 patients shown as `<5`), date ranges, and per-department and per-year coverage. Free-text columns MUST NOT be sampled. Identifiers MUST NOT appear in the report. | T | MS0 |
| FR-M0-3 | The Atlas MUST propose a mapping from source columns to the canonical model using: <br>• column-name heuristics; <br>• value patterns (ICD-10, ATC, NHI drug, NHI fee, LOINC, MRN regex, ROC dates); <br>• a model step that sees only column names, types, and de-identified samples of coded columns. <br>The model step's input passes the PHI guard. Each proposal carries a confidence and a reason. | T | MS1 |
| FR-M0-4 | The Atlas MUST export the proposal as an XLSX workbook (one sheet per canonical table, dropdowns, a lexicon sheet), read the steward's returned workbook into `mapping/<site>.yaml`, and email the diff. Gate G0. | T | MS0 |
| FR-M0-5 | After each ingest the Atlas MUST compute: <br>• **domain coverage** per patient and scope: the share of patients with ≥ 1 record per domain in the last 12, 24 and 60 months; <br>• **freshness**: latest source timestamp to snapshot. | T | MS0 |
| FR-M0-9 | Ingest MUST stream with bounded memory (≤ 8 GB RSS regardless of patient count), chunked by patient id, and restartable per chunk. | T | MS1 |
| FR-M0-10 | The site profile (TransCelerate SIP-compatible: staff, equipment, IRB and contract timelines, past enrollment) MUST be versioned and maintained by workbook round trip. It is pre-filled from the box's own data (departments, practitioners, historical enrollment from M6). | T | MS1 |
| FR-M0-12 | Optional structured source: **NHI MediCloud** (健保醫療資訊雲端查詢) medication and lab history. <br>• MediCloud is queried per patient for that patient's care. Bulk retention for research pre-screening is outside its normal terms and PDPA purpose limitation. <br>• The source MAY be enabled only with written NHIA permission and an IRB-approved purpose on file. <br>• It is ingested with provenance `source=nhi_cloud`. | T, I | MS5 |
| FR-M0-14 | *(Replaces FR-M0-1.)* The box MUST connect to each source kind of §5. <br>**Source kinds:** <br>• read-only SQL views, with optional CDC; <br>• CGRD-type research databases (TRE zone only); <br>• FHIR Bulk Data Access 3.0.0 (2.0.0 servers accepted) with SMART Backend Services; <br>• HL7 v2.5.1 over MLLP/TLS; <br>• CSV/Parquet/registry drops with a `.sha256` sidecar; <br>• cohort/alliance aggregates; <br>• SS-MIX2 standard storage (JP profile, `services/dataplat/sources/ssmix2.py`). <br>**Configuration:** each source is declared in `site/sources.yaml` with its kind, zone, data class, owner, cadence and contract reference. Credentials live in the secrets store (§14), never in Git. | T | MS0 (HL7 v2 and CDC MS2; SS-MIX2 MS6) |
| FR-M0-15 | *(Replaces FR-M0-6.)* The Atlas MUST compute a **computability score** for every IR v3 construct (§10.1) and ValueSet over a scope. <br>**Basis per construct:** <br>• presence and value atoms; <br>• `attribute` paths per `source_priority` entry; <br>• each `derived` calculator: the share of patients with all inputs in the window; <br>• `line_of_therapy`: the share with medication administrations of the named classes in the lookback; <br>• `organ_function`: the share with every panel lab in the window. <br>**Example:** "eGFR within 28 d of screening: 41 % of active NEPH patients". <br>**Consumers:** M1 annotates criteria with it; the compiler sets `filter_class` from it (SAFE-1). | T | MS1 |
| FR-M0-16 | *(Replaces FR-M0-7.)* For each snapshot the Atlas MUST render the **DQ scorecard** computed by §5: pass rates per domain and check in the Kahn categories (conformance, completeness, plausibility × verification, validation), the 12-snapshot trend and the reconciliation deltas. Blocking findings carry the check id, affected row count and ≤ 20 pseudonymous record references; they stop publication (§5) and go to the steward with the proposed fix. The scorecard goes to the steward and research office and into the monthly QA pack. | T | MS0 |
| FR-M0-17 | *(Replaces FR-M0-8.)* The box MUST load the following into the terminology service (§5): <br>• NHI ICD-10-CM/PCS **2014 and 2023 editions with the official 2014→2023 mapping** (edition assigned by visit date from 2025-01-01); <br>• ICD-9-CM 2001 for history; <br>• the NHI drug master with ATC; <br>• NHI medical-service fee codes; <br>• TFDA licence and ATC codes; <br>• LOINC with the MOHW Taiwan LOINC mapping; <br>• the site lab dictionary; <br>• departments and practitioners; <br>• (MS6) the JP masters of ML-17. <br>Every snapshot manifest records the loaded versions. `$validate-code` and `$translate` MUST answer for every loaded system. | T | MS0 |
| FR-M0-18 | *(Replaces FR-M0-11.)* `trialbox doctor` MUST check, per topology (A/B/C): host, GPU, driver pin; models and SHAs as seen through the gateway; gateway reachability and routing-policy hash; mail, Teams/LINE and Hermes status with `channels.engine`; sources and last reconciliation; egress (only the gateway reaches model endpoints); clock, disk, backup immutability, certificate expiry; the WebAuthn and OCRA stores; and the licence manifest against site policy flags. It prints the fix for each failure. | T | MS0 |
| FR-M0-19 | *(Replaces FR-M0-13; brought forward from R2.)* The lake MUST hold `condition_attribute(pid, condition_ref, path, value_code, value_num, unit, effective, source, source_rank)`. <br>**Feeds:** cancer-registry extracts (癌症登記, with site-specific factors), structured pathology fields, staging tables, and note-derived attributes approved through M8 abstraction. <br>**Precedence:** `source_rank` follows the criterion's `source_priority` (registry → structured pathology → report span → note). <br>**No mapped source:** an `attribute` atom has computability 0 and is routed to the note path (S2/S2b/S3). It is never `fail`. | T | MS1 |
| FR-M0-20 | **Data-contract authoring.** For each source the Atlas MUST propose a contract from profiling, in the schema of §6. <br>**Contract contents:** schema, primary and foreign keys, nullability, enumerations, unit expectations, the control-total query, freshness SLA, owner, zone, data class and lawful basis. <br>**Approval:** the steward confirms it at G0. It is stored as `site/contracts/<source>.yaml`, versioned in Git. <br>**Breaking change:** a batch that violates the contract is quarantined (§5). The steward receives the diff, the affected row count and a proposed contract revision. A revision is a new G0. | T | MS0 |
| FR-M0-21 | **Source onboarding playbook.** `trialbox source add <kind>` (CLI, mirrored in the admin console) MUST run these steps, each a durable step (§11), reporting progress by email to the steward: <br>1. connect; <br>2. profile; <br>3. propose the contract; <br>4. propose the mapping; <br>5. ingest into a sandbox snapshot; <br>6. reconcile against the control totals; <br>7. produce the DQ scorecard and the computability delta; <br>8. G0. <br>A source becomes `active` only after G0 and one clean publish. | T | MS1 |
| FR-M0-22 | **Zone assignment.** Every source MUST declare a zone (§7): <br>• `identified` (the screening zone: D3 in the lake, D4 in the vault); or <br>• `deidentified` (the TRE: D2). <br>A CGRD-type research database is always `deidentified`. The Atlas MUST refuse a mapping that would let a `deidentified` source contribute to pre-screening (M4), patient matching (M5) or any list naming a patient. Such sources serve feasibility, validation replay and evaluation only. | T | MS1 |
| FR-M0-23 | **Atlas as catalogue.** For every table and column the Atlas MUST list owner, contract version, coverage, freshness, DQ status, terminology binding and lineage link (§5), exportable as DCAT-AP 3.0 or OpenMetadata JSON *(optional per site)*. | T | MS4 |
| FR-M0-24 | **Terminology coverage and local-code mapping.** Per snapshot the Atlas MUST report: <br>• the share of coded records resolved to a standard system, per domain and per edition; <br>• unmapped local lab codes ranked by patient count, each with a proposed LOINC mapping from `propose_mapping` over lab name, specimen and unit, with the reason. <br>Proposals are G0 items. An unresolved code is not silently dropped: atoms over it have computability 0. | T | MS1 |
| FR-M0-25 | **Note-language profile.** Per note type × department × month the Atlas MUST compute aggregate text statistics: <br>• sentence-level language-tag shares (zh/en/ja/mixed, §6 canonical text); <br>• script-token share; <br>• abbreviation density; <br>• unknown-token rate against the approved lexicon; <br>• notes per patient-month. <br>Values are aggregates only and contain no text. They seed the ML-15 drift baselines and the strata of the `lexicon_recall` suite (SAFE-9). | T | MS1 |
| FR-M0-26 | **Scheduling readiness.** Before M4 can be enabled for a clinic, the Atlas MUST report: <br>• the share of that clinic's appointments that arrive same-day through SIU or CDC versus the nightly view; <br>• the booking lead-time distribution; <br>• the share of appointments with an identifiable practitioner. <br>M4 clinic-day lists are refused for a clinic whose practitioner identification is below 0.95. | T | MS2 |
| FR-M0-27 | **Consent and opt-out source.** Before M4 goes live, a consent source MUST be mapped: FHIR `Consent` with the scopes `research_use`, `contact` and `nhi_secondary_use`, or the registry CSV (§7). The Atlas reports the patients covered and the scope distribution, in rounded counts. Without a mapped consent source, M4 stays in `shadow` mode (FR-M4-20). | T | MS2 |
| FR-M0-28 | **Computability function.** The internal function `atlas.computability(construct, valueset, window, scope)` (not a front-door tool; HER-8 keeps exactly eight `tb.*` tools) MUST return the score, its basis sentence and the snapshot id, with no patient data. M1, M3 and Hermes' `tb.atlas_describe` use only this function for availability statements. | T | MS1 |
| FR-M0-29 | **Atlas diff.** After each publish, the Atlas MUST compare coverage, freshness and unit consistency with the previous snapshot. If a domain's 12-month coverage changes by more than 2 percentage points, or a lab's unit consistency falls below 0.9, the Atlas MUST: <br>• email the steward; <br>• list the recruiting studies whose criteria depend on that domain (`depends_on`); <br>• have the compiler recompute `filter_class` (SAFE-1) before the next screening run. | T | MS2 |
| FR-M0-30 | **Lexicon onboarding.** At onboarding the box MUST: <br>• load the lexicon seeds (ML-5); <br>• run deterministic mining on the note corpus; <br>• present the proposed rows in the G0 workbook with rounded support. <br>Until the `lexicon_recall` suite has passed for a criterion type and language stratum (SAFE-9), S2 zero-hit exclusion is off for that stratum. | T | MS1 |

**Acceptance metrics (M0)**

| Metric | Target | Comparator | Suite / evidence | MS |
| --- | --- | --- | --- | --- |
| Identifiers in any Atlas or DQ output | 0 (PHI-guard scan of every artefact) | — | `atlas_privacy` | MS0 |
| Planted-defect detection (truncated view, unit swap, duplicate encounters, 0.5 % row drop, MRN merge) | 100 % detected, with publication blocked | v3: seven rules, no reconciliation | `pipeline_scale` with Synthea 300k (§16) | MS0 |
| Open FHIR end-to-end: MIMIC-IV-on-FHIR demo through Bulk NDJSON | 0 blocking DQ errors; lineage complete; coverage report produced | — | `ingest_fhir_demo` | MS0 |
| Terminology resolution of coded records (ICD, NHI drug, NHI fee, LOINC-mapped labs) | ≥ 0.98 per domain | ITRI FHIR coding tool 91.3 % (code recommendation, different task) | `code_versions`, Atlas report | MS1 |
| Computability prediction error: Atlas-predicted versus realised share of patients with the data at S1 | median absolute error ≤ 0.05 per criterion | none published | validation replay (§16) | MS1 |
| Source onboarding elapsed time | ≤ 10 working days per supported source kind | review target | onboarding log | MS4 |

---

### 10.1 M1: Protocol intake, IR v3 and the criterion library

**Purpose.** M1 turns a protocol into a frozen, compiled and computable ruleset whose every element is traced to its
protocol span. The defining change from v3 is **match-then-draft**: the extractor's first task is to match each
criterion to an entry in the **criterion library**, and it drafts IR only when no entry fits. M1 also answers protocol
questions (`ASK`), diffs amendments, digitises the schedule of activities (SoA) and auto-parses registry criteria for M5
and M3.

The IR v3 schema is normative in §6. This section specifies how M1 produces it, and what each construct must do.

**Inputs and outputs**

| Direction | Item | Class |
| --- | --- | --- |
| In | Protocol, as one of: PDF (text or scanned), DOCX, ICH M11 CeSHarP, CDISC USDM 4.x JSON, a ClinicalTrials.gov record, or pasted text. Languages: en, zh-TW, ja. | D1 (sponsor-confidential) |
| In | Criterion library, terminology service, Atlas computability, approved lexicon | D0 / D1 |
| Out | Ruleset `<study>/v<semver>`, frozen at G1, containing: <br>• IR v3; <br>• ValueSets; <br>• CQL, SQL and CIRCE JSON; <br>• equivalence-gate report; <br>• annotations. | D1 |
| Out | Understanding email, plus the criteria workbook or the optional review page (§3) | D1 |
| Out | FHIR `EvidenceVariable` and USDM eligibility items (exchange, §12) | D1 |
| Out | Library updates, made at G1: new entries, variants and per-site history | D1 |

**Pipeline (normative order).**

```
intake ─► doc-parser: locate I&E, SoA, definitions, lab-threshold tables, appendices      deterministic + LLM locate (D1)
       ─► segment into criteria (one row per protocol bullet; sub-bullets kept as children)  deterministic
       ─► library retrieval: BM25 + bge-m3 over library canonical texts (en, zh-TW, ja)
          → top-20 → cross-encoder rerank → top-5                                            embed / rerank (D1)
       ─► match_criterion_library[J]: "match <entry>" | "variant <entry> + parameter diff" | "none"    LLM, recorded
            match   → reuse the entry's IR; parameters (numbers, units, windows) re-read from the
                      protocol span by the deterministic span parser (ML-3) and checked equal
            variant → the entry's IR with the parsed parameters substituted; the slot diff is shown
            none    → extract_criteria[J] drafts IR v3 with source spans
       ─► concept normalisation: tb.vocab.search (terminology service + approved lexicon)
          → rerank → concept_select[J] chooses among hits only; edition expansion (ML-16)      LLM selection, code check
       ─► compile: CQL + SQL + CIRCE JSON from templates; equivalence gate (CQL ≡ SQL)         deterministic
       ─► annotate: computability (FR-M0-28), filter_class (SAFE-1), depends_on, lexicon_keys,
          note_question (protocol + site language), S2b question embedding, zero-hit eligibility
          (SAFE-9), flip_rule, safety_critical, canonical_hash                                deterministic
       ─► independent check: extract_criteria[V] (night pass) on every drafted or variant criterion
          and on every safety_critical one; any structural difference → a numbered question     LLM, recorded; deterministic diff
       ─► understanding email + workbook / review page ─► G1 (Level A) ─► freeze; library update
```

**IR v3 constructs (functional view).**
- The table lists what M1 must emit, what each construct is computed from, and what happens when it is not computable.
- Every construct keeps the IR 2 semantics where they still apply:
  - three-valued logic;
  - affirmative exclusion only;
  - the index-condition exception.
- Every construct compiles from templates, and is covered by fixtures in `rulesets/ATOMS_V3` for the equivalence gate.

| Construct | Example criterion | Computable from | Not computable → | MS |
| --- | --- | --- | --- | --- |
| Presence / value atom on any domain (condition, observation, medication, procedure, encounter, demographic, claim, report, appointment). Value comparisons are allowed outside the observation domain, lifting the v1 `semantics.py` restriction. | "LVEF ≥ 50 % on echocardiography within 28 days" (a `report` value) | Typed spans of structured reports, or the observation table | `unknown` → note path | MS1 |
| `attribute` with `source_priority` | "ECOG 0–1", "HER2-positive (IHC 3+ or ISH+)", "stage IIIB–IV" | `condition_attribute` in rank order (FR-M0-19) | Note path, with the attribute's note question | MS1 |
| `derived` with a versioned calculator (§6 calculator library) | "CrCl ≥ 50 mL/min (Cockcroft–Gault)", "eGFR ≥ 45 (CKD-EPI 2021)", "Child-Pugh A", "BMI 18.5–35" | Calculator inputs in the window. Each calculator declares its inputs and its missing-component rule. | `unknown`. The packet names the missing inputs (`potential:data_gap`). | MS1 (CKD-EPI 2021, Cockcroft–Gault, BMI, DAS28, BASDAI, ASDAS from `libs/tb_common/derived.py`); MS4 (Child-Pugh, MELD, NYHA and ECOG from notes, RECIST status from reports) |
| `anchor: screening \| randomization \| event \| index` | "ANC ≥ 1.5 × 10⁹/L within 14 days **before randomisation**" | The window is resolved against the anchor date supplied at run time. <br>• Pre-screening: the next appointment date, or the date a CRC sets. <br>• Feasibility: the run date plus the site's screening offset. | Never silently re-anchored to "today" | MS1 |
| `organ_function` macro | "Adequate organ function as defined in Table 3" | Expands to a lab panel with thresholds: <br>• from the protocol's own table, which the doc-parser extracts; <br>• otherwise from the sponsor-standard default panel, seeded from the ELaPro core lab set *(composition to be confirmed, uncertain)*. A default is used only after the CRC confirms it as an ambiguity question. | Per-lab `unknown` | MS1 |
| `line_of_therapy` | "Progressed on or after ≥ 2 prior systemic lines including a platinum doublet" | **Regimen model** (`services/criteria_compiler/regimen/`): <br>• drug-class sets (ATC); <br>• cycle and gap rules (a new line after a gap > 90 d *(est.)* or a class switch); <br>• progression events from registry fields and pathology/radiology report spans. | Note path, with the line-count note question | IR representation and note path MS1; structured regimen derivation MS4 |
| `seq`, `atleast`, washout windows, `trend` | "≥ 4 weeks since last dose of a biologic DMARD" | Medication records | `unknown`; the watchlist flip date is computed when computable | MS1 |
| Note criterion | "No history of interstitial lung disease" | S2 lexicon → S2b semantic screen → S3/S4 judge | `potential:uncertain` or `potential:data_gap` | MS1 |
| `human` criterion | "In the investigator's opinion, able to comply" | Never computed. It carries a structured `investigator_check` field ("what to confirm at screening"). | `verify_at_screening` | MS1 |

**The criterion library.** The library is a set of Postgres tables (`library_entry`, `library_variant`,
`library_site_history`, `library_source`) with a Git-exported, signed snapshot, in `services/criteria_compiler/library/`.

Each entry stores the canonical hash (§6), canonical text in en, zh-TW and ja, the IR v3 with parameter **slots**
(e.g. `{egfr_min}`, `{window_days}`), ValueSets, lexicon keys, the bilingual note question, the `filter_class` basis,
the `safety_critical` flag and provenance. Each site adds history without PHI: computability, PI-rejection precision
(FR-M4-8), screen-fail blind spots (FR-M4-11) and its elusion-ledger cells (SAFE-10).

*Entry statuses:*

| Status | Meaning | May be used for |
| --- | --- | --- |
| `seed` | Drafted automatically from a public corpus; not reviewed | Retrieval candidates only. A protocol criterion matched to a `seed` entry is treated as **drafted**: it gets the V check and is flagged in the workbook. |
| `curated` | Reviewed by the TrialBox clinical-informatics team against its source texts; equivalence fixtures pass | Match with the normal G1 review |
| `approved@<site>` | Passed G1 at that site at least once | Match; its site history is shown in the workbook |
| `deprecated` | Superseded, or demoted by SAFE evidence | Never matched; kept for audit |

*Seeding.*
1. **Chia corpus** (1,000 trials, 12,409 criteria; entity and relation annotations aligned to OMOP CDM domains; licence
   CC BY 4.0 *(uncertain)*). Annotations are converted into IR atoms and slots by `tools/library_seed_chia.py`. Criteria
   whose annotations cannot be expressed in IR v3 are kept as `seed` with `ir: null` and counted. This count is the
   expressiveness gap report.
2. **ClinicalTrials.gov API v2** eligibility text from the local mirror (FR-M5-9): every study recruiting in Taiwan or
   Japan, and phase II–IV interventional studies since 2016 in the site's top ten areas *(scope est.)*. Text is
   normalised deterministically (numbers, units, durations → slots), clustered with bge-m3 (cosine ≥ 0.92 *(est.)*)
   into templates, drafted with `extract_criteria` (D0, any allowed route), and promoted to `curated` only after human
   review.
3. **Site G1 approvals.** Every frozen ruleset adds its matched entries' history and its new entries, as `approved@site`.

*Sharing.* The library contains no PHI. `curated` entries ship with the product bundle. `approved@site` history MAY be
exported to alliance boxes as a signed pack, reviewed at G1 on import (as ML-12).

**Concept-normalisation targets per domain.**
- **What is measured.** Accuracy is top-1 exact-code agreement with the gold code set, after edition expansion.
  "Top-5 recall" is the share of criteria whose gold code is among the five candidates shown to the G1 reviewer.
- **Gold set.** Chia-derived, with codes mapped to the TW systems by two annotators. Planned size: ≥ 400 concept
  mentions per domain *(est.)*.
- **Floors.** They are binding from the round-3 review.

| Domain | TW target systems | JP target systems (MS6) | MS1 floor (top-1) | MS4 target (top-1) | Top-5 recall | Published comparator |
| --- | --- | --- | --- | --- | --- | --- |
| Drug | ATC; NHI drug codes; TFDA licence | YJ / HOT codes | ≥ 0.80 | ≥ 0.90 | ≥ 0.97 | GPT-4 OMOP concept mapping 48.5 %, USAGI 32.0 % (JMIR Med Inform 2025) |
| Condition | ICD-10-CM TW 2014 + 2023; SNOMED CT where licensed | MEDIS standard disease names; ICD-10 | ≥ 0.70 | ≥ 0.85 | ≥ 0.95 | C2Q entity normalisation 0.51; C2Q 3.0 concept F1 0.891 (entity level) |
| Measurement | LOINC + LOINC-TW mapping; site lab dictionary | JLAC10/11 | ≥ 0.65 | ≥ 0.80 | ≥ 0.95 | as above |
| Procedure | ICD-10-PCS; NHI fee codes | 診療行為 master codes | ≥ 0.65 *(est.)* | ≥ 0.75 *(est.)* | ≥ 0.93 | as above |
| Attribute / observation values | registry SSF codes; LOINC answer lists; SNOMED qualifiers | JP registry codes | ≥ 0.70 *(est.)* | ≥ 0.85 *(est.)* | ≥ 0.95 | none published |

Normalisation uses retrieval over the loaded terminologies, then a reranker, then `concept_select` among the hits. It
never uses codes from model memory. A code absent from the loaded terminology fails the build. The hallucinated-code
target is therefore 0 by construction, and it is tested.

**LLM functions.** `match_criterion_library`, `extract_criteria`, `concept_select` and `answer_protocol`, all D1, on-prem by
default (J by day, V by night). A cloud route needs both a topology-C policy permitting D1 for the role and the
sponsor's written consent for that protocol (FR-M1-15). No model writes SQL, CQL or CIRCE, and no model sets a
parameter value: the span parser reads parameters and a model's reading is only checked against it.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M1-1 | The box MUST accept protocols as PDF (text or scanned), DOCX, ICH M11 structured protocol, CDISC USDM JSON, a ClinicalTrials.gov record, or pasted text, in English, Chinese or Japanese. It MUST locate the I&E sections and the schedule of activities (SoA). | T | MS1 (USDM MS4) |
| FR-M1-3 | Concept mapping MUST use `tb.vocab.search` results only; no codes from model memory. Every code is checked to exist in the loaded terminology. Codes are expanded across ICD editions via the official mapping. | T | MS1 |
| FR-M1-5 | Ambiguities (undefined thresholds, unit-less values, "adequate organ function", "per investigator judgement") MUST be listed with a proposed default. The CRC confirms or edits by numbered reply. | T | MS1 |
| FR-M1-6 | The criteria workbook MUST show, per criterion: <br>• the text in the protocol language and the site language; <br>• the source span and IR summary; <br>• ValueSets, computability and filter class; <br>• the aggregate count on the current snapshot. <br>The SQL/CQL text is in a hidden sheet for QA. G1 freezes the ruleset (Git tag + SHA). | T | MS1 |
| FR-M1-7 | Protocol amendments MUST produce a criterion-level diff against the previous version. After re-approval, open candidates are re-evaluated and consent re-versioning is flagged (FR-M6-6). | T | MS4 |
| FR-M1-8 | The SoA MUST be digitised into a USDM-lite structure (visits, windows, procedures, NHI fee-code mapping candidates) for M7. | T | MS4 |
| FR-M1-10 | **Protocol Q&A (`ASK`).** A delegated user MAY ask a question about a study's protocol in any supported language. <br>• The answer MUST be built only from retrieved protocol passages (`tb.protocol.search`). <br>• It MUST quote and cite each passage (section number + quote in the protocol language). <br>• It ends with "Per protocol section X" and states that the investigator and sponsor decide. <br>• With no supporting passage, the answer is "The protocol does not say; ask the sponsor (draft question attached)". <br>• No patient data is used. | T | MS1 |
| FR-M1-11 | *(Replaces FR-M1-2.)* **Match-then-draft.** Every segmented criterion MUST first be retrieved against the library (BM25 + bge-m3, top-20, reranked to top-5) and classified by `match_criterion_library` as `match`, `variant` or `none`. <br>• **`match` / `variant`:** the entry's IR is reused. Every slot is filled by the deterministic span parser (ML-3) from the protocol span. If the model's reading disagrees with the parser, the criterion becomes a numbered question. <br>• **`none`:** `extract_criteria` drafts IR v3 with source spans. <br>The workbook shows each criterion's library status: matched entry id and status, variant diff, or "new". | T | MS1 |
| FR-M1-12 | **Independent check.** Every criterion that is drafted, a `variant`, matched to a `seed` entry, or `safety_critical` MUST be extracted a second time by `extract_criteria` on the V build (night pass), without seeing the first result. <br>• Any structural difference (atoms, operators, windows, anchors, domains, codes) becomes a numbered question. <br>• Criteria matched to `curated` or `approved@site` entries with an identical slot fill skip the V check. <br>• Agreement is recorded per criterion in `provenance`. | T | MS1 |
| FR-M1-13 | **Library store.** The library MUST be implemented in `services/criteria_compiler/library/` with the fields and statuses above. <br>• Entries are immutable. A change creates a new version linked to its predecessor. <br>• Each entry's equivalence fixtures run in CI. <br>• `trialbox library export --signed` produces the shareable pack (no PHI; site history in rounded counts). | T | MS1 |
| FR-M1-14 | *(Replaces FR-M1-4.)* Every criterion MUST be classified `structured`, `note` or `human`. It MUST be annotated with: <br>• `depends_on`, `lexicon_keys`, `computability`, `filter_class`, `canonical_hash`, `flip_rule`, `anchor`; <br>• `s2b_question` (the embedding text for S2b, in protocol and site language); <br>• `zero_hit_exclusion: allowed \| off` (from SAFE-9); <br>• `library_ref`. <br>The understanding email states computability in plain words ("we can check this for about 63 % of patients") and names criteria that will rely on notes. | T | MS1 |
| FR-M1-15 | *(Replaces FR-M1-9.)* Protocol text is class D1 (sponsor-confidential). <br>• It MUST be processed only on routes the §8 routing policy allows for D1. <br>• A cloud route requires the sponsor's written consent for that protocol, recorded on the Study Card with the document reference. The default is off. <br>• The gateway audit record of every M1 call names the class and the route. | T, I | MS1 |
| FR-M1-16 | **IR v3 coverage.** The extractor and compiler MUST support every construct of the IR v3 table above, at the milestone given there. Each construct has: <br>• a CQL template; <br>• a SQL template; <br>• a CIRCE JSON template where OMOP can express the construct; <br>• fixtures in `rulesets/ATOMS_V3` passing the equivalence gate. <br>A construct that CIRCE cannot express is marked `circe: n/a` in the manifest, never approximated. | T | MS1 |
| FR-M1-17 | **Run-time anchors.** A ruleset with `screening` or `randomization` anchors MUST be evaluated with an explicit anchor date per patient run, as in the construct table (feasibility offset: site parameter `screening_offset_days`, default 14), recorded in the evidence. Changing the anchor re-evaluates only the affected pairs (dirty set, §4). | T | MS1 |
| FR-M1-18 | **Calculator library.** Derived atoms MUST call versioned calculators in `libs/tb_common/derived.py`, extended to `libs/tb_common/calculators/`. Each calculator declares: <br>• its formula and reference publication; <br>• its inputs with LOINC codes and units; <br>• its window defaults and missing-component rule. <br>The same constants render the CQL helper library and the SQL templates (v1 pattern). Values are compared unrounded. | T | MS1 |
| FR-M1-19 | **Organ-function macro.** "Adequate organ function" and similar phrases MUST expand to an explicit lab panel as in the construct table. Each threshold carries its own span; a default panel is used only after confirmation as an ambiguity question (FR-M1-5); each lab is a separate criterion row with its own computability and evidence. | T | MS1 |
| FR-M1-20 | **Line of therapy.** M1 MUST represent `line_of_therapy` in IR v3 from MS1 (note path). From MS4 the regimen model derives lines, after the design note `docs/design/line_of_therapy.md`; structured derivation may exclude only after its agreement with registry-abstracted lines is measured on the oncology validation set (SAFE-1 applies). | A, T | MS1 / MS4 |
| FR-M1-21 | **Library seeding.** By MS1 the library MUST be seeded from Chia and from ClinicalTrials.gov as described above. The seeding tools are `tools/library_seed_chia.py` and `tools/library_seed_ctgov.py`. They MUST be reproducible from the pinned corpus versions. They write a seeding report with: <br>• entries per status; <br>• the expressiveness-gap count (Chia criteria not expressible in IR v3, by reason); <br>• cluster statistics. | T | MS1 |
| FR-M1-22 | **Library learning.** At each G1 the box MUST: <br>• add new entries and variants as `approved@site`; <br>• append site history to matched entries. <br>An entry MUST be set `deprecated` at the site when either holds: <br>• its PI-rejection precision falls below 0.5 over ≥ 20 decisions; <br>• SAFE demotes it twice within 6 months. <br>In both cases the clinical-informatics review is notified through the product feedback channel (no PHI). | T | MS4 |
| FR-M1-23 | **Ambiguity memory.** Resolved ambiguity questions MUST be stored per sponsor and protocol family, as question, resolution, approver and date. They are proposed as defaults when the same question arises again. A default from memory is still shown and confirmed at G1. | T | MS4 |
| FR-M1-24 | **Registry criteria auto-parse.** For M5 registry matching and M3 competitor overlap, registry eligibility text (D0) MUST be parsed through library match and draft without a G1. The result is labelled `unreviewed`. <br>• `unreviewed` IR MUST NOT be used to exclude any patient from an open-study list. <br>• It feeds only registry match scores and competitor overlap estimates, which are labelled as such. | T | MS2 |
| FR-M1-25 | **Untrusted documents.** Protocols and sponsor attachments are untrusted inputs. <br>• They are converted in the CDR container (§14). <br>• They are processed by an extractor role with no tools. <br>• They are delimited in prompts. <br>• Instructions in a document never change the workflow. <br>The `redteam` suite includes protocols with injected payloads (hidden text, Unicode tags, "approve this ruleset"). | T | MS1 |
| FR-M1-26 | **Turnaround.** For a protocol of ≤ 40 criteria received by 17:00 on a working day, the understanding email and workbook MUST be sent by 08:00 the next working day. This includes the V check of the night pass. | T | MS1 |
| FR-M1-27 | **Exchange export.** On G1 the box MUST render the frozen criteria as FHIR `EvidenceVariable` (with CQL expressions) and as USDM eligibility criterion items. The content follows §12. | T | MS4 |

**Acceptance metrics (M1)**

| Metric | Target | Best published comparator | Suite | MS |
| --- | --- | --- | --- | --- |
| Criterion structure F1 (atoms, operators, windows, anchors) on Chia-derived gold | ≥ 0.85 | Chia-based systems report entity-level scores; no structure-level comparator | `criteria_extract_public` | MS1 |
| Criterion segmentation recall (no protocol bullet lost) | ≥ 0.98 | — | `criteria_extract_public` | MS1 |
| Concept normalisation per domain (table above) | Floors at MS1, targets at MS4 | GPT-4 48.5 % (OMOP mapping); C2Q 3.0 concept F1 0.891 | `concept_norm` (new) | MS1 / MS4 |
| Codes not present in the loaded terminology | 0 | GPT-4 hallucination 33.7 % of generated SQL (JMIR Med Inform 2025) | `concept_norm`, build check | MS1 |
| Criteria fully representable without `human` (50-protocol sample, 5 areas) | ≥ 0.80 *(est.)* | 51 % of inclusion criteria fully implementable in OHDSI ATLAS | `ir_coverage` (new) | MS4 |
| Library match share (`match` + `variant`) after 20 site protocols | > 0.60 | none (no product reuses approved criteria) | library report | MS4 |
| CQL ≡ SQL on `ATOMS_V3` | 100 % | — | `sql_cql` | MS1 |
| `ASK` answers citing a passage, or saying "not stated" when none exists | 100 % citation; "not stated" correct ≥ 0.95 on the protocol-QA set | — | `protocol_qa` (new) | MS1 |

---

### 10.2 M2: Protocol optimisation

**Purpose.** M2 shows the PI, the research office and (after G2) the sponsor which criteria cost patients at this site,
and what relaxing a criterion would add and risk. Each figure has its source:
- criterion impact comes from the deterministic stages S0–S2;
- note-dependent impacts come from sampled S3/S4 estimates (CAS-8);
- relaxation risk comes from site-observable safety proxies.

M2 never proposes relaxing a `safety_critical` criterion. Its outputs feed the feasibility pack (§12); M2 does not
release them itself.

**Inputs and outputs**

| Direction | Item | Class |
| --- | --- | --- |
| In | Frozen or draft ruleset; snapshot; Atlas computability; library parameter distributions | D1 / D3 (lake, in-perimeter) |
| Out | Criterion-impact table: <br>• alone-excludes; <br>• drop-one gain; <br>• funnel position; <br>• unknown rate; <br>• safety-proxy delta; <br>• registry benchmark. | D1 (rounded aggregates) |
| Out | `WHATIF` variant results (internal only) | D1 |
| Out | Optimisation memo (narrative with placeholders) | D1 |

**LLM functions.** `draft_narrative` (D1 aggregates) writes the memo, with placeholders checked by `numbers_match`
(AI-07). Every number in M2 comes from deterministic code. M2 runs no model on patient data beyond the CAS-8 sample
estimates it reuses from M3.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M2-1 | For any ruleset the box MUST compute, per criterion: patients excluded by it alone, drop-one gain, and its funnel position, on S0–S2 (no model). | T | MS1 |
| FR-M2-2 | What-if (`WHATIF`) MAY disable a criterion or change a threshold. It re-runs on the same snapshot and is marked internal-only. It is limited to 10 variants per study per snapshot (PRIV-21, PRIV-23). It is never released externally without a fresh packet through G2. | T | MS4 |
| FR-M2-3 | **Counterfactual relaxation with safety proxies.** For each non-`safety_critical` criterion, the box SHOULD report (Trial Pathfinder approach): <br>• the pool gain; <br>• the change in site-observable 90-day outcome proxies among the added patients. <br>The proxies are ED visits, admissions, and lab excursions beyond CTCAE grade 3 thresholds as already flagged by the hospital lab system. Results are rounded aggregates within the privacy budget. | T | MS4 |
| FR-M2-5 | **Unknown-rate disclosure.** The impact table MUST show, per criterion, the share of the population for which the criterion is `unknown` after S2, with the reason (data absent, data stale, note-only). A criterion with unknown rate > 0.30 is flagged "count depends on chart review" in every derived figure. | T | MS1 |
| FR-M2-6 | **Registry benchmark.** For each criterion with a library match, the box MUST report how its parameters compare with the same entry across registry trials of the same phase group and therapeutic area. Example: "eGFR ≥ 60 is stricter than in 72 % of 340 comparable trials" *(illustrative wording)*. The computation is deterministic over library slot values (D0). Fewer than 20 comparable trials → not shown. | T | MS4 |
| FR-M2-7 | **Overlap and redundancy.** The box MUST compute pairwise overlap of exclusion sets on S0–S2: Jaccard index, and the share of one criterion's exclusions also excluded by the other. Criteria whose exclusions are ≥ 0.95 contained in another's are listed as "adds little at this site". | T | MS4 |
| FR-M2-8 | **Amendment simulation.** Given draft amendment text, the box MUST: <br>• run M1 diff and compile (no G1); <br>• compute the M2 impact on the current snapshot; <br>• report the change in eligible pool and in projected enrolment (M3). <br>The result is marked "draft amendment, internal only". | T | MS4 |
| FR-M2-9 | **Locked criteria.** The compiler MUST set `safety_critical` from the library flag and from defaults: <br>• pregnancy and lactation; <br>• hypersensitivity to the investigational product or class; <br>• organ-function safety thresholds; <br>• QTc limits; <br>• active serious infection. <br>The PI MAY add criteria at G1. Only the PI MAY remove the flag, with a recorded reason. M2 MUST NOT list a locked criterion as a relaxation candidate. | T | MS1 |
| FR-M2-10 | **Figure data objects.** M2 MUST emit the data objects for the tornado chart, criterion waterfall and overlap heatmap, rendered per §12. | T | MS1 |
| FR-M2-11 | **Representativeness under relaxation.** For each relaxation candidate, the box SHOULD report the change in the representativeness profile of FR-M3-21, as rounded deltas. | T | MS5 |

**Acceptance metrics (M2)**

| Metric | Target | Comparator | Suite | MS |
| --- | --- | --- | --- | --- |
| Drop-one and alone-excludes counts reproduced exactly by an independent SQL implementation on Synthea 300k | 100 % | — | `m2_replay` | MS1 |
| `safety_critical` criteria ever listed as relaxation candidates | 0 | — | `m2_locked` | MS1 |
| Privacy-accountant violations in M2 outputs | 0 | — | `privacy` | MS1 |

---

### 10.3 M3: Feasibility, recruitability and the sponsor questionnaire

**Purpose.** A funnel of counts is necessary, but it does not answer the sponsor. The sponsor's question is: "how many
patients can this site randomise per month, with what confidence, and on what evidence?" M3 answers it with the
eligible pool from the cascade; a **recruitability model** (eligible → reachable → approachable → consent → screen
pass); a **forecast ledger** that scores every projection against what happened; representativeness and competing
trials; and questionnaire autofill with answer memory.

The deliverables (feasibility pack sections, figures, formats) are specified in §12. M3 produces their data objects.

**Inputs and outputs**

| Direction | Item | Class |
| --- | --- | --- |
| In | Frozen ruleset (G1); snapshot; Atlas; appointments and visit history | D1 / D3 (in-perimeter) |
| In | Site history from M6 (pipeline transitions of closed and open studies) | D3 → aggregated |
| In | Published priors file `site/priors/recruitability_priors.yaml` | D0 |
| In | Registry mirror (competing trials); site CTMS list of open studies | D0 / D1 |
| In | Sponsor questionnaire (XLSX, DOCX, PDF form) | D1 |
| Out | Feasibility data object (§6): funnel, tier estimates with intervals, recruitability stages, monthly p10/p50/p90, assumptions, calibration record, competing trials, representativeness, data-availability disclosure | D1 (rounded, accountant-checked) |
| Out | Forecast-ledger entry | D1 |
| Out | Filled questionnaire with provenance sheet; answer-memory updates | D1 |

**The recruitability model (normative).** The projection is a chain of stages. Each stage is either computed
deterministically from data or estimated with an explicit prior, and the packet states which.

| Stage | Definition | How it is obtained | Uncertainty carried |
| --- | --- | --- | --- |
| 1. Eligible | Prevalent eligible pool at T0, plus incident eligible flow per month | Cascade S0–S2 on the full population. S3/S4 on the stratified sample (CAS-8). Eligible = strong + w × potential, where w = P(potential resolves eligible): <br>• from the site's ledger of resolved `potential` candidates per criterion type; <br>• prior Beta(2, 3) *(est.)* until ≥ 30 are resolved. <br>Incident flow: monthly new index-condition patients over 24 months who pass S0–S2, with month-of-year seasonality. | Sample interval (CAS-8); Gamma-distributed incident rate (Poisson–Gamma, Anisimov & Fedorov 2007) |
| 2. Reachable | Alive, and seen at the site in the last 12 months, and with local follow-up (≥ 2 encounters at the site in 24 months), and likely to visit within the enrolment window | Deterministic filters from the lake. Each patient's probability of a visit within the window comes from: <br>• booked appointments where they exist; <br>• otherwise the empirical inter-visit distribution of their department and diagnosis group. <br>In the TRE zone (no appointments), visit cadence only. | Per-patient Bernoulli |
| 3. Approachable | Not opted out for `contact`; not allocated to a competing study; the PI acts on the candidate | Opt-outs: deterministic (consent scopes). Competing allocation: the PI's declared priority among overlapping open studies at the site (FR-M3-20), as a share a_c. PI action rate: hierarchical Beta-Binomial on G3 `confirm` → `contacted` transitions. | Beta posterior |
| 4. Consent | Consents, given approach | Hierarchical Beta-Binomial on `contacted` → `consented` | Beta posterior |
| 5. Screen pass | Randomised, given consent | Hierarchical Beta-Binomial on `consented` → `randomized`. The screen-fail reasons of closed studies inform it (FR-M4-11). | Beta posterior |

*Hierarchical Beta-Binomial* (`services/feasibility/recruitability/model.py`). For stages 3–5, θ is estimated over
four levels: published prior → site → therapeutic area × phase group (I/II, III/IV) → study. Each level takes the
parent posterior Beta(a, b), down-weights it to Beta(a·k, b·k) with k = min(1, κ_max/(a+b)), and adds its own counts.
Defaults: κ_max = 20 at site and 10 at area level *(est.)*; a published prior enters with its declared effective sample
size κ₀ (default 10). The scheme is closed-form and deterministic, and keeps a site with long history from becoming
overconfident about a new area. A full Bayesian fit (NumPyro, fixed seed) runs as a shadow check; the report shows both
when their p50s differ by > 20 %.

*Published priors from day one.* `site/priors/recruitability_priors.yaml` ships with the product.

| Element | Content |
| --- | --- |
| Row fields | `stage`, `therapeutic_area`, `phase_group`, `setting` (academic/community; country), `mean`, `kappa0`, `source` (citation with DOI or URL), `population`, `year`, `notes` |
| Without a citation | A row is labelled `expert_default`, shown as such in the packet, and counts as "defaults" in the assumptions statement |
| Before MS1 | Every row used by the first site's therapeutic areas MUST carry a citation. Candidate sources include: <br>• the RECTIFIER randomised trial (eligibility determination 20.4 % vs 12.7 %; enrollment 1.6 % vs 0.9 %); <br>• published screen-failure and consent-rate meta-analyses for the area; <br>• the site's own pre-TrialBox enrolment logs entered at onboarding. |
| Fixed by this spec | No numeric prior value. Values are data, reviewed at G5. |

*Projection* (one method, stated once: `libs/tb_analytics/forecast.py`: stage probabilities per §10.3; monthly rate λ moment-matched to Gamma and propagated as the Poisson–Gamma predictive (§12.3.4); 10,000 seeded paths; seed from the packet id). Stage probabilities θ_approach, θ_consent,
θ_screen come from their posteriors; each path simulates month by month the prevalent pool depleted by approach, incident
arrivals drawn from the Poisson–Gamma predictive, per-patient visit probability, and binomial thinning through stages 3–5. Outputs:
p10/p50/p90 per month and at 12 months, the time-to-target distribution, P(target by plan), and the one-at-a-time
sensitivity of p50 to each assumption (the "what drives this forecast" tornado, §12).

*Forecast ledger* (one table `forecast_ledger`, one writer `services/tracking/ledger.py`, FR-M6-12). Every released projection is stored with its inputs hash,
model version, cumulative-count quantiles at months 3, 6, 9 and 12, P(target by plan) and the PI's estimate if given.
M6 supplies actuals monthly (§10.6). Scores: **CRPS** of the cumulative count, **PIT** and **80 % interval coverage**,
and the **Brier** score of "target by plan", for the box and for the PI.

**Representativeness.** Eligible pool versus condition population, by age band, sex, comorbidity burden (Charlson from
coded diagnoses), NHI insured category where recorded (e.g. catastrophic-illness certificate 重大傷病, low-income),
county/city of residence (generalised) and preferred language where recorded. Headings follow FDA's diversity action
plan guidance *(draft; final status uncertain)*.

**LLM functions.** `map_questionnaire` and `draft_narrative` (D1); `judge`/`second_opinion` on the feasibility sample
belong to the cascade (D3, on-prem). No model computes any number, prior, rate or interval.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M3-1 | `FEAS` MUST produce the feasibility packet (§6) by 08:00 on the first working day after G1, for a ruleset of ≤ 40 criteria on ≤ 3M patients on the reference profile (§13). | T | MS1 |
| FR-M3-2 | Counts MUST be produced by the cascade (CAS-8): full population for S0–S2; stratified sample for S3–S4; tier estimates with 95 % intervals. | T | MS1 |
| FR-M3-5 | Investigator suggestions MUST rank investigators by: <br>• candidate count in their clinics (published as rounded bands; exact counts only internally); <br>• past trials in the area; <br>• current load. | T | MS1 |
| FR-M3-6 | **Questionnaire autofill with answer memory.** Given a sponsor questionnaire (XLSX, DOCX, or a PDF form), the box MUST map each question to a packet path, a site-profile field or an **answer memory** entry. An answer-memory entry is a previously approved answer to the same SIP field, with a validity date. <br>• It fills the answers and attaches a provenance sheet listing source path, data cut, rule version and memory reference. <br>• The mapping is learned per sponsor template and confirmed once by the CRC. <br>• Unmapped questions are listed and never invented (AI-08). | T | MS1 |
| FR-M3-7 | "What changed since your last answer to this sponsor": when a sponsor sends a new questionnaire, the box MUST list answers that differ from the last released set, with reasons (new data cut, profile change). | T | MS4 |
| FR-M3-8 | Every released number MUST pass the disclosure profile of its recipient class (§12.2; sponsor default: 1–10 shown as `<11`, other counts rounded to base 5; internal: v1 `round_count`, `<5`), complementary suppression (§7) and the privacy accountant (§7). | T | MS1 |
| FR-M3-9 | External release MUST pass G2 and be logged with recipient, content hash, packet id and privacy-ledger entry. | T | MS1 |
| FR-M3-10 | **Site qualification pack:** site profile, past performance per area (enrollment versus target, time to first patient, screen-fail rate, all rounded), and start-up timelines, ready to attach to the sponsor reply. | T | MS4 |
| FR-M3-11 | **AI disclosure (CMP-34).** Every external packet MUST include a one-paragraph disclosure stating: <br>• that AI-assisted pre-screening is used at the site; <br>• how eligibility is decided (by the investigator); <br>• the current recall certificate statement. | T | MS1 |
| FR-M3-12 | **Computable feasibility exchange.** A sponsor MAY send criteria as M11/USDM or FHIR `EvidenceVariable`. The box answers **by email**, after G2, with the same packet plus a machine-readable attachment (rounded, accountant-checked, recall-certified, manifest hash; formats per §12). There is no inbound API. | T | MS5 |
| FR-M3-13 | **Recruitability stages.** Every projection MUST be computed through the five stages of the recruitability table. The data object lists, per stage: <br>• the count or rate; <br>• its source (`data`, `site_history(n)`, `area_history(n)`, `published(citation)`, `expert_default`); <br>• its interval. <br>A stage whose source is `expert_default` is named in the packet's assumptions statement. | T | MS1 |
| FR-M3-14 | **Hierarchical Beta-Binomial from day one** (brought forward from R2). Stages 3–5 MUST be estimated with the four-level hierarchy and caps above; fitted parameters per level are stored with the forecast. | T, A | MS1 |
| FR-M3-15 | **Priors file.** The box MUST load `site/priors/recruitability_priors.yaml`, validate it against its JSON Schema, and refuse a row with no `source` unless it is marked `expert_default`. The file is versioned in Git; changes are G5. The packet's methods section lists the priors used, with citations. | T | MS1 |
| FR-M3-16 | **Projection.** The projection MUST be computed by `libs/tb_analytics/forecast.py`: stage probabilities per §10.3; monthly rate λ moment-matched to Gamma and propagated as the Poisson–Gamma predictive (§12.3.4); 10,000 seeded paths, over 12 months or the planned enrolment period if longer, and be byte-identical on re-run. | T | MS1 |
| FR-M3-17 | **Forecast ledger.** Every projection released at G2 and every monthly re-projection (FR-M3-24) MUST be written, immutably, to `forecast_ledger` through its single writer `services/tracking/ledger.py` (FR-M6-12), with the fields above plus the priors version. | T | MS1 |
| FR-M3-18 | **Scoring.** At months 3, 6, 9 and 12 of recruitment and at close, the box MUST score each ledger entry and each PI estimate against M6 actuals (CRPS, PIT, 80 % coverage, Brier), for the QA pack and the calibration record. | T | MS4 |
| FR-M3-19 | **Calibration display.** With ≥ 5 studies scored at 12 months or close, every feasibility pack MUST include the site's calibration record: PIT histogram, 80 % coverage, slope of actual on p50, and Brier versus PI estimates, by therapeutic area with n. Below 5 it says "no calibration record yet (n = k)". | T | MS4 |
| FR-M3-20 | *(Replaces FR-M3-4.)* **Competing trials.** The box MUST list competing trials from: <br>• the local registry mirror (ClinicalTrials.gov API v2; the Taiwan clinical-trial registry where machine-readable *(availability uncertain)*; jRCT for JP at MS6); <br>• the site's own open-study list, filtered by condition, phase, status and location. <br>For each competitor with eligibility text, the box auto-parses its criteria (FR-M1-24) and evaluates S0–S2 on the same population. It reports the **overlap**: the share of this study's S0–S2 pool also in the competitor's, with interval, labelled `unreviewed criteria`. For overlapping studies open at the site, the PI MAY declare an allocation priority (one reply line). Stage 3 uses it. | T | MS1 (overlap MS2) |
| FR-M3-21 | *(Moved from FR-M2-4; brought forward from R3.)* **Representativeness.** The box MUST report the eligible pool versus the condition population by the dimensions above, as rounded distributions with percentage-point gaps and intervals, never adjusted silently. Small cells are suppressed so that they cannot be back-calculated (accountant). | T | MS4 |
| FR-M3-22 | **Data-availability disclosure.** For every criterion, the packet MUST state its computability and unknown rate (FR-M2-5). It MUST also state how many eligible-pool patients depend on chart review to be confirmed. The headline eligible count MUST NOT include `potential` patients unweighted. | T | MS1 |
| FR-M3-23 | **PI estimate capture.** At G2 the box MUST invite the PI to state their own 12-month enrolment estimate in one reply line (`ESTIMATE <study> <n>`, proposed by Hermes from plain words). The estimate is stored in the ledger and never shown to the sponsor without the PI's approval. | T | MS2 |
| FR-M3-24 | **Monthly re-projection.** During recruitment, the projection MUST be recomputed monthly. The update conditions on actual pipeline counts to date and on the current pool. The Monday digest (M6) and the accrual pack (§12) use the latest ledger entry. | T | MS4 |
| FR-M3-25 | **Feasibility on de-identified data.** At MS1, `FEAS` MUST run on a `deidentified`-zone source (CGRD-type, FR-M0-22) with stage 2 computed from visit cadence only, and the packet labels this. Results from the TRE are aggregates. They pass the accountant and G2 like any other packet. | T | MS1 |
| FR-M3-26 | **Answer memory governance.** Each answer-memory entry MUST carry its SIP field or question fingerprint, value, source, approver, approval reference and validity date. Expired entries are not used and the question is listed for refresh; count-derived entries expire with their data cut. | T | MS1 |
| FR-M3-27 | **Turnaround.** The time from a sponsor's request (questionnaire or criteria received) to a G2-ready pack MUST be ≤ 2 working days for ≤ 40 criteria, excluding time waiting on G1 replies. | T | MS4 |

**Acceptance metrics (M3)**

| Metric | Target | Best published comparator | Suite / evidence | MS |
| --- | --- | --- | --- | --- |
| Tier-estimate interval coverage in validation replay (true count from full adjudication of the replayed sample frame) | ≥ 0.90 at nominal 95 % *(est.)* | none published | `feas_replay` (§16) | MS1 |
| 80 % forecast-interval coverage, scored studies | 0.70–0.90 after ≥ 10 studies | none: no prospectively calibrated site forecast published | forecast ledger | MS6 |
| Calibration slope (actual on p50, 12 months) | 0.8–1.2 after ≥ 10 studies (review); on ≥ 20 trials by MS6 | Deep Poisson–Gamma duration MAE 7.52 months (preprint); none site-level | forecast ledger | MS6 |
| Brier score, "target reached by plan" | ≤ 0.25 *(est.)* and below the PI estimates' Brier on the same studies | PI forecasts Brier 0.38 (PLoS One 2022) | forecast ledger | MS6 |
| Questionnaire questions auto-answered on a known template (after first confirmation) | ≥ 0.70 *(est.)* | none peer-reviewed | `qfill` | MS4 |
| Invented questionnaire answers | 0 | — | `qfill` | MS1 |
| Request → G2-ready pack | ≤ 2 working days | vendors claim "minutes" (unverified) | workflow log | MS4 |

---

### 10.4 M4: Pre-screening and recruitment

**Purpose.** For every recruiting study, M4 finds the patients who are likely to be eligible. It does so before they
come to clinic, and it gives investigators the evidence and a fast way to decide. The working unit is the **clinic
day**:
- each practitioner receives one consolidated list per clinic day, across all their recruiting studies;
- each candidate carries per-criterion evidence;
- each candidate is in a tier that tells the CRC what kind of work remains.

M4 never contacts patients. It never decides eligibility: the investigator decides (G3), and the box records the
decision.

**Tiers (v4).** `potential` is split by the reason the candidate is not `strong`. The tier rules are deterministic
(§6 candidate object).

| Tier | Rule | What the packet shows | Ranking within tier |
| --- | --- | --- | --- |
| `strong` | Every criterion that can be evaluated before screening is met: <br>• every structured inclusion passes; <br>• no exclusion matches; <br>• every note criterion is affirmed with verified evidence (multi-span allowed), rule-assertion agreement and S4 agreement. <br>Only `verify_at_screening` and `pending_human` (human criteria) remain. | Per-criterion evidence; the investigator checklist for human criteria | Next appointment date |
| `potential:uncertain` | No hard failure, and ≥ 1 criterion where evidence exists but the judgement abstained. Causes: <br>• nonconformity above the LTT threshold; <br>• J/V disagreement; <br>• assertion disagreement; <br>• quote verification failure. | Both quotes, side by side, with the question to resolve | Nonconformity rank; review depth k (FR-M4-17) |
| `potential:data_gap` | No hard failure; no abstained criterion; ≥ 1 criterion `unknown` because the required data are absent or stale. Causes: <br>• a structured value outside its window; <br>• a missing calculator input; <br>• a note criterion with no relevant text after S2/S2b where the IR requires `evidence_of_absence`. | What is missing, the window it must fall in, the date the latest value expires, and the next appointment | Fewest gaps first, then next appointment |
| `watchlist` | Fails only criteria with a `flip_rule`, and the flip date falls inside the enrolment window | Flip date, flip reason, next visit | Flip date |
| `excluded` | A hard failure | Not listed for the PI; part of the recall audit population (§10.14) | — |

A candidate with both an abstained criterion and a data gap is `potential:uncertain`, and its data gaps are listed. The
box never tells an investigator to order a test for research purposes outside the protocol and the IRB plan (FR-M4-13).

**Inputs and outputs**

| Direction | Item | Class |
| --- | --- | --- |
| In | Frozen rulesets of recruiting studies; snapshot T; same-day appointment events (SIU/CDC, §5); consent scopes | D1 / D3 |
| In | Delegation log; practitioner–clinic map | D1 |
| In | G3 decisions (reply lines, the decision sheet, or the optional review page); five-minute review answers | D3 (thread-bound) |
| Out | Clinic-day packet per practitioner. It holds: <br>• an encrypted XLSX decision sheet; <br>• one consolidated evidence PDF with bookmarks per candidate (quotes in the original language, glosses marked); <br>• the recall certificate statement. <br>Identifiers are rendered only as §7 allows for delegated investigators. | D4 (encrypted, internal recipients only) |
| Out | Non-PHI nudges ("3 candidates waiting for Tuesday's clinic") on Teams/LINE (§3) | D1 |
| Out | Optional CDS Hooks card (FR-M4-19) | D1 card text in the EHR context |
| Out | Decisions, reasons, screen-fail mapping, calibration and exemplar updates; ledger samples | D3 |

**LLM functions.** `judge` (S3) and `second_opinion` (S4), D3 on-prem only, as specified in §4 and §8; `embed` for
the S2b screen, thresholds calibrated per criterion type (§4); `classify_intent` for plain-language decision replies,
through Hermes or the native intake (§9), classed **D3** because the thread is bound to a candidate packet, with
MRN-like and name-like tokens redacted before Hermes sees the text (§7). The one-line candidate summary is a
deterministic template.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M4-1 | For each study with status `recruiting`, the box MUST run the cascade on the scoped population at the configured cadence (weekly default, nightly allowed) and on request. | T | MS2 |
| FR-M4-2 | **Portfolio clinic-day lists.** Each night, every patient with an appointment in the next N days (default 14) MUST be screened against all recruiting studies of that clinic's practitioners. The output is one consolidated list per practitioner per clinic day. The judgement cache shares note work across studies. | T | MS2 |
| FR-M4-5 | **G3 decisions.** The PI or a delegated sub-investigator MUST be able to confirm, reject (fixed reason code + free text) or defer each candidate, by reply line (`CONFIRM P0156`, `REJECT P0156 R02 on dialysis`) or by returned decision sheet (FR-UX-4). A CRC MAY add notes and `DEFER`, but not confirm or reject. | T | MS2 |
| FR-M4-6 | Patients with `research_use: deny` are removed at L3; `contact: deny` at S0 and list rendering (§7.13). Site default for patients without a record per DM-22/OD-08. The `nhi_secondary_use` scope applies to NHIA databases, and to the hospital's own data only if the site adopts it as policy (a site setting). | T | MS1 |
| FR-M4-7 | **Watchlist with flip dates.** For candidates failing only criteria with a `flip_rule`, the box MUST compute the flip date (washout end, next scheduled lab, age reached, window slide) and re-evaluate on that date, not on cadence. The PI sees "becomes possibly eligible on 12 Nov; next visit 14 Nov". | T | MS4 |
| FR-M4-8 | Rejection reasons MUST feed per-criterion precision estimates (§8). A criterion with a PI rejection rate > 30 % over ≥ 20 decisions MUST be flagged for review at the next G1. | T | MS2 |
| FR-M4-9 | The box MUST NOT contact patients. IRB-approved outreach materials MAY be attached to the PI packet. | T (no outbound to non-staff addresses) | MS2 |
| FR-M4-11 | **Screen-failure learning.** After screening, screen-failure reasons (M6) MUST be mapped to criteria. A criterion causing ≥ 3 screen failures that the cascade marked `pass` is flagged as a pre-screening blind spot, with the patients' evidence attached for QA. | T | MS4 |
| FR-M4-13 | *(Replaces FR-M4-10; brought forward.)* **`potential:data_gap`.** For each data-gap criterion the packet MUST state, by fixed template, the missing datum (code, lab or calculator input), its window relative to the anchor, the expiry date of the latest value and the next appointment ("eGFR within 28 days of screening is needed; the latest value (2026-09-02) expires for a screening on or after 2026-09-30"). The box never suggests ordering a test for research purposes outside the protocol and IRB plan. | T | MS2 |
| FR-M4-14 | *(Replaces FR-M4-4.)* **Routing and packet form.** Candidates MUST be routed to the investigator who owns the next appointment, or else the last visit. Each carries the date, the clinic and a one-line bilingual summary from template. <br>**Packet contents:** <br>• one encrypted XLSX decision sheet; <br>• one consolidated evidence PDF per packet, with a bookmark and page per candidate (quotes in the original language, with gloss). <br>A packet lists at most `max_candidates_per_packet` (default 20). Further candidates roll to the next packet; their count is stated. | T | MS2 |
| FR-M4-15 | *(Replaces FR-M4-3.)* **Per-criterion evidence.** Each candidate MUST carry per-criterion status and evidence (§6). <br>• A note-criterion affirmation needs verified evidence of ≤ 3 spans, possibly from different chunks. Each span must be quote-verified against canonical text and inside the window. <br>• The assertion rules MUST agree on every span that carries the asserted fact. <br>• `strong` requires S4 agreement on every note criterion. | T | MS2 |
| FR-M4-16 | **`potential:uncertain`.** For each abstained criterion the packet MUST show the note question in the site language, the J and V quotes side by side, and the abstention reason (`nonconformity`, `disagreement`, `assertion`, `verification`). A reply line (`RESOLVE P0156 C05 met\|not_met`) or the review page records the investigator's resolution, which feeds calibration and the exemplar bank (§8) and re-tiers the candidate in the next packet. | T | MS2 |
| FR-M4-17 | *(Replaces FR-M4-12.)* **Review depth (QBCB).** The `potential:uncertain` list MUST be ranked by nonconformity. The packet tells the CRC how deep to review: "review the top k; beyond that the chance of another candidate is below the certificate's target". k is computed with the quantile-based stopping rule of Lewis, Yang & Frieder (CIKM 2021). Its inputs are the ranks of blinded known positives (§10.14, line B), pooled per criterion type. Until ≥ 30 blinded positives exist for the type, k = the whole list. | T | MS4 |
| FR-M4-18 | **Decision handling through the conversation.** A PI or sub-investigator MAY reply in plain words in any supported language. Example: 「前兩位可以，第三位在洗腎」("the first two are fine, the third is on dialysis"). <br>**Proposal:** `classify_intent` proposes grammar lines in the same thread (e.g. `CONFIRM P0156 P0157` / `REJECT P0158 R02 on dialysis`) for one-word confirmation (`OK`). <br>**Who applies:** only the deterministic intake applies confirmed lines, as G3 approvals bound to the packet hash. Hermes and the model never apply a decision. <br>**Unmapped reasons:** a reason that maps to no reason code is proposed as `R07` with the free text. <br>**Unclear references:** a reply that names a candidate ambiguously gets one clarification question, never a guess. <br>**Class:** packet-thread replies are D3 and route on-prem only (FR-CONV-8). | T | MS2 |
| FR-M4-19 | **CDS Hooks card (optional, per site, off by default).** The box MAY expose a CDS Hooks 2.0 `patient-view` service, authenticated with SMART Backend Services, returning at most one card ("Possible pre-screening match: <study short title>, see this week's packet") only when the viewing practitioner is delegated on the study, the patient is a current `strong` or `potential` candidate, and the patient has not opted out of `contact`. The card carries no criteria, evidence or counts; its only link is the optional review page. Feedback is a signal, never a G3 decision. pid lookups use purpose `cds_card` and are audited. | T | MS5 |
| FR-M4-20 | **Study modes.** Each study MUST have `prescreen.mode: shadow \| silent \| live`. <br>• `shadow`: run and record; nothing is sent. <br>• `silent`: packets to the named CRC champion only, for comparison with the CRC's own pre-screening log. <br>• `live`: packets to investigators. <br>Mode changes are Level A approvals by the PI and the research office. The silent-mode comparison report (capture of CRC-logged candidates, with lower bound) is generated weekly. | T | MS2 |
| FR-M4-21 | **Same-day appointments.** When an SIU or CDC event books a patient into a clinic within the next 48 hours *after* the nightly run, the box MUST evaluate that patient: <br>• S0–S2 and the cache within 30 minutes *(est.)*; <br>• S3 only within the day-pass budget. <br>The practitioner gets an addendum to that clinic day's packet if the patient becomes a candidate. The addendum is suppressed during quiet hours (22:00–07:00 local, the FR-AG-10 site parameter). | T | MS3 |
| FR-M4-22 | **Budget truncation is visible.** If a run hits its budget (§4), the packet MUST state the number of unprocessed patients and the next scheduled processing time. Unprocessed patients never enter an `excluded` stratum (SAFE-13). | T | MS2 |
| FR-M4-23 | **Pre-screening log.** For each study the box MUST maintain a pre-screening log: candidates presented, decision, reason, transition to `contacted` and onward. Sponsor-facing copies are aggregate and rounded, released through G2 in the accrual pack (§12). | T | MS4 |
| FR-M4-24 | **Screen-fail mapping into the library.** Mapped screen-failure reasons (FR-M4-11) MUST also update the library site history (FR-M1-22) and per-criterion precision. A screen failure on a criterion the cascade `excluded` in another study is a recall event for the SAFE ledger (SAFE-17). | T | MS4 |
| FR-M4-25 | **Five-minute review.** Weekly, each CRC MUST receive ≤ 10 yes/no questions, chosen by expected information gain (§8). Blinded SAFE audit items (§10.14) are interleaved so that the reviewer cannot tell which items are audit samples. Answers are recorded per item with the reviewer and the blinding flag. | T | MS2 |

**Acceptance metrics (M4)**

| Metric | Target | Best published comparator | Suite / evidence | MS |
| --- | --- | --- | --- | --- |
| Criterion-level sensitivity / specificity on site notes, per language stratum | ≥ 0.95 / ≥ 0.90 (MS2, §16.4 owns the floor); ≥ 0.97 / ≥ 0.92 (MS4) *(est.)*; stratum gap ≤ 5 points | UTSW 2026: sens 0.98, spec 0.81, acc 0.94 (cloud GPT-4.x, English) | `judge_ml` (≥ 100 items per stratum) | MS2 |
| Silent-mode capture of CRC-logged candidates | ≥ 0.80 (95 % lower bound reported) | manual screening found 36.4 % of truly eligible (UTHSA, JAMIA 2026) | silent-mode report | MS3 |
| PPV of `strong` (PI confirm rate) on site charts | ≥ 0.70 in replay; ≥ 0.75 live (MS3) (§16.4); ≥ 0.80 (MS4) *(est.)* | 27/42 = 64 % on Japanese charts (Fujitsu/Nagoya-Gifu); TrialGPT local PPV 75 % | G3 log | MS3 |
| Certified known-positive recall, blinded line B, portfolio | lower bound ≥ 0.90 | none: no competitor or paper reports a certified bound | `recall_cert`, ledger | MS4 |
| CRC pre-screening time per clinic day, time-and-motion | −50 % versus the pre-TrialBox baseline | −42.6 % (TrialGPT), −55 % (TrialGPT 2.0), self-reported | time-and-motion study (§16) | MS3 |
| Evidence spans quote-verified | 100 % | LLM citations often fail to substantiate claims (2026 preprints) | `judge_ml`, runtime check | MS2 |
| Judgement-cache hit rate after 4 weeks, daily-note clinics (sentence-set key, §4) | > 0.80 | — | manifest metrics | MS4 |
| Cost per screened patient on owned GPUs, including amortisation | reported in NT$; < US$0.05 equivalent *(est.)* | US$0.02–0.12 cloud (RECTIFIER, UTSW) | `bench` cost model (§8) | MS3 |

---

### 10.5 M5: Matching in both directions

**Purpose.** One matching engine answers "which patients fit this trial?" (trial → patients, the cascade used by M3
and M4) and "which trials fit this patient?" (patient → trials): the site's **open studies** by their frozen rulesets,
and **registry trials** not open here by the TrialGPT port's retrieval and criterion-level judging. A **tumour-board
mode** runs patient → trials for a meeting roster. Both directions share the judgement cache, judge roles, evidence
schema, quote verification and tier logic, so they cannot disagree about a patient–criterion pair on one snapshot.
Open-study matching (FR-M5-6) is brought forward to MS2 in **silent mode only**, with a CRC champion, and goes live at
MS3; registry matching (FR-M5-7, FR-M5-9, FR-M5-11) and tumour-board mode (FR-M5-8) are MS4.

**Engine layout.** The engine lives in `services/matching/`. The TrialGPT port moves from the research branch
`claude/trialgpt-local-lcvm9p` (`trialgpt/trialgpt_local/`; not in this worktree, vendored by S1-17) as follows.

| v4 module | Content | Source in the port | Change from the port |
| --- | --- | --- | --- |
| `engine.py` | `MatchEngine`, with two entry points sharing cache, judge and evidence | — | new |
| `trial_to_patients.py` | Cascade S0–S5 entry point (M3/M4) | v1 cascade | unchanged |
| `patient_to_trials.py` | One patient → open studies + registry trials | `pipeline.py` | rewritten as durable steps (§11) |
| `registry_match/retrieval.py` | Hybrid retrieval with NCBI's settings: <br>• BM25 over 3 × title + 2 × conditions + text; <br>• MedCPT query/article encoders; <br>• reciprocal-rank fusion with k = 20 and keyword-priority weights 1/(i+1). | `retrieval.py` | offline indexes over the local mirror; `embed` via gateway; bge-m3 cross-lingual channel added |
| `registry_match/core.py` | Criterion-level matching and NCBI's `get_matching_score` and `get_agg_score` | `core.py`, `prompts.py` | production: TrialBox `judge`; NCBI prompts only in `--ncbi-faithful` benchmark mode |
| `registry_match/keywords.py` | Search keywords from the patient summary (`match_keywords`, D3, on-prem) | keyword generation in `core.py` | never sent outside the box |
| `registry_mirror/` | Nightly ClinicalTrials.gov API v2 mirror (D0); jRCT at MS6 | `ctgov.py` (live search) | **live search removed**: no patient-derived query leaves the box |
| `tumour_board.py` | Roster → per-patient one-pagers | — | new |
| `rank.py` | Deterministic ranking and tiering | `get_matching_score`, `get_agg_score`, `rank_results.py` logic | evidence-gated (below) |
| `eval/match_registry/` | SIGIR 2016, TREC CT 2021/2022 benchmark and the paper reference values | `benchmark.py`, `metrics.py`, `benchmarks/paper_reference.json` | becomes a CI suite |
| `eval/cgrd_match/` | Blinded physician validation in the TRE zone | `cgrd/` | de-identified zone only (FR-M0-22) |
| not ported | `app.py` web interface; `h2h/` comparisons | — | C-5′; external comparisons stay D0 research |

**Patient → trials algorithm (one patient, snapshot T).**
1. **Open studies.** Evaluate the patient against every recruiting study's frozen ruleset through S0–S4, with cache hits
   first. The result is a tier per study.
2. **Registry candidates.**
   1. Build a deterministic **patient summary** from structured facts: age band, sex, active coded problems, registry
      stage/histology/biomarkers, recent key labs, current systemic therapies.
   2. Optionally add `match_keywords`.
   3. Retrieve the top-K (default 100) from the local mirror, filtered by status `recruiting`, by country (default TW;
      configurable list) and by age/sex gates.
3. **Registry criteria.** Use the auto-parsed `unreviewed` IR (FR-M1-24) where it exists. Judge each criterion's
   text against the patient's window-restricted chunks with `judge` (S3, cached), for the top-N (default 20). Verify
   quotes as in the cascade.
4. **Score and rank.** NCBI's matching score plus aggregation score give the registry rank. A registry trial is shown
   as "likely fit" only when every criterion judged `not_met` has a verified quote. Otherwise it is "possible fit".
5. **Output per trial.**
   - Open studies: the tier, per-criterion status with evidence, and data gaps.
   - Registry trials: the label **"not open here; registry match; criteria not reviewed by a person"**, the nearest
     recruiting sites and their contacts from the registry record, and the registry identifier.

**LLM functions.** `judge`, `second_opinion`, `match_keywords`, and `embed`/`rerank` over patient text: all D3,
on-prem only. Registry text alone is D0 and may be pre-processed (library match, IR drafting) on any route §8 allows
for D0.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M5-4 | A CMP-28 written intended-use analysis MUST exist before M5 ships. | I (document) | MS2 |
| FR-M5-5 | **One engine.** Trial → patients and patient → trials MUST be implemented by `services/matching/engine.py` over the same cache key, judge roles, evidence schema, quote verifier and tier rules. A test MUST show that, for the same snapshot, a patient–criterion pair receives the same status from both directions. | T | MS2 |
| FR-M5-6 | *(Replaces FR-M5-1; brought forward.)* **Open studies.** `MATCH <MRN>` from a delegated clinician MUST rank the site's recruiting studies by tier, with per-criterion evidence. The ranking is deterministic: tier first, then the number of unresolved criteria, then the study's enrolment priority set by the research office. At MS2 the ranking runs in silent mode only (results to a CRC champion, not to the requester); live from MS3. | T | MS2 (silent); MS3 (live) |
| FR-M5-7 | *(Replaces FR-M5-2; brought forward.)* **Registry trials.** The box MUST rank registry trials not open at the site by the algorithm above, using the ported retrieval and criterion-level judging, and label them as above. Registry results MUST NOT be mixed into the open-study ranking. | T | MS4 |
| FR-M5-8 | *(Replaces FR-M5-3.)* **Tumour-board mode.** Given a roster (`MATCH` with MRNs and a meeting date, or a roster feed mapped in M0), the box MUST deliver to the tumour-board coordinator, 24 hours before the meeting, one page per patient (open-study tiers, top registry matches, and data gaps that would change a match, e.g. "EGFR status not recorded") and a roster summary, and record coordinator minutes per patient. | T | MS4 |
| FR-M5-9 | **No patient-derived egress.** Registry retrieval MUST run only over the local mirror (`registry_mirror/`), refreshed nightly from ClinicalTrials.gov API v2 with a manifest (records, hash, fetch time). Keywords, summaries, embeddings or any other patient-derived text MUST NOT be sent to any external service. The egress test (§14) covers it. | T | MS4 |
| FR-M5-10 | **Who may match whom.** `MATCH` MUST be accepted only when either holds: <br>• the requester is a delegated investigator on ≥ 1 recruiting study and has a care relationship with the patient (an encounter within 12 months); <br>• the patient is on a tumour-board roster the requester belongs to. <br>Otherwise the request is refused without revealing whether the MRN exists (FR-AG-4). Hermes MAY propose a `MATCH` line but cannot execute it. Results go only by encrypted email to the requester, never to Teams or LINE. | T | MS2 |
| FR-M5-11 | **Cross-lingual retrieval.** MedCPT is English-only. For patients whose notes are mainly zh-TW, ja or mixed (ML-4 tags), retrieval MUST add: <br>• the bge-m3 dense channel over trial text; <br>• English keywords from `match_keywords`. <br>Recall@500 is reported per language stratum (ML-18). | T | MS4 |
| FR-M5-12 | **Event-triggered matching (optional, site flag).** On a new index-type event for a patient, the box MAY run patient → open studies and add qualifying tiers to the treating practitioner's next clinic-day packet. Events: a pathology report with a new malignant diagnosis (ORU/MDM), or a new problem-list diagnosis in a configured set. It never adds a separate alert. | T | MS4 |
| FR-M5-14 | **Benchmark mode.** `trialbox eval match_registry` MUST reproduce the port's published-reference comparison on SIGIR 2016, TREC CT 2021 and TREC CT 2022. It runs in two modes: NCBI-faithful prompts, and the production judge. Metrics: recall@500, recall@1000, NDCG@10, P@10, and AUROC of eligible versus excluded, with the paper's definitions. | T | MS1 |

**Acceptance metrics (M5)**

| Metric | Target | Best published comparator | Suite | MS |
| --- | --- | --- | --- | --- |
| Registry retrieval recall@500, SIGIR 2016 (with the paper's keyword file) | ≥ 0.90 | port 0.931; paper 0.934 | `match_registry` | MS1 |
| Registry ranking NDCG@10, on-prem J build, production judge | ≥ 0.65 *(est.)* | TrialGPT GPT-4 0.73 (paper) | `match_registry` | MS4 |
| Cross-lingual parity: recall@500 for zh-TW and mixed renderings of the SIGIR notes (`eval/criterion_ml` translations) versus English | gap ≤ 5 points | none: no CJK patient → trial benchmark exists | `match_registry_ml` (new) | MS4 |
| Criterion-level accuracy on the 1,015 NCBI expert annotations (production judge, on-prem J) | ≥ 0.85 (§16.4); false-block upper ≤ 0.030 *(provisional)*, ≤ 0.022 target at MS4 | GPT-4 0.873; false-block 0.014 (95 % upper bound 0.022); experts 0.887–0.900 | `judge_public` | MS1 |
| Tumour board: ≥ 1 open-study or registry trial the board accepts within the top 5 | ≥ 0.90 of patients with any accepted trial | TrialGPT 2.0: top-10 contained a clinician-chosen trial in about 91 % of 288 cases (preprint); TrialMatchAI top-20 92 % | tumour-board log | MS5 |
| Coordinator minutes per tumour-board patient | −50 % versus baseline | TrialGPT 2.0 screening time −55 % | time-and-motion | MS5 |
| Patient-derived bytes leaving the perimeter | 0 | — | egress test | MS2 |

---

### 10.13 ML: Multilingual text (C-8)

**Purpose.** Notes in Taiwan mix Traditional Chinese, English and abbreviations, and Japanese sites write in Japanese.
Criteria arrive in English. The multilingual requirements make every function work on these texts:
- without translating before reasoning;
- with quotes verified byte for byte in the original script;
- with evaluation strata that expose any language whose quality falls behind.

ML-1 to ML-12 are carried from v3 unchanged, except that ML-10 is extended by ML-17 and ML-11 by ML-15. ML-13 to ML-24
are new.

**LLM functions.** `judge`, `second_opinion` and `extract_criteria` receive bilingual questions and verbatim text
(ML-8); glosses come from the J build on-prem (ML-22). The bake-off uses D0 data only on OpenRouter routes under §8;
its results are pending and none is assumed here.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| ML-1 | **Keep the source script.** Notes and protocols MUST NOT be translated before reasoning. Evidence is always quoted in the original. A generated gloss MAY be added, marked as a translation (`gloss`). | T | MS1 |
| ML-2 | **Canonical text** (§6) MUST be computed once at ingest. All offsets refer to it, and a quote is verified against it byte-for-byte. | T | MS1 |
| ML-3 | **Dates and numbers.** The normaliser MUST parse into typed spans: <br>• ROC (民國) dates (`113/3/5`, `113.03.05`, `民國113年3月5日`); <br>• Japanese era dates (`令和6年3月5日`, `R6.3.5`); <br>• Western formats; <br>• full-width digits; <br>• Chinese numerals in quantities (`三個月`, `兩次`); <br>• value-unit pairs with unseparated numbers (`Cr1.2`, `EF35%`). <br>Each parser is table-driven and unit-tested. | T | MS1 |
| ML-4 | **Language tags** per sentence (zh/en/ja/mixed) and the abbreviation density MUST be stored with chunks, and used for evaluation strata and calibration (§8). | T | MS1 |
| ML-5 | **Site lexicon** (§6). <br>• **Seeds:** NHI drug master Chinese and English names, ICD-10-CM-TW Chinese labels, LOINC-TW names and the site lab dictionary. <br>• **Growth:** deterministic mining of `ABBR (中文)`, `中文 (ABBR)` and `中文/English` patterns, and of co-occurrence in the same sentence. <br>• **Approval:** mined entries are `proposed` until the steward approves them in the Atlas workbook (G0). Retrieval and S2 use approved entries only. <br>It replaces `scenarios/terms.py`. | T | MS1 |
| ML-6 | **Deterministic assertion pass.** A bilingual cue grammar (zh/en/ja) MUST label the sentence containing an evidence quote as affirmed, negated, historical, family, hypothetical or uncertain, with scope rules (cue → target within the clause). <br>• Cue tables live in `vocab/assertion_cues.yaml`, seeded with Appendix E. <br>• The S3 model's `assertion` MUST agree with the rules, or the judgement becomes `insufficient` and goes to S4. | T | MS1 |
| ML-7 | **Retrieval** MUST expand the criterion's query through the approved lexicon in all site languages. It uses hybrid scoring (CJK bigram FTS + bge-m3 + optional bge-reranker-v2-m3), restricted to the criterion window. | T | MS1 |
| ML-8 | **Prompts** MUST present the criterion's `note_question` in the protocol language and the site language. They instruct the model that notes mix Chinese, English and abbreviations, and that it must quote verbatim and never translate the quote. | T | MS1 |
| ML-9 | **Output language per artefact:** <br>• PI/CRC packets, Study Card and digests: the recipient's preferred language (default site locale zh-TW); <br>• sponsor packets and questionnaires: the sponsor template's language (default English); <br>• IRB documents: the IRB's language; <br>• the signature manifestation: both. <br>Terms are rendered as `code — 中文 (English)`. | T | MS1 |
| ML-10 | **Japanese profile** (site flag `locale: ja-JP`): JP Core FHIR adapter, ja lexicon seeds (standard disease names, YJ drug codes, JLAC lab codes, where licensed), ja assertion cues, ja templates. Extended by ML-17. | T | MS6 |
| ML-11 | **Drift monitor:** mixing ratio, unknown-token rate and new-abbreviation rate per note type and department per month. A change > 3σ from the trailing 6 months raises a recalibration task (§8). Extended by ML-15. | T | MS4 |
| ML-12 | **Alliance language packs.** Approved lexicon rows (surface → concept, language, rounded support) and sentence-level de-identified assertion exemplars contain no PHI. <br>• They MAY be exported as signed "TW clinical shorthand packs" and exchanged between alliance boxes by email (v1 COHORT channel). <br>• An imported pack is reviewed at G0 like mined rows. | T | MS5 |
| ML-13 | **CHIP → Traditional Chinese.** Simplified-Chinese criterion datasets (CHIP-CTC; CHIP-STS; other CBLUE tasks where licensed) MUST be converted with OpenCC `s2twp` plus a versioned medical-term override table (`vocab/s2tw_medical.yaml`, e.g. 心肌梗死 → 心肌梗塞, 艾滋病 → 愛滋病), checked by a Simplified-character detector, and labelled `synthetic-TW`, never pooled with site gold. CBLUE licences are research-only *(terms uncertain)*: converted data serves evaluation only, never training of shipped weights or library seeding. | T | MS1 |
| ML-14 | **Code-mixed synthetic variants.** Until site data exist, `tools/mix_variants.py` MUST derive code-mixed variants of zh-TW items by substituting English surfaces from approved lexicon rows, in fixed-seed mixing bins (English script-token share 0–20 %, 20–50 %, 50–80 %), labelled `synthetic-mixed`, with quote offsets recomputed on the variant's canonical text. | T | MS1 |
| ML-15 | **Code-mixed drift (extends ML-11).** Per note type × department × month the monitor MUST also track the sentence language-tag distribution, the lexicon hit rate and the S2b screen-positive rate per criterion type. An alarm (> 3σ from the trailing 6 months, or a CUSUM signal, parameters per §16) opens a recalibration task (§8), schedules `lexicon_recall` re-measurement for the affected strata, and **suspends S2 zero-hit exclusion** for the affected criterion types until re-measured (SAFE-9). | T | MS2 |
| ML-16 | **ICD editions 2014/2023.** <br>• **Edition assignment:** each coded diagnosis and procedure gets its edition from its visit date (2023 edition from 2025-01-01, per NHIA; 2014 before; ICD-9-CM 2001 for older history). <br>• **ValueSet expansion:** expanded in both directions through the official mapping. A one-to-many mapping is flagged in the workbook and expanded to all targets unless the CRC narrows it at G1. <br>• **Test:** the `code_versions` suite requires identical criterion outcomes for synthetic patients coded in either edition. | T | MS1 |
| ML-17 | **JP profile (extends ML-10).** The `ja-JP` profile MUST add the SS-MIX2 source and JP Core 1.x mapping (`services/dataplat/standardise/jp_core/`); Japanese canonical-text rules (NFKC incl. half-width katakana; era dates per ML-3); ja assertion cues; ja lexicon seeds where licensed (MEDIS standard disease-name master, YJ/HOT drug codes, JLAC10/JLAC11, MANBYO for disease-name variants); ja protocol intake; ja templates for every ML-9 artefact; and ja strata in every suite. Each licence is recorded in the licence manifest (§8). | T | MS6 |
| ML-18 | **Language strata in every suite.** Every evaluation suite with text input (`judge_ml`, `judge_public`, `assertion_ml`, `criteria_extract_public`, `criteria_zh`, `match_registry_ml`, `lexicon_recall`) MUST report results per stratum: en, zh-TW, ja, mixed, and abbreviation-heavy (density above the site's 75th percentile). A suite fails if any stratum is below its floor, or the largest gap between strata exceeds 5 points, regardless of the pooled result. | T | MS1 |
| ML-19 | **Bake-off floors.** The small-model bake-off (§16) MUST apply the ML-18 strata and floors per task. A build with any stratum below its floor cannot become a `shadow` candidate, whatever its composite score. Bake-off inputs are D0 only; the gateway refuses other classes on bake-off routes. | T | MS1 |
| ML-20 | **Lexicon recall per language stratum.** The `lexicon_recall` suite (SAFE-9) MUST be computed per criterion type × language stratum on judged pairs. Public pre-measurement uses the expert evidence sentences of `eval/criterion_ml` in all four renderings. Site measurement uses adjudicated site pairs. | T | MS1 (public) / MS2 (site) |
| ML-21 | **Cross-lingual evidence retrieval.** Criterion (English) → note sentence retrieval MUST be measured as evidence-sentence recall@k against the physicians' sentence ids in `eval/criterion_ml`, per language. The retrieval configuration (lexicon expansion, bge-m3, reranker; MedCPT for en only) is chosen by this measure. | T | MS1 |
| ML-22 | **Glosses.** A gloss MUST: <br>• be generated by the J build on-prem; <br>• be stored separately from the quote; <br>• carry the label "machine translation"; <br>• never be used by the verifier or the assertion pass. <br>A monthly sample of 20 glosses per language is reviewed in the QA pack. | T | MS2 |
| ML-23 | **Script hygiene in outputs.** No artefact for a zh-TW recipient may contain Simplified characters. The output check rejects them and the template engine falls back to the code-system display in Traditional Chinese. Terms use the NHI/TFDA Chinese displays where they exist. | T | MS1 |
| ML-24 | **Clinician verification of translated evaluation notes** (= VV-32, §16.5). A bilingual clinician MUST review all 326 sentences of each rendering (zh-TW, ja, mixed) in `eval/criterion_ml`, using the §16.5 error taxonomy, before MS1. Meaning-changing errors are corrected in a new dataset version that carries the review record. Until then, every report labels rendering results "machine-translated, unverified". | I, T | MS1 |

**Acceptance metrics (ML)**

| Metric | Target | Best published comparator | Suite | MS |
| --- | --- | --- | --- | --- |
| Criterion accuracy per language on the 1,015 annotations (en / zh-TW / ja / mixed) | ≥ 0.85 en; ≥ 0.82 zh-TW/ja/mixed until VV-32 (ML-24) completes, then ≥ 0.85 in every stratum (§16.4); gap ≤ 5 points | GPT-4 0.873 (English only) | `judge_public` | MS1 |
| Site judging per stratum (zh-only, en-only, mixed, abbreviation-heavy) | sens ≥ 0.95, spec ≥ 0.90 (§16.4); gap ≤ 5 points | UTSW spec 0.81 (English) | `judge_ml` | MS2 |
| Local extraction of eligibility atoms from Traditional-Chinese code-mixed text | macro-F1 ≥ 0.90 | Gemma-2-27B QLoRA macro-F1 0.906 (Japanese primary-care notes, nine fields) | `criteria_zh`, site set | MS4 |
| Dates and numbers | exact match ≥ 0.99 | E-Da rules 99.98 % (numeric extraction, cardiac CT) | `dates_numbers` | MS1 |
| Assertion (rules) | macro-F1 ≥ 0.90 | — | `assertion_ml` | MS1 |
| Criterion outcome across ICD editions | identical in 100 % of cases | — | `code_versions` | MS1 |

---

### 10.14 SAFE: Never silently lose a patient

**Purpose.** A filter-first cascade excludes most patients without a person or a model reading their notes. SAFE
bounds the share of excluded patients who were in fact candidates, bounds recall on known positives, and demotes any
criterion whose evidence says it excludes wrongly.

**What v4 changes.** Every bound printed on any day must be valid however many months have been looked at. v3's
repeated Clopper–Pearson bounds on an accumulating sample are not (R3-03). In the reference simulation
(`tools/recall_sim.py`, `python -m tools.recall_sim`, seed 11: p = 0.02, 12 monthly looks of 40, 300 ledgers):
- repeated Clopper–Pearson missed the true rate in **9.7 %** of ledgers;
- the confidence sequence missed it in **0.3 %**.

The statistics live in `libs/tb_common/recall.py`, which already implements the anytime-valid sequence (`ConfidenceSequence`,
Waudby-Smith & Ramdas, JRSS-B 2024). This section specifies what is added to it and how the ledger, the certificate and
demotion use it. The certificate object is in §6.

**Strata.** An excluded patient–criterion pair belongs to the stratum of the stage that excluded it.

| Stratum | Exclusion | Present when |
| --- | --- | --- |
| `S1-affirmative` | Structured affirmative evidence of ineligibility (CAS-11) | Always |
| `S2-absence(index)` | No index-condition code, no lexicon mention in the lookback (rescue sweep), and, unless the index criterion passed the SAFE-9 gate, the S2b screen below threshold | Always |
| `S2-zero_hit(note)` | Zero approved-lexicon hits in the window, for a criterion whose `zero_hit_exclusion` is `allowed` | Only for criteria that passed the `lexicon_recall` gate (SAFE-9) |
| `S2b-below` | Zero lexicon hits, and the S2b semantic screen below its calibrated threshold, under `absence_of_evidence` | Criteria without the gate |
| `S3-not_met` | Verified, non-abstained hard `not_met` (CAS-7) | Note criteria |

**The ledger.** It is keyed by **cell** = (canonical criterion hash, stratum), pooled across every study that uses the
criterion and across months, so a new study inherits its criteria's evidence on day one. Each observation records the
pseudonymous pid hash, study and run, draw probability, weight, adjudicated label (1 = wrongly excluded), adjudication
route (S4 full pipeline, blinded human, or both) and timestamp. Sequences are append-only and stored in full, so every
bound can be recomputed at any α.

**Importance weighting with a uniform floor.** Within a cell's monthly excluded set of size N, draws are made with
replacement with probability q_i = f/N + (1 − f) · g_i/Σg, where g_i increases with the S3 nonconformity score, the S2
hit margin and the S2b similarity margin. The audit concentrates near the decision boundary, where misses are likely,
and the floor f keeps every patient drawable. Each draw yields Y_i = x_i · w_i/w_max, with w_i = 1/(N q_i) and
w_max = 1/f, so Y_i ∈ [0, 1] and E[Y_i] = p/w_max; the bound on the elusion rate p is w_max times the sequence bound on
E[Y]. With no misses found, the bound is w_max times the uniform-sampling bound for the same n (twice at f = 0.5): the
floor caps what weighting costs the certificate, while weighting finds boundary misses, and so triggers D1, sooner.
Under drift the certified parameter is the average elusion rate over the months sampled, which equals the current rate
when it is stable; a G5 change starts a new sequence (SAFE-8). v3's 5 % floor (AI-15) allowed a twenty-fold inflation; v4
defaults to f = 0.5 *(est.)*, configurable in [0.05, 1.0], and the `recall_cert` simulation fixes the shipped default at
MS2 by minimising the expected 12-month bound over planted-miss configurations.

**Study certificate.** For a study with excluded counts E_c per cell c, the missed-patient bound is
Σ_c E_c · U_c(α_c), where U_c(α_c) is the cell's anytime upper bound recomputed from its stored sequence at level α_c.
The allocation α_c = α · E_c/ΣE is **pre-registered** (frozen from the counts at the study's first certificate) and sums
to α: a weighted Bonferroni union bound. It is re-registered only at a new G1 ruleset version or a G5 change (SAFE-8),
which starts a new certificate series; old series are kept. Per-stratum bounds sum the cells of each stratum.

**Two known-positive lines.** Every certificate carries both lines.

| Line | Population | Method | Label |
| --- | --- | --- | --- |
| **H: historical enrollees** | Patients enrolled in any study at the site since the box's history start. Each is a known positive for every canonical criterion they passed at screening, pooled per criterion type and therapeutic area. | Replay at each enrollee's recruitment-start snapshot. Count enrollees the cascade excluded. Recall lower bound from the anytime sequence on misses. | "historical enrollees; biased: found by the previous process" |
| **B: blinded chart review** | Random samples of the study's passed and excluded patients, mixed in one queue. Reviewers are blind to the cascade decision (the queue is interleaved with five-minute review items, FR-M4-25). | Recall ≥ TP_L / (TP_L + FN_U), where TP_L = N_passed × the anytime lower bound of the eligible share among blinded passed samples, and FN_U is the missed-patient upper bound computed from **human-labelled** observations only. α is split between the two terms. r = the number of blinded positives found. | "blinded chart review; unbiased population; r = …" |

A recall claim in any text MUST quote a line's lower bound and name its population (AI-13). Line B is quoted when
r ≥ 30. Otherwise the statement quotes line H with its bias label, and states line B's r.

**Anytime sample sizes.** These were computed with the shipped `ConfidenceSequence` (non-uniform grid of 2,001 points,
step 0.00005 below 0.05) and equal App. F.3. Clopper–Pearson is shown for comparison; it is valid for one pre-planned
look only.

| Claim (0 misses found) | Single-look Clopper–Pearson n | Anytime sequence n |
| --- | --- | --- |
| Elusion < 2 %, α = 0.05 | 149 | 296 |
| Elusion < 1 %, α = 0.05 | 299 | 595 |
| Elusion < 0.5 %, α = 0.05 | 598 | 1,194 |
| Elusion < 1 %, α = 0.0125 (four cells, equal allocation) | 437 | 870 |
| Known-positive recall ≥ 0.90, α = 0.05 | 29 | 56 |
| Known-positive recall ≥ 0.95, α = 0.05 | 59 | 116 |
| Known-positive recall ≥ 0.98, α = 0.05 | 149 | 296 |

The anytime sequence needs roughly twice the sample. That is the price of looking every month and demoting on any
month. Pooling per canonical criterion across studies pays it: a frequently used criterion reaches n ≈ 600 within two
quarters at the default sampling rate *(est.)*.

**Demotion on the sequence.** Demotion is evaluated at every monthly look, per cell, on the cell's own sequence at
α_d = 0.05. No multiplicity correction is applied, because demotion is the conservative action.

| Rule | Trigger | Effect |
| --- | --- | --- |
| D1 harm | The anytime **lower** bound of the cell's elusion rate exceeds 0.01. This is evidence that the criterion excludes candidates. | Immediate: <br>• the S1 criterion becomes `soft` (its exclusions become `unknown`); <br>• for S2, zero-hit exclusion is revoked; <br>• for S2b, the threshold is moved to its conservative end. |
| D2 cannot certify | n ≥ n₀(f) + 60 and the anytime **upper** bound > 0.10, where n₀(f) is the smallest n at which a miss-free sequence certifies ≤ 0.10 (56 at f = 1; 116 at f = 0.5) | Same as D1, at the next run |
| D3 known positive | Any line-H or line-B known positive excluded by the criterion | Same as D1, at the next run; the patient's evidence goes to QA |

**Re-promotion.** Re-promotion is a G5 change. It requires re-established evidence (SAFE-8), and it starts a new
sequence for the cell. The old sequence is kept and shown.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SAFE-1 | **Filter classes.** The compiler MUST set `filter_class = hard` only if all of the following hold: <br>• (a) the atom is single-domain presence or a value comparison; <br>• (b) Atlas coverage for that domain in the scope is ≥ 0.9; <br>• (c) unit consistency is ≥ 0.9 for value atoms. <br>Otherwise it MUST set `soft`. A soft failure keeps the patient in the cascade as `unknown` for that criterion. | T | MS1 |
| SAFE-5 | **"History of" exclusions** (for example malignancy within 5 years) MUST have an explicit window. Resolution or cure needs `evidence_of_absence`, or the criterion is `pending_human`. | T | MS1 |
| SAFE-6 | **Coverage threshold.** `coverage_threshold` (default 0.8) for `missing_data → unknown` is a named, per-domain parameter recorded in every manifest. | T | MS1 |
| SAFE-8 | Recall evidence MUST be re-established after any G5 change to a model, prompt, lexicon or threshold that affects S1–S4 (MOD-5). | T | MS2 |
| SAFE-9 | **`lexicon_recall` gate for S2 zero-hit exclusion.** <br>**Default:** zero lexicon hits route the pair to S2b; they never exclude. <br>**Allowing zero-hit exclusion:** a criterion MAY be set `zero_hit_exclusion: allowed` only if every stratum is certified. Lexicon recall = the share of adjudicated positive pairs where an approved lexicon key hits a sentence carrying the evidence. A stratum is certified only if the one-sided 95 % Clopper–Pearson lower bound of lexicon recall on judged positives is ≥ 0.98 (0 misses needs ≥ 149 positives, 1 miss ≥ 236, 2 ≥ 313, 3 ≥ 386; App. F.1). Strata: criterion type × language (zh-only, en-only, mixed, abbreviation-heavy; ja from MS6), each with ≥ 5 % of the site's sentences (FR-M0-25). <br>**Data:** site adjudications (validation annotation, five-minute review). The public `eval/criterion_ml` pre-measure (ML-20) is reported but cannot open the gate. <br>**Suspension:** the permission is suspended automatically on: <br>• a lexicon G5 change; <br>• an ML-15 drift alarm for the stratum; <br>• a D1/D2 demotion of the cell. <br>It is restored only by re-measurement. | T | MS2 |
| SAFE-10 | *(Replaces SAFE-2, part 1.)* **Recall ledger.** Each month the box MUST draw audit samples from every cell with exclusions, with a stored seed. Every sample MUST be re-evaluated by S4 with the full note pipeline (no S2 shortcut). At least 30 excluded and 30 passed patients per month across the portfolio go blinded to a CRC (FR-M4-25; line B). Where no human label exists, the S4 label is used, and the certificate prints the S4–human agreement on the blinded subset. Sequences are pooled per canonical criterion and stored append-only in Postgres (`recall_observation`, `recall_cell`). Default rate: 150 new samples per stratum per month across the portfolio, allocated to cells in proportion to √E_c *(est.)*. **Reviewer capacity:** each site MUST have at least 2 reviewing CRCs or a research-nurse annotator; otherwise the blinded quota scales to 0.75 × the reviewers' FR-M4-25 capacity, and the certificate prints the shortfall. | T | MS2 |
| SAFE-11 | *(Replaces SAFE-2, part 2, and v3 AI-15, which §8 MUST retire.)* **Importance weighting with a uniform floor.** Draws MUST follow the q_i above with f = site parameter `audit_floor` (default 0.5 *(est.)*; allowed 0.05–1.0), and each observation is recorded as Y_i with its draw probability. The certificate reports the effective sample size and w_max per cell. | T | MS2 |
| SAFE-12 | *(Replaces SAFE-3, part 1.)* **Anytime-valid bounds.** Every elusion and recall bound MUST come from the confidence sequence in `libs/tb_common/recall.py`. Additions to the module: <br>**Implemented** (§1.3): real-valued observations in [0, 1] (truncation keeps 1 + λ(m − x) ≥ 0.5); `recall_lower_sequence` for the cumulative chart-review line (`certificate(..., known_positive_sequence=...)`). <br>**Not implemented, MUST be added:** <br>• per-cell pre-registered α weights in `certificate()` (it splits α/K equally); <br>• Horvitz–Thompson rescaling `Y_i = x_i·w_i/w_max`; <br>• pooling per canonical criterion; <br>• a lower bound on the elusion rate (the sequence on 1 − Y), for D1; <br>• a log-spaced grid below 0.0005 (the present grid steps 0.00005 on [0, 0.05]). <br>Clopper–Pearson remains only for the single-look validation replay (§16) and is labelled as such. | T | MS2 |
| SAFE-13 | **What is never an exclusion.** The following MUST NOT enter any excluded stratum or the "excluded" count: <br>• unprocessed patients (budget, FR-M4-22); <br>• patients with an abstained criterion; <br>• patients whose only failing criteria are `soft`; <br>• patients scoped out by S0 opt-out. <br>They are reported separately on the certificate. | T | MS2 |
| SAFE-14 | *(Replaces SAFE-3, part 2.)* **Certificate content.** Each candidate packet and feasibility packet MUST carry the study's current certificate (§6): (a) per-stratum elusion upper bounds as "missed per 1,000 excluded" and the implied missed-patient bound, by the pre-registered weighted Bonferroni above; (b) lines H and B with population, r, misses and anytime lower bound; (c) the point estimate; (d) demotions in force; (e) registration date and series. All numbers come from the shipped function on the printed inputs; statements follow the quoting rule (AI-13). | T | MS2 |
| SAFE-15 | *(Replaces SAFE-4.)* **Demotion on the sequence.** Rules D1–D3 above MUST be evaluated at every monthly look on each cell's anytime bounds. <br>• Each demotion is recorded with the cell, rule, bounds and n. <br>• It is emailed to the study teams that use the criterion, and applied at the next run. <br>• It is never reversed except by G5 re-promotion with a new sequence. | T | MS2 |
| SAFE-16 | **`recall_cert` suite.** The suite MUST: <br>• plant misses in every stratum, including near the decision boundary; <br>• simulate 12 monthly looks with importance-weighted draws; <br>• require that the bound covers the true rate **at every look** in ≥ 95 % of seeds, for cells and for certificates. <br>It also records the repeated Clopper–Pearson failure rate on the same seeds, as the documented contrast. It uses ≥ 1,000 seeds per configuration in nightly CI and 150 in the PR gate. | T | MS2 |
| SAFE-17 | *(Replaces SAFE-7.)* **Ever-excluded enrollee check.** At each G4 transition to `consented` or `randomized`, and again at study close, the participant MUST be checked against every past run of every study. <br>A participant ever hard-excluded by a criterion they passed at screening: <br>• is written to the ledger as a line-H miss for that cell (triggering D3); <br>• is reported in the next monthly QA pack. <br>The target is 0. | T | MS4 |
| SAFE-18 | **Monthly QA view.** The monthly QA pack MUST show per cell in use n, effective sample size, found, both bounds, demotion status and trend; per study, lines H and B with r; and the criteria whose S2 zero-hit permission is active, suspended or never granted. | T | MS2 |

**Acceptance metrics (SAFE)**

| Metric | Target | Comparator | Suite / evidence | MS |
| --- | --- | --- | --- | --- |
| Coverage of the anytime bound over 12 monthly looks (planted misses, weighted draws) | ≥ 0.95 of seeds at every look; reference simulation 0.997 (`tools/recall_sim.py`, seed 11) | repeated Clopper–Pearson 0.903 on the same simulation | `recall_cert` | MS2 |
| Studies whose first packet carries a certificate inherited from pooled cells | ≥ 0.80 of new studies after 6 months of operation *(est.)* | none: no product publishes a recall bound | ledger report | MS4 |
| Line B known positives (portfolio) and recall lower bound | r ≥ 59; lower bound ≥ 0.90 | none published (UTSW and TrialGPT 2.0 do not report false negatives) | ledger | MS4 |
| Ever-excluded enrollees | 0 per quarter | — | SAFE-17 report | MS4 |
