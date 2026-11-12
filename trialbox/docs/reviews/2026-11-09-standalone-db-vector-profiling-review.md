# TrialBox: patient database, vector database and patient profiling. An independent review

| Field | Value |
| --- | --- |
| Date | 2026-11-09 |
| Head reviewed | `origin/master` 264fa99 (ada9c8f plus the 2026-11-09 full system review commit) at `/home/user/Auto-GPT/trialbox` |
| Kind | Read-only review. No edits, commits or cloud. Small timing experiments under `/tmp/claude-0/review-db/scratch/`, cleaned up |
| Independence | Written without reading the parallel design proposal |
| Inputs | `docs/ARCHITECTURE.md`, `DATA.md`, `SECURITY.md`; DECISIONS D-120 to D-140 (there is no D-141 at this head); `docs/reviews/2026-11-09-full-system-review.md` and its six parts; `2026-11-09-baseline-open-data.md`; the owner's `PATIENT_PROFILING.md`; the code named in §1 and the appendix |
| Owner decisions taken as given | Listed in §0.2. They are stress-tested, not re-asked |

Facts marked **(verified)** were checked on the web today; **(unverified)** means I could not check them and they should be confirmed before they are relied on. **(measured)** means I measured it here on a 4-core, 15 GB container.

---

## 0. One page

### 0.1 Verdict

- **The current "database" is a good screening engine and a poor patient repository.** The lake is a nightly derived cache: twelve fixed tables flattened from FHIR into per-snapshot DuckDB files, rebuilt whole every night, with no primary keys, no provenance columns, no conflict model, no value text for labs and no room for a specialty item without a code change. It is reproducible and well tested at 5,000 synthetic patients. It has not run at 50,000 on the real model path, and the Postgres side has the stability faults the 2026-11-09 review found (one connection per store, no reconnect, no container limits). "Not very good; at least it needs to be stable" is a fair summary.
- **Core model: the owner's choice, OMOP CDM v5.4 in Postgres as the source of truth with FHIR for exchange, is right, with three conditions.** (1) OMOP must be extended with a provenance table and a fact-status table, or the "proposed / confirmed / signed" rule of D-135 cannot be kept. (2) The DuckDB snapshot stays as the screening engine, now exported from OMOP, so the compiled SQL, the goldens and the byte-identical re-run survive. (3) HAPI leaves the nightly path and becomes an on-demand FHIR export; the nightly load of a second store of record costs hours and nothing reads it at run time.
- **Vector store: pgvector in the same Postgres is right for 50,000 patients.** Use `halfvec(1024)`, HNSW, a chunk table that carries `person_id`, note date and site, exact ranking for single-patient queries and iterative scans for study-sized filters. At 500,000 patients with all history the index no longer fits comfortably in RAM on one workstation; the mitigations are in §3.5. DuckDB's `vss` is not fit for production (its own documentation says so). Qdrant and LanceDB would work but add a second store to back up, secure and restore for no gain at this scale.
- **Profiling: build the symbolic layers first, by code, from OMOP; let the judge model write only a cited narrative over them.** Every sentence cites item ids; a sentence whose quote is not found verbatim is dropped; the profile abstains when too little is citable. Facts update within minutes; the narrative updates nightly for changed patients only. The first build of 50,000 narratives is 5 to 10 idle nights on the RTX PRO 6000 by my estimate (§4.1), and it is not feasible on the 5090 tier's 8k context.
- **Two of the owner's v1 layers sit on the medical-device line.** The gap finder and the personal setpoints are fine as *trial screening* aids ("needs information", feasibility) and become decision support the moment a treating physician is shown "abnormal for this patient" or "suspected IPF" about their own patient. Ship them in v1 only inside the screening frame, behind a flag, and get a written device-qualification view before they reach clinic use.

### 0.2 Owner decisions already taken (2026-11-09), and my view

| Decision | My view |
| --- | --- |
| Full clinical repository now, trials first, Anamnesis layers later on the same base | Agree. The repository must be designed for the later layers (provenance, versions, local concepts) from day one, or it will be rebuilt a second time. |
| Data steward is named hospital staff per site; Aimedics never holds patient data | Agree. It also decides the consortium model: boxes exchange counts and de-identified objects, never a central patient store. |
| All subspecialties (generic model); first templates rheumatology, neurology, oncology, nephrology/general internal | Agree. OMOP's `measurement` and `observation` with local concepts carry CDR and DAS28 alike; the specialty lives in templates and concept sets, not in tables. |
| Profiles written by the judge (Gemma 4 26B-A4B) at night or idle, incremental after the first build | Agree, with a hardware caveat: the 5090 tier (8k context, sleep swap) cannot hold a profile prompt and the model is awake for screening at night. Profiles on `medium` and `large` tiers in v1; the 5090 gets the symbolic layers without narrative. |
| OMOP CDM core in Postgres; FHIR for exchange | Agree, with the three conditions above. Do not run the OHDSI Java stack (WebAPI, ATLAS) on the box; run DQD and Achilles as scripts when needed. |
| pgvector in the same Postgres | Agree to 50,000 patients. Plan for partitioning and a smaller index (patient-level vectors, recent years only, or 512-d) before 500,000. |
| Facts and profile object update within minutes; LLM text nightly or on request | Agree, and make the two clocks explicit: screening pins a nightly snapshot (D-82 reproducibility); the profile reads live OMOP and shows both "facts as of" and "narrative as of". |
| Profile access: steward all, PI own studies, CRC own study, all views audited | Agree. Add: the treating physician who is not on a study is not a v1 reader; API reads are audited like page views; chart numbers stay with the reveal rule (D-133). |
| Consortium may share counts and de-identified profiles (IRB plus data-sharing agreement) | Agree for counts. For profiles: symbolic layers only, dates shifted, free text and vectors never shared, small cells suppressed. A rich profile is re-identifying by construction (the owner's own §9). |
| Physician structured annotations count as confirmed (signed, audited); free text is read as notes; neither excludes silently | Agree. "Not silently" needs the excluded-patients page (review R-07) to exist first, with the annotation shown as the evidence, and a retraction path. |
| Conflicts resolved by the steward, or by a PI for their own study; unresolved = unknown | Agree. Add time: two values can both be true at different dates, and a resolution must say "at date". |
| v1 layers: cited record, timeline, phenotype, eligibility, personal lab setpoints, gap finder, similar patients | Agree on the first four. Setpoints, gap finder and similar patients: v1 behind flags, screening frame only (§4.4, §4.5). |
| PI spreadsheet values are trusted as coded, with provenance shown | Agree, with two guards. A sheet row joins by pseudonym; the review found that leading zeros and case give phantom patients (R-48) and that Big5 sheets can be misread (R-33), so a sheet value must carry `source_kind = sheet` in `tb_fact_provenance`, be shown with its file and row, and open a `tb_conflict` when it disagrees with the hospital feed instead of overriding it (§5.1). |
| Break-glass: reason plus second-person confirmation, time-limited, audited | Agree. Design in §4.6. The second person must be a steward or administrator, not another PI of the same study; the grant has a hard end time; every read during the grant is logged against the grant id. |
| Sponsor monitors get SDV access to enrolled subjects only | Agree. Design in §4.6. SDV shows the cited record items behind a CRF value, never the narrative, never neighbours, never chart numbers; it raises the open question of whether the built-in forms are an eCRF of record (review §6). |
| De-identified profile export: project pseudonyms, ±180-day shift, k = 5, no quotes, no vectors; contracts may only tighten | Agree, with one addition: k = 5 must be applied to quasi-identifier combinations (age band, sex, rare concept, site), not only to count cells, and rare concepts must be generalised to their parent. §5.2. |
| SNOMED: ask SNOMED International about an affiliate licence rather than leave standard concepts empty | Right to ask. The path, the cost shape and what v1 does until it is settled are in §2.5. Nothing in screening needs SNOMED; the consortium's OMOP standard concepts for conditions do. |
| Gap rules: approved by a PI of the specialty, live after at least 7 of 10 sampled hits are confirmed, research use | Agree with the approval and the research-use frame. 7 of 10 is a weak gate: with n = 10 the 95 % interval on 70 % precision runs from about 35 % to 93 %. Keep the 7/10 as the switch-on gate and add a rolling precision check (every 50 hits, keep ≥ 70 %) and a negative-control rule set (§4.4). |
| Treating physicians (clinician role, not a PI) see and annotate their own patients' profiles from the start | Agree that the role exists; I disagree with "from the start" for two layers. A clinician reading "outside this patient's usual range" or "possible undiagnosed IPF" about their own patient is care decision support. Give the clinician role the record, timeline, phenotype and eligibility layers from the start, and the setpoint and gap layers only after the written device-qualification view (§4.5). Affiliation and audit design in §4.6. |
| First full profile build: study patients first, nights only | Agree. It is how §4.1 and plan step 8 are written. |
| Subspecialty and clinical items map to existing standards (LOINC, Athena vocabularies, OHDSI Phenotype Library, OMOP Oncology, CDISC QRS, NIH CDE / REDCap Shared Library), never invented; a separate agent builds the item catalogue as data; "patient like me" with vectors is part of the patient-finding platform | Agree. The catalogue must become the `concept` table's front door and own the derived-score component codes that are hard-coded today (`compile_sql/generator.py:206-262`, `tb_common/derived.py`), or the two will drift. Phenotype Library definitions are SNOMED- and RxNorm-based and US-validated: each needs local maps and a site re-validation. "Patient like me" should be structured-first with embedding re-ranking and an explanation on every neighbour (§4.7). |

### 0.3 What is good today

- One rule for model-read facts (D-135): proposed facts never reach the coded tables and can only make an answer unknown. `lake/flatten.py:361-378`, `matching/proposed.py`, `tests/unit/test_one_rule.py`. This is the right seed for the whole provenance model.
- Fail-closed codes (D-113, D-130): off-list family codes and unreadable code systems give unknown, never "no".
- Pseudonyms at the door, pid map encrypted per row (`adapter/pidmap.py`), names never in the lake.
- Reproducible screening: SQL pinned to a snapshot; GOUT-COH funnel pinned in `tools/e2e_simple.py:729-751`; off-list oracle fixtures.
- A hybrid retrieval already exists per patient: BM25 over CJK bigrams plus cosine, fused by RRF (`lake/store.py:273-335`), with an embedding cache keyed by text hash (`store.py:202-237`).
- The data core already has a field-level conflict model with ownership and a trail (`datacore/store.py:36-38`, D-123). It is the pattern to copy for clinical facts.

---

## 1. The current database, honestly

### 1.1 What exists

Clinical facts take four forms on the box, all derived from the adapter's canonical rows:

| Store | Where | Written | Read at run time by |
| --- | --- | --- | --- |
| FHIR R4 NDJSON snapshot | `lake/ndjson/<snapshot>/` | nightly (`adapter/pipeline.py:189-193`) | lake rebuild, HAPI delta load |
| HAPI FHIR JPA (database `hapi`) | Postgres | nightly delta (`adapter/load_fhir.py`; D-122) | the compile-time CQL gate only (D-130; `orchestrator/app.py:87` wires a `FhirEvaluator` but SQL is the only runtime engine) |
| Parquet per snapshot | `lake/parquet/snapshot=<s>/` | nightly | the DuckDB build |
| DuckDB per snapshot | `lake/db/<s>.duckdb` | nightly, whole rebuild (`lake/store.py:120-200`) | every job: FEAS, SCREEN, NAV, CASE, site readiness |

The DuckDB file holds twelve flat tables (`lake/flatten.py:24-130`): `patient`, `practitioner`, `encounter`, `appointment`, `condition`, `observation`, `medication`, `procedure`, `report`, `document`, `claim`, `site_fact`, `consent`, plus `document_chunk` with `embedding FLOAT[1024]` and a BM25 index (`store.py:168-190`).

Trial facts live in Postgres `trialbox_wf`, one schema per store (D-126): `datacore`, `sitesetup`, `pidmap`, `terminology` (licensed lists), `refdata` (CT.gov pack), `site`, `orch`, `auth`, and the rest.

### 1.2 Is it stable?

| Question | Answer | Evidence |
| --- | --- | --- |
| Does the same input give the same answer? | Yes, on the stub. The SQL is pinned to a snapshot; the GOUT-COH funnel is pinned. With the model pair, note judgements drift ~9 % (D-116), so SCREEN is not byte-identical (review R-41). | `e2e_simple.py:729-751`; D-137 "identical" |
| Does it survive a database hiccup? | No. One psycopg connection per store for the process life, never reconnected; `/healthz` does not touch the DB. | `libs/tb_common/db.py:99-127`, review R-13 |
| Does it survive memory pressure? | Partly. DuckDB is capped at 40 % of RAM and spills (`store.py:67-74`, `connect()` 240-256). Ingest is in-memory at ~0.33 GB per 1,000 patients (D-80, DECISIONS l.573): 50,000 patients need ~16 GB in one process; 500,000 cannot be ingested without streaming. The cascade loads a year of notes for every alive patient into one Arrow table (R-87). No container has a memory limit (R-17). | `adapter/pipeline.py:130-175`; `cascade/engine.py:265-268` |
| Does it scale to 50k–500k? | 50k: the lake rebuild was fixed for memory (D-105) and the cascade ran at 5,000 in 75 s on the stub (D-139). The 50k run on the real pair has not happened (Gate G1). 500k: a full HAPI reload took ~8 h (D-122); the whole-file nightly rebuild of DuckDB, FTS and chunks grows linearly; the embedding cache makes only new chunks cost. | D-122, D-139 |
| Are migrations safe? | Partly. Versioned under an advisory lock, but each script is split on `;` and never checksummed; a failed statement mid-version leaves the schema half-applied inside one transaction (that part is fine) but a later edit of an applied script is not detected. | `db.py:155-175`; R-13 |
| Can a site change rebuild the lake under a running job? | Yes. Publishing a site fact rebuilds `main` under the same snapshot id; re-runs are not byte-identical that day (D-135 "Spaces and reproducibility"; "Not done": not batched). | `sitesetup/publish.py`, `lake/store.py:103-117` |

**Grade: stable as an engine, fragile as an operation.** The faults are known and costed in the review's Wave 1 (R-13, R-17, R-02, R-06). None of them is caused by DuckDB or by the lake design. They are caused by the Postgres access layer and by missing limits.

### 1.3 Is the schema fit for all structured plus unstructured data?

No. It was built for one purpose, criteria screening, and it shows:

| Need | What the lake has | Gap, with evidence |
| --- | --- | --- |
| Labs with text results ("<0.3", "陰性", "75 H") | `observation.value_num`, `unit`, `value_code` | No `value_text`; `flatten.py:260` keeps only a number. A text result is dropped and the atom reads FALSE (review R-02, Blocker). No reference range, no interpretation flag, no specimen, no status. |
| Diagnosis certainty (疑い suspected; 主病名 principal; 除外 ruled out) | `condition.status` = clinicalStatus only | No verification status; `flatten.py:233-245`. SS-MIX2 疑い becomes a real diagnosis (R-08). |
| Medication detail | `atc`, `nhi_code`, `name`, `dose` text, dates | No route, no numeric dose, no YJ/HOT columns in the lake (they stay in the FHIR resource). |
| Specialty items (CDR, DAS28 components, BASDAI, ECOG) | Any LOINC-coded observation row; DAS28/ASDAS/BASDAI/eGFR formulas hard-coded | `compile_sql/generator.py:206-262` and `tb_common/derived.py`: a new score is a code change in two places (SQL and CQL). CDR has no home but a local observation code. |
| Allergies, family and social history, imaging, vitals as a class, problem lists | Not modelled | SS-MIX2 allergy messages are not read (D-137 "Not done"). |
| Provenance per fact (which file, which line, which quote, which model, which person) | `site_fact.basis` only (`flatten.py:110-121`) | The quote, the input file and the decider live in Postgres `sitesetup.fact` (`store.py:31-37`); the lake row has no link back except the id. Hospital rows carry no source, no ingest run, no load time. Spec v4 §5 planned bitemporal and provenance columns; they were not built. |
| Conflicts between facts | None for clinical facts | `datacore.conflict` is for trial-data fields only (`datacore/store.py:36-38`). `sitesetup/publish.py:disagreements()` lists demographic disagreements only. A note that contradicts a coded diagnosis has no place to be recorded. |
| Row identity across nights | Source ids from the adapter | No primary keys in DuckDB (`CREATE TABLE ... AS SELECT * FROM read_parquet`, `store.py:167`); no "first seen / last seen"; no deletion history beyond the HAPI ledger. |
| Unstructured text | `document.text`, `document_chunk` (500-char windows, 100 overlap, `lake/textproc.py:32-48`) | Good enough for retrieval. Windows cut mid-sentence and mid-word in CJK; no section awareness (S/O/A/P); no char offsets stored for citation. |
| Terminology | Four homes: Parquet in the repo (`criteria_compiler/terminology/*.parquet`), Postgres `terminology` (licensed lists, D-137), Postgres `refdata` (D-140), CSV lookups under `adapter/mapping/*` | No single concept table, no concept ids, no versioned maps. The open-data review says the shipped terminology is "a gout demo" outside ICD-10-CM. |

### 1.4 Is "never two stores of record for one fact" true?

Not for clinical facts. HAPI holds the same facts as the lake, is loaded nightly (8 h for a 500k full load, D-122), has no authentication (R-34), and is read at run time by nothing (D-130 made SQL the only engine; the gate is compile-time). It is a cost without a reader. The owner's "FHIR for exchange" resolves this: produce FHIR NDJSON from the core on demand; stop the nightly load.

### 1.5 Summary of §1

The lake is the right **serving** shape for screening: columnar, pinned, read-only, memory-capped. It is the wrong **system of record**: no keys, no provenance, no conflicts, no versions, lossy columns. The owner's instinct is correct. The fix is not to make DuckDB the record; it is to put a record in front of it and keep DuckDB as the derived engine.

---

## 2. The core data model

### 2.1 Options

- **(a) OMOP CDM v5.4 in Postgres as the core.** Person-centric event tables, standard concepts, `*_source_value` and `*_source_concept_id` on every row, `note` and `note_nlp` for text and NLP output. v5.4 is the version the OHDSI tools support; v6.0 was never adopted **(verified: OHDSI materials and the 2023 OHDSI NLP paper describe CDM 5.4 as the schema the tools use; I found no newer recommended version)**.
- **(b) FHIR-native (HAPI) as the core.** Keep resources as the record, query by FHIR search or SQL-on-FHIR views.
- **(c) Today's lake, extended.** Add columns, a `fact_provenance` table and a `conflict` table to the flattener; keep DuckDB as the record.
- **(d) Hybrid.** OMOP-shaped Postgres as the source of truth; DuckDB/Parquet snapshots exported from it for screening; FHIR produced on demand.

### 2.2 Scores

1 = poor, 5 = good. The weights are mine; the owner may change them.

| Criterion | (a) OMOP core | (b) FHIR core | (c) lake extended | (d) hybrid | Notes |
| --- | --- | --- | --- | --- | --- |
| Stability (keys, constraints, transactions, backup) | 5 | 3 | 2 | 5 | DuckDB has no concurrent writers and the lake has no keys; HAPI is stable but opaque (JPA tables) |
| Flexibility for specialty items | 4 | 4 | 3 | 4 | OMOP: any item is a `measurement`/`observation` with a standard or local concept; FHIR: any Observation; lake: a code change per derived score |
| Japan/Taiwan coding | 3 | 4 | 3 | 3 | JP Core and TW Core exist for FHIR; OMOP has no official JLAC10, YJ, MEDIS or NHI vocabularies in Athena **(verified: OHDSI Japan is mapping YJ and JLAC to RxNorm/LOINC; an ISPOR 2026 abstract says no Japanese OMOP vocabulary exists yet; Taiwan NHIRD was converted with 86.7 % of drug codes mapped to RxNorm)**. Local concepts (ids ≥ 2,000,000,000) are the standard OHDSI answer and work |
| Query speed for the SQL engine at 50k–500k | 3 | 1 | 5 | 5 | DuckDB over Parquet is the fastest path for the CTE-heavy generated SQL; Postgres row store is 3–10× slower on these scans (estimate); FHIR search cannot run the generated SQL at all |
| Consortium federation (OHDSI) | 5 | 2 | 1 | 5 | OMOP is what network studies run on; a FHIR core would need a conversion anyway |
| Migration cost from today | 2 | 3 | 4 | 3 | (a) rewrites compile_sql and the goldens; (c) is cheapest but keeps the faults; (d) adds an OMOP writer and an exporter, keeps compile_sql untouched |
| On-box operations on Windows/WSL2 | 4 | 3 | 4 | 4 | Postgres is already there; HAPI is a JVM with its own memory; DuckDB files are simple to back up |
| Provenance and conflicts (the owner's requirements) | 3 (needs extensions) | 3 (Provenance resource exists, heavy) | 2 | 4 (extensions designed with the exporter) | OMOP's `note_nlp` holds offsets and modifiers but no "proposed/confirmed/signed" status; the OHDSI NLP WG itself proposes pushing NLP facts into event tables with a link back **(verified: OHDSI brief report)** |
| **Total (unweighted)** | **29** | **23** | **24** | **33** | |

### 2.3 Recommendation: (d), as the owner decided, with the conditions below

1. **OMOP CDM v5.4 tables in Postgres**, a new database `tb_omop` on the same server (its own backup unit; `trialbox_wf` stays the trial database). Every row keeps `*_source_value` and `*_source_concept_id`. Unmapped local codes get **local concepts** in a site range (ids ≥ 2,000,000,000), never silently `concept_id = 0` without the source value. The `concept` table becomes the one terminology home; the four homes of §1.3 feed it.
2. **Three extension tables**, because the owner's rules cannot live in plain OMOP:
   - `tb_fact_provenance (event_table, event_id, source_kind {his_feed, ssmix2, sheet, chart, redcap, annotation, llm}, source_ref, ingest_run_id, note_id, note_nlp_id, char_start, char_end, quote_sha, model_version, recorded_at)`.
   - `tb_fact_status (event_table, event_id, status {coded, proposed, confirmed, signed, rejected, superseded}, decided_by, decided_at, before_json)`. The lake exporter writes `proposed` rows to `site_fact` only, exactly as `flatten.py:361-378` does today, so the one rule is unchanged.
   - `tb_conflict (id, person_id, concept_id, a_table, a_id, b_table, b_id, kind {contradiction, duplicate, unit, date}, state {open, keep_a, keep_b, both_at_dates, unknown}, resolved_by, resolved_at, note)`.
3. **The lake is exported from OMOP**, not from NDJSON. An exporter writes the same twelve tables with the same column names (`flatten.SCHEMAS`) from OMOP views, so `compile_sql/generator.py` and every approved ruleset run unchanged and the goldens hold byte for byte. Columns the owner needs (`value_text`, `verification_status`) are added as new columns; existing SQL does not read them.
4. **FHIR for exchange only.** NDJSON is generated from OMOP on demand (JP Core / TW Core profiles as today, `adapter/validate/jpcore.py` keeps its job). HAPI leaves the nightly path. The CQL equivalence gate stays compile-time and moves to CI (it needs HAPI CR; the box does not).
5. **Do not install the OHDSI Java stack on the box.** WebAPI and ATLAS need Tomcat and a second Postgres schema and bring no value to a CRC. Run Data Quality Dashboard and Achilles as scripts at a snapshot when the consortium asks.
6. **Keep `datacore` as the owner of trial facts.** Mirror consent, visits and lifecycle into OMOP `observation` / `visit_occurrence` as a read-only view for consortium queries, never as a second writer (D-123 one-writer rule).

### 2.4 Where OMOP will hurt, said plainly

- **Person ids.** OMOP's `person_id` is an integer. The pseudonym is a 40-character HMAC. Store the pseudonym in `person_source_value` and mint `person_id` once; a restore that re-keys (review R-50) must not re-mint. Keep the pid map as is.
- **Suspected diagnoses.** OMOP has `condition_status_concept_id` and `condition_type_concept_id`, but no standard "suspected" status that the tools honour. Carry 疑い as a local status concept and have the exporter write `verification_status = 'suspected'`; the SQL engine then treats it as unknown for exclusions (the fix of R-08).
- **Text labs.** `measurement.value_source_value` keeps "<0.3" and `value_as_number` stays NULL; the exporter writes `value_text`; the generator returns NULL when no numeric value is in the window (the fix of R-02).
- **Local vocabularies.** Nothing official exists for JLAC10, YJ, HOT, MEDIS 病名 or NHI codes in Athena. The box must ship a local concept table and maps (the open-data pack of D-140 is the start) and the consortium must agree on one concept-id range per hospital so counts can be joined later.
- **Loading speed.** A naive row-by-row OMOP load is slow; use `COPY` (`db.py:68-77` already has `copy_rows`) and load per ingest run into staging, then swap. The nightly delta is small.
- **Two clocks.** Screening pins a nightly snapshot; profile facts read live OMOP within minutes. Both are correct; both must be shown.

### 2.5 The SNOMED question

OMOP's standard concepts for conditions are SNOMED CT; for labs LOINC; for drugs RxNorm (and RxNorm Extension); ATC is a classification. Japan and Taiwan are not SNOMED International members (the open-data review checked the member list on 2026-11-09). What that means:

- **Using SNOMED content in a non-member territory needs an Affiliate Licence from SNOMED International**, and in non-member territories the licence carries a fee. SNOMED International publishes the licence terms and the fee basis on its site; the fee is set per deployment or per end-user organisation and depends on the territory's income band and the number of deployments **(unverified today: I did not fetch the current fee schedule; Aimedics or the lead hospital should request the Affiliate Licence agreement and the non-member fee table from SNOMED International directly)**. Downloading the OHDSI vocabularies from Athena with SNOMED included requires accepting the SNOMED terms, so a box in Japan or Taiwan that loads SNOMED-standard concepts needs the licence.
- **Who would hold it.** Either each hospital as an end user, or Aimedics as a vendor with sub-licensing for its deployments. The vendor route is the usual one for a product; the hospital route fits a consortium with its own data stewardship. This is a question for the owner (§7).
- **What is free now.** The SNOMED **IPS Terminology** (a subset of about 13,000 concepts for the International Patient Summary) is released under CC BY 4.0 for use in non-member countries **(verified in the open-data review's sources; terms to be re-read before use)**. It covers common conditions and procedures but not the long tail a specialty needs.
- **What v1 should do until it is settled.** Nothing in TrialBox's screening needs SNOMED: the rulesets compile to ICD-10-CM, LOINC, ATC and NHI codes, and the engine fails closed on anything else. So: load OMOP with **ICD-10-CM (and the WHO ICD-10 category bridge) as the consortium's declared standard for conditions**, LOINC for measurements, RxNorm or the NHI/薬価 lists for drugs, and keep `*_source_concept_id` on every row. Mark the condition concepts as "consortium standard, not OHDSI standard" in the `vocabulary` table. When a SNOMED licence arrives, a one-time mapping ICD-10-CM → SNOMED (the OHDSI vocabularies ship these maps) populates `condition_concept_id` without touching the source columns, and the goldens must not move because screening never read those columns. The consortium's own counts work either way; participation in an OHDSI network study needs the licence.

---

## 3. The vector database

### 3.1 What exists

- `document_chunk` in each DuckDB snapshot: 500-character windows, `FLOAT[1024]`, BM25 over CJK bigrams, exact cosine per patient, RRF (`lake/store.py:143-190, 273-335`; `textproc.py`).
- Embedders: `HashEmbedder` (deterministic feature hashing, the default `TB_EMBED_MODE=hash` in `.env.example:6`), `BgeM3Embedder` (sentence-transformers, CPU by default, `TB_EMBED_DEVICE`), `HttpEmbedder` to `embed-service` (`embed_service/embedder.py`). The compose stack points the lake at the embed-service with `/models/bge-m3` (`deploy/docker-compose.yml:88-97`); the GB10 overlay puts it on CUDA. Every gate has run on the hash embedder (review S6, R-56).
- S2b embeds the question and the window's sentences on the fly per pair (`cascade/s2b_semantic.py:93-101`); it does not use the index. Its threshold is a placeholder (`s2b_semantic.py:25-27`).
- A sha-keyed embedding cache (`store.py:202-237`), which is the right basis for incremental embedding and re-embedding.

So the box already has a per-patient hybrid retrieval and no cross-patient index. "Introduce a vector database" means: one durable index over all chunks, filterable by study and role, that the profile assembler and "similar patients" can query.

### 3.2 Scale

Assumptions, to be replaced by the site's numbers: 50,000 patients, five years of notes, 60 notes per patient, 1.5 chunks per note (progress notes are short; discharge summaries and reports are long).

| | 50k patients | 500k patients |
| --- | --- | --- |
| Chunks | ~4.5 M | ~45 M |
| Vectors, `vector(1024)` float32 | 18 GB | 180 GB |
| Vectors, `halfvec(1024)` | 9 GB | 90 GB |
| HNSW index (m=16), rough | 1.0–1.5× the vectors | the same |
| Chunk text | ~3 GB | ~30 GB |
| New chunks per night (1 note per patient per week) | ~10k | ~100k |

At 50k everything fits on an NVMe and the hot part of the index fits in RAM on a 64–128 GB workstation. At 500k with all history it does not fit in RAM; see §3.5.

### 3.3 Options

| | pgvector in `trialbox_wf`'s server | Qdrant | Milvus | LanceDB | DuckDB `vss` | No vector DB |
| --- | --- | --- | --- | --- | --- | --- |
| Backup and restore | One `pg_dump` with the rest (D-126 `.tbbak`); dump grows by the vector size | Its own snapshot API; a second artefact to encrypt, verify and restore | Needs etcd + MinIO/S3; heavy | Files on disk (Lance format); easy to copy, no transactions across stores | In the snapshot file; but see persistence | Nothing |
| Access control per study/role | SQL join to study membership; Postgres RLS possible; one audit path | Payload filters only; the app must enforce; no RLS | Same as Qdrant | Application filter only | Application filter only | — |
| Operational load on one box | None new: same server, same backup, same monitoring | One more container, port, token, health check, upgrade path | Three more containers | A Python library in the lake service; no server | None new | None |
| Scale 50k / 500k | Good / strained (index RAM, dump size) | Good / good | Good / good | Good / good (IVF-PQ on disk) | Fair / poor (index in RAM, rebuilt per snapshot) | — |
| Filtered search quality | HNSW with iterative scans since 0.8.0 **(verified: pgvector CHANGELOG, 0.8.0 2024-10-30; current 0.8.7, 2026-10-01)**; `halfvec` indexable | Good filtered HNSW | Good | Good | Falls back to a scan when a filter is present (my measurement below) | — |
| Multilingual | Model choice, not store choice | same | same | same | same | — |
| Production readiness | Mature, in Debian and the Postgres image ecosystem | Mature | Mature but oversized | Young but used | **Not for production**: the HNSW index persists only behind `hnsw_enable_experimental_persistence`; WAL recovery for the index is not implemented; the docs say do not use in production **(verified: DuckDB docs)** | — |
| Fit with the owner's "same Postgres" decision | Yes | No | No | No | No | — |

### 3.4 Local measurement **(measured)**

Synthetic random unit vectors, 1024 dimensions, 4 cores, 15 GB RAM, no GPU. These numbers show shape, not production speed; real embeddings cluster and HNSW recall differs.

**DuckDB 1.5.5 with the `vss` extension (the repo's own venv), 150,000 chunks × 1024 float32, 50,000 pseudo-patients:**

| Operation | Time |
| --- | --- |
| Insert 150,000 rows | 14 s |
| Exact cosine top-10, whole table (no filter) | 729 ms |
| Exact cosine top-10, one patient (`pid = ?`) | 62 ms |
| Exact cosine top-10, 1,000 patients (a study) | 74 ms |
| HNSW index build (default m, cosine), 4 cores | **720 s** |
| HNSW top-10, whole table | 61 ms |
| HNSW top-10 with `pid = ?` filter (planner falls back to a scan) | 84 ms |
| Database file after the index | 1.5 GB (0.6 GB vectors) |

A 300,000-row attempt did not finish its index build in 15 minutes. Scaled naively, the 4.5 M chunks of a 50,000-patient site would take about six hours of index build in DuckDB on this hardware, the index must be rebuilt in every nightly snapshot file (the lake rebuilds whole, `store.py:120-200`), and the persistence is marked experimental. That is why DuckDB `vss` is not the answer even before the production warning.

**pgvector:** not measured here. The Debian `postgresql-16-pgvector` package (0.6.0) installed, but the sandbox refused the `postgres` user access to a data directory under the review folder, and a source build of 0.8.1 was not permitted, so no cluster could start. Public figures for pgvector 0.8 HNSW on 1024-d vectors are in the range of a few milliseconds per top-10 query at recall ≈ 0.95 with `ef_search` 40–100, and index builds of roughly 1–3 minutes per million `halfvec(1024)` rows with parallel workers and enough `maintenance_work_mem` **(unverified: vendor and community benchmarks, not measured on this box)**. The design in §3.5 does not depend on these numbers; it depends on the shape: exact ranking per patient, ANN only for population queries.

Reading: single-patient queries never need an approximate index; a btree on `person_id` plus exact ranking of a few hundred chunks is milliseconds in either engine. Study-sized filters (1,000–5,000 patients) and whole-population "similar patients" are where HNSW matters, and that is where DuckDB's index does not help under a filter and pgvector's iterative scan does.

### 3.5 Recommendation: pgvector in the same Postgres server, as decided, with this design

1. **Table.** `note_chunk (chunk_id bigserial, person_id, note_id, site_id, note_date, note_type, chunk_no, char_start, char_end, text, text_sha, lang, embedding halfvec(1024), embedding_model text, embedded_at)`, in `tb_omop` beside `note`. Index: HNSW on `embedding halfvec_cosine_ops` (m=16, ef_construction=64 to start), btree on `(person_id, note_date)`, btree on `(site_id, note_date)`. `halfvec` halves disk and RAM; pgvector indexes it up to 4,000 dimensions **(verified: pgvector 0.7.0 notes)**.
2. **Queries.** Per patient: `WHERE person_id = ?` then exact `ORDER BY embedding <=> ?` (the planner uses the btree). Per study: join `study_person` and set `hnsw.iterative_scan = relaxed_order` with `hnsw.max_scan_tuples` raised for the study size. Whole population (similar patients): HNSW on **patient-level vectors**, a second small table `person_vector (person_id, embedding halfvec, model, as_of)`, 50k rows, not 4.5 M.
3. **Row-level filtering.** The console is the only caller; it already scopes by study (`console/auth.py:179`). Add Postgres RLS on `note_chunk` and `person_vector` keyed on a session variable set by the backend, as a second fence. Every retrieval that reaches a page is audited with the study id and the chunk ids returned.
4. **Hybrid search.** Postgres has no CJK tokenizer. Store the lake's bigram token string (`textproc.token_string`) as `tsvector('simple', tok)` and rank with `ts_rank_cd`; fuse with RRF as today. This gives parity with the lake's current behaviour without a new extension. If BM25 proper matters, `pg_bigm` (Japanese bigram, light) or PGroonga (full CJK, heavier) are the candidates; measure first. **(unverified: pg_bigm/PGroonga packaging for the pinned Postgres 16 image.)**
5. **Chunking.** Replace fixed 500-character windows with sentence-aware chunks: split on `。！？\n` and on SOAP / 既往歴 / 現病歴 / 主訴 / 診斷 / 用藥 headers, target 400–600 characters, 1–2 sentences overlap, never split inside 「」 or a numeric with its unit. Store `char_start`/`char_end` so a citation can point into the note. Keep the note type and date in the text that is embedded ("[退院時要約 2024-03-02] ...") so retrieval sees context.
6. **Embedding models (on-box candidates).** All sizes are the fp16 weights; throughput is my estimate and must be measured on the site's card.

   | Model | Params / dims / context | Languages | Evidence | Fit |
   | --- | --- | --- | --- | --- |
   | BAAI/bge-m3 (already wired) | 568 M / 1024 / 8192 | 100+, incl. ja, zh | MTEB multilingual 59.6 **(verified, Qwen3 paper table)**; JMTEB v2 retrieval 0.7245 **(verified, Sionic model card)** | Default until an on-box eval says otherwise; ~1.1 GB; CPU ~5–15 chunks/s on 8 cores, GPU ~300–800 chunks/s **(estimate)** |
   | Qwen/Qwen3-Embedding-0.6B | 0.6 B / 1024 (MRL, can shrink) / 32k | 100+ | MTEB multilingual 64.33; C-MTEB retrieval 71.0 **(verified, Qwen model card)** | Best candidate to replace bge-m3 at the same dimension; instruction-aware; about the same cost |
   | Qwen/Qwen3-Embedding-4B | 4 B / 2560 / 32k | 100+ | JMTEB v2 retrieval 0.7779 **(verified, Sionic card)** | Too large for a shared card in v1 (8 GB fp16); 2560-d doubles storage |
   | intfloat/multilingual-e5-large(-instruct) | 560 M / 1024 / 512 | 100 | MTEB multilingual 63.2 (instruct) **(verified)**; JMTEB v1 71.65 **(verified, Ruri card)** | 512-token context is short for discharge summaries |
   | cl-nagoya/ruri-v3-310m | 310 M / 768 | Japanese only | JMTEB v1 avg 77.24 **(verified, model card)** | Japan-only sites; not for zh-TW/en; different dimension |

   Recommendation: keep bge-m3 as the shipped default (it is wired and 1024-d); run `tools/medtxt_eval.py` and `trialgpt_compare.py` with Qwen3-Embedding-0.6B at 1024-d; switch if it wins by a clear margin in ja and zh-TW. Both are 1024-d, so no schema change either way.
7. **GPU budget.** The embedder is small (about 1.1 GB) but competes for the card. Rule: the first full build runs on the GPU in idle hours while the judge sleeps (5090) or inside the ~40 % headroom (PRO 6000, `docker-compose.rtxpro6000.yml:14` says the embedder stays on the CPU today); nightly increments (~10k chunks at 50k patients) run on the CPU in well under an hour **(estimate)**. On the Spark the embedder already runs on CUDA (`docker-compose.gb10.yml:105`).
8. **Re-embedding when the model changes.** `embedding_model` on every row; a shadow column `embedding_next`; a background job fills it from the sha cache or the model; the HNSW index on `embedding_next` is built `CONCURRENTLY`; one transaction renames columns and indexes; the old column is dropped after the next backup. At 4.5 M chunks that is hours on a GPU and days on a CPU **(estimate)**; the profile assembler must not mix models in one query (filter on `embedding_model`).
9. **Backup.** Vectors go in the `.tbbak` (restore must work offline, the box cannot re-embed without the model and hours). Expect the dump to grow by 9–20 GB at 50k. The embed cache DuckDB file (`lake/embed_cache.duckdb`) becomes redundant once the chunk table exists; keep the sha → vector cache as a Postgres table instead.
10. **500k patients.** Before then: embed the last N years only; partition `note_chunk` by year (pgvector indexes per partition); use patient-level vectors for population queries; consider 512-d Qwen3 (MRL) to halve everything. Or accept a separate engine then; the chunk table design above moves to Qdrant or LanceDB without changing the callers.
11. **What vectors must never do.** Retrieval never changes a screening answer. S2b may route a pair to the judge; only the two-model rule on a verified quote may exclude (D-115, D-117). The profile may cite a retrieved chunk; it may not count it.

### 3.6 "No vector DB" considered

Screening does not need one: S2 lexicon plus S3/S4 on the notes in the window does the work, and S2b is a placeholder. The profile does: "similar patients", cohort-by-example and retrieval for the narrative are vector operations. So the vector store is justified by profiling, not by screening, and its failure must never block a screening run (`stale_index` as spec v4 §5 L5 already says).

---

## 4. Patient profiling: how to integrate

### 4.1 Generation

**Principle.** Code writes the facts; the model writes prose about the facts; every sentence points at a fact id; anything the model says that the facts do not support is removed before anyone sees it.

**Two update clocks (owner decision).**

| What | When | How |
| --- | --- | --- |
| Symbolic layers (record, timeline, eligibility, phenotype, setpoints, gaps, neighbours) | within minutes of a change | Postgres `LISTEN/NOTIFY` on OMOP and annotation writes, or a 5-minute poller over `ingest_run_id` / `recorded_at`; the assembler recomputes only the layers whose inputs changed (a dirty-set per layer) |
| Narrative (LLM) | nightly, for patients whose symbolic layers changed; on request from the page | Queue ordered by: active-study patients first, then by change size |

**Triggers.** New or changed OMOP rows for the person; a fact status change (proposed → confirmed, signed, rejected); a new or retracted annotation; a conflict resolution; a ruleset approval that touches the person's studies; a model version change (narrative only, in the background over weeks); a terminology map change (symbolic only).

**Inputs to the narrative prompt.** Not the raw record. A compressed symbolic digest: the timeline (dates, concepts, values), the phenotype items, eligibility per active study with reasons, setpoints, open gaps and conflicts, physician annotations (verbatim, marked as such), and the top-k retrieved chunks for each open question (k ≈ 8–12, by hybrid retrieval over the person's own notes). Every item carries an id. Target 6–12k tokens in, 600–1,000 out.

**Hallucination guards, in order.**

1. Schema-bound output (the gateway already forces JSON schemas, D-124 serving discipline): a list of sentences, each with `cites: [item_id, ...]`.
2. Citation verification: every cited id must exist in the digest; a quote cited from a note must be found verbatim in that note (`tb_common/quotes.py` does this for the judge already).
3. Number check: every number in a sentence must appear in a cited item (value, date, count). A sentence that fails is dropped and logged as `uncited`.
4. Negation and uncertainty words are kept only when the cited item carries them (疑い, 否定, "no evidence of").
5. Abstain: if fewer than, say, 80 % of sentences survive, the narrative is not published; the page shows the symbolic layers and "narrative not available: insufficient support", and the case goes to a queue the steward can see. The threshold is a setting; start strict.
6. The narrative is never an input to screening, to a fact, or to another narrative. It is a view.
7. Prompt-injection posture: notes are data; the prompt says so and delimits them (review R-35 asks for the same in `judge_v4.md`); a sentence that cites nothing is dropped regardless.

**Diff and history.** `profile_version (person_id, version, as_of_facts, as_of_narrative, snapshot_id, model_version, prompt_version, layer_hashes jsonb, narrative jsonb, created_at)`; the page shows "what changed since you last looked" from the layer hashes and a sentence-level diff; versions are kept for the audit retention (10 years on the box, D-138) or until erasure.

**Cost on the box's GPU (estimate, to be measured in a Gate-G1-style run).** D-139 measured about 6.3 s per patient for an S3 judge call on the PRO 6000 (a few thousand tokens in, a few hundred out, one stream). A narrative is roughly three times the input and three times the output: 15–30 s single-stream; with vLLM batching 8–16 requests the effective cost is 3–6 s per profile. 50,000 profiles: 40–85 GPU hours, so **5–10 idle nights of 8 h on the PRO 6000**; about half that on synthetic-length notes. Nightly increments (2–5 % of patients changed) are 1–4 h. On the 5090 (8k context, one model awake, screening holds the card at night) a full profile prompt does not fit and there is no idle window: no narrative on that tier in v1. On the Spark the numbers are between the two and must be measured.

### 4.2 Physician annotations

**Data model** (schema `annotation` in `tb_omop`, append-only):

```
annotation (
  id, person_id, author_user, author_role, study_id NULL,     -- scope: a study or the person
  kind {free_text, structured}, created_at,
  text,                                                        -- free text, read as a note
  structured jsonb,                                            -- {domain, concept_id, source_value, value_num, unit,
                                                               --  value_concept_id, date, date_precision, valueset}
  status {draft, signed, retracted, superseded}, signed_at, signature_hash, auth_method,  -- re-authentication at sign
  supersedes_id NULL, retract_reason NULL,
  visibility {study, person}                                   -- who may read it (owner access rule applies on top)
)
```

**Flows.**

- A **signed structured** annotation is written as an OMOP event (`condition_occurrence`, `measurement`, `drug_exposure` or `observation`) with a type concept "physician-entered" and a `tb_fact_status = signed` row and a provenance row pointing at the annotation. It counts like a confirmed fact (owner decision), so it may make a criterion met or not met. It may exclude a patient only through the normal coded path, which must be visible: the excluded-patients page (review R-07) lists the patient with the annotation as the evidence, and the author is told by the morning mail. That is what "not silently" means in code.
- **Free text** becomes a `note` row of type `physician_annotation` and is chunked and embedded like any note. The two models read it at S3/S4 under the two-model rule. It never exclues by itself.
- **Retraction** supersedes the OMOP event (`tb_fact_status = retracted`); screening recomputes; the trail stays.
- **Drafts** are visible to the author only and are not facts.

**Conflicts with the record.** When a signed annotation disagrees with a coded hospital fact on the same concept and overlapping dates, the assembler opens a `tb_conflict` row. Authority is not automatic: the steward, or the PI of that study, resolves it (`keep_a`, `keep_b`, `both_at_dates`, `unknown`). Until then the criterion that depends on it is unknown (the D-130 pattern), the profile shows both values with a conflict badge, and feasibility counts the patient under "needs information".

### 4.3 The profile object

**Shape.** One JSON document per version, plus the relational tables that feed it. Keyed by `person_id`; the pseudonym is `person_source_value`; chart numbers never appear.

```json
{
  "schema": "tb-profile/1",
  "person_id": 1234, "pseudonym": "a1b2c3d4...",
  "as_of_facts": "2026-11-09T06:40:00+09:00", "as_of_narrative": "2026-11-09T03:12:00+09:00",
  "snapshot_id": "2026-11-09", "versions": {"assembler": "1.0", "narrative_model": "gemma-4-26b-a4b-it-nvfp4/j-workhorse", "prompt": "profile_v1", "vocab": "2026.1"},
  "layers": {
    "record":      {"items": [{"id": "r-...", "table": "condition_occurrence", "event_id": 9, "concept_id": 201826, "display": "Type 2 diabetes", "date": "2021-04-02", "status": "coded", "sources": ["prov-..."]}]},
    "timeline":    {"items": [{"id": "t-...", "date": "2024-03-02", "kind": "admission", "refs": ["r-..."]}]},
    "phenotype":   {"items": [{"id": "p-...", "name": "RA, seropositive", "definition": "cohort:RA_SEROPOS/v3", "met": true, "refs": ["r-...", "m-..."]}]},
    "eligibility": {"items": [{"id": "e-...", "study": "GZQO", "ruleset": "GZQO/v4", "criterion": "INC-02", "answer": "unknown", "reason": "proposed_fact", "refs": ["sf-..."]}]},
    "setpoints":   {"items": [{"id": "s-...", "concept_id": 3010813, "display": "CRP", "personal_mean": 0.4, "rcv_pct": 60, "n": 14, "window": "2021-2026", "refs": ["m-..."]}]},
    "gaps":        {"items": [{"id": "g-...", "rule": "UIP_in_report_no_IPF_code/v1", "basis": "proposed", "refs": ["note-...#120-188"]}]},
    "similar":     {"items": [{"id": "n-...", "person_id": 5678, "score": 0.83, "model": "bge-m3", "scope": "study:GZQO"}]},
    "annotations": {"items": [{"id": "a-...", "author_role": "investigator", "study": "GZQO", "kind": "structured", "status": "signed"}]},
    "conflicts":   {"items": [{"id": "c-...", "state": "open", "a": "r-...", "b": "a-..."}]}
  },
  "narrative": {"sentences": [{"text": "...", "cites": ["r-...", "m-..."]}], "dropped_uncited": 2, "published": true},
  "hashes": {"record": "sha256:...", "timeline": "..."}
}
```

**Versioning.** `schema` is the contract version (a `schemas/profile.schema.json` in the repo, generated into `tb_contracts` like every other contract); `versions` names every producer; the object is immutable per version; a new version is written on any layer change; readers pin a version in the audit.

**Who reads it.**

| Reader | Uses | Rule |
| --- | --- | --- |
| Screening (SCREEN, NAV) | nothing from the narrative; `eligibility` is *written by* screening, not read | screening reads OMOP's snapshot and the ruleset only |
| Feasibility (FEAS) | `phenotype` counts, `eligibility` basis counts | symbolic only |
| Matching / the PI page | `eligibility`, `record`, `timeline`, `annotations`, `conflicts`, narrative | the owner's access rule; every view audited with version |
| CRC lists | `eligibility` reasons, "needs information" items | own study only |
| The LLM (judge at S3, the assistant) | the digest (symbolic items with ids) and retrieved chunks | the narrative is never fed back |
| Consortium export | a de-identified symbolic subset (§5) | never narrative, never vectors |

### 4.4 Layers: v1 and later

The owner fixed v1 as: cited record, timeline, phenotype, eligibility, personal lab setpoints, gap finder, similar patients. My reading of each against TrialBox's purpose (screening, feasibility, lifecycle):

| Layer | v1? | How, in TrialBox terms | Device risk |
| --- | --- | --- | --- |
| Cited record | yes | OMOP events with provenance; the "wiki" page | none |
| Timeline | yes | visits, eras, key events, from OMOP | none |
| Phenotype | yes | named cohort definitions (concept sets plus logic, the ruleset compiler already does this), adopted from the OHDSI Phenotype Library through the item catalogue where a definition exists and re-validated on the site's sample, else site-defined from its templates (§4.7) | none while descriptive |
| Eligibility | yes | per active study, from the last SCREEN plus live unknowns | none (the investigator decides, as today) |
| Personal lab setpoints | yes, behind a flag, screening frame | per analyte: personal mean, SD, RCV over a stable window, n; shown as numbers; used to flag a *screening value* as "outside this patient's usual range: check" | becomes decision support if shown to the treating physician as "abnormal for this patient" in care |
| Gap finder | yes, behind a flag, rule-based first | rules over coded and report text (e.g. UIP wording in a radiology report and no IPF code) produce **proposed** facts with quotes; the LLM may propose too, under D-135; they only ever make a criterion unknown or add a patient to "needs information". **Gate (owner):** a PI of the specialty approves the rule like a criterion (S20); it goes live for research use after at least 7 of 10 sampled hits are confirmed by a CRC or PI. **Add:** the sample is drawn at random from the rule's hits, not chosen; a rolling check keeps the rule live only while confirmed precision stays ≥ 70 % over every 50 hits; each rule ships with a negative-control rule (a pattern that should find nothing) whose hit count is shown beside it; a rule that fails either is switched off automatically and its proposed facts become `rejected` with the reason | becomes diagnosis support if presented as "this patient probably has X" outside a trial context |
| Similar patients | yes, behind a flag, steward and PI only | patient-level vectors within the reader's scope; cohort-by-example for feasibility | low in feasibility; recontact use is out of scope |
| Risk and forecast | later | needs calibration, validation, model registry | SaMD |
| Biological (HLA, PGx, variants) | later | biobank link, separate consent | SaMD when used for therapy |
| Learned patient embedding (foundation model) | later | the owner's Anamnesis plane | depends on use |
| Multimodal encoders | later | out of scope for the box | — |

Said plainly: I would ship record, timeline, eligibility and phenotype as v1.0 and the other three as v1.1 behind flags, because the flags need the excluded-patients page, the conflict queue and the device-qualification view to exist first.

### 4.5 Regulation and privacy

- **Identifiability.** A profile is the most identifying object the box will hold: a full timeline plus free text plus neighbours. It is 要配慮個人情報 (APPI) and special data (Taiwan PDPA). Pseudonymisation does not change that on the box. Consequences: the profile page needs the same reveal discipline as chart numbers (no profile in mail, no profile in exports, no profile to a CRO account), every view audited with the version id, access by the owner's rule, and encryption at rest fixed first (review R-05 is a Blocker that applies doubly here).
- **Taiwan.** The PDPA amendment passed 2025-10-17 and was promulgated 2025-11-11; it creates an independent Personal Data Protection Commission; the effective date is to be set and is expected in 2026 **(verified: Baker McKenzie, K&L Gates)**. Medical records are sensitive data; the legal basis for pre-screening with re-identification is a *counsel* item (SECURITY §7). The 2022 Constitutional Court judgment means an opt-out path.
- **Japan.** APPI: 要配慮; the 2023 生命・医学系指針 opt-out with notice and an ethics committee for existing records; 仮名加工情報 supports research use but not contacting patients; the 次世代医療基盤法 route exists only through a certified operator **(verified in part: MHLW study group 2022; the Act's 仮名加工医療情報 in force since April 2024)**. A hospital's own profiles under its IRB protocol are outside the Act.
- **SaMD line.** Japan: the 2021 プログラムの医療機器該当性に関するガイドライン (amended 2023-03-31) decides by the intended purpose as presented and by risk **(verified: PMDA/MHLW documents)**; it does not name trial pre-screening. Taiwan: TFDA's qualification guidance (revised December 2020) and AI/ML SaMD guidance (2021) **(verified: MOHW index pages)**. TrialBox's non-device position rests on: the investigator decides eligibility; the box never diagnoses, grades or advises treatment; nothing writes to the EMR or reaches patients. Layers that would break that position: **risk/forecast** (any probability about the patient's course), **gap finder presented as a diagnosis** to a treating physician, **setpoint alerts** in a care context, **biological/PGx** used to choose therapy, **recontact** driven by a model. Record, timeline, eligibility and phenotype do not. The owner's §8 says the same for the twin: "SaMD the moment it drives a decision".
- **De-identified consortium profiles.** Only symbolic layers; dates shifted per person; free text, quotes, neighbours and vectors removed (embedding inversion and membership attacks are real, the owner's §9); counts under 5 suppressed (`tb_common/smallcell.py` exists); a DSA and IRB per site; a per-release manifest with hashes, like the refdata pack. The owner's strict defaults (project pseudonyms, ±180-day shift, k = 5, no quotes, no vectors, contracts may only tighten) are in §5.2.

### 4.6 Access design: clinicians, break-glass, monitors, exports

**Roles after the owner's decisions.**

| Role | Sees | Annotates | Chart number |
| --- | --- | --- | --- |
| Data steward | every profile, every layer, conflicts, exports | structured and free text | reveal with reason (today's coordinator rule, D-133) |
| PI | profiles of patients on their studies' lists, all layers | yes, scoped to the study or the person | no (D-133) |
| CRC | profiles of patients on their own study's lists; eligibility and "needs information" items first | yes, as confirmations (D-135) | reveal with reason |
| Clinician (treating physician, not a PI) | profiles of **their own patients**: record, timeline, phenotype, eligibility from the start; setpoints and gaps only after the device-qualification view | yes, scoped to the person | no |
| Sponsor monitor (CRO) | enrolled subjects of their study only: the record items cited by CRF values (SDV view); never the narrative, neighbours, gaps or setpoints | no | no, ever |
| Viewer, administrator | no profiles (administrator: health and audit only) | no | no |

Every view, by page or by `/api/v1`, writes an audit event with user, role, `person_id`, profile version, the layers shown and the **basis of access** (study list, affiliation record, break-glass grant or monitor assignment).

**Clinician affiliation: how "own patients" is decided.** The console user is linked to a hospital practitioner once, by the steward: `user_practitioner (username, practitioner_id, staff_id, department, valid_from, valid_to)`, where `staff_id` comes from the HIS (the lake's `practitioner.staff_id` and the SSO header can carry it; `CANONICAL.md` already maps `practitioner.staff_id, name, dept_code`). A patient is the clinician's own when at least one holds, computed from OMOP every few minutes and stored as `affiliation (person_id, practitioner_id, basis, basis_id, from, to)`:

1. **Encounter provider.** A `visit_occurrence` (or `visit_detail`) in the last N months with `provider_id` = the clinician (`encounter.practitioner_id` in the lake today; SS-MIX2 PV1-7 attending and PV1-9 consulting; CSV `encounter.staff_id`). Default N = 24 months, a site setting.
2. **Scheduled appointment.** An `appointment` with the clinician as actor in the next M days (the lake has `appointment.practitioner_id`). Default M = 90.
3. **Order or diagnosis provider.** A `condition_occurrence`, `drug_exposure` or `procedure_occurrence` with `provider_id` = the clinician in the last N months (OMP ORC-12 ordering provider, PPR diagnosing provider).
4. **Team membership**, optional and off by default: the patient's current admission is under the clinician's department (`encounter.dept`), for sites where attending data is poor. This is wider and the privacy office must switch it on.

What is **not** a basis: the same department in the past, a shared surname, a search by name or chart number. The affiliation table is read-only to users, visible to the steward, rebuilt from the record, and every row names the encounter or order it rests on, so the audit event can say "seen as treating physician: visit 2026-09-14".

**Break-glass.** A clinician, PI or CRC may request access to a patient outside their scope: reason (free text, required), a second person confirms (steward or administrator; never the requester, never another member of the same study), a grant with a hard end (default 24 h, maximum 7 days), scope one `person_id`. Every read during the grant carries the grant id; the grant and its reads appear on the steward's daily list and in the morning mail to the administrator; the patient's profile page shows "accessed under break-glass by ... on ...". No grant may add chart-number reveal to a role that lacks it.

**Sponsor monitor SDV.** A monitor account is bound to one study and sees only subjects in state enrolled or later (`datacore.subject`, D-134). The SDV page shows, per CRF field, the value and the record items its provenance cites (dates, codes, values), each with its OMOP table and id and the hospital source kind, so the monitor can verify without seeing the narrative, free text, neighbours or any other patient. Reads are audited per field. If the built-in forms become the eCRF of record (the open owner question in the review's §6), this view also needs reason-for-change and record lock; until then the page says "worklist and pre-screening record, not the CRF of record".

**Who may change the access tables.** Only the steward and the administrator; every change is an audit event; the affiliation rule's parameters (N, M, team basis) are site settings with history.

### 4.7 The item catalogue, the OHDSI Phenotype Library and "patients like this one"

The owner's direction: subspecialty and clinical items map to existing standards (LOINC scores and panels, OMOP vocabularies from Athena, the OHDSI Phenotype Library, the OMOP Oncology extension, CDISC QRS, NIH CDE / REDCap Shared Library), never invented; a separate agent builds the item catalogue as data; "patient like me" with vectors is part of the patient-finding platform. How these three fit the plan:

**The item catalogue is the `concept` table's front door, not a parallel vocabulary.** Each catalogue item should resolve to: a standard concept where one exists (a LOINC code for a score or a panel member, a SNOMED or ICD-10-CM concept for a condition, an RxNorm/ATC/NHI code for a drug, an OMOP Oncology `episode` / `measurement` concept for stage and histology, a CDISC QRS item for a validated instrument such as DAS28 or CDR, an NIH CDE id for a form field), its OMOP **domain** (`measurement`, `observation`, `condition`, `drug`, `procedure`, `episode`), its **unit** (UCUM), its allowed **value set** for coded answers, and the **local source codes** at each site that feed it (`sitesetup.local_code` becomes a view of the catalogue's `source_map`). An item with no standard concept gets a local concept in the site range **and a ticket**, never a permanent invented code. The catalogue is versioned and shipped like the refdata pack; a catalogue release is approved like a ruleset because it changes counts. In OMOP terms: the catalogue populates `concept`, `concept_relationship` ("Maps to"), `source_to_concept_map` and a small `tb_item (item_id, concept_id, domain, unit_concept_id, valueset_id, instrument, cde_id, version)` table.

Things to watch, from the code: the DAS28, ASDAS, BASDAI and eGFR formulas are hard-coded in `compile_sql/generator.py:206-262` and `tb_common/derived.py` with their own component codes (`CODES`, `COMPONENTS`). The catalogue must own those component codes (LOINC where they exist, CDISC QRS otherwise) and the generator must read them from it, or the two will drift. **(Unverified: which DAS28 components and CDR have LOINC codes; the catalogue agent should check LOINC's clinical-assessment panels and CDISC QRS before minting anything.)**

**The OHDSI Phenotype Library is the phenotype layer's definition source and the gap finder's positive templates.** A library entry is a cohort definition (concept sets plus inclusion logic, with a validation record). Fit:

- The **phenotype layer** item of §4.3 should carry `definition = phenotype_library:<id>/<version>` for an adopted definition, or `site:<id>` for a local one derived from a library template. Adopting a definition means: import its concept sets into the catalogue, run it on the OMOP snapshot with the box's own SQL (the criteria compiler already turns concept sets plus logic into DuckDB SQL; a cohort definition is the same shape), record the count, and compare it with the library's published characterisation where one exists.
- The **gap finder** gets its positive patterns from the same place: "meets the library's phenotype for X by codes and text, has no X diagnosis code" is a gap rule whose approval, 7/10 gate and precision check are in §4.4. The library's definitions were validated on Western, mostly US, data; a site must re-validate on its own sample before the rule goes live, which the 7/10 gate does.
- What the library does **not** give: Japanese and Taiwanese code coverage (its concept sets are SNOMED- and RxNorm-based), so each adopted definition needs the consortium's local maps; and the SNOMED licence question of §2.5 applies to the concept sets themselves.

**"Patients like this one": two similarities, both explainable, never one black box.**

| | Structured-feature similarity | Embedding similarity |
| --- | --- | --- |
| Input | a per-patient feature vector built from the catalogue: one slot per item (present/absent, latest value z-scored against the site, time since first and last), plus age band, sex, visit counts | a per-patient vector derived from note chunk embeddings (mean of the last N chunks, or the chunk-set centroid per note type) and, later, a concept-sequence embedding |
| Where it lives | `person_feature (person_id, catalogue_version, features jsonb, vector halfvec(k))`, k ≈ 200–2,000 catalogue items | `person_vector (person_id, model, as_of, embedding halfvec(1024))` |
| Distance | weighted cosine or Gower on the feature vector; weights per use (eligibility items up-weighted for a given study) | cosine |
| Explainable? | yes: the top contributing items are listed ("both have RA seropositive, MTX exposure, CRP 2–4 mg/dL, aged 55–64") | no, by itself; explained only by retrieving the chunks that drive the similarity and showing them |
| Fails when | items are missing or unmapped at one site (the catalogue's coverage report shows this) | notes are sparse, or one patient has long discharge summaries and the other only progress notes |
| Good for | feasibility ("how many patients look like this index case on the items this protocol cares about"), cohort-by-example with a reason | catching what codes miss (a phenotype described only in text), ranking within a structured candidate set |

Recommendation: **structured first, embedding as a re-ranker**, in the same query. A "patient like me" call takes an index patient, builds the structured neighbour set within the reader's scope (top 200 by weighted feature distance), re-ranks it by embedding cosine, and returns each neighbour with the shared catalogue items and, for the embedding part, the two or three chunk pairs with the highest similarity, shown as quotes. The page never shows a similarity score alone. In the profile object this is the `similar` layer with `basis: {structured: [...item ids], text: [...chunk pairs]}`.

Which features feed the structured vector: every catalogue item that is a phenotype component, an eligibility atom in any active ruleset, or a specialty core item (the first templates), plus demographics. Not: free text, chart numbers, dates (only intervals), provider ids, department (a site setting may add it for feasibility). The feature vector is rebuilt when the catalogue version changes; neighbours from different catalogue versions are never mixed.

Where this sits in the plan: the catalogue work lands with step 2 (it populates `concept`), the structured feature vector with step 7 (symbolic profile), the embedding re-ranker with step 9 behind the same flag as neighbours. The catalogue's coverage report (items with no local source at a site) belongs on the readiness page beside D-130's unknown code systems.

---

## 5. Reconciliation and consortium

### 5.1 Conflict states and authority

Every clinical fact has a **status** (coded, proposed, confirmed, signed, rejected, superseded) and may be party to a **conflict**. States of a conflict: `open`, `keep_a`, `keep_b`, `both_at_dates`, `unknown`. A conflict is opened by the assembler when two facts of the same concept family disagree in a way that matters: a value outside the other's RCV on the same day, a diagnosis present and explicitly negated, a unit mismatch, a date impossibility.

Authority is **not** a fixed ranking applied by the machine; it is a person's decision with a default view:

| Pair | Default shown | Who resolves | Effect while open |
| --- | --- | --- | --- |
| Hospital coded vs LLM proposed | coded stands; proposed shown beside its quote | CRC confirms or rejects the proposed fact (D-135) | criterion unknown if it could change the answer |
| Hospital coded vs physician signed annotation | both, with a conflict badge | steward, or the PI of that study | unknown |
| Two hospital sources (feed vs sheet vs chart) | both; demographic ones already listed by `publish.disagreements()` | steward | unknown; patient "needs information" |
| Note text vs coded (judge says "fail", code says "met") | both quotes (D-120 both opinions) | the two-model rule decides exclusion; otherwise review | unknown, never exclusion on disagreement (D-115) |
| Hospital A vs hospital B (consortium) | never merged | each box keeps its own; counts are per site | n/a |

"This differs by hospital" (the owner): the *default view* and the conflict thresholds are site settings (RCV tables, which note types count, which departments' codes are trusted), stored in `tb_omop.site_policy` with versions, never in code.

### 5.2 Cross-hospital alignment

- **Standard concepts plus local maps.** Each hospital keeps its local codes as source values and local concepts; a consortium **concept map registry** (versioned, in git, packaged like the refdata pack) maps local → standard (ICD-10-CM / WHO ICD-10 category bridge, LOINC via NHI and JLAC10 maps, ATC codes from the NHI list, 薬効分類 classes, UCUM). The open-data review's P0 list is exactly this registry's first release.
- **Concept-id ranges.** One range per hospital for local concepts, assigned by the consortium lead, so two boxes never collide and a later merge of counts is a union.
- **Phenotype definitions** as shared cohort definitions (concept sets plus logic), versioned, run locally.
- **Federated counts.** v1: each box runs the shared definition on its own OMOP snapshot and exports a signed counts file (small cells suppressed), carried by a person; the lead merges. v2: the OHDSI study-package pattern (R or Python) run locally, results out only. No central patient store, ever (the owner's rule that Aimedics holds no patient data extends to the consortium).
- **De-identified profiles** under IRB and DSA, hashes and manifests per release, with the owner's strict defaults as the floor that a contract may only tighten:
  - **Project pseudonyms**: a per-project HMAC of the site pseudonym with a per-project key held by the site; two projects cannot be joined; the site keeps the map.
  - **Date shift**: one random offset per person in ±180 days, applied to every date of that person so intervals survive; ages as 5-year bands, 90+ as one band; no exact birth date.
  - **k = 5 over quasi-identifiers**, not only over count cells: the combination (age band, sex, site, rarest concept in the record) must occur at least five times in the export; a rare concept (fewer than five persons) is generalised to its parent in the hierarchy or dropped; free-text fields, quotes, note types with dates, neighbours and vectors are removed; `tb_common/smallcell.py` already gives the cell rule.
  - **Provenance kept, identity not**: each fact keeps its status (coded, confirmed, signed) and source kind, never the source file name or the person who decided.
  - **A release manifest** with the parameters used, the record counts, the suppressed counts and hashes, signed by the box; the receiving site verifies it as `refdata.verify` does today.
  - **Review by the privacy office** of the first export of each project; a re-identification check against the site's own data (how many persons are unique on the exported fields) is printed in the manifest.

### 5.3 Governance

- A consortium terminology steward who owns the map registry's releases; each site's data steward signs the site's local map (`sitesetup.local_code.mapped_by` exists; add a countersignature from a specialty PI for specialty items).
- Change control: a map release changes screening counts; it ships with before/after funnel counts on the synthetic hospitals (the open-data review §3 method) and is approved like a ruleset.
- A data-sharing agreement template; an IRB protocol per site; a per-release manifest; audit of every export.

---

## 6. An integration plan

Each step ships alone and is testable. The golden rule: **the GOUT-COH funnel (`e2e_simple.py:729-751`) and a committed per-ruleset funnel golden (review R-67) must be identical after every step**, at 5,000 (the gate) and at the 50,000 synthetic hospital. Effort is engineer-days; S ≤ 1, M 2–5, L > 5. The review's Wave 1 and Gate G1 come first and are not counted here.

| # | Step | What ships | Done-check | Effort | Risks |
| --- | --- | --- | --- | --- | --- |
| 0 | Goldens and baselines | Per-ruleset funnel goldens at 5k and 50k; lake table row-count and hash goldens; a `perf` baseline of rebuild and SCREEN times | goldens committed; CI fails on a changed count | 3 | none |
| 1 | Postgres hardening (from Wave 1) | connection pool, `SELECT 1` health, container limits, migration checksums (R-13, R-17) | a Postgres restart under load recovers; OOM test passes | 4 | already planned |
| 2 | OMOP CDM v5.4 writer and the item catalogue | database `tb_omop`; DDL from the OHDSI repo; `concept` loaded from the Athena vocabularies the licences allow plus the item catalogue's standard and local concepts (`tb_item`, `source_to_concept_map`, §4.7); the adapter writes OMOP staging from its canonical rows beside NDJSON; `COPY` loads; `tb_fact_provenance`, `tb_fact_status`, `tb_conflict`; DQD-lite checks (person/visit/observation_period integrity); the derived-score components read from the catalogue | OMOP row counts equal the lake's per table at 5k and 50k; every catalogue item resolves to a concept and a domain; the catalogue coverage report lists unmapped items per site; load time per night recorded | 20–25 | local vocab gaps; `person_id` minting; load speed; SNOMED-based concept sets without a licence |
| 3 | HAPI out of the nightly path | FHIR NDJSON generated from OMOP on demand; JP Core validation kept; CQL gate moved to CI | the gate passes in CI on the off-list fixtures; a night without HAPI is shorter by its load time | 5 | the gate needs a HAPI in CI (compose) |
| 4 | Lake exported from OMOP | views OMOP → `flatten.SCHEMAS` columns; Parquet and DuckDB built from them; new columns `value_text`, `verification_status`; the generator returns NULL on text-only labs and treats suspected as unknown for exclusions (R-02, R-08) | funnel goldens identical where no text lab or 疑い exists; the new fixtures move exclusions to unknown as specified | 10–15 | subtle date/time-zone drift between flatten and views; measure byte equality of the generated SQL's output |
| 5 | `note_chunk` and pgvector | sentence-aware chunker with offsets; `note_chunk` with `halfvec`, HNSW, btree; dual-write with `document_chunk`; `search()` parity test (same top-k, same RRF) behind a flag; CPU incremental embedding nightly | parity ≥ 95 % top-5 overlap on the public notes; re-embed drill with the shadow column | 10–15 | index build time; backup size; CJK FTS parity |
| 6 | Facts, annotations, conflicts unified | `sitesetup.fact` migrated to OMOP + status + provenance; `annotation` schema and pages; `tb_conflict` queue page for steward and PI; the excluded-patients page (R-07) | `test_one_rule.py` unchanged and passing on the OMOP-backed lake; a signed annotation that excludes appears on the excluded page with the annotation as evidence; an open conflict gives unknown | 15 | role rules; signature re-authentication (needs MFA from Wave 2) |
| 7 | Profile object v1.0, symbolic | assembler for record, timeline, eligibility, phenotype (definitions adopted from the OHDSI Phenotype Library through the catalogue, or site-defined from its templates); `person_feature` structured vectors from catalogue items; `profile_version`; the wiki page; access rule including the clinician role, `user_practitioner`, `affiliation` and break-glass (§4.6); view audit with basis of access; monitor SDV view; `schemas/profile.schema.json` | the page for every role in three languages; audit of every view with its basis; a clinician sees only patients with an affiliation row and the page names the visit; break-glass needs a second person and expires; symbolic profile for 50k synthetic patients built in under one night on CPU | 20–25 | scope creep into narrative; the clinician role needs MFA and SSO (review R-04, R-11) first |
| 8 | Narrative with citations | digest builder; retrieval over the person's chunks; prompt `profile_v1` through the gateway; citation and number checks; abstain; nightly incremental queue; diff view | on the synthetic hospital with planted findings: 0 uncited sentences published; ≥ 95 % of planted facts cited; cost per profile measured on the card; first-build nights estimated from the measurement | 15 + one GPU run | model cost; prompt injection suite (R-35) must exist |
| 9 | Setpoints, gap finder, similar patients (flags) | per-analyte setpoints over OMOP measurements; rule-based gap rules as proposed facts with the S20-style approval, the random 10-hit sample, the 7/10 switch-on, the rolling precision check and a negative-control rule per rule; `person_vector` and neighbours within scope, structured-first with embedding re-ranking and shared items plus chunk pairs as the explanation (§4.7); both layers hidden from the clinician role until the device view | planted gaps found as proposed facts and never counted; a rule below 7/10 stays off; a rule that drops under 70 % over 50 hits switches itself off; setpoints equal a reference implementation; neighbours never cross the reader's scope | 15–20 | device line; false "gaps" from care elsewhere (the owner's §9) |
| 10 | Consortium v1 | concept-map registry release; local concept ranges; shared cohort definitions; signed counts export with small cells; de-identified symbolic profile export | two synthetic sites produce mergeable counts; the export contains no free text, no vectors, no cells under 5 | 15–20 | agreements take longer than code |

**Total: about 135–180 engineer-days** after Wave 1 and Gate G1, with steps 2–5 doable by a second engineer in parallel with Waves 2–3 of the review. Steps 0–5 change nothing a CRC sees. Steps 6–8 are the owner's "profile".

**Risks across the plan.**

- Doing OMOP before the stability fixes moves the same faults to a bigger database. Step 1 first.
- The 5090 tier: no narrative; say so in the tier table.
- Backup size and time grow with vectors; the backup drill (`tools/backup_drill`) must include `tb_omop`.
- Two engineers writing the OMOP exporter and the lake reader at once can drift; the goldens are the contract.
- Local vocabularies: without the MEDIS permission and the NHI/LOINC maps the OMOP core will have many local-only concepts; that is acceptable (fail-closed stays) but the consortium benefit waits.
- Regulatory: shipping step 9 to treating physicians before a device-qualification view would be a mistake.

---

## 7. Questions for the owner

The decided items of §0.2 are not re-asked. Each question has options and my recommended answer with a one-line reason.

### Scope

1. **Which patients enter the repository?** (a) every patient in the hospital feed; (b) only patients of the departments of participating PIs and clinicians; (c) only patients covered by a research opt-out notice or consent. **Recommend (a) for pseudonymised facts and feasibility, as today, and (b) for profiles.** Reason: feasibility needs the whole population; profiles are identifying and should stay where an IRB protocol or a treating relationship covers them.
2. **How far back do we load and embed?** (a) 2 years; (b) 5 years; (c) everything the hospital exports (CGRD goes back to 2001). **Recommend (b) for v1, (c) for structured facts when the box is proven.** Reason: notes older than five years rarely decide eligibility and they dominate embedding and storage cost.
3. **Which phenotype templates first, two per specialty?** For example rheumatology: RA seropositive, gout; neurology: MCI/dementia with CDR, epilepsy; oncology: by primary site and stage; nephrology/general: CKD stage, diabetes. **Recommend the owner names two per specialty from the studies the first sites will run.** Reason: templates are only useful if a real study needs them in the first year.
4. **Do clinicians see the setpoint and gap layers before a written device-qualification view exists?** (a) no: record, timeline, phenotype and eligibility only until then; (b) yes, labelled "research use, not for clinical decisions"; (c) yes, without a label. **Recommend (a).** Reason: a label does not change what a regulator sees as the intended use; the layers are the same for PI and CRC inside screening, where the frame is clear.

### Roles and governance

5. **Who signs a local code map?** (a) the data steward alone; (b) the steward plus a specialty PI for specialty items; (c) a hospital terminology committee. **Recommend (b).** Reason: a wrong lab or score mapping changes counts silently and a clinician will catch it.
6. **May the steward read every patient's free text?** (a) yes, audited; (b) only when a conflict or a check item needs it; (c) never, text stays with the PI. **Recommend (b) technically enforced, with (a) as the fallback the privacy office approves.** Reason: the steward's job needs it sometimes; "always" is hard to defend under APPI/PDPA minimisation.
7. **How long are profile versions and annotations kept?** (a) until the study ends; (b) 10 years like the audit; (c) forever. **Recommend (b).** Reason: it matches the audit and the retention table already in SECURITY §6.
8. **Clinician affiliation window.** A patient counts as a clinician's own when the clinician was the encounter or order provider in the last: (a) 12 months; (b) 24 months; (c) 60 months; plus appointments in the next 90 days. **Recommend (b).** Reason: chronic-disease follow-up in rheumatology and neurology is often yearly; 12 months drops real patients, 60 keeps patients who have moved on.
9. **Is "same department as the current admission" an allowed affiliation basis?** (a) no; (b) yes, for inpatients only, switched on by the privacy office per site; (c) yes, everywhere. **Recommend (b).** Reason: attending data is poor at some sites, but department-wide access to outpatients is too wide.
10. **Who may be the second person for break-glass, and at night?** (a) steward or administrator only, with an on-call rota; (b) also the PI of any study the patient is on; (c) also the department head. **Recommend (a).** Reason: the second person must have no stake in the study; the rota is a hospital matter the DSA should name.
11. **Who confirms the 10-hit sample of a new gap rule?** (a) a CRC; (b) the approving PI; (c) either, but not the rule's author. **Recommend (c).** Reason: independence matters more than role; the author should never grade their own rule.

### Data model

12. **Where do trial facts (consent, visits, AEs) live relative to OMOP?** (a) only in `datacore`; (b) mirrored read-only into OMOP for consortium queries; (c) moved into OMOP. **Recommend (b).** Reason: one writer per fact (D-123) is kept and consortium queries still see enrolment.
13. **What happens to HAPI?** (a) keep it as a nightly mirror; (b) exchange only, FHIR generated on demand, gate in CI; (c) remove FHIR entirely. **Recommend (b).** Reason: nothing reads it at run time and the nightly load costs hours; JP Core/TW Core remain the exchange contract.
14. **Unmapped local codes in OMOP:** (a) `concept_id = 0` with the source value (OHDSI default); (b) a local concept per code in a per-site id range; (c) both, with (b) only after a person maps it. **Recommend (b).** Reason: counts by local concept are possible on day one and fail-closed screening is unchanged.
15. **When a catalogue item has no standard code anywhere (LOINC, SNOMED, CDISC QRS, NIH CDE):** (a) a local concept in the site range plus a ticket to the standards body, reviewed each release; (b) refuse the item until a standard exists; (c) a consortium-wide local concept. **Recommend (c), with the ticket.** Reason: the owner's rule is "map, don't invent", but a few specialty items will have no home and two sites must still count them the same way. (LOINC coverage of CDR and the DAS28 components: **unverified**, for the catalogue agent to check.)
15b. **Which Phenotype Library definitions are adopted first?** (a) one per first template (RA, gout, MCI/dementia, epilepsy, the first oncology sites, CKD, type 2 diabetes), re-validated on each site's sample; (b) the whole library; (c) none, site definitions only. **Recommend (a).** Reason: each adopted definition needs local code maps and a validation sample; seven is a quarter's work, the library is not.
15c. **"Patients like this one" default:** (a) structured catalogue items first, embedding re-rank, both explained; (b) embedding only; (c) structured only. **Recommend (a).** Reason: an unexplained neighbour cannot be acted on in a trial or defended to a regulator; embeddings add what codes miss.
16. **Point-in-time for OMOP:** (a) lake snapshots only, OMOP is live; (b) `recorded_at` / `valid_to` columns on OMOP rows so "facts as of" is a query; (c) monthly OMOP dumps. **Recommend (b).** Reason: a profile's "as of" and a re-run's snapshot must be reproducible without file copies.
17. **When a PI's spreadsheet disagrees with the hospital feed on the same item:** (a) the feed wins, the sheet value is shown as a note; (b) the sheet wins; (c) a conflict is opened and the patient is "needs information" until the steward or PI resolves it. **Recommend (c).** Reason: the owner trusts sheet values as coded, and the feed is coded too; two coded values that disagree are exactly what the conflict queue is for.
18. **Who holds the SNOMED Affiliate Licence if one is sought?** (a) Aimedics as vendor, sub-licensed per deployment; (b) each hospital as end user; (c) the consortium lead hospital for all members. **Recommend (a) for a product sold to several hospitals, (c) if the consortium is the buyer.** Reason: the fee basis in non-member territories is per deployment or organisation and the holder must track deployments; a vendor already does. (Fee schedule **unverified**; request it from SNOMED International.)
19. **Until SNOMED is settled, the consortium's standard for conditions is:** (a) ICD-10-CM with the WHO ICD-10 category bridge; (b) the free SNOMED IPS subset where it covers, ICD-10-CM otherwise; (c) wait. **Recommend (a).** Reason: it is what every ruleset already compiles to, and the mapping to SNOMED later does not move screening.

### Vectors

20. **Which embedding model?** (a) keep bge-m3; (b) evaluate Qwen3-Embedding-0.6B and switch if it wins in ja and zh-TW; (c) a Japanese-only model (Ruri) at Japanese sites. **Recommend (b), default (a) until the eval.** Reason: same 1024 dimensions, likely better multilingual scores, same cost.
21. **Which text is embedded?** (a) all note types, 5 years; (b) progress, discharge, consult and reports only; (c) everything ever. **Recommend (a).** Reason: nursing notes carry functional status and adherence that criteria ask for; 5 years bounds cost.
22. **Do vectors go in the backup?** (a) yes, in the `.tbbak`; (b) no, re-embed after restore; (c) a separate vector backup. **Recommend (a).** Reason: a restore must work offline in one step; re-embedding needs the model and hours.
23. **Scope of "similar patients":** (a) within the reader's studies or affiliation only; (b) the department; (c) the whole hospital for the steward. **Recommend (a) for PI, CRC and clinician, (c) for the steward with audit.** Reason: neighbours leak information about patients the reader has no reason to see.
24. **Where should the embedder run on the shared card?** (a) CPU always; (b) GPU for the first build and model changes, CPU nightly; (c) GPU always. **Recommend (b).** Reason: nightly increments are small; the first build is not.

### Profiling

25. **Narrative language:** (a) the site language only; (b) site language plus English; (c) all three. **Recommend (a), with English on request for the owner's own reading.** Reason: every extra language doubles the cost and the citation checks.
26. **Page shape:** (a) one page of prose; (b) sections per layer, each sentence cited, one-paragraph summary on top; (c) a table-only dossier with no prose. **Recommend (b).** Reason: a clinician reads the summary, an auditor opens a section, and both see the citations.
27. **May anyone edit the narrative?** (a) nobody; physicians annotate and the narrative regenerates showing the annotation; (b) the PI may edit sentences; (c) the steward may edit. **Recommend (a).** Reason: an edited model sentence has no citation discipline and would become a fact by stealth.
28. **Does an open conflict block "ready"?** (a) yes, the patient is "needs information" until resolved; (b) no, show a badge only; (c) PI's choice per study. **Recommend (a).** Reason: it is the D-130/D-135 rule applied to people's disagreements, not only to codes.
29. **May the LLM propose gap facts in v1, beside the approved rules?** (a) no, rules only; (b) yes, as proposed facts under D-135, once the prompt-injection suite (review R-35) passes; (c) yes now. **Recommend (b).** Reason: the proposed-fact path already exists and is safe by construction; the injection suite does not exist yet.
30. **Setpoints presentation:** (a) numbers only (personal mean, RCV, n); (b) numbers plus "outside this patient's usual range: check" on screening values; (c) alerts in mail and on the clinic list. **Recommend (b), never (c) before a device view.** Reason: (b) serves screening; (c) is care decision support.
31. **Abstain threshold for the narrative:** (a) publish if ≥ 95 % of sentences are cited; (b) ≥ 80 %; (c) always publish the cited subset. **Recommend (a) at the start.** Reason: the first readers decide whether they trust the box; a half-empty profile is better than a wrong one.
32. **Which CRF fields may a sponsor monitor source-verify?** (a) every field of the sponsor's own instruments for enrolled subjects; (b) only eligibility and safety fields; (c) the PI chooses per study. **Recommend (a), with the SDV view limited to the cited record items.** Reason: that is what SDV means in GCP; the limit on what is shown, not on which fields, protects the rest of the record.

### Consortium

33. **How do counts travel between hospitals in v1?** (a) a signed file carried by a person; (b) an automated API between boxes; (c) a central hub run by the lead hospital. **Recommend (a).** Reason: no network path between hospitals exists today and a file fits the DSA review.
34. **Who hosts the concept-map registry?** (a) the lead hospital (CGMH) in git, Aimedics packages releases; (b) Aimedics; (c) submit to OHDSI Athena. **Recommend (a), and (c) later for the Japanese and Taiwanese vocabularies.** Reason: the data owners should own the maps; Athena submission is the long-term path (OHDSI Japan is already discussing YJ and JLAC registration).
35. **Who reviews a project's first de-identified export against the k = 5 and rare-concept rules?** (a) the exporting site's privacy office; (b) the consortium lead; (c) both. **Recommend (c) for the first export of each project, (a) after.** Reason: the receiving side sees the join risk the exporter cannot.

### Regulation

36. **Do we seek a written device-qualification view before the setpoint and gap layers reach clinicians?** (a) yes, Japan 該当性 consultation and TFDA qualification inquiry first; (b) only before commercial sale; (c) no. **Recommend (a).** Reason: the two layers sit on the line and a written view protects the pilot sites as much as Aimedics.
37. **Legal basis for profiles in the pilot:** (a) the same IRB opt-out protocol as pre-screening, profiles listed as an output, plus the treating relationship for the clinician role; (b) a separate consent; (c) counsel decides per site. **Recommend (a) with (c) confirming per site.** Reason: profiles are a view of the same data; a separate consent would exclude most patients; the clinician's own-patient access rests on the care relationship, not on research.
38. **Audit of profile views:** (a) every page and API view with version id and basis of access, kept 10 years; (b) sampled; (c) page views only. **Recommend (a).** Reason: APPI and the Taiwan EMR regulation ask for a full access log, and the profile is the most sensitive page.

### Budget and hardware

39. **Which tiers get the narrative?** (a) `large` and `medium` only; `small` (5090) gets symbolic layers; (b) all tiers, with a smaller model on the 5090; (c) `large` only. **Recommend (a).** Reason: 8k context and the sleep swap make the 5090 unfit; a third model would need its own validation.
40. **Disk and RAM for the first site:** (a) 2 TB NVMe and 128 GB RAM; (b) 1 TB and 64 GB; (c) size per site from the note volume. **Recommend (a) as the default, (c) to confirm.** Reason: OMOP plus 4.5 M chunks plus backups and snapshots fit in 2 TB with headroom; HNSW likes RAM.
41. **Is a paid GPU run to measure profile cost acceptable before the design is final?** (a) yes, one run on the PRO 6000 VM (about US$15–30); (b) measure on the first site's box; (c) no. **Recommend (a).** Reason: every estimate in §4.1 rests on one S3 measurement; a profile prompt is a different shape.
42. **A budget line for SNOMED:** (a) ask for the quote now and decide with the number; (b) budget nothing until the consortium asks for an OHDSI network study; (c) decide now to license. **Recommend (a).** Reason: the fee basis is unverified and the v1 path does not need it.

### Timeline

43. **Order of work:** (a) Wave 1 and Gate G1 first, OMOP (steps 2–5) in parallel by a second engineer; (b) OMOP first, then the review's waves; (c) the review's waves alone until the pilot. **Recommend (a).** Reason: the pilot blockers are safety items; the OMOP steps change nothing a CRC sees and can overlap.
44. **First profile readers:** (a) the steward only for one month as a data-quality tool, then PI, CRC and clinicians; (b) all roles on day one; (c) PI and CRC first, clinicians later. **Recommend (a).** Reason: the steward finds the mapping and conflict faults before a clinician sees a wrong sentence; the clinician role then starts as decided, with the two layers held back per question 4.
45. **When does the consortium work start?** (a) after two sites run the OMOP core; (b) now, with the concept-map registry only; (c) after the pilot year. **Recommend (b).** Reason: the registry is needed by the first site anyway; everything else needs two running sites.

---

## Appendix A. Files read

`docs/ARCHITECTURE.md`, `docs/DATA.md`, `docs/SECURITY.md`, `docs/DECISIONS.md` (D-120 to D-140, D-12, D-80, D-105), `docs/reviews/2026-11-09-full-system-review.md`, `docs/reviews/2026-11-09-review-parts/01-architecture-serving-stability.md` (summary), `docs/reviews/2026-11-09-baseline-open-data.md`, `docs/plan/24-plan-v4.md` (OMOP line), `spec/v4/04_architecture_llm_hermes.md` (omop-db, ADR-V4-10), `spec/v4/05_data_platform_model_privacy.md` (L2–L5).

Code: `services/lake/store.py`, `flatten.py`, `textproc.py`, `sqlguard.py` (name only); `services/embed_service/embedder.py`, `app.py`; `services/matching/cascade/engine.py` (notes, S2/S2b), `s2b_semantic.py`, `proposed.py`; `services/criteria_compiler/compile_sql/generator.py`, `terminology/mapper.py`; `services/adapter/pipeline.py`, `pidmap.py`, `licensed.py` (schema), `mapping/templates/CANONICAL.md`; `services/sitesetup/store.py`, `publish.py`, `service.py` (outline); `services/datacore/store.py`; `libs/tb_common/db.py`, `refdata.py` (schema); `services/console/auth.py` (roles, scope, reveal); `deploy/docker-compose.yml`, `docker-compose.rtxpro6000.yml`, `docker-compose.gb10.yml`, `.env.example`; `tools/e2e_simple.py` (GOUT_COH_BEFORE_STEP7); `pyproject.toml`, `deploy/requirements.lock`.

## Appendix B. Web sources used today

- pgvector CHANGELOG (GitHub master): versions 0.8.0 (iterative scans, 2024-10-30) to 0.8.7 (2026-10-01); 0.9.0 unreleased.
- DuckDB `vss` documentation (core extensions page): experimental persistence, no WAL recovery for the index, "do not use in production".
- Qwen3 Embedding model card and paper (arXiv 2506.05176): MTEB multilingual 64.33 (0.6B), 69.45 (4B), 70.58 (8B); bge-m3 59.56; multilingual-e5-large-instruct 63.22; C-MTEB retrieval 71.03 (0.6B).
- Sionic AI comsat-embed-ja model card: JMTEB v2 retrieval Qwen3-Embedding-4B 0.7779, ruri-v3-130m 0.7641, bge-m3 0.7245. Ruri v3 cards: JMTEB v1 averages 74.51–77.24; multilingual-e5-large 71.65.
- OHDSI: APAC community calls 2025–2026; Yamashita 2025 (Japan EMR sharing service, YJ and JLAC mapping); OHDSI forum thread on registering YJ/JLAC in Athena; OHDSI NLP paper (CDM 5.4 NOTE/NOTE_NLP) and brief report on pushing NLP facts into event tables; TMU clinical research database converted to OMOP; Taiwan NHIRD conversion (86.7 % of drug codes to RxNorm). ISPOR 2026 abstract: "no Japanese OMOP vocabulary exists".
- Japan: MHLW/PMDA プログラムの医療機器該当性に関するガイドライン (2021-03-31, amended 2023-03-31). MHLW 2022 study group on 仮名加工情報 in medicine. RIKEN 2025 (次世代医療基盤法 certified use).
- Taiwan: Baker McKenzie and K&L Gates notes on the PDPA amendment (passed 2025-10-17, promulgated 2025-11-11, PDPC, effective date pending). MOHW index pages for TFDA SaMD qualification (Dec 2020) and AI/ML SaMD guidance (2021).

Unverified and marked so in the text: CJK FTS extension packaging for the pinned Postgres image; LOINC coverage of CDR and DAS28 components; embedding throughput on the box's cards; the Gemma profile cost per patient; chunk counts per patient at a real site.
