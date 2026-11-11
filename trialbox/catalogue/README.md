# Clinical item catalogue

The items a patient database, the patient profile and trial screening need, each mapped to an existing standard
where one exists. Data only; no runtime code reads it yet. Design and findings:
`docs/reviews/2026-11-09-clinical-item-catalogue.md`.

| File | What it holds |
| --- | --- |
| `items.csv` | one row per item: names (en, ja, zh-TW), specialties, type, value type and range, UCUM unit, LOINC code or `local` with a proposed concept id ≥ 2,000,001,001, CDISC QRS code, components, formula reference, source, licence, what may be stored, how it is documented, typical criterion phrasing, an extraction hint, Japan and Taiwan notes; then the verification columns (D-180): `verified`, `code_fit`, `verified_source`, `verified_date`, `verified_note`, `jlac10`, `jlac10_source` |
| `scores/*.yaml` | one file per derived score: inputs, formula, rounding, windows, edge cases, worked examples from published sources (see `scores/README.md`) |
| `phenotypes.csv` | the initial phenotype list per specialty, linked to OHDSI Phenotype Library cohort ids (3.37.0) or marked local; verification columns as in `items.csv` |
| `phenotype_icd10cm.csv` | for each OHDSI-linked phenotype, the ICD-10-CM concept set that stands in for the cohort's SNOMED entry concepts, and how it was derived |
| `codes_checked.csv` | every code the catalogue names anywhere (code columns, a phenotype's `codes`, notes, score files, `specialties.csv`): system, code, the name the public source gives, the source, the date, and `may_exclude` |
| `verification/` | the curated inputs (`loinc_decisions.csv`, `jlac10_map.csv`, `phenotype_icd10cm_map.csv`) and `evidence.json`, what the public sources said on the date checked |
| `instruments.csv` | the instrument copyright register (T-307, D-375): one row per licensed instrument with its holder, `licence` (`needed`, `free-with-terms`, `unclear`), what the terms say, the public source read and the date, and the catalogue items it covers (none for an instrument not in the catalogue). Curated by hand; read by `tb_common.instruments` |
| `phenotype_status.csv` | the phenotypes whose ICD-10-CM set was run on the synthetic hospital with the expected hits (`synthetic`, T-307); every other phenotype is "not validated here". Curated by hand; read by `tb_common.phenotypes` |
| `specialties.csv` | each specialty template: core scores, labs and findings, social items, phenotypes, finder-rule examples, patient-vector features, and what the first pass left out |

Rules:

- A LOINC code in `items.csv` is a code and a name only, under the LOINC licence (free, notice required). No
  licensed questionnaire text is in this folder; `storable` says per item whether a site may store the score,
  the item values, or the text.
- `omop_concept_id` is blank for LOINC items: the id is resolved from the CONCEPT table (vocabulary LOINC, the code)
  when the vocabulary pack is loaded. Athena refused this session's requests, so none were copied by hand.
- Local ids are assigned in file order inside the TB-SHARED block. Rows are appended, never reordered.
- Chinese names are Taiwan usage (zh-TW); Japanese names follow common chart usage, not always the official translation.

## Verification (D-180)

`tools/catalogue_verify.py` writes the verification columns, the adopted LOINC codes, `phenotype_icd10cm.csv` and
`codes_checked.csv`.
Edit the files in `verification/`, never the generated columns by hand.

    python -m tools.catalogue_verify fetch --date YYYY-MM-DD   # network: rereads the sources into evidence.json
    python -m tools.catalogue_verify build                     # offline: rewrites the CSVs
    python -m tools.catalogue_verify build --check             # CI (tests/unit/test_catalogue_verify.py)

What the columns mean:

- `verified = yes` on an item: its LOINC code was found in the NLM Clinical Tables LOINC service on `verified_date`;
  its long name is in `verified_source`. `code_fit` says whether a person read that name against the item:
  `exact` or `partial` (a row in `verification/loinc_decisions.csv`: `adopt`, `adopt_partial`, `fit_exact`,
  `fit_partial`; the note says how), `unreviewed` (no row yet), `none` (local item). `verified = no`: the item is
  local; `verified_note` lists the LOINC searches run and their hit counts. A local item whose name search found any LOINC term has a reviewed
  row in `verification/loinc_decisions.csv`; the build stops otherwise.
- A code reaches a CSV only when `evidence.json` holds it. Nothing is typed in from memory.
- Adopting a LOINC code retires the item's local id (kept in `loinc_decisions.csv` as `retired_local_id`); a
  retired id is never given to another item.
- `jlac10`: the 17-digit codes from the MHLW 特定健診 XML item table (付属2 Ver.4), the only public JLAC10 source
  that could be read (the JSLM pages refused automated reading). Items outside that table have no JLAC10 code here.
  `jlac10_map.csv` must give each mapped row a `fit` of `exact` or `partial` (the build stops otherwise), and
  `source_unit_ucum`, the MHLW unit in UCUM. When it differs from the item's `unit_ucum`, `unit_factor` must say
  how to convert (value in the item's unit = MHLW value x factor; CRP mg/dL x10, WBC /uL x0.001, platelets
  10*4/uL x10), or the build stops. A code for which the MHLW table gives no unit cannot fit a unit-bearing item
  exactly.
- Adopting a LOINC code appends the LOINC notice to `licence_notes`; other licence notes stay.
- Phenotypes: `verified = yes` when every library cohort id exists in PhenotypeLibrary 3.37.0 and every code in
  `codes` was found: ICD-10-CM (NLM Clinical Tables; a range such as `A15-A19` is checked category by category, and
  `(excl. M06.1)` codes are recorded as excluded, `use = exclude`), LOINC and ATC. It does not say the definition is clinically right.
  `phenotype_icd10cm.csv` has `codes_verified` (all codes exist) and `mapping_verified = no` throughout: the sets
  were made by hand from the cohorts' entry concept names, not from the OMOP Maps-to table (Athena refused).
- Other codes: ATC codes are checked against the WHOCC ATC/DDD Index, CDISC CT codelists (`cdisc_qrs`, `use =
  reference`) against the NCI EVS SDTM Terminology file, and every LOINC code in a note, a component list or a score
  file against NLM (with its check digit). Cells are scanned for code shapes with or without the word LOINC or ATC
  (a LOINC shape with a valid check digit; an ATC code of level 3 or deeper in a drug-exposure cell).
  `codes_checked.csv` lists each one with the name the source gives, so a reader can see what the code really is.
  ICD-O-3 is not checked (no public machine-readable source was read); MEDIS names and `local items` are names, not
  codes. OMOP concept ids are kept for the cohorts' entry concepts; SNOMED CT concept codes are not stored here
  (the SNOMED CT licence question is open, D-161). The entry concepts' names (OMOP concept names, which for SNOMED
  concepts are the SNOMED preferred terms) are still in `evidence.json` and `phenotype_icd10cm.csv`: the name check
  needs them. Whether they may stay is an open owner question under D-161.

`may_exclude` (items, phenotypes, `phenotype_icd10cm.csv`, `codes_checked.csv`): **unknown never excludes**; when
unsure, `no`. It is `yes` only for a code that was found in its public source, sits in an item's `loinc` or `jlac10`
column and was read against the item and found to fit exactly (`code_fit = exact`; `fit = exact` in
`jlac10_map.csv`). Everything else is `no`: unreviewed and partial fits, every phenotype and phenotype code (no
per-code fit review of phenotype codes yet), excluded codes, the hand-made ICD-10-CM sets (`mapping_verified = no`),
CDISC codelists, codes named in text, and anything not found. A loader (T-107) may let a `may_exclude = no` code or
phenotype raise a candidate or show evidence, never remove a patient: such a criterion is "unknown" when nothing else
decides it. `may_exclude = yes` says only that the code is real and means the item; the screening rules still need a
coded or confirmed fact, and proposed facts never count. Tests: `test_unknown_never_excludes`,
`test_the_shipped_catalogue_obeys_unknown_never_excludes`, `test_a_code_has_one_fit_everywhere`,
`test_every_code_shape_in_the_shipped_catalogue_is_registered`.

How this relates to the reference-data loaders (D-170 to D-175): the `jlac10` column says which MHLW 特定健診 rows
name the same thing as a catalogue item, by a person's reading of the names. It is not a JLAC10 to LOINC map and
must not be loaded as one; a site's own JLAC10 to LOINC file (D-174) is the only map. The WHO-only codes flagged
here (F00, I64, A16) are the same kind of difference that the WHO ICD-10 to ICD-10-CM bridge of D-173 handles.
