# D-539 The lake's build is a process of its own

- **Task:** PERF-001's part "the build as its own process" (PERF-025 of the review of 2026-11-12; plan v7, wave 2,
  lane B)
- **PR:** this branch (`agent/PERF-001-lake-build-own-process`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** T-690 / D-472 (a rebuild is a job with a state file, followed by polling), D-462 (the build lock),
  T-692 / D-473 (the build reads and writes in streams), T-724 / D-490 (generations)

## Context

The lake service started a rebuild as a thread of one of its query workers (`lake.app._spawn`). The review
measured what that costs (PERF-025): a query beside a rebuild thread went from a median of 180 ms to 297 ms at
4,000 patients, and, the part that matters on a night, **when the build is killed for memory it takes the query
worker and every query in it along**. The job's state was already outside the worker (a file beside the build
lock; a job whose lock nobody holds reads `interrupted`), so the build did not need to live in the worker.

## Decision

1. **The service starts the build as a child process**: `python -m lake.build <lock fd> <the job as JSON>`
   (`lake.app._launch`). The route still decides at once what can be decided at once (held, already building,
   no feed folder: 409, nothing written), writes the job `running`, and answers 202. Following the job
   (`GET /rebuild/<snapshot>`) is unchanged, and so is every state.
2. **The build lock is handed over, not taken twice.** The lock is an `flock` on an open file. The starter takes
   it, the child inherits the open file (`pass_fds`), and the starter closes its end without unlocking
   (`BuildLock.hand_over`). There is no moment without a holder. The child asks for the lock again on the file
   it was given (`BuildLock.adopt`), after checking that the file is the snapshot's lock file; the kernel grants
   it only if that open file holds it or nobody does. The starter never unlocks, also when the start fails: an
   unlock would take the lock from a child that shares the open file. When the
   child ends, however it ends, the kernel frees the lock and the job reads `done`, `refused`, `busy`, `failed`
   or, with no answer written, `interrupted`, as before.
3. **The child reads what the service reads**: the lake's folder is passed; the site's zone, the chart-number
   pattern and the embedder come from the environment (`TB_TZ`, the site's pattern, `TB_LAKE_EMBEDDER`,
   `EMBED_URL`), as the service's own do. Nothing else crosses: no patient data is in the arguments.
4. **The kernel is asked to kill the build first** when the container's memory runs out: the child raises its own
   `oom_score_adj` to the kernel's maximum (1000, the kernel's scale, not a limit of ours). A build can be started
   again; a query worker's requests cannot.
5. **A build that cannot be started is the job's end**: `failed`, with the error's type, and the lock is freed.
   If the failure comes after the process exists, the process is killed first: a caller told `failed` never gets
   a build behind that answer. A process that ends by itself with an error and no answer (it could not import,
   its job could not be read) is `failed` with its exit code, written by the worker that waits for it; only a
   process that was killed reads `interrupted`.
6. **`TB_LAKE_BUILD`** (declared): `process` (default, what a box runs) or `thread` (the build in the worker, as
   before). `thread` exists because a lake or an embedder handed to the service in memory cannot be given to
   another process: that is how most tests drive the service, and the test suite sets it for them
   (`tests/conftest.py`). `tests/unit/test_lake_build_process.py` runs the box's way, with real processes.

## Consequences

- A build killed under the memory cap no longer ends the worker: the worker answers queries, the job reads
  `interrupted`, the snapshot can be built again. Tested by stopping the child as it starts and killing it
  (the interrupt test).
- A worker that is killed no longer ends a build it started: the child holds the lock itself and goes on. It
  is then an orphan: on the compose box the container's init (`init: true`) reaps it when it ends. The Kubernetes
  form has no init in the lake's container, so the ended child would stay in the process table as an entry
  without memory until the container restarts. With its worker gone nobody writes `failed` for an exit code: such
  a build reads `interrupted`.
- The child is in the worker's process group (not a session of its own): whatever stops the service's processes
  as a group stops the build too, and the scale gate's teardown reaches it.
- **Which process the kernel kills is the compose box's behaviour.** Where the platform kills the whole container
  when memory runs out (Kubernetes with cgroup v2 does, by what is documented; not verified here), decision 4
  changes nothing and the worker dies with the build, as before.
- **The scale gate** (`tools/scale_gate.py`) runs the lake as a box does (`TB_LAKE_BUILD=process`), hands the
  build the memory limit the service derives from the cap, and reads a build killed alone as the rebuild not
  ending under the cap.
- The test suite sets `TB_LAKE_BUILD=thread` (set, not defaulted: a shell that exports the box's value does not
  change what the tests drive).
- **The build has no memory cap of its own yet.** It runs inside the lake container's cap (`TB_MEM_*`, and
  DuckDB's `TB_LAKE_MEMORY_LIMIT`, which the child reads from the same environment). What this decision gives is
  which process dies. A cap for the build alone (a one-shot container, or a cgroup of its own) is the compose
  file's and the deploy lane's.
- The build's Python starts each time (imports; about a second) and opens its own connections. Nothing is shared
  with the worker's memory, so a worker's caches are not warmed by a build.
- The adapter's own in-process lake step (`TB_ADAPTER_LAKE` not `http`) and tools that call `Lake.rebuild`
  directly are not changed: they are already not a query worker.

## Not decided here

- The adapter's ingest as a process of its own (the other half of PERF-025; its run record is PERF-008).
- A memory cap for the build alone (see above).
