# D-742 A memory limit met while the lake opens a snapshot is the lake's limit

- **Task:** NEW-B-41 (lane C2's review by running against the real lake service, NEW-SITE-5; placed by the
  integrator on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-41-lake-open-limit-is-503`), on top of NEW-B-35 (#563, which carries #549)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-675 (the status of a failed lake query: 503 where the lake cannot serve it, the box's limit among
  them), D-664 (what the lake says of a failure), D-80 / T-108a (the lake's bounded memory)

## Context

With the box's memory limit met while a snapshot was being opened (loading the full-text extension, setting the
instance up, reading the layout), `/query` answered 500 "OutOfMemoryException: LAKE-QUERY", where the same limit met
in the query answers 503 with `LAKE-LIMIT`: `Lake.connect` was outside the query's limit handler. Reproduced with a
256 KB limit on a real small lake.

## Decision

1. **`Lake.connect` turns the engine's out-of-memory into `LakeLimitError`** with the lake's limit sentence, as
   `query` does; a connection opened before the limit was met is closed. Every reader that opens a snapshot (the
   query, the search, the chunks, the holds) gets the same error.
2. **The status rule and the error answer place the engine's own `OutOfMemoryException` as the limit** too (503,
   `LAKE-LIMIT` words), wherever a reader met it.

## What a person sees differently

A caller of the lake gets 503 and "LAKE-LIMIT: the lake query needed more than the box allows ..." for a limit met
while opening, as for one met in the query; never a 500 "the lake broke".

## Tests

`tests/unit/test_lake_open_limit.py` (3 tests; all fail on the parent): a real small lake under a 256 KB limit:
the query and the open raise `LakeLimitError`; through the real service and client, 503 with the limit's words, and
the same question answered once the limit is lifted; the status rule and the answer place the engine's class.
**D-675's own test of the engine's classes** now lists `OutOfMemoryException` beside the interrupt as 503. No state
change.
