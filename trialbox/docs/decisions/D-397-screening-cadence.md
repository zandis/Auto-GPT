# D-397 Screening cadence: new patients every week and after each ingest, inside a night budget

- **Task:** T-624, screening cadence (`docs/plan/28-master-plan-v6.md` §6.2.4)
- **PR:** this branch (`agent/T-624-screening-cadence`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** LIFE-014 (new patients enter the candidate pool once a month)
- **Builds on:** D-383 (each job pins one lake snapshot), D-386 (lists only for an open study), D-147 (opt-out),
  D-82 (byte-identical re-run)

## Context

The weekly MICROBATCH re-checked the pool's patients with a visit in the next 14 days, time-sensitive criteria
only. New in-scope patients were screened on the first Monday of a month, or by hand. A first-visit patient booked
for next week, the best candidate in a memory clinic, was missed. There was no screen after the nightly ingest, and
nothing bounded how many patients a night's runs evaluated.

## Decision

1. **Every weekly run screens new patients.** MICROBATCH screens the study's new in-scope patients in every run
   (the scope of SCREEN: who the study's set-up page says to screen). The first-Monday rule is gone; `incident=0`
   still asks for a re-check only.
2. **After each ingest, the booked new patients.** An ingest that passed submits a MICROBATCH with
   `trigger=ingest` for every study with a candidate pool (`orchestrator.scheduler.after_ingest`, called by the
   INGEST scenario). It screens only new patients with a booked visit in the micro-batch window (14 days) and does
   not re-check the pool. It mails the list only when it found a new candidate. A study that is not open is held
   (D-386). After the timer's ingest (option `timer=1`) the night's model self-test must pass first, as for the
   other night jobs; an ingest asked for by hand is followed at once.
3. **Who is new.** In scope, and on none of these lists: the pool, the study's last SCREEN (its candidate and
   excluded lists), the latest micro-batch record after it (`new_screened_<study>_v<version>.json`, phi, never
   mailed, cumulative). A patient excluded by SCREEN is not screened again until the next SCREEN. Nearest visit
   first; patients with no visit last.
4. **The night budget.** `TB_MICROBATCH_NIGHT_BUDGET` (patients, default 2000, 0 = no limit, declared in
   `tb_common.config.Env`). The micro-batch jobs of one run date, every study together, evaluate at most that many
   patients. A job takes what the night's earlier micro-batch jobs used (their `patients_scoped`) off the budget,
   re-checks the nearest visits first, then screens new patients. The rest carry over to the next run. The summary
   says how many, and the audit event `microbatch.budget` records the numbers. Nothing is cut in silence.
5. **Re-runs.** The allowance (`night_left`) and the lists that define "new" (`seen_from`) are fixed in the job's
   options on its first run. A resumed job and a re-run (D-82) use the same ones. Pool rows the job itself added
   are not treated as the pool's.
6. **The console's list.** MICROBATCH now stores `candidate_list_<study>_v<version>.json` (phi, not mailed): the
   whole pool and the new candidates. Before, the week page took the latest SCREEN or MICROBATCH job and found no
   list on a MICROBATCH, so the page was empty after a weekly run.
7. **The snapshot.** The micro-batch reads the lake through the job's pinned lake (D-383). Its rows come from one
   night and the job records it.

## Consequences

- A patient who first appears in Tuesday's data with a Friday visit is on the PI's clinic list on Wednesday
  morning. `tools/e2e_simple.py` stage 17 checks this on the synthetic hospital.
- The nightly cost is bounded by the budget. Studies share one budget per night. When it runs out, the work
  waits for the next run and the summary says so.
- The budget counts patients, not model tokens. A token budget (SPEC CAS-4a) can replace the count later without
  changing the carry-over rule.
