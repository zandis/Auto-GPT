# D-492 The night runner: a step starts when the step before it has finished

- **Task:** T-726 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.3, wave G; the night and capacity lane; it absorbs
  the chain of T-704)
- **PR:** this branch (`agent/T-726-night-runner`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** F-33 (the chain: fixed times; two micro-batches of one study) of
  `docs/reviews/2026-11-11-scale-timeouts.md`; root cause S3 in part ("the night is not an object") of the review of
  2026-11-12
- **Builds on:** D-397 (the screening cadence: a weekly micro-batch, and one after every ingest that passed), D-386
  (a list job runs only for an open study), D-490 (T-724: a generation), D-474 (T-746: the administrator's retry of
  a scheduled job), OD-10 (no fixed time that is not derived)
- **Read by:** T-704 (the micro-batch allowance, retention, the nightly deltas)

## Context

The night was a list of clock times: the ingest at 02:00, the weekly micro-batch at 03:00, NAV at 03:30, retention
at 05:00. The times assumed an ingest of under an hour. At 50,000 patients the ingest is longer, so Monday's
micro-batch started while the ingest still ran and screened on last night's snapshot, with no notice; the
micro-batch that follows every ingest then ran a second time for the same study the same night, and both mailed
(F-33). Retention ran at its hour whatever the others were doing.

## Decision

1. **Only the ingest and the monthly jobs keep a clock time** (`INGEST`; `COHORT` and `CALIBRATION` on the 1st).
   The weekly micro-batch, the weekly NAV and the daily retention have no timer of their own any more. Their
   schedule entries keep their meaning for the **day** (`MON`); the hour in them is no longer read.
2. **The night is a chain that follows the ingest** (`orchestrator.night`). When the timer's ingest has passed,
   the steps run in this order, each started only when every job of the step before it has ended:
   `screen` (one micro-batch per study with a candidate pool), `nav` (on its day, one per approved NHI ruleset),
   `retention` (every night). A step with nothing to do is passed over. The model steps wait for the night's
   self-test as before; a night whose self-test failed passes over them, says so in the audit, and still runs
   retention.
3. **One run per study and generation.** Every job the chain starts carries the night it belongs to in its record
   (`options.night`: the generation the ingest published, else its date; `options.step`). Before the chain starts
   a job it looks for one of that type, study and night; it never starts a second. On the weekly day the
   micro-batch is the weekly one (it covers the new in-scope patients and those booked in the window); on other
   nights the one that follows the ingest (D-397): never both.
4. **A weekly step that missed its day runs at the next night that passes.** A step is due when no run of it for
   the study exists for a night since its last scheduled day. So a Monday whose ingest failed or was held is made
   up on Tuesday's night, on Tuesday's snapshot: the weekly jobs never run on a snapshot older than the ingest
   they follow.
5. **A restart resumes the step it was in.** The chain keeps no state of its own: it is read from the jobs (the
   last timed ingest that passed, and the chain's jobs of that night). `advance` is called when the ingest ends,
   when any job ends, and when the orchestrator starts: after a restart the interrupted jobs are queued again by
   the orchestrator and the chain goes on from the first step that is not finished.
6. **An ingest asked for by hand** is followed by its micro-batch as before (D-397) and starts no weekly step: a
   person asked for an ingest, not for the night.

## Consequences

- Monday's jobs pin the snapshot Monday's ingest published, however long the ingest took.
- The night's length is the sum of its steps; nothing is cut at a clock time (OD-10).
- `settings.schedule.microbatch`, `.nav` and `.retention` are read for their day only.

## Not decided here

- The backup as a step of the chain: it runs from the host's timer and already waits for running jobs (D-455).
- The micro-batch allowance, retention's keep rule and the nightly deltas (T-704).
