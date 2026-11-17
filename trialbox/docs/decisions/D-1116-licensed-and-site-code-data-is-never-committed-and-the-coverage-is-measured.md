# D-1116 Licensed and site code data is never committed (a guard test); the coverage is measured by a tool

- **Task:** lane H, card H-5 (TERM-2), on D-1028 points 2 and 4
- **PR:** this branch (`claude/lane-h-5-term2`)
- **Date:** 2026-11-17
- **Status:** proposed
- **Builds on:** D-858 (lane E's measurement of P1b's drafted concepts), D-201 (scratch and test roots)

## Decision

1. **Where the site's files go.** The site's IT stages LOINC, WHO ICD-10, ATC and the site's own lists in
   `deploy/site/terminology/`. Git and the image's build context ignore it. A loaded folder inside the tree
   (`data/terminology/`) is ignored too. `.gitignore` names both folders.
2. **The guard** (`tests/unit/test_term2_licensed_tables_never_committed.py`) fails when:
   - a tracked file sits in either folder;
   - a tracked file is named like a table the loader writes for them (`loinc_table`, `icd10_who`, `atc_index`,
     `site_*` as Parquet);
   - a tracked data file looks like one of them: LOINC's table, a ClaML file, the ATC index, a site list in the
     loader's format, or a manifest that records a licence acceptance.

   The detector is shown each kind first. The tests of TERM-2 write their LOINC, WHO ICD-10 and ATC tables at run
   time: made-up codes, marked SYNTHETIC.
3. **The measurement is a tool.** `python -m tools.terminology_coverage <raw-traces.json> [--installed DIR]` maps
   every `concept_candidates` entry of a launch's `extract_criteria` calls (no model, no synonym dictionary) and
   counts by domain. On launch P1b's `sigir.tgz` it reproduces lane E's figures: 58 of 1,273 before TERM-1, and 266
   with TERM-1 (lane E's first draft said 270). The figures and what remains are in
   `docs/plan/measurements/term2-coverage-2026-11-17.md`.
