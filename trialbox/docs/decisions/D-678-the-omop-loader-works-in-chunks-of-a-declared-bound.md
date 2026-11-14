# D-678 The OMOP loader works in chunks of a declared bound

- **Task:** NEW-B-37 (deep review 2026-11-13, DATA-026, High; placed with lane B by the owner on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-37-omop-loader-in-batches`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-151 (the OMOP store of record), D-271 (a refused batch loads nothing), D-441 (withheld persons),
  D-473 (the ingest's sort runs take a sixteenth of the memory cap), D-521 (a date of another calendar refuses the
  batch)

## Context

`omop.load.load_batch` held the whole batch in memory: every resource (the callers read the snapshot into lists),
every record built from it, and every stored record of the kind to diff against. Measured before the change, one
process, local PostgreSQL, synthetic data (the generator's hospital, and the T-687 dense profile of about 500
records and 42 notes a patient), `python -m omop load`'s path:

| batch | resources | `tb_record` rows | NDJSON | peak, first load | peak, again | time |
|---|---|---|---|---|---|---|
| 5,000 thin patients | 155,713 | 163,831 | 145 MiB | 1,514 MiB | 1,459 MiB | 14 s |
| 100 dense | 54,695 | 58,001 | 54 MiB | 591 MiB | 565 MiB | 6 s |
| 1,000 dense | 559,056 | 591,576 | 553 MiB | 5,476 MiB | 5,267 MiB | 70 s |

Linear, about 9.5 KB a resource: about 270 GiB at 50,000 dense patients against the adapter's 6 GiB cap (the
review's 28 GB counted only the stored records' dict). Where it went, at 1,000 dense: the input read into lists
3.1 GB (57 %), the records built 1.0 GB, concept resolution 0.27 GB, the diff and the writes 0.42 GB. Batching the
diff alone would have saved under a tenth.

## Decision

1. **One transaction, as before** (a load is all or nothing, two loads never interleave; a refusal loads nothing),
   but **nothing of the batch is held whole**:
   - the records are built line by line and **staged** in a temporary table of the transaction
     (`tb_load_stage`), a chunk at a time: one row per key, the last line of a key winning with that line's
     position, as the whole-batch loader's dict did; the person, providers and care sites it names, its codes
     and its standard-only lookups are kept beside it;
   - the **guard** (D-271) counts live and missing records in SQL against the stage;
   - **ids**: the person, provider and care-site maps are minted once from the distinct pseudonyms (as large as
     the patients and staff, not the records); each record's OMOP id is given in the batch's order a chunk at a
     time, before any record is resolved further, so a fact still names the visit of an encounter later in the
     batch;
   - **concepts** are prepared from one stream of every code of the batch, before any record is resolved, so
     local concepts are minted in the order they were;
   - each chunk is then resolved (visits, providers, care sites, concepts, required dates, routing), diffed with
     the stored records **of its own keys** (a join), and written;
   - what the batch no longer carries (or carries for a withheld patient) is found by an **anti-join** with the
     stage and tombstoned a chunk at a time, by record key.
2. **The chunk is a declared setting**, `TB_OMOP_LOAD_CHUNK` (records). Unset, it is derived: a sixteenth of the
   process's memory cap (cgroup v2, else the host's), at the measured 9.5 KB a record, the share the ingest's
   sort runs take (D-473). On this 15 GB machine: about 106,000.
3. **The callers stream**: the dual write and `python -m omop load` pass `adapter.ndjson.readers` (each type read
   from its file again when iterated); the lake's OMOP source passes its re-readable streams as they are.
   `Medication` and `ClaimResponse` are still indexed whole (the records name them; 0 and 146 of them at 1,000
   dense patients).
4. Staged records are written as JSON with their types (a date, a datetime, a decimal, a code), not pickled, so
   they read back as built and a record's content sha is unchanged.

## Measured after the change (the same machine, the same data)

| batch | chunk | peak, first load | peak, again | time |
|---|---|---|---|---|
| 1,000 dense | derived (about 106,000) | 1,363 MiB | 1,329 MiB | 116 to 119 s |
| 1,000 dense | 20,000 | 344 MiB | 338 MiB | 125 to 134 s |

The peak follows the chunk, not the batch. **The load is slower**, about 1.7 to 1.9 times at 1,000 dense patients
(staging, JSON in and out, more round trips); the dual write and a lake built from OMOP pay it, a legacy lake does
not. The time was measured with a whole unit suite running on the same 4 cores for part of it.

## What this does not do

- The export of a lake back from OMOP (`omop.export.export_rows`) is still whole (scale review F-17, T-702).
- `_derive` reads per affected person, as before.
- The staging table is in the database's temporary space: a batch needs about its NDJSON's size there for the
  transaction's length.

## Tests

`tests/unit/test_omop_load_batches.py` (4 tests):

- **the peak does not grow with the batch**: four times the patients, the same chunk, the input streamed: below
  1.6 times the peak (on the parent: 4.5 times, failing);
- **a load in small chunks leaves the same store as one chunk**: the committed synthetic site A (600 patients)
  through the real adapter, two nights (a few records gone, one changed), chunk 37 against 100,000,000: every row
  of every CDM table, `tb_record`, its events, the id map and the concepts, without the clock, equal; the reports
  equal;
- **a date of another calendar in a late chunk** refuses the batch, writes nothing, keeps the refusal;
- **interrupt test**: a load cut after two chunks were written leaves the store as it was, and the next load
  ends as it should.

The 17 test files that load OMOP or build a lake from it pass unchanged (200 passed, 3 skipped).
