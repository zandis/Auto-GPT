<!-- written by deploy/gcp/results_report.py: do not edit by hand, run the reader again -->

# Cloud run results: 20261114T014216Z-cb850470

Synthetic data only. Written from the collected results folder by `deploy/gcp/results_report.py`.

- **Run id**: `20261114T014216Z-cb850470`
- **Commit**: `cb8504708a4fd739e93e82454da840722c442f6c`
- **Card**: not in the folder
- **Hours**: 0.2 h (VM hours given with --vm-hours); estimate 0.68 h; cap 1 h
- **Cost**: US$0.55 at US$2.74 an hour; estimate US$1.86; cap US$2.74
- **Parts**: 0 passed, 1 failed, 0 pending, 0 missing, of 1 planned
- **Verdict**: **FAILED**

## Parts

| part | status | checks passed | in flight | seconds | note |
| --- | --- | --- | --- | --- | --- |
| `g8-protocols` | FAILED | 2/3 | 16 | 239.7 | 1 failed check(s) |

A part with no result is PENDING (its VM still runs, or a half-written result is there) or MISSING. Neither counts as passed.

## G-1: chat template identity

- **Verdict: NOT PLANNED** (the plan has no chat-template part)

## G-3: throughput at each number of calls in flight

The plan has no hospital part: no curve.

## Defects

1 entry(ies) in `DEFECTS.md`.

Files: `capacity_inputs.json` (the figures T-667, T-637 and T-734 read), `DEFECTS.md`.
