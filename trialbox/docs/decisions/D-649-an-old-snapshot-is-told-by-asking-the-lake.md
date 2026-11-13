# D-649 A snapshot from before the site facts is told by asking the lake, not by reading an error's text

- **Task:** NEW-TRUST-6, lane A2's place (`services/matching/proposed.py`), from lane C2's list in D-700
- **PR:** this branch (`agent/NEW-TRUST-6-proposed-table-probe`), cut from lane C2's #505 (`cff04eb4`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train)
- **Builds on:** D-700 (an error's text across services), D-127 / F-04 (a list never silently drops the rule)

## Context

A snapshot built before step 5b has no `site_fact` table and holds no proposed fact. `Proposed.load` and
`site_basis` told such a snapshot from any other failure by words in the error's text ("site_fact" with "exist"
or "Catalog"). The text was not shown to anyone, but it decided whether the proposed-fact rule applied. An
error's text is whatever its author put in it: another failure whose text holds those words dropped the rule
silently, and a reworded engine message stopped every run on an old snapshot.

## Decision

After a query of `site_fact` fails, the lake is asked one question (`TABLE_SQL`: how many tables or views of that
name the snapshot has; `duckdb_tables()` and `duckdb_views()`, which the lake's query guard allows). Only one row
with the integer 0 means "no site facts". Any other answer, and a failure of the question itself, leaves the first
failure to stop the run. The question is asked only after a failure: a snapshot with the table costs nothing more.

A wrong "no site facts" now needs two things at once: the table's query fails, and the lake says the table is not
there.

## Test

`tests/unit/test_proposed_old_snapshot.py` (over a DuckDB in memory behind the lake's own query guard): the old
snapshot whatever the error's text; the old words in another failure's text on a snapshot that has the table;
the question failing; every answer that is not a clear no; a view counts as there. `test_one_rule.py`: its
old-lake stand-in now answers the question (it raised for every query, which no lake without the table does).
`matching/proposed.py` is off the list of `tests/unit/test_error_text_across_services.py`.
