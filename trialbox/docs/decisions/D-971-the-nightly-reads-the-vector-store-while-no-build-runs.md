# D-971 the nightly backup reads the vector store while no build runs

- **Task:** lane D; a gap found while applying lane B2's answer to PERF-010 R3b (#905), approved by the integrator on
  #639 (2026-11-16) as a small card of its own
- **PR:** this branch (`agent/D971-the-nightly-reads-the-vector-store-while-no-build-runs`)
- **Date:** 2026-11-16
- **Status:** accepted
- **Builds on:** D-455 (the lake read under its lock), D-462 (the lake lock and the build lock), D-755 (PERF-011: the
  lock for the listing only)

## Context

Lane B2 answered on #639 which lake files are written in place. Every served file (a date's DuckDB file, a Parquet
folder, the sidecars) is swapped in by rename, so D-755's lock over the listing is enough for them. The vector store,
`embed_cache.duckdb`, is not: a build opens it read-write and adds embeddings to it while it runs. It can be rebuilt
only by embedding every chunk again (a long GPU job), so it has to be backed up, and whole.

The nightly `.tbbak` read it with "the rest of the lake", after the lake lock was let go. A build writes the store while
it holds its snapshot's build lock (`locks/<snapshot>.build.lock`, for the whole build); it holds the lake lock only at
its start and its swap. So a rebuild running at the time of the nightly could leave a half-written vector store in the
backup, and nothing checked it.

## Decision

1. The vector store (`LAKE_STORE`: `embed_cache.duckdb` and its `.wal` when there is one) is read last, by
   `_add_lake_store`, while the lake is quiet (`_quiet_lake`):
   - under the lake lock, so no build can start (a build takes the lake lock at its start, after its build lock);
   - with every `locks/*.build.lock` taken without waiting (`_build_locks`), so none is running.
2. The locks are held for that read only. The served files keep D-755's lock over the listing; the NDJSON and the
   site inputs are read without a lock, as before.
3. A running build is waited for: the backup lets the locks go and looks again every 15 s, up to 3 hours, then fails
   naming the snapshot that is building, with nothing written. An idle lock file left by an ended build does not stop
   it (`BuildLock` never deletes its file).
4. **Measured on every run:** `manifest["lake_store"]` records the files taken, whether the lake lock was taken, how
   long the backup waited for a running build (`waited_s`) and how long it held the locks (`held_s`). The integrator
   asked for that number; the sealed manifest carries it for every night's backup, and the box rehearsal's backup
   (PERF-010 R4) reports it.

## Test

`tests/unit/test_backup_vector_store.py`:
- the store is in the `.tbbak` and comes back byte for byte, and the wait and hold are recorded;
- the store and its `.wal` are read together;
- a running build is waited for, and the store is read only after the build lets go;
- a build that outlasts the wait fails the backup by name, with no file on the target;
- an idle build lock file does not stop the backup;
- the lake lock is held while the store is read and not while the other lake files are, and is free after;
- a lake without a store records nothing.

PERF-010 R3b (#905) applies the same quiet-lake rule to the restic path; it takes these helpers when it is merged with
master.
