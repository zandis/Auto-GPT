# D-742 A memory limit met while the lake opens a snapshot is the lake's limit

- **Task:** NEW-B-41 (lane C2's review by running against the real lake service, NEW-SITE-5; placed by the
  integrator on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-41-lake-open-limit-is-503`), on top of NEW-B-35 (#563, which carries #549)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-675 (the status of a failed lake query: 503 where the lake cannot serve it, the box's limit among
  them), D-664 (what the lake says of a failure), D-80 / T-108a (the lake's bounded memory)

## Context

With the box's memory limit met while a snapshot was being opened (reading its layout: the first statement of a
new instance), `/query` answered 500 "OutOfMemoryException: LAKE-QUERY", where the same limit met
in the query answers 503 with `LAKE-LIMIT`: `Lake.connect` was outside the query's limit handler. Reproduced with a
256 KB limit on a real small lake.

## Decision

1. **`Lake.connect` turns the engine's out-of-memory into `LakeLimitError`** with the lake's limit sentence, as
   `query` does; a connection opened before the limit was met is closed. Both readers that open a snapshot (the
   query and the note search) get the same error; holds open none.
2. **The status rule and the error answer place the engine's own `OutOfMemoryException` as the limit** too (503,
   `LAKE-LIMIT` words), for a reader that meets it outside `connect` and `query`. **A build keeps its own words**
   (`LAKE-BUILD`): the limit's sentence speaks of a query and passes the engine's first line, which a build does
   not send. An out-of-memory error without a message is still answered.
3. **`/chunks/search` answers the limit 503** with the limit's words (it answered 500 "internal error": the route
   caught only a snapshot that is not there).
4. **The view an older snapshot gets (`patient.deceased`, schema < 4) no longer swallows the limit**: it was read
   as a table that is not there, and the reader then failed later as a question naming a missing column (422).

## What a person sees differently

A caller of the lake gets 503 and "LAKE-LIMIT: the lake query needed more than the box allows ..." for a limit met
while opening, as for one met in the query, from `/query` and from `/chunks/search`. Not changed: `/vec/s2b`
keeps reading any failure of the vector store as its fallback (200, `state: fallback`, the reason naming
`LakeLimitError`), and the cascade ranks on the fly.

## Tests

`tests/unit/test_lake_open_limit.py` (7 tests; all fail on the parent): a real small lake under a 256 KB limit:
the query and the open raise `LakeLimitError`; through the real service and client, 503 with `LakeLimitError:
LAKE-LIMIT`, and the same question answered once the limit is lifted; `/chunks/search` 503 with the same words; the
status rule and the answer place the engine's class; a build's out-of-memory keeps `LAKE-BUILD`; an empty message is
answered; the old layout's view does not swallow the limit.
**D-675's own test of the engine's classes** now lists `OutOfMemoryException` beside the interrupt as 503. No state
change.

## Review

One adversarial read-only review, run against the real lake service on a real small lake (routes, threads,
injected failures, mutants). Findings, fixed test-first in the second commit: `/chunks/search` answered 500 for the
limit; a build's out-of-memory got the query's limit sentence; an empty out-of-memory message raised `IndexError`
in the answer; the service test did not pin the open's wrapper (it now asserts the class name); the old layout's
view swallowed the limit; this record named holds as readers and claimed "never a 500". Seen and not changed: the
limit's sentence names the limit of the environment, which a second connection to an instance already open does not
use (D-80's shared instance, as before).
