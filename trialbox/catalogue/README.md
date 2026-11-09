# Clinical item catalogue

The items a patient database, the patient profile and trial screening need, each mapped to an existing standard
where one exists. Data only; no runtime code reads it yet. Design and findings:
`docs/reviews/2026-11-09-clinical-item-catalogue.md`.

| File | What it holds |
| --- | --- |
| `items.csv` | one row per item: names (en, ja, zh-TW), specialties, type, value type and range, UCUM unit, LOINC code or `local` with a proposed concept id ≥ 2,000,001,001, CDISC QRS code, components, formula reference, source, licence, what may be stored, how it is documented, typical criterion phrasing, an extraction hint, Japan and Taiwan notes, and whether the code was verified on 2026-11-09 |
| `scores/*.yaml` | one file per derived score: inputs, formula, rounding, windows, edge cases, worked examples from published sources (see `scores/README.md`) |
| `phenotypes.csv` | the initial phenotype list per specialty, linked to OHDSI Phenotype Library cohort ids (3.37.0) or marked local |
| `specialties.csv` | each specialty template: core scores, labs and findings, social items, phenotypes, finder-rule examples, patient-vector features, and what the first pass left out |

Rules:

- A LOINC code in `items.csv` is a code and a name only, under the LOINC licence (free, notice required). No
  licensed questionnaire text is in this folder; `storable` says per item whether a site may store the score,
  the item values, or the text.
- `omop_concept_id` is blank for LOINC items: the id is resolved from the CONCEPT table (vocabulary LOINC, the code)
  when the vocabulary pack is loaded. Athena refused this session's requests, so none were copied by hand.
- Local ids are assigned in file order inside the TB-SHARED block. Rows are appended, never reordered.
- Chinese names are Taiwan usage (zh-TW); Japanese names follow common chart usage, not always the official translation.
