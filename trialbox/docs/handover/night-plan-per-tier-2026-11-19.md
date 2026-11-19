# The night plan follows the tier (card 10E-11, 2026-11-19)

**Reader:** the people who build TrialBox

Plan 10 row 10E-11 (review 13 row 13-12, section 7.3). The builders' draft, PR #1203 (head `c54021d3`), was ruled to
lane H on 2026-11-19, 16:11 UTC with three High and four Medium findings. Lane H started again from master: the
draft's design (tier shape written into job options) was the cause of every High finding. Decision D-1336.
Findings: [findings.json](night-plan-per-tier-2026-11-19/findings.json).

## What the box does now

At start the scheduler builds the night plan (`services/orchestrator/night_plan.py`) and logs it, for example:

    night plan (rtxpro6000): ingest 02:00, then screen > nav > retention after it ends; models: judge and verifier
    both resident, the pair at the screen concurrency; night budget 2000 patients (fallback; tier figure not
    measured); screen concurrency declared, not measured; judge calls per second not measured

| Box (`TB_PROFILE`) | Plan |
| --- | --- |
| `P-PRO6000` | the resident pair (measured); budget, concurrency and rate not measured: 2000 patients, the fallback |
| `P-5090` (the 32 GB site box) | "not measured: the safe plan"; every figure not measured; 2000 patients |
| any other label, no record | the safe plan, "no tier record for this TB_PROFILE" |
| a ballast, malformed or unreadable record, a pipe | the safe plan; the reader answers `malformed` at once |
| a measured budget over 45,000 | not taken; 2000 patients; a warning names the stated limit |

The plan writes no job option and cancels nothing. The screen step's budget (`microbatch.night_budget`) reads the
tier value through the plan's `tier_budget`, so the two never differ.

## The findings of PR #1203

| Id | Finding | Now |
| --- | --- | --- |
| N11-01 High | pass order, concurrency and residency written into options the worker never reads | no option is written; the plan names only the chain's steps |
| N11-02 High | a coded-only plan still dispatched MICROBATCH, which can ask the judge | the plan makes no coded-only claim; a record measuring no model is warned as differing from the configuration |
| N11-03 High | the 06:00 CPU note cutoff cancelled jobs, then the chain made a new CPU note job | no CPU note pass, no cutoff (no job runs a CPU note pass) |
| N11-04 Medium | the cutoff searched only the 200 newest jobs | no cutoff |
| N11-05 Medium | the backup window wrote nothing on the shipped Compose (no operations folder) | the scheduler opens no backup window |
| N11-06 Medium | `P-GB10` read `gb10.json` in the plan but not in the worker: 750 stated, 2000 enforced | one reader, one budget, on every label |
| N11-07 Medium | two first-load slices with the same name | no first-load slices; step names are unique |

## Left open

- Review 13 section 7.3's tier A CPU note pass with its 06:00 stop, the first-load slices of C and D and the
  scheduler's part in the 06:00 to 08:00 backup are not built: no job runs them. The card that builds the job adds
  it to the plan (`night_plan.build`), with a test that runs it, not one that reads its options.
- `screen_concurrency` is declared on both records; the plan reports it as not measured. The running concurrency is
  `TB_SCREEN_LLM_CONCURRENCY` as before.
- The `P-GB10` and CPU boxes have no tier record (D-1322); their plan is the safe plan.

## Tests

`tests/unit/test_night_plan_per_tier.py`: one test per tier, per not-a-record case (ballast, malformed, deep, pipe),
the stated limit (its figure taken from `tests/unit/test_screen_limit_stated.py`) and each finding above. On the
builders' head 30 of its 31 tests fail.
