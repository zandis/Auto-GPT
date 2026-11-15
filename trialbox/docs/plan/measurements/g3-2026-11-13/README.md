<!-- written by deploy/gcp/results_report.py: do not edit by hand, run the reader again -->

# Cloud run results: 20261113T044219Z-2b9eec74

Synthetic data only. Written from the collected results folder by `deploy/gcp/results_report.py`.

- **Run id**: `20261113T044219Z-2b9eec74`
- **Commit**: `2b9eec74ab556b44464b2e83536c720a8a7357a6`
- **Card**: not in the folder
- **Hours**: 1.99 h (VM hours given with --vm-hours); estimate 3.27 h; cap 5 h
- **Cost**: US$5.45 at US$2.74 an hour; estimate US$8.95; cap US$13.70
- **Parts**: 1 passed, 9 failed, 0 pending, 0 missing, of 10 planned
- **Verdict**: **FAILED**

## Parts

| part | status | checks passed | in flight | seconds | note |
| --- | --- | --- | --- | --- | --- |
| `prepare` | PASSED | 2/2 | 1 | 3.0 | - |
| `hospital-ja@c1` | FAILED | 224/225 | 1 | 1685.5 | 1 failed check(s) |
| `hospital-zh-TW@c1` | FAILED | 224/225 | 1 | 1655.8 | 1 failed check(s) |
| `hospital-ja@c4` | FAILED | 224/225 | 4 | 734.1 | 1 failed check(s) |
| `hospital-zh-TW@c4` | FAILED | 224/225 | 4 | 791.5 | 1 failed check(s) |
| `g5-tokens` | FAILED | 1/2 | 1 | 10.8 | 1 failed check(s) |
| `hospital-ja@c16` | FAILED | 224/225 | 16 | 501.5 | 1 failed check(s) |
| `hospital-zh-TW@c16` | FAILED | 224/225 | 16 | 507.9 | 1 failed check(s) |
| `g4-decoding` | FAILED | 3/4 | 1 | 62.5 | 1 failed check(s) |
| `g7-clipped` | FAILED | 1/2 | 1 | 24.8 | 1 failed check(s) |

A part with no result is PENDING (its VM still runs, or a half-written result is there) or MISSING. Neither counts as passed.

## G-1: chat template identity

- **Verdict: NOT PLANNED** (the plan has no chat-template part)

## G-3: throughput at each number of calls in flight

### hospital-ja

| in flight | status | measured over | calls/s | tokens/s | p50 s | p95 s | GPU % mean | GPU MiB peak | GPU MiB total | breaker opened | listed | list sha256 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | FAILED | main SCREEN | 0.385 | 402.705 | 2.353 | 4.086 | 32.6 | 62590.0 | 97887.0 | 0 | 55 | `6e78c71cd0bf` |
| 4 | FAILED | main SCREEN | 1.435 | 1492.028 | 2.424 | 4.193 | 47.8 | 62592.0 | 97887.0 | 0 | 55 | `72d3513176a1` |
| 16 | FAILED | main SCREEN | 4.391 | 4580.144 | 2.845 | 5.413 | 32.7 | 62592.0 | 97887.0 | 0 | 55 | `6e78c71cd0bf` |

- **FAIL: the candidate list at 4 in flight differs from the list at 1, 16.** The list must not depend on the calls in flight.
- Chosen setting: **16** in flight (the highest calls/s among the settings with the reference list and no breaker opening).
- Night window: **PASS: meets the window.** Measured 4.391 calls/s; needed 0.061 calls/s.
- How the need is computed: 5,000 patients x 5 studies x 0.0492 calls per patient and study / (8.0 h x 3600 x 0.7). Calls per patient and study: measured: 246 calls for 5,000 patients in `hospital-ja@c16`, taken as one study.

### hospital-zh-TW

| in flight | status | measured over | calls/s | tokens/s | p50 s | p95 s | GPU % mean | GPU MiB peak | GPU MiB total | breaker opened | listed | list sha256 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | FAILED | main SCREEN | 0.388 | 402.122 | 2.36 | 4.109 | 31.0 | 62592.0 | 97887.0 | 0 | 55 | `72d3513176a1` |
| 4 | FAILED | main SCREEN | 1.432 | 1499.917 | 2.511 | 4.281 | 46.7 | 62592.0 | 97887.0 | 0 | 55 | `6e78c71cd0bf` |
| 16 | FAILED | main SCREEN | 4.613 | 4785.824 | 2.741 | 4.652 | 34.1 | 62592.0 | 97887.0 | 0 | 55 | `72d3513176a1` |

- **FAIL: the candidate list at 4 in flight differs from the list at 1, 16.** The list must not depend on the calls in flight.
- Chosen setting: **16** in flight (the highest calls/s among the settings with the reference list and no breaker opening).
- Night window: **PASS: meets the window.** Measured 4.613 calls/s; needed 0.061 calls/s.
- How the need is computed: 5,000 patients x 5 studies x 0.0488 calls per patient and study / (8.0 h x 3600 x 0.7). Calls per patient and study: measured: 244 calls for 5,000 patients in `hospital-zh-TW@c16`, taken as one study.

## Defects

11 entry(ies) in `DEFECTS.md`.

Files: `capacity_inputs.json` (the figures T-667, T-637 and T-734 read), `DEFECTS.md`.
