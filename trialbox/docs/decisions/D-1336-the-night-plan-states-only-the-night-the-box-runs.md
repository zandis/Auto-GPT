# D-1336 The night plan states only the night the box runs, with tier figures only when measured

- **Task:** lane H, plan 10 row 10E-11 (night plan per tier; review 13 row 13-12, section 7.3). PR #1203 was ruled
  to lane H on 2026-11-19, 16:11 UTC.
- **Date:** 2026-11-19
- **Status:** proposed
- **Builds on:** D-1320 (the tier record), D-1322 (a reader takes a tier value only when it is measured), D-492 (the
  night chain), H23b-01 (the stated limit of about 45,000 patients)

## Context

Review 13 section 7.3 proposes a night per tier: a CPU note pass on tier A that stops at 06:00, a judge pass, swap
and verifier pass on B, first-load slices on C and D, and a backup window from 06:00. The builders' draft
(PR #1203) wrote that shape into job options that no worker reads, read declared values as if measured, read
records for labels the services do not know (`P-GB10`, `P-CPU`), and cancelled jobs at 06:00. No job runs a
first-load slice or a CPU note pass today, only `rtxpro6000` measures its `models_on_card`, and no record measures a
night budget.

## Decision

1. **The plan states the night the box runs.** `services/orchestrator/night_plan.py` builds one plan at the
   scheduler's start and logs it: the timer's ingest, then the chain's steps (screen, NAV, retention) after the
   ingest ends. It writes no job option. A pass that no job runs (first-load slices, a CPU note pass, the 06:00
   stop, the backup window) is not in the plan until a card builds the job that runs it.
2. **Measured only, through the one reader.** Every tier figure (`models_on_card`, `screen_concurrency`,
   `night_budget_patients`, `judge_calls_per_second`) is read through `tb_common.tier_value.measured` (never raises,
   never hangs). A declared, not measured, missing or malformed value gives no figure, and the plan says which.
3. **An unmeasured tier runs the safe plan.** When `models_on_card` is not measured, the plan is today's night,
   labelled "not measured: the safe plan". No figure is filled from a default.
4. **A ballast record is no record.** `tier_value.measured` answers `malformed` for a record with "by ballast" in
   any string, as `tools/tier_record.py` refuses it. The services' gateway, night budget and console readers follow.
5. **The stated limit.** A measured night budget over 45,000 patients is not taken: the screen step keeps its
   fallback, and the plan says why. A configured budget still wins (D-1322) and is warned when over the limit or 0.
6. **One budget.** The screen step's budget (`microbatch.night_budget`) reads the tier value through the plan's
   `tier_budget`, and the plan reports the number that function returns, so the stated and enforced budgets are one.

## Consequences

- No shipped box changes behaviour: both records are free of ballast, neither measures a night budget, and every
  other label keeps 2000 patients.
- The `rtxpro6000` plan says "judge and verifier both resident"; the 32 GB box's plan says "not measured: the safe
  plan" until R-1 measures it.
- Review 13 section 7.3's tier A cutoff, the first-load slices and the scheduler's backup window are open work for
  the cards that build those jobs (see `docs/handover/night-plan-per-tier-2026-11-19.md`).
