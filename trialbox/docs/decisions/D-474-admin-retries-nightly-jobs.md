# D-474 The administrator may retry a failed nightly job of the box's scheduler, with the failed job's own inputs

- **Task:** T-746 (owner's ruling of 2026-11-12: "Admin can retry")
- **PR:** this branch (`agent/T-746-admin-retries-nightly-jobs`), stacked on T-713 (D-464, PR #288)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI, after PR #288)
- **Builds on:** D-464 (the orchestrator admits each calling service to its own routes; `requested_by: scheduler`
  never comes over HTTP), D-146 (a console job is authorised by the signed role), D-178 (the administrator's
  operations rows), D-366 / D-380 (the permission matrix, `permit`)

## Decision

1. **One right, not three.** The matrix gains one action, `job.retry_scheduled`, held by the administrator only: run
   again a FAILED job the box's own scheduler started (every type of `orchestrator.scheduler.plan`: INGEST,
   MICROBATCH, NAV, COHORT, RETENTION, CALIBRATION), with that job's type, study, options and inputs. It is not a right
   to start INGEST, RETENTION or CALIBRATION: `command.INGEST` and its siblings stay absent, so `POST /jobs` still
   refuses them for the administrator's role.
2. **The orchestrator copies, the console names.** `POST /jobs/{job_id}/retry` (route group `job_retry_scheduled`,
   the console's row only in `route_callers.yaml`; the mail gateway and the operator token are refused by the D-464
   gate) takes the failed job's id and the administrator's reply mailbox, nothing else (an unknown body field is
   422). The orchestrator verifies the signed person and role (`permit(role, "job.retry_scheduled")`), that the job
   failed, and that it is a scheduler job: `requested_by` is `scheduler`, or it is itself such a retry (its
   `parent_job_id` chain ends at a scheduler job of the same type and study). It then creates the new job from the
   failed job's own fields.
3. **No two at once.** A retry while a job of the same type and study (none for INGEST and RETENTION) is not finished
   is refused (409, "already queued or running"): no two ingests at once. There was no such rule for `POST /jobs`;
   this one holds for the retry only.
4. **Who and what it retries.** The new job's `requested_by` is the administrator's mailbox (the reply address), its
   `parent_job_id` the failed job; one audit event `job.retried` names the failed job, the new job, the type, the
   signed person and the role (labelled in en, ja and zh-TW), beside the usual `job.state`.
5. **The console.** The jobs tab shows Retry again on every failed scheduler job when the account holds
   `job.retry_scheduled`; the console route calls the new orchestrator route and sends no type or options. The
   T-713 "runs again at its next scheduled time" refusal and its text are removed. A failed job a person started is
   retried as before (`POST /jobs` under the person's role).

## Consequences

- The administrator can run a failed night's INGEST, RETENTION or CALIBRATION again the same day, with the night's
  options, and cannot start one with options of their own.
- A retried scheduler job mails its notices to the administrator (the scheduler's own jobs mail nobody).

## Open

- The "not finished" check and the insert are not one transaction: two clicks in the same instant could both pass.
  The console's confirm step makes this unlikely; a lock is a follow-up if it is ever seen.
