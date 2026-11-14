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
   The eight row queries that follow in `read_lake` have no handler and stop the build already; the first
   question now does the same, and what happens then is what happened for them:
   - the twins are built after an ingest that has passed (`twin.after_ingest`, its only caller in the services);
     that step never fails the ingest: it logs `twin build after the ingest did not run: <the error's type>`
     and answers None;
   - nothing is kept: the store is written only after the lake was read;
   - the night's ledger entry for "twin" stays "building" (D-491), not "finished";
   - the next ingest builds them. No job ends with the lake's sentence or status for this: it is in the log.
2. **Whether the version column is there is asked of the lake, not read from an error** (the way lane A2's
   D-649 to D-651 ask for a missing table; those are on train 14, not on this branch): one question first, `twin.VERSION_COLUMN_SQL`: how many
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

On a night when the lake fails exactly on the layout question, no twin is built and the night's "twin" entry
stays "building", where twins without provenance were kept and the entry read "finished" before. The ingest
passes either way; the reason is in the log by the error's type. A healthy lake is asked one small question more per build (not per patient). Nothing
else changes for a lake of any readable layout.

## What this does not do

- The other open callers of D-675 (`coded_values.attach`, `feas_profile.build`, `screen.practitioner_names`,
  `screen.confirmed_facts`, `readiness.unknown_share` and `feed_loaded`) are their lanes'.
- A stand-in lake of a test or a tool that answers every query with the same rows, or that fails on a question
  it does not know, now meets a new question. The suite's twin tests pass unchanged.
- The question counts a column named `schema_version` in any table named `lake_meta` the connection sees. The
  lake opens one snapshot per query, and refuses a snapshot without `lake_meta` before any query (`LAKE-SCHEMA`).
- **A snapshot as schema 1 or 2 built it cannot be read by the twin's reader at all**, before this card and
  after: the reader asks for `encounter.status`, which came with schema 3, and the engine refuses the question.
  The lake itself reads schemas 1 to 4. So "schema 1" here is an answer the reader keeps giving correctly, not
  a build that passes. Found by this card's review; sent to the integrator; not changed here.
- The layout question and each row query open the snapshot on their own, as before; a named generation pins them
  to one file, a plain date does not.
- Opted-out twins are erased before the lake is read, as before: a stopped build does not hold an erasure back.

## Tests

`tests/unit/test_twin_lake_failure.py` (26 tests):

- **the defect end to end**, on a real lake and a real store: the lake fails on the layout question only; the
  night step keeps no twin and answers None, and the next run builds both. On the parent's `twin.py` it fails:
  two twins were kept;
- each of the twelve failures of the lake and the eight faults of the question (the engine's own "column not
  found" among them) stops, through the real route and in process; on the parent each answered 1;
- only the lake's plain 0 is schema 1, and seven answers that are not a plain number are refused; a failure of
  the version question after the column was found stops (the new contract, against a stand-in);
- `read_lake` asks for no rows after the layout question failed;
- a real small lake says its version through the service and in process, and a night it does not hold is 503;
- a built snapshot with **only the version column dropped** answered 0 and read as schema 1; D-741 (NEW-B-40) replaced
  that test: a snapshot older than schema 3 is now refused with a sentence, and a schema-3 file is read.

The caller's line in `tests/unit/test_lake_query_status.py` moves from OPEN to "no handler: the error goes on".
No state change is added.

## Review

One adversarial, read-only review of the head by a fresh agent, by running. It saw, on real built lakes: the
question answers a Python int 1 and the right version through the lake service (plain date and a named
generation), in process, and through the job's and the re-run's pinned lakes; the connection holds no other
database and no other `lake_meta`; the guard lets the question through with no rewrite or row limit; altered
files of schema 3, 2 and 1 answer 1 or 0 as their `lake_meta` has the column or not; lane A2's scan (train 14)
finds nothing in this file; every test file that builds twins passes. Its findings, all taken: this record
said a job ends with the lake's sentence (it does not: the log and the ledger, above); the dropped-column test
was called a real schema-1 snapshot (renamed, and what it is not is said); "six row queries" (eight); the
schema 1-2 finding above. Not verified by it: the service-token check with auth enforced; a file built by an
old TrialBox.
