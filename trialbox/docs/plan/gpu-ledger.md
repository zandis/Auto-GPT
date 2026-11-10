# GPU ledger

The queue of long runs on the two GPUs the project has (TB-PLAN-06 §4, RSK-51, card T-664). The cloud GPU quota is
one spot VM; this ledger replaces the request for more quota (CR-070, moot). Runs go one at a time on each machine.
Every cloud run needs the owner's OK and its cost first, and ends with the VM `TERMINATED`. A finished run fills
hours, pre-emptions, cost and the record path. No model is named here: "the model pair" is the judge and the verifier.

## Machines

| Machine | Kind | Who may start a run | Cost |
| --- | --- | --- | --- |
| Spot VM | one cloud VM with one RTX PRO 6000, pre-emptible | an agent session, after the owner's OK per run | per GPU-hour, to record per run |
| Owner's B200 | the owner's own machine | the owner or the named second operator (Q-08); an agent only after the access design is approved (T-630) | no cloud cost |

## Queue

Budget on the spot VM before G3: 60 to 90 GPU-hours for the six runs (TB-PLAN-06 §4). Dates are planned.

| # | Run | Machine | Card | Planned | Owner OK | Hours | Pre-emptions | Cost | Record path | State |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S1 | The short run (recorded opinions for the PoC) | Spot VM | T-004 | 2026-11-20 | | | | | | queued |
| S2a | G1 tier run, attempt 1 (about 9 h) | Spot VM | T-004 | 2026-11-24 | | | | | | queued |
| S2b | G1 tier run, attempt 2 (only if 1 fails) | Spot VM | T-004 | 2026-11-27 | | | | | | queued |
| S2c | G1 tier run, attempt 3 (only if 2 fails) | Spot VM | T-004 | 2026-12-01 | | | | | | queued |
| S3 | Profile cost test and embedding test | Spot VM | T-004 | 2026-12-02 | | | | | | queued |
| S4 | Judge bake-off with the challenger build | Spot VM | T-674 | 2026-12-15 | | | | | | queued |
| S5 | Prompt-injection and false-positive suite on the model pair | Spot VM | T-208 | 2026-12-17 | | | | | | queued |
| S6 | G1 re-run on the release | Spot VM | T-004 | 2027-03-01 | | | | | | queued |
| B1 | G1 functional run, 50k, the model pair, ja and zh-TW | Owner's B200 | T-004 | 2026-12-02 | | | | none | | queued |
| B2 | G1b qualification, two MIG layouts, host fingerprint | Owner's B200 | T-114 | 2026-12-11 | | | | none | | queued |
| B3 | GP-2: the PoC with the model pair (optional) | Owner's B200 | GP-2 | 2027-01-12 | | | | none | | queued |
| B4 | Acceptance drills | Owner's B200 | as TB-PLAN-05 | before G3 | | | | none | | queued |

## Totals

| Machine | Runs done | GPU-hours | Pre-emptions | Cost |
| --- | --- | --- | --- | --- |
| Spot VM | 0 | 0 | 0 | 0 |
| Owner's B200 | 0 | 0 | 0 | none |

## Rules

- One run at a time per machine. A run that waits says who it waits for in "State".
- A G1 attempt counts only on a commit that holds T-601 (TB-PLAN-06 §2.1).
- A pre-empted run resumes with `--resume`; each pre-emption is counted in its row.
- After a model or prompt change, the qualifying run is added here before it starts.
