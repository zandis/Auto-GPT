# D-403 All-history back-fill, held snapshots and the batched site publish

- **Task:** T-305b, part b of T-305 (`docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-305b-backfill`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-061, the back-fill half; MR-129 (chunked, resumable back-fill), MR-183 (batched publish on `main`,
  pruning skips referenced snapshots), FR-REP-02 for running jobs
- **Builds on:** D-383 (T-305a snapshot pinning), D-271 (a bad night never moves `CURRENT`), D-149 (tombstones on
  delta nights), D-384 (T-202, the lake from OMOP)

## Context

The first load of a site is all of its history (owner decision C-02). `run_ingest` holds a whole night in memory
(0.33 GB per 1,000 patients). Since T-305a every job pins one snapshot, but the snapshot was still rebuilt under the
same id by a site publish on `main` (every confirmation of a fact), so a running job could read changed bytes between
two queries, and the adapter's pruning did not know about pins. A record deleted at the source was tombstoned in OMOP
like any record that left the feed.

## Decision

1. **The back-fill** (`adapter/backfill.py`, `adapter backfill`) spools the source once by clinical year, sorts and
   checks one year at a time (newest first, a `dq.json` per year), and merges the years into the same NDJSON bytes
   the nightly full load writes. With `--first-years N` it publishes once after the newest N years and again at the
   end. It resumes after a stop at the year it reached. It publishes through the drop guard, the OMOP dual write and
   the lake rebuild. It does not run the data contracts, the completeness gate, the JP Core sample or the fhir-store
   load; the nightly loads after it do.
2. **Holds.** A job's pin is also a hold on the lake (`<lake>/holds/<job id>.json`; `Lake.hold`, `/holds`). The lake
   refuses to rebuild a held snapshot that exists (`SnapshotHeld`, a `RebuildError`, HTTP 409); `prune_snapshots`
   keeps held snapshots. The orchestrator releases the hold when the job is done or failed (a job waiting for an
   approval keeps it). A hold older than 14 days protects nothing.
3. **Batched publish on `main`.** A site decision within `TB_SITE_PUBLISH_BATCH_SECONDS` of the last publish of
   `main` waits (`pending`); the orchestrator applies the waiting batch every minute and after each job; the Publish
   button applies it at once. Nothing is published while a job holds the snapshot. Code default 0 (publish every
   decision, as before); the production compose file sets 300. Practice spaces are not batched.
4. **Why a delete happened.** The OMOP loader takes the night's `tombstones.json` and writes the reason `deleted at
   the source` on those tombstone events; any other tombstone says `left the feed`.

## Consequences

- A running job's snapshot does not change under it; a re-run long after the job may still read a snapshot that a
  later same-day publish rebuilt. Content-addressed snapshot ids (`<date>.<seq>`) would close that; the snapshot id
  is a date in the job record, the lake API and every scenario, so that change is left to a later card.
- A nightly re-run of a night a job holds is refused and held (the operator runs it again after the job).
- The back-fill's memory still grows with the largest source table (the CSV reader reads a file at once) and the
  OMOP load and lake rebuild read the whole snapshot; the 50,000-patient run is not done
  (`docs/plan/measurements/backfill-2026-11-11.md`).
