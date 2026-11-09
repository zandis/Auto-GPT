# TrialBox: clinical item catalogue mapped to standards (2026-11-09)

*Status: research, data files and a design note. Nothing here is runtime code. Facts about outside standards were
checked on the web on 2026-11-09 unless marked "unverified". The data is in `catalogue/` (`items.csv`,
`scores/*.yaml`, `phenotypes.csv`, `specialties.csv`). It follows the patient-data design of the same day
(`2026-11-09-design-patient-data-and-roles.md`, §2.3 "flexible specialty items", §2.4 taxonomy, §2.7 profile).*

## 0. The owner's direction and the short answer

The owner asked today: the subspecialty items and possible clinical items should have a mapping system; OHDSI
probably already describes most of it; done ahead of time, with patient profiling and "patient like me", the
patient-finding platform is more complete.

The short answer. Yes, most of it exists, in four places. LOINC has codes for the common labs and for many
clinical scores (MMSE, MoCA, CDR, ECOG, Karnofsky, NIHSS, mRS, GCS, PHQ-9, GAD-7, CDAI, SDAI, HAQ-DI, joint
counts, patient and evaluator global, Child-Pugh, MELD, NYHA, eGFR, UACR, UPCR, Barthel, FIB-4, 6MWT). LOINC has
no code for DAS28, EDSS, BASDAI, ASDAS, SLEDAI, BVAS, mRSS, Hoehn and Yahr, HDS-R, CDR sum of boxes or PASI
(searched today). CDISC QRS has test-code lists for about 40 of our instruments and, as a by-product, a public
record of which instruments are public domain and which copyright holders said yes or no. The OHDSI Phenotype
Library holds 1,104 Circe cohort definitions under Apache 2.0, 89 of which match our initial phenotype list. The
OMOP Oncology extension gives EPISODE and EPISODE_EVENT for disease phases, regimens and lines of therapy, and
the Cancer Modifier vocabulary for TNM and stage. What does not exist anywhere is the rheumatology composite
score layer as codes (DAS28, SLEDAI, BVAS, ASDAS), the Japanese and Taiwanese instruments and social items
(HDS-R, JCS, 要介護度, 自立度, CMS 長照等級, 巴氏量表 bands, 重大傷病), and the per-item extraction hints. Those are
local concepts in our 2,000,000,000+ range, 256 of them in this first pass.

Counts in this pass: 469 items (213 with a LOINC code, 256 local, 39 with a CDISC QRS test-code list); 26
score definitions as data; 164 phenotypes (89 linked to the Phenotype Library, 75 local); 15 specialty
templates (6 deep: rheumatology, neurology, oncology, hematology, nephrology, general internal medicine; 9 light).

## 1. What exists and what we reuse

### 1.1 LOINC

What it gives: codes and names for laboratory tests, vital signs and a growing set of clinical scales and
survey instruments (panels with per-item codes, e.g. NIHSS 70182-1 with 15 item codes, PHQ-9 panel 44249-1,
HAQ-DI items 75823-5 onward, PROMIS item banks). Coverage checked today with the NLM Clinical Table Search
Service (LOINC items; free, no login):

| Item | LOINC | Item | LOINC |
| --- | --- | --- | --- |
| MMSE total | 72106-8 (panel 72107-6) | DAS28-ESR/CRP | none |
| MoCA total | 72172-0 | EDSS | none |
| CDR | 72088-8 (scale); no sum-of-boxes code | BASDAI, ASDAS | none |
| ECOG | 89247-1 | SLEDAI, BVAS, mRSS | none |
| Karnofsky | 89243-0 | Hoehn and Yahr | none |
| NIHSS total | 72089-6 | PASI | none (PASII 75841-7 is a different scale) |
| mRS | 75859-9 | HDS-R, CASI, JCS | none |
| GCS total | 9269-2 | CDAI (RA) | 75847-4 |
| PHQ-9 total | 44261-6 | SDAI | 75845-8 |
| GAD-7 total | 70274-6 | HAQ-DI total | 75874-8 |
| Child-Pugh total | 98152-2 | Tender / swollen joint count | 88981-6 / 88980-8 |
| MELD / MELD-Na | 44760-7 / 100348-2 | Patient global 0-10 | 75844-1 |
| NYHA functional capacity | 88020-3 | Evaluator global 0-10 | 75846-6 |
| eGFR CKD-EPI 2021 | 98979-8 | Barthel total | 96761-2 |
| UACR / UPCR | 9318-7 / 2890-2 | FIB-4 | 98488-0 |
| Cockcroft-Gault CrCl | 35591-7 | 6-minute walk | 64098-7 |
| HbA1c NGSP / JDS | 4548-4 / 62388-4 | Schwab and England | 77715-1 |

Licence: free for any commercial or non-commercial purpose with the LOINC copyright notice, licence and version
(`2026-11-09-baseline-open-data.md`, row LOINC, read at the source yesterday; loinc.org blocked automated reading
today). Format: CSV table, about 80 MB zip, twice a year; the baseline pack already ships it (P0, row 3).

### 1.2 OMOP vocabularies via Athena

Athena (athena.ohdsi.org) bundles the vocabularies as CSV. The OHDSI-authored content is Apache 2.0 (HL7
Terminology naming-system page for OMOP, read today). Source vocabularies keep their own terms:

| Vocabulary | Status for TrialBox | Evidence |
| --- | --- | --- |
| LOINC | free, LOINC notice | as 1.1 |
| OMOP Extension, Cancer Modifier | free (OHDSI-authored; Cancer Modifier built from NAACCR and CAP checklists, 2,666 concepts in 2020) | OHDSI 2020 poster; HL7 THO |
| ICDO3 | distributed on Athena; WHO/IARC copyright; redistribution terms **unverified** | search today found no statement |
| NAACCR | distributed on Athena; terms **unverified** | same |
| HemOnc | **restricted**: Athena licence forbids use "in any type of system intended for direct or indirect patient care"; full ontology CC BY-NC-SA 4.0, component subset CC BY 4.0, commercial use case by case (licensing@hemonc.org) | hemonc.org/wiki/Ontology; Athena term pages |
| CDISC | free; CDISC Controlled Terminology is published by NCI EVS "freely available, without licensing restrictions"; NCI Thesaurus is CC BY 4.0 | cancer.gov CDISC pages; HL7 licence page |
| SNOMED | licence; Japan and Taiwan are not members | baseline-open-data |
| CPT4, MedDRA, Medi-Span GPI, FDB, ISBT, CDT, IQVIA, Gemscript | "licence required" on Athena | HL7 THO OMOP page |

Athena's search API refused this session's requests (HTTP 403), so no concept ids were copied by hand.
`items.csv` leaves `omop_concept_id` blank for LOINC items; the vocabulary loader resolves them from CONCEPT by
(vocabulary_id = LOINC, concept_code). Offline loading: download the CSV bundle once (needs an Athena account and
the licence acknowledgements), load with the OHDSI vocabulary DDL, keep the version in `tb_snapshot`.

### 1.3 OHDSI Phenotype Library

Read today from the repository's `inst/Cohorts.csv` and `DESCRIPTION`: version 3.37.0 (2026-04-08), licence
Apache 2.0, 1,104 cohort definitions, all `isCirceJson = 1`, 295 marked reference cohorts. Status column: 873
"Pending peer review", 119 "Pending", 64 "Prediction", 22 "Accepted", 22 "Withdrawn", 1 "Deprecated". The two
accepted definitions that matter to us are AKI (269, 362) and SLE indexed on signs, symptoms, treatment or
diagnosis (119). Each cohort is Circe JSON (the ATLAS cohort-definition object model) plus generated SQL;
`getPlCohortDefinitionSet()` returns id, name, SQL and JSON for CohortGenerator. Offline use: clone the repository
at a tag; the JSON files sit in the package's `inst` tree (the exact folder name was not confirmed today).

How it maps to TrialBox: a Circe cohort definition is a phenotype in the twin's `phenotype.documented` layer,
evaluated by SQL over the CDM. Circe JSON references standard concept ids (SNOMED for conditions). Because our
sites keep ICD-10-CM, MEDIS or WHO ICD-10 as source concepts without SNOMED (§2.2 of the design), each imported
definition needs a concept-set translation to ICD-10-CM families before it runs. `phenotypes.csv` therefore
carries both the library id and the ICD-10-CM codes. The gap finder uses the same shape: a finder rule is
"phenotype A present and phenotype or exposure B absent", so library cohorts become the A and B of finder rules.

### 1.4 OMOP Oncology extension

Checked today in the CDM v5.4 page: EPISODE (episode_id, person_id, episode_concept_id, start and end dates,
episode_parent_id for nesting, episode_number for "lines of treatment", episode_object_concept_id from the
Condition domain for disease episodes or Procedure domain / Regimen class for treatment episodes,
episode_type_concept_id, source value and source concept) and EPISODE_EVENT (episode_id, event_id,
episode_event_field_concept_id), which links condition, drug, procedure and measurement rows to an episode
instead of FACT_RELATIONSHIP. Episode concepts (from the Oncology WG documentation mirrors; verify in Athena):
32528 Disease First Occurrence, 32529 Disease Recurrence, 32530 Disease Remission, 32677 Disease Progression,
32531 Treatment Regimen, 32532 Treatment Cycle, 32533 Episode of Care. Line of therapy: an EPISODE with concept
32531, the regimen as object, the line number in episode_number; the WG says this convention is still work in
progress. Staging and modifiers: MEASUREMENT rows with Cancer Modifier concepts (code pattern
`[c/p]-[edition]th_AJCC/UICC-[TNM value]`, stage groups with "Stage"), linked to the diagnosis through
measurement_event_id and meas_event_field_concept_id (the 5.4 names of the former modifier_of_event_id and
modifier_of_field_concept_id). The WG page itself says the extension "is a work in progress" and asks not to use
the page as a basis for implementation; our catalogue therefore stores TNM, stage, edition and line number as
plain items and leaves the EPISODE mapping to the ETL.

### 1.5 CDISC QRS

The QRS page lists 324 instruments. A supplement exists only where CDISC obtained the copyright holder's
permission; "permission to create a supplement is not a license for CDISC standards users to use the
instrument". The status column is a useful public record. Read today: MMSE Granted (PAR), MoCA Denied, CAT Denied,
SF-36 Author Permission Required, MADRS / BDI-II / YMRS / ACT / WOMAC No Response, and Public Domain for EDSS,
ECOG, Karnofsky, mRS, GCS (NINDS version), PASI (four versions), Child-Pugh, MELD, HAM-D, HAM-A, GDS, CGI, PGI,
mMRC, 6MWT, TUG, Crohn's CDAI, Roland-Morris; Exempt from Copyright for PHQ-9 and GAD-7; Granted for MDS-UPDRS,
UPDRS, C-SSRS, EQ-5D, ADAS-Cog, ADCS-ADL, EORTC QLQ-C30, NPI, PANSS, FSS, 9-HPT, T25FW, Epworth, BPI, Oswestry,
FIQR. The controlled terminology file (`SDTM Terminology.txt`, 13.8 MB, 2026-09-25, NCI EVS) was downloaded and
the test-code codelists copied into `items.csv` (`cdisc_qrs`): e.g. MMS1TC, CDR01TC, EDSS01TC, ECOG1TC, KPSS01TC,
CPS01TC, MELD01TC, MELD02TC, MRS01TC, GCS01TC, PHQ01TC, GAD01TC, HAQ01TC, HAMD1TC, PANSS1TC, UPD1TC, UPD2TC,
PASI02TC-PASI05TC, KDIGO1TC, SOFA01TC, HBI01TC, MCHR01TC, DLQI1TC, NYHAC (response list). Not in CDISC: DAS28,
RA CDAI/SDAI, SLEDAI, BASDAI, ASDAS, mRSS, BVAS, NIHSS, MoCA, Hoehn and Yahr, Barthel, FIB-4.

### 1.6 NIH CDE Repository, PROMIS, REDCap Shared Library

NIH CDE Repository (cde.nlm.nih.gov): CDEs and forms, exportable as JSON, CSV, Excel, ODM, SDC and FHIR; no
public API documentation found today; whether CDEs carry LOINC ids was not confirmed; copyrighted questionnaires
need their own licence (HEAL note). Use: a source of form definitions, not a code system.

PROMIS: LOINC has item banks and profiles (62337-1 PROMIS-29, 62336-3 PROMIS-43, 85524-7 global). The PROMIS
Terms and Conditions carry a "Personal and Non-Commercial Use Limitation"; Assessment Center API licensing for
software integration is fee-based (secondary source). TrialBox stores PROMIS T-scores only, until a licence.

REDCap Shared Library: instruments for REDCap consortium members, each under its own copyright; the REDCap EULA is
non-commercial. TrialBox does not redistribute library instruments; a site that holds REDCap may map its own
library forms to catalogue items (the data core already imports REDCap dictionaries, D-129).

### 1.7 Instrument copyright, per instrument

| Instrument | Holder and terms (checked today unless noted) | TrialBox stores |
| --- | --- | --- |
| MMSE | PAR Inc.; written permission to reproduce; per-form fee (about 1.23 USD/test); the 2006 VA FAQ accepted score and answers in a note without the questions | score only |
| MMSE-J (Japan) | 日本文化科学社, paid forms, separate copyright (**unverified**, forum sources only) | score only |
| CDR | Washington University (Knight ADRC): "requires a license whether its intended use is for-profit or non-profit"; algorithm code licensed separately | global and box scores; no text; algorithm after licence |
| MoCA | MoCA Test Inc.; training and certification since 2019 (fee; free for academics); institutional licences; commercial terms not published | score only |
| HDS-R | no licence statement found (**unverified**); used freely across Japan | score and items; text pending check |
| CASI | copyright not found (**unverified**) | score |
| PHQ-9, GAD-7 | Pfizer: "No permission required to reproduce, translate, display or distribute" | everything |
| HAQ-DI | Stanford: "copyrighted only so that it will be used unmodified ... There is no charge for permission" | score and items; text after permission |
| DAS28 | van Riel, "all rights reserved", requests through Mapi ePROVIDE; fee terms not found | score and components (formula is published) |
| CDAI, SDAI (RA) | published indices; no licence known | everything |
| SLEDAI-2K, BILAG, SLICC | copyright **unverified** | score and descriptors; BILAG score only |
| BVAS, VDI | Oxford University Innovation licence application required | score only |
| mRSS, BASDAI, ASDAS, BASFI | published; copyright **unverified** | score and items |
| EDSS, ECOG, Karnofsky, mRS, GCS, PASI, Child-Pugh, MELD, HAM-D, 6MWT, mMRC, Crohn's CDAI | public domain (CDISC QRS table; ECOG-ACRIN credit line; GCS "no cost" with acknowledgement) | everything |
| NIHSS | NINDS material "in the public domain" (archived NINDS page; current page refused today) | everything |
| MDS-UPDRS, UPDRS | Movement Disorder Society; per study, protocol and language; industry fee (secondary source: 20,000 USD) | score only |
| ADAS-Cog | copyright (Rosen/Mohs); terms **unverified** | score only |
| EQ-5D | EuroQol; registration always; fee for commercial use | index and VAS only |
| SF-36 | QualityMetric/Optum licence (not re-read today) | score only |
| DLQI | Cardiff University; free for not-for-profit academic use; licence with charge otherwise, incl. clinical trials | score only |
| CAT | GSK; CDISC request denied | score only |
| PANSS | MHS licence (not re-read today) | score only |
| FACT-G, FACIT-F | FACIT: no fee for clinical and investigator use; per-trial fees for commercial use; licence expected | score only |
| EORTC QLQ-C30 | free academic, fee commercial (not re-read today) | score only |
| PedsQL | Mapi Research Trust; fees for funded studies | score only |
| FRAX | University of Sheffield; software integration licence (**unverified**) | score only |
| AJCC TNM and stage | AJCC licenses staging content for EHR and other software (ajcc@facs.org); UICC via Wiley permissions | the stage value as recorded; no staging tables in the product |
| RECIST 1.1, CTCAE, KDIGO thresholds, JSN eGFR, CKD-EPI, Cockcroft-Gault, FIB-4, Friedewald, CHA2DS2-VASc | published formulas or public domain | everything |

### 1.8 Japan and Taiwan specifics

- **Japan.** HDS-R (加藤 1991, cut-off ≤ 20) is the common bedside screen; MMSE-J is a separately published
  paid instrument; MoCA-J (Fujiwara 2010, cut-off 25/26) exists. JCS (3-3-9度方式) is recorded instead of GCS in
  registries; Nakajima 2023 published a JCS to GCS conversion table (two rows confirmed from a second source).
  eGFR is the JSN 2009 equation (194·Cr^-1.094·age^-0.287, ×0.739 female), printed on lab reports; worked value
  from the CKD診療ガイド2023 早見表: male, 50 y, Cr 1.0 → 63.1. HbA1c before 2012-04 is JDS; NGSP = 1.02·JDS + 0.25
  (JDS 6.1 = NGSP 6.5). CRP is in mg/dL. Platelets are written in 万/µL. 1秒率 means FEV1/FVC. Social items:
  要介護度, 障害高齢者の日常生活自立度 (J1-C2), 認知症高齢者の日常生活自立度 (Ⅰ-M), 身体障害者手帳, 指定難病受給者証.
  Hoehn and Yahr drives the 指定難病 severity for Parkinson's disease. JLAC10 codes: the baseline pack maps the
  CLINS 43+5 items to LOINC (our own table); no JLAC10 code for eGFR or for any score was found today
  (**unverified**); KL-6 and SP-D are Japan-specific ILD markers (local concepts).
- **Taiwan.** CDR ≥ 0.5 is the entry rule for 失智共同照護 (MOHW); CDR and MMSE appear in insurance and court
  records; CASI C-2.0 is widely used. 巴氏量表 (Barthel) is the statutory assessment for foreign caregivers, with
  bands 0-20, 21-60, 61-90, 91-99, 100; 長照 CMS 等級 1-8 (levels 2-8 funded); 重大傷病證明 is a strong confirmer of
  cancer, SLE, dialysis and major psychiatric diagnoses. Labs are mapped through the NHIA PAS IG ConceptMap
  nhi-loinc (1.2.4, 2026-07-01, 806 mappings, CC0, read today): 09015C creatinine, 09026C ALT, 09025C AST, 09038C
  albumin, 09029C total bilirubin, 09033C LDH, 08002C WBC, 08003C hemoglobin, 08006C platelets, 14030C/14031C
  HBsAg, 14051C anti-HCV, 09011C calcium. eGFR in Taiwanese reports is MDRD or CKD-EPI 2009; Chen 2014 (PLoS ONE)
  gives Taiwanese coefficients (1.309·MDRD^0.912; 1.262·CKD-EPI^0.914); a society endorsement was not found.

## 2. Licence decisions

1. **Ship** (codes and names in the product): LOINC (notice), CDISC Controlled Terminology (NCI EVS, free),
   OHDSI Phenotype Library definitions (Apache 2.0, with attribution), OMOP Extension and Cancer Modifier
   concepts, published formulas and thresholds (JSN, CKD-EPI, Cockcroft-Gault, MELD, Child-Pugh, FIB-4, KDIGO,
   RECIST, CTCAE, PHQ-9, GAD-7, ECOG, KPS, EDSS, NIHSS, mRS, GCS, PASI), the NHIA nhi-loinc map (CC0).
2. **Ship the score, never the text**: MMSE, MoCA, CDR, MDS-UPDRS, ADAS-Cog, EQ-5D, SF-36, DLQI, CAT, PANSS,
   FACT, EORTC, PROMIS, PedsQL, BVAS/VDI, BILAG, FRAX, AJCC stage. The `storable` column enforces this per item.
   A site that holds its own licence may turn item or text storage on in its template; the catalogue default
   stays off.
3. **Ask before shipping**: HAQ-DI item text (free permission), DAS28 (ePROVIDE conditions), HDS-R (holder),
   ICDO3 and NAACCR redistribution (Athena terms), HemOnc regimen names (the "indirect patient care" clause: a
   research pre-screening product is arguably outside it, but the consortium coordinator should ask).
4. **Do not ship**: SNOMED (unchanged), WHO ICD-10 text, ATC text (unchanged), AJCC staging tables, any
   questionnaire text in group 2.
5. **Record the version**: every vocabulary and every score definition carries its version in the provenance of
   the facts it produced (`tb_snapshot`, `tb_score_definition.version`).

## 3. How the catalogue plugs into the OMOP design

- **Concept registry (§2.4).** Each `items.csv` row becomes one `vocab.concept` row. A LOINC item points to the
  LOINC concept and carries TrialBox's extra columns (value type, unit, range, specialty, storable, extraction
  hint). A local item is a `TB-SHARED` concept with the proposed id (2,000,001,001 upward, assigned in file order;
  rows are appended, never renumbered) and a "Maps to" row where a weaker standard exists (e.g. CDR sum of boxes
  → "Is a" CDR). Site codes (JLAC10, NHI order codes, sheet columns) map to catalogue items through
  `source_to_concept_map`, once per site, as D-135 already does for diagnoses and drugs. The nhi-loinc map seeds
  Taiwanese lab mappings; the CLINS JLAC10→LOINC table seeds Japanese ones.
- **Score definitions as data (§2.3).** Each `scores/*.yaml` is one `tb_score_definition` row plus its
  components. The box implements the nine `formula_kind` values listed in `catalogue/scores/README.md`; a file
  supplies coefficients, units, windows (e.g. ESR within 7 days of the joint count), rounding and edge cases. The
  worked examples become the unit tests of the compute step. A definition is approved on the console like a
  ruleset; versions recompute forward. Where today's files say "no published worked example found" (DAS28, BASDAI,
  ASDAS, MELD 3.0 primary source), approval waits for a clinician-supplied example.
- **Profile templates (§2.3, `tb_specialty_template`).** `specialties.csv` is the first content of the four
  shipped templates plus eleven more. The page shows the template's scores and labs as trend lines, the
  phenotypes as the Problems section, and the social items in the Context section.
- **Phenotype layer (§2.7.3).** `phenotypes.csv` seeds `phenotype.documented`: a library cohort id where one
  exists, else a local Circe definition written from the ICD-10-CM families in the `codes` column. Status is kept
  so a PI can see that most library definitions are "pending peer review" and only AKI and SLE are "accepted".
- **Gap finder (§2.7.3).** `specialties.csv` lists finder-rule examples per specialty in the evidence/absence
  form the design requires (e.g. UIP pattern on HRCT and no J84.112; seropositive erosive RA and no biologic in
  24 months; CKD G3b/G4 twice and no nephrology visit). Each rule names catalogue items only, so it compiles with
  the same engine as a criterion and inherits fail-closed behaviour.
- **"Patient like me" (§2.7.4).** The patient vector in v1 is text-based (mean of note-chunk embeddings plus the
  Summary section). The catalogue adds a structured feature block per specialty (`patient_vector_features` in
  `specialties.csv`): the latest value of each core score and lab (instrument-flagged, unit-normalised), the
  phenotype flags, the stage or line number, the GC dose, the eGFR slope. These are concatenated as a normalised
  numeric vector and stored beside the text vector in `vec.patient` with `method = structured_v1`; similarity
  queries can weight the two. Items feed the vector only when `storable` allows the score and the fact is
  `coded`, `confirmed` or `derived`; proposed facts never enter it. Cognitive scores from different instruments
  (MMSE, HDS-R, MoCA, CASI) are kept as separate features, not converted, because published conversions are
  weak; the template marks which instrument the site uses.

## 4. How note extraction uses it

The LLM extraction prompt (`chart_facts_v1`) lists, per specialty template, the catalogue items the model may
propose: id, name in the note's language, value type, allowed range or values, unit, and the `extraction_hint`
column, which says how the item is usually written ("'MMSE 24/30', 'MMSE 24点'; keep the version", "'Plt
18.5万' → 185 ×10^3/µL", "'1秒率' is FEV1/FVC, not %FEV1", "'PS 1' in a JP oncology note means ECOG"). The model
returns item id, value, unit as written, quote and offset; the box converts units with the UCUM table, checks the
range, and writes a NOTE_NLP row and a proposed fact (D-135). An item whose hint says "derive, do not take from
text" (eGFR slope, LEDD, drug-resistant epilepsy, seropositive RA) is never proposed from text; the compute step
derives it. Items marked `documented_as = form` (HAQ-DI, PHQ-9, BASDAI) are expected from forms or the data core,
and a total found in a note is proposed with lower confidence. Scores whose `storable` is "score" never get their
item answers extracted, whatever the note contains.

## 5. How screening uses it

A criterion compiles against item ids, not against free text or codes chosen at compile time. "DAS28-CRP ≥ 3.2
at screening" compiles to: latest MEASUREMENT with concept rheum.das28_crp (entered or derived, screening view
only) within the protocol window, value ≥ 3.2; if absent, components present → derive; else unknown. "eGFR ≥ 30"
with no equation named compiles to the site's own eGFR item (JSN in Japan, the reported equation in Taiwan) and
records which; a criterion that names the equation compiles to that item. "ECOG 0-1" accepts an ECOG row or a
KPS row converted through `ecog_kps_map.yaml` with a flag. The `criterion_phrasing` column holds the wording the
drafting assistant and the parser recognise. Phenotype criteria ("documented RA", "no history of malignancy")
compile to `phenotypes.csv` entries, i.e. Circe or local definitions over source concepts.

## 6. Gaps

- No OMOP concept ids in `items.csv` (Athena blocked); resolved at vocabulary load.
- No JLAC10 or NHI codes for scores; JLAC10 codes for labs not verified today.
- Four score files lack a published worked example (DAS28-ESR, DAS28-CRP, BASDAI, ASDAS); two rely on
  calculator pages (MELD 3.0, Child-Pugh); two rely on remembered tables (prednisolone equivalents, LEDD).
- DLCO LOINC code, anti-MDA5, KL-6, PD-L1 CPS, FeNO, TRAb, PIVKA-II: local until a LOINC lookup is done.
- Light specialties: cardiology lacks valve grading and device data; pulmonology lacks sleep studies and SGRQ;
  GI lacks UCEIS and celiac serology; endocrinology lacks CGM metrics; psychiatry lacks DSM-5 structured
  diagnoses and Japanese or Chinese scale norms; dermatology lacks SALT, VASI, NAPSI; infectious disease lacks
  structured antibiograms; pediatrics lacks age-specific reference ranges and JP/TW growth references;
  ophthalmology needs a per-eye laterality model for every item (listed per row in `specialties.csv`,
  `missing_first_pass`).
- Phenotype definitions from the library assume SNOMED standard concepts; each needs an ICD-10-CM concept-set
  translation before it runs at a JP or TW site.
- No Japanese or Taiwanese cognitive norm tables; MMSE/HDS-R/MoCA/CASI are kept as separate features.
- Instrument copyright for about fifteen scales is marked "unverified"; see §1.7.

## 7. Questions for the owner

1. **CDR licence.** Options: (a) buy the Washington University licence for the instrument and the scoring
   algorithm so TrialBox can derive the global score and ship the Japanese and Chinese translations; (b) store
   only entered global scores, no derivation, no translations. Recommendation: (a), because CDR gates Taiwanese
   dementia services and most dementia trials; it is one licence for the whole consortium.
2. **HDS-R or MMSE for Japan.** Options: (a) make HDS-R the primary Japanese cognitive item and MMSE secondary;
   (b) MMSE primary, as in global trials; (c) both, no conversion, instrument flagged (what the catalogue does
   now). Recommendation: (c) for storage, with HDS-R shown first on Japanese templates; buy no MMSE licence
   until a sponsor protocol demands MMSE text in the product. Ask the HDS-R rights holder for a statement.
3. **MoCA.** Options: (a) institutional licence; (b) score only. Recommendation: (b) now; sites already certify
   their own raters.
4. **DAS28.** Options: (a) ask ePROVIDE/van Riel for a software-use permission; (b) store entered and derived
   scores under the published formula without asking. Recommendation: (a) in writing before release; the
   formula is public but the owner asserts all rights.
5. **MDS-UPDRS.** Options: (a) licence per study when a sponsor needs it; (b) product-wide licence.
   Recommendation: (a); TrialBox stores the total and Part III as entered.
6. **AJCC.** Options: (a) licence AJCC content so the box can validate T/N/M against stage tables; (b) store
   stage values as recorded, no validation. Recommendation: (b) now; Taiwan Cancer Registry stages are already
   AJCC-coded and Japanese 規約 stages differ anyway.
7. **HemOnc regimen vocabulary.** Options: (a) ask HemOnc whether a research pre-screening product is "indirect
   patient care"; (b) use our own regimen list keyed to ATC. Recommendation: (a) by the consortium coordinator;
   (b) as the fallback in the catalogue.
8. **OHDSI Phenotype Library status.** Options: (a) load all 1,104 definitions and show the status; (b) load
   only "Accepted" and reference cohorts. Recommendation: (a); the status is the honest signal and the SLE and
   AKI definitions are the only accepted ones we need.
9. **Which eGFR for Taiwan.** Options: (a) CKD-EPI 2021; (b) CKD-EPI 2009 as printed by TW labs; (c) Taiwanese
   MDRD (Chen 2014). Recommendation: store the reported value with its equation, derive CKD-EPI 2021 beside it,
   and let the criterion name the equation; ask the Taiwan Society of Nephrology which it endorses.
10. **Vector features.** Options: (a) text vector only in v1 (the design); (b) text plus the structured feature
    block of §3. Recommendation: (b), because the structured block is explainable and lets "patients like these
    three" respect scores and stages, not only note wording.

## Appendix A. Sources checked today

LOINC items via clinicaltables.nlm.nih.gov (LOINC codes above); loinc.org/license (blocked; terms from
baseline-open-data); github.com/OHDSI/PhenotypeLibrary (README, DESCRIPTION, NEWS.md, inst/Cohorts.csv);
ohdsi.github.io/CommonDataModel/cdm54.html (EPISODE, EPISODE_EVENT, MEASUREMENT); OHDSI OncologyWG site and
documentation mirrors (episode concepts, Cancer Modifier code pattern); forums.ohdsi.org (line of therapy,
measurement_event_id rename); cdisc.org/standards/foundational/qrs; evs.nci.nih.gov/ftp1/CDISC/SDTM/SDTM
Terminology.txt (2026-09-25); cancer.gov CDISC terminology pages; terminology.hl7.org OMOP and TNM naming
systems; hemonc.org/wiki/Ontology and Athena HemOnc licence pages; knightadrc.wustl.edu (copyright, scoring
rules, scoring algorithm); PAR MMSE statements (BMC Geriatrics 2025 correction; VA 2006 FAQ); MoCA training
sources; Stanford HAQ instructions (NIEHS copy); das-score.nl; CamCOPS DAS28 and PHQ-9 task pages;
innovation.ox.ac.uk BVAS licence; movementdisorders.org rating-scale permissions; EuroQol registration; Cardiff
University DLQI licensing; facit.org; glasgowcomascale.org/permissions; NINDS archived public-domain statement;
ECOG-ACRIN scale page; healthmeasures PROMIS terms (assessmentcenter.net PTAC); cde.nlm.nih.gov guides; REDCap
Shared Library descriptions; Matsuo 2009 (JSN eGFR); Okayama City and Kagoshima Prefecture eGFR 早見表; JDS 2012
HbA1c conversion sources (PMC4014931); Chen 2014 PLoS ONE (Taiwanese eGFR); Nakajima 2023 J Epidemiol (JCS to
GCS); MOHW Taiwan dementia care documents; 勞動部 巴氏量表 rules via news sources; 長期照顧服務申請及給付辦法 (CMS
levels); 厚生省 自立度 notices via municipal documents; NHIA PAS IG 1.2.4 ConceptMap nhi-loinc; kidney.org
CKD-EPI 2021 page; KDIGO 2024 summaries; Pharmaceutical Journal Cockcroft-Gault example; R package cliot
documentation (CDAI, SDAI, SLEDAI-2K, Friedewald examples); primecalcpro and other calculator pages (Child-Pugh,
FIB-4, MELD 3.0 examples, graded "calculator").
