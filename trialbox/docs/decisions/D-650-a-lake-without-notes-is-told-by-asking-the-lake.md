# D-650 A lake without a note table is told by asking the lake, not by reading an error's text

- **Task:** NEW-TRUST-6, the cascade's place (`services/matching/cascade/engine.py`), found by the review of D-649
- **PR:** this branch (`agent/NEW-TRUST-6-note-table-probe`), cut from #517 (`95428c69`, D-649)
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train)
- **Builds on:** D-649 (the same remedy for `site_fact`), D-700, D-127 / F-04

## Context

A lake with no `document` table has no notes. (The lake's own store builds the table always, empty when there
are no notes, also for the MIMIC demo; the case is live only for a lake made by hand or by other software.) The
cascade's note reader tolerated that one failure and told it from any other by a helper, `missing_table`, that read the error's text: the table's name
with "does not exist" or "Catalog Error".

**What a mistaken reading did:** another failure of the note query whose text held those words (run for this
card: a 503 saying "Catalog busy; document does not exist in the cache") was taken for a lake without notes. The
reader returned no notes and the run went on: every note pair of the run became a data gap, which the cascade
answers "unknown". It leans to unknown, never to a pass: no patient was let through on it. But a whole run's note
criteria went unknown without the run saying why, which D-127 forbids. The other way round, a reworded engine
message stopped every run on a lake without notes.

**Why the scan of D-700 did not see it:** that scan looks at statements inside an `except` block that use the
caught error's text. Here the `except` block held `if not missing_table(exc, "document")`: the text was read in a
helper, called from an `if`.

## Decision

1. The question of D-649 is one module, `matching/lakeprobe.py`: `rows_or_no_table(lake, sql, params, snapshot,
   table)` runs the query; after a failure it asks the lake how many tables or views named `table` the snapshot
   has; only one row with the integer 0 means "no such table"; any other answer, and a failure of the question,
   leaves the first failure to stop the run. With no snapshot named, the query again and the question go to the
   snapshot the lake names as current. `proposed.py` (D-649) and the cascade's note reader both use it.
2. `missing_table` is removed. Nothing in the matching service reads a caught error's text to decide anything; a
   test over the service's source holds that (one listed place keeps a model's own refusal as an answer's error).
3. The table's name in the question is a plain lower-case name written in this code (`site_fact`, `document`);
   `table_sql` refuses anything else.

## Test

`tests/unit/test_cascade_lake_errors.py`, rewritten: it tested the helper's reading of texts, which is gone. It
now runs the cascade's note reader over a DuckDB in memory behind the lake's own query guard: a lake with notes;
a lake without, whatever the error's text; every other failure stops, also with the old words in its text (the
table is there, the lake answers 1); the question failing; every answer that is not a clear no; an unpinned run.
The four "other errors are not mistaken" cases of the old file are kept as cases of the new one.
`tests/unit/test_proposed_old_snapshot.py` (D-649) passes unchanged.
The test's last part looks at every use of a caught error in the service's source, whatever its spelling
(`str`, `repr`, `format`, an f-string, `%`, `.args`, the error passed on to a helper), and at the scan itself.

## Review

One adversarial review by running, on the first form (`3c6167af`). Verdict: merge; no HIGH or MED in the card.

| Finding | Confirmed | What was done |
|---|---|---|
| **MED, outside this card and this lane, the same defect in a worse direction:** `libs/tb_common/optout.py` `registry_state` tells a lake without a `consent` table by the error's text; another failure with those words gives "no registry", and the cascade then applies no opt-out: people who said no are listed. It leans to a pass | by running (the helper), by reading (the cascade's use) | not in this card: reported to the integrator at once. The remedy is the same question; `lakeprobe` would move to the library |
| LOW: `services/edc/prefill.py` returns no site facts for any failure whose text names `site_fact` | by reading | reported with the above |
| LOW: the source test saw one spelling only | by reading | the scan looks at every use of a caught error; a test of the scan |
| LOW: with the lake answering None for its current snapshot, a mutant that asked the question of "current" after all survived; a view of the name was untested here | by running | tests |
| LOW: on an unpinned run, a failure after the first (the lake's naming, the second try) was raised in place of the first | by running | the first failure is the one raised; test |
| LOW: the record said the MIMIC demo has no note table; the store builds one always | by running | the record says so |
| LOW: four places elsewhere swallow a lake failure without reading its text (`screen.py` confirmed facts and practitioner names, `coded_values.py` display, `feas_profile.py` counts) | by reading | not in this card: listed for the integrator |

Held (the reviewer's runs): a real lake in process and over HTTP with the table, with it dropped by hand, by
generation name, an unknown snapshot; no object of the name in the full-text schema; a view, another schema, a
temporary table or an attached database each count as there (the run stops); with the two catalogue functions
forbidden in the lake's guard the note reader stops; 15 of 17 mutants killed before the fixes, the two survivors
are the tests added; `proposed.py` moved line for line.
