<!-- written by deploy/gcp/results_report.py: do not edit by hand, run the reader again -->

# Cloud run results: 20261113T231557Z-0e9be8a5

Synthetic data only. Written from the collected results folder by `deploy/gcp/results_report.py`.

- **Run id**: `20261113T231557Z-0e9be8a5`
- **Commit**: `0e9be8a5f27c7a512a68e4fd270c779e80682a15`
- **Card**: not in the folder
- **Hours**: 0.8 h (VM hours given with --vm-hours); estimate 1.54 h; cap 3 h
- **Cost**: US$2.19 at US$2.74 an hour; estimate US$4.22; cap US$8.22
- **Parts**: 1 passed, 1 failed, 0 pending, 0 missing, of 2 planned
- **Verdict**: **FAILED**

## Parts

| part | status | checks passed | in flight | seconds | note |
| --- | --- | --- | --- | --- | --- |
| `g5-tokens` | PASSED | 2/2 | 16 | 17.3 | - |
| `g8-protocols` | FAILED | 0/3 | 16 | 2.1 | 3 failed check(s) |

A part with no result is PENDING (its VM still runs, or a half-written result is there) or MISSING. Neither counts as passed.

## G-1: chat template identity

- **Verdict: NOT PLANNED** (the plan has no chat-template part)

## G-3: throughput at each number of calls in flight

The plan has no hospital part: no curve.

## Defects

3 entry(ies) in `DEFECTS.md`.

Files: `capacity_inputs.json` (the figures T-667, T-637 and T-734 read), `DEFECTS.md`.
