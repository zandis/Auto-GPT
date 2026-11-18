# Root review 06: code systems and terminology (lane J, round 2, 2026-11-17)

**Reader:** the owner (a clinician) first, then the builders and whoever writes plan 9's next revision.

**The question, in the owner's words:** "The coding use: OHDSI, I have the entire version, we need to use all, and
find ALL possible open coding systems to improve it."

**How every claim is marked.**

| Mark | Meaning |
| --- | --- |
| **[measured]** | A command was run in this session; the command and the number are given (log in section 10) |
| **[read]** | Read in the repository; file and line given. Paths are relative to `trialbox/`, at master `8778394f` |
| **[source]** | Opened at the publisher on 2026-11-17; the link is given (list in section 11) |
| **[opinion]** | The author's judgement or estimate, with its reasoning |
| **[not verified]** | Could not be opened or checked in this session; never filled from memory without this mark |

It builds on root review 01 (B1-M2: 676 `concept_map` calls), 03 (B3-2), 05 (section 2c), plan 9 (C-5, 9c-2, 9c-3,
decision 12) and the decisions D-858, D-1028, D-1029, D-1113 to D-1116, D-1127 and D-1128. It does not repeat them.

---

## 1. One page for the owner

**What is good enough today.**

- The plumbing for "load code systems at install" exists and is careful: a loader with a manifest per table, a
  refusal when a file changed, a named person who accepts each licence, a guard test that keeps licensed data out of
  git, and a licence register of 54 rows [read: `services/criteria_compiler/terminology/installed.py:1-30`,
  `tests/unit/test_term2_licensed_tables_never_committed.py`, `docs/licences/register.csv`].
- An Athena loader exists too (`services/omop/vocab_load.py:798-1037`, `load_athena`), with a licence
  acknowledgement per vocabulary and a release row [read]. Rulesets already carry a pinned "terminology release" and
  are marked "recompile needed" when it changes [read: `vocab_load.py:24-30`, `terminology/resolver.py:166-211`].
- ICD-10-CM is complete: 98,186 codes, 280 blocks and 28,792 index terms ship in the image [measured, row 5].

**What is not good enough.**

1. **The model is asked to pick a code from lists that hold almost nothing.** In the P2b sigir launch the
   `concept_map` call ran 676 times, and **626 of the 676 answers (93 %) chose no code** [measured, row 3]. The model
   did nothing useful in nine calls of ten. The reason is in the code: the candidates come only from the curated demo
   rows (79 ICD-10-CM, 27 LOINC, 4 procedure rows), not from the full lists [read: `mapper.py:11-14`, `:879-892`].
2. **Medicines never reach either a table or the model.** Of 200 drafted medication concepts, 4 resolve [measured,
   row 4], and 0 `concept_map` calls were for medication [measured, row 3]: the 33-row ATC table shares no word with
   trial drug names, so the candidate list is empty and the mapper answers "no mapping" silently.
3. **The "43 % a person decides" is mostly not a terminology problem.** Of the 497 "human" criteria, only 60 carry
   `concept_unmapped`; 197 carry `logic_invalid` and 150 carry none of the flags `concept_unmapped`, `logic_invalid`, `structure`, `group_*` (the model chose "human") [measured, row 6].
   Terminology's real damage is elsewhere: **356 criteria still classed structured or mixed have an unmapped concept**,
   so their coded check matches nothing [measured, row 6]. Full code systems repair those; they do not empty the
   "human" pile. Review 01's chain "demo tables, so 43 % human" is corrected here.
4. **The Athena loader cannot load a real Athena download.** It reads every table into Python lists before writing
   [read: `vocab_load.py:838-851`]; a full CONCEPT_ANCESTOR has tens of millions of rows [opinion, section 3.4]. It
   refuses SNOMED, ICD10CM, ICD10PCS, NDC and every other vocabulary not on a 25-name allow-list [read:
   `vocab_load.py:801-805`], skips DRUG_STRENGTH [read: `:824`], and the compiler never reads what it loads: it reads
   only its own Parquet tables, mirrored [read: `resolver.py:146-163`, `vocab_load.py:446`].
5. **Three stores of codes with three registers**: the compiler's Parquet folder with `manifest.json`, the OMOP
   vocabulary tables with `tb_vocab_release`, and the reference-data pack in schema `refdata` [read:
   `installed.py:1-30`; `vocab_load.py:1-35`; `libs/tb_common/refdata.py:1-40`]. A site's IT meets three procedures.
6. **Another prompt writes codes from memory.** `chart_facts` asks the local model for ICD-10-CM, LOINC and ATC codes
   "when you are sure" with no list [read: `libs/tb_llm/prompts/chart_facts_v2.md:13-15`]; a condition or medicine
   code is kept unchecked against any code list [read: `services/sitesetup/charts.py:333-335`] (proposed, a
   coordinator confirms).

**The five changes that matter most.**

1. **Candidates from the full code systems, and drugs through RxNorm and ATC** (T6-1, T6-3). The model then chooses
   among real codes or is not asked.
2. **One vocabulary store: the Athena bundle loaded by streaming into PostgreSQL**, with DRUG_STRENGTH, the licence
   register as the allow-list, and the compiler reading it (T6-4, T6-5).
3. **Descendants and Maps-to in the compiler**: "any anticoagulant" becomes ATC B01A and all its RxNorm ingredients;
   a hospital's ICD-10-CM, NDC or NHI code reaches the same concept (T6-6, T6-7).
4. **Measure before and after with a replay that needs no model** (T6-2): it already reproduces 718 model-step calls
   against the launch's 676 [measured, row 7].
5. **Settle the licences in one register and one decision list** (section 9): SNOMED is not usable at a Taiwan or
   Japan site without an affiliate licence; ATC names need WHOCC permission; MEDIS masters need an application.

**What it costs.** No purchase is needed for the first four changes: they use the owner's Athena download, which is
loaded at the site and never shipped. Effort: 16 cards, about 3 L, 8 M and 5 S (section 8) [opinion]. Paid or
permission items wait for the owner (section 9): the ATC/DDD electronic index (price not verified today), a SNOMED
affiliate licence (fee per hospital per year, quoted in `docs/plan/snomed-inquiry.md`), MedDRA and WHODrug
subscriptions only if adverse-event coding enters scope.

---

## 2. What TrialBox uses today

### 2.1 Every code table in the repository

| Table | Rows | Where from | Licence (register row) | Used for |
| --- | --- | --- | --- | --- |
| `icd10cm_full` (`terminology/src/icd10cm_2026.csv.gz`) | 98,186 [measured] | CMS/NCHS FY2026 | US public domain (`icd10cm`) | compile: code lookups and code-prefix groupers; not candidates [read: `mapper.py:11-14`] |
| `icd10cm_blocks`, `icd10cm_index` | 280; 28,792 [measured] | CMS FY2026 tabular and index | `icd10cm` | compile: step 2d, condition names (D-858) |
| `icd10cm_tw` | 79 [measured] | curated demo, with zh-TW names | `icd10cm-tw`, own work | compile: exact names and **the only condition candidates** for the model [read: `mapper.py:885-887`] |
| `atc` | 33 [measured] | curated demo | `atc` (WHOCC; permission to ask) | compile: medication names and candidates |
| `loinc_tw` | 27 [measured] | curated demo, zh-TW names | `loinc` | compile: observation names and candidates |
| `nhi_drug`, `nhi_order` | 24; 4 [measured] | synthetic demo rows (`synthetic=yes`) | `nhi-codes` | compile: claim and procedure domains |
| `department` | 9 [measured] | own | `trialbox-terminology` | encounter domain |
| `synonyms` (curated groupers) | 186 [measured] | own | own work | compile step 2 |
| `refdata_src/zh_tw_clinical_synonyms.csv`, `ja_clinical_synonyms.csv` | 42; 70 [measured] | own | `trialbox-terminology` | compile step 2a (D-172) and the note dictionary |
| `refdata_src/icd10_who_cm_checked.csv` | 36 [measured] | own bridge, codes only | `icd10-who-cm-bridge` | WHO-only categories (D-314) at screening |
| `refdata_src/jp_yj_atc.csv` | 56 [measured] | own, YJ stems from MHLW list | `yj-atc` | Japan: medication YJ → ATC at ingest and in ValueSets (T-610) |
| adapter `jp_core/byomei_to_icd10.csv`, `jlac10_to_loinc.csv`, `yj_to_atc.csv` | 32; 14; 22 [measured] | demo maps | `jp-demo-maps` | mapping hospital codes at ingest (Japan) |
| adapter `tw_core/lab_local_to_loinc.csv` | 14 [measured] | demo | own | mapping hospital lab codes at ingest (Taiwan) |
| adapter `mimic/tables/*` (ICD-9→10, lab→LOINC, drug→ATC, item→PCS) | 60; 12; 9; 5 [measured] | demo | own | the MIMIC-shaped test adapter |
| `catalogue/codes_checked.csv`, `items.csv`, `phenotype_icd10cm.csv` | 983; 469; 89 [measured] | own, citing LOINC, UCUM, CDISC, ICD-10-CM | `trialbox-catalogue`, `ohdsi-phenotypes` | the catalogue of items and phenotypes |
| `sitesetup/dx_names.csv` | 101 [measured] | own | own | site setup: local diagnosis names → suggestion [read: `sitesetup/mapping.py:1-15`] |
| `orchestrator/scenarios/terms.py` TERMS | 32 entries [read: 05 section 2c; `terms.py:11-44`] | own | own | screening S2: English → zh-TW and ja keywords for notes |
| `tests/fixtures/vocab/athena-test/*` | 19 concepts, 9 relationships [measured] | made-up Athena layout | test | the Athena loader's tests |
| Refdata pack items (TW 6, JP 8) | fetched by the vendor | data.gov.tw, MHLW, NCI, own | `ship` or `site-fetch` per item [read: `refdata_tw.py:418-490`, `refdata_jp.py:626-725`] | maps and synonyms in schema `refdata` |
| EDC CDASH hints | 8 LOINC codes in code [read: `services/edc/cdash.py:181-198`] | own | `loinc` | EDC pre-fill: which record fills a CRF item |

Loaded at install (nothing in git): full LOINC, WHO ICD-10, ATC index, ICD-10-PCS, the NHI lists, the site's own
lists (`installed.py`, D-1113 to D-1116, D-1127) [read]; an Athena bundle into schema `omop` (`vocab_load.py`) [read];
MEDIS 病名, JLAC10 and YJ/HOT masters (`load_licensed`) [read: `vocab_load.py:593`].

Uses outside the compiler [read]: **screening** reads ValueSets the compiler wrote and matches ICD-10 and ATC by
prefix, WHO-only families through the bridge (`resolver.family_systems`); **mapping from hospital codes** is the
adapter's YAML maps and the site's confirmed local codes (`sitesetup/mapping.py`); **EDC pre-fill** matches by system
and prefix, an ICD-10 or ATC prefix of 3 characters at least (`services/edc/prefill.py:141-159`); **units**: UCUM
conversion in `libs/tb_common/labunit.py`, which fails for `IU/L` against `U/L` (01 M17);
**de-identification** uses no code table (no match of `loinc|icd10|atc` in `services/guard`) [measured, grep];
**reports** carry the codes of the ValueSets only.

### 2.2 Every place a model chooses or writes a code

| Call | Where | What the model does with codes | Count in P2b sigir |
| --- | --- | --- | --- |
| `concept_map` (cloud class, prompt v2) | `criteria_compiler/service.py:454-476`; called at `terminology/mapper.py:529-536` | picks codes from up to 20 word-overlap candidates; always for review | **676** calls; 626 empty; 657 for review [measured, row 3] |
| `ir_extract` (v4) | `service.py:850` | drafts concept names, domains and synonyms; told "Never invent codes" [read: `ir_extract_v4.md:11,31`] | 200 calls; 1,727 candidates, 1,501 not demographic [measured, row 4] |
| `chart_facts` (v2, local) | `sitesetup/charts.py:407-429` | writes ICD-10-CM, LOINC and ATC codes "when you are sure", no list [read: `chart_facts_v2.md:13-15`] | not in the launch (site setup) |
| `crf_prefill` (v2) | `services/edc/prefill.py` | picks a CRF choice code, not a terminology code [read: `crf_prefill_v2.md:15`] | not in the launch |
| `judge` (v5) | screening S3 | none: answers a criterion over notes | 369 [read: 01 section 3.2] |

**What the 676 calls were** [measured, row 3]: by domain observation 361, condition 246, procedure 57, encounter 7,
claim 5, medication 0. Candidates per call: median 3, maximum 20. The 50 calls that chose a code chose LOINC 28,
ICD-10-CM 22, department 2, clinical score 1. 607 distinct (domain, name) pairs; 111 calls repeat a name already
asked in the same launch (pregnancy 10 times). Many observation names are not labs at all ("WHO performance status",
"insulin resistance", "critical illness") and several are diagnoses filed as observations or claims ("myocardial
infarction", "bipolar disorder") [measured, row 3].

**Why a gate on the candidate score is not the fix.** Skipping calls whose best name-to-candidate word overlap is
below 0.2 would remove 598 of 676 calls but lose 34 of the 50 codes the model did choose, because many picks came
through the model's synonyms [measured, row 8]. The fix is better candidates and tables, not fewer questions.

---

## 3. Using all of OHDSI

### 3.1 The tables of an Athena download

| Table | What it holds | What TrialBox gets from it | Loaded today? |
| --- | --- | --- | --- |
| CONCEPT | every code of every vocabulary: name, domain, vocabulary, class, standard flag, validity | exact-name resolution in every domain; code validation (chart facts, site lists) | yes, in memory [read: `vocab_load.py:838-851`] |
| CONCEPT_RELATIONSHIP | Maps to, Is a, ATC – RxNorm, RxNorm has ingredient, LOINC parts, ... | Maps-to from source codes (ICD-10-CM, NDC, local) to standard; drug ingredient; panel members | yes, in memory |
| CONCEPT_ANCESTOR | the transitive closure over standard concepts, with min and max levels | descendants for criteria ("any anticoagulant"; "any LOINC in the creatinine group") | yes, in memory |
| CONCEPT_SYNONYM | other names, with a language concept | synonyms for names and for note keywords; any non-English names present | yes, in memory |
| DRUG_STRENGTH | amount, numerator and denominator per ingredient of a clinical drug | dose criteria ("methotrexate above 25 mg a week") | **no** [read: `vocab_load.py:824`] |
| VOCABULARY, DOMAIN, CONCEPT_CLASS, RELATIONSHIP | metadata, versions | the release version and the licence register check | yes |

The book of OHDSI says CONCEPT_ANCESTOR is built from CONCEPT_RELATIONSHIP, that non-standard concepts map to
standard ones by "Maps to", and that releases happen in February and August [source: Book of OHDSI 2nd ed.,
vocabularies chapter]. The current Athena release is **v20260829** [measured, row 9: Athena's public
`release-version` endpoint]. Its release notes name SNOMED 2026-02 international, ICD10CM 2027, ICD10PCS 2027, LOINC
2.82, RxNorm and RxNorm Extension June 2026, NDC 2026-08-23, HPO 2026-06-23, MedDRA 29.0, CPT4 2026AA; the February
2026 release updated ATC (February 2026) and CVX [source: OHDSI/Vocabulary-v5.0 releases].

### 3.2 The vocabularies, their licence class, and what each buys TrialBox

Licence classes: **open** (download and use, notice kept); **register** (free, with an account or an agreement);
**licensed** (proof of a licence before Athena releases it, or a membership); **site-owned** (the hospital's own).
Athena lists 18 vocabularies that need proof of licence, among them CPT4, MedDRA, Medi-Span GPI, First Databank
products, Gemscript, IQVIA sources (GRR, DA_France, LPD_Australia), CDT, ISBT and CAP [source: HL7 THO NamingSystem
OMOP]. "Over 140 vocabularies" are offered [source: Book of OHDSI]. The full current list with each vocabulary's
terms is shown only to a signed-in Athena user [measured, row 9: the list endpoint answers 403]; it is **not
verified** here, and the owner's own download's `VOCABULARY.csv` is the record of what he holds.

| Vocabulary (Athena id) | Licence class | What it buys TrialBox | Priority |
| --- | --- | --- | --- |
| RxNorm, RxNorm Extension | open (NLM terms; OHDSI) [source: NLM RxNorm terms of service] | drug ingredients, clinical drugs, brands; ATC → RxNorm descendants; DRUG_STRENGTH | P1 |
| ATC | open in Athena; WHOCC terms forbid commercial copying and distribution [source: atcddd.fhi.no copyright] | drug classes as ancestors of RxNorm ingredients; "any anticoagulant" | P1 (codes); names wait for WHOCC (decision O-3) |
| LOINC | open (Regenstrief licence, notice) [read: register row `loinc`] | labs: names, components, systems, LOINC groups; 598 of P2b's 1,501 concepts were drafted as observations [measured, row 4] | P1 |
| UCUM | open (notice) [read: register row `ucum`] | unit concepts; checking a criterion's unit | P1 |
| ICD10CM | open (US public domain) | Maps to SNOMED (if licensed); validation of a site's codes; already shipped | P1 |
| ICD10PCS, ICD9CM, ICD9Proc | open (US public domain) | procedure names; old records (Taiwan before 2016) | P2 |
| NDC, SPL | open (FDA) [not verified today] | only for US-sourced data and the MIMIC-shaped tests | P3 |
| CVX | open (CDC) [not verified today] | vaccine criteria | P3 |
| HCPCS | open (CMS) [not verified today] | US-only | P4 |
| ICD10 (WHO), ICD10GM, ICD10CN, KCD7 | WHO copyright for the WHO text [read: register row `icd10-who`]; the national modifications by their owners [not verified] | WHO-coded records (Japan's ICD-10 base); ICD10CN carries simplified-Chinese names [not verified] | P2 site-loaded |
| ICDO3 | WHO/IARC terms [not verified] | oncology topography and morphology for cancer criteria | P2 site-loaded |
| SNOMED | licensed outside member countries; Japan and Taiwan are **not** members [source: snomed.org members list, 54 members, checked 2026-11-17] | the OMOP standard for conditions and procedures: condition hierarchy, Maps-to targets | **only with an affiliate licence** (decision O-2) |
| HemOnc, Cancer Modifier, NAACCR | OHDSI oncology vocabularies [not verified] | regimens, staging (T2-3 Nx M0 in sigir) | P3 |
| HPO | HPO's own licence (free, acknowledgement) [source: HPO licence page via search; current page not opened] | rare-disease phenotypes; note keywords | P3 |
| OMOP Genomic | OHDSI [not verified] | biomarker criteria (EGFR, HER2) | P3 |
| JMDC | in Athena as a source of the ATC–RxNorm mapping [source: search summary only] | Japanese drug codes → RxNorm Extension [not verified] | P2 for Japan, after verification |
| CPT4 | licensed (AMA EULA; names reconstituted with a UMLS key) [source: OHDSI CPT EULA page; Book of OHDSI] | US procedures only | none |
| MedDRA | licensed (subscription) [source: HL7 THO list] | adverse events, not eligibility | none unless AE coding enters scope |
| OMOP metadata (Domain, Visit, Type Concept, Gender, ...) | open | the CDM's own concepts, already stand-ins [read: `omop/vocab.py:1-10`] | P1 |

**What the hierarchy buys, by criterion form** [opinion, from the OMOP model]:

| Criterion | Path through the vocabulary |
| --- | --- |
| "any anticoagulant", "TNF inhibitor" | ATC class (B01A, L04AB) → CONCEPT_ANCESTOR → RxNorm ingredients → (reverse Maps to) NDC, RxNorm Extension, a site's NHI or YJ codes mapped to the ingredient |
| "methotrexate above 25 mg a week" | ingredient → clinical drugs → DRUG_STRENGTH amount and unit → dose per day from the order's frequency |
| "serum creatinine above 1.5 mg/dL" | LOINC component "Creatinine" + system "Ser/Plas" (LOINC parts) → every LOINC code of it, with UCUM unit conversion |
| "history of myocardial infarction" | ICD-10-CM family I21-I22, I25.2 (today); with SNOMED: ICD-10-CM → Maps to SNOMED → descendants → every source code mapped to them |
| a hospital code (NHI drug, local lab) | source concept → Maps to → standard concept, so one criterion matches every hospital |

**Without SNOMED** the conditions keep today's path (ICD-10-CM families and the WHO bridge): in OMOP, ICD-10-CM
codes are non-standard and have no ancestors of their own in CONCEPT_ANCESTOR [opinion, from the OHDSI rule that the
ancestor table covers standard concepts; not verified on the owner's download]. Drugs, labs and units gain fully
without SNOMED.

### 3.3 The loader: one import at install, into one store

| Point | Design [opinion] |
| --- | --- |
| Store | the PostgreSQL schema `omop` that `vocab_load` already writes (D-301 makes it "the one home of the codes") [read: `vocab_load.py:1-3`]. Not Parquet: the ancestor table is too large to hold in the mapper's memory. Not the DuckDB lake: the lake is rebuilt nightly |
| Reading the files | stream each CSV with PostgreSQL `COPY ... FROM STDIN` (the database class already has `copy_rows`) [read: `libs/tb_common/db.py:301-307`], in chunks, never as a Python list; tab-separated, no quoting, as Athena writes it [read: `vocab_load.py:839`] |
| Order | VOCABULARY, DOMAIN, CONCEPT_CLASS, RELATIONSHIP, CONCEPT, CONCEPT_SYNONYM, CONCEPT_RELATIONSHIP, CONCEPT_ANCESTOR, DRUG_STRENGTH; indexes after the copy |
| Indexes | `concept(concept_code, vocabulary_id)`; `concept(lower(concept_name))`; a trigram index on names and synonyms for candidates (`pg_trgm`, a PostgreSQL contrib extension, whether the box's PostgreSQL image carries it: **not verified**); `concept_relationship(concept_id_1, relationship_id)`; `concept_ancestor(ancestor_concept_id)` and `(descendant_concept_id)`; `drug_strength(drug_concept_id)` |
| Allow-list | the licence register, not a constant: a vocabulary loads only when the register has a row for it with status `cleared` or `site-loaded` and, for a licensed one, the manifest names the person who accepted it (D-1114). SNOMED loads only with an affiliate-licence row |
| Size and time | **estimate**, to be replaced by the owner's `wc -l` on his download (T6-4's first step): one user reported the full CONCEPT.csv at about 800 MB [source: OHDSI forum, search summary]; a broad bundle is commonly several GB of CSV, of order 10 million concepts and tens of millions of relationship and ancestor rows [opinion, not verified]. On disk with indexes, PostgreSQL needs roughly 3 to 5 times the CSV size [opinion]. Load on a 4-core box: of order one to a few hours [opinion]. Without RxNorm Extension, NDC and the US-only vocabularies the bundle is much smaller [opinion] |
| Where it runs | `deploy/terminology.sh`'s pattern: the Python image, no network, the staging folder read-only [read: `docs/handover/OFFLINE-MEDIA.md:142-150`] |
| What ships | nothing of Athena: the owner's download is his; the site's IT downloads its own from Athena with its own account and ticks, or the vendor supplies only what the vocabulary's terms let it redistribute (section 7) |

### 3.4 Versioning: a release pinned per approved rule set

The mechanism exists and needs two repairs [read: `vocab_load.py:24-30`, `:60`, `resolver.py:166-211`]:

1. `COMPILE_RELEASES` holds `terminology-parquet`, `ICD10CM`, `LOINC`, `ATC` and **not** `ATHENA` [read:
   `vocab_load.py:60`]: a new Athena bundle does not mark approved rulesets "recompile needed". Add it.
2. A ruleset pinned to an older release is refused until recompiled [read: `resolver.py:187-198`]. With a
   semi-annual release that blocks screening at every site twice a year. Replace the refusal by a **re-check**: on a
   new release, recompile each approved ruleset in the background, diff its ValueSets (codes added, removed,
   renamed), and run on the old release until a person approves the diff; a ruleset with no diff moves by itself,
   with an audit line. The ValueSet records `terminology_release` (the bundle's version and sha256).

### 3.5 How the compiler, the mapper and the screening engine read it

| Reader | Today | With the vocabulary [opinion] |
| --- | --- | --- |
| Mapper, steps 1 to 2e | Parquet tables in memory (`mapper.py:301`) | unchanged first (site lists win, D-1113), then a new step 2f: exact name or synonym in CONCEPT/CONCEPT_SYNONYM, standard concepts of the domain's vocabularies (Condition: ICD10CM; Measurement: LOINC; Drug: RxNorm, ATC; Procedure: ICD10PCS, NHI), not for review when one concept answers |
| Mapper, step 3 candidates | word overlap over the curated rows (`mapper.py:879-892`) | trigram search over the full vocabulary of the domain, top 20, plus the model's synonyms; the model then chooses among real codes |
| Groupers | 186 curated rows | a class (ATC level 3/4, a LOINC group) expands through CONCEPT_ANCESTOR into the ValueSet's concepts; the ValueSet keeps the class as a family (D-113) so an unseen descendant is "unknown" |
| Screening engine | ValueSet codes, prefix families | unchanged: it reads the ValueSet; the expansion is done at compile and pinned (no live vocabulary query at night) |
| Adapter (hospital codes) | YAML maps, site local codes | source concept → Maps to (`omop/vocab.py:14-16` already does this for ATC → RxNorm) [read] |
| Chart facts, site lists | code kept unchecked | a code not in CONCEPT for its vocabulary is dropped to "uncoded" |

### 3.6 A GPU-less box

Everything in this section runs on the CPU: the import, the indexes, the mapper's table steps and the trigram search
[opinion]. On a box without a GPU (the stub) `concept_map` answers nothing, so today 1,297 of P2b's 1,501 concepts
would stay unmapped [measured, row 4: 204 resolved]. With the vocabulary, every concept a table resolves is resolved
the same with or without a GPU; that is the larger part of the gain for a GPU-less site.

### 3.7 A small open subset for the synthetic hospital and the tests

| Point | Design [opinion] |
| --- | --- |
| Content | the concepts the synthetic hospital and the shipped and open-data rulesets use, and their closure (ancestors, Maps-to targets, ingredients, strengths): from RxNorm and RxNorm Extension (public domain or OHDSI open), ICD10CM and ICD10PCS (public domain), UCUM, and the OMOP metadata vocabularies |
| Not in it | LOINC, ATC names and WHO ICD-10 text (D-1028 point 4, D-1116), SNOMED, anything licensed. Labs and ATC classes use made-up codes in a shape no real code takes, marked SYNTHETIC, as D-1128 did (LOINC-shaped from 9900001, ATC group Z) |
| Size | a few thousand concepts, under 2 MB [opinion]; the existing `athena-test` fixture holds 19 [measured] |
| How it is made | a tool (`tools/athena_subset.py`) run by the integrator on a real download, deterministic, writing the subset and its manifest; the never-committed guard checks it has only allowed vocabulary ids |
| Register | a row `athena-open-subset`, status `cleared`, naming the paths |

---

## 4. All other open code systems worth loading

**One table.** Ship = may be redistributed in the signed bundle; site = loaded at install from the site's own copy.
Priority P1 (needed for the five changes) to P4 (only for a scenario not in 1.0).

| System | Publisher | Link | Licence class | Ship or site | Size | Use in TrialBox | Priority |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ICD-10-CM (+ blocks, index, GEMs) | CDC/NCHS, CMS | cdc.gov/nchs/icd | open (US PD) [read: register `icd10cm`] | ship (does) | 98,186 codes [measured] | conditions | P1, done |
| ICD-10-PCS | CMS | cms.gov ICD-10 | open (US PD) [read: register `icd10pcs-full`] | ship allowed (D-1029), not yet | of order 79,000 codes [not verified] | procedures by name | P2 |
| WHO ICD-10 | WHO | icd.who.int/browse10 | permission for commercial text [read: register `icd10-who`] | site | – | Japan's base classification; WHO-only categories | P2 |
| WHO ICD-11 (MMS) | WHO | icd.who.int | CC BY-ND 3.0 IGO; incorporation in software "is not an adaptation"; code, title and URI kept; translations need a separate agreement [source: ICD-11 licence PDF] | ship possible under those terms [opinion] | – | not used by Taiwan or Japan claims yet [opinion]; future-proofing only | P4 |
| ICD-O-3 | WHO/IARC | – | not verified | site | – | cancer morphology | P3 |
| ATC (codes) / ATC/DDD index (names, DDD) | WHOCC Oslo | atcddd.fhi.no | "Copying and distribution for commercial purposes is not allowed"; attribution required [source: WHOCC copyright page]; electronic index in Excel/XML through a registered order account [source: WHOCC index page]; price not shown [measured, row 10] | codes as identifiers (today's practice, ask WHOCC: TB-LIC-02); names site | ~6,000 codes [not verified] | drug classes | P1 codes, names by decision O-3 |
| LOINC (+ linguistic variants) | Regenstrief | loinc.org | open, notice [read: register `loinc`]; 22 languages, Arabic and Czech new in 2.81 [source: Regenstrief release article via search]; a zh-CN variant exists [source: UMLS LNC-ZH-CN metadata]; **no Japanese variant found** [source: search; not verified on the download's `LinguisticVariants.csv`] | site (D-1028 point 4) | of order 100,000 terms [not verified] | labs | P1 |
| UCUM | Regenstrief/UCUM Org | ucum.org | open, notice [read: register `ucum`] | ship (in the CQL jar) | – | units | P1 |
| RxNorm | NLM | nlm.nih.gov/research/umls/rxnorm | NLM names and RXCUIs public domain; full release needs a free UMLS licence; acknowledge NLM [source: RxNorm terms] | site (from Athena); the open subset may ship (section 3.7) | – | drugs, ingredients, strengths | P1 |
| SNOMED CT | SNOMED International | snomed.org | licensed; JP and TW not members [source] | site, only with an affiliate licence | – | condition hierarchy | O-2 |
| SNOMED Global Patient Set | SNOMED International | docs.snomed.org GPS guide | "permissively licensed", usable in non-member countries; **without** hierarchies and logical definitions [source: GPS guide; search summary says CC BY 4.0, not verified on the English page] | ship possible [opinion] | all active concepts, no hierarchy | display names only; does not give descendants | P4 |
| HPO | Monarch / JAX | hpo.jax.org | free, acknowledgement, no modification [source: older licence page via search] | ship possible [opinion] | – | rare-disease phenotypes | P3 |
| ORPHAcodes | Orphanet | orphadata.com | CC BY 4.0 [source] | ship | – | rare diseases | P3 |
| MONDO | Monarch | – | not verified | – | – | disease ontology bridge | P4 |
| OncoTree | MSKCC | – | not verified | – | – | tumour types | P3 |
| NCIt | NCI EVS | evs.nci.nih.gov | CC BY 4.0; name "NCI Thesaurus" trademarked [source] | ship | – | oncology terms; hosts CDISC CT | P3 |
| CTCAE v5 | NCI | ctep.cancer.gov | US PD [read: register `ctcae`] | ship (samples do) | – | toxicity grades in criteria ("grade ≥ 2 neuropathy") | P2 |
| CDISC CT | CDISC, via NCI EVS | cdisc.org | distributed with NCIt, quarterly [source]; licence terms not stated on the page [not verified] | ship of the codelists the EDC uses [read: `edc/cdash.py:13-15`] | – | EDC DS/IE values | P2 |
| MeSH | NLM | – | not verified | – | – | literature terms; synonyms | P4 |
| UMLS | NLM | – | free licence agreement with source restrictions [source: RxNorm terms page mentions section 12] | site, never ship | – | not needed if Athena is loaded [opinion] | none |
| CVX | CDC | – | not verified | site via Athena | – | vaccines | P3 |
| HGNC | HGNC | – | not verified | – | – | gene names for biomarker criteria | P3 |
| ChEBI | EMBL-EBI | – | not verified | – | – | chemistry; not needed | none |
| DrugBank open data | DrugBank | – | not verified | – | – | synonyms; RxNorm covers it [opinion] | none |
| EDQM Standard Terms | EDQM | standardterms.edqm.eu | free with registration; 35 languages incl. Chinese, not Japanese; redistribution terms not stated [source] | site | – | dose forms, routes | P3 |
| NDC | FDA | – | not verified | site via Athena | – | US data only | P3 |
| UNII/GSRS | FDA | – | not verified | – | – | substance identity | P4 |
| MedDRA | ICH/MSSO, JMO | meddra.org | subscription [source: HL7 THO list]; rates page not readable [measured, row 10] | site | – | adverse events, not eligibility | none (O-6) |
| WHODrug | Uppsala Monitoring Centre | – | subscription [not verified] | site | – | concomitant medication coding | none (O-6) |

**Taiwan**

| System | Publisher and link | Licence | Ship or site | Size | Use | Priority |
| --- | --- | --- | --- | --- | --- | --- |
| NHI drug list 健保用藥品項 (with ATC column) | NHIA, data.gov.tw 23715 | OGDL 1.0 [read: D-1127, verified online 2026-11-17] | ship (D-1028 point 3) | 45,224 codes [read: D-1127] | drug code → ATC → RxNorm | P1 |
| NHI service and order codes 醫療服務給付項目 | NHIA, data.gov.tw 174450 | OGDL 1.0 [read: D-1127] | ship | 6,175 codes [read: D-1127] | procedures | P1 |
| NHI Chinese herbal medicine codes 中藥用藥品項 | NHIA; TW Core CodeSystem `nhi-medication-ch-herb-tw` "partial set" [source: TW Core 1.0.0 artifacts] | OGDL [not verified] | ship | – | TCM criteria | P3 |
| ICD-10-CM/PCS Chinese editions 2014 and 2023, and their map | NHIA, data.gov.tw 177508 | OGDL 1.0 [read: register `icd10cm-tw`] | ship | – | read records by year; the map is unused in the nightly path (plan 9 9b-7) | P1 |
| TW Core code systems | MOHW, TW Core IG 1.0.0 (2025-12-10) | CC0/OGDL [not verified per system] | ship (package) | 2014 and 2023 ICD-10-CM, NHI drugs, routes, frequency, TFDA licences, ATC (`medcation-atc-tw`), service payment items [source] | FHIR output and validation | P2 |
| NHI lab order → LOINC | NHIA PAS IG ConceptMap `nhi-loinc` (1.3.0) | CC0 [read: register `twpas-ig`] | ship | – | hospital lab codes → LOINC | P1 |
| NAER medical terms en ↔ zh-TW | NAER, data.gov.tw 15460 | OGDL [read: register `tw-open-data-samples`] | ship | – | zh-TW names for every English concept name; note keywords | P1 |

**Japan**

| System | Publisher | Licence | Ship or site | Use | Priority |
| --- | --- | --- | --- | --- | --- |
| MEDIS ICD-10対応標準病名マスター | MEDIS-DC | free for medical institutions; others apply (使用申請) [source: search summary of a MEDIS 規格票, dental master; not verified for the disease master] | site [read: register `jp-licensed-masters`] | disease names → ICD-10 | P1 for Japan |
| MEDIS HOT code master (医薬品) | MEDIS-DC | as above [not verified] | site | drug codes → YJ, receipt codes | P1 for Japan |
| JLAC10 / JLAC11 臨床検査 | JSLM / MEDIS | not verified | site [read: register `jp-licensed-masters`] | lab codes → LOINC (no public map found) | P1 for Japan |
| YJ codes, 薬価基準収載品目リスト | MHLW | PDL 1.0 [read: register `mhlw-yakka`] | ship | drug stems → ATC (T-610) | P1 |
| レセプト電算 masters (傷病名, 医薬品, 診療行為 incl. K codes, 特定器材) | MHLW / 診療報酬情報提供サービス | site copyright; modification without permission prohibited; no licence for reuse stated [source: shinryohoshu FAQ] | site | receipt-coded records; procedure K codes | P2 |
| JP Core code systems | JAMI/HL7 Japan, jp-core.r4 1.1.0 [read: 01 M12] | not verified | ship (package) | FHIR validation | P2 |
| MANBYO (万病辞書) | NAIST Sociocom | CC BY 4.0 [source]; latest MANBYO_202106; each entry with an ICD-10 code from the MEDIS master V4.04 [source] | ship | Japanese disease names in notes → ICD-10; note keywords | P1 for Japan notes |
| CTCAE v5.0 JCOG Japanese | JCOG | site-fetch [read: `refdata_jp.py:690-700`] | site | toxicity terms in Japanese | P2 |

**Maps between systems** (who publishes, terms):

| Map | Publisher | Terms | Ship? |
| --- | --- | --- | --- |
| ICD-10-CM → SNOMED; NDC → RxNorm; ATC → RxNorm; LOINC parts | OHDSI, in Athena | as the vocabularies they join [source: Book of OHDSI] | site |
| ICD-9-CM ↔ ICD-10-CM (GEMs) | CMS | US PD [read: register `icd10cm`] | ship |
| Taiwan ICD-10-CM 2014 ↔ 2023 | NHIA | OGDL [read] | ship |
| NHI drug → ATC | NHIA (in the drug list) | OGDL [read] | ship |
| NHI lab → LOINC | NHIA PAS IG | CC0 [read] | ship |
| MEDIS 病名 → ICD-10 | MEDIS | MEDIS terms [read] | site |
| JLAC10 → LOINC | none public found; the hospital's own [read: `refdata_jp.py:675-685`] | – | site |
| YJ → ATC | TrialBox own stems (56) [measured]; JMDC in Athena [not verified] | own | ship |
| WHO ICD-10 ↔ ICD-10-CM | TrialBox own category bridge (36 checked) [measured] | own | ship |
| MANBYO → ICD-10 | NAIST | CC BY 4.0 [source] | ship |

---

## 5. What moves from the model to a table

Expected effects are **opinions** derived from the measured breakdown; the proof is the replay of section 5.2.

| Call or gap | Today [measured] | Which system answers | Expected effect [opinion] |
| --- | --- | --- | --- |
| `concept_map`, observation (361 calls, 332 empty) | candidates from 27 LOINC rows and clinical scores | LOINC (names, components, LOINC groups) + the site's lab list + NHI lab → LOINC | lab names ("platelet count", "hemoglobin", "serum creatinine", "AST", "TSH") resolve by table; non-lab states stay with the model or move to `human`; calls fall by about half, non-labs remain |
| `concept_map`, condition (246, 227 empty) | candidates from 79 curated rows | full ICD-10-CM descriptions, index and blocks as candidates (already shipped); WHO ICD-10, MEDIS and MANBYO names at a site | the model now chooses among real codes; empty answers fall sharply; calls fall little until synonyms grow |
| `concept_map`, procedure (57, 57 empty) | 4 NHI order rows | ICD-10-PCS, NHI service list, ICD-9-Proc (via Athena) | answers become possible; NHI items stay "for review" (D-1127 point 10) |
| encounter, claim (12) | departments, NHI drugs | none: a domain error of `ir_extract` ("bipolar disorder" as a claim) | re-file by domain before mapping (T6-9) |
| medication (200 concepts, 0 calls, 4 resolved) | 33 ATC rows | RxNorm ingredient names and synonyms, ATC classes, NHI drug ingredients, YJ stems | the largest gain: most ingredient names ("acetazolamide", "amoxicillin") and classes ("anticoagulants", "ARB") resolve by table |
| 356 structured or mixed criteria with an unmapped concept | coded check matches nothing | the above | their coded check becomes real; a share of the 293 mixed criteria no longer need notes |
| 497 human criteria | 60 with an unmapped concept | the above | at most those 60 move; the other 437 are logic or the model's choice (root review 01 and plan 9 9c-*) |
| `chart_facts` codes | unchecked | CONCEPT validation | a code not in the vocabulary is dropped; no model change |

### 5.2 The measurement that proves it

1. **Replay without a model** (exists in part). `python -m tools.terminology_coverage <raw-traces.json> --installed
   DIR` counts concepts resolved by table [read: `tools/terminology_coverage.py:1-20`]; on P2b sigir it gives
   **204 of 1,501** today (condition 190, observation 10, medication 4, procedure 0) [measured, row 4]. Card T6-2 adds
   `--model-calls`: the same map with a recording stand-in for the model, counting calls by domain. This session's
   prototype gives **316 calls without the model's synonyms and 718 with them** against the launch's real 676
   [measured, row 7]; the difference is the newer master and repeated names.
2. **Acceptance for T6-1 to T6-7**, on P2b sigir and P1b (`tests/fixtures/terminology/p1b_concepts.csv`, CI): concepts
   resolved by table, by domain; model-step calls; concepts with an empty answer; criteria with `concept_unmapped`
   after re-running the compiler's post-processing on the stored `ir_extract` outputs (no model: T6-2's second mode).
   Plan 9's C-5 already asks for the first two.
3. **On the synthetic hospital**: the compiled rulesets' ValueSets before and after (`tools/build_rulesets.py
   --check` shows the diff), and screening results unchanged except where a ValueSet grew; any change is listed.
4. **One GPU launch** only after 1 to 3 (plan 9 V23 rules): the real `concept_map` count and the class mix.

## 6. The note side: synonyms and abbreviations per language

Today S2 uses an approved lexicon or 32 shipped English terms with zh-TW and ja forms [read:
`orchestrator/scenarios/terms.py:11-44`]; negation and family contexts are regular expressions in two places
[read: `services/matching/inferred.py:105`; `services/sitesetup/charts.py:198`].

| Source | Languages | What it adds [opinion] |
| --- | --- | --- |
| CONCEPT_SYNONYM (Athena) | mostly English; non-English share unknown | English synonyms of every resolved concept; the count per language is one query on the owner's download (`SELECT language_concept_id, count(*) FROM concept_synonym GROUP BY 1`) [not verified] |
| NAER terms | en ↔ zh-TW | a zh-TW name for most English clinical terms |
| MANBYO | ja | variant Japanese disease names written by clinicians, each with ICD-10 |
| LOINC zh-CN variant | zh-CN (simplified) | lab names, converted to traditional characters for Taiwan; Japan has none |
| The NHI lists (Chinese names), the YJ list (Japanese names) | zh-TW, ja | drug names as written in orders |
| TrialBox curated (42 zh-TW, 70 ja) | zh-TW, ja | abbreviations (GPT for ALT), ambiguous items, always reviewed |

Each generated term carries the concept it came from, its language, and an **avoid context** list in the same
language: negation (no, denies, 無, 否認, なし, 認めない), family (family history, 家族史, 家族歴), history only (history of,
既往, 既往歴), risk and drug-for (高血圧リスク, 糖尿病薬) [read: `inferred.py:1-12`]. This is plan 9's 9c-3; this review
gives it its content and asks that a generated term be shown to the study's approver before use, as the lexicon is
today [opinion].

## 7. Governance

| Point | Rule [opinion unless marked] |
| --- | --- |
| One register | `docs/licences/register.csv` stays the only register [read: D-342]; the Athena allow-list, the installed loader and the refdata pack read it instead of their own constants (`ATHENA_ALLOW`, `SHIPPABLE`, the pack's `distribution`) |
| Ship versus site | ships: ICD-10-CM/PCS, GEMs, NHI open data, Taiwan edition map, NHI lab → LOINC, NAER, TW Core and JP Core packages, YJ list, MANBYO, CTCAE English, ORPHAcodes, NCIt, the open Athena subset of section 3.7, TrialBox's own tables. Site: LOINC, ATC index, WHO ICD-10, MEDIS masters, JLAC, receipt masters, the Athena bundle, SNOMED (only with a licence), MedDRA, WHODrug, the site's own lists |
| Attribution | NOTICE gains rows for every shipped one (OGDL statements, CC BY credits, NLM, Regenstrief); a loaded one shows its notice in the console's notices page from its manifest line [read: `services/console/templates/notices.html` exists] |
| Update procedure | the site's IT downloads from Athena with the site's account, ticks only the vocabularies the register clears for that site, stages the zip, runs one command; the box loads, re-checks rulesets (section 3.4), and the doctor names the release |
| What a hospital's IT does | holds an Athena account; accepts each licence by name; keeps the download beside the box's media; on a new release repeats the load; for MEDIS and LOINC, keeps the publisher's acceptance record |
| Intended use and validation | the validation record names, per approved ruleset, the vocabulary release (Athena version, sha256) and each loaded table's manifest line; a new release is a change that needs the ValueSet diff approved (D-301's re-check), not a revalidation of the product; the intended-use statement says codes come from the loaded release and a person approves every ValueSet |

## 8. Cards

| Card | What | Lane guess | Size | Waits for | Proof |
| --- | --- | --- | --- | --- | --- |
| T6-1 | Model-step candidates from the full shipped ICD-10-CM (descriptions, index) and, when loaded, LOINC, ICD-10-PCS and the NHI lists; a candidate index built once at load | A2 | M | – | replay: empty `concept_map` answers on P2b fall from 626; model calls by domain |
| T6-2 | `tools.terminology_coverage --model-calls` and a second mode that re-runs the compiler's post-processing on stored `ir_extract` outputs (no model), counting `concept_unmapped` criteria | H | S | – | reproduces 676 ± 10 % on P2b sigir and the 416 `concept_unmapped` |
| T6-3 | Medications: a name resolves through RxNorm ingredient names and synonyms, ATC class names, NHI 成分 and YJ ingredients; the candidate list is never empty for want of a table | A2 | M | T6-4 for RxNorm | medication concepts resolved on P2b from 4 of 200 |
| T6-4 | Athena import by streaming COPY into schema `omop`, all nine tables with DRUG_STRENGTH, indexes after copy, sizes and times written into the box's doctor; first step: `wc -l` of the owner's download into the measurement file | E | L | O-1 | a full download loads on a 4-core box; rows per table; time; disk |
| T6-5 | The allow-list is the licence register; a licensed vocabulary needs its row and its acceptor; SNOMED refused without an affiliate row | E | S | O-1, O-2 | test per vocabulary class |
| T6-6 | The compiler's step 2f reads CONCEPT and CONCEPT_SYNONYM; groupers expand by CONCEPT_ANCESTOR at compile; the ValueSet keeps the class as a family | A2 | L | T6-4 | P2b and P1b resolved by domain; goldens diff listed and approved |
| T6-7 | Maps-to in the adapter for every source vocabulary loaded (ICD-10-CM, NDC, NHI via ATC, local codes) | B2 | M | T6-4 | share of records with a standard concept on the synthetic sites |
| T6-8 | Dose criteria through DRUG_STRENGTH and the order's frequency | A2 | M | T6-4 | a test ruleset with three dose criteria on the synthetic hospital |
| T6-9 | Re-file a concept by domain before mapping (a diagnosis drafted as observation, claim or encounter) | A2 | S | – | the 12 encounter and claim calls and the misfiled observations of P2b |
| T6-10 | `ATHENA` in `COMPILE_RELEASES`; a new release re-checks each approved ruleset by ValueSet diff instead of refusing it | E | M | T6-4 | test: a new release lists diffs; an unchanged ruleset moves alone |
| T6-11 | One store and one procedure: the installed Parquet loader and the refdata pack's code items write into schema `omop`; `trialbox doctor` shows one terminology line | E | L | T6-4 | the three registers become one; the install guide has one step |
| T6-12 | `chart_facts` codes checked against the loaded vocabulary; an unknown code is dropped | B2 | S | – | test with a made-up code |
| T6-13 | The open Athena subset in the repository (section 3.7), built by a tool from a real download | E | M | T6-4, O-1 | the synthetic hospital compiles and screens on it; the guard passes |
| T6-14 | Ship the NHI lists, ICD-10-PCS, NAER and MANBYO as built tables with manifest lines (D-1127's path) | E | M | the integrator's fetch | `nhi-check` style check per table |
| T6-15 | Note keywords generated from the loaded names in three languages with avoid contexts (content for plan 9's 9c-3) | A2 | M | T6-6 | S2 recall and precision per language on the synthetic gold |
| T6-16 | Licence register rows for every system of section 4 that is used, with NOTICE lines | H | S | O-3 to O-5 | `tools/licence_register.py` passes |

Count: 3 L (T6-4, T6-6, T6-11), 8 M, 5 S. Order: T6-2 and T6-1 first (no new data), then T6-4, then the rest.

## 9. Decisions only the owner can make

**O-1. Which vocabularies does your Athena download hold, and which do you want supported?** Please answer from the
download's `VOCABULARY.csv` (one line per vocabulary with its version), and for each licensed one say on what
licence you hold it:
(a) SNOMED: do you hold a SNOMED CT affiliate licence, or did you tick it as a user in a member country?
(b) CPT4 (AMA EULA), MedDRA (MSSO or JMO subscription), and any of the 18 restricted vocabularies.
(c) Is the download for your own use, or may the box's install procedure tell a hospital to use the same set?
*Recommendation:* support RxNorm, RxNorm Extension, ATC, LOINC, UCUM, ICD10CM, ICD10PCS, ICD9CM, ICD10 (site),
ICDO3 (site) and the OMOP metadata for 1.0; everything else on request. Each site downloads its own copy.

**O-2. SNOMED for Taiwan and Japan sites.** Neither country is a member [source]. Options: (a) no SNOMED in 1.0,
conditions stay on ICD-10-CM families (today); (b) send the inquiry `docs/plan/snomed-inquiry.md` and decide on the
quote; (c) the Global Patient Set for names only (no hierarchy, so little gain). *Recommendation:* (a) for 1.0 and
send (b) now; nothing in sections 5 and 8 needs SNOMED.

**O-3. ATC names: buy the electronic index and ask WHOCC?** The WHOCC terms forbid commercial copying and
distribution [source]. Options: (a) codes only, names from NHI and MHLW lists (today); (b) send TB-LIC-02 and buy the
index for each release; (c) each site buys its own copy. *Recommendation:* (a) now, send TB-LIC-02; with Athena's ATC
(open in Athena's terms) the class names are on the box at site load anyway, so the purchase matters only for
shipping names.

**O-4. MEDIS masters and the receipt masters for the Japan site.** Ask the Japan hospital to apply for MEDIS use
(as a medical institution it is free [source: search summary, not verified]) and to load its own copy.
*Recommendation:* yes; TrialBox never ships them.

**O-5. May a small LOINC subset (the codes the synthetic hospital uses, under 500) be committed with LOINC's
notice?** D-1028 point 4 says no today. *Recommendation:* keep no, use made-up LOINC-shaped codes (D-1128).

**O-6. Adverse-event coding (MedDRA, WHODrug).** Out of scope for eligibility. *Recommendation:* stay out of 1.0.

## 10. Measurement log

Every command ran from the worktree's `trialbox/` or in `/var/tmp/trialbox-0/b6/`; the scripts are kept there.
The archive `sigir.tgz` comes from `git show origin/integrator/p2b-artefacts:trialbox/.p2b-artefacts/sigir.tgz`
(sha256 `1e13cf7a...`; `raw-traces.json` sha256 `98045336...`), unpacked into an empty scratch folder, read as data.

| # | Command | Number |
| --- | --- | --- |
| 1 | `wc -l` and `zcat \| wc -l` on `services/criteria_compiler/terminology/src/*` | atc 33, department 9, blocks 280, icd10cm_tw 79, loinc_tw 27, nhi_drug 24, nhi_order 4, synonyms 186, icd10cm 98,186, index 28,792 |
| 2 | `wc -l` on `libs/tb_common/refdata_src/*`, `services/adapter/mapping/*/*.csv`, `catalogue/*.csv`, `tests/fixtures/vocab/athena-test/*` | as in section 2.1 |
| 3 | `python3 -I cm2.py sigir/work/raw-traces.json` (each `concept_map@*` call: input JSON, output choices) | 676 calls: observation 361, condition 246, procedure 57, encounter 7, claim 5; empty 626; for review 657; median 3 candidates; chosen 50 |
| 4 | `PYTHONPATH=libs:services:. python -m tools.terminology_coverage sigir/work/raw-traces.json` | 200 calls, 1,727 candidates; 1,501 not demographic; resolved 204 (condition 190 of 477, observation 10 of 598, medication 4 of 200, procedure 0 of 143, encounter 0 of 58, claim 0 of 25) |
| 5 | (01's M 5) Parquet row counts | as row 1 |
| 6 | `python3 -I ans.py sigir/work/answers.json` and a flag cross-tab | 1,165 criteria: human 497, mixed 293, structured 282, note 93; `concept_unmapped` 416; human with it 60; human with `logic_invalid` 197; structured 113 and mixed 243 with an unmapped concept |
| 7 | `python reach.py sigir/work/raw-traces.json` (`Terminology.map` with a stand-in model that records calls) | 316 calls without synonyms (observation 164, condition 147, procedure 5); 718 with synonyms (observation 386, condition 254, procedure 59, encounter 14, claim 5); medication 0 |
| 8 | `python3 -I gate.py sigir/work/raw-traces.json` (best word overlap of name and candidates) | at 0.2: 78 calls kept, 34 of 50 picks lost; at 0.25: 43 kept, 39 lost |
| 9 | `curl https://athena.ohdsi.org/api/v1/vocabularies/release-version`; `.../vocabularies/list` | `{"vocabularyVersion":"v20260829"}`; list: HTTP 403 |
| 10 | WebFetch of `orders.atcddd.fhi.no/home` and `meddra.org/subscription/subscription-rate` | both render no content without a script: price not read |

## 11. Sources opened (2026-11-17)

- Athena release version endpoint: https://athena.ohdsi.org/api/v1/vocabularies/release-version
- OHDSI vocabulary releases: https://github.com/OHDSI/Vocabulary-v5.0/releases
- Book of OHDSI, 2nd ed., vocabularies: https://ohdsi.github.io/BookOfOhdsi-2ndEdition/representation/vocabularies.html
- HL7 THO, OMOP naming system (restricted vocabularies): https://build.fhir.org/ig/HL7/UTG/en/NamingSystem-OMOP.html
- SNOMED International members: https://www.snomed.org/members
- SNOMED GPS guide: https://docs.snomed.org/implementation-guides/gps-implementation-guide/introduction
- WHOCC ATC/DDD index page and copyright: https://atcddd.fhi.no/atc_ddd_index_and_guidelines/ ,
  https://atcddd.fhi.no/copyright_disclaimer/
- ICD-11 licence: https://icd.who.int/en/docs/icd11-license.pdf
- RxNorm terms of service: https://www.nlm.nih.gov/research/umls/rxnorm/docs/termsofservice.html
- NCI Thesaurus terms: https://evs.nci.nih.gov/ftp1/NCI_Thesaurus/ThesaurusTermsofUse.htm
- CDISC controlled terminology: https://www.cdisc.org/standards/terminology/controlled-terminology
- Orphadata: https://www.orphadata.com/
- EDQM Standard Terms: https://standardterms.edqm.eu/
- MANBYO: https://sociocom.naist.jp/manbyou-dic/
- 診療報酬情報提供サービス FAQ: https://shinryohoshu.mhlw.go.jp/shinryohoshu/faq/
- TW Core IG 1.0.0 artifacts: https://twcore.mohw.gov.tw/ig/twcore/artifacts.html
- Search summaries only (not opened at the publisher): LOINC linguistic variants and the UMLS LNC-ZH-CN record; HPO
  licence; MEDIS 使用申請; OHDSI forum on CONCEPT.csv size; JMDC in Athena.

## 12. What this document did not verify

- The full list of Athena vocabularies and each one's licence flag: the list needs a signed-in account (row 9).
- The sizes of a full Athena download, its PostgreSQL size with indexes and its load time on a box: estimates only;
  T6-4's first step measures them on the owner's download.
- Whether ICD-10-CM concepts have ancestor rows in the owner's download, and the share of non-English synonyms.
- The ATC/DDD index price (plan 9 cites about €200 from a search summary) and MedDRA rates: the order pages need a
  script to render.
- LOINC's current terms and its list of linguistic variants (loinc.org answered 403); a Japanese variant is not
  known to exist.
- The current HPO licence page; the English GPS licence statement; MEDIS terms for the disease master; the receipt
  masters' reuse terms; JP Core and TW Core per-system licences; ICD-10-PCS, ATC and LOINC code counts; licences of
  ICD-O-3, MONDO, OncoTree, MeSH, CVX, HGNC, ChEBI, DrugBank, NDC, UNII, WHODrug.
- Whether the box's PostgreSQL image carries `pg_trgm`.
- Any effect of the cards on a GPU launch: every expected effect in section 5 is an opinion until T6-2's replay runs.
- No lawyer read any licence.
