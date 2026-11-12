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

1. **A 409 from `POST /run` means "the night is running": the job follows it.** `AdapterHttp.run` asks the adapter
   for its newest run (`GET /run`) and reads that run to its end as if it had started it: the run's report is the
   job's report, the run's failure the job's failure.
2. **Nothing to follow is the failure it was.** Another refusal (400, 5xx), an adapter that cannot be asked, or
   one that knows no run (it restarted between the two requests) fails the step with the adapter's own words.
3. **Whose run it is does not matter.** The run that is followed may have been started by the job before the
   restart, by the console, or by a person: one ingest runs at a time, and its end is what the box serves next.

## Consequences

- After an orchestrator restart during the ingest the INGEST job ends "done" with the night's report, and what
  hangs on the job's end runs (the derive batch, the micro-batch or the night's chain, the twin build).
- An adapter restart during the ingest is not covered: its runs are in its process memory, and a poller is told
  the run is lost (D-472). The night's state as a data-operations row that a restarted adapter answers from is
  T-723's row and its follow-up.

## Not decided here

- The 409 carries the run's id in `X-TB-Run` (D-472); the client asks `GET /run` instead because the service
  error does not carry headers. One request more, the same run.
