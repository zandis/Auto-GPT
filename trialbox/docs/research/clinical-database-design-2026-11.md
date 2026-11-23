# Clinical database design: code tables, the store, sources, the profile and time (lane DB, 2026-11-23)

*Research and design only: this page changes no product code. Owner's ask of 2026-11-23, five parts. Every patient
named or counted here is synthetic (`tools/synth_hospital`). Public sources are cited by URL; a claim marked
**[unverified]** could not be read on the publisher's own page on 2026-11-23 (a page blocked, empty or moved), and
**[secondary]** means a search snippet or a third party, not the publisher. Findings are in the
[findings file](clinical-database-design-2026-11/findings.json) (card DB).*

**Reader:** the people who build TrialBox, and the integrator, who forms the cards.

## 0. Summary

- **Most of the asked-for design already exists.** OMOP v5.4 is the store of record with year partitions, the
  install-time loader exists with a named person per licence, the twin cites every item, the vector store is
  pgvector with HNSW, and instants are written in the site zone. What follows extends these. It does not replace them.
- **Code tables.** Five tables can ship or be fetched by the box with no person: ICD-10-CM, ICD-10-PCS, the NHIA open
  data, RxNorm's prescribable subset and UCUM. Every other table needs a person at the hospital: a named account,
  acceptance of terms, a fee or an affiliate agreement. An installer may open the page, prefill non-secret fields,
  check the file the person downloaded and load it. It may never accept terms (§2).
- **Today's screening queries.** Measured on the synthetic hospital amplified to 300,000 patients, one index date
  takes 0.6 s to 11.5 s per ruleset. About half of the operator time (46 % to 54 %) is the per-criterion value-set
  join. A one-pass "value-set hit" table, built once per snapshot, takes 0.25 s to 0.32 s to build. A 100-patient query still costs 24 % to
  48 % of the whole-hospital query, so slicing a run into patient batches repeats most of the work (§4).
- **The two biggest gaps.** First, the loaded code tables have two homes: the installed files in
  `TB_TERMINOLOGY_DIR`, and the OMOP vocabulary that D-301 calls the one home. Second, no fact read from a note has a
  versioned, cited home outside site setup.
- **Next.** Ten proposed cards, in four steps. None touches the PoC walk: each one either adds beside what is there,
  or sits behind a flag with an equivalence check (§5).

## 1. The five asks against what TrialBox has now

Paths are on master `2040ca24`; "l." is a line number.

| Ask | What exists (file, line) | Gap | Risk |
| --- | --- | --- | --- |
| 1. Code tables preloaded at install, updated later | **Loader:** `tools/terminology_install.py` l. 1–40: ICD-10-CM, ICD-10-PCS, NHI drugs and services, LOINC, WHO ICD-10 and ATC with `--accepted-by` (l. 151, D-1114), site lists. **Mount:** the volume is read-only in its readers (D-991). **Ruling:** D-1028. **Register:** `docs/licences/register.csv` (rows `loinc-full`, `atc-index`, `icd10-who`, `snomed-ct`, `athena-licensed`). **OMOP vocabulary:** `services/omop/vocab_load.py` (DATA §7.1, `docs/data/07-the-omop-store-of-record.md` l. 38). **JP masters:** `services/adapter/licensed.py` (D-137). | (a) Two homes: `vocab_load.py` never reads `TB_TERMINOLOGY_DIR` (grep: no hit), so a table loaded at install reaches the compiler but not `omop.concept`. This conflicts with D-301's "one home" and with D-1181 (value sets expanded for the store). (b) JJ1017, department codes and ICD-11 have no loader or register row. (c) No update schedule: a newer release is noticed only by a person. (d) No single page where the hospital does every licence step: the steps are command lines in `docs/handover/OFFLINE-MEDIA.md`. (e) The MEDIS, JLAC10 and YJ masters load through a second path (`adapter.licensed`). | High for (a): a criterion resolved from the installed table and the same code in OMOP can disagree, and the lake built from OMOP (`lake.source=omop`, D-384) would read `concept_id = 0`. Medium for (b) to (e). |
| 2. A clinical database built with standard methods: indexes, partitions, patient views, the vector index | **Store of record:** OMOP v5.4 with the pinned official indexes, seven tables partitioned by year of their required date (`services/omop/partitions.py` l. 25–33, D-339). **Screening reads:** a per-snapshot DuckDB lake (`services/lake/store.py`) with no secondary index, relying on DuckDB's zone maps. **Vectors:** pgvector `halfvec`, one HNSW per embedding model, btree on `(pid, note_date)` (D-439). **Batching:** `services/matching/batches.py` l. 43 (D-748, D-924). | (a) Each compiled criterion joins its fact table against an inline `VALUES` value-set list (`rulesets/GZQO/sql/GZQO.sql` l. 15 on; 35 such joins in GZQO), with correlated `EXISTS`. This is the measured hot spot (§4). (b) No per-snapshot materialised patient features (latest value per code, first and last coded date per value set). (c) The OMOP store has no composite (concept, date, person) index: the official DDL indexes person and concept apart. (d) The pid filter is `list_contains` over the base rows only, so the fact subqueries are not pruned by the batch. | Medium: the 300,000-patient one-index run fits in about 12 s on 4 cores, but FEAS (36 month-ends) and micro-batches repeat it. The risk grows with the batch count. |
| 3. Heterogeneous sources: schema'd feeds, physician sheets, free text, facts from notes | **Feeds:** the mapping YAML per site (DATA §2, `services/adapter/mapping/`), SS-MIX2 (lane M). **Codes:** a suggested standard code per local code (`services/sitesetup/mapping.py` l. 265). **Facts from charts:** site setup writes a NOTE and a NOTE_NLP row (`services/omop/load.py` l. 995). A model's unconfirmed fact goes to the lake's `site_fact` only (`services/lake/flatten.py` l. 17). **Notes:** full text, chunks and vectors (D-439, D-449). | (a) No field-level mapping proposal for a sheet with its own columns. The person writes `rename:` by hand; codes are suggested, columns are not. (b) A fact read from a note has no versioned, cited home of its own: NOTE_NLP keeps the term, the status and the offset, and the quote stays in site setup. There is no extractor version, no note-text hash, no supersede chain and no confirm state in the store of record. (c) D-1093 (inside the box, notes are read and indexed as written) is not yet reflected: the lake and the vector index still mask before chunking (`services/lake/store.py` l. 823, `services/vec/index.py` l. 58, DATA §11 l. 9). | High for (b): a confirmed fact cannot be traced back to the note version it came from once the note is changed at the source. Medium for (a) and (c). |
| 4. A patient profile built from all of this, easy to search | **Twin:** `services/patient_profile/twin.py` (`build` l. 399; study patients only, `study_pids` l. 445), versioned JSON with `source` on every item (D-440, DATA §10). | (a) Built only for study patients, so there is no profile for a hospital-wide search. (b) No search structure: the twin is one JSON document per patient, with no index over its layers. (c) No free text by design (DATA §10, `docs/data/10-the-patient-twin.md` l. 13), so note-derived facts reach it only once confirmed into the lake. | Medium: a "find patients like this" or a coordinator's search runs the whole cascade, or reads every twin. |
| 5. Time: dates, intervals, windows, the latest value, imprecise dates, time zones, what each date means | **Instants:** written in the site zone (`services/adapter/instants.py` l. 1–10, T-619a). **Dates:** ROC, Japanese-era and partial dates read in one module (`libs/tb_common/dates.py` l. 1–25; uncertain dates return None, never a guess). **Windows:** compiled as `BETWEEN (index_date + -90) AND index_date` on one chosen date column (`rulesets/GZQO/sql/GZQO.sql` l. 5411). **History:** as-of export (D-384). | (a) A stored date is a point. There is no precision, so a "2023-05" record is either refused or pinned to one day, and a window cannot answer "possibly within". (b) What each source's date means (ordered, collected, resulted, reported, billed) is fixed per lake column (`medication.authored`, `condition` onset else recorded), not recorded per source. (c) "Latest value" is computed in each criterion, with no shared rule for ties or same-day repeats. | Medium: the risk is a wrong "not met" at a window edge. The cascade's unknown-as-needs-information rule limits the harm. |

## 2. Licences: every code system, and who must do what

**Sources.** The register (`docs/licences/register.csv`) is the record. This table adds the access step and the
split between the installer and a person, from the publishers' pages read on 2026-11-23.

**Network.** The box loads through `deploy/terminology.sh` with `--network none` (D-991). Every download below is
therefore made by a person or by a networked staging machine, and the box only checks the file and loads it.

| System | Publisher, licence | Access | Fee | May TrialBox ship it? | What the installer may do / what a person must do | Updates | Today |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ICD-10-CM | CDC NCHS and CMS; US public domain ([CMS](https://www.cms.gov/medicare/coding-billing/icd-10-codes), [NCHS files](https://www.cdc.gov/nchs/icd/icd-10-cm/files.html)) | open download | none | yes (FY2026 ships, D-1029) | Installer: fetch, check and load. Person: nothing. | 1 October, plus a 1 April addenda | `icd10cm` loader |
| ICD-10-PCS | CMS; US public domain (same page) | open | none | yes | as ICD-10-CM | yearly | `icd10pcs` loader |
| NHIA ICD-10-CM/PCS Chinese edition and the 2014→2023 map | NHIA; Open Government Data License 1.0 ([data.gov.tw/dataset/177507](https://data.gov.tw/dataset/177507), [licence](https://data.gov.tw/license)) | open, an API URL | none | yes, **with the prescribed attribution** (the grant lapses without it) | Installer: fetch and load. Person: nothing. | irregular | edition map (§7.1) |
| NHI drug list (with ATC column), service and order codes | NHIA; OGDL 1.0 ([174450](https://data.gov.tw/dataset/174450), [169469](https://data.gov.tw/dataset/169469)) | open | none | yes, with attribution (`docs/licences/nhi-open-data-attribution.md`) | as above | the drug list changes often; the payment items daily | `nhi-build`, `nhi-drugs`, `nhi-services` |
| WHO ICD-10 | WHO; a licence by application ([WHO classifications licensing](https://www.who.int/about/licensing/classifications)) **[unverified]**: the page did not load | application form | not stated | no; the site loads its own copy (`icd10-who`) | Installer: open the page and prefill the organisation and purpose. **Person:** applies, accepts and downloads. | frozen | `icd10who --accepted-by` |
| WHO ICD-11 | WHO; CC BY-ND 3.0 IGO ([licence](https://icd.who.int/en/docs/icd11-license.pdf)) | API registration; a local container exists | none | yes, if code, title and URI are kept and cited; translations and maps need a WHO agreement | Installer: load a release file. Person: registers for the API, if used. | yearly | not loaded (no row) |
| LOINC (and its linguistic variants) | Regenstrief; the LOINC licence ([loinc.org/license](https://loinc.org/license/)) **[unverified]**: 403 from this session | free account | none | codes in rulesets yes, with the notice (`loinc`); the full table no (`loinc-full`) | Installer: open the download page and check the zip's sha256. **Person:** holds the account, accepts and downloads. Whether the zh-TW and ja variants are in the download is [unverified]. | twice yearly [unverified] | `loinc --accepted-by` |
| ATC/DDD | WHO Collaborating Centre, Oslo; WHOCC copyright ([copyright](https://atcddd.fhi.no/copyright_disclaimer/), [use](https://atcddd.fhi.no/use_of_atc_ddd/)) | order form, e-mailed file | €200 per electronic file [secondary] | **no**: "copying and distribution for commercial purposes is not allowed". Codes in value sets only; names need permission (`docs/licences/atc-permission-request.md`, written, not sent) | Installer: open the order page. **Person:** orders, pays and accepts. Installer: loads the file. | January, yearly | `atc --accepted-by` |
| SNOMED CT | SNOMED International; Affiliate Licence ([get SNOMED](https://www.snomed.org/get-snomed), [members](https://www.snomed.org/members)) | MLDS account | **Taiwan and Japan are not members**: a yearly fee by World Bank band and use | no; the vendor must be an Affiliate and sublicense each hospital, or the hospital is one | **Person:** the Affiliate (vendor or hospital) signs and pays. Installer: loads RF2 only after that. | monthly international releases [unverified] | none (Q-22) |
| UMLS Metathesaurus | NLM; UMLS licence ([licence](https://www.nlm.nih.gov/research/umls/knowledge_sources/metathesaurus/release/license_agreement.html)) | **personal UTS account**: "issued only to individuals" | none; a yearly usage report | only as an integral part of an application, with notice to NLM; source categories restrict it further | **Person:** a hospital staff member holds the UTS account and the API key. The installer may use the key that person supplies, once, through the secrets path. It never ships a vendor key. | May and November | not used |
| RxNorm | NLM ([files](https://www.nlm.nih.gov/research/umls/rxnorm/docs/rxnormfiles.html), [prescribable](https://www.nlm.nih.gov/research/umls/rxnorm/docs/prescribe.html)) | full set: UMLS licence; Current Prescribable Content: none | none | the prescribable subset yes; the rest as UMLS | Prescribable: installer fetches and loads. Full: person as for UMLS. | monthly, weekly updates | via the Athena bundle (`rxnorm`) |
| OHDSI Athena bundle | OHDSI ([how to download](https://github.com/OHDSI/Vocabulary-v5.0/wiki/General-Structure,-Download-and-Use)) | Athena account; a person picks vocabularies; the link comes by e-mail | none for the free vocabularies | no; licensed vocabularies need the user's own licence (`athena-licensed`) | **Person:** account, selection, download; CPT4 is rebuilt locally with that person's UMLS key. Installer: `python -m omop vocab athena --file DIR`. | per bundle | `omop vocab athena` |
| CPT | AMA; a licence per product ([licensing](https://www.ama-assn.org/practice-management/cpt/ama-cpt-licensing-overview)) | written licence | royalties | no | not proposed: US billing codes, not needed for TW or JP screening | yearly | never (`athena_never`) |
| MedDRA (and MedDRA/J) | ICH, MSSO and JMO ([meddra.org](https://www.meddra.org/)) **[unverified]**: empty page | subscription | tiered by revenue [unverified] | no | **Person:** the subscriber. Needed only for adverse-event coding, not for screening. | March and September [unverified] | not loaded |
| JJ1017 v3.4 (radiology order codes) | JSRT with JIRA and JAHIS ([JJ1017](https://www.jsrt.or.jp/97mi/content/jj1017.html)) | free PDF | none | terms not stated **[unverified]**: ask JSRT before shipping | Installer: load a table a person transcribed or the site's own list. Person: none known. | irregular (3.4 in 2024) | not loaded (no row) |
| MEDIS standard disease-name master (ICD-10 対応標準病名マスター) | MEDIS-DC ([byomei](https://www2.medis.or.jp/stdcd/byomei/index.html)) | open download | none | **no**: use outside a medical institution, or distribution, needs a 使用許諾申請書 and MEDIS's written permission | **Person:** the hospital downloads for its own use. Installer: loads it (`adapter.licensed`). | versioned (5.x) | site-loaded (`jp-licensed-masters`) |
| HOT / YJ code master | MEDIS-DC ([HOT](https://www2.medis.or.jp/master/hcode/)) **[unverified]**: the page did not render; YJ per the MHLW price list (`mhlw-yakka`, PDL 1.0) | open download [unverified] | none [unverified] | treat as MEDIS: no | as MEDIS | monthly [unverified] | site-loaded |
| JLAC10 / JLAC11 | JSLM ([code committee](https://www.jslm.org/committees/code/)) **[unverified]**: 403 | [unverified] | [unverified] | no (`jp-licensed-masters`) | **Person:** the hospital's own copy | versioned | site-loaded |
| Department codes | TW: NHIA 就醫科別 in the claims specification; JP: 診療科 codes in the MHLW receipt specification. Both **[unverified]**: no primary page read | public specifications [unverified] | none | TrialBox's own department table ships (`trialbox-terminology`); the site's own list wins (D-1113) | Installer: load the site's list. Person: confirms the local-to-standard map. | rare | own table plus site list |
| UCUM | Regenstrief and the UCUM Organization ([licence](https://ucum.org/license)) | none | none | yes, with notice; no derivative works | none | rare | cleared (`ucum`) |
| HL7 terminology (THO) | HL7; CC0 for HL7-authored content, external systems keep their own licences ([terminology.hl7.org](https://terminology.hl7.org/)) **[unverified]**: a redirect stub | none | none | yes for HL7-authored code systems | none | several per year [unverified] | via FHIR packages |

**What the installer may do, and what it may not.**

The installer is the installer bot or `tools/terminology_install.py`.

- **May:**
  - open the publisher's page in the person's browser;
  - prefill fields that hold no secret and no personal choice: the hospital's legal name, the purpose and the
    product;
  - name the exact file and release to fetch;
  - check the sha256 of the file the person downloaded, and the release it claims to be;
  - load it, and record the release, the file hash and the person's name and date (`--accepted-by`, D-1114);
  - remind before a known release date.
- **May not:**
  - tick a licence box, submit an acceptance or create an account;
  - type a password or hold a person's API key beyond the one load it was given for;
  - pay;
  - fetch a licensed file with credentials that are not the hospital's own.
- **Why.** The terms read here grant the licence to a named individual (UMLS) or to the organisation that signs
  (SNOMED Affiliate, MEDIS, AMA). None of the terms read allows an agent to accept for the licensee. Where the
  wording could not be read (LOINC, Athena), the same rule is assumed.

**Updates.** Each manifest line gets the publisher's known cadence. The doctor reports a table "due" after that
date (D-1028 point 1 and card V-18). The box never fetches. A person brings the file on the offline media, as at
install.

## 3. Recommended target design

The design follows what the public systems do, measured against TrialBox:

- **OMOP's model.** Concept-based facts, with `concept_ancestor` expanding a hierarchy in one join, and era tables
  ([CDM 5.4](https://ohdsi.github.io/CommonDataModel/cdm54.html),
  [Book of OHDSI, vocabularies](https://ohdsi.github.io/TheBookOfOhdsi/StandardizedVocabularies.html)).
- **OMOP's official indexes.** person and concept indexed apart; no date index; `CLUSTER` on person
  ([indices](https://github.com/OHDSI/CommonDataModel/blob/main/inst/ddl/5.4/postgresql/OMOPCDM_postgresql_5.4_indices.sql)).
- **Circe's cohort logic.** Windows relative to the index date, collapsed into non-overlapping periods
  ([circe-be](https://github.com/OHDSI/circe-be), [cohorts](https://ohdsi.github.io/TheBookOfOhdsi/Cohorts.html)).
- **HAPI's JPA store.** Hashed per-type search-index tables (`HFJ_SPIDX_*`), with dates stored as low and high
  bounds ([schema](https://hapifhir.io/hapi-fhir/docs/server_jpa/schema.html)).
- **Medplum.** One table per resource type, with search columns and token lookup tables beside the JSON. It warns
  that GIN `fastupdate` stalls bulk writes
  ([search architecture](https://www.medplum.com/docs/contributing/search-architecture),
  [GIN](https://www.medplum.com/docs/self-hosting/gin-index-performance)).
- **i2b2.** One `observation_fact` table, indexed on concept and on (start date, patient)
  ([DDL](https://raw.githubusercontent.com/i2b2/i2b2-data/master/edu.harvard.i2b2.data/Release_1-8/NewInstall/Crcdata/scripts/crc_create_datamart_postgresql.sql)).
- **TriNetX.** Federated, with the data kept at each site
  ([JAMIA Open 2023](https://academic.oup.com/jamiaopen/article/6/2/ooad035/7161780)).
- **Epic.** A relational reporting copy (Clarity) feeds a dimensional warehouse (Caboodle)
  ([Caboodle](https://ehealth.connect-care.ca/epic-systems/epic-analytic-tools/caboodle),
  [Clarity](https://ehealth.connect-care.ca/epic-systems/epic-analytic-tools/clarity)).

The common pattern is that a transactional record is copied nightly into a read model built for the question.
TrialBox already has that pattern (OMOP, then the lake snapshot). The design below gives the read model the
structures the measurements ask for.

**Module boundaries.**

| Module | Owns | Writes | Reads | New | Flag / proof |
| --- | --- | --- | --- | --- | --- |
| T. Terminology | install and update of every code system; the one manifest | `TB_TERMINOLOGY_DIR` (as now) **and**, in the same step, `omop.concept`, `concept_synonym`, `concept_relationship`, `concept_ancestor` and `tb_vocab_release` through `vocab_load` | publisher files a person brought | one manifest line kind per §2 row; a "due" date; a console page **Code systems** that lists each row, its state, the person who accepted and the next step | none: adds tables; the doctor's `terminology` line already exists |
| VS. Value-set expansion (D-1181, V-18) | the expansion of each ruleset's value sets against the loaded release | `omop.tb_valueset_member(vs_id, ruleset, release, concept_id, system, code)` | module T | the table; the release it was expanded against | the compiler's equivalence harness: the same ValueSets and SQL as `TB_TERMINOLOGY_SOURCE=parquet` |
| S. Store of record | OMOP as now | as now | as now | composite indexes `(<domain>_concept_id, <date>, person_id)` and `(<domain>_source_concept_id, <date>, person_id)` on the partitioned tables; `concept_ancestor` both ways as shipped; the era tables built per night | DQD and migration pins; no change to the official DDL file |
| R. Read model (the lake) | a per-snapshot screening model | the lake snapshot | OMOP, or the NDJSON | per snapshot: `vs_hit(vs_id, pid, d_low, d_high, rid, src_table)` from module VS; `latest_value(pid, code, system, d, value, unit, rid)`; `coded_span(pid, vs_id, first_d, last_d, n)` | behind a flag `lake.read_model`; the compiler emits a second SQL form that reads `vs_hit`; CI runs both forms on every ruleset and fails on a difference (as D-384 did for `lake.source`) |
| N. Note facts | facts read from notes | `omop.note_nlp` (as now) plus `omop.tb_note_fact` (§3.2) | notes, the extractor | provenance, versions and a confirm state | facts stay out of the coded tables until confirmed (as now: `site_fact`) |
| P. Profile and search | the twin, all patients, and its search table | `profile.tb_patient_profile` (as now); `profile.tb_profile_search` per snapshot | the lake snapshot | the search table (§3.3) | the twin's `basis` and `permit`, as now |
| X. Source intake | mapping proposals for sheets with their own columns | `sitesetup` proposals, then the mapping YAML version a person confirmed | the uploaded sheet | field profiling and a proposal (§3.1) | nothing reaches a snapshot before a person confirms (as codes today) |

### 3.1 Heterogeneous sources

**Feeds with a schema** (CGRD SQL, CSV with the canonical columns, SS-MIX2, FHIR bulk) keep the mapping YAML
(DATA §2). Nothing changes.

**A sheet with its own structure** (a physician's Excel list) goes through a proposal step in site setup:

1. **Profile the columns.** Header text in ja, zh-TW and en; the value type (date, number, code-like, free text);
   the date forms `tb_common.dates.read` accepts; the code system a code-like column matches (by trying
   `sitesetup.mapping.suggest` on a sample); the unit pattern.
2. **Propose a target for each column:** a canonical column, `site_fact`, or "keep as note". The proposal comes from
   the header and the profile; the language model ranks candidates only when the header is free text.
3. **A person confirms** each column. The confirmed map is saved as a mapping version, with its sha, exactly as a
   hand-written `rename:` is today.

No value is guessed. A column a person has not confirmed stays out.

**Free text** is read by the language model inside the box. Per D-1093, the note is read and indexed as written.
Masking applies only where data leaves the box (exports, mail). For module R, D-439's "masked text" therefore
becomes "the note's text". The chunk offsets stay valid, `mask_version` records `none`, and §11 and D-439 need a
superseding decision (card DB-C6).

### 3.2 Facts from notes: storage, versions and citation

`omop.tb_note_fact`, beside NOTE_NLP, one row per fact version. NOTE_NLP's own fields stay the OMOP view of a
confirmed fact: `offset`, `lexical_variant`, `term_exists`, `term_temporal`, `term_modifiers`, `nlp_system`,
`nlp_date`.

| Column | Meaning |
| --- | --- |
| `fact_id`, `version` | stable id; a new reading of the same span makes the next version, and the old one is marked superseded, never rewritten |
| `person_id`, `note_id`, `note_sha256` | the note, and the exact text version read: a note changed at the source gives a new sha, and the fact is re-read, not carried |
| `start_char`, `end_char`, `quote_sha256` | the cited span: the quote is `note.text[start:end]` and its hash proves it is unchanged |
| `domain`, `concept_id`, `source_value`, `value_as_number`, `unit`, `d_low`, `d_high`, `d_precision` | the fact, with its date as an interval (§3.4) |
| `assertion` | present, absent, possible, historical or family. NOTE_NLP's `term_exists` and `term_temporal` are derived from it |
| `extractor`, `extractor_version`, `prompt_sha256`, `read_at` | what read it (the build id only, never a model name in the repository text) |
| `state`, `by`, `at`, `reason` | `proposed`, `confirmed` or `rejected`, and by whom. Only a `confirmed` fact reaches the coded tables and the lake (as `site_fact` rules today) |

FHIR side: a confirmed fact is exported as the resource with a `Provenance` (`entity.role = quotation`, the
DocumentReference as `entity.what`, the extractor as an agent)
([Provenance](https://hl7.org/fhir/R4/provenance.html),
[DocumentReference](https://hl7.org/fhir/R4/documentreference.html)). The twin cites `fact_id@version`, so a
reader can open the note at the span.

### 3.3 The patient profile and its search

- **Keep the twin as the cited document** (D-440).
- **Build it for every patient in the snapshot**, not only study patients. This is a cost to measure first (card
  DB-C9).
- **Add `profile.tb_profile_search`**, one row per patient per snapshot:
  - `pid`, `age_band`, `sex`;
  - `vs_ids text[]` (every value set the patient has a hit in, from module R);
  - `codes text[]` (system|code);
  - `latest jsonb` (code → value, unit, date);
  - `last_encounter`, `depts text[]`;
  - `tsv tsvector` over the profile's display names in ja, zh-TW and en.

  Indexes:
  - GIN on `vs_ids`, `codes` and `tsv`, with `fastupdate = off`: the table is rebuilt per snapshot, so Medplum's
    write stalls do not arise;
  - btree on `(age_band, sex)`.
- **Reads go through `permit`**, like the twin. A search result is a list of pids, and each hit opens the twin.
- **The similarity layer** stays the vector store's (D-439).

### 3.4 Time

- **Every event date becomes an interval:** `d_low`, `d_high` and `d_precision` (day, month, year), the way FHIR
  treats a partial date as an implicit range ([datatypes](https://hl7.org/fhir/R4/datatypes.html),
  [search: dates](https://hl7.org/fhir/R4/search.html)) and HAPI stores LOW and HIGH. A day-precise date has
  `d_low = d_high`. `tb_common.dates` keeps refusing what it cannot read. A year or a month that it can read for
  certain becomes a wider interval instead of None.
- **Windows are three-valued.**
  - "Within 6 months before the index date" is **met** when `[d_low, d_high]` lies inside `[index − 6 months,
    index]`.
  - It is **not met** when the two do not overlap.
  - Otherwise it is **unknown**, which goes to needs-information, as the cascade does today.
  - Month arithmetic uses `tb_common.timeutil.add_months` (end-of-month clamp), as the compiler does now.
- **Latest value** is one rule for every criterion and for `latest_value`: the greatest `d_high`, then the
  greatest instant, then the highest row id. A same-day repeat counts as one value when its value and unit are
  the same.
- **Date meaning per source.** The site profile (DATA §15) records, per source table and date column, what the date
  is: ordered, collected, resulted, reported, administered, dispensed or billed. Each value set's domain then names
  the meaning it wants, for example "lab result: collected, else resulted". The lake's chosen column today (for
  example `coalesce(onset, recorded)`) becomes this rule written down.
- **Time zones.** Instants stay in the site zone (T-619a). A date without a time stays a date, never a midnight
  instant, as OMOP leaves `*_datetime` NULL ([CDM 5.4](https://ohdsi.github.io/CommonDataModel/cdm54.html)). The
  index date is a site-zone date.

## 4. Measured note: today's screening queries

**Set-up.** This session's container: 4 cores, 15 GB, DuckDB 4 threads, local PostgreSQL 16 (no pgvector).

**Data.** `python -m tools.synth_hospital --profile ci` built the site `tw-a`: 2,500 fictional patients, 70,000
lake rows. It was ingested with `tests/inproc_box.ingest_site`, then amplified ×20 and ×120 with
`tools/bench.py`'s `amplify`: every patient copied with suffixed ids, so the dates and value mix are the same.

**Queries.** Each shipped ruleset's compiled SQL (`rulesets/*/sql/*.sql`), run directly on the snapshot. Times are
the median of three runs, in seconds.

**Not run:**
- the product's batching (`matching.batches.query_by_patients`);
- the lake service over HTTP;
- the vector store (pgvector is not installed in this container);
- the 36-month form at 300,000 patients past the first ruleset (out of memory; see below).

| Ruleset | 2,500 · 1 index | 2,500 · 36 month-ends | 50,000 · 1 index | 50,000 · 36 month-ends | 300,000 · 1 index | 300,000 · 100 pids |
| --- | --- | --- | --- | --- | --- | --- |
| AD-MAB | 0.07 | 0.35 | 0.35 | 4.79 | 1.89 | 0.87 |
| GOUT-COH | 0.12 | 0.59 | 0.68 | 10.36 | 3.69 | 1.03 |
| GZQO | 0.48 | 1.42 | 1.85 | 21.95 | 11.50 | 2.79 |
| NEUR-COH | 0.02 | 0.18 | 0.13 | 2.87 | 0.60 | 0.15 |
| ONC-OSI | 0.06 | 0.36 | 0.35 | 4.75 | 1.84 | 0.87 |
| RA-BIO | 0.47 | 1.54 | 1.95 | 20.51 | 9.01 | 1.94 |
| RA-COH | 0.14 | 0.53 | 0.73 | 8.30 | 3.53 | 1.00 |
| RA-JAK | 0.40 | 1.11 | 1.46 | 14.63 | 6.40 | 1.82 |

**What the numbers show.**

1. **One index date scales about linearly:** ×120 patients costs ×20 to ×30.
2. **The 36-month-end form as one query does not fit at 300,000 patients.** AD-MAB took 37.3 s, then GOUT-COH
   stopped at DuckDB's 10.6 GiB limit. This confirms why the product slices the patients (NEW-B-53, D-748; the
   comment in `services/orchestrator/scenarios/feas_compute.py` l. 297 records the same at 50,000). It is not a new
   defect.
3. **A slice does not cost its share.** At 300,000 patients, 100 patients cost 24 % (GZQO) to 46 % (AD-MAB) of the
   whole hospital. The fact subqueries are not restricted to the slice's patients: the pid filter is on `base` only
   (`rulesets/GZQO/sql/GZQO.sql` l. 11). So N slices pay most of the fixed work N times. (Hypothesis for the
   product's own slice size, which this run did not use.)
4. **Where the time goes.** Profiled: GZQO and RA-BIO at 300,000 patients, one index date. Operator time was 23.3 s
   and 24.8 s, wall time 9.6 s and 9.2 s.

   | Operator | GZQO | RA-BIO |
   | --- | --- | --- |
   | Correlated `EXISTS` against the inline value-set list (`LEFT_DELIM_JOIN`) | 31 % | 23 % |
   | Hash joins | 23 % | 23 % |
   | Group-bys | 17 % | 19 % |
   | All table scans together | 14 % | 18 % |

   GZQO has 35 criterion joins over the fact tables (25 on `condition`); RA-BIO has 32.

   **What would help.** A one-pass `vs_hit` table: every value-set code of the ruleset joined once to `condition`,
   `observation` and `medication`. It built in **0.25 s** for GZQO (5,280 value-set codes, 1.62 million hits) and
   **0.32 s** for RA-BIO (2.05 million hits). A `latest_value` table (patient × code) built in **0.26 s**
   (1.59 million rows). These are building times only. The rulesets were not rewritten to read the tables, so the
   end-to-end gain is not measured: that is card DB-C4, with its equivalence check.
5. **PostgreSQL (the OMOP store).**

   **Data.** The OMOP load of the same site (`python -m omop load`, 17 s), copied ×100 into unpartitioned scratch
   tables: 699,400 conditions for 230,300 persons, and 2,113,000 measurements. Medians of three, in ms.

   | Query | No index | Person and concept indexes, apart (as the official DDL) | Plus a composite (concept, date, person) / (concept, person, date desc) INCLUDE value |
   | --- | --- | --- | --- |
   | A condition within 6 months before the index | 25.7 | 26.0 | **12.6** |
   | Latest lab value ≥ 7 before the index, per person | 103.6 | 165.2 | 116.9 |
   | One person's conditions (profile page) | 18.4 | **0.38** | 0.34 |

   - **The composite index halves the windowed query.**
   - **The per-person latest value is not helped by any index.** The planner prefers a bitmap scan and a sort.
   - **A materialised `latest` view does help.** One row per person and code (built in 1.35 s, unique index 0.38 s)
     answers the latest-value query in **24 ms to 48 ms**, and `REFRESH ... CONCURRENTLY` took 6.4 s. It holds the
     latest value as of the snapshot, not as of an earlier index date, so FEAS's month-ends still need the window
     form.
   - **The year partitions do not help these person- and concept-centred reads.** In the synthetic site most rows
     fall in the 2026 partition. A forum thread on a 500 GB MEASUREMENT table notes that OHDSI's queries filter by
     concept, not by date
     ([OHDSI forum](https://forums.ohdsi.org/t/seeking-guidance-on-partitioning-the-measurement-table-in-postgresql-cdm-v15/24062)).
     Keep the partitions for retention and vacuum, and add none.
6. **The vector index** was not measured. pgvector 0.8's iterative index scans (`hnsw.iterative_scan`) are the
   documented answer to a filtered nearest-neighbour search: a per-patient filter after the HNSW scan returns too few
   rows. For a selective patient filter, the documented alternative is the existing btree on `(pid, note_date)`
   ([pgvector](https://github.com/pgvector/pgvector),
   [0.8.0](https://www.postgresql.org/about/news/pgvector-0.8.0-released-2952/)).

**Recommended indexes and views, in order.**

1. `vs_hit` and `latest_value` per lake snapshot, read by a second SQL form (DB-C4).
2. Restrict each criterion's fact subquery to the slice's pids (DB-C5).
3. Composite (concept, date, person) indexes on the OMOP partitioned tables (DB-C3).
4. `tb_profile_search` with GIN (DB-C9).
5. Set `hnsw.iterative_scan` for the patient-filtered vector reads (DB-C10).

## 5. Proposed cards

Sizes: S is up to a day, M a few days, L a week or more. Lanes as on #639. A lane marked "?" is a guess for the
integrator to set.

| Order | Card | What | Owner lane | Size | Needs |
| --- | --- | --- | --- | --- | --- |
| 1 | DB-C1 | One home for the loaded tables: `terminology_install` also runs `vocab_load` into `omop.concept` and its relations in the same step, or `vocab_load` reads `TB_TERMINOLOGY_DIR`; a test that a loaded LOINC row resolves in both | E (TERM loader) with V (V-18) | M | a ruling on which side owns the write (question below) |
| 1 | DB-C2 | Licence rows and loaders for JJ1017, department codes, ICD-11 (optional) and MedDRA (not loaded, row only); the register's `access` and `cadence` columns from §2; the doctor's "due" line | E | M | JSRT's answer on JJ1017 terms |
| 2 | DB-C3 | Composite indexes `(<concept>, <date>, person_id)` on the partitioned OMOP tables, as an OMOP migration beside the pinned DDL; a measured note at 300,000 patients | the lane that holds `services/omop/` (?) | S | none |
| 2 | DB-C4 | Read model `vs_hit`, `latest_value` and `coded_span` per lake snapshot, from D-1181's expansion; the compiler's second SQL form behind `lake.read_model`; CI runs both forms on every ruleset and its goldens | the compiler's lane with the lake's (?) | L | DB-C1, D-1181's table |
| 2 | DB-C5 | Restrict the fact subqueries to the slice's pids (semi-join on `base`); a measured note of a 300,000-patient FEAS with the product's slices, before and after | the compiler's lane (?) | S | equivalence goldens |
| 3 | DB-C6 | D-1093 in the store: index notes as written inside the box (`mask_version = none`); a decision superseding D-439 item 3 and DATA §11's masking line; exports keep masking | the lane that holds `services/vec/` (?) | M | the integrator's ruling on the decision text |
| 3 | DB-C7 | `omop.tb_note_fact` with versions, note sha, span and quote sha, extractor id and confirm state; NOTE_NLP from confirmed rows; the twin cites `fact_id@version`; the FHIR Provenance on export | lane V (FHIR side) with the lane that holds site setup (?) | L | none |
| 3 | DB-C8 | Date intervals: `d_low`, `d_high` and `d_precision` in the lake rows; three-valued windows in the compiler; one latest-value rule; date meaning per source in the site profile (DATA §15) | the compiler's lane, with M for the site profile | L | DB-C4 |
| 4 | DB-C9 | `profile.tb_profile_search` for every patient per snapshot, with GIN; a measured note of twin build cost hospital-wide | the lane that holds `services/patient_profile/` (?) | M | DB-C4 |
| 4 | DB-C10 | Sheet intake: column profiling and a proposed mapping in site setup, confirmed by a person; `hnsw.iterative_scan` for patient-filtered vector reads | M (mapping) | M | none |

**What the PoC walk keeps.**

- Nothing above changes a table, route or result the PoC walk reads until its flag is switched.
- DB-C1 and DB-C2 add loaders and rows.
- DB-C3 adds indexes.
- DB-C4, DB-C5 and DB-C8 put a second SQL form behind a flag, proved equal on every ruleset before any flip.
- DB-C6 needs a ruling.
- DB-C7 and DB-C9 add tables.

## 6. What this page did not do

- **No product code, no decision file and no register row.** Findings go only in the
  [findings file](clinical-database-design-2026-11/findings.json).
- **No licensed file downloaded, no account made, nothing paid.** Pages that could not be read are marked.
- **No end-to-end timing of the proposed read model.** Only its building times were measured (§4 point 4).
- **No vector timing** (no pgvector here), and no timing through the lake service or the product's slices.
- **One container, not a box.** The numbers are this session's 4-core container, not the reference host of
  `tools/bench.py`.
