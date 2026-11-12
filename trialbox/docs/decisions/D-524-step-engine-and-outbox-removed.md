# D-524 The unused step engine, its outbox dispatcher and schema `wf` are removed

- **Task:** NEW-ARCH-2 (TB-PLAN-07 wave 1, lane B: "delete `StepStore`/`Dispatcher`"; deep review ARCH-004)
- **PR:** this branch (`agent/NEW-ARCH-2-delete-stepstore`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Supersedes:** D-127 (delivery through the outbox) where it describes the orchestrator's own outbox
- **Builds on:** D-456 (T-689: a job that was running is queued again and replays its kept model answers), D-401
  (T-108c: the mail gateway's send keys are the outbox of a mail), D-126 (one trial database)

## Context

`services/orchestrator/db_pg.py` held a durable step engine (`StepStore`: leases, attempts, an input hash, a
recorded output) and `services/orchestrator/outbox.py` a dispatcher for its outbox table, both in schema `wf`.
Nothing a job runs calls either: the only callers were their own kill-loop test and one line of another test. The
architecture page still said "delivery goes through the outbox", and the erasure registry carried two tables as
owed that hold nothing on a box. T-689 was built on the job row and the kept answers, not on `StepStore`
(ARCH-004: "decide once: use it or delete it").

## Decision

1. **Deleted:** `StepStore` and its types, `orchestrator/outbox.py` (`Dispatcher`), their test
   (`tests/unit/test_outbox_killloop.py`: it tested only the deleted code), the migrations of schema `wf`, its
   migration baseline, its two entries in the erasure registry, its row in the record inventory, and `wf` in the
   schema lists of the orchestrator's and the console's database roles.
2. **Kept:** the backend (`PostgresBackend`, `open_backend`; the recall ledger is on it, schema `recall`) and the
   database `trialbox_wf`. A backend is now opened with its schema named: there is no default schema.
3. **How the two promises are kept instead** (ARCHITECTURE §9): a mail leaves once through the mail gateway's send
   keys (D-401); a job resumes from its row and its kept answers (D-456).

## Consequences

- No service ever created schema `wf` on a box (only the deleted test and tools did), so there is nothing to
  migrate. A development database that has it keeps two empty tables nobody reads: `DROP SCHEMA wf CASCADE` by
  hand, or leave it. A backup that holds the schema restores as before.
- About 760 lines and one schema fewer to read as "the crash safety of jobs".

## Not decided here

- A lease so that two workers cannot resume one job (the plan's next row for this lane): it goes on the job row,
  not on a step table.
