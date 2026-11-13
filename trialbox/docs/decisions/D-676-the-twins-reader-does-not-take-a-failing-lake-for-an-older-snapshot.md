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
2. **Only one answer is read as schema 1**: a fault of the question (D-675's 422: the engine's "wrong statement"
   group) **with** the engine's sentence `Referenced column "schema_version" not found`. Both are asked for: a
   5xx whose words happen to hold the sentence is still the lake failing.
3. **Any other 4xx stops too**: it is a fault of the code (the guard refused the statement, another column, a
   missing `lake_meta`), and shows as one.
4. **The lake as a library** (`LakeLocal`: tools, the adapter's local mode) raises the engine's classes, with no
   status: the error is placed by the lake's own rule (`lake.store.query_failure_status`, imported where it is
   needed; `patient_profile` gets no import of the lake at module level).

## What a person sees differently

On a night when the lake fails exactly on the version question, the twin build fails with the lake's status
where it "passed" before. Nothing changes for a healthy lake of any readable layout.

## What this does not do

- The other open callers of D-675 (`coded_values.attach`, `feas_profile.build`, `screen.practitioner_names`,
  `screen.confirmed_facts`, `readiness.unknown_share` and `feed_loaded`) are their lanes'.
- A fake lake in a test that raises a bare error to mean "schema 1" would now stop; none was found in the suite.
- The sentence is the engine's of the pinned version. A test asks the engine itself for it, so a version that
  words it otherwise fails the test, not the night.
- Opted-out twins are erased before the lake is read, as before: a stopped build does not hold an erasure back.

## Tests

`tests/unit/test_twin_lake_failure.py` (23 tests; 22 fail on unchanged code): the engine's own error for a
`lake_meta` without the column is schema 1, through the real route and in process; each of the twelve failures
of the lake and each of the seven other faults of the question stops, both ways; an I/O error whose words hold
the sentence stops; `read_lake` asks for no rows after the version question failed; a real small lake says its
version through the service, and a night it does not hold is 503, not schema 1. The caller's line in
`tests/unit/test_lake_query_status.py` moves from OPEN to its own kind. No state change is added.
