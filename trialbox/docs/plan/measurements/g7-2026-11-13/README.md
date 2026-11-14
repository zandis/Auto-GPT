<!-- written by deploy/gcp/results_report.py: do not edit by hand, run the reader again -->

# Cloud run results: 20261113T081311Z-c25cea6b

Synthetic data only. Written from the collected results folder by `deploy/gcp/results_report.py`.

- **Run id**: `20261113T081311Z-c25cea6b`
- **Commit**: `c25cea6bc78e6182f39dd3d6a1b30132f760e7ce`
- **Card**: not in the folder
- **Hours**: 0.39 h (VM hours given with --vm-hours); estimate 0.62 h; cap 1 h
- **Cost**: US$1.07 at US$2.74 an hour; estimate US$1.69; cap US$2.74
- **Parts**: 1 passed, 1 failed, 0 pending, 0 missing, of 2 planned
- **Verdict**: **FAILED**

## Parts

| part | status | checks passed | in flight | seconds | note |
| --- | --- | --- | --- | --- | --- |
| `g4-decoding` | FAILED | 3/4 | 16 | 33.5 | 1 failed check(s) |
| `g7-clipped` | PASSED | 2/2 | 16 | 26.8 | - |

A part with no result is PENDING (its VM still runs, or a half-written result is there) or MISSING. Neither counts as passed.

## G-1: chat template identity

- **Verdict: NOT PLANNED** (the plan has no chat-template part)

## G-3: throughput at each number of calls in flight

The plan has no hospital part: no curve.

## Defects

1 entry(ies) in `DEFECTS.md`.

Files: `capacity_inputs.json` (the figures T-667, T-637 and T-734 read), `DEFECTS.md`.
