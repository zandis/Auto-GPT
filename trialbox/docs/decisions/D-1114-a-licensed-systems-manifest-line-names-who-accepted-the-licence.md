# D-1114 A licensed code system's manifest line names the person who accepted its licence

- **Task:** lane H, card H-5 (TERM-2), on D-1028 point 4 (LOINC, WHO ICD-10 and ATC are loaded at install and not
  committed) and lane E's note on #639 that LOINC needs a named person to accept Regenstrief's licence
- **PR:** this branch (`claude/lane-h-5-term2`)
- **Date:** 2026-11-17
- **Status:** proposed
- **Builds on:** D-858, D-1028, D-314 (WHO-only categories)

## Decision

1. **Three loaders for the licensed systems**, each from the site's own copy:
   - `loinc` reads Regenstrief's zip (its `LoincTable/Loinc.csv`) or the CSV into `loinc_table`: code, long common
     name, short name, component, specimen, class, status.
   - `icd10who` reads WHO's ClaML (or a code and title table) into `icd10_who`. A ClaML file that declares an entity or
     an internal DTD is refused. Its external DTD reference is dropped and never fetched.
   - `atc` reads the ATC index exported as CSV or TSV (`ATC code`, `ATC level name`) into `atc_index`. No DDD is read.
2. **`--accepted-by` is required: a person's name.** The manifest line records `licence` (the licence the table is
   under), `licence_accepted_by` and `licence_accepted_on` (default: the day of loading). A missing name, or a word
   that names nobody (`yes`, `admin`, `IT`, digits), is refused, and nothing is written.
3. **A licensed table whose line names nobody is refused.** It gets the same refusal as TERM-1's for a missing line or
   other bytes: it is never read, the mapper reports it (`installed_problems`), and `trialbox doctor`'s `terminology`
   line is FAIL. The doctor and `status` print "licence accepted by <name> on <day>" for each loaded licensed table.
4. **How they map (step 2e of `Terminology.map`, after TERM-1's step 2d and before the model's):**
   - a LOINC long common name or short name resolves to its code. A LOINC component resolves to its blood, serum and
     plasma codes, for review.
   - a WHO ICD-10 title resolves to its code (a category: its family under the WHO URI, D-314), only after ICD-10-CM.
   - an ATC name resolves to its code (a group: its substances, as a family).
   - deprecated LOINC codes are left out.
