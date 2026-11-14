# TrialBox complete-platform run

Head `0e9be8a5f27c` (Lane G: G-5 measures the product's current token estimate (D-645)). Run: 20261113T231557Z-0e9be8a5-s1. Model: local/gemma-4-26b-a4b-nvfp4, local/qwen3.5-9b-awq (gateway (installed box, synthetic weight pins)). Hospital: 50,000 synthetic patients. Languages run: -. OCR: tesseract. Model calls in flight: 16. Host: x86_64, 48 CPUs.
Run started 2026-11-13T23:22:30+00:00, finished 2026-11-13T23:22:52+00:00 (the parts' own times); report built 2026-11-14T00:06:30+00:00.

**FAILED**: 2 of 5 checks passed (3 failed); 2 of 2 screenshots; 0.3 min of part time (each part's wall time, summed: parts on several VMs ran at the same time); 0 known findings reported.

Screenshots are in the run's `report/shots/` folder (not committed).

Door secret after the collect (T-119): door secret tb-gpu-door: enabled version(s) 2 remain (this run's not destroyed: none); destroy each with: gcloud secrets versions destroy <version> --secret tb-gpu-door --quiet

| part | stage | checks | result | seconds | screenshot |
| --- | --- | --- | --- | --- | --- |
| g5-tokens | G-5 token counts: /tokenize against the product's estimates | 2/2 | pass | 16.2 | `g5-tokens.png` |
| g8-protocols | G-8 public protocols compiled with the production judge | 0/3 | FAIL | 1.8 | `g8-protocols.png` |

## Scenarios


## Throughput (model calls through the gateway)

Calls and tokens per second are over the seconds in which a call was in flight (the gateway's audit); the servers' `/metrics` before and after, `gpu.csv` (every 10 s) and `vllm.csv` are in `parts/<part>/`. A hospital part has two rows: **main SCREEN** (the SCREEN job's own window: the throughput of the curve) and **whole part** (with the canary's one-at-a-time calls and stages 15 and 17). GPU % is `nvidia-smi` utilisation, the share of time a kernel ran: not a headroom measure (a card at 100 % may take more calls). KV peak: each server's KV-cache usage peak (vllm.csv). Not measured: the gateway's slot wait per call (the gateway does not record it).

| part | window | in flight | calls | calls/s | tokens/s | p50 s | p95 s | queue s (vLLM) | GPU % mean | GPU % max | KV peak | GPU MiB peak | breaker opened | listed | list sha256 | refused (of asked) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| g5-tokens | whole part | 16 | 0 | - | - | - | - | - | 0.0 | 0.0 | judge 0.0, verifier 0.0 | 62576.0 | - | - | `-` | - |
| g8-protocols | whole part | 16 | 0 | - | - | - | - | - | 0.0 | 0.0 | judge 0.0, verifier 0.0 | 62576.0 | - | - | `-` | 2 of 2 (role_not_allowed 2) |

## Review tests G-4, G-5, G-7, G-8 (plan v7 §7.1)

### G-5 (g5-tokens)

| language | estimator | n | p50 | p95 | max |
| --- | --- | --- | --- | --- | --- |
| ja | budget | 200 | 0.7273 | 0.8 | 0.9143 |
| ja | cascade | 200 | 0.7273 | 0.8 | 0.9143 |
| ja | prompt | 200 | 0.9018 | 0.9622 | 0.9743 |
| zh-TW | budget | 200 | 0.8317 | 0.8972 | 0.9355 |
| zh-TW | cascade | 200 | 0.8317 | 0.8972 | 0.9355 |
| zh-TW | prompt | 200 | 0.9392 | 0.9707 | 0.9792 |
| en | budget | 200 | 0.8429 | 0.9208 | 0.9888 |
| en | cascade | 200 | 0.8429 | 0.9208 | 0.9888 |
| en | prompt | 200 | 0.9494 | 0.9716 | 0.9819 |

Largest ratio 0.9888 x 1.05 against 1 / SAFETY = 1.1765: **fits**; SAFETY from this measurement: 0.85.

### G-8 (g8-protocols)

| protocol | criteria | classes | needs_review | time_sensitive | extension, no warning | groups flattened |
| --- | --- | --- | --- | --- | --- | --- |
| NCT02629159 | error: CompileFailed: ir_extract: the model did not return usable criteria (gateway ref | | | | | |
| NCT03887455 | error: CompileFailed: ir_extract: the model did not return usable criteria (gateway ref | | | | | |


## Part times

| part | wall seconds |
| --- | --- |
| g5-tokens | 17.3 |
| g8-protocols | 2.1 |

## Failed checks

Each detail is cut at 300 characters here (TB_REPORT_DETAIL_CHARS); the whole detail of each is in `failed-checks.json` beside this report (as the part recorded it).

- g8-protocols / G-8 public protocols compiled with the production judge: 2 protocol(s) compiled with the production judge: ['CompileFailed: ir_extract: the model did not return usable criteria (gateway refused ir_extract: role_not_allowed); send the protocol again', 'CompileFailed: ir_extract: the model did not return usable criteria (gateway refused ir_extract: role_not_allowed); send the protocol again']
- g8-protocols / G-8 public protocols compiled with the production judge: no extension-phase line active without a warning: {}
- g8-protocols / G-8 public protocols compiled with the production judge: alternative diagnosis groups not flattened to AND: {}
