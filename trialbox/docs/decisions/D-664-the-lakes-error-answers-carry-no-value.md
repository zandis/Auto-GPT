# D-664 The lake's error answers carry no value of a row and no text of the query

- **Task:** NEW-B-23 (a finding of lane C2's review, placed by the integrator on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-23-lake-error-answers`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** T-690 / D-472 (a rebuild job's state and its `detail`), the lake's own refusals (`LAKE-LIMIT`,
  `LAKE-STALE`, `LAKE-SCHEMA`), the SQL guard

## Context

The lake answered a failed query with the engine's own message (`422`, "the engine message (no data echoed)", as
the comment had it). Run on train 8, the engine does echo data:

- a conversion error quotes the value: `Could not convert string 'Tanaka-san-0' to INT32`;
- an error about a missing column adds the query's own line under its message (`LINE 1: SELECT ... WHERE pid =
  'Tanaka-san'`), with any literal the caller wrote;
- the SQL guard's "unparseable SQL" passed on the parser's message, which shows the query's text around the fault.

A failed rebuild job's `detail` was built the same way. These texts travel: `lake query failed (422): ...` becomes
a job's failure, its mail and its audit event; a rebuild's detail becomes the night's error.

Callers read some of these messages: the matching cascade and the rules tell "a table or column that is not
there" from the engine's sentence (`Table with name X does not exist`).

## Decision

1. **One function says what the lake answers for a failure** (`lake.store.error_answer`), used by `/query`'s 422
   and by a rebuild job's `failed` detail:
   - the lake's own refusals (`LAKE-LIMIT`, `LAKE-STALE`, `LAKE-SCHEMA`, and the build's own refusals, now of a
     class of their own, `LakeSaid`: sentences written in the lake): whole, as before;
   - **two engine sentences, and only these, are passed on**: "Table with name X does not exist!" and
     "Referenced column "X" not found in FROM clause!", with X an identifier (what a caller wrote). They are
     what callers read (the cascade and the opt-out reader look for a table that is not there). What the engine
     adds under them (candidate names, the query's line) is not sent;
   - a build the operating system stopped (no space left on the device, a file that cannot be read): the
     system's own words, without the file's name;
   - everything else: the error's type and a fixed sentence (`LAKE-QUERY` for a query, `LAKE-BUILD` for a build).
2. **The engine's message is not logged either.** The log gets the error's type, the engine's name for its kind
   ("Conversion Error": the words before the first colon) and, for a build, the frames where it failed. A person
   who needs the message runs the query on the box.
3. **"Unparseable SQL" says where, not what**: the error's type and, where the parser gives them, line and
   column; a tokenizer's error (an unterminated string) is refused the same way (it reached the engine before).
   "Unknown table" names the table only when its name is an identifier (a string literal in a table's place is
   read as a name).
4. The other answers built from an exception's text are sentences written in the lake (no such snapshot, a
   holder that is not a job id, busy, a refused rebuild with its counts): read one by one, unchanged.

## Why not "the first line of a shape error" and "mask what is quoted"

Both were built first and broken by the review, by running about 190 queries through the service:

- the first line of a Binder or Catalog error repeats literals of the query (`Sequence with name <literal> does
  not exist`, a regex, a struct key, a type name), and **after a PIVOT without a list of values the rows' values
  are column names**: an ordinary mistake (`GROUP BY` after such a PIVOT) answered with patient ids in its first
  line;
- the engine prints values without quotation marks (a failed `strptime` puts the value on a line of its own;
  regex errors; numbers in overflow errors), and a value with an apostrophe breaks the pairing of quotes: a
  masked message still held values.

## Consequences

- A job that fails on a conversion in the lake reads `lake query failed (422): ConversionException: LAKE-QUERY:
  ...` with no value in it. Debugging it means running the query on the box: the price of a log that holds no
  value.
- Callers that look for a missing table find it as before; the cascade's and the opt-out reader's tests pass
  unchanged.
- A failed build's detail says `LAKE-BUILD` and, for a full disk, "No space left on device". Before, the build's
  log held the engine's whole message with the traceback; now it holds the frames.
- **PIVOT is still allowed by the SQL guard.** Its values-as-column-names can no longer reach an answer or the
  log through an error. Whether the guard should refuse a PIVOT without a list of values is not decided here.
- **Not covered:** the OMOP store's refusals (`OmopError`) reach a `refused` detail whole, as before this
  change; some name a record id or a code (read by the reviewer: `omop/load.py`, `omop/vocab.py`). The in-process
  lake of the site set-up (`LakeLocal`) raises the engine's own text to its caller. Unhandled errors of other
  lake routes answer a fixed 500, and their log line is written by the shared handler with the message.

## Not decided here

- The OMOP store's refusal texts, the shared handler's log line, and the in-process lake (above).
- The same reading of the other services' error answers.
