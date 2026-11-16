# D-858 A condition's name resolves through ICD-10-CM itself: its codes, its blocks and its Alphabetic Index

- **Task:** TERM-1 (the review of GPU launch P1b; the owner: "do everything to remedy these ... make it works")
- **PR:** this branch (`agent/TERM-1-icd10cm-names-blocks-index`)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** D-122 (the full ICD-10-CM list, for code lookups only), D-113 and D-518 (families: a record coded
  inside a family but outside the list is unknown), D-314 (WHO-only categories)

## Decision

1. **Measured first.** On P1b's public protocols (ClinicalTrials.gov, the SIGIR set), the compiler drafted 588
   condition concepts; the tables resolved 47. Name matching read only the 79 curated rows. With this change, 255
   resolve (measured offline on the stored drafts; the model's step not counted).
2. **A new step 2d in `Terminology.map`, for conditions only**, after every curated step and before the model's:
   - a block's or chapter's name (`Ischemic heart diseases` I20-I25, `Malignant neoplasms`, `Cerebrovascular
     diseases`): every category in it, each kept as a family;
   - a code's own description: that code (a category: its family);
   - an Alphabetic Index term, following at most two "see" references, the words also read turned
     (`cerebrovascular accident`: `Accident, cerebrovascular`): its code's category, as a family;
   - before these, a short list of our own for trial words and abbreviations (COPD, CHF, MI, CKD, T2DM, SLE, "cancer",
     "renal insufficiency"), written as the index or a block names them, or as the categories themselves.
   An index term or one of our words is for review; a block or a description is not. Curated rows still win.
3. **Data.** `tools/icd10cm_cms.py` reads CMS's code-tables zip (public domain, US government) and writes
   `src/icd10cm_blocks_2026.csv` (280 blocks and chapters) and `src/icd10cm_index_2026.csv.gz` (28,792 main terms
   and first-level subterms); `tools/build_terminology.py` makes them Parquet. The zip itself is not kept. The
   licence register's ICD-10-CM row lists the four files.
4. **Release.** The two tables are read beside the code tables, else from the shipped ones (a box's tables built
   from its vocabulary hold codes only). They are not part of the release id: they change only with an ICD-10-CM
   release, which changes `icd10cm_full`.
5. **One test's input moved, on purpose:** `test_parser_terminology_review` showed the model's step with "type 2
   diabetes", which ICD-10-CM now resolves; it uses a name nothing can place.
6. Not in this card: labs (LOINC), drugs (an ingredient-to-ATC table) and procedures (ICD-10-PCS or NHI codes) wait
   for the owner's answers on #639; the model's candidates from the full list is lane A2's call site.
