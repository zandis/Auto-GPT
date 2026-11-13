# D-673 An answer of the lake without its key is an error of the lake

- **Task:** NEW-B-32 (item 5 of NEW-B-31's review; placed by the integrator on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-32-lake-client-answers-without-their-key`), on top of NEW-B-31 (#527,
  `b3c7e348`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-672 (`snapshot()` says "none" only for a healthy lake that has none), D-489 / D-490 (promote,
  generations, pinned holds), D-403 (holds), D-449 (the vector ranking falls back)

## Context

After D-672 the client's other readers still turned a 200 answer of the wrong shape into a plain value:

| reader | a 200 without its key was read as | which means |
|---|---|---|
| `promote` | False | "a newer night is served": the publish ends without serving the night it built |
| `generation` | None | "the lake has none, or the date was built before generations" |
| `site_in_sync` | None | "not known": the site's publish keeps the old answer |
| `hold` | the snapshot's name | "held, not pinned": the job reads a date another build can replace |
| `release` | False | "there was no such hold" |
| `holds`, `put_site`, `chunks_search` | a `KeyError` or `AttributeError` of the client's own code | an internal error |

A 200 of the wrong shape is what a proxy, a half-deployed service or another responder gives.

## Decision

1. **One reader for every answer**: `_object` (the answer is a JSON object) and `_key` (the key is there and of
   its kind). Anything else raises `LakeBadAnswer`, a `ServiceError` of the lake, with what is missing and never
   the body. A job that meets it ends "The lake service failed."
2. **The lake's own words for "no" and "not known" stay answers**: `promoted: false`, `released: false`,
   `generation: null` (a hold that is not pinned; a date built before generations), `site_in_sync: null`.
   A key that is missing, or of another kind (`promoted: "yes"`, `generation: 7`), is the error.
3. **A query's 200 that is not a table** raises `LakeBadAnswer` too.
4. **The vector ranking falls back** on a 200 it cannot read, as its docstring said and the code did not (a 200
   that was not JSON raised into the run).
5. **A rebuild job's state** (`start_rebuild`, `rebuild_state`) must be an object; its keys are the job's own
   and are read by `follow_rebuild`, which already raises on a state it does not know.
6. A refusal of the lake (4xx, 5xx) raises as before; this card is about 200 answers.

## Every reader

`tests/unit/test_lake_client_answers.py` lists every public method of `LakeHttp` with its path, a right answer
and what the call gives for it. A test over the client's source fails when a method reads an answer with
`.json()` itself, or when a public method is not on the list.

## What this does not do

- The lake as a library (`LakeLocal`) has no answers to read.
- The callers are not changed: each already had to handle an error of the lake from these calls (a refusal, a
  lake that cannot be reached). What a person sees is "The lake service failed." where a wrong 200 was read as a
  plain answer before.

## Tests

`tests/unit/test_lake_client_answers.py`: for ten readers, a right answer reads as before; eight wrong 200
answers each raise `LakeBadAnswer` (not JSON, not an object, an object without the key); eleven answers with the
key of another kind; the lake's own "no" and "not known"; a refusal raises as before; the vector ranking falls
back; a query's answer that is not a table; the test over the client's source. No state change is added.
