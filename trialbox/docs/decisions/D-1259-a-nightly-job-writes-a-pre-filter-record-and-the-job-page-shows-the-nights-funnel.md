# D-1259 A nightly job writes a pre-filter record, and its job page shows the night's funnel of its study (10E-12)

- **Task:** card 10E-12 of plan 10, Track E (`docs/plan/47-plan-10-2026-11-18.md`, row 10E-12; review 13 item 13-13:
  "pre-filter report per study per night"). Lane J. The counting is lane H's (its comment on PR #639 of 2026-11-19
  19:21 UTC), built as written except where this file says. · **Date:** 2026-11-19
- **Status:** accepted; the number is reserved for this card (lane J's block D-1220 to D-1319).
- **Builds on:** D-397 and D-642 (the nightly cadence: re-checks, new patients, excluded patients screened again),
  D-458 and D-646 (the night budget and the excluded patients' share), D-147, D-441 and D-477 (the opt-out register
  and the consent rule), D-118 and D-142 (a patient not at the index date is not screened), D-99 (exact counts on
  internal console pages), D-467 rule 5 (complementary suppression of a funnel's drops), H-45 (a job's metrics carry
  a per-job record), D-1245 (the first-load card on the same page, and its gate).

## Context

The nightly screening (MICROBATCH) filters patients in stages before the model judges any. A nightly job published no
funnel: the counts existed only in the `microbatch.budget` and `screen.evaluated` audit events, per job, and not as
patients (a patient re-checked and then screened again was in both). Sites and the owner want, per study per night,
how many patients were in scope and how many each stage removed.

## Decision

1. **The record.** When a nightly job finishes it writes one pre-filter record into its own metrics, beside
   `patients_scoped`: `JobMetrics.prefilter` (job schema 1.2.0; `PrefilterRecord` in `schemas/job.schema.json`). The
   job's metrics are stored in the jobs table's JSON `data` column: no SQL migration. The audit schema and
   `ROLE_EVENTS` are not touched. Counts only (a trigger and nine integers); the pseudonyms used to count live in the
   job's memory and are never stored. Other jobs carry no record (absent, as `step_seconds` is on all but APPROVE).
2. **The stages** (`tb_common.prefilter.STAGES`), each patient in exactly one, in the funnel's order:
   - `opted_out`: on the opt-out register, a refusal of research use or of contact (D-477), or not at the index date
     (every answer "unknown" for `not_in_snapshot` or `check_dates`: not in the snapshot, deceased or not yet born);
   - `not_due`: in scope, not looked at by this run's cadence (a pool row with no visit in the window, a weekly run
     with nothing to re-check, and, on an after-ingest run, every patient of the scope that is not a new booked one);
   - `carried`: due, and left by the night budget for a later night;
   - `coded_excluded`: evaluated, and a criterion the coded records decide was not met;
   - `no_model`: evaluated, past the coded filter, not listed, and the model read no note for them;
   - `model_not_listed`: evaluated, past the coded filter, the model read their notes, not listed;
   - `listed`: evaluated and listed (high or review).

   `in_scope` is their sum. **One stage added to lane H's list:** `model_not_listed`. Without it a patient the model
   read and did not list fits no stage, and the stages do not add up to "in scope". The model "read the notes" when a
   note answer of this evaluation has a reason other than not evaluated, the model down, no notes, the gateway's
   refusal or a person's criterion. For a pool row the re-check's own answers decide, not the stored ones.
3. **Counted once, at the last evaluation.** Inside a job: an evaluation always replaces what was said of the patient
   before, and a stage reached without an evaluation replaces only another such stage. So a pool row re-checked,
   excluded by the codes and screened again the same job counts once, at the screen. A pool row re-checked and then
   carried by the excluded patients' budget counts at the re-check.
4. **The night.** `tb_common.prefilter.night_funnel` sums the records of the study's finished MICROBATCH jobs that
   share the `run_date`. A night with no such record has no report (None, never a funnel of zeros). **Not exact across
   jobs:** a record holds no ids, so a patient two jobs of one study looked at on one night (a weekly run and an
   after-ingest run, or a weekly run started twice by hand) is counted by each. The page says so. Making it exact
   needs per-patient state across jobs (for example a phi stage map in the existing `new_screened_` document); that is
   not built and is the coordinator's to rule.
5. **Where it is shown.** On the existing job page (`/pilot/jobs/{id}`) of a finished nightly job with a record, one
   more card beside the first-load card. Shown to exactly the accounts the first-load card is shown to: the study's
   candidate list's own check (`Helpers.admits_candidates`: the study is seen and the account has its `screen` task;
   no break-glass grant opens it). The check comes before any other job is read. The coordinator on the delegation
   log sees it; an investigator off the log, a viewer and the privacy officer do not, and nothing is read for them.
   No new route, page, export, role or right. The console reads the night's jobs through the orchestrator's existing
   `GET /jobs` with its existing `ruleset` and `type` filters (the console's backend gained the two keyword
   arguments). It reads at most 500. When all 500 belong to this night or a later one, an earlier job of the night may
   be missing, and the card is not shown (never a short count).
6. **Exact counts** on this internal page (D-99). Anything mailed or exported goes through
   `tb_common.prefilter.publishable` (`funnel_drops_publishable`, complementary suppression). This card mails and
   exports nothing.
7. **Byte-identical without a record.** A job page with no record (a nightly job from before the record, any other
   job, a nightly job not finished) renders the same bytes as master's.

## Consequences

- The re-check rows are in the funnel, as `screen.stage_funnel` counts them.
- `stage_funnel` (SCREEN's funnel) compares a note answer's reason with the text "not evaluated", which no answer
  carries since the reasons became codes (`not_evaluated`). Its "notes read" count therefore includes note answers
  nobody gave. This card does not change it (another page's figure); it is reported as a finding.
- Tests: `tests/unit/test_prefilter_night_10e12.py` (the tally, the stage order, the night's sum, a night with no
  job, the suppression for mail, counts only, and a weekly and an after-ingest job end to end) and
  `tests/console/test_night_funnel_page.py` (three languages, the role walk, a night that cannot be read whole, and
  the render comparison).
