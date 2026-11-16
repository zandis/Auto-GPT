# D-858 A condition's name resolves through ICD-10-CM itself: its blocks and index ship, a later release loads at install

- **Task:** TERM-1 (the review of GPU launch P1b; the owner: "do everything to remedy these ... make it works"),
  on the owner's rulings D-528 (code systems loaded at install) and D-529 (public-domain US government code data,
  ICD-10-CM's codes, blocks and index included, may be committed and shipped)
- **PR:** this branch (`agent/TERM-1-icd10cm-names-blocks-index`)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** D-122 (the full ICD-10-CM list), D-113 and D-518 (families), D-314 (WHO-only categories), D-171

## Decision

1. **Shipped, and loadable at install (D-529, D-528).** ICD-10-CM FY2026's blocks and chapters (280) and its
   Alphabetic Index's main terms and first-level subterms (28,792) are committed beside the full code list:
   `src/icd10cm_blocks_2026.csv`, `src/icd10cm_index_2026.csv.gz` (written by `tools/icd10cm_cms.py` from CMS's
   code-tables zip, US public domain) and their Parquet, under the `icd10cm` licence-register row. A later release
   is loaded onto a box without a new image by `python -m tools.terminology_install icd10cm <zip>` into
   `TB_TERMINOLOGY_DIR` (default `/data/terminology`), each table with its line in `manifest.json`: source (the zip's
   name and sha256), version, licence note, the table's sha256, rows, when loaded; the mapper then reads it in place
   of the shipped table. A loaded table with no line, or whose bytes differ from it, is refused: never read, the
   shipped table answers, and the mapper and `trialbox doctor` report it (`terminology`: FAIL; nothing loaded: PASS,
   the shipped tables answer). The same loader, manifest and refusal serve the code systems that are not committed
   (LOINC, WHO ICD-10, ATC, a site's own lists: D-528), as their loaders come.
2. **A new step 2d in `Terminology.map`, for conditions only**, after every curated step and before the model's: a
   block's or chapter's name (every category in it, as families); a code's own description in the shipped full list
   (that code; a category: its family); an Alphabetic Index term, following "see" references and read turned
   (`cerebrovascular accident`: `Accident, cerebrovascular`), to its code's category; before these, a short list of
   our own English trial words and abbreviations (COPD, CHF, MI, CKD, T2DM, SLE, "cancer"). An index term or one of
   our words is for review; curated rows still win.
3. **Measured offline** on P1b's stored drafts (public ClinicalTrials.gov protocols), with the 2026 release loaded by
   the same command into a private folder: of 588 drafted condition concepts, 47 resolved before; 162 with the
   descriptions and our words alone; **255 with the blocks and index** (shipped, or the same release loaded).
4. **Which ICD-10.** Taiwan's NHI codes diagnoses in ICD-10-CM (its Chinese edition: 2014 until 2024-12-31, 2023
   from 2025-01-01, D-171), not WHO ICD-10; the US release's blocks and index name the same categories. The
   differences that matter for mapping: ICD-10-CM adds detail below the WHO category (up to seven characters), splits
   some WHO categories (diabetes E08-E13 where WHO has E10-E14; hypertension I10-I1A) and lacks five WHO categories
   (E14, I64, F00, B24, C97: D-314 keeps them as WHO families, so a WHO-coded record is unknown, never a silent
   no). A block found here is ICD-10-CM's; a site's own code list stays the primary source (D-528 point 2).
5. **One test's input moved, on purpose:** `test_parser_terminology_review` showed the model's step with "type 2
   diabetes", which the shipped list's descriptions now resolve; it uses a name nothing can place.
6. Not in this card: labs (LOINC), drugs (through the NHI drug codes, D-528 point 6) and procedures, and the model's
   candidates from the full list (lane A2's call site).
