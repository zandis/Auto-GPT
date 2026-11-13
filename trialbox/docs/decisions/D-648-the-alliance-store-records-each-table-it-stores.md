# D-648 The alliance store records each table it stores, in the transaction that stores it

- **Task:** COHORT-store-record (the owner's request of 2026-11-13, relayed by the integrator; follows NEW-B-25)
- **PR:** this branch (`agent/COHORT-store-record`), cut from lane B2's #489 (`59966b9f`), which holds #479
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-666 (a re-run of a merge rebuilds the alliance tables as the earlier merges left them, or says
  it cannot)

## Context

`cohort_tables` holds each site's latest table. A re-run of a `COHORT MERGE` needs the tables as they stood when
that merge ran, so it goes through the earlier COHORT jobs and stores again what each one stored. What an earlier
job stored was written nowhere. D-666 reads it from how the job ended, and that has an ending with no answer: a
merge stopped while it ran (an internal error, a service's failure, a restart, a kill between two tables). Such a
job stored some of its tables and not the rest. From then on, the re-run of **every later merge** on that box said
"cannot be re-run".

Two more ways the reading from the ending can be wrong were found while building this:

- (By reading.) The root's own COHORT run stores its table before it publishes the file the replay reads. A run that failed
  after the store (in the trial simulation, in the report) left its table in the store, and a later merge counted
  it; the replay finds no published file and stores nothing.
- The replay parses the job's files with today's reader. The files may be gone (retention), and a reader that
  changes reads old bytes differently (the case D-666 was written for).

## Decision

1. **The store writes the record.** `JobDB.cohort_store` adds one row to `cohort_stored` for each site's table it
   stores, in the same transaction as the rows of `cohort_tables`: the job, the site, who sent it, the table's
   hash, the table, and `seq`, its place in the order. No caller can store a table without its record, or leave a
   record of a table that was not stored. The root's own run goes through the same function and is recorded too.
2. **The job's end adds nothing.** There is no "finished" mark for a replay to trust. A job stored exactly its
   recorded tables; a job with no row stored nothing. A job stopped half-way stored the tables recorded so far.
3. **A stopped merge no longer stops later re-runs.** `cohort.replay_stored(record, into, job_id)` stores a job's
   recorded tables into another store, in order. It needs neither the job's files, nor today's reader, nor the
   job's ending. Lane B2's `rerun.py` calls it for each earlier job (their change, on this head).
4. **Jobs from before the record.** The schema step that adds the record notes the last job that existed then
   (`cohort_stored_since`, a `jobs.seq`). For a job up to that mark `cohort_stored` answers None, never "nothing",
   and `replay_stored` returns False: the replay then has only the job's ending (D-666), and a job of that time
   with an ending that cannot be read keeps "cannot be re-run", for that job and the merges after it on that box.
   This is the one case left. It exists only on a box that ran merges before this release; a go-live install
   starts with the record and never has it.
5. **One store at a time.** `cohort_store` takes a lock for its transaction, so `seq` is the order in which the
   tables were committed, also when two merges run at once.

## Changed from the design as asked, and why

The design asked for the site, the table's hash and its place in the order. The record also keeps **the table
itself** (`rows`, the cells of `cohort_tables` as JSON) and **who sent it**. Reason: with the hash alone the replay
must find the bytes again and parse them with today's reader. That fails for the root's own run that failed before
it published (no file was ever written), for a file removed by retention, and whenever the reader changes. With the
table in the record the replay depends on nothing else. The hash stays: `replay_stored` checks each table against
it and refuses a record that was altered (`RecordChanged`). The table is the same data in the same class as
`cohort_tables` (aggregate counts, small cells already suppressed by the sending site): no patient data, entered as
such in the erasure registry and the record inventory. It grows by one small row per table stored.

## What a merge's endings were checked against

`tests/unit/test_cohort_store_record.py` runs the real merge on a real store and stops it at every point: reading
a table, parsing it, the check of who may send it, right after the store, reading the tables back, publishing,
mailing; at each of its three tables where that applies; with each kind of error (the scenario's own, a
programming error, the object store's, the old reader's, the database's, a routing refusal, a cancel, the process
dying: 150 endings). After each one the record names exactly the tables the store holds, by hash, and the record
alone, replayed into an empty store, gives the same rows. Also: a cancel asked for while tables are read; a merge
killed and run again (both runs recorded, in order); a table whose rows cannot all be stored leaves no record and
keeps what it would have replaced; a record that cannot be written leaves no rows; a later merge, run again after
a stopped one on tables rebuilt from the record alone, publishes the same bytes as its first run.

## Not in this card

- `rerun.py` reading the record (lane B2). Until it does, a re-run still reads the endings.
- The re-run through `rerun()` end to end with the record: lane B2's test, with their change.
