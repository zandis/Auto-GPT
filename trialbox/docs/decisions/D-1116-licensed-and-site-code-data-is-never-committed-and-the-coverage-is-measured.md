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

## After the class B review (same PR)

1. **The guard scans the whole repository** (from its root, not `trialbox/` only), and looks into more files:
   - zip, xlsx and gz files, including the zip's member names (`Loinc.csv`), its ClaML files and an xlsx's header
     cells;
   - UTF-16 files with their BOM;
   - files separated by `;` or `|`.
2. **What it calls LOINC, ATC or a site list:**
   - LOINC is matched on its `LOINC_NUM` column alone, and the ATC index on `ATC code` too.
   - A site list is any file with `local_code` or `local_name` beside `code`, whatever its other columns.
   - Such a file passes only when the licence register accounts for its path as own work, synthetic or cleared
     (the adapter's demo maps). A site's own list has no such row: its row is `site-loaded` and has no paths.
3. **"Nothing changes when nothing is loaded" is a test.** The mapper's answers to a fixed list of names are the same
   with no folder and with an empty one, and none comes from TERM-2's steps. The goldens stay identical.
