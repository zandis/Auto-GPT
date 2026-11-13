# D-676 The twin's reader does not take a failing lake for an older snapshot

- **Task:** NEW-B-35 (the first of the open callers of D-675; placed by the integrator on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-35-twin-says-a-failed-lake`), on top of NEW-B-34 (#549, `c257a486`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-675 (the status of a failed lake query says who failed: 4xx the question, 5xx the lake),
  D-664 (the engine's sentence about a missing column is kept whole), D-673 (`LakeQueryFailed` carries the status)

## Context

`patient_profile.twin.lake_schema` asks a snapshot for its layout version (`SELECT schema_version FROM
lake_meta`). A snapshot of schema 1 has no such column, and the lake still reads schema 1
(`MIN_READABLE_SCHEMA`). The handler around the question caught **every** error and answered 1.

So a lake that failed on that one question (a limit, an I/O error, a snapshot that is not there, a layout this
reader does not serve) was read as "an older snapshot". `read_lake` then asked for the rows with the provenance
columns as NULL. If those queries passed, the night's twins were built and kept **without the provenance of
their rows**, and nothing said so.

## Decision

1. **A failure of the lake stops the build.** It is not said as "could not be read" and gone past: the version
   decides which columns the twin's rows carry, and a twin built on a guess of it is a wrong record that is kept.
   The six row queries that follow in `read_lake` have no handler and stop the build already; the first question
   now does the same. The job that builds the twins then ends "The lake service failed." with the status
   (D-673), and the next night or a retry builds them.
2. **Whether the version column is there is asked of the lake, not read from an error** (the way of D-649 to
   D-651, `tb_common.lakeprobe`, for a missing table): one question first, `twin.VERSION_COLUMN_SQL`: how many
   columns `schema_version` the snapshot's `lake_meta` has. One row with the integer 0 is schema 1. A number
   above 0: the version is asked for, as before. Any other answer (no row, two rows, a null, a text, a float, a
   boolean) is `TwinError`: the lake did not say.
3. **There is no handler left around either question.** A failure of the lake (5xx) and a fault of the question
   (4xx: a fault of this code) both go on and stop the build. Nothing reads an error's text or status here, so
   the lake as a service and the lake as a library (`LakeLocal`) behave the same without a rule for each.

The first cut of this card kept a handler and read schema 1 from the engine's sentence about the column with
the status 422. It was dropped before any push: a sentence is whatever its author put in it, and lane A2's scan
(D-651: no code decides by the text of an error it caught) would have counted it.

## What a person sees differently

On a night when the lake fails exactly on the layout question, the twin build fails with the lake's status
where it "passed" before. A healthy lake is asked one small question more per build (not per patient). Nothing
else changes for a lake of any readable layout.

## What this does not do

- The other open callers of D-675 (`coded_values.attach`, `feas_profile.build`, `screen.practitioner_names`,
  `screen.confirmed_facts`, `readiness.unknown_share` and `feed_loaded`) are their lanes'.
- A stand-in lake of a test or a tool that answers every query with the same rows, or that fails on a question
  it does not know, now meets a new question. The suite's twin tests pass unchanged.
- The question counts a column named `schema_version` in any table named `lake_meta` the connection sees. The
  lake opens one snapshot per query, and refuses a snapshot without `lake_meta` before any query (`LAKE-SCHEMA`).
- Opted-out twins are erased before the lake is read, as before: a stopped build does not hold an erasure back.

## Tests

`tests/unit/test_twin_lake_failure.py` (25 tests; all fail on the parent's `twin.py`, the twenty parametrised
ones because it answers 1 where the lake failed): each of the twelve failures of the lake and the eight faults
of the question (the engine's own "column not found" among them) stops, through the real route and in process;
only the lake's plain 0 is schema 1, and seven answers that are not a plain number are refused; a failure of the
version question after the column was found stops; `read_lake` asks for no rows after the layout question
failed; a real small lake says its version through the service and in process, and a night it does not hold is
503, not schema 1; **a real lake file without the version column** (the column dropped from a built snapshot)
is schema 1 through the service and in process, and its rows are read without provenance, as before. The
caller's line in `tests/unit/test_lake_query_status.py` moves from OPEN to "no handler: the error goes on". No
state change is added.
