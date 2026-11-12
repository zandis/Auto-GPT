# D-523 On 409 the orchestrator's INGEST job follows the ingest that is running

- **Task:** NEW-PERF-2 / NEW-ARCH-1 (TB-PLAN-07 wave 0, lane B; deep review PERF-008 and ARCH-002)
- **PR:** this branch (`agent/NEW-PERF-2-follow-running-ingest`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-472 (T-690: the ingest is a polled job on the adapter; one ingest at a time, a second start is
  409), D-456 (T-689: a job that was running when the orchestrator stopped is queued again at its start)

## Context

The night's ingest runs on the adapter; the orchestrator's INGEST job starts it (`POST /run`) and reads its state
until it ends. When the orchestrator restarts during the ingest, the job is queued again and asks for a start. The
adapter is still on the first run and answers 409. The job failed at once ("an ingest is already running") while
the adapter finished the night and moved `CURRENT`: a published night with a failed job, no stored ingest report,
no micro-batch for the new patients, no twin build, a "failed" mail to the site, and an administrator's retry that
ran a second ingest of the served night (PERF-008, ARCH-002; both run in the review).

## Decision

1. **A 409 from `POST /run` that names the running run means "the night is running": the job follows it.**
   `AdapterHttp.run` reads the run the 409 names (`X-TB-Run`, D-472; `ServiceError` now carries the refusal's
   headers) to its end as if it had started it: the run's report is the job's report, the run's failure the job's
   failure. The read is the poll's, which bears silence up to its declared bound.
2. **Never "the adapter's newest run".** The adapter holds its lock before it registers the new run, so its newest
   registered run can be last night's, ended. A 409 that names no run is the failure it was: the administrator's
   retry starts or follows.
3. **The job writes the adapter run it is on into its record** (`options.adapter_run`) as soon as it is known. A
   job that follows the run it started itself before a restart goes on as if nothing happened.
4. **The steps that follow an ingest run once per adapter run** (the derive batch, the screening that follows, the
   twin build, the report's publication): in the first job that is on the run. A second job that follows the same
   run (an administrator's retry beside the timer's job; two jobs queued again together) ends with the run's
   result and says that the steps run in the other job.
5. **A job whose own request did not run does not end "done".** A job that asked for a back-fill (`since`) and
   followed a run that is not its own fails when the run has ended, with words that say its request was not run.

## Consequences

- After an orchestrator restart during the ingest the INGEST job ends "done" with the night's report, and what
  hangs on the job's end runs (the derive batch, the micro-batch or the night's chain, the twin build).
- An adapter restart during the ingest is not covered: its runs are in its process memory, and a poller is told
  the run is lost (D-472). The night's state as a data-operations row that a restarted adapter answers from is
  T-723's row and its follow-up.

## Not decided here

- **An orchestrator restart that outlasts the ingest:** the job queued again finds no run in progress, starts a
  new one and ingests the served night a second time (the re-run rules of D-271 and D-489 apply). Knowing that the
  night is already done needs the night's state where a restarted process reads it: the data-operations row.
- A job without `since` that follows a run another caller started with another source or snapshot ends with that
  run's report (which names the real snapshot).
