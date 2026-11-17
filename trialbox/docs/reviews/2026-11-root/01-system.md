# The system from the root, layer by layer, with measurements (lane J, job B-1, 2026-11-17)

**Reader:** the owner first (the one-page summary), then the builders (the layers), then plan 9 (the fix table at
the end).

**What was analysed:** master `15108f46` (train 76) and the stored launch traces of P2b on the branch
`integrator/p2b-artefacts` (read, not merged). One synthetic hospital already seeded on this machine
(`/var/tmp/trialbox-0/j1/box`, 5,001 Taiwanese and 400 Japanese synthetic patients) was read; nothing was seeded
again. No GPU, no network service, no model, no hospital data. Public and synthetic data only.

**What this page adds.** The two reviews of today (`docs/reviews/2026-11-17-full-review.md`, areas I to N, and
`docs/reviews/2026-11-17-journey-and-simplicity.md`, areas A to H) and plan 8 (`docs/plan/44-plan-8-2026-11-17.md`)
are not repeated. Where this page agrees with one of their findings it cites the id (I-3, J-2, C-1, ...) and adds
only what is new. The standards review of 2026-11-12 (`docs/reviews/2026-11-12-deep-review/11-standards.md`,
STD-001 to STD-021) is used the same way.

**How every claim is marked.**

| Mark | Meaning |
| --- | --- |
| **[M n]** | Measured: the command is row n of the measurement log (section 11), with its number |
| **[R]** | Read: the file and line follow in backticks |
| **[S]** | Source: a public link follows |
| **[O]** | Opinion: the analyst's judgement, to be argued with |
| **not verified** | Could not be checked here; section 12 lists each |

---

## Summary (one page, plain words)

**TrialBox is a careful product built as many careful parts. The parts are good; the joins are where it loses
time, accuracy and simplicity.** [O]

1. **The data connectors are fewer and narrower than they look.** Four batch readers exist: hospital CSV files, a
   SQL replica, FHIR export files and SS-MIX2 [R `services/adapter/sources/`]. The SQL reader cannot open the Oracle
   or SQL Server databases its own comment names, because no driver for either is installed [M 18]. There is no live
   HL7 v2 feed (no MLLP listener), no FHIR server client, no US Core profile, and nothing that reads Taiwan's NHI
   claim files or MediCloud [M 21]. [O] For a hospital in the US, the box today can only read files someone else
   exports for it.
2. **SS-MIX2 is the strongest connector**, and the owner's "must" is mostly met: the folder tree, versioning by
   timestamp, deletion flags, five character-set variants and ten message types are read and tested
   [R `services/adapter/sources/ssmix2/source.py:1-70`; M 3, M 4]. Missing: allergies (ADT-61), orders (OML-01,
   OMG), transfers and leave (ADT-21/31/41/51), the `_contents.xml` index of extended storage, and one real
   vendor's storage read end to end (STD-014, unchanged) [R].
3. **The model does work that a table should do.** The compiler's drug and lab code tables hold 33 ATC rows, 27
   LOINC rows and 24 NHI drug rows [M 5]. So in the P2b launch the large model was asked 676 times to pick a code
   (`concept_map`), more than three times the 200 calls that read the protocols, and 43 % of all criteria ended
   as "a person decides" [M 6, M 8]. Loading the public code systems onto the box (TERM-1/2 of plan 8) is the
   cheapest accuracy fix in the product. [O]
4. **The small-model filter in front of the large model filtered nothing in the real runs.** In P2b, the
   keyword step found words in 4 of 292 sigir pairs and 0 of 500 tcga pairs, and the embedding step then sent
   every remaining pair (788 of 788) on to the large model [M 7]. The "mixture, not all LLM" the owner asked for
   exists in design but not yet in effect. [O]
5. **One fact lives in up to seven places.** A hospital row becomes a FHIR file (7 times the CSV's size), a
   Parquet file, a DuckDB file, optionally a FHIR server copy and an OMOP copy, note chunks in two vector stores
   [M 1, R]. Two screening engines (v1 and the cascade), two lake sources (legacy and OMOP), three chunkers and
   three detectors of identifiers live side by side [R; M 15].
6. **The identifier guard has three implementations that disagree.** On 18 synthetic probes the compiler's
   check caught 5, the note masker 14, the gateway's guard 13. A Taiwan ID number written in full-width digits
   (common in CJK text) passed all three; so did a US Social Security number [M 15].
7. **Rust: not now.** [O, from M 19] The measured time sits in the model (most of a night's wall time, on a GPU), in JSON
   serialisation and per-row Python in the adapter and lake (minutes per night), and in DuckDB (already native).
   A second language in a validated product costs more than the minutes it would save. The cheaper compiled
   paths are already in the dependencies: DuckDB's own JSON reader and Arrow (section 6).
8. **The serving engine is held back by its own flags.** Both model servers run with CUDA graphs off
   (`--enforce-eager`) [R `deploy/docker-compose.rtxpro6000.yml:70,83`] and the engine is two minor releases old
   [M 11]. On P2b the judge pair ran 3.1 calls a second on tcga, but protocol reading crawled: one `ir_extract`
   call every 16 s at the median, with seven "gave up, ask again in parts" retries [M 6, M 9]. One measured GPU
   run (section 3.5) decides the flags.
9. **Interoperability by country:** Taiwan and Japan are well served at the profile level (TW Core 1.0.0, JP Core
   1.1.0 outputs are checked) [R]; the US is not served at all (no US Core, no Bulk Data client, no SMART, no
   HIPAA de-identification rule) [M 21]. [O] Release 1.0 should say "Taiwan and Japan" plainly.

**The twelve fixes that matter most** are marked ★ in the table of section 10. Three are a day's work each: a
real driver for Oracle and SQL Server, one identifier guard with Unicode normalisation, and refusing to screen
with the hash stand-in embedder on a production box.

---

## 1. Data in

### 1.1 The connectors that exist

| Connector | Code | Reads | Tested by | Verdict |
| --- | --- | --- | --- | --- |
| Hospital CSV export | `services/adapter/sources/csv/source.py` (143 lines) | One file per canonical table; UTF-8, Shift_JIS, Big5 weighed per file; quarantine of unreadable files [R :65-77] | 81 test files name it [M 22] | **Complete for files**; the workhorse of every demo |
| SQL replica ("CGRD") | `services/adapter/sources/cgrd_sql/source.py` (139 lines) | Any SQLAlchemy DSN; delta by a change-time column [R :1-6] | 6 test files, SQLite only [M 22] | **Partial**: docstring says "Oracle/MSSQL on site", but `uv.lock` has neither `oracledb` nor `pyodbc`/`pymssql` [M 18]. It can read PostgreSQL and SQLite only |
| FHIR Bulk Data files | `services/adapter/sources/fhir_bulk/source.py` (47 lines) | `*.ndjson` in a folder; `DELETE` bundles as tombstones [R :1-47] | 6 test files [M 22] | **Partial** (STD-013, unchanged): no `$export` kick-off, no polling, no SMART Backend Services |
| SS-MIX2 standardised and extended storage | `services/adapter/sources/ssmix2/` (1,161 lines) | 10 message types, extended documents, side CSVs [R `source.py:1-70`] | 26 test files, 9 + 8 + 8 focused [M 22] | **Strong partial**: section 1.3 |
| REDCap project | `services/rc_bridge/` (1,081 lines) | API read and write of the site's own project; `https://` enforced [R `client.py:165-178`] | yes (a simulator, `services/rc_sim/`) | **Complete for its job** (an EDC-side source, not hospital data) |
| A PI's spreadsheet, QuestionnaireResponse bundle | `services/datacore/` | CSV/XLSX in three encodings [R `docs/data/01-what-the-box-reads.md`] | yes | Complete for trial data |
| Charts one by one (text, Word, PDF, scans) | `services/sitesetup/charts.py` | The large model proposes facts (`chart_facts`) a person confirms [R :7] | yes (stub) | A fallback for a site with no feed, by design |
| OMOP CDM | `services/omop/` | **Written, never read from outside**: the box loads its own OMOP copy and exports the lake from it [R `services/lake/source.py:1-20`] | yes | **Absent as an input**: a hospital's existing OMOP database cannot be read |
| HL7 v2 live feed (MLLP), CDA, DICOM, NHI claims XML, X12 | none | none | none | **Absent** [M 21] |

### 1.2 What "complete" means for a connector

A connector is complete when every line below is true and has a test that could fail. [O; the list is distilled
from the dataflow and standards reviews of 2026-11-09 and 2026-11-12, and from the SS-MIX2 reader, which already
does most of it]

1. **Transport**: it reaches the data the way a hospital offers it (file drop, SQL replica with the vendor's
   driver, MLLP socket, FHIR REST with the site's authentication), inside the box's egress rules.
2. **Encoding**: it reads every character set the region's vendors write, strictly, and quarantines what it
   cannot read, never replacing bytes.
3. **Coverage**: it reads every record type the criteria need (demographics, encounters, diagnoses with system
   and version, medications ordered and given, labs with units and ranges, procedures, vitals, allergies, notes
   and reports, death, consent).
4. **Versioning**: it applies updates, corrections and deletions (tombstones) and knows which record is current.
5. **Delta**: it reads only what changed since the last night, and proves nothing was skipped (counts, a
   completeness gate).
6. **Codes**: it carries the source code with its system and edition, maps to the standard one where a table
   says so, and counts what it could not map, by volume.
7. **Identity**: it pseudonymises at the door and handles merges of chart numbers.
8. **Provenance**: every row says which file, table and line it came from.
9. **Report**: one report per night a steward can read (counts, quarantine, unmapped, held).
10. **Proof on real data**: one de-identified or vendor-sample feed read end to end, with the numbers on file.

Measured against this list, CSV meets 1 to 9; SS-MIX2 meets 1, 2, 4 to 9 and part of 3; FHIR files meet 2, 4, 7,
8 and part of 3 and 6; SQL meets 4 to 9 for PostgreSQL only. **None meets 10** (STD-014; plan 8 criterion 6 is
the first CGRD day). [R]

### 1.3 SS-MIX2: what reading it entails, and where TrialBox stands

**What the standard is** [S https://www.ss-mix.org/]: SS-MIX2 (Standardized Structured Medical Information
eXchange 2) is the Japanese storage convention behind MID-NET and most university-hospital data warehouses. A
hospital's HIS writes, beside its own database, one HL7 v2.5 message per file into a fixed tree. There are two
parts: **standardised storage** (標準化ストレージ: messages of fixed types) and **extended storage**
(拡張ストレージ: documents, reports and anything the standard does not fix). [S, and R `source.py:1-70`, which
cites 標準化ストレージ仕様書 v1.2]

**What a first reader must cover**, and what TrialBox's reader does:

| Must cover | TrialBox | Evidence |
| --- | --- | --- |
| The tree `<root>/<id[0:3]>/<id[3:6]>/<patient id>/<YYYYMMDD or ->/<data type>/<file>` | Yes | [R `source.py:4`]; the synthetic storage is 10,361 files in that tree [M 3] |
| File names `<pid>_<date>_<type>_<order no>_<timestamp>_<dept>_<flag>`; newest timestamp wins per (patient, type, order); flag 0 = deleted | Yes, and a site option when order numbers repeat per day (D-594) | [R `source.py:5-9`] |
| HL7 v2.5 parsing: segments by CR, escapes, repetitions, components | Yes, a small own parser | [R `hl7.py:1-60`] |
| Character set: MSH-18 `~ISO IR87` (ISO-2022-JP) as the norm; vendor variants (half-width kana, NEC and IBM extensions, JIS X 0212/0213, Shift_JIS, UTF-8) | Yes, strictly, quarantine otherwise | [R `hl7.py:1-14`]; synthetic storage: `~ISO IR87` on 400 of 400 sampled files [M 3] |
| ADT-00 patient | Yes | [R `source.py:15-17`] |
| ADT-12 outpatient, ADT-22 admission, ADT-52 discharge and class change | Yes | [R `source.py:18-24`] |
| ADT-21/31/32/41/42/51 (planned admission, leave, transfer, planned discharge), ADT-61 allergy, ADT-01 deletion | **No** | [R `source.py:58-64`, the `TYPES` table]; STD-014 |
| PPR-01 problems with 標準病名 and ICD-10 (WHO 2013, not ICD-10-CM), suspected flag | Yes | [R `source.py:25-29`] |
| OMP-01/02 orders, OMP-11/12 administrations; YJ and HOT codes to ATC | Yes; ATC resolved on 62.5 % of synthetic lines, ingredient on 100 % | [R `source.py:30-35`; M 4] |
| OML-11 lab results with JLAC10, value types, corrections and deletions | Yes | [R `source.py:36-43`] |
| OML-01 lab orders, OMG-01/02/03/11/12/13 (radiology, endoscopy, physiology orders and results), OMD (diet) | **No** | [R `source.py:58-64`] |
| Extended storage documents, with `_contents.xml` where the vendor writes one | Documents by folder kind; **no `_contents.xml`** | [R `docs/data/01-what-the-box-reads.md`] |
| Licensed code lists (MEDIS 標準病名, JLAC10, YJ/HOT) loaded by the site | Yes, with version and checksum | [R `docs/data/01-what-the-box-reads.md`] |
| Delta: only new files since the last night | Re-walks the tree; no change index | [R `source.py`; not timed on a large storage: not verified] |
| One real vendor's storage | **Never** | STD-014 |

**Measured on the synthetic storage** [M 4]: 400 patients, 10,323 message files and 38 extended files read into
12,496 FHIR resources in 14 s (about 740 messages a second on this shared 4-core machine), the lake step 3.8 s.
The HL7 JVM validator was not used ("structural-fallback" on 139 sampled resources).

**What remains for "SS-MIX2 complete"** [O]: (a) ADT-61 allergies into AllergyIntolerance (S); (b) the transfer
and leave ADT types as encounter changes (S); (c) OML-01 and OMG orders and results as ServiceRequest, Procedure
and Observation (M); (d) `_contents.xml` when present (S); (e) a delta by file modification time with a
completeness count per type (S); (f) one vendor sample storage read end to end, with the quarantine and unmapped
counts filed (M, needs a hospital or a vendor's sample; SS-MIX普及推進コンソーシアム publishes sample data:
not verified).

### 1.4 The gap table: connector by country

Size of work: S a day or less, M a few days, L a week or more. Country need: **must** (a typical first hospital
cannot start without it), **often**, **rare**. [O for need and size; R for "exists"]

| Connector | TW | JP | US | Exists | Evidence | Size |
| --- | --- | --- | --- | --- | --- | --- |
| CSV export | must | often | often | yes | 1.1 | – |
| SQL replica, Oracle / SQL Server driver | must (CGRD-type views on Oracle) | often | often | **partial** | [M 18] | S |
| SS-MIX2 standardised + extended | – | must | – | partial | 1.3 | M for (a) to (e) |
| HL7 v2.x live feed: ADT, ORU (results), ORM/OML (orders), RDE/RAS (pharmacy); MLLP with ACK | often | often (SS-MIX2 is v2.5 on disk) | **must** | **absent** | [M 21] | L (plan 8 lists it as "candidate to leave out") |
| FHIR R4 REST client with SMART Backend Services; Bulk Data `$export` kick-off and polling | rare | rare (JP-CLINS servers growing) | **must** (ONC certification requires Bulk Data export from certified EHRs; 8.3) | **partial** (files only) | STD-013 | M |
| US Core profiles on input (mapping from US Core 6/7/8 resources) | – | – | must | **absent** | [M 21] | M |
| TW Core profiles on output and validation | must | – | – | yes | 13 profiles, TW Core 1.0.0 [R `services/adapter/validate/twcore_rules.json`; M 12] | – |
| JP Core profiles on output and validation | – | must | – | yes | 16 profiles, JP Core 1.1.0 [R `jp_core_rules.json`; M 12] | – |
| NHI claims (門診/住院 申報 XML, the 點數清單) | often (the most complete history a TW hospital holds) | – | – | **absent** | [M 21] | M |
| NHI drug code to ATC in the nightly path | must | – | – | **absent** (STD-005, unchanged: only the set-up page reads the map) | [R `libs/tb_common/refdata_tw.py:140`; no adapter caller] | S |
| ICD-9-CM years (TW before 2016) | must | – | rare | yes (NEW-STD-1 fixed) | [R `services/adapter/mapping/tw_core/demo_his.yaml:14,164-170`] | – |
| NHI MediCloud (健保醫療資訊雲端查詢) | rare: a per-patient look-up behind the NHI card reader, not a bulk feed | – | – | absent, and **should stay absent** [O] | – | – |
| TW EMR exchange (EEC, 電子病歷交換中心) | rare (summaries between hospitals) | – | – | absent | – | M, later |
| OMOP CDM as an **input** | rare | rare | often (academic centres hold OMOP) | **absent** | 1.1 | M |
| CDA R2 documents (C-CDA in the US; Japan's 診療情報提供書 CDA) | rare | rare | often | absent | [M 21] | M |
| Lab and pathology feeds (HL7 ORU, LIS exports) | via CSV | via SS-MIX2 OML-11 | via HL7 ORU | partial | – | inside the HL7 v2 item |
| DICOM metadata | rare for eligibility | rare | rare | absent, not needed for 1.0 [O] | [M 21] | – |
| REDCap (as EDC) | yes | yes | yes | yes | 1.1 | – |

**Japanese units and enzyme activity (STD-004)** are half fixed: `×10^3/μL` and `mL/分/1.73m2` now read
[M 17], but `IU/L` against a criterion in `U/L` still gives no value (`labunit.convert(45, "IU/L", "U/L", LOINC,
"1742-6")` returns `None`) [M 17]. Every AST, ALT, ALP, LDH and CK criterion at a site that prints `IU/L` stays
"unknown". (S)

### 1.5 Structured data and notes: one patient walked through the code

The question the owner asked: what is decided by rules, by terminology, by a small model, by the large model?
One synthetic patient of the seeded box, from the hospital's CSV to a screening answer:

| # | Step | Decided by | Where | Measured on the synthetic hospital or P2b |
| --- | --- | --- | --- | --- |
| 1 | The CSV file is read; the encoding is chosen | **rules** | `services/adapter/sources/csv/source.py:65-77` [R] | 149,030 lines in 13 files [M 1] |
| 2 | The chart number becomes a pseudonym, `HMAC(site key, chart number)` | **rules** | `libs/tb_common/crypto.py:38` [R] | 5,001 patients [M 2] |
| 3 | Each row becomes a FHIR resource by a YAML mapping (codes, units, dates, status) | **rules** + **terminology** (look-up tables) | `services/adapter/mapping/engine.py:546` (`load`), `tw_core/demo_his.yaml` [R] | 154,992 resources [M 2] |
| 4 | Note text is masked (names, numbers, addresses) before anything else reads it | **rules** (regular expressions) | `engine.py:1177-1179` → `libs/tb_common/phi_guard.py:847` [R] | 14 of 18 probes masked [M 15] |
| 5 | Resources are written as NDJSON, sorted, then flattened to 13 lake tables; notes are chunked | **rules** | `services/adapter/ndjson.py:75`, `services/lake/flatten.py:718`, `services/lake/textproc.py:32` [R] | 11,619 chunks [M 2] |
| 6 | The protocol is read and each criterion is turned into logic (`ir_extract`) | **large model** | `services/criteria_compiler/service.py:850` [R] | 200 calls for 104 sigir protocols [M 6] |
| 7 | Negation and polarity fixed after the model | **rules** | `criteria_compiler/ir_extract/polarity.py:47-53` [R] | – |
| 8 | Concept names to codes: exact name, synonyms, dictionary, ICD-10-CM index | **terminology** | `criteria_compiler/terminology/mapper.py:1-20` [R] | tables of 33 ATC, 27 LOINC, 24 NHI drug, 186 synonym rows [M 5] |
| 9 | What step 8 could not resolve: the model picks among the top 20 candidates (`concept_map`) | **large model** | `mapper.py:19`; `service.py:454-470` [R] | **676 calls** in sigir [M 6] |
| 10 | Each criterion is classed structured / mixed / note / human | **large model**, then rules demote what cannot compile | `service.py:576` (`demote_uncompilable`) [R] | 282 structured, 293 mixed, 93 note, **497 human (43 %)** of 1,165 [M 8] |
| 11 | S0, S1: scope and coded criteria in SQL over the lake | **rules** (compiled SQL) | `services/matching/cascade/engine.py:457,535` [R] | – |
| 12 | S2: approved words in the note sentences of the window | **rules** (lexicon) | `engine.py:799`; `lexicon_terms` at `:345` [R] | hits on **4 of 292** sigir pairs, **0 of 500** tcga [M 7] |
| 13 | S2b: sentences ranked by meaning; below a threshold, absence semantics | **small model** (the embedder) | `engine.py:910`; `matching/cascade/s2b_semantic.py:139` [R] | **788 of 788** above the threshold, none filtered [M 7] |
| 14 | S3: the judge reads the excerpts and answers met / not met / unknown with a quote; the quote is verified | **large model**, then **rules** (quote check) | `engine.py:1246` [R] | 291 sigir pairs, 500 tcga [M 7] |
| 15 | S4: a second model on would-be candidates; disagreement means "uncertain" | **large model** (second) | `engine.py:1331` [R] | 0 sigir, 48 tcga [M 7] |

**What should move down the ladder** (from large model toward small model, terminology and rules) [O]:

- **Step 9 to step 8.** Load the public code systems (full ATC from the WHO index once licensed, or ATC codes
  without names; LOINC with its licence; NHI drug and order codes from data.gov.tw; MEDIS where licensed) so that
  most concept names resolve by table. The model then only breaks ties. Expected: `concept_map` calls fall by most
  of 676, and some of the 497 "human" criteria become structured. Measure first: the share of concept names
  resolved by table before and after, on the sigir and P1b protocol sets (`--check` style, no GPU).
- **Step 10's "human" bucket.** Of 497, the share that a better table would make structured is **not verified**;
  P1b's review gave "58 of 1,273 concepts mapped" (full review M-2) [R].
- **Steps 12 and 13 must start to filter, or be dropped from the screening path.** A filter that passes 100 %
  adds latency and a component to validate. Either refit S2b's threshold on the chosen embedder (D-429 waits for
  it) and measure recall on the gold sets, or run S3 directly with retrieval only choosing excerpts (which is what
  happens today in effect). [O]
- **New rules before step 14** for the shapes P2b showed: sex-only atoms on pregnancy lines excluded women at S1
  with no model call (`docs/plan/measurements/p2b-review-2026-11-17.md`, sigir-20156) [R]. A rule "a pregnancy
  or lactation line never compiles to sex alone" belongs in step 7, not in a prompt.
- **What should stay with the large model:** reading the protocol (step 6) and reading notes against a question
  (step 14). Nothing measured here argues for removing either. [O]

---

## 2. Stores

### 2.1 What is there, measured on the seeded synthetic hospital

| Store | Format | Partitioning | Size at 5,001 patients | Rebuilt | Evidence |
| --- | --- | --- | --- | --- | --- |
| Hospital export (input) | CSV, 13 files | none | 21.6 MB | – | [M 1] |
| FHIR snapshot | NDJSON, 15 resource types + reports | by night (`ndjson/<date>/`) | **152.2 MB** per night (7.0 × the CSV) | every night, whole | [M 1] |
| Lake tables | Parquet with `.sha256` sidecars | `parquet/snapshot=<date>/` | 16.3 MB per night | every night, whole | [M 1] |
| Lake query file | DuckDB with FTS index and chunks | one file per night | 47.2 MB per night | every night, whole | [M 1] |
| Lake vectors | DuckDB, `sha256(chunk) → vector` | one file for all nights | 26.2 MB (hash stand-in vectors) | incremental | [M 1; R `services/lake/store.py:9,20-24`] |
| Note vectors (second store) | PostgreSQL `vec` schema, pgvector `halfvec`, one HNSW index per embedder | none | not indexed on this box | **never by the product**: only `tools/vec_parity.py:179` calls `index_snapshot` | [R `docs/data/11-the-vector-store.md`; grep] |
| FHIR server | HAPI JPA on PostgreSQL | – | off in the demo (`"fhir": "skipped"`) | nightly delta | [M 2]; full review I-M6 |
| OMOP CDM 5.4 | PostgreSQL `omop` schema | `omop/partitions.py` | off in the demo (`"omop": "skipped"`) | nightly | [M 2]; STD-006 |
| Trial database | PostgreSQL 16, about 27 schemas, one role per service | – | not measured | migrations | [R `libs/tb_common/db.py:1-45`] |
| Rulesets | a git repository (dulwich) of YAML, SQL, CQL, ELM | by ruleset and tag | – | per approval | [R `criteria_compiler/repo.py`] |
| Objects (jobs' inputs and outputs) | files under `obj/` | by job | – | – | [R `libs/tb_common/objstore.py`] |
| Audit | hash-chained JSONL plus `audit.journal` in PostgreSQL | by day | – | append | full review I |

The ingest of one night of 5,001 patients took **98.8 s** end to end on the seeded box, of which the lake build
was **33.5 s** [M 2]. The HL7 validator was skipped there [M 2].

**Migrations** are inline, checksummed scripts per store, 26 call sites of `migrate` [M 13 grep; R
`libs/tb_common/db.py:25-45`]. They are tested on throwaway clusters (`tools/pglocal.py`) [R]. There is no
down-migration by design (the update path decides) [R `db.py:44-45`]. [O] This is sound.

### 2.2 One fact, many copies

The same diagnosis of one patient exists, on a box with every option on, in: the hospital's CSV (landing), the
NDJSON snapshot, the Parquet table, the DuckDB file, the HAPI server, the OMOP `condition_occurrence`, and, for a
note, the lake chunk table, `embed_cache.duckdb` and `vec.note_chunk` [R `services/lake/store.py:1-25`,
`docs/data/11-the-vector-store.md`]. The demo runs four of these [M 2]. **What the extra copies cost:**

- **NDJSON is 9.4 times the Parquet** of the same night [M 1]. Of what the adapter writes, the lake never reads
  `Coverage` (5,001 resources), `Organization`, seven `Claim` fields and six `ClaimResponse` fields, among others:
  the ingest report lists them as `fhir_unread` [M 2]. [O] The NDJSON exists for the FHIR server and for the
  validator; once the FHIR server leaves the box (I-M6, plan 8 "the FHIR store off the box"), the adapter can
  write Arrow directly and keep NDJSON only as the validator's 1 % sample.
- **Every copy is a store that erasure must reach.** J-2 counts 28 owed stores; four of them are copies listed
  above [R `docs/validation/erasure-registry.md`]. Fewer copies is the cheapest erasure fix. [O]
- **Two lake sources** (`legacy` from NDJSON, `omop` via the OMOP store) give "the same rows" by a parity test
  [R `services/lake/source.py:1-12`]. Every change to a lake table is made twice. STD-006's "decide once" is
  still open. [O] Decide `legacy` for 1.0 and freeze OMOP as an export.

### 2.3 The vector store: is it needed?

- **What it is:** two stores. The lake's `embed_cache.duckdb` (live: screening reads it through S2b) and
  PostgreSQL `vec` with pgvector (built, behind the off flag `vec.s2b`, never filled by the night) [R
  `docs/data/11-the-vector-store.md`; `libs/tb_common/flags.py:139`].
- **What it does in screening:** S2b ranked 788 of 788 pairs above the threshold in P2b, so it chose excerpts but
  excluded nobody [M 7]. In feasibility its threshold is "fitted to on-the-fly vectors and refitted only after
  the embedder is chosen" [R `docs/data/11-the-vector-store.md`].
- **A silent fallback:** when the embed service does not answer, SCREEN ranks note sentences with the **hash
  stand-in** and only logs a warning [R `services/orchestrator/scenarios/screen_cascade.py:278-300`]. On a
  production box this changes which sentences the judge sees, without a mark on the result. [O] Refuse it in
  VALIDATION and PRODUCTION; record the embedder in the job's provenance (it is in `s2b_source_*.json` only when
  the `vec` flag is on).
- **Verdict** [O]: a vector index is needed for one thing, choosing which note sentences the judge reads; at
  5,001 patients a brute-force cosine in numpy (already used, `s2b_semantic.py:93-104` [R]) over the window's
  sentences is fast enough (S2b's time is part of the cascade's 14.7 s baseline, `tools/bench_baseline.json`
  [R]). **Keep one store** (the lake's, keyed by chunk hash), retire `vec` and its HNSW index until a measured
  need at 50,000 patients appears. Measure first: S2b's share of SCREEN time at 50,000 patients with the chosen
  embedder (section 3.5, run G-3).

### 2.4 Flexibility: what must change to add a field, a resource type, a hospital

| Change | Files touched today [R, counted by reading the code paths] | Size | [O] What would make it smaller |
| --- | --- | --- | --- |
| **One field** (e.g. a lab's specimen) | the site mapping YAML; `services/lake/flatten.py` (the table schema, `SCHEMAS`); `services/omop/load.py` and `omop/export.py` (both lake sources must agree); the lake schema version and its fingerprint (`lake/store.py:80-101`); the goldens | S, but in five places | one table schema read by flatten, OMOP export and the SQL compiler |
| **One resource type** (e.g. AllergyIntolerance) | the reader (SS-MIX2 or CSV canonical table, `templates/CANONICAL.md`); the mapping; `flatten.py` (a new table); OMOP load and export; the compiler's domain list and SQL generator; the CQL generator; the equivalence gate; the cascade's coded check; the JP and TW Core rule files; the erasure registry | M to L | the same, plus a "domain plug-in" checklist test that fails until every place is done |
| **One hospital** | the site folder (`deploy/site/`), the mapping YAML from a template (`mapping/templates/*.yaml`), the lab and drug look-ups, the site's chart-number pattern, the licensed lists; no code | M of steward time | already designed this way (`docs/data/02-mapping-a-site.md`) [R] |

The adapter's own core is the hardest place to change: `_run_ingest` is one function of **660 lines and 181
branches** [M 13], the fifth-largest function in the product and the largest outside the console. The full review
counted the console's functions (L-3) and not this one. [O] It needs the same size ratchet.

### 2.5 Findings for the stores

- **B1-S1 (High)** [O, from M 1, M 2]: the NDJSON copy is 7 × the input and 9.4 × the lake, rebuilt whole every
  night, and partly unread. *Fix:* after the FHIR store leaves the box, write Arrow from the mapper; NDJSON only for
  the validator's sample. **M.** Measure first: lake build time and peak memory at 50,000 patients before and
  after (bench `ingest`).
- **B1-S2 (Medium)**: two vector stores, one unused by the product. *Fix:* retire `vec` for 1.0. **S.**
- **B1-S3 (Medium)**: the hash stand-in embedder is used silently when the embed service is down. *Fix:* refuse in
  VALIDATION and PRODUCTION; name the embedder in every SCREEN's provenance. **S.**
- **B1-S4 (Medium)**: two lake sources. *Fix:* rule `legacy` for 1.0 (STD-006). **S** (a decision) then deletion.
- **B1-S5 (Medium)**: `_run_ingest` 660 lines. *Fix:* split into the night's named steps (read, map, write,
  validate, gate, publish) as functions with their own tests. **M.**

---

## 3. The model in use

### 3.1 Serving as built

| Part | As built | Evidence |
| --- | --- | --- |
| Engine | vLLM, OpenAI-compatible, pinned `v0.32.0` by digest; latest on Docker Hub `v0.34.0` | [R `deploy/docker-compose.rtxpro6000.yml:32`; M 11] |
| Two models resident on the RTX PRO 6000 layout; judge 40 % and verifier 20 % of GPU memory; 16 sequences each; context 32,768 | as stated | [R `docker-compose.rtxpro6000.yml:59-84`] |
| CUDA graphs | **off** on both servers (`--enforce-eager`) | [R `:70`, `:83`] |
| Prefix caching | not set on the command line; whether the pinned version enables it by default is **not verified** | [R] |
| One-card layouts (RTX 5090) | the two models swap; `orchestrator/twophase.py` runs judge, then verifier, then judge from memory | [R `services/orchestrator/twophase.py:1-28`] |
| Structured output | every non-free-form role must send a `json_schema` response format; the gateway checks the answer against it | [R `libs/tb_llm/client.py:243-245`; `services/gateway/core.py:249`] |
| Prompts pinned by rule set; prompt registry | yes (full review M checklist 7) | [R] |
| One path to the model; PHI tripwire | yes; **the P2b run set `TB_GATEWAY_PHI_TRIPWIRE=off`** (public data) | [R p2b `summary.json`, `provenance.tripwire`] |
| Outage handling | a job waits up to 30 min (`TB_LLM_OUTAGE_WAIT_S`) for a model fault | [R `libs/tb_llm/outage.py:37`] |
| Traces | prompt, output, call id, time stamp per call; **no duration, no token counts per call** | [M 6: keys of 1,245 traces are `attributes, call_id, output, prompt, sc, span, ts`] |

### 3.2 Where time goes on the GPU: the stored P2b traces

P2b ran on one RTX PRO 6000 box, three public sets, 2026-11-17 [R `docs/plan/measurements/p2b-review-2026-11-17.md`].
From the stored traces [M 6, M 7]:

| Set | Calls | Wall span of calls | By prompt | Tokens (screen reports) |
| --- | --- | --- | --- | --- |
| sigir (104 protocols, 3 streams) | 1,245 | 6,710 s (1 h 52 min) | `ir_extract` 200 (mean 4,446 prompt chars, **3,415 output chars**, median gap 15.7 s, 90th 99.5 s); `concept_map` 676 (1,704 in, 48 out); `judge` 369 (325 judge, 44 verifier) | screening: 199,839 in, 30,217 out |
| tcga (1 protocol, 500 reports) | 979 | 363 s | `ir_extract` 1; `judge` 978 (501 judge, 477 verifier), **3.06 calls/s**, median gap 0.15 s; 5,470 prompt chars | screening: 1,509,865 in, 117,284 out |

What this says [O]:

- **Note screening is fast enough.** 978 judge and verifier calls in 319 s with prompts of about 1,500 tokens is
  about 4,700 prompt tokens and 370 output tokens a second for the pair. At that rate the full review's
  50,000-patient figure (6,704 calls) is about 37 min of model time, not the 8,584 s measured on 2026-11-11 under
  older settings. Not verified at 50,000.
- **Protocol reading is the bottleneck.** `ir_extract` writes long JSON (about 1,000 tokens per call) one protocol
  part at a time; 7 calls failed upstream and were split and asked again [M 9]. 104 protocols took 1 h 52 min; one
  study's compile is minutes, not seconds. This is decode-bound work, the case CUDA graphs speed up most.
- **`concept_map` is the most frequent call** (676 of 1,245 in sigir) and the least necessary (section 1.5).

### 3.3 Where time goes on the CPU: the stub, profiled here

One stub night of the regression gate's shape (5,000 synthetic patients, study GZQO, the in-process gateway and
stub model), timed per phase by the gate's own timers [M 19, M 20]:

| Phase | Today, unprofiled (load average 15 to 16) | The gate's baseline, 2026-11-10 (`tools/bench_baseline.json`) [R] |
| --- | --- | --- |
| Synthetic data | 3.0 s | 2.5 s |
| Ingest and lake build | 95.8 s | 58.0 s |
| Cascade S0 to S5 | 38.7 s | 14.7 s |
| Pack, certificate, outputs | 34.2 s | 18.4 s |
| Total | 171.8 s | 93.6 s |
| Peak memory | 1,758 MB | 1,871 MB |
| CPU calibration loop | 0.567 s | 0.324 s |

The machine was 1.75 times slower by the gate's own calibration loop; scaled, today's total is about 98 s, so no
regression is visible [M 20; O]. In the profiled run the cascade's 153 stub judge calls cost 15.9 s through the
in-process HTTP gateway [M 19]. **The stub says nothing about model time**: on the GPU, 978 real calls took 319 s
(3.2). What the stub night does measure is the CPU work around the model, which is section 6.

### 3.4 A box with no GPU

[R full review I, "When a part is down"; `libs/tb_llm/outage.py:1-20`] Coded criteria (S0, S1) run; note criteria
wait for the model up to the job's allowance and then stop with a named outage; the compiler cannot read a new
protocol. [O] That is the right behaviour. One defect found here: a gateway that refuses because **it is
misconfigured** (no service token: HTTP 503 "no service token configured") is treated as a model outage and
waited on for 30 minutes before the job fails [M 16]. The client maps every 5xx to `GatewayDown`
[R `libs/tb_llm/client.py:274`]. A production box with a missing token file would stall each job for half an
hour. *Fix:* a distinct refusal code for configuration errors that is never retried (B1-M3, S).

### 3.5 The run for the GPU VM (for the integrator to run; not run here)

Nothing below was run. Each run uses the P2b driver on a box already installed from the signed bundle, the
public sets only, and an override compose file for the flag under test (never a commit). The driver prints its own
cost estimate for free first: `deploy/gcp/box-run.sh --estimate --mode validation --steps acc --only <sets>`
[R `deploy/gcp/box-run.sh:17-20`]. For scale: P2b, install included, ran 07:38 to 10:02 UTC [R p2b review].

| Run | What | Commands (from `trialbox/`) | Expected duration | Decides |
| --- | --- | --- | --- | --- |
| G-1 | CUDA graphs off vs on, compile throughput | `deploy/gcp/box-run.sh --mode validation --steps acc --only sigir` as shipped; then the same with an override that drops `--enforce-eager` from both servers of `deploy/docker-compose.rtxpro6000.yml`; compare `ir_extract` calls per minute and the answers (`replay`) | 2 × about 2 h | Whether to drop `--enforce-eager` (B1-M1) |
| G-2 | Prefix caching stated off vs on, judge throughput | the same driver with `--only tcga`, once with `--no-enable-prefix-caching` and once with `--enable-prefix-caching` in the override | 2 × about 10 min | Whether to set the flag explicitly |
| G-3 | Scale: 50,000 synthetic patients, one study, the real pair | `python tools/bench.py --tasks screen,ingest --ingest-patients 50000 --llm-url <the box's gateway>` on the box (`tools/bench.py:1-30`), with `nvidia-smi dmon -s um -d 5 > gpu.tsv` beside it | about 1 h | The night's model time at 50,000 (I-4's capacity statement) |
| G-4 | Per-call latency and tokens | a code change before G-1 to G-3: `duration_ms`, `tokens_in`, `tokens_out` on the gateway's trace record (B1-M4) | – | Every later capacity figure |

Total about 6 h of VM time; the cost is what `--estimate` prints for these sets (not run here). Each run writes
its stored set the way P2b did.

### 3.6 Findings for the model in use

- **B1-M1 (High)**: `--enforce-eager` on both servers. *Fix:* run G-1; drop the flag if the gain holds and the
  qualification answers are unchanged. **S** after G-1.
- **B1-M2 (High)** ★: `concept_map` is 54 % of all sigir calls because the terminology tables are demo-sized.
  *Fix:* plan 8's TERM-1/2 (code systems loaded at install), then count the calls again. **M.**
- **B1-M3 (Medium)**: a configuration 503 is waited on as an outage for 30 min [M 16]. **S.**
- **B1-M4 (Medium)**: traces have no duration and no token counts per call [M 6]. G-4. **S.**
- **B1-M5 (Medium)**: the engine is two minor releases old [M 11]; the waiver for its image is part of J-1. *Fix:*
  move with the re-qualification card already planned (J-1, F1). **S** plus a qualification run.

---

## 4. Coupling: where it is loosely connected functions and not one system

### 4.1 What was found, beyond I-2 and I-3

| Kind | What | Evidence | Size |
| --- | --- | --- | --- |
| Two engines for one job | Two screening pipelines: the cascade (default) and the v1 evaluator (`TB_SCREEN_PIPELINE=v1`); NAV always uses v1. Two retrieval paths for notes: the cascade's sentence windows and v1's `/chunks/search` k=5 | [R `services/orchestrator/scenarios/screen_cascade.py:15,67-70`; `scenarios/nav.py:169`; `scenarios/evaluate.py:1-20`] | M to retire v1 after NAV moves |
| Three chunkers | `lake/textproc.chunk` (500/100 characters), `vec/chunker` (sentence ends, 500/100), `s2b_semantic.windows` | [R `services/lake/textproc.py:32`; `services/vec/chunker.py`; `s2b_semantic.py:121`] | S |
| Three identifier detectors | `phi_guard.scan` (the compiler), `phi_guard.mask_note` (notes), `guard.Guard` (the gateway) with different coverage | [R `criteria_compiler/service.py:26`; `phi_guard.py:847`; `services/guard/guard.py:87-92`; M 15] | S (section 7) |
| Two lake sources | `legacy` and `omop` | 2.2 | S decision |
| Two vector stores | `embed_cache.duckdb` and `vec` | 2.3 | S |
| Two backup systems | the full `.tbbak` (X25519 to the hospital's key) and restic (password under the KEK) | [R `tools/trialbox/backup.py:21-25`; `tools/trialbox/restic_repo.py:1-20`] | keep both; one page that says which restores what [O] |
| Three versions of the actor claim | `X-TB-Actor` (v1), v2 assertion, v3 assertion; plus a "legacy" shared token accepted from any caller with a warning | [R `libs/tb_common/service_auth.py:1-40`; `actor_v3.py:1-30`] | S: refuse v1 and the legacy token in PRODUCTION |
| Shared ownership of schemas | the console's role owns 21 schemas, the orchestrator's 23; **17 are owned by both**, with full rights (a non-owned schema's group owns its tables) | [R `deploy/docker/db-init/30-service-roles.sh` (the `access` map and the `CREATE SCHEMA ... AUTHORIZATION` loop)] | M: read-only grants for the console where it only reads |
| Hand-off by file | the adapter and the lake share a folder under `flock` (full review I); jobs' inputs and outputs are files under `obj/`; rulesets in a git repository; the night's state in `night_runs.json`, `publish.json`, `gate.json` | [R `services/lake/store.py:1-25`; M 2] | – (acceptable on one box) [O] |
| Hand-off by mail | the product is "email-driven" by its own description; jobs arrive by mail through the mail gateway | [R `pyproject.toml` description; `services/mail_gateway/`] | – |
| In process vs HTTP | the bench and the e2e run every service in one process; a refusal that only happens over HTTP (the service token) hung the in-process bench for 30 min when `TB_ENV` was unset [M 16] | I-2 | – (I-2's fix) |

### 4.2 The data flow as it is

```
 HIS ──CSV / SQL(pg only) / SS-MIX2 / FHIR files──► ADAPTER (_run_ingest, 660 lines)
        │ pseudonym, mapping YAML, mask_note
        ▼
   NDJSON snapshot (152 MB/night @5k) ──► [HAPI FHIR, optional] ──► CQL at compile time only
        │                              └─► [OMOP schema, optional] ──► omop.export ─┐
        ▼                                                                         │ (lake source "omop")
   lake.flatten ──► Parquet (16 MB) ──► DuckDB (47 MB, FTS, chunks) ◄─────────────┘
        │                                  │
        │                                  ├─► embed_cache.duckdb  (S2b, v1 RAG)
        │                                  └─► [vec / pgvector, flag off, never filled]
        ▼
 COMPILER ── ir_extract (LLM) ─ terminology (33 ATC / 27 LOINC rows) ─ concept_map (LLM) ─► ruleset git repo
        ▼
 ORCHESTRATOR ── cascade S0..S5 (SQL, lexicon, embedder, judge, verifier) ── or v1 evaluator (NAV)
        │  23 schemas                          │
        ▼                                      ▼
 CONSOLE (21 schemas, 17 shared) ◄── reads the orchestrator's stores directly; MAIL GATEWAY ◄─► jobs by mail
```

### 4.3 The data flow as it should be [O]

```
 HIS ──CSV / SQL (Oracle, SQL Server, pg) / SS-MIX2 / FHIR REST+files / HL7 v2 (later)──► ADAPTER
        │ read → map → (Arrow) → gate → publish, each a named step
        ▼
   Parquet + DuckDB (one lake, one source)  ──► 1 % NDJSON sample ──► validator
        │
        └─► one note index: chunk hash → vector (one chunker, one embedder, named in provenance)
        ▼
 COMPILER ── ir_extract (LLM) ─ terminology loaded at install (full code systems) ─ concept_map only for ties
        ▼
 ORCHESTRATOR ── one screening engine (the cascade; NAV on it) ── writes results and events
        ▼
 CONSOLE ── reads through the orchestrator's API or read-only views; owns only its own schemas
 OMOP: an export for research, not a second lake source.   FHIR server: off the box.
```

---

## 5. Code quality

### 5.1 The pinned libraries against their current releases

| Item | Pinned | Current (measured today) | Note |
| --- | --- | --- | --- |
| Python packages in the venv | 115 installed; 189 in `uv.lock` | **18 behind** their latest release [M 10] | most are patch releases |
| `duckdb`, `duckdb-extension-fts` | `==1.5.5` | **2.0.0** [M 10] | a major release; the lake's file format and FTS index; needs its own card and a parity run (M) |
| `fastapi` | 0.162.4 | 0.163.1 [M 10] | Starlette now warns that `httpx` in its test client is deprecated (seen in every run here) [M 19] |
| `pypdf` | 7.0.1 | 7.1.0 [M 10] | parses mailed protocols; keep current (advisory history, `pyproject.toml:26`) [R] |
| `psycopg`, `sqlalchemy`, `sqlglot`, `numpy`, `python-multipart` | patch behind | [M 10] | routine |
| Python | 3.12 (`requires-python <3.13`) | 3.14.9 on Docker Hub [M 11] | 3.12 is supported until 2028 (Python's release policy) [S https://devguide.python.org/versions/]; no hurry [O] |
| PostgreSQL | 16 by digest | 18.7 on Docker Hub [M 11] | 16 is supported until 2028 [S https://www.postgresql.org/support/versioning/]; plan 8's "major-version procedure" covers it |
| vLLM | v0.32.0 | v0.34.0 [M 11] | B1-M5 |
| HAPI FHIR | v8.12.0-2 | v8.12.0-2 [M 11] | current |
| Temurin JRE | 21.0.13 | 21 is an LTS; 25 exists [M 11] | fine |
| JVM jars | 105 sha256-pinned jars (cql-to-elm 5.4.0, hapi-fhir-base 8.10.0, jackson-databind 2.21.8, commons-collections 3.2.2, commons-text 1.10.0) | not compared one by one: **not verified** | [R `tools/jvm-deps.sha256`] |
| Node tools (tests only) | playwright 1.63.0, axe-core 4.14.0 | not compared: **not verified** | [R `tools/package.json`] |
| Known advisories | `pip-audit` is **not installed** in the venv: **not run**. CI runs its own scans (`tools/security_scan.py`) and the 94 waivers of J-1 | [R] |

### 5.2 Typing, tests, size

- **Typing:** mypy `strict = true` over services, libs, tools and tests, with `warn_unused_ignores` [R
  `pyproject.toml:140-148`]. `# type: ignore`: **64** in product code, 807 including tools and tests; `noqa`: 139
  in product code [M 14]. [O] Healthy.
- **Tests:** the full review counted 8,337 test functions (L figures) [R]; not recounted. Per connector [M 22]:
  CSV 81 test files, SS-MIX2 26, SQL 6, FHIR files 6. [O] The SQL connector's six run on SQLite only; nothing
  tests the dialect a hospital uses.
- **Size** [M 13]: 7,105 functions; 32 over 200 lines (31 on 2026-11-17's count); 8 modules over 1,500 lines. Of
  the twelve largest functions, ten are console page registrations (L-3), one is `_run_ingest`
  (`services/adapter/pipeline.py:502`, 660 lines), one is MICROBATCH's `run`
  (`services/orchestrator/scenarios/microbatch.py:325`, 422 lines). The largest module is generated
  (`libs/tb_contracts/generated/models.py`, 3,350 lines).
- **Dead code:** no dead-code tool is installed (vulture is not in the venv): **not run**. Sampled by reading:
  `services/vec/` is reachable only from `tools/vec_parity.py` and the lake's `/vec/s2b` route behind an off flag
  (2.3); the v1 evaluator is live only for NAV and by a setting (4.1); `site_params.yaml` has no reader (full
  review I-M1) [R].
- **Build and packaging:** one Python image (`trialbox-py:1.0.0`) for every Python service, a JVM image, an embed
  image and a database image, all from digest-pinned bases [R `deploy/docker/*.Dockerfile`]. The release bundle
  is signed and checked on install (full review J, A08) [R]. The P2b box recorded `"commit": null` and
  `"bundle_id": null` in its provenance [R p2b `summary.json`]: the launch ran from a tree, not from a release
  bundle (K-1's "nothing is executed" seen in a launch record).

### 5.3 Findings for code quality

- **B1-Q1 (Medium)**: `duckdb` 2.0 is out; the lake pins 1.5.5. *Fix:* a card with a parity run of the goldens on
  2.0 before the release candidate, or a written decision to ship 1.5.5. **M.**
- **B1-Q2 (Medium)**: no test of the SQL connector against Oracle or SQL Server (and no driver, B1-D1). **M**
  (containers for both exist publicly; Oracle's needs licence acceptance: not verified).
- **B1-Q3 (Low)**: Starlette's deprecation of `httpx` in its test client will break the in-process tests at a
  future upgrade. **S.**

---

## 6. Performance, and the Rust question

### 6.1 Where the CPU time goes (cProfile, this machine, shared with five other agents)

Two profiles, stats files kept under `/var/tmp/trialbox-0/b1/prof/` (not in the repository). cProfile slows
Python-level code two to three times more than C code, so the seconds below are profiled seconds; the shares
inside a phase are what matters. Python 3.12's profiler sees every thread [M 19].

**Profile A: the stub night at 5,000 patients** (`stub5000.pstats`; profiled phases: ingest and lake 164.9 s,
cascade 55.7 s, the rest 62.7 s, total 289.7 s) [M 19]:

| Where | Profiled s (cumulative) | Share | Calls | Kind of work |
| --- | --- | --- | --- | --- |
| Mapping rows to FHIR (`adapter/mapping/engine.py:1592` `map_row`; inside it `value` 31.7 s, `set_path` 12.5 s, `prune` 9.5 s) | 68.1 | 41 % of ingest and lake | 196,959 rows | per-row Python over dicts |
| NDJSON: serialise, external sort, write (`adapter/ndjson.py:264`) | 25.6 | 16 % of ingest and lake | 155,728 resources | `json.dumps(sort_keys=True)`, `heapq.merge` |
| A failing `import pandas` (DuckDB probes for pandas, which is not installed; a failed import is not cached) | 33.5 | 12 % of the whole run | **112,252** | the import machinery scanning `sys.path` |
| Recall certificate (`libs/tb_common/recall.py:87` `update`, a 1,001-point grid looped in Python per observation) | 20.4 | 33 % of "the rest" | 6.33 million calls of `_lambda` | float maths in Python loops |
| Hash stand-in embedder | 11.4 | 7 % | 188 batches | stub only: the GPU embedder on a box |
| Date walk over every resource (`adapter/instants.py:46`) | 10.4 | 6 % | 5.67 million | recursive Python |
| Parquet write (`lake/store.py:781`) | 10.5 | 6 % | 13 tables | `pa.Table.from_pylist` from Python dicts |
| `json` encode / decode, everywhere | 9.5 / 8.3 | – | 635,216 / 1,322,330 | C-accelerated, called per resource |
| `_strptime` | 7.9 | – | 404,524 | date parsing in Python |
| FTS tokens of chunks (`lake/textproc.py:12`) | 7.5 | 5 % | 19,689 | regex |
| Note masking (`phi_guard.py:847`) | 5.2 | 3 % | 9,504 notes | regex |
| Stub judge calls through the in-process gateway | 15.9 | 29 % of the cascade | 153 | HTTP in process |

Unprofiled, one failing `import pandas` costs 80 to 98 µs and a small DuckDB statement 975 µs as shipped against
732 to 763 µs with a negative entry for `pandas` in `sys.modules` [M 23]. At 112,252 probes that is about 10 s of
a 94 s night: **a tenth of the stub night is spent looking for a library that is not there.** [O]

**Profile B: the compile, offline** (`compile_check.pstats`: `tools.build_rulesets --check` recompiles the ValueSets,
SQL and CQL of the 8 shipped rulesets; 11.98 s profiled) [M 24]:

| Where | Profiled s | Calls |
| --- | --- | --- |
| Loading the terminology tables (`terminology/mapper.py:301`) | 4.4 | 1 |
| Code-prefix expansion (`mapper.py:429` `expand`): every prefix scans all 98,186 ICD-10-CM codes | 4.0 | 169 expansions, **9.45 million `str.startswith`** |
| Parse of the GZQO protocol PDF (`doc_parser.parser.parse`, a separate profile) | 0.8 | 1 |

On the GPU, one protocol's model work is minutes (3.2). The CPU side of the compile is seconds and does not
matter to the user; `expand` is the one quadratic loop.

**At hospital scale.** The full review cites 805 s for ingest to a published snapshot at 50,000 patients [R
`docs/reviews/2026-11-12-deep-review/07-performance-scale-robustness.md:265`] and an estimate of 20 to 70 h for one
full night at 500,000 [R ibid. 267-268]. The model's share at 50,000 is about 37 min on the P2b rate (3.2, an
estimate). So at 50,000 patients the CPU side of ingest is about a quarter of the night's wall time and the model
the rest; at 500,000 the full reload (T-694, T-702, T-703) is the problem, and that is a design fix (a delta
night), not a language fix. [O]

### 6.2 Rust, part by part

The owner asked whether Rust should improve the performance, in whole or in part. The answer, part by part, with
the share of time each part holds [shares from M 19, M 24; verdicts O]:

| Part | Share of its phase | Rust? | The cheaper compiled path, already in the dependencies | Expected gain |
| --- | --- | --- | --- | --- |
| Model calls (judge, verifier, `ir_extract`, `concept_map`) | the whole night's majority on a GPU (3.2) | **No**: the time is on the GPU | serving flags (G-1, G-2); fewer calls (B1-M2) | the largest of all |
| Row mapping (`map_row`) | 41 % of ingest | **Not now** | first, cut the work: NDJSON written for an unread copy (B1-S1); declarative mappings compiled once to closures | 1.5 to 2 × on ingest [O, not measured] |
| NDJSON serialise and sort | 16 % of ingest | No | drop the copy (B1-S1); or DuckDB's `read_json` / Arrow's JSON reader instead of `json.loads` per line | the 16 % |
| Failing `import pandas` | about 10 % of the night | No | one line at service start, or fewer, larger DuckDB statements (B1-F1) | about 10 % |
| Recall certificate loop | a third of "the rest" | No | numpy over the 1,001-point grid (the cascade's cosine already moved to numpy for the same reason, `s2b_semantic.py:93-104` [R]) | 10 to 100 × on that function [O] |
| Code-prefix expansion | a third of the offline compile | No | `bisect` on the sorted code list, or a `starts_with` filter in Arrow | 4 s to milliseconds [O] |
| Date parsing (`_strptime`) | 404,524 calls | No | `datetime.fromisoformat` (C) where the format is ISO | most of 7.9 profiled s |
| Lake queries (S1 SQL, FTS) | DuckDB | **Already native** (C++) | – | – |
| HL7 v2 parsing of SS-MIX2 | 740 messages a second on the synthetic storage [M 4] | Not now | – | a 500-bed hospital writes tens of thousands of messages a day: minutes, not hours [O] |
| PHI masking (regex) | 3 % of ingest | No | – | – |

**The cost of a second language in a validated product** [O]: a Rust part is a second toolchain in the build and
the SBOM, a second set of advisories and waivers (J-1 already has 94), a second test runner, FFI boundaries that
the mutation and coverage ratchets do not see, and a skill few hospital IT reviewers or future maintainers have.
Under GAMP 5 and IEC 62304 practice, each such part is another software item to classify, verify and keep. That
price is worth paying for a part that holds most of the time and cannot be made fast in Python with the native
libraries already locked (DuckDB, Arrow, numpy). **No part measured here is such a part.**

**Verdict:** no Rust for release 1.0. Revisit only if, after B1-S1, B1-F1 to B1-F4 and the delta night, a measured
night at 500,000 patients still has a pure-Python step above a third of its wall time. Then the first candidate is
the row mapper, as a small extension behind the same interface, with the Python mapper kept as the test oracle.

---

## 7. Security and privacy: what the full review did not cover

Read first: the full review's area J (ASVS by chapter, Top 10, J-1 to J-L3). Below is only what it did not say.

### 7.1 The identifier guard: three detectors, measured

Eighteen synthetic probes (no real person; the strings are in `/var/tmp/trialbox-0/b1/phi_probe.py`, not in the
repository): Taiwan ID in ASCII, full-width, lower-case and spaced; Japanese My Number and insurance numbers; a US
SSN; an unlabelled chart number; phones; an e-mail; a Japanese name with さん and in katakana with 様; an English
name with a title; a birth date in ISO and in 和暦; a Japanese address [M 15].

| Detector | Used by | Hits of 18 |
| --- | --- | --- |
| `phi_guard.scan` | the compiler's check before a protocol or variables go to the model (`criteria_compiler/service.py:26`) | **5** |
| `phi_guard.mask_note` | every note before chunking (adapter, lake, vec, embed service, reveal) | 14 |
| `guard.Guard.tripwire` (recognisers + `scan`) | the gateway's tripwire | 13 |

Missed by **all three**: a Taiwan ID in full-width digits and letter (`Ａ１２…`), and a US SSN. Missed by the
gateway and the masker: a katakana name. Missed by `scan` alone: e-mail, full-width phone, 和暦 birth date,
address, My Number. [O] The cause of the full-width miss is one missing line: no Unicode NFKC normalisation
before matching. The compiler's own check (`scan`) is the weakest of the three and guards protocol text, which
in a hospital may be a pasted chart.

- **B1-P1 (High)** ★: *Fix:* one detector (the recognisers), NFKC-normalised input with offsets mapped back,
  used by all three call sites; the 18 probes plus a full-width and a US set as a test. **S.**

### 7.2 Other places the full review did not look

| Place | What was found | Mark | Severity, fix, size |
| --- | --- | --- | --- |
| The P2b launch in VALIDATION | ran with the PHI tripwire **off** by a declared setting | [R p2b `summary.json` `provenance.tripwire`] | Low: public data. *Fix:* `doctor` FAILs the setting in PRODUCTION; the launch record prints it on its first line. S |
| Configuration 503 retried as an outage | 30 min stall per job | [M 16] | Medium, B1-M3 |
| Archive uploads | a ruleset import reads every member of a zip into memory with no size or count limit (`z.read(n)` for all names); path traversal is checked | [R `services/criteria_compiler/import_ruleset.py:30-44`] | Low (administrator upload): cap the total uncompressed size and the member count. S |
| SSRF from connectors | the REDCap URL must be `https://` but any host; `refdata` follows redirects | [R `services/rc_bridge/client.py:165-178`; `libs/tb_common/refdata.py:245`] | Low: default-deny egress bounds both (full review J). *Fix:* the REDCap host on the egress allow-list by name. S |
| Deserialisation | no `pickle`, no unsafe YAML; the prompt registry's loader is a `SafeLoader` subclass | [M 13 grep; R `libs/tb_llm/prompt_registry.py:150`] | none found |
| Actor claims | v1 header, v2 and v3 assertions and a "legacy" shared token accepted from any caller co-exist; the replay guard is in memory (a restart forgets 2 minutes of nonces) | [R `libs/tb_common/service_auth.py:1-40,305-320`] | Low: refuse v1 and legacy in PRODUCTION. S |
| Schema ownership | console and orchestrator both own 17 schemas, DDL included | [R `deploy/docker/db-init/30-service-roles.sh`] | Medium: a console compromise can alter the orchestrator's tables. *Fix:* read-only grants where the console only reads. M |
| `TB_ENV` unset | fails closed (refuses calls) | [M 16; R `service_auth.py:22-23`] | correct |

---

## 8. Interoperability and regulation in Taiwan, Japan and the US

An engineer's reading, not legal advice. "Meets" is what the repository shows (read); nothing here was assessed
by an authority.

### 8.1 Taiwan

| Standard or rule | What it asks of a product like this | TrialBox | Gap, size |
| --- | --- | --- | --- |
| TW Core IG 1.0.0 (MOHW) [S https://twcore.mohw.gov.tw/ig/twcore/] | FHIR R4 profiles and code systems for exchange | 13 profiles emitted and checked [R `services/adapter/validate/twcore_rules.json`]; registry latest is 1.0.0 [M 12] | none for output; no TW Core **input** from a FHIR server (STD-013). M |
| NHI coding: ICD-10-CM TW editions, ICD-9-CM before 2016, NHI drug and order codes, ATC | read the hospital's codes as written, by year | ICD-9-CM years fixed (NEW-STD-1) [R]; 2014→2023 edition map unused (STD-007) [R]; NHI drug → ATC not in the nightly path (STD-005) | S each |
| NHI claims files and MediCloud | the claims are the most complete history a hospital holds | absent [M 21] | claims reader M; MediCloud: not a bulk source [O] |
| 醫療機構電子病歷製作及管理辦法 (2022) [S https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0020121] | electronic records' integrity, access logs, outsourcing and encryption | applies to the hospital's record system; TrialBox reads copies and never writes back [R `docs/data/01-what-the-box-reads.md`] | none for the reader [O] |
| 個人資料保護法 (PDPA) | purpose, access logging, erasure | full review J (privacy table): erasure owed (J-2), withdrawal unread (J-3) | as there |
| 人體研究法, TFDA GCP, the TFDA 2024 computerised systems guideline | records, validation | full review K | as there |
| 資通安全管理法 (critical-infrastructure hospitals) [S https://mohw.gov.tw/cp-16-83515-1.html] | supplier security duties for designated hospitals | the security design in `docs/plan/design/03-security-privacy.md` [R] | a supplier statement (S), not code |

### 8.2 Japan

| Standard or rule | What it asks | TrialBox | Gap, size |
| --- | --- | --- | --- |
| SS-MIX2 standardised and extended storage [S https://www.ss-mix.org/] | read the tree and the HL7 v2.5 messages | section 1.3 | ADT-61, OML-01, OMG, ADT transfers, `_contents.xml`, one vendor storage: S to M each |
| JP Core 1.1.0 (JAMI / NeXEHRS) [S https://jpfhir.jp/fhir/core/] | FHIR profiles | 16 profiles checked offline [R]; the package registry's latest is 1.1.0 [M 12] (STD-020 noted a 1.2.0 IG page: which applies is **not verified**) | none |
| 電子カルテ情報共有サービス (3文書6情報, JP-CLINS) | FHIR documents between institutions | not read [M 21] | M, later [O] |
| MHLW 医療情報システムの安全管理に関するガイドライン (6.0, 2023; 7.0, 2026 per the repository) [S https://www.mhlw.go.jp/stf/shingi/0000516275_00006.html] | access control, logs, supply chain, 2FA | mapped control by control in `docs/plan/design/03-security-privacy.md` (SC-13 to SC-90) [R] | as there |
| APPI (2022) and 次世代医療基盤法 (amended 2024) | pseudonymised data, opt-out, third-party provision | pseudonyms at the door, opt-out register [R `libs/tb_common/optout.py:1-20`] | erasure (J-2) |
| ER/ES guideline (2005), J-GCP | electronic records and signatures | full review K: no assessment against the ER/ES guideline | as there |
| Japanese units and enzyme activity | read `IU/L`, `×10^3/μL` | half fixed [M 17] | S |

### 8.3 The United States

| Standard or rule | What it asks | TrialBox | Gap, size |
| --- | --- | --- | --- |
| HL7 v2 (ADT, ORU, ORM) over MLLP | the way most US hospital interfaces still deliver | absent [M 21] | L (or an integration engine at the site) |
| FHIR R4 US Core [S https://hl7.org/fhir/us/core/] (registry latest 9.0.0 [M 12]) | the profiles every certified EHR exposes | absent [M 21] | M |
| Bulk Data Access [S https://hl7.org/fhir/uv/bulkdata/] (3.0.0 [M 12]) and SMART App Launch / Backend Services [S https://hl7.org/fhir/smart-app-launch/] (2.2.0 [M 12]) | population export from certified EHRs (ONC certification criterion 170.315(g)(10)) [S https://www.healthit.gov/test-method/standardized-api-patient-and-population-services] | reads exported files only (STD-013) | M |
| USCDI (ONC HTI-1) [S https://www.healthit.gov/isa/united-states-core-data-interoperability-uscdi] | the data classes a US source will offer | not mapped [M 21] | M (with US Core) |
| HIPAA Privacy Rule de-identification (Safe Harbor's 18 identifiers, or expert determination) [S https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html] | what may leave the covered entity's control | the box stays inside the hospital; but the masker misses SSNs [M 15] | S for the detector; the rest is the hospital's |
| 21 CFR Part 11 [S https://www.ecfr.gov/current/title-21/chapter-I/subchapter-A/part-11] | electronic records and signatures | full review K | as there |
| FDA, Use of EHR data in clinical investigations (2018) [S https://www.fda.gov/regulatory-information/search-fda-guidance-documents/use-electronic-health-record-data-clinical-investigations-guidance-industry] | provenance of data from EHR to EDC | the signed Send with provenance (full review K) [R] | provenance pointer (G5) |
| OMOP CDM as a source (academic centres) | read an existing OMOP database | absent (1.1) | M |
| Units in US labs (conventional units) | mg/dL, U/L | read [R `libs/tb_common/labunit.py`] | none |

[O] The product today is a Taiwan and Japan product. A US site needs, at minimum, US Core on input through FHIR
files (M), an SSN rule in the guard (S) and a decision on HL7 v2 (L, or a site integration engine that writes
FHIR files).

---

## 9. What should move first: a short order [O]

1. The three one-day fixes: B1-D1 (Oracle and SQL Server drivers), B1-P1 (one guard, NFKC), B1-S3 (no hash
   embedder on a production box).
2. Terminology loaded at install (plan 8 TERM-1/2) with the concept-resolution count as its acceptance (B1-M2).
3. The GPU runs G-1 to G-4 (6 h of VM time) before any further tuning of prompts or batch sizes.
4. Decisions, not code: one lake source, one vector store, one screening engine, the US out of 1.0 or in.

---

## 10. Every fix, for plan 9

Lanes are a guess from plan 8 section 8b. ★ marks the twelve most important.

| Id | Layer | Fix | Size | Lane | Measure first |
| --- | --- | --- | --- | --- | --- |
| B1-D1 ★ | Data in | Oracle and SQL Server drivers in the image; a dialect test per database | S (+M for B1-Q2) | E, B2 | that a CGRD-type view reads through each driver (container test) |
| B1-D2 ★ | Data in | SS-MIX2: ADT-61 allergies; ADT-21/31/32/41/42/51; OML-01 and OMG; `_contents.xml`; delta by file time | M | B2 | the share of each type in a vendor sample storage |
| B1-D3 ★ | Data in | One SS-MIX2 vendor sample storage read end to end, numbers filed | M | B2, Int | – (needs the sample) |
| B1-D4 | Data in | NHI drug code to ATC in the nightly path (STD-005) | S | B2 | ATC share of medication rows before and after |
| B1-D5 | Data in | `IU/L` ↔ `U/L` for enzyme-activity analytes (STD-004 rest) | S | B2 | count of `unit_mismatch` on the JP synthetic site |
| B1-D6 | Data in | FHIR REST client: SMART Backend Services and Bulk `$export` (STD-013) | M | E | – |
| B1-D7 | Data in | US Core input mapping (Patient, Encounter, Condition, Observation, MedicationRequest, DocumentReference) | M | E | – |
| B1-D8 | Data in | HL7 v2 MLLP listener (ADT, ORU, ORM) or a written "use the site's integration engine to write files" | L | E | the first US or TW site's interface inventory |
| B1-D9 | Data in | OMOP CDM as an input source | M | B2 | – |
| B1-D10 | Data in | NHI claims files reader (TW) | M | B2 | a site's answer on what claim extracts it can give |
| B1-L1 ★ | Ladder | A rule: a pregnancy or lactation line never compiles to a sex-only atom | S | A2 | the 12 sex-only exclusion lines of P2b |
| B1-L2 ★ | Ladder | S2/S2b filter something or leave the screening path; refit S2b with the chosen embedder | M | A2 | recall of S2b-below on the gold sets |
| B1-S1 ★ | Stores | NDJSON only as the validator's sample; Arrow from the mapper | M | B2 | lake build time and peak memory at 50,000 |
| B1-S2 | Stores | Retire the `vec` schema for 1.0 | S | B2 | – |
| B1-S3 ★ | Stores | Refuse the hash embedder in VALIDATION and PRODUCTION; name the embedder in SCREEN provenance | S | A2 | – |
| B1-S4 | Stores | One lake source for 1.0 (STD-006) | S then M | Int, B2 | – (a decision) |
| B1-S5 | Stores | Split `_run_ingest` into named steps; size ratchet on the adapter | M | B2 | – |
| B1-M1 ★ | Model | Drop `--enforce-eager` if G-1 shows the gain | S | D | G-1 |
| B1-M2 ★ | Model | Terminology loaded at install; `concept_map` only for ties | M | E, H | concept names resolved by table, before and after |
| B1-M3 | Model | A configuration refusal is never retried as an outage | S | A2 | – |
| B1-M4 | Model | Duration and tokens per call in the gateway's trace | S | A2 | – |
| B1-M5 | Model | Serving engine update with the re-qualification card | S + run | D | G-1 on the new version |
| B1-C1 | Coupling | Retire the v1 evaluator after NAV moves to the cascade | M | A2 | NAV's outputs equal on the goldens |
| B1-C2 | Coupling | One chunker | S | B2 | – |
| B1-C3 | Coupling | Read-only grants for the console on the orchestrator's schemas | M | C2b, D | which console routes write which schemas |
| B1-Q1 | Code | `duckdb` 2.0 parity run, or a decision to ship 1.5.5 | M | B2 | goldens on 2.0 |
| B1-Q2 | Code | SQL connector tests on Oracle and SQL Server | M | B2 | – |
| B1-Q3 | Code | The Starlette test-client deprecation | S | C2b | – |
| B1-P1 ★ | Security | One identifier detector, NFKC-normalised, with a US set; used by compiler, masker and gateway | S | B2, A2 | the 18 probes plus a full-width set |
| B1-P2 | Security | `doctor` FAILs the tripwire off in PRODUCTION; launch records print it | S | D | – |
| B1-P3 | Security | Cap zip imports (size, count) | S | A2 | – |
| B1-P4 | Security | Refuse the v1 actor header and the legacy token in PRODUCTION | S | C2b | – |
| B1-I1 ★ | Interop | Say "Taiwan and Japan" in the 1.0 claim; a US scope decision for the owner | S | Int | – |
| B1-G1 ★ | GPU | Runs G-1 to G-4 on the VM | M (6 h VM) | Int | – |
| B1-F1 | Performance | Stop DuckDB's 112,252 failing `pandas` probes per 5,000-patient night | S | B2 | the stub gate before and after |
| B1-F2 | Performance | numpy for the recall certificate's grid loop | S | A2 | the certificate's time; byte-equal certificate |
| B1-F3 | Performance | `bisect` for code-prefix expansion | S | A2 | `build_rulesets --check` time; equal ValueSets |
| B1-F4 | Performance | ISO dates through `fromisoformat` in the mapper and the date walk | S | B2 | ingest time on the bench |
| B1-F5 | Performance | No Rust for 1.0; revisit at a measured 500,000-patient night | – | Int | the night at 500,000 after B1-S1 and the delta night |

---

## 11. Measurement log

Every command ran on this machine (4 cores shared with five other agents, load average 8 to 15 during the runs),
from `trialbox/` with `PYTHONPATH=libs:services:.` and the venv, unless the row names another folder. Scratch
files are under `/var/tmp/trialbox-0/b1/`.

| # | Command | Number |
| --- | --- | --- |
| 1 | `du -sb` on the seeded box `j1/box`: `hospital/`, `lake/ndjson/2026-11-02`, `lake/parquet/snapshot=2026-11-02`, `lake/db/2026-11-02.duckdb`, `lake/embed_cache.duckdb`; `wc -l hospital/*.csv` | 21,606,991; 152,165,004; 16,250,096; 47,198,208; 26,226,688 bytes; 149,030 CSV lines |
| 2 | read `j1/box/lake/ndjson/2026-11-02/ingest_report.json` and `publish.json` | 154,992 resources; 98.8 s start to finish; lake 33.48 s; 11,619 chunks; validator skipped; fhir and omop steps skipped; `fhir_unread` lists Coverage 5,001 and others |
| 3 | `find japan/ssmix2 -type f` by type folder; MSH-18 of 400 files of `200/` | 10,361 files (OMP-01 2,744, ADT-12 2,653, OML-11 1,897, PPR-01 1,142, OMP-11 1,077, ADT-00 400, OMP-02 165, OMP-12 109, ADT-52 68, ADT-22 68; extended 38); `~ISO IR87` 400 of 400 |
| 4 | read `japan/lake-ssmix2/ndjson/2026-10-31/ingest_report.json` and `reader.json` | 12,496 resources, 14 s; lake 3.82 s; validator structural-fallback on 139; ATC 62.47 %, ingredient 100 % of 3,648 lines |
| 5 | `pyarrow.parquet.read_metadata(...).num_rows` on `services/criteria_compiler/terminology/*.parquet` | atc 33; department 9; icd10cm_blocks 280; icd10cm_full 98,186; icd10cm_index 28,792; icd10cm_tw 79; loinc_tw 27; nhi_drug 24; nhi_order 4; synonyms 186 |
| 6 | `python3 /var/tmp/trialbox-0/b1/traces2.py sigir tcga` over `work/raw-traces.json` of the P2b sets | as section 3.2; trace keys: attributes, call_id, output, prompt, sc, span, ts |
| 7 | `python3 /var/tmp/trialbox-0/b1/screens.py sigir tcga` over `work/screen/*.json` | sigir: 101 reports, 550 applied, 447 human, 371 note criteria; S2 hit 4 / zero 288; S2b above 288 / below 0; S3 291; tokens 199,839 / 30,217. tcga: S2 0 / 500; S2b 500 / 0; S3 500; S4 48; tokens 1,509,865 / 117,284 |
| 8 | `grep -oE '"class": *"[a-z_]+"' sigir/work/answers.json \| sort \| uniq -c` | human 497, mixed 293, structured 282, note 93 |
| 9 | read `sigir/work/gateway-audit.json` and `services.log` | `upstream_failed` 7; seven "gave up, asking again in N parts" lines |
| 10 | `uv pip list --outdated --python .venv/bin/python` | 18 behind of 115 installed (list in 5.1) |
| 11 | Docker Hub tag listings (`hub.docker.com/v2/repositories/<repo>/tags`) for vllm/vllm-openai, postgres, python, hapiproject/hapi, eclipse-temurin | v0.34.0 newest vLLM release tag; postgres 18.7; python 3.14.9; hapi v8.12.0-2 |
| 12 | `curl https://packages.fhir.org/<package>` (dist-tags) | tw.gov.mohw.twcore 1.0.0; jp-core.r4 1.1.0; hl7.fhir.us.core 9.0.0; hl7.fhir.uv.bulkdata 3.0.0; hl7.fhir.uv.smart-app-launch 2.2.0 |
| 13 | `python3 /var/tmp/trialbox-0/b1/complexity.py .` (syntax tree over services and libs); `grep -c` of `.migrate(` and of `pickle\|yaml.load\|eval(\|shell=True` | 7,105 functions; 32 over 200 lines; `create_app` 2,011; `_run_ingest` 660 lines, 181 branches; 8 modules over 1,500 lines; 26 migrate call sites; no pickle or unsafe YAML |
| 14 | `grep -rn 'type: *ignore'` and `'noqa'` | 64 in services and libs, 807 with tools and tests; noqa 139 |
| 15 | `python /var/tmp/trialbox-0/b1/phi_probe.py` and `phi_probe2.py` (18 synthetic probes) | scan 5; mask_note 14; Guard.tripwire 13; full-width TW ID and US SSN missed by all |
| 16 | `measure_stub` with `TB_ENV` unset, then with `TB_LLM_OUTAGE_WAIT_S=0` | first run slept in `outage.wait_and_retry` for more than 8 min (stack taken with gdb); second failed in 11.8 s with `GatewayDown: gateway error 503: no service token configured` |
| 17 | `labvalue.ucum(...)`, `labunit.convert(45, "IU/L", "U/L", "http://loinc.org", "1742-6")` | `×10^3/μL` → `10*3/uL`; `mL/分/1.73m2` → `mL/min/{1.73_m2}`; convert → `None` |
| 18 | `grep -E '^name = "(oracledb\|cx-oracle\|pyodbc\|pymssql)"' uv.lock` | no match |
| 19 | `TB_ENV=TEST TB_LLM_OUTAGE_WAIT_S=0 python /var/tmp/trialbox-0/b1/prof_stub.py 5000` (cProfile around `tools.bench.measure_stub`); `analyse.py`, `pick.py` on the stats | profiled phases 164.9 / 55.7 / 62.7 s, total 289.7 s, 299.2 s own time; frames as in 6.1 |
| 20 | `TB_ENV=TEST TB_LLM_OUTAGE_WAIT_S=0 python /var/tmp/trialbox-0/b1/run_stub_plain.py 5000` (no profiler), then `bench.calibrate()` | 3.03 / 95.8 / 38.71 / 34.22 s, total 171.76 s, peak 1,758 MB; calibration 0.567 s |
| 23 | `python /var/tmp/trialbox-0/b1/import_cost.py` (twice); `count_imports.py` (a `sys.meta_path` spy) at 500 and 200 patients | failing import 98 and 80 µs; DuckDB statement 975 and 977 µs as shipped, 763 and 732 µs with `sys.modules["pandas"] = None`; 11,292 `pandas` look-ups at 500 patients, raised from `lake/store.py:1437` and `lake/store.py:1666` |
| 24 | `TB_ENV=DEV python /var/tmp/trialbox-0/b1/prof_compile.py` (cProfile around `tools.build_rulesets.main(["--check"])` and `doc_parser.parser.parse` of the GZQO PDF) | 8 rulesets "equal to the compiler's output", 11.98 s; parse 0.8 s |
| 21 | `grep -rli` over services and libs (code) and docs for `US Core`, `USCDI`, `MLLP`, `ORU^R01`, `CDA R2`, `DICOM`, `MediCloud`, `申報`, `JP-CLINS`, `X12` | 0 code files each (docs: 1, 0, 7, 1, 0, 1, 5, 3, 6, 1) |
| 22 | `grep -rl` over `tests/` for `ssmix`, and for each source name | ssmix 26 files; csv 81; cgrd_sql 6; fhir_bulk 6 |

---

## 12. What this analysis did not verify

- Any figure on a GPU: every model-time number is read from the stored P2b traces; per-call latency is not in
  them. The effect of `--enforce-eager` and of prefix caching (G-1, G-2).
- Whether the pinned vLLM release enables prefix caching by default.
- Any connector on real or vendor-sample data: no hospital SS-MIX2 storage, no Oracle or SQL Server database, no
  FHIR server was reachable or in scope.
- Delta reading time of SS-MIX2 on a large storage (the synthetic one has 400 patients).
- Known advisories of the installed packages: `pip-audit` is not installed and was not added. The JVM jars and
  Node tools were not compared with their latest releases.
- Dead code by tool (no vulture); the counts are by reading.
- Whether the public SS-MIX2 sample data of the consortium exists in a usable form.
- The share of the 497 "human" criteria that full code tables would turn into structured ones.
- Regulatory readings: the links were taken from the repository's own registers or from the standards' home pages
  and were not re-read in full today; none was assessed by a lawyer or an authority. Which JP Core release a
  Japanese site expects (1.1.0 on the package registry, a 1.2.0 IG page per STD-020).
- The test pyramid was not recounted (the full review's counts are cited); no test suite was run.
- Erasure, backups and restore were not exercised.
