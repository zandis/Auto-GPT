# D-1100 Imperfect hospital data: what "counted with its reason" and "silently wrong" mean for the test

- **Task:** lane H, card H-34 (was lane V's V-10; the integrator): "imperfect hospital data (cut-off file, the same
  file twice, wrong column count, Big5, 0000-00-00 and ROC years, a two-megabyte note, unknown code, two chart
  numbers, empty export): nothing crashes, each rejected row counted with its reason." Plan 8's V15 ("imperfect
  data").
- **PR:** this branch (`claude/lane-h-34-imperfect-hospital-data`)
- **Date:** 2026-11-18
- **Status:** reserved
- **Builds on:** STD-025 and T-615a (a row the mapping cannot read is rejected and counted by reason), T-615b and
  D-215 (a file in a character set the reader cannot be sure of is set aside, no U+FFFD reaches a record), T-611 and
  NEW-DIN-8 (an empty or missing table holds the night), DATA-017 (a duplicate key is counted), D-589 (ROC dates where
  a site declares them), NEW-DIN-6 (codes not mapped are counted), D-668 (a failure in words), D-1067 (every
  connector in release 1.0), D-1180 (the findings register)

## Context

The card asks two things of every imperfect file: nothing crashes, and each rejected row is counted with its reason.
Both need words a test can hold: what "a crash" is when the box runs the night as a process, where a count must be
for a person to see it, and when data in the lake is "silently wrong" rather than kept as the hospital sent it.

## Decision

1. **The entry point** is the box's own command line, `python -m adapter.cli run`, run as a process with the
   box's configuration (a settings file from the settings wizard, the lake step local). `adapter.run_job`, which the
   service starts at night, calls the same function with the same configuration.
2. **A crash** is a run that ends with a traceback instead of a report. A night that ends with a report that says it
   failed or is held is not a crash; it is judged by the next rules.
3. **Counted with its reason:** a row (or file) the night did not take is counted, under its table, with words that
   say what is wrong with it, in a file of the night (`completeness.json`, `reader.json`) **and** on a surface a
   person reads: the error lines of `ingest_report.json` (which the INGEST job's mail counts), the steward's batch
   row, or the audit event. A count in a file only is recorded as "counted" in the table and is a finding of its
   own (H34-11). A reason "a person can act on" names the table and the fault the file has (cut, a column missing, a
   character set), not only a symptom further on (a date that does not parse, a validation percentage).
4. **Silently wrong** is the lake's own tables of the night (the served Parquet) holding a fact the file does not
   say: a value cut short, a date moved, a text garbled (a replacement character or half-width katakana in the
   served snapshot), a row twice, one patient split or two merged by the box, a good row missing. It is "silently"
   wrong whether or not a count elsewhere mentions the table: data served wrong is wrong. **Kept as written** is
   apart: an impossible value (a birth after the visits, 9999-12-31) or two charts of one person served as the
   hospital wrote them; it is a finding when nothing counts it.
5. **The reference** is the clean export's own lake, compared with what the generator says it holds (equal for CSV,
   SQL and FHIR Bulk; SS-MIX2 adds the exporter's four discharge summaries), so a fault of the harness shows as a
   clean night that is not equal.
6. **Severity** by the card's rule: silently wrong data in the lake is High; a crash is High; a rejection not
   counted is Medium; a reason nobody can act on is Low or Medium. **Lane** by the file at fault: the source readers
   and the mapping are lane E's, the night's report and the steward's row lane B2's, the SS-MIX2 reader's repairs
   lane B2's (plan 10, 10B-1 to 10B-5).
7. **Files.** The bad files are made at run time in a scratch folder by `tools/imperfect_feed.py` and never
   committed; `make imperfect-feed` runs every case in every format the adapter reads; the results
   (`docs/plan/measurements/imperfect-feed-2026-11-18/results.json`) hold counts, states and the product's own
   words, never a cell. Formats not built (a live HL7 v2 feed, a live FHIR feed) are said to be not built.

## Consequences

The page `docs/plan/measurements/imperfect-feed-2026-11-18.md` and its `findings.json` (22 findings: 9 High, 8
Medium, 5 Low; lane E 18, lane B2 4). No product file changes. A fix in the adapter changes the page when the
harness is run again; the tests hold the harness, not the findings.
