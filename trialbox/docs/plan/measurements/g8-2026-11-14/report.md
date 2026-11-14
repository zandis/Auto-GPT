# TrialBox complete-platform run

Head `cb8504708a4f` (Lane G: results of run 20261113T231557Z-0e9be8a5 (G-5 and G-8) and the findings note). Run: 20261114T014216Z-cb850470-s1. Model: local/gemma-4-26b-a4b-nvfp4, local/qwen3.5-9b-awq (gateway (installed box, synthetic weight pins)). Hospital: 50,000 synthetic patients. Languages run: -. OCR: tesseract. Model calls in flight: 16. Host: x86_64, 48 CPUs.
Run started 2026-11-14T01:48:52+00:00, finished 2026-11-14T01:52:52+00:00 (the parts' own times); report built 2026-11-14T01:55:12+00:00.

**FAILED**: 2 of 3 checks passed (1 failed); 1 of 1 screenshots; 4.0 min of part time (each part's wall time, summed: parts on several VMs ran at the same time); 0 known findings reported.

Screenshots are in the run's `report/shots/` folder (not committed).

Door secret after the collect (T-119): door secret tb-gpu-door: enabled version(s) 2 remain (this run's not destroyed: none); destroy each with: gcloud secrets versions destroy <version> --secret tb-gpu-door --quiet

| part | stage | checks | result | seconds | screenshot |
| --- | --- | --- | --- | --- | --- |
| g8-protocols | G-8 public protocols compiled with the production judge | 2/3 | FAIL | 239.3 | `g8-protocols.png` |

## Scenarios


## Throughput (model calls through the gateway)

Calls and tokens per second are over the seconds in which a call was in flight (the gateway's audit); the servers' `/metrics` before and after, `gpu.csv` (every 10 s) and `vllm.csv` are in `parts/<part>/`. A hospital part has two rows: **main SCREEN** (the SCREEN job's own window: the throughput of the curve) and **whole part** (with the canary's one-at-a-time calls and stages 15 and 17). GPU % is `nvidia-smi` utilisation, the share of time a kernel ran: not a headroom measure (a card at 100 % may take more calls). KV peak: each server's KV-cache usage peak (vllm.csv). Not measured: the gateway's slot wait per call (the gateway does not record it).

| part | window | in flight | calls | calls/s | tokens/s | p50 s | p95 s | queue s (vLLM) | GPU % mean | GPU % max | KV peak | GPU MiB peak | breaker opened | listed | list sha256 | refused (of asked) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| g8-protocols | whole part | 16 | 33 | 0.14 | 134.333 | 0.394 | 27.26 | judge 0.0018 | 31.7 | 35.0 | judge 0.010323820743749157, verifier 0.0 | 62582.0 | 0 | - | `-` | 0 of 33 |

## Review tests G-4, G-5, G-7, G-8 (plan v7 §7.1)

### G-8 (g8-protocols)

| protocol | criteria | classes | needs_review | time_sensitive | extension, no warning | groups flattened |
| --- | --- | --- | --- | --- | --- | --- |
| NCT02629159 | 10 | {'structured': 1, 'note': 7, 'mixed': 1, 'human': 1} | 7 | 0 | 0 | 0 |
| NCT03887455 | error: KeyError: 'ValueSet VS_CDR_SCORE not defined for ruleset G8P2' | | | | | |


## Part times

| part | wall seconds |
| --- | --- |
| g8-protocols | 239.7 |

## Failed checks

Each detail is cut at 300 characters here (TB_REPORT_DETAIL_CHARS); the whole detail of each is in `failed-checks.json` beside this report (as the part recorded it).

- g8-protocols / G-8 public protocols compiled with the production judge: 2 protocol(s) compiled with the production judge: ["KeyError: 'ValueSet VS_CDR_SCORE not defined for ruleset G8P2'"]
