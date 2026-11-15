> **SUPERSEDED on 2026-11-14: not evidence of the shipped product.** See `SUPERSEDED.md` and [the validation reset plan](../validation-reset-2026-11-14.md).

<!-- written by deploy/gcp/results_report.py: do not edit by hand, run the reader again -->

# Cloud run results: 20261113T085509Z-c25cea6b

Synthetic data only. Written from the collected results folder by `deploy/gcp/results_report.py`.

- **Run id**: `20261113T085509Z-c25cea6b`
- **Commit**: `c25cea6bc78e6182f39dd3d6a1b30132f760e7ce`
- **Card**: not in the folder
- **Hours**: 2.0 h (VM hours given with --vm-hours); estimate 7.22 h; cap 11 h
- **Cost**: US$5.48 at US$2.74 an hour; estimate US$19.78; cap US$30.14
- **Parts**: 2 passed, 4 failed, 0 pending, 0 missing, of 6 planned
- **Verdict**: **FAILED**

## Parts

| part | status | checks passed | in flight | seconds | note |
| --- | --- | --- | --- | --- | --- |
| `prepare` | PASSED | 2/2 | 16 | 16.4 | - |
| `hospital-ja` | FAILED | 227/228 | 16 | 2986.1 | 1 failed check(s) |
| `hospital-zh-TW` | FAILED | 227/228 | 16 | 2990.7 | 1 failed check(s) |
| `g5-tokens` | FAILED | 1/2 | 16 | 10.9 | 1 failed check(s) |
| `g4-decoding` | FAILED | 3/4 | 16 | 26.1 | 1 failed check(s) |
| `g7-clipped` | PASSED | 2/2 | 16 | 26.5 | - |

A part with no result is PENDING (its VM still runs, or a half-written result is there) or MISSING. Neither counts as passed.

## G-1: chat template identity

- **Verdict: NOT PLANNED** (the plan has no chat-template part)

## G-3: throughput at each number of calls in flight

### hospital-ja

| in flight | status | measured over | calls/s | tokens/s | p50 s | p95 s | GPU % mean | GPU MiB peak | GPU MiB total | breaker opened | listed | list sha256 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 16 | FAILED | main SCREEN | 4.447 | 5213.022 | 3.221 | 5.116 | 48.0 | 62968.0 | 97887.0 | 0 | 627 | `63f2c9f5e2c3` |

- Candidate list: **NOT JUDGED**, fewer than two settings have a candidate list.
- Chosen setting: **16** in flight (the highest calls/s among the settings with the reference list and no breaker opening).
- Night window: **NOT COMPUTED**. not given and not in the plan: studies (--studies), night hours (--night-hours)

### hospital-zh-TW

| in flight | status | measured over | calls/s | tokens/s | p50 s | p95 s | GPU % mean | GPU MiB peak | GPU MiB total | breaker opened | listed | list sha256 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 16 | FAILED | main SCREEN | 4.558 | 5325.943 | 3.187 | 5.013 | 46.9 | 62968.0 | 97887.0 | 0 | 628 | `e84d4223d34b` |

- Candidate list: **NOT JUDGED**, fewer than two settings have a candidate list.
- Chosen setting: **16** in flight (the highest calls/s among the settings with the reference list and no breaker opening).
- Night window: **NOT COMPUTED**. not given and not in the plan: studies (--studies), night hours (--night-hours)

## Defects

4 entry(ies) in `DEFECTS.md`.

Files: `capacity_inputs.json` (the figures T-667, T-637 and T-734 read), `DEFECTS.md`.
