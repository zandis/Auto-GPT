# D-383 Snapshot pinning: every job reads one lake snapshot; a stale snapshot is refused

- **Task:** T-305a, snapshot pinning pulled forward from T-305 (`docs/plan/28-master-plan-v6.md` §6.2.4)
- **PR:** this branch (`agent/T-305a-snapshot-pin`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-063 (jobs not pinned to a snapshot), S-14 (no snapshot-age check)
- **Builds on:** T-106b (lake schema 3; an older night is built but never `CURRENT`), D-82 (the re-run on the job's
  snapshot), D-271 (a bad night never moves `CURRENT`)

## Context

Each scenario read `CURRENT` once (for its report and `snapshot_date`) and then ran most of its queries without
naming a snapshot. A nightly publish that landed mid-job moved those later queries to the new night: one candidate
list could mix two nights, and the job's recorded snapshot was not the one all its rows came from. Nothing refused a
lake that had stopped updating: a box whose ingest failed for a week screened on week-old data without a word.

## Decision

1. **The pin.** Each job's `Ctx` hands its scenario a `PinnedLake` (`services/orchestrator/jobs.py`). The first lake
   call of the job pins `CURRENT`, records it on the job (`Job.snapshot_date`, the pin field) and every later query
   and note search names it. A job that never reads the lake pins nothing. A job that already has a
   `snapshot_date` (resumed after approval, or a reproducibility re-run) keeps it.
2. **The age check.** When a job pins `CURRENT`, the snapshot's night (its name) is compared with the job's run date
   (`lake.store.check_snapshot_age`; the orchestrator's clock, so a frozen clock decides). More than
   `TB_LAKE_MAX_SNAPSHOT_AGE_DAYS` days old fails the job with `LAKE-STALE` and a plain message, before any read. A
   snapshot named after a later day than the run date counts as 0 days old. A recorded pin is not checked again.
3. **The config value.** `TB_LAKE_MAX_SNAPSHOT_AGE_DAYS` is declared in `tb_common.config.Env`
   (`lake_max_snapshot_age_days`; a negative value is a configuration error). The code default is 0 (no check):
   tests, demos and goldens run old synthetic nights on a real or pinned clock. The production compose file sets 3
   for the orchestrator: a weekly screening tolerates a missed night or two, not a dead feed.
4. **The lake.** `Lake.pin(today, max_age_days)` gives the same rule to an in-process caller; the lake clients pass
   a snapshot to the note search (`chunks_search(..., snapshot=)`), which the lake API already accepted.

## Consequences

- A job's rows all come from the snapshot it records; the re-run (D-82) and the audit name the same night.
- A box whose feed stopped fails its lake jobs with `LAKE-STALE` (runbook, troubleshooting) instead of screening on
  old data. STATUS, HELP and other jobs that read no lake still run.
- Pruning keeps the last nights (SPEC §10.3), so a pinned snapshot outlives a job. Pruning does not yet look at the
  pins of running jobs; that belongs with T-305b (batched publish).
