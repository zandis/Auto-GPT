# RTX PRO 6000 profile run, 2026-11-08 (TB-PLAN-04 step 1, D-124)

`tb-gpu-sim` (g4-standard-48 spot, one RTX PRO 6000 Blackwell Server Edition, 97,887 MiB), uncapped, started with
`deploy/gcp/gpu-pro6000-run.sh`: judge Gemma 4 26B-A4B NVFP4 and verifier Qwen3.5-9B AWQ, both resident, 32k
context, 16 sequences, 0.40 + 0.20 of the card, vLLM 0.32.0. VM up 13:32–14:05 UTC (about US$1.50), then stopped
(TERMINATED) and its usual startup script put back.

| check | result | file |
| --- | --- | --- |
| serving record, `measured rtxpro6000` | pass; weight hashes equal the 8 Nov run | `deploy/measured/serving_config.rtxpro6000.json` |
| card memory, both loaded and under load | 62,588 MiB of 97,887 (peak) | `gpu_peak.json` |
| KV cache | judge 19.7 GiB (326,778 tokens, 9.97 × 32k); verifier 10.4 GiB (305,359 tokens, 9.32 × 32k) | serial log |
| pair canary (54 cases, en/ja/zh-TW) | pass: judge 54/54, verifier 49/54, pair 53 correct, **0 wrong exclusions**, 1 disagreement | `canary_pair.json` |
| `public_e2e --lang en` with both models | **98/98** in 1,303 s; PUB-ONC screen 563 s; 7 disagreements and 1 model failure went to review, none excluded | `public_e2e_result.json`, `public_e2e_stages.md` |

The judge did better than on the capped card (54/54 against 53/54 on 8 Nov). The verifier's five misses are
"fail" where the answer is "unknown" or "pass"; the pair rule turns each into a disagreement, never an exclusion.
