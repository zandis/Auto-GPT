**D-180 Clinical item catalogue: codes checked against public sources, JLAC10 from the MHLW table, ICD-10-CM sets
for the OHDSI phenotypes.**
Source: `docs/reviews/2026-11-09-clinical-item-catalogue.md` §6 (gaps); WS-04.1 of TB-PLAN-05. Sources were read
on 2026-11-10 (the evidence date); nothing was copied from memory.

*Decision.* A code enters the catalogue only when a public source was read and the result is kept in
`catalogue/verification/evidence.json`. `tools/catalogue_verify.py fetch` reads the sources (network);
`tools/catalogue_verify.py build` writes the CSVs offline from the evidence and three curated files in
`catalogue/verification/` (`loinc_decisions.csv`, `jlac10_map.csv`, `phenotype_icd10cm_map.csv`). Each item and
phenotype row now says `verified` yes or no, with the source and the date checked, and `catalogue/codes_checked.csv`
lists every code the catalogue names anywhere (983 rows on 2026-11-10) with the name its source gives. Unknown
stays unknown: a local item that no search could match stays local and `verified = no`, with the searches and hit
counts in `verified_note`. **Unknown never excludes; when unsure, no:** a new column `may_exclude` is `yes` only for a
code found in its source, in an item's `loinc` or `jlac10` column, that a person read against the item and found to
fit exactly (94 rows: 18 LOINC items, 76 JLAC10 codes). Unreviewed and partial fits, every phenotype and phenotype
code (no per-code fit review yet), codes a phenotype excludes, the hand-made ICD-10-CM sets, CDISC codelists, codes
named in text and anything not found are `no`. A loader may let a `may_exclude = no` code raise a candidate or show
evidence, never remove a patient; proposed facts never count either way. Tests hold the rule over the fixtures and
over the shipped catalogue.

*What changed.*
1. LOINC. All coded items were looked up by code in the NLM Clinical Tables LOINC service: all exist, and the long
   name is kept in `verified_source`. `code_fit` says whether a person read that name against the item, from
   `loinc_decisions.csv`: 18 `exact`, 20 `partial` (e.g. vitamin D3 only, the right eye only, the 28-joint counts
   whose LOINC codes name no joint set, anti-MDA5 presence only, PIVKA-II units only, PD-L1 CPS whose name does not
   say CPS), 196 `unreviewed` (no decision row yet; never excludes). 22 local items got a LOINC code: anti-MDA5 107563-9, KL-6 93369-7, SP-D 74541-4,
   PIVKA-II 93768-0 (acarboxyprothrombin), TRAb 5385-0, FeNO 96269-6, DLCO % predicted 98130-8, PD-L1 CPS 105303-2
   (the component is the CPS definition; the name does not say CPS), CAP 81894-8, SOFA 96790-1, qSOFA 96791-9,
   KCCQ 71940-1, TOAST 88003-9, and the NAACCR cancer items (primary site, histology and behaviour ICD-O-3, date of
   diagnosis, clinical and pathologic T, N, M). Their local ids are retired, never reused. 235 items stay local;
   the AFB smear grade, DAS28, EDSS, BASDAI, Hoehn and Yahr, HDS-R, JCS and others found no matching term.
2. JLAC10. The one public source that could be read is the MHLW 特定健診 XML item table (付属2 Ver.4); the JSLM pages
   refused automated reading. 39 items carry its 17-digit codes, each with a required `fit`: 35 `exact`, 4 `partial`
   (eGFR 8A065000002391901, the table does not name the equation; random glucose rows for any glucose; the
   calculated LDL whose formula is not named; PSA, for which the table gives no unit). KL-6 is not in that table and has no JLAC10 code here.
3. ICD-10-CM for the OHDSI phenotypes. `catalogue/phenotype_icd10cm.csv` gives each of the 89 linked phenotypes an
   ICD-10-CM include and exclude set, made by hand from the cohort's entry concepts (PhenotypeLibrary v3.37.0) and the
   ICD-10-CM list; every code family exists in ICD-10-CM (NLM). `mapping_verified = no` throughout: the OMOP Maps-to
   table was not used (Athena refused, HTTP 403). The check found WHO-only codes in `phenotypes.csv` (F00, I64, and
   A16 inside the A15-A19 range) and a meaning change (M07 is enteropathic arthropathy in ICD-10-CM; psoriatic
   arthritis is L40.5); the sets use the ICD-10-CM codes and say why. The cohorts' entry concepts are kept as OMOP
   concept ids; SNOMED CT concept codes are not stored (the SNOMED CT licence question is open, D-161), and the
   names of CPT4, HCPCS and SNOMED concepts are not stored either (licensed text): `fetch` searches the ICD-10-CM
   titles by name and keeps the result by OMOP concept id.
4. Every other code. Cells are scanned for code shapes with or without the words LOINC or ATC. LOINC codes in notes,
   component lists, sources and the score files (92, each with its check digit), the phenotypes' LOINC and ATC
   codes, the ATC codes of items' drug-exposure cells, the score files and `specialties.csv` (WHOCC ATC/DDD
   Index; 38 ATC codes in all) and the 47 CDISC CT codelists of `cdisc_qrs` (NCI EVS SDTM Terminology, `use =
   reference`) were all found.
   Phenotype ranges are checked category by category and `(excl. ...)` codes are recorded as excluded. Reading the
   names against the text found one wrong code: `lab.tst` named 23538-2 as the 3-day tuberculin reading; it is the
   avian tuberculin code, and the readings are 23537-4 (2 days) and 23539-0 (3 days). Seven phenotype rows are
   `verified = no`: five with codes ICD-10-CM lacks (F00 twice, I64, A16 inside A15-A19, I14 inside I10-I15), breast
   cancer (ICD-O-3 C50: no public ICD-O-3 source was read) and resistant hypertension (no code at all).
5. Relation to the reference-data loaders (D-170 to D-175): the catalogue's `jlac10` column pairs an item with MHLW
   rows by name; it is not a JLAC10 to LOINC map and is not loaded as one (D-174's site file is the map). No
   reference-data file is changed here.

*Review fixes (2026-11-10).* An independent review of the pull request found:
- JLAC10 units were stored but never compared. `jlac10_map.csv` now gives `source_unit_ucum` (the MHLW unit in
  UCUM, checked against a fixed table in the tool) and `unit_factor` (value in the item's unit = MHLW value x
  factor); the build stops when the units differ and no factor is given. CRP mg/dL x10 to mg/L, WBC /uL x0.001
  to 10*3/uL, platelets 10*4/uL x10 to 10*3/uL. A code for which the MHLW table gives no unit cannot fit a
  unit-bearing item exactly (PSA becomes `partial`, `may_exclude = no`).
- Adopting a LOINC code replaced `licence_notes` with the LOINC notice. The notice is now appended, and the notes
  that were erased are restored from the earlier `items.csv`: the KCCQ copyright, the AJCC licence warning on the
  five TNM items, the ICD-O-3 WHO copyright on primary site and morphology, and three published-formula notes. A
  note that only said "local concept" goes.
- `evidence.json` and `phenotype_icd10cm.csv` keep only the ids of CPT4, HCPCS and SNOMED concepts.
- Two data fixes, each checked in its public source on 2026-11-10: the RA finder-rule example in `specialties.csv`
  also excludes ATC L04AF (JAK inhibitors, WHOCC); `ph.igan` uses ICD-10-CM N02.B (IgA nephropathy, added in FY2023;
  NLM icd10cm) instead of N02.8.

*Evidence.* `tests/unit/test_catalogue_verify.py` (small fixtures, no network): adopted codes must be in the
evidence, a local item with search hits needs a reviewed decision, retired ids are not reused, JLAC10 codes must be
in the MHLW rows, every linked phenotype has a translation whose codes exist, phenotype ATC and LOINC codes must be
found, ranges are checked per category and excluded codes are never included, every code is registered with its
source (a LOINC typo fails its check digit; an independent grep finds no unregistered code shape), `may_exclude` is
never `yes` for an unverified, unreviewed, partial, excluded, text-only, reference or mapped code, a code has one fit
everywhere, `jlac10_map` fit is required, a JLAC10 unit that differs from the item's needs a factor, the source unit
must be the MHLW unit, a unitless code cannot fit exactly, adopting LOINC keeps the other licence notes, the
evidence keeps no CPT4, HCPCS or SNOMED names, the fetch step with a fake network, and the shipped catalogue is up to date
with its evidence (`build --check`).

*Not done here.* OMOP concept ids (needs the Athena bundle), a check of the ICD-10-CM sets against the Maps-to table,
JLAC10 codes outside the 特定健診 table (needs the JSLM or JLAC Center files), ICD-O-3, a per-code fit review of the
196 unreviewed items and of the phenotype codes (until then they never exclude), the code that reads `may_exclude`
(T-107 loads the catalogue), the SNOMED preferred terms question (D-161), and the licence questions of §2 (WS-15.3).
