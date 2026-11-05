# Model card: qwen3.5-9b-rtx5090

Generated from `models/registry.yaml` by `python -m registry.cards --write`. Do not edit by hand.

| Field | Value |
| --- | --- |
| Alias | `v-verifier` |
| Model | Qwen3.5-9B (4-bit, RTX 5090 verifier) |
| Status | candidate |
| Serving | vllm |
| Weights SHA-256 | not yet pinned (null) |
| Revision | not yet pinned |
| Quantisation | 4-bit (NVFP4 or AWQ; recipe to record at qualification) |
| Context length | 8192 |
| Licence | Apache-2.0 (to confirm) (SPDX: Apache-2.0; verified: no) |
| Origin | Alibaba Qwen (CN); non-PRC: no |

## Contexts of use

None approved. A build is used only through a route in `models/routing.yaml` after G5 (§8.16).

## Evaluation

No evaluation report is recorded. Per-language results (en, zh-TW, ja, mixed) come from the suites (§8.9).
