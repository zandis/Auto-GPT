# D-663 The night's ingest is a process of its own, and its run record is on disk

- **Task:** the other half of PERF-025, with PERF-008's run record (the review of 2026-11-12; placed by the
  integrator after D-539)
- **PR:** this branch (`agent/PERF-025-adapter-ingest-own-process`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** T-690 / D-472 (the ingest is started with `POST /run` and followed by polling), D-539 (the lake's
  build as a process of its own: the lock handed over as an open file), NEW-PERF-2 (a 409 names the running run,
  and the orchestrator's job follows it), T-723 / D-489 (the steward's accept and the night's run wait for each
  other)

## Context

The adapter ran the night's ingest as a thread of its API process, with the runs' states in a dictionary in
memory (PERF-025). Two things followed. A night killed for memory took the service with it. And a restart of the
adapter forgot the run: the orchestrator's job, polling `GET /run/<id>`, got "unknown run" and failed beside a
night that might be published (PERF-008).

## Decision

1. **The service starts the night as a child process**: `python -m adapter.run_job <lock fd> <the request as
   JSON>`. The route decides at once what it decided at once before (409 while an ingest runs, 400 for a bad
   request), answers 202 with the run id, and `GET /run/<id>` follows it. The states are the same four:
   `running`, `done` with the ingest report, `refused`, `failed`.
2. **The run's record is on disk**: `<lake>/adapter-runs/<run id>.json` (`adapter.runs`), written before the
   child starts and by the child at its end. `GET /run/<id>` and `GET /run` read it when this life of the service
   does not know the run. No row of the feed is in it: what the ingest report already holds.
3. **One lock says an ingest runs**: an `flock` on `<lake>/locks/adapter.run.lock`, handed to the child as an
   open file (D-539's pattern: inherited, never unlocked by the starter; the child checks it is that file). The
   kernel frees it when the child ends, however it ends. Beside it, `adapter.run.holder` names the run the lock is
   held for. A run recorded `running` that is not that run, or whose lock nobody holds, is answered `failed: the
   ingest's process ended without an answer`; a child that ended by itself with an error and no answer is
   `failed` with its exit code.
4. **A restart of the service no longer loses what happened.** On the compose box a restart of the adapter is a
   restart of its container: the night's process ends with it (the container's init ends every process). What
   survives is the record: `GET /run/<id>` answers `failed: ended without an answer` instead of "unknown run", the
   orchestrator's job fails with the true reason, and the night is run again. Where the service's process could
   end and the night's go on (not under compose; read, not run), the lock is still held: a new `POST /run` is
   refused 409 and names the running run, and a steward's accept is refused rather than publishing beside it.
5. **The child asks the kernel to be killed first** when the container's memory runs out (as the lake's build
   does): a night can be run again, the service's requests cannot.
6. **`TB_ADAPTER_RUN`** (declared): `process` (default) or `thread` (the ingest in the service, as before).
   `thread` exists because a configuration handed to the service in memory cannot be given to another process:
   that is how most tests drive the service, and the suite sets it. `tests/unit/test_adapter_run_process.py`
   runs the box's way, with real processes.
7. **How long run records are kept is the lake's own retention**: a record of a run that started before the
   oldest snapshot the lake still keeps is dropped when the next run starts. No new number.

## What is not changed

- **The steward's accept (`POST /publish`) is still a thread of the service** with its state in memory. It is
  short next to a night, it reads a folder that already exists, and its own record of steps is on disk
  (`publish.json`, T-723). A restart of the service during an accept still loses the accept's run id.
- The waiting of a night's run behind an accept (T-723) is in the service's memory: a run that waits is written
  to disk when it starts, not while it waits.
- The run's lock is beside, not instead of, the service's own in-memory lock: in one life of the service the
  rules between a run and an accept are exactly as before.

## Consequences

- A night killed under the memory cap no longer ends the adapter's API; the run reads `failed` with a reason and
  can be started again. Tested by stopping the child as it starts and killing it (the interrupt test). The test's
  "restart of the service" clears what the service holds in memory; it does not end the service's process.
- After an adapter restart the orchestrator's job no longer reads "the adapter no longer knows ingest run": the
  record answers, with `failed` and the reason when the night's process ended with the container.
- The question "does a night run" is asked by taking the lock for a moment. All askers and starters are threads
  of the one service process and take turns, so a poll never refuses a night's start (the reviewer showed it
  could: 10 false `failed` in 150 starts under a polling thread).
- A record left `running` by a crash or a restored backup reads `failed` also while a later night runs, and goes
  with the lake's retention like any other.
- A run's start is in UTC and a snapshot is a date of the site: a record is dropped only when its start is before
  the day before the oldest snapshot the lake keeps.
- The night has no memory cap of its own: it runs inside the adapter container's cap. Which process the kernel
  kills is the compose box's behaviour (D-539 says the same of the lake's build, with its limits on a cluster).
- The child reads its configuration from the environment and the settings file at its start, as the service did
  at each run.
- The child is handed the service's own import path (`PYTHONPATH` = the service's `sys.path`): it imports what
  the service imports, whatever put the path there. Found by running: under a test runner that sets its import
  path in process only, the child did not find `datacore`.
- The lock class is a second copy of the pattern of `lake.store.BuildLock` (about forty lines), kept in the
  adapter so the lake's lock is not touched by this card. One class for both is a later tidy-up.

## Not decided here

- The accept as a process of its own, and its state on disk.
- A memory cap for the night alone (the compose file's).
