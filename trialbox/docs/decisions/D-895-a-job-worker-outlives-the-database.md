# D-895 a job worker outlives the database

- **Task:** ORCH-WORKER-RETRY, the integrator's red on #639 (2026-11-16): train 39's validation rehearsal (run
  43794656559), step 17, SCREEN stayed `received` for 1287 s
- **PR:** this branch (`agent/ORCH-WORKER-RETRY-a-worker-outlives-the-database`)
- **Date:** 2026-11-16
- **Status:** accepted

## Cause

At step 12's restart without the installer, the orchestrator came up before host `db` resolved. Each worker's
`self.db.claim()` (`services/orchestrator/core.py`, `_worker`) was outside the loop's `try`, raised
`DatabaseError: cannot reach the trial database`, and the thread ended. The API stayed up and `/healthz` turned green
again once the database answered, so the SCREEN job was accepted and never taken. On a hospital box: after a reboot,
jobs queue for ever and the doctor is green.

## Decision

1. A worker whose claim fails waits and tries again, and never ends. The wait starts at 1 s and doubles up to 30 s
   (`WORKER_RETRY_FIRST`, `WORKER_RETRY_MAX`). It waits on the pool's wake condition, so `stop()` still ends it. It
   logs the first failure of a streak with the error's type, then every tenth wait at the cap, and logs once when the
   database answers again.
2. `Orchestrator.workers_alive()` gives `(alive, started)`. The orchestrator's `/healthz` has a `_workers` check:
   `workers_alive: "4/4"`, or 503 with `_workers: error: WorkersNotAlive` when a started worker has ended. The
   compose health check then fails, the box's watchdog (`tb.watchdog: restart`) restarts the service, and the
   doctor and the console's service health show it red.
3. Compose: the orchestrator already starts after `db` is healthy (the `x-py` anchor's `depends_on`, D-176), and a
   test now pins that. A Docker daemon restart (a reboot) starts the containers without compose's order, which is
   why the worker's own retry is the fix.

**Another lane's file:** `services/orchestrator/core.py` is lane A2's. The diff stays inside `_worker`'s loop, adds
the 3-line `workers_alive` beside `stop`, and adds the two constants. `services/orchestrator/app.py` gains the health
check only. A2 is told on #639.

## Test

`tests/unit/test_orch_worker_outlives_db.py`:

- The database is taken away for real under two running workers: a TCP relay to the test cluster is closed, cutting
  every connection and refusing new ones. Both workers fail, wait and try again, and stay alive. Once the relay is
  open again, a new job is taken. Without the fix, the threads end after the first failed claim and the test fails.
- The health line is red when a started worker is dead.
- The compose dependency is pinned.
