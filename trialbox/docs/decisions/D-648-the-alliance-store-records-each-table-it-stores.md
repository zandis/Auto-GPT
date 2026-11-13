# D-648 The alliance store records each table it stores, in the transaction that stores it

- **Task:** COHORT-store-record (the owner's request of 2026-11-13, relayed by the integrator; follows NEW-B-25)
- **PR:** this branch (`agent/COHORT-store-record`), cut from lane B2's #489 (`59966b9f`), which holds #479
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-666 (a re-run of a merge rebuilds the alliance tables as the earlier merges left them, or says
  it cannot)

## Context

`cohort_tables` holds each site's latest table. A re-run of a `COHORT MERGE` needs the tables as they stood when
that merge read them, so it goes through the earlier COHORT jobs and stores again what each one stored. What an earlier
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
   hash, the table, and `seq`, its place in the order of all stores. No caller can store a table without its
   record, or leave a record of a table that was not stored. The root's own run goes through the same function
   and is recorded too.
2. **The job's end adds nothing.** There is no "finished" mark for a replay to trust. A job stored exactly its
   recorded tables; a job stopped half-way stored the tables recorded so far.
3. **The replay follows the order of the stores, not of the jobs.** A merge reads the tables for its output
   through `JobDB.cohort_read`, which records, in the transaction that reads, the last store before the read
   (`cohort_read.upto`). `cohort.replay_stored(record, into, job_id)` rebuilds the tables as they stood at that
   point: every recorded table up to it, in `seq` order, whichever job stored it. A stopped merge, a merge run
   again later, and two merges running at once are replayed as they happened. It needs no job's files, today's
   reader, or any job's ending, so a stopped merge no longer makes later merges' re-runs answer "cannot". Lane
   B2's `rerun.py` calls it once, for the job it runs again (their change, on this head).
4. **A box updated in place.** The tables such a box already holds are in no record. The schema step copies them
   as it finds them (`cohort_tables_before`), and the replay starts from them. So every merge that reads after
   the update is run again exactly, whatever the endings of the old jobs. What remains: a merge that itself read
   **before** the update has no recorded read; `replay_stored` returns False and the re-run has only how the
   earlier jobs ended (D-666), with its "cannot" where an earlier job of that time was stopped. This is the one
   case left; a go-live install has no such job.
5. **One store or read at a time.** `cohort_store` and `cohort_read` take one lock for their transaction, so
   `seq` is the order in which tables were committed and a read point falls between two stores, never inside one.
6. **What the record cannot settle is refused, not guessed.** A store replaces a site's rows for one disease,
   quarter and definition. If, between a merge's store of such a table and its read, another job stored that
   same table, the first run read the other job's; the re-run would store its own over it. `replay_stored` raises
   `ReplayUnsure` (two merges with the same table from the same sender, running at the same time). Another job's
   table of the same site for another quarter does not matter: the re-run does not touch it. A recorded table
   that cannot be read or does not match its hash raises `RecordChanged`, before anything is stored.
7. **Who may send a site's table is asked where it is stored.** The rule (a site's table comes only from the
   address that first sent it, never the root's own site) was checked before the store, outside its lock: another
   sender's store of the same site between the check and the write let both in, the merge ended done, and its
   re-run failed on the same check. `cohort_store(refuse=...)` asks the rule inside its transaction, under the
   lock, with the senders as they stand there; a refusal stores nothing. The refusal's sentence names the site
   and no address (D-555): it goes back to whoever mailed the table and into the job's record.

## Changed from the design as asked, and why

- The design asked for the site, the table's hash and its place in the order. The record also keeps **the table
  itself** (`rows`, the cells of `cohort_tables` as JSON) and **who sent it**. With the hash alone the replay must
  find the bytes again and parse them with today's reader. That fails for the root's own run that failed before
  it published (no file was ever written), for a file that is gone, and whenever the reader changes. With the
  table in the record the replay depends on nothing else. The table is the same data in the same class as
  `cohort_tables` (aggregate counts; small cells are suppressed by the sending site, and by `table_rows` for the
  root's own table, before the store): no patient data, entered as such in the erasure registry and the record
  inventory. It grows by one small row per table stored.
- The design had the replay go job by job ("no marker means stopped after the last recorded table"). The review
  showed, by running, that job order is not store order: a stopped merge run again after a later merge, or two
  merges at once, gave a re-run that read tables stored after the first run. Hence the read point and `seq`
  (item 3). The design's point stands: no end marker is trusted.
- The design kept D-666's "cannot" for every job without a record. With the tables found at the update kept
  (item 4) that case shrinks to the re-run of a merge that read before the update.

## What the hash is for

It tells a table that was damaged or edited in place from the one that was stored. It covers the cells, not the
sender or the job, and a deleted row of the record is not noticed: the record is not protected against someone
who can write to the store.

## For lane B2 (`rerun.py`)

- Call `cohort.replay_stored(orch.db, db, original.job_id)` for the merge being run again. True: the scratch
  store is ready. False: D-666's way, as today.
- `ReplayUnsure` and `RecordChanged` are to be answered like `ReplayUnknown`: drop the scratch schema, "this job
  cannot be re-run: ...". The replay stores table by table; after an error the scratch store is partial.

## What a merge's endings were checked against

`tests/unit/test_cohort_store_record.py` runs the real merge on a real store and stops it at every point: reading
a table, parsing it, the check of who may send it, right after the store, reading the tables back, publishing,
mailing; at each of its three tables where that applies; with each kind of error (the scenario's own, a
programming error, two of the object store's, the old reader's, the database's, a routing refusal, a cancel, the
process dying in two ways: 150 endings). After each one the record names exactly the tables the store holds, by
hash, and the record alone, replayed into an empty store, gives the same rows. Also: a cancel asked for while
tables are read; a merge killed and run again (both runs recorded, in order); a table whose rows cannot all be
stored leaves no record and keeps what it would have replaced; a record that cannot be written leaves no rows; a
later merge, run again after a stopped one that was itself run again afterwards, publishes the same bytes as its
first run, and so does the stopped one; another job's table of the same site before the read is refused; a box
updated in place replays a later merge with the tables it had, and says False for a merge from before.

## Review

One adversarial review by running, on the first version (`0ac5abed`).

| Finding | Confirmed | What was done |
|---|---|---|
| HIGH-1: a replay job by job in job order is not the store as it stood (a stopped merge run again later; two merges at once) | by running | the read point and the replay in store order (items 3, 5, 6); tests |
| MED-1: a job created before the update and run after it was fully recorded, yet answered "cannot say" | by running | the mark of "jobs before the record" is gone; such a job has a recorded read like any other; test |
| MED-2: on a box updated in place the records alone never rebuild the store | by running | `cohort_tables_before` (item 4); test |
| LOW-1: only the cells are covered by the hash; a malformed record raised other errors | by running | a record that cannot be read raises `RecordChanged`; the limits are stated above |
| LOW-2: `rerun.py` catches only `ReplayUnknown` | by reading | for lane B2, stated above |
| LOW-3: the replay stores table by table, a failure leaves the scratch store partial | by reading | stated above; the scratch store is dropped by the caller |

Held (the reviewer's runs): the record against the store after all 150 endings; a version that wrote the record in
a second transaction is caught by the tests; four migrations at once; the lock; the hash on eleven near-equal
values; several groups in one table, a later partial replacement, the same job twice; grants and backup are per
schema (by reading). Not verified by anyone: a restore end to end, the owner-role migration path.

## Not in this card

- `rerun.py` reading the record (lane B2). Until it does, a re-run still reads the endings.
- The re-run through `rerun()` end to end with the record: lane B2's test, with their change. Here the same steps
  are run by the test itself (the replay into a store of its own, then the job).

## Second review (of lane B2's re-run built on this record; two findings here, by running)

| Finding | What was done |
|---|---|
| `ReplayUnsure` was asked per site: another job's table of the same site for another quarter made the re-run "cannot" | asked per table (site, disease, quarter, definition), item 6; test |
| the sender check ran outside the store's lock: two senders of one site could both get in; the refusal's sentence carried two mail addresses | the check is made in the store's transaction, item 7; the sentence names the site only; tests |

## Review of the fix card (one, by running; verdict merge, no HIGH or MED)

Held, by running: two real connections with two senders storing a site's first table at once, 25 rounds, exactly
one gets in each time; an error raised by the rule inside the transaction stores nothing and frees the lock; the
tests fail when the check is put back outside the lock or the question back per site; re-runs of a refused
merge are identical; no sentence carries an address.

Noted, not changed:

- **Data from before this fix with two senders for one site** (got in through the old race): both are refused
  for that site from then on, as before this card; only an operator can clear it, and a re-run of the merge
  that got in differs without saying why. The fix prevents new cases and does not repair old ones. A go-live
  install holds none.
- The rule reads the senders whose tables stand in the store now, not the record of all stores. No path removes
  a bound sender's rows, so the two agree.
- A store with no rule (the root's own run, a replay) replaces what is there. It can meet a member's table only
  if the root's own site id equals a member's; the merge side refuses the root's own site whatever the senders.
