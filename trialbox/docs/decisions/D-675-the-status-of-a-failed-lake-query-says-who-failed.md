# D-675 The status of a failed lake query says who failed: the question or the lake

- **Task:** NEW-B-34 (from lane C2's review by running of its patient-check card against the real lake service;
  placed by the integrator on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-34-lake-query-status-says-who-failed`), on top of NEW-B-32 (#539, `bd7d6d2c`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-664 (what the lake says of a failure: fixed sentences, never a row's value), D-673 (a failed
  query is `LakeQueryFailed`, a `ServiceError` of the lake with the status), D-672 (a lake that cannot answer is
  not an empty lake)

## Context

The lake's `/query` answered with:

- 400 for a statement its guard refused;
- **422 for every other error**: the engine's complaint about the question (a column that is not there, a value
  that does not convert) and the lake's own failures (an I/O error, a snapshot too old, the memory limit) alike;
- 404 for a snapshot that is not there.

A caller could not tell "my question is wrong", which is a fault of its code and must stop it, from "the lake is
failing", which it should say and never read as "no data". Lane C2's patient-check route had to treat "whatever
its status but 400" as the lake failing.

## Decision

1. **4xx is a fault of the question; 5xx is a failure of the lake** (`lake.store.query_failure_status`):

   | status | what | which errors |
   |---|---|---|
   | 400 | the guard refused the statement | `SqlRejected` (as before) |
   | 422 | the engine refused the question | what the engine files under a wrong statement or wrong data: the DB-API groups `ProgrammingError`, `DataError`, `NotSupportedError`, `IntegrityError` (a table or column that is not there, a value that does not convert); the lake's refusal in words (`LakeSaid`) |
   | 503 | the lake cannot serve it | the snapshot is not there, too old (`LAKE-STALE`), of a layout this reader does not serve (`LAKE-SCHEMA`); the query met the box's limit (`LAKE-LIMIT`); it was interrupted at its time limit |
   | 500 | the lake broke | an I/O error, an error inside the engine, anything nobody expected |

2. **The engine's classes are placed by the engine's own grouping**, not by a list kept here: a class the engine
   adds later falls where its parent is. A test walks every error class the engine has.
3. **The sentences are unchanged** (D-664): the lake's own refusals whole, the two engine sentences callers read
   ("Table with name ... does not exist!", "Referenced column ... not found") as they are, anything else the type
   and a fixed sentence. Only the status moves.
4. **The client carries the status** (`LakeQueryFailed.status`, D-673). A caller's rule: `exc.status >= 500` is
   "the lake failed".
5. **The request's own fault is answered before the lake is asked**: a generation header that is none is 400.
   It was raised inside the handler that turns every error into the lake's, and came out as 422, then as 500
   (found by this card's review by running).
6. **A snapshot that is not there is 503, not 404.** The caller asked for a night the lake does not hold (it was
   never built, or it is gone): the lake cannot serve the question. It is not a fault of the question's text, and
   a caller that pinned a snapshot must not take it for one.

## Every caller of query(), and what it does

`tests/unit/test_lake_query_status.py` finds every `.query(` call in `services/` and `libs/` and fails when one is
not on its list, or when the list and the code disagree about a handler around the call. The tools (`tools/`)
are not listed: each fails with the error.

- **No handler: the error goes on** and the job or the request fails. With D-673 a job then ends "The lake
  service failed." with the status; a 4xx there is a fault of the code and shows as one. Twenty-five callers:
  the job scenarios and their helpers, the cascade's stages, the twin's reader, the vector indexer, the
  equivalence gate, the EDC prefill, the lake's own uses.
- **Whether a table is there is asked of the lake** (lane A2's D-649 to D-652, on master with train 14):
  `tb_common.lakeprobe.rows_or_no_table` takes only the lake's plain 0 for the table as "no such table" and raises
  every other failure; its question's own failure answers "not known" (`no_table`), and the first failure stops
  the run. The cascade's notes, the proposed facts, the opt-out registry and the screen's confirmed facts read
  through it now, not by `query()` directly.
- **Said as "could not be read", never as none** (D-652): `scenarios/feas_profile.data_facts`.
- **Open, not changed here (each is another lane's file; sent to the integrator): a handler that catches every
  error, a 5xx too, and reads it as something else:**
  - `matching/coded_values.attach`: no coded value to show (display only; the answers stand);
  - `scenarios/screen.practitioner_names`: no names (the settings' ids are shown);
  - `sitesetup/readiness.unknown_share` and `feed_loaded`: no diagnosis, no feed loaded.
  Each was written for "an older snapshot without the table". With this card each can narrow its handler to the
  4xx and let a 5xx go on. (`patient_profile/twin.lake_schema` was on this list: NEW-B-35, D-676, asks the lake.)

## What this does not do

- The lake as a library (`LakeLocal`) raises the lake's own classes, not a status; `query_failure_status` is
  there for a caller that wants the same rule.
- The other routes of the lake (`/chunks/search`, `/vec/s2b`, the holds, the rebuild) keep their statuses.
- The list sees a handler around the call, not one in the function's caller.
- **The status is the lake's word only when the lake answered.** The service-token check in front of every
  service answers 401 or 403 for a caller it does not know, and 503 when the box has no token configured: a 4xx
  there is the box's set-up, not the question, and that 503 is not the lake's data failing. Unchanged by this
  card; a caller that must tell them apart reads the sentence.
- `LAKE-STALE` is raised where a job pins its snapshot, not by a query; its 503 is the rule for the day a query
  raises it.

## What a person sees differently now

A failed job's detail reads `HTTP 503` or `HTTP 500` where it read `HTTP 404` or `HTTP 422`. Nothing waits or
retries that failed at once before (checked by the review: no caller branches on the old statuses, and the
job-follower that waits through 5xx answers is not on the query's path).

## Tests

`tests/unit/test_lake_query_status.py`: seven faults of the question (400, 422, with the sentences callers read)
and twelve failures of the lake (503, 500), each through the real route and the client, none repeating a value;
every error class of the engine placed by its group; a real small lake (a wrong column and a value that does not
convert: 422; a statement the guard refuses: 400; a snapshot that is not there: 503); the list of callers and the
check of handlers; a generation header that is none is 400. **Expected statuses moved in three existing tests,
each with the same words asserted**: `tests/unit/test_lake_error_answers.py` (D-664's: the lake's own limit, 422
to 503), `tests/unit/test_t724_generations.py` (a generation that is gone, 404 to 503: found failing by this
card's review; its match is now the status and the sentence), and two mocked answers in
`tests/unit/test_lake_client_answers.py` (D-673's), so they describe the service as it answers now. No state
change is added.

Seen against the real service by the review (a real small lake): a missing column, a missing function, an
overflow, a failed cast, a wrong number or kind of parameters: 422; a statement the guard cannot read: 400; a
query cut at its time limit, the memory limit, a snapshot or generation that is not there, a deleted database
file, a newer layout: 503; a truncated database file: 500; a dropped `document` table: 422 with the sentence the
cascade reads.
