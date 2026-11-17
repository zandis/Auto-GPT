# D-1124 A steps-mode box starts the orchestrator's opt-out worker, and nothing else of its start-up

- **Task:** lane H, card H-25 (the integrator, 2026-11-17 12:47 UTC: "F-20 is yours")
- **PR:** this branch (`claude/lane-h-25-start-up-on-the-steps-box`), from master merged with H-20's head
- **Date:** 2026-11-17
- **Status:** reserved
- **Builds on:** D-1135 (H-20's life-cycle walk, its finding F-20), D-1062 (steps mode), D-441 (the opt-out worker),
  D-465 (the erasure registry)

## Context

H-20's walk found that on a steps-mode box an opt-out never completes: finding F-20, which blocked the step.

The opt-out register takes the patient and the lists withhold them, but none of the erasure registry's clears ever
runs. The health check `tb_health_check_level{check="optout_worker"}` stays at 2.

The cause is in `tools/demo.py`, which builds the orchestrator in process (`tools/feas_demo.py`, `tests/inproc_box.py`)
and serves the console. The orchestrator's start-up (`services/orchestrator/app.py`, `lifespan`) never runs, and that
start-up is what starts the worker.

## Decision

1. **Only the opt-out worker.** After the seed and its checks, on the step that serves (never with `--no-serve`),
   `tools/demo.start_up` starts the worker by its own public start (`datacore.optout_worker.start`, unchanged). The
   orchestrator is built as before and the lifespan is not run.
2. **The rest stays off, by name.** `tools.demo.START_UP` lists each part of the lifespan with its setting:
   - the job workers: off (the box runs its jobs in process);
   - the model pair canary: off;
   - the night's clocks (INGEST, CALIBRATION, COHORT, the weekly not-matched sample): off, or a box would ingest
     again and move its synthetic data at night;
   - the site-publish batch tick: off;
   - the opt-out worker: on.

   A test reads the lifespan's code and fails on a part the table does not name. It also holds that a start without
   `TB_ENV`, with DEV or with PRODUCTION starts the worker and no scheduler and no canary. If the start-up as a whole
   is ruled for, the other parts are turned on in this one table.
3. **What a tester sees, and when.** The worker's first run is at the console's start, then every minute
   (`TB_OPTOUT_WORKER_MINUTES` is 1 on a demo box unless set). Within a minute of an opt-out the audit trail (the
   steward's, event "Opt-out worker run") shows a run, and its record in the audit log:
   - counts the new opt-out;
   - names every clear of `docs/validation/erasure-registry.md` §1 (candidate_pool, candidate_registry, held_mail,
     omop, owed_tables, pid_pending, profile, screening_log, setup_uploads, vec);
   - has nothing failed and nothing left.

   `omop` and `vec` report "skipped": this box has no OMOP store and no vector store. The administrator's `/metrics`
   shows `tb_health_check_level{check="optout_worker"} 0`. The Health tab still shows no line for it (F-21 stands).
4. **The walk.**
   - Step 21 of H-20's walk is now the steward's: the audit trail filtered to the worker's event. The walk notes the
     newest run, then waits on that page (read again every 2 s, at most 240 s) for a newer one, which is a run after
     the opt-out.
   - The page shows the run but not what it did: the browser shows only its allowed detail keys, and the worker's are
     not among them. So the test reads the run's own record in the box's audit log (`TB_WALK_AUDIT_DIR`, set by the
     walk's box fixture) and asserts every clear of §1, none failed, nothing left. A box given by its address has no
     log on the walk's machine, and the test says so as a reasoned skip after the pages have passed.
   - New finding F-22 (lane C2, slows the tester): a steward cannot see on any page what an erase did.
   - Step 22 is the administrator's `/metrics` at level 0, which means the last run had nothing failed and nothing
     left.
   - The coordinator is refused both pages.
   - F-20 leaves the plan and the findings page, which stay equal, and the erase leaves "cannot complete".

## Test

`tests/unit/test_h25_demo_start_up.py` holds the table against the lifespan, that only the worker starts (also without
`TB_ENV`), that a set interval is kept, and that the box starts it only when it serves. It fails on master (no
`start_up`). In `tests/e2e/test_life_cycle_walk.py`, the walk's steps 21 and 22 fail on master, where the worker
never runs and the health check is 2.
