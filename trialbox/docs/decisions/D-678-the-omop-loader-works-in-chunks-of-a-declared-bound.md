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
   - the batch is built and staged **before the load's lock**, as it was built before it when held whole (a date
     of another calendar is refused first; the opt-out worker does not wait for a batch being built); the records
     of a withheld patient are marked under the lock;
   - the **guard** (D-271) counts live and missing records in SQL against the stage;
   - **ids**: the person, provider and care-site maps are minted once from the distinct pseudonyms (as large as
     the patients and staff, not the records); each record's OMOP id is given in the batch's order a chunk at a
     time, before any record is resolved further, so a fact still names the visit of an encounter later in the
     batch;
   - **concepts** are prepared from one stream of every code of the batch, before any record is resolved, so
     local concepts are minted in the order they were;
   - the ids are kept **beside** the stage (`tb_load_ids`), not written into it (an update would write every
     staged row again);
   - each chunk is then resolved (visits, providers, care sites, concepts, required dates, routing), diffed with
     the stored records **of its own keys** (a join with an analysed key table, so the planner reads the chunk's
     stored rows, not all of them), and written;
   - every scratch table of the load is made **once per transaction** and emptied for each chunk: made again for
     every chunk, each kept its lock to the commit, and a load of many chunks ran PostgreSQL's shared lock table out
     (and another session's migration with it);
   - what the batch no longer carries (or carries for a withheld patient) is found by an **anti-join** with the
     stage and tombstoned a chunk at a time, by record key.
2. **The chunk is a declared setting**, `TB_OMOP_LOAD_CHUNK` (records). Unset, it is derived: a sixteenth of the
   process's memory cap (cgroup v2, else the host's; cgroup v1 is not read), at the measured 12 KB a record of a
   chunk, the share the ingest's sort runs take (D-473). On this 15 GB machine: 87,860.
3. **The callers stream**: the dual write and `python -m omop load` pass `adapter.ndjson.readers` (each type read
   from its file again when iterated); the lake's OMOP source passes its re-readable streams as they are.
   `Medication` and `ClaimResponse` are still indexed whole (the records name them; 0 and 146 of them at 1,000
   dense patients).
4. Staged records are written as JSON with their types (a date, a datetime, a decimal, a code), not pickled, so
   they read back as built and a record's content sha is unchanged.

## Measured after the change (the same machine, the same data)

| batch | loader | chunk | peak, first load | peak, again | time |
|---|---|---|---|---|---|
| 1,000 dense | before, lists | whole | 5,476 MiB | 5,267 MiB | 57 to 70 s |
| 1,000 dense | before, the same streams | whole | 2,645 MiB | | 54 s |
| 1,000 dense | after | derived | 1,124 MiB | 1,091 MiB | 108 to 130 s |
| 1,000 dense | after | 20,000 | 366 MiB | 346 MiB | 115 to 127 s |

The peak follows the chunk, not the batch; the old loader fed streams is still linear (2.6 GiB here, about 130 GiB
at 50,000 dense patients). **The load is slower**, about 2 to 2.4 times the old one fed the same streams (building
and staging, JSON in and out, the passes over the stage); the dual write and a lake built from OMOP pay it, a
legacy lake does not. The times were measured with a whole unit suite running on the same 4 cores.

The stage takes about 1.4 times the batch's NDJSON in the database's temporary space while the transaction lasts
(195 MiB for 143 MiB at 250 dense patients, measured by the review), the ids table a few bytes a record more.

## What this does not do

- The export of a lake back from OMOP (`omop.export.export_rows`) is still whole (scale review F-17, T-702).
- `_derive` reads per affected person, as before.
- The tombstone events of a batch are written in record-key order (the old loader wrote them in the order an
  unordered query gave).
- A temporary table is still made per load (about ten), each with its lock: a constant, not per chunk.

## Tests

`tests/unit/test_omop_load_batches.py` (5 tests):

- **the peak does not grow with the batch**: four times the patients, the same chunk, the input streamed: below
  1.6 times the peak (on the parent: 4.5 times, failing);
- **a load in small chunks leaves the same store as one chunk**: the committed synthetic site A (600 patients)
  through the real adapter, two nights (a few records gone, one changed), chunk 37 against 100,000,000: every row
  of every CDM table, `tb_record`, its events, the id map and the concepts, without the clock, equal; the reports
  equal;
- **a date of another calendar in a late chunk** refuses the batch, writes nothing, keeps the refusal;
- **interrupt test**: a load cut after two chunks were written leaves the store as it was, and the next load
  ends as it should;
- **the locks the load holds do not grow with its chunks** (after the review): 10 chunks and about 100 hold the same
  number before the tombstones (5,918 against 757 before the fix).

The equivalence and late-refusal tests also pass on the old loader (it ignores the chunk; it refused before
writing): they guard the new one. The peak and interrupt tests fail on it.

The test files that load OMOP or build a lake from it pass. **One existing test's expected text changed**: `tests/unit/test_role_paths.py` looked for the load's `CREATE TEMP TABLE tb_in_tmp`; it now looks for `CREATE TEMP TABLE IF NOT EXISTS tb_in_tmp` (the table is made once per load). Its point stands: the load makes its temporary table under the store's own role. Found by the whole unit suite.

## Review

One adversarial, read-only review by a fresh agent, by running. It loaded the same sequence into the old loader
and the new one at chunk 37, the derived chunk and chunk 500 with streamed input: site A through the real adapter,
a vocabulary so records route by domain, a site batch, a withheld patient, nights with deletions, updates,
`deleted=`, duplicate ids, records without a person, encounters named by facts earlier in the batch, an unknown
encounter, `withhold()`, restores, a release, a repeated night and an older batch. Every table, sequence and report
was identical across the four, but for two tombstone event ids swapped (the order above). It also checked: the
memory flat at chunk 5,000 (137 and 144 MiB at 250 and 1,000 dense); every temp table dropped at commit; a refusal
after written chunks leaves the store byte-identical; the JSON round trip keeps every record's content sha.
Findings, all taken: the lock table run out by per-chunk temp tables (fixed and tested); the unanalysed key joins
and the visit lookup scanning the stage each chunk (fixed); the id pass rewriting every staged row (now beside
it); building under the lock (now before it); the slowdown, the temp space and "a sixteenth of the cap" stated
wrongly here (corrected with its numbers and ours). Not verified by it: cgroup v1; a deploy cluster's own lock
table size; the backup drill and the roles tool's loads.
