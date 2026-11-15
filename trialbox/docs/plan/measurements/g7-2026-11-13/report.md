# TrialBox complete-platform run

Head `c25cea6bc78e` (Lane G: every apt on the run VM waits for the dpkg lock, not only the script's own calls). Run: 20261113T081311Z-c25cea6b-s1. Model: local/gemma-4-26b-a4b-nvfp4, local/qwen3.5-9b-awq (gateway (installed box, synthetic weight pins)). Hospital: 50,000 synthetic patients. Languages run: -. OCR: tesseract. Model calls in flight: 16. Host: x86_64, 48 CPUs.
Run started 2026-11-13T08:19:57+00:00, finished 2026-11-13T08:20:59+00:00 (the parts' own times); report built 2026-11-13T08:36:31+00:00.

**FAILED**: 5 of 6 checks passed (1 failed); 2 of 2 screenshots; 1.0 min of part time (each part's wall time, summed: parts on several VMs ran at the same time); 0 known findings reported.

Screenshots are in the run's `report/shots/` folder (not committed).

Door secret after the collect (T-119): door secret tb-gpu-door: enabled version(s) 2 remain (this run's not destroyed: none); destroy each with: gcloud secrets versions destroy <version> --secret tb-gpu-door --quiet

| part | stage | checks | result | seconds | screenshot |
| --- | --- | --- | --- | --- | --- |
| g4-decoding | G-4 structured output: backend, guided decoding on and off, eager start | 3/4 | FAIL | 31.5 | `g4-decoding.png` |
| g7-clipped | G-7 clipped against whole note (LLM-001) | 2/2 | pass | 26.3 | `g7-clipped.png` |

## Scenarios


## Throughput (model calls through the gateway)

Calls and tokens per second are over the seconds in which a call was in flight (the gateway's audit); the servers' `/metrics` before and after, `gpu.csv` (every 10 s) and `vllm.csv` are in `parts/<part>/`. A hospital part has two rows: **main SCREEN** (the SCREEN job's own window: the throughput of the curve) and **whole part** (with the canary's one-at-a-time calls and stages 15 and 17). GPU % is `nvidia-smi` utilisation, the share of time a kernel ran: not a headroom measure (a card at 100 % may take more calls). KV peak: each server's KV-cache usage peak (vllm.csv). Not measured: the gateway's slot wait per call (the gateway does not record it).

| part | window | in flight | calls | calls/s | tokens/s | p50 s | p95 s | queue s (vLLM) | GPU % mean | GPU % max | KV peak | GPU MiB peak | breaker opened | listed | list sha256 | refused (of asked) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| g4-decoding | whole part | 16 | 0 | - | - | - | - | judge 0.1584 | 25.8 | 48.0 | judge 0.02529801119188979, verifier 0.0 | 62582.0 | - | - | `-` | - |
| g7-clipped | whole part | 16 | 14 | 0.548 | 1346.252 | 1.617 | 2.801 | judge 0.0013, verifier 0.2038 | 28.0 | 40.0 | judge 0.006681031141975824, verifier 0.009345794392523366 | 62590.0 | 0 | - | `-` | 0 of 14 |

## Review tests G-4, G-5, G-7, G-8 (plan v7 §7.1)

### G-4 (g4-decoding)

Structured-output backend: **auto** (the serving record (the container's command line)). Eager start: needs a restart: not run (--enforce-eager is a start flag; the part never restarts a server) (record: enforce_eager True).

| setting | calls | answered | calls/s | p50 s | p95 s | schema failures |
| --- | --- | --- | --- | --- | --- | --- |
| guided on | 64 | 64 | 3.576 | 2.2844 | 9.3712 | 1 |
| guided off | 64 | 64 | 4.732 | 1.657 | 3.844 | 64 |

Profile: guided decoding on (16 in flight, 64 prompts each way).

guided on: answers outside the schema by finish_reason: stop 1; the first 1 (finish_reason, completion tokens, the first 200 characters):

- stop, 71 tokens: `"{\n \"verdict\": \"unknown\",\n \"reason\": \"The provided excerpt does not mention gout or any gout flares; it only discusses stomach discomfort and dietary advice.\",\n \"quote\": \"unknown\",\n \"quote_date\": \"0000"`

guided off: answers outside the schema by finish_reason: stop 64; the first 5 (finish_reason, completion tokens, the first 200 characters):

- stop, 64 tokens: `"\u0060\u0060\u0060json\n{\n \"answer\": \"fail\",\n \"quote_date\": \"2026-06-01\",\n \"quote\": \"過去一年間に痛風発作はなく、関節の発赤・腫脹もない。\",\n \"confidence\": 1.0\n}\n\u0060\u0060\u0060"`
- stop, 38 tokens: `"\u0060\u0060\u0060json\n{\n \"answer\": \"unknown\",\n \"quote\": null,\n \"quote_date\": null,\n \"confidence\": 1.0\n}\n\u0060\u0060\u0060"`
- stop, 76 tokens: `"\u0060\u0060\u0060json\n{\n \"answer\": \"unknown\",\n \"quote\": \"現在、右第一中足趾節関節に急性の発赤・腫脹・疼痛あり、急性痛風発作中である。\",\n \"quote_date\": \"2026-06-03\",\n \"confidence\": 1.0\n}\n\u0060\u0060\u0060"`
- stop, 87 tokens: `"\u0060\u0060\u0060json\n{\n \"answer\": \"unknown\",\n \"quote_date\": \"2026-06-04\",\n \"quote\": \"2025年12月1日に右足関節の発赤・腫脹・熱感・疼痛あり、急性痛風発作と診断しコルヒチンで改善した。\",\n \"confidence\": 0.8\n}\n\u0060\u0060\u0060"`
- stop, 203 tokens: `"\u0060\u0060\u0060json\n{\n \"answer\": \"pass\",\n \"quote_date\": \"2026-06-05\",\n \"quote\": \"令和8年2月3日に左膝関節の発赤・腫脹・熱感・疼痛あり、急性痛風発作と診断しコルヒチンで改善した。\",\n \"confidence\": 1.0\n}\n\u0060\u0060\u0060\n\n**Note on reasoning:**\nThe note dated 2026-06-05 desc"`

### G-7 (g7-clipped)

| case | clipped | left out | view | judge | verifier | pair | final |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LLM-001-ja-family-history | True | 1 | clipped | unknown | unknown | unknown | review |
| LLM-001-ja-family-history | True | 0 | whole | unknown | unknown | unknown | review |
| LLM-001-zh-TW-denied-list | True | 1 | clipped | fail | fail | fail | met |
| LLM-001-zh-TW-denied-list | True | 0 | whole | fail | fail | fail | met |

Final not met from a clipped note: **none**.


## Part times

| part | wall seconds |
| --- | --- |
| g4-decoding | 33.5 |
| g7-clipped | 26.8 |

## Failed checks

Each detail is cut at 300 characters here (TB_REPORT_DETAIL_CHARS); the whole detail of each is in `failed-checks.json` beside this report (as the part recorded it).

- g4-decoding / G-4 structured output: backend, guided decoding on and off, eager start: guided on: no answer outside the judge schema: 1
