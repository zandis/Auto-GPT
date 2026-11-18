# Root review 22: the vocabularies the owner holds, and what each may be used for (lane J, B-24, 2026-11-18)

**Reader:** the owner (a clinician) first, then the builders of Track H.

**Input.** The owner supplied the vocabulary table (`VOCABULARY.csv`) of his OHDSI Athena download: 130 rows
(id, name, reference, version, concept id). It is committed unchanged as
`docs/licences/owner-athena-vocabularies-2026-11-18.tsv` (sha256 `7717965b…bae33b`) [measured: `sha256sum`, `wc -l` 131
lines], beside the licence register (`docs/data` was the asked place, but the documentation linter allows only
`NN-<slug>.md` pages there [measured: `tools/doclint.py`; read: `tools/doclint.py:243-245`]). It holds no patient data
and no secret. The download itself (about 910 MB) stays in the owner's own cloud drive
and never enters the repository or the bundle (decision 23, closed) [read: `origin/agent/B18-plan-10`
`47-plan-10-2026-11-18.md`, Track H row 9h-4].

**Builds on, does not repeat:** review 06 (cards T6-1 to T6-16, decisions O-1 to O-6; its section 3.2 and 4 licence
tables), review 11 section 4 (Japanese masters), review 20 (licence-label defects, card 20-2), plan 10 Track H (9h-1 to
9h-15, 10H-1) and the grade the owner chose, "E plus fourteen O" (decision 123).

**Marks:** **[measured]** a command was run here; **[read]** file and line (paths under `trialbox/`, master
`a4aa0be15`); **[source]** opened at the publisher on 2026-11-18 (section 8); **[opinion]**; **[not verified]**.
Nothing here is legal advice.

---

## 1. For the owner, in one page

1. **Your list answers review 06's first question (O-1).** It holds the vocabularies that matter for finding patients
   at a US site and most of what matters internationally: RxNorm and RxNorm Extension, ATC, LOINC, UCUM, ICD-10-CM,
   ICD-10-PCS, ICD-9-CM, WHO ICD-10, ICD-O-3, SNOMED, NCIt, HemOnc, the OMOP structural vocabularies [measured: the
   table]. It is one release old: the OMOP row says `v5.0 27-AUG-25`; Athena's current release is `v20260829`
   [measured: the TSV's `None` row; Athena's public `release-version` endpoint].
2. **Today's loader would refuse your download whole.** It accepts 25 named vocabularies and refuses a bundle holding
   any other; 106 of your 130 are not on its list [measured: script over `services/omop/vocab_load.py:801-805` and the
   TSV; read: refusal at `:905-908`]. Card 22-2 makes it filter by the licence register instead of refusing.
3. **Of the 130, 33 matter at one or more of the three kinds of site and 11 more "maybe"; the other 86 are other
   countries' codes, US billing codes, knowledge bases or retired OMOP types** (section 2) [opinion, per row;
   counted by script, section 7 row 7].
4. **What may ship in the bundle, and what may not.** Open (class a): RxNorm, RxNorm Extension, ICD-10-PCS, ICD-9-CM,
   NDC, CVX and the OMOP vocabularies. With terms (class b): LOINC, UCUM (no modification: a UCUM *subset* is a
   modification), NCIt. Never (class c): SNOMED, CPT4, HemOnc, ATC names, WHO ICD-10 text, ICD-O-3, MedDRA's SMQ,
   EORTC, the proprietary drug files. Each site loads class (c) under its own licence [source: section 8].
5. **One surprise worth a short check:** the UMLS licence lists ICD-10-CM as restricted (category 3) for users
   *outside* the US, because it is made "under authorization by the World Health Organization" [source: UMLS appendix];
   the repository ships it as "U.S. public domain" [read: `docs/licences/register.csv:4`]. That label holds for the
   CDC files in the US; whether a vendor may ship them to Japan or Taiwan is **not verified** (card 22-7).
6. **Your download does not contain what the first site needs most.** It has one Japanese code set (JMDC drug codes)
   and no Japanese disease master, drug master (HOT/YJ), laboratory code (JLAC10/11) or procedure code (K codes); no
   Taiwanese code set; no MedDRA (only its SMQ queries, useless alone) and no CTCAE (section 3) [measured: the table].
   Those come from MEDIS, MHLW, NHIA and the site, as reviews 06 and 11 planned.
7. **Smallest useful step under your grade:** build, on the build machine, an RxNorm ingredient-and-synonym candidate
   table and an open subset from classes (a) and (d); feed it to the mapper's candidates (T6-1, T6-3). Review 06
   measured 4 of 200 medicine concepts resolved and 626 of 676 model answers choosing no code; this attacks both
   (section 4) [read: 06 §1].
8. **Cost:** nothing to buy. Eight cards: 4 S, 3 M, 1 L, most folded into existing Track H ids (section 5)
   [opinion].

---

## 2. The table, classified

**Columns.** *What*: five words. *JP TW US*: matters for patient finding at a Japanese first site, a Taiwanese site, a
US site (Y yes, M maybe, N no). *Class* for a commercial on-premises product in an offline bundle: **a** open, may
ship; **b** free with terms, may ship if the terms are met; **c** a licence the user or vendor must hold, may NOT ship;
**d** OMOP-generated structural, part of the OMOP distribution (OHDSI's vocabulary repository is under the Unlicense
[source 3]). *Evidence*: a source number from section 8, or "ref" (the table's own reference column, publisher page
**not opened**).

### 2.1 The 47 that matter, may matter, or needed a licence check (publisher pages opened, section 8)

| Id | What | JP TW US | Why | Class | Evidence |
| --- | --- | --- | --- | --- | --- |
| RxNorm | US normalised clinical drug names | Y Y Y | Ingredient hub for every drug criterion | a; credit NLM | [5] |
| RxNorm Extension | OHDSI drugs outside US market | Y Y Y | Non-US products, JMDC targets | a (OMOP-generated, open) | [2], [3] |
| ATC | WHO drug class hierarchy | Y Y Y | "Any anticoagulant"; NHI lists carry ATC | c for names and the index; codes as identifiers open question (TB-LIC-02) | [8] |
| LOINC | Laboratory and observation codes | Y Y Y | Labs; no JLAC map exists | b: notice, version, no change; repository rule keeps it site-loaded (D-1028) | [6] (licence page 403) |
| UCUM | Units of measure | Y Y Y | Lab thresholds, conversion | b: notice; no add/delete/modify | [10] |
| ICD10CM | US diagnosis modification | M Y Y | Taiwan codes in it; US claims | a in the US; outside US: UMLS category 3 | [6], [13]; card 22-7 |
| ICD10 | WHO diagnosis classification | Y M M | Japan's base classification | c: WHO text needs permission | [6], [12]; register row `icd10-who` |
| ICD10PCS | US inpatient procedure codes | N Y Y | Taiwan inpatient procedures | a (UMLS: no restriction line) | [6], [13] |
| ICD9CM | Old US diagnosis codes | N Y Y | Taiwan records before 2016 | a (UMLS: no restriction line) | [6] |
| ICD9Proc | Old US procedure codes | N Y M | Taiwan records before 2016 | a | [6] |
| ICDO3 | Cancer topography and morphology | Y Y Y | Cancer registry; histology criteria | c: WHO/IARC copyright; SEER page states no terms | [17] |
| SNOMED | Clinical terms, OMOP standard | M M Y | Condition hierarchy; JP, TW non-members | c: affiliate licence; fees in non-member territories | [7], [1] |
| NCIt | NCI oncology thesaurus | M M M | Oncology terms, CDISC host | b: UMLS no restriction ("subset only"); terms page did not render | [6], [19] |
| HemOnc | Chemotherapy regimens and drugs | M M M | Regimen criteria | c: Athena terms forbid use in a "Data Creation System" for patient care; sharing only with the licence | [1] |
| Cancer Modifier | OMOP staging and grade | M M M | TNM and stage criteria | d | ref |
| OMOP Genomic | Known disease variants | M M M | Biomarker criteria (EGFR) | d | ref |
| OncoTree | MSK tumour type tree | M M M | Tumour type criteria | not verified (pages 403/404) | ref |
| JMDC | Japanese claims drug codes | M N N | Only Japanese set present | reference says "OMOP generated"; JMDC is a commercial data company [source 22]; treat as c until card 22-6 | ref |
| OMOP Invest Drug | Investigational substances (GSRS) | M M M | Protocol drug codes | a probable (NCATS GSRS) | ref |
| NDC | US product package codes | N N Y | US drug data | a probable: FDA page states no terms | [15] |
| SPL | FDA product labels | N N M | US label links | a probable (UMLS MTHSPL no restriction) | [6], [15] |
| CVX | US vaccine codes | N N Y | Vaccine criteria | a probable (UMLS no restriction; CDC page states no terms) | [6], [16] |
| HCPCS | US procedure and supply codes | N N Y | US outpatient claims | b: Level II open; embedded CPT is c | [6] |
| CPT4 | AMA procedure codes | N N Y | US procedures | c: AMA; Athena's EULA allows OHDSI use only | [9] |
| SMQ | MedDRA standardised queries | N N N | Useless without MedDRA (absent) | c: MedDRA subscription (UMLS category 3) | [6] |
| CDISC | Trial data standard terms | M M M | The EDC's CDASH values, not finding | b: terms not stated on page | [18] |
| VANDF | VA national drug file | N N M | US VA drug data | a ("now a category 0") | [6] |
| VA Class | VA drug classes | N N M | US VA drug classes | a probable | [6] |
| NDFRT | Retired VA drug terminology | N N N | Superseded by MED-RT | a probable | ref |
| MeSH | Literature subject headings | N N N | Not record codes | a (UMLS no restriction) | [6] |
| Race | US race codes | N N Y | US demographics | a (CDC) | ref |
| Ethnicity | OMOP ethnicity | N N Y | US demographics | d | ref |
| Gender | OMOP gender | Y Y Y | Sex criteria | d | [3] |
| Visit | OMOP visit kinds | Y Y Y | Inpatient or outpatient criteria | d | [3] |
| Type Concept | OMOP record provenance | Y Y Y | Claims versus EHR rows | d | [3] |
| Domain, Vocabulary, Concept Class, Relationship | OMOP metadata | Y Y Y | The store itself | d | [3] |
| None | The OMOP release itself | Y Y Y | Release version for the manifest | d | [3] |
| Condition Status, Meas Type, Language, Metadata, Episode, Episode Type, OMOP Extension | OMOP structure | Y Y Y | Already on the loader's list | d | [read: `vocab_load.py:801-805`] |

The last two rows group eleven OMOP vocabularies that behave identically; each is classed **d** and **Y Y Y**.

### 2.2 The long tail: 83 that do not matter (classed from the reference column, publisher pages not opened)

| Id | What | Why not | Class |
| --- | --- | --- | --- |
| CIM10 | French ICD-10 | France only | c (WHO-derived) |
| ICD10GM | German ICD-10 | Germany only | c (WHO-derived) |
| ICD10CN | Chinese ICD-10 | Mainland China only | c (WHO-derived) |
| KCD7 | Korean disease classification | Korea only | c (WHO-derived) |
| ICD9ProcCN | Chinese procedure codes | Mainland China only | c probable |
| EDI | Korean claims codes | Korea only | b probable |
| KDC | Korean drug codes | Korea only | b probable |
| KNHIS, Korean Revenue Code | Korean payer codes | Korea only | d |
| NCCD | Chinese clinical drugs | Mainland China only | b probable |
| SUS | Brazilian procedure and drug table | Brazil; "IQVIA proprietary" | c (table says proprietary) |
| MMI | Modernizing Medicine codes | "MMI proprietary" | c (table says proprietary) |
| GCN_SEQNO | First Databank formulation ids | US, FDB package | c (commercial drug database) |
| Multum | Cerner drug database | US commercial | c (UMLS category 1) [6] |
| CCAM | French medical acts | France only | b probable |
| OPS | German procedures | Germany only | b probable |
| OPCS4 | English procedures | UK only | b probable |
| Read | UK Read codes v2 | UK only | c (UMLS licensed content) |
| OXMIS | Old UK GP codes | UK only; "courtesy of GSK" | c probable |
| dm+d | UK medicines dictionary | UK only | b probable |
| HES Specialty, NHS Ethnic Category, NHS Place of Service | NHS administrative codes | UK only | b probable |
| BDPM | French medicines database | France only | a probable |
| GGR | Belgian drug directory | Belgium only | b probable |
| DPD | Canadian drug products | Canada only | a probable (open.canada.ca) |
| AMT | Australian medicines | Australia only | b probable |
| EphMRA ATC, NFC | Industry drug classes, forms | Market research | c probable (association) |
| EORTC QLQ | Quality-of-life questionnaires | Outcomes, not eligibility | c: permission per use [source 20] |
| SNOMED Veterinary, Nebraska Lexicon | SNOMED extensions | Veterinary; US pathology | c (SNOMED-derived) |
| CIEL | OpenMRS concept dictionary | Low-resource EMRs | b probable |
| CTD | Toxicogenomics database | Research | b probable |
| ClinVar | Variant clinical significance | Knowledge base, not record codes | a probable (NCBI) |
| CIViC | Cancer variant interpretations | Knowledge base | a probable |
| CGI | Cancer genome biomarkers | Knowledge base | b probable |
| OncoKB | MSK oncology knowledge base | Knowledge base | c probable (commercial licence) |
| JAX | Jackson Lab knowledgebase | Knowledge base | c probable |
| NAACCR | US cancer registry dictionary | US registries | b probable |
| NUCC | US provider taxonomy | US billing | c (UMLS category 3) [6] |
| ABMS, Medicare Specialty | US physician specialties | Not patient data | b probable |
| CMS Place of Service, UB04 Typ bill, UB04 Point of Origin, UB04 Pt dis status, UB04 Pri Typ of Adm, Revenue Code | US claim form codes | US billing | c probable (NUBC-owned) |
| DRG, MDC, APC | US payment groupers | US billing | a probable (CMS) |
| SOPT | US payer typology | US billing | b probable |
| US Census | US regions | US geography | a probable |
| Currency | ISO 4217 | Not clinical | b probable (ISO) |
| OSM | OpenStreetMap boundaries | Not clinical | b: ODbL share-alike [opinion] |
| UK Biobank, CO-CONNECT, CO-CONNECT MIABIS, CO-CONNECT TWINS, SG COHORTS, PPI | Research cohort codebooks | Other studies' questionnaires | b probable |
| PCORNet, CDM | Network and model ids | Not needed | d |
| Specimen Type, Visit Type, Drug Type, Procedure Type, Observation Type, Condition Type, Obs Period Type, Device Type, Death Type, Note Type, Cohort Type | Old OMOP type vocabularies | Superseded by Type Concept [opinion] | d |
| Plan, Sponsor, Plan Stop Reason, Cost, Cost Type, Provider, Supplier, Cohort | OMOP payer and cost structure | Not used by finding | d |

Every one of the 130 ids appears once in 2.1 or 2.2 [measured: a script matched each TSV id against this file's
table rows; log in section 7].

### 2.3 Athena's own download terms

Athena shows no general terms page; its terms are a licence modal in the download application and per-vocabulary
"License required" gates [measured: the application bundle at athena.ohdsi.org, 2026-11-18; source 1]. The modal says
that, without an affiliate licence, SNOMED may be used only "for the purpose of exploring and evaluating the
terminology", "not … to add or copy SNOMED CT identifiers into any type of record system", and "not … to distribute
or share SNOMED CT Content or Derivatives"; HemOnc may be used in a "Data Analysis System" but "must not" be used in
"any type of system intended for direct or indirect patient care" [source 1]. OHDSI's vocabulary team writes that
vocabularies not marked "license required" "are open source as a part of OMOP and OHDSI tools", and "do not extract
vocabs and redistribute them" for restricted ones [source 4]. Athena's CPT4 EULA limits CPT to "personal use in
directly participating in healthcare programs administered by OHDSI" [source 9]. **Reading** [opinion]: the open
vocabularies follow their own publishers' terms (section 2.1); nothing restricted that Athena gave the owner may be
copied into a product.

---

## 3. What the first site needs that the download does not hold

| Needed | In the download? | Where it comes from | Plan |
| --- | --- | --- | --- |
| ICD10対応標準病名マスター with 修飾語 | No | MEDIS-DC; free for medical institutions, distribution needs 使用許諾 [read: 11 §4 row 1] | Site-loaded; 11/JP-9 |
| HOT, YJ drug codes | No (JMDC only) | MEDIS (HOT), MHLW 薬価 list (YJ, PDL 1.0) [read: 11 §4] | YJ stems ship (56 today); HOT site-loaded |
| JLAC10 / JLAC11 laboratory codes | No | JSLM / MEDIS; no public LOINC map [read: 11 §4] | The site's own map |
| 診療行為 (K, J, D codes), レセプト電算 masters, 手術・処置 | No | MHLW 診療報酬情報提供サービス; MEDIS [read: 11 §4] | Site-loaded, with a claims feed |
| Japanese names for any concept | No Japanese synonyms expected [opinion; not verified on CONCEPT_SYNONYM] | MANBYO, JMED-DICT mini (review 20) | 10H-1 |
| Taiwan NHI drug, order and service codes; ICD-10-CM Chinese editions; NHI lab to LOINC | No | NHIA, data.gov.tw, OGDL 1.0 [read: 06 §4 Taiwan] | Ship (9h-14) |
| MedDRA, MedDRA/J | No (SMQ only) | MSSO, JMO; subscription | Out of 1.0 (O-6) |
| CTCAE v5 (and JCOG Japanese) | No | NCI (US public domain), JCOG | Already in the register (`ctcae`) |
| HPO, ORPHAcodes | No | Monarch, Orphanet | P3 (06 §4) |

**Plainly** [opinion]: the download improves medicines, labs, units and US or Taiwanese diagnosis codes everywhere;
for the Japanese site it adds ATC and RxNorm as the hubs that YJ and HOT codes map onto, and nothing for diagnoses,
labs or procedures in Japanese codes.

---

## 4. What this changes in reviews 06 and plan 10's terminology cards

### 4.1 Which cards can start now

| Card | Before | Now [opinion] |
| --- | --- | --- |
| 9h-4 / T6-4 (Athena import) | Waited for the owner's list | Can start on the build machine once 22-2 lets the loader filter; its first step (row counts) needs the download, not the owner |
| 9h-5 / T6-5 (register as allow-list) | Waited for decisions 23, 24 | Can start: section 2 gives each id its class |
| 9h-15 / T6-16 (register rows, NOTICE) | Waited for decisions 24 to 26 | Can start for the 33 rows marked Y; the long tail gets no row (it never loads) |
| 9h-13 / T6-13 (open subset) | "From his download only if he rules so" | Decision 22-A below |
| 9h-1, 9h-3 / T6-1, T6-3 (candidates; medicines) | 9h-3 waited for 9h-4 | Can start from a derived table built on the build machine (22-5), before the full import |

### 4.2 Does a derived table inherit the source's licence? Class by class [opinion]

| Derived from | May the derived artefact ship? |
| --- | --- |
| a with a (RxNorm ingredient synonyms; ICD-9-CM to ICD-10-CM; NDC to RxNorm) | Yes, with the credits (NLM's statement, the RxNorm "not the latest" notice [source 5]) |
| d with a | Yes |
| b (LOINC, UCUM, NCIt) | Only as the terms allow: LOINC stays site-loaded by D-1028; UCUM must not be cut down (its licence bars "add, delete, or modify" [source 10]), so ship the full UCUM essence (already in the CQL jar) or nothing; NCIt with attribution |
| anything with c (SNOMED, ATC names, WHO ICD-10, ICD-O-3, HemOnc, CPT4, JMDC until checked) | No. A mapping that carries a class (c) code or name is built at the site, from the site's own licensed copy |
| ATC **codes** alone, as identifiers | Open question TB-LIC-02; meanwhile ATC codes reach the bundle only through Taiwan's NHI list (OGDL) and TrialBox's own YJ stems, as today |

### 4.3 The smallest useful first step under "E plus fourteen"

On the build machine, from the download read in place: (1) an **RxNorm candidate table**: every ingredient and
precise ingredient with its synonyms and brand names, RXCUI as the key (class a only, a few hundred thousand rows
[opinion; not measured]); (2) the **open subset** of 9h-13 (RxNorm, RxNorm Extension, ICD-10-CM, ICD-10-PCS,
ICD-9-CM, OMOP structural), with the closure the synthetic hospital needs. Feed (1) to the mapper's medicine candidates
and (2) to the tests. Proof: review 06's replay without a model (T6-2) on P2b sigir: medicine concepts resolved
rising from 4 of 200, empty `concept_map` answers falling from 626 [read: 06 §1, §5.2].

---

## 5. Cards

| Id | Maps onto | What | Size | Lane | Waits for | Proved by | Grade |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 22-1 | 9h-15 / T6-16 | The owner's list in `docs/licences` (this commit); register rows with a `class` (a to d) for the 33 vocabularies marked Y; NOTICE lines for a and b | S | H | – | `tools/licence_register.py` passes; each id marked Y has a row | E |
| 22-2 | 9h-5 / T6-5 | The loader's allow-list read from the register; a bundle with other vocabularies is **filtered** (rows skipped, counted, logged), not refused; class c loads only with a site acceptance row | S | E | 22-1 | Loading a fixture with a SNOMED and a KCD7 row loads the rest and reports two skipped | E |
| 22-3 | 9h-4 (first step) | Build-machine manifest: read `VOCABULARY.csv` from the download in place; record each vocabulary's version, the release, and sha256 per file into the build record (no data copied) | S | E | – | The manifest for this download lists 130 rows and `v5.0 27-AUG-25` | E |
| 22-4 | 9h-13's guard | Build-time bundle test: every concept id and code-system tag in every artefact the bundle carries is looked up in the download's CONCEPT; any vocabulary of class c, or any id absent from the open list, fails the build | M | E, Int | 22-2, 22-3 | A planted SNOMED concept in a test artefact fails the build; the real bundle passes | E |
| 22-5 | 9h-3 / T6-3 (first half), 9h-1 | RxNorm candidate table built on the build machine (section 4.3, item 1), shipped with NLM's credit | M | A2 | 22-3 | T6-2 replay: medicine concepts resolved on P2b, from 4 of 200 | E |
| 22-6 | new | Check JMDC's terms (Athena marks it OMOP-generated; JMDC is a company) and whether JMDC to RxNorm maps cover YJ stems | S | H | – | A register row with evidence, or JMDC stays site-only | E |
| 22-7 | new | ICD-10-CM outside the US: read NCHS's and WHO's terms for a vendor shipping the CDC files to Japan and Taiwan (UMLS category 3 for non-US users) | S | H | – | The register row `icd10cm` cites a publisher statement, or is re-classed | E |
| 9h-4 | 9h-4 / T6-4 | Unchanged: the full import, now filtered (22-2) and measured on the build machine | L | E | 22-2, 22-3 | Rows, time, disk recorded for this download | E |

**Count:** 4 S, 3 M, 1 L (22-1 to 22-7 plus 9h-4). Track H's other cards (9h-6 to 9h-12, 9h-14) are unchanged.

---

## 6. Decisions for the owner

**22-A. May tables derived from your download, from class a and d vocabularies only, ship in the bundle?** (the RxNorm
candidate table, the open subset; closes plan 9 revision 2's correction 3 "only if he rules so").
*Recommendation:* **yes**; nothing of class b or c, and the guard 22-4 enforces it.

**22-B. Refresh the download to Athena's current release before the measured import?** Yours is `v20250827`; current is
`v20260829` (newer RxNorm, LOINC, ICD-10-CM). Free; same selection. *Recommendation:* **yes, when convenient**; nothing
waits for it except 9h-4's final measurement.

**No decision needed** (defaults are obvious): SNOMED, CPT4, HemOnc, ICD-O-3, WHO ICD-10 text and ATC names never ship
and load only on a site's own licence (review 06 O-2, O-3 stand); the 83 long-tail vocabularies are filtered out at
load; the Japanese masters stay site-loaded (O-4, 11/JP-9).

---

## 7. Measurement log

| # | What | Command | Result |
| --- | --- | --- | --- |
| 1 | Row count and hash of the owner's list | `wc -l`; `sha256sum` on the TSV | 131 lines (130 vocabularies); `7717965bd054…bae33b` |
| 2 | Loader allow-list against the list | Python: parse `ATHENA_ALLOW` from `services/omop/vocab_load.py:801-805`; set difference with the TSV ids | 24 allowed, 106 refused; `Note Encoding` allowed but absent |
| 3 | OMOP-generated rows; proprietary; UMLS-licensed references | Same script on the reference column | 42; SUS, MMI; CPT4, Read, HCPCS, MeSH, SNOMED |
| 4 | Athena release | `curl https://athena.ohdsi.org/api/v1/vocabularies/release-version` | `v20260829`; the list endpoint answers 403 |
| 5 | Athena licence text | `curl` of the application bundle named in athena.ohdsi.org's page; text search for the licence modal | SNOMED and HemOnc terms quoted in 2.3 |
| 6 | UMLS restriction categories | `curl` of the UMLS licence appendix and agreement; text search per source | As cited in section 2.1 |
| 7 | Every TSV id covered by section 2; relevance counts | `/var/tmp/trialbox-0/b24/cover.py`: each id found once as a first-column cell (grouped cells split on commas); JP TW US flags counted | 130 of 130, none twice; 2.1 holds 47 (33 with a Y, 11 M only, 3 N), 2.2 holds 83 |

Scratch in `/var/tmp/trialbox-0/b24/` (deleted when done).

---

## 8. Sources opened (2026-11-18)

| # | Source | Link | What it gave |
| --- | --- | --- | --- |
| 1 | Athena download application (licence modal) | https://athena.ohdsi.org/ (its application script) | SNOMED and HemOnc terms |
| 2 | Athena release endpoint | https://athena.ohdsi.org/api/v1/vocabularies/release-version | `v20260829` |
| 3 | OHDSI Vocabulary-v5.0 licence | https://github.com/OHDSI/Vocabulary-v5.0/blob/master/LICENSE | The Unlicense |
| 4 | OHDSI forum, licensing terms for vocabulary download | https://forums.ohdsi.org/t/licensing-terms-for-vocabulary-download/19628 | "open source as a part of OMOP"; "do not extract vocabs and redistribute them" |
| 5 | RxNorm terms of service | https://www.nlm.nih.gov/research/umls/rxnorm/docs/termsofservice.html | Names and RXCUIs public domain; acknowledgement; currency notice |
| 6 | UMLS licence appendix and agreement section 12 | https://www.nlm.nih.gov/research/umls/knowledge_sources/metathesaurus/release/license_agreement_appendix.html | Restriction categories per source (ICD10CM: 4 US, 3 non-US; MDR, CPT, ICD10 WHO, NUCC, Read: 3; MMSL: 1; VANDF: 0; LOINC special notice) |
| 7 | SNOMED International, get SNOMED | https://www.snomed.org/get-snomed | Non-member territories: annual MLDS licence; "charges may apply" |
| 8 | WHOCC copyright | https://atcddd.fhi.no/copyright_disclaimer/ | "Copying and distribution for commercial purposes is not allowed"; no changes |
| 9 | OHDSI CPT EULA | https://ohdsi.org/?p=3672 | OHDSI-only use; no commercial use; no derivatives |
| 10 | UCUM licence | https://ucum.org/license | Commercial software allowed; notice; no add, delete or modify |
| 11 | LOINC licence | https://loinc.org/license/ | **403**; terms taken from the register and source 6 |
| 12 | WHO copyright policy | https://www.who.int/about/policies/publishing/copyright | ICD-11: CC BY-ND 3.0 IGO; ICD-10 not addressed |
| 13 | CMS ICD-10 page | https://www.cms.gov/medicare/coding-billing/icd-10-codes | No licence statement |
| 14 | CDC ICD-10-CM page | https://www.cdc.gov/nchs/icd/icd-10-cm/index.html | No licence statement; "WHO … owns and publishes ICD-10" |
| 15 | FDA NDC directory | https://www.fda.gov/drugs/drug-approvals-and-databases/national-drug-code-directory | No terms stated |
| 16 | CDC CVX | https://www2a.cdc.gov/vaccines/iis/iisstandards/vaccines.asp?rpt=cvx | No terms stated |
| 17 | SEER ICD-O-3 | https://seer.cancer.gov/icd-o-3/ | No terms stated; IARC publishes it |
| 18 | CDISC Controlled Terminology | https://www.cdisc.org/standards/terminology/controlled-terminology | No licence stated |
| 19 | NCI EVS licence | https://evs.nci.nih.gov/license | Page did not render |
| 20 | EORTC QLQ questionnaires | https://qol.eortc.org/questionnaires/ | Permission per use; "General Terms of Non-fee bearing User" |
| 21 | MedDRA subscription pages | https://www.meddra.org/subscription/subscription-rate | Page did not render |
| 22 | JMDC | https://www.jmdc.co.jp/en/ | Provides data "to pharmaceutical companies, research institutions…" |
| 23 | OncoTree | https://oncotree.mskcc.org/ | 403; licence file 404 |

---

## 9. What this document did not verify

- The licence of LOINC (page 403), NCIt (page empty), MedDRA (page empty) and OncoTree (403, 404) from the publisher
  today; LOINC and NCIt classes rest on the register, review 06 and the UMLS appendix.
- Whether a vendor may ship CDC's ICD-10-CM files outside the US (card 22-7); whether ICD-10-PCS, NDC and CVX are
  public domain in a publisher's own words (none of their pages states terms; "a probable").
- JMDC's terms and coverage (card 22-6); whether CONCEPT_SYNONYM in this download holds any Japanese names.
- Every row of section 2.2 (publisher pages not opened; classes from the reference column).
- The download itself: no row counts, sizes or load time (the data stays in the owner's drive; 22-3, 9h-4).
- Whether "Data Analysis System" in HemOnc's terms would cover TrialBox's screening at all; treated as class c.
