# Model card: ministral-3-14b-verifier-candidate

Generated from `models/registry.yaml` by `python -m registry.cards --write`. Do not edit by hand.

| Field | Value |
| --- | --- |
| Alias | `v-verifier` |
| Model | Ministral 3 14B Instruct 2512 (second verifier candidate) |
| Status | candidate |
| Serving | vllm |
| Weights SHA-256 | not yet pinned (null) |
| Revision | not yet pinned |
| Quantisation | 4-bit own build (recipe to commit with the build) |
| Context length | 32768 |
| Licence | Apache-2.0 (to confirm) (SPDX: Apache-2.0; verified: no) |
| Origin | Mistral AI (FR); non-PRC: yes |
| Source | `mistralai/Ministral-3-14B-Instruct-2512` at 29439f81c2be (own-quantisation) |
| Licence file | to record at download |
| Bake-off | second verifier candidate: unmeasured (not in the GPU ledger) |

## Contexts of use

None approved. A build is used only through a route in `models/routing.yaml` after G5 (§8.16).

## Evaluation

No evaluation report is recorded. Per-language results (en, zh-TW, ja, mixed) come from the suites (§8.9).
