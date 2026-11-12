# D-462 The lake: one lock for rebuild and hold, holds checked again at the swap, one rebuild per snapshot at a time

- **Task:** T-722 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.3, wave G; card G-1 of the lifecycle review)
- **PR:** this branch (`agent/T-722-lake-rebuild-hold-lock`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** lifecycle review 2026-11-12 F-1 (a hold taken while a rebuild runs does not protect the snapshot); the
  "two writers of `<snapshot>.building`" part of scale review 2026-11-11 F-01; the adversarial review of PR #284
  (decisions 4 to 9)
- **Builds on:** D-383 (T-305a, the pin), D-403 (T-305b, holds), D-271 (refused rebuilds leave `CURRENT` alone)

## Decision

1. **One lake lock.** `lake/.rebuild.lock`, an exclusive `flock` (the same mechanism as the audit chain,
   `tb_common/audit.py`; no new dependency). It works across the lake's uvicorn worker processes, the adapter and the
   tools that share the lake folder, and a killed process releases it. `hold`, `release`, the adapter's pruning
   (`prune_snapshots`) and the two critical moments of a rebuild (its start and its swap) take it. It is held for
   milliseconds (reading holds, renaming files; the hash of the finished file is taken before it), never across a
   build, so a job that starts during a long rebuild is not kept waiting for the build.
2. **Holds are checked again at the swap.** A rebuild builds beside the served bytes (`db/<snapshot>.building` and,
   new here, `parquet/.building/snapshot=<snapshot>/`), then, under the lake lock, reads the holds again. If a running
   job now holds the snapshot, the rebuild **is refused with `SnapshotHeld`** (HTTP 409, "being read by a running
   job"): the new build is discarded, the held DuckDB file, its Parquet files and sidecars, the markers and `CURRENT`
   are unchanged. Nothing a reader can see is written before the swap: the `FEED` and `.siteonly` markers moved after
   it. The DuckDB file's sidecar is written from the hash taken before the lock, so a hold or a release never waits
   for a hash of a hospital-size file.
3. **Why refuse, not keep the build and swap on release.** Keeping the build beside and swapping it when the last
   hold is released would make `release` a writer of snapshots (sidecars, the source record, the promotion, the
   "older than `CURRENT`" rule) and leave a built file whose inputs may be stale by then. Refusing is the smallest
   correct behaviour for today's date-named snapshots: the cost is a rebuild done again after the job ends, which the
   callers already do. T-724 makes every rebuild a new generation, so a held generation is never replaced and this
   refusal goes away; nothing here is in its way (the build-beside layout is what a generation folder needs).
4. **One rebuild per snapshot at a time.** A rebuild holds a second `flock`, `locks/<snapshot>.build.lock`, for its
   whole run, taken without waiting. A second rebuild of the same snapshot while one runs (another worker, a retry of
   a timed-out client) is refused at once with `SnapshotBuilding` (HTTP 409, "already building"); it writes nothing.
   Rebuilds of different snapshots still run side by side. A killed rebuild releases the lock; its leftovers
   (`.building`, the Parquet stage, `snapshot=<s>.old`) are swept by the next rebuild of that snapshot, under the
   same lock. **The lock files are never deleted** (a deleted file that someone has open lets a second holder in):
   one empty file per snapshot date stays in `locks/`. The adapter's pruning takes each snapshot's build lock without
   waiting before it deletes the snapshot's files and **skips a snapshot that is building** (the build would bring it
   back at its swap).
5. **"Busy" is one class, never refused data.** `LakeBusy` (a `RebuildError`) is the parent of `SnapshotHeld` (at the
   start or at the swap) and `SnapshotBuilding`. The lake service answers it with 409 and the header
   `X-TB-Lake-Busy: held|building`. The adapter reads the class in process and the header over HTTP the same way: the
   night ends with the error "lake busy: the night is run again once the lake is free (nothing was written)", `held`
   false, no `held.json`, `lake_busy` in the audit detail. A 409 without the header stays a refusal of the data
   (`RebuildRefused`, a held night). A job hold at the start of a night's rebuild therefore no longer holds the night
   for the steward (it never was a judgement on the data); the back-fill keeps its own "held, run again" state. The
   data-operations states are unchanged: a named "busy" state of the night's record is T-723's.
6. **Readers never get a replaced file's cached copy.** DuckDB keeps one open copy of a file per path in a process;
   while any connection to it is open, a new connection to the same path after a swap still reads the old bytes (an
   unheld console query open in a worker; a job that pins and holds after the swap: its first query read the old
   file, later ones the new). Readers now open a hard link named after the file's identity
   (`db/.open/<inode>-<mtime>-<size>/<snapshot>.duckdb`, the same file name, so the same database name); the swap and
   the pruning remove links that no longer name the snapshot's file. Without hard links the file itself is opened, as
   before. A new file name per build (T-724) replaces this.
7. **A re-run holds its snapshot.** `orchestrator.rerun.PinnedLake` now passes `hold` and `release` to the lake, under
   the name `rerun.<job>.<tag>`; before, a re-run held nothing and a publish could rebuild its snapshot under it.
8. **`verify()` flags a missing or empty Parquet folder** (a swap cut short between its renames); the backup leaves
   out every path with a part ending in `.building` or `.old` and the reader links (`db/.open/`); a file that vanishes
   during a backup was already a named skip ("removed while the backup ran").
9. **The site publish shows "already building".** `SiteSetup.publish` (the hospital's lake and a practice site)
   answers a `SnapshotBuilding` refusal (in process, or the service's 409 marked `building`) as a waiting publish:
   `pending: true, building: true`, the last published state unchanged, an audit event `setup.publish_building`. It
   never starts a second writer because its HTTP client timed out. It does not yet know when the running rebuild ends
   or whether it carried the same facts: the polled job of T-690 does that.
10. **`CURRENT` is re-read at the swap.** A rebuild that would promote a snapshot older than `CURRENT` as it is at
   the swap (another night was promoted during the build) builds it without promoting it (DATA-007, as before, now
   also when `CURRENT` moved during the build).

No time limit is added (OD-10): the build lock is not waited on, and the lake lock is held only for short steps.

## What T-690 can rely on

- At most one rebuild of a snapshot runs at any time on a box, whatever the number of lake workers or callers.
- A second `POST /rebuild` of a snapshot that is building answers 409 with `X-TB-Lake-Busy: building` at once and
  changes nothing; a held snapshot answers 409 with `X-TB-Lake-Busy: held` (at the start or at the swap) and changes
  nothing. A 409 without the header is a refusal of the data.
- A rebuild that returns 200 swapped its file in while no job held the snapshot.

## Open (not built here)

- **T-724:** a `CURRENT` that is always held (jobs back to back) is never rebuilt, and a refusal at the swap wastes the
  build's time; generations remove both, and the reader links of decision 6.
- **T-690:** a site publish whose rebuild takes longer than its client's 330 s still never records its publish (each
  later tick starts a new rebuild once the last has ended): serialised now, no longer overlapping.
- **T-723 (a guess, to verify):** a site publish may lose its facts when the adapter promotes a newer night that was
  built before the publish's `put_site`, while the publish is recorded with its digest and the next one is skipped as
  unchanged.
