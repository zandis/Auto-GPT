# D-532 A running job holds a lease: one worker runs a job at a time, in every process

- **Task:** NEW-B-11 (the night and capacity lane's queue: "a lease so two workers cannot resume one job")
- **PR:** this branch (`agent/NEW-B-11-job-lease`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** T-689 (D-456: a job interrupted by a restart is queued again, its restarts counted, its kept
  answers replayed), T-704 (D-458: the worker kept for the ingest), D-126 (the trial data is in PostgreSQL)

## Context

`Orchestrator.start()` takes every job that is neither queued nor ended nor waiting for approval for "interrupted
by a restart": it counts a restart, sets the job back to `received` and queues it. That is right for one
orchestrator process. With a second process on the same database (an update that starts the new container before
the old one has stopped; a second replica started by mistake) the second process did it to the jobs the first one
was **running**: two workers ran one job, both wrote its state, its mail could go twice, and the restart count
rose for a job nothing had interrupted. The queue itself was safe (`claim` takes a row with `FOR UPDATE SKIP
LOCKED`); nothing said "this job is being run".

## Decision

1. **A run holds a lease** (`JobDB.lease`, taken at the top of `Orchestrator.run`, released when the run ends in
   any way). The lease is a session advisory lock of PostgreSQL on a connection of its own, keyed by the store's
   schema and the job id (two keys: two jobs never share a lock).
2. **It ends with its holder.** A worker that dies loses its connection and with it the lease; nothing is written
   that a later process would have to clean up. No heartbeat and no time limit (OD-10): the database knows whether
   the holder is alive.
3. **The restart recovery skips a leased job** (`JobDB.leased`): it is not interrupted, so it is not counted and
   not queued. When its holder has died, the next start finds it interrupted, as before.
4. **A worker that gets hold of a leased job's id runs nothing** (logged). The job stays its holder's.

## Reuse check

PostgreSQL's session advisory locks cover it: the box's own database, used for locks already (the generation
ledger, the audit writer), no new dependency. A job-queue library (Procrastinate, PGQueuer) would bring a lease
with it but replaces the jobs table, the claim and the restart recovery: not proposed for this.

## Consequences

- One more database connection per running job (at most the number of workers).
- A job queued again by hand (`requeue`) while it runs is claimed, found leased and not run a second time; its
  running worker goes on. Before, it ran twice.
- If the lease's connection is lost while the worker lives (a database restart), the lease is gone and the run
  goes on without it: for that window the box is as it was before this card. The run is not stopped for it.

## Not decided here

- Two orchestrator processes on one database by design (a second worker container): the lease makes it safe to
  resume; whether the box should run that way is another question.
- A job that waits for approval holds no lease (nothing runs).
