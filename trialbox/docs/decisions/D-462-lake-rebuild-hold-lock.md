# D-462 The lake: one lock for rebuild and hold, holds checked again at the swap, one rebuild per snapshot at a time

- **Task:** T-722 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.3, wave G; card G-1 of the lifecycle review)
- **PR:** this branch (`agent/T-722-lake-rebuild-hold-lock`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** lifecycle review 2026-11-12 F-1 (a hold taken while a rebuild runs does not protect the snapshot); the
  "two writers of `<snapshot>.building`" part of scale review 2026-11-11 F-01
- **Builds on:** D-383 (T-305a, the pin), D-403 (T-305b, holds), D-271 (refused rebuilds leave `CURRENT` alone)

## Decision

1. **One lake lock.** `lake/.rebuild.lock`, an exclusive `flock` (the same mechanism as the audit chain,
   `tb_common/audit.py`; no new dependency). It works across the lake's uvicorn worker processes, the adapter and the
   tools that share the lake folder, and a killed process releases it. `hold`, `release`, the adapter's pruning
   (`prune_snapshots`) and the two critical moments of a rebuild (its start and its swap) take it. It is held for
   milliseconds to seconds (reading holds, renaming files, hashing the finished file), never across a build, so a
   job that starts during a long rebuild is not kept waiting for the build.
2. **Holds are checked again at the swap.** A rebuild builds beside the served bytes (`db/<snapshot>.building` and,
   new here, `parquet/.building/snapshot=<snapshot>/`), then, under the lake lock, reads the holds again. If a running
   job now holds the snapshot, the rebuild **is refused with `SnapshotHeld`** (HTTP 409, "being read by a running
   job"): the new build is discarded, the held DuckDB file, its Parquet files and sidecars, the markers and `CURRENT`
   are unchanged. The caller already treats this refusal as "wait for the job": the site publish turns it into a
   waiting batch (D-403) and the adapter into a held night (D-271). Nothing a reader can see is written before the
   swap: the `FEED` and `.siteonly` markers moved after it.
3. **Why refuse, not keep the build and swap on release.** Keeping the build beside and swapping it when the last
   hold is released would make `release` a writer of snapshots (sidecars, the source record, the promotion, the
   "older than `CURRENT`" rule) and leave a built file whose inputs may be stale by then. Refusing is the smallest
   correct behaviour for today's date-named snapshots: the cost is a rebuild done again after the job ends, which the
   callers already do. T-724 makes every rebuild a new generation, so a held generation is never replaced and this
   refusal goes away; nothing here is in its way (the build-beside layout is what a generation folder needs).
4. **One rebuild per snapshot at a time.** A rebuild holds a second `flock`, `db/<snapshot>.build.lock`, for its whole
   run, taken without waiting. A second rebuild of the same snapshot while one runs (another worker, a retry of a
   timed-out client) is refused at once with `SnapshotBuilding` (HTTP 409, "already building"); it writes nothing.
   Rebuilds of different snapshots still run side by side. A killed rebuild releases the lock; its leftovers are
   cleared by the next rebuild of that snapshot. The lock files are never deleted (deleting a locked file breaks
   `flock`), and pruning does not touch them.
5. **The site publish shows "already building".** `SiteSetup.publish("main")` answers a `SnapshotBuilding` refusal
   (in process, or the service's 409 "already building") as a waiting publish: `pending: true, building: true`,
   the last published state unchanged, an audit event `setup.publish_building`. It never starts a second writer
   because its HTTP client timed out. It does not yet know when the running rebuild ends or whether it carried the
   same facts: the polled job of T-690 does that.
6. **`CURRENT` is re-read at the swap.** A rebuild that would promote a snapshot older than `CURRENT` as it is at
   the swap (another night was promoted during the build) builds it without promoting it (DATA-007, as before, now
   also when `CURRENT` moved during the build).

No time limit is added (OD-10): the build lock is not waited on, and the lake lock is held only for short steps.

## What T-690 can rely on

- At most one rebuild of a snapshot runs at any time on a box, whatever the number of lake workers or callers.
- A second `POST /rebuild` of a snapshot that is building answers 409 with "already building" at once and changes
  nothing; a held snapshot answers 409 with "running job" (at the start or at the swap) and changes nothing.
- A rebuild that returns 200 swapped its file in while no job held the snapshot.

## Open

- A site publish whose rebuild takes longer than its client's 330 s still never records its publish (each later tick
  starts a new rebuild once the last has ended): serialised now, no longer overlapping. T-690 (a polled job) closes it.
- A refusal at the swap wastes the build's time. T-724 (generations) removes it.
