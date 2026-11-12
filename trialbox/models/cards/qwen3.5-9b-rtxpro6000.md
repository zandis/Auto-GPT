# Model card: qwen3.5-9b-rtxpro6000

Generated from `models/registry.yaml` by `python -m registry.cards --write`. Do not edit by hand.

| Field | Value |
| --- | --- |
| Alias | `v-verifier` |
| Model | Qwen3.5-9B (AWQ 4-bit, RTX PRO 6000 verifier) |
| Status | candidate |
| Serving | vllm |
| Weights SHA-256 | not yet pinned (null) |
| Revision | not yet pinned |
| Quantisation | AWQ 4-bit (measured 2026-11-08) |
| Context length | 32768 |
| Licence | Apache-2.0 (SPDX: Apache-2.0; verified: yes) |
| Origin | Alibaba Qwen (CN); non-PRC: no |
| Source | `cyankiwi/Qwen3.5-9B-AWQ-4bit` at e4d2d39cede8c5d1716d824cd843e2889c648083 (own-copy, the default until the owner answers) |
| Base model | `Qwen/Qwen3.5-9B` at c20223623576 |
| Licence file | `LICENSE` sha256 bbedc3fda3305820b977265f01b8619d87570a6739de3a5582c3464840f1e57a |

## Contexts of use

None approved. A build is used only through a route in `models/routing.yaml` after G5 (§8.16).

## Evaluation

No evaluation report is recorded. Per-language results (en, zh-TW, ja, mixed) come from the suites (§8.9).
