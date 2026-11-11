# Model card: gemma-4-31b-it-qat-challenger

Generated from `models/registry.yaml` by `python -m registry.cards --write`. Do not edit by hand.

| Field | Value |
| --- | --- |
| Alias | `j-workhorse` |
| Model | Gemma 4 31B-it (QAT w4a16, judge challenger) |
| Status | candidate |
| Serving | vllm |
| Weights SHA-256 | not yet pinned (null) |
| Revision | not yet pinned |
| Quantisation | w4a16 QAT, compressed-tensors (Google release) |
| Context length | 32768 |
| Licence | Apache-2.0 (Gemma 4; to confirm at download) (SPDX: Apache-2.0; verified: no) |
| Origin | Google (US); non-PRC: yes |
| Source | `google/gemma-4-31B-it-qat-w4a16-ct` at revision not yet read (publisher-quantisation) |
| Licence file | to record at download |
| Bake-off | judge challenger: queued (GPU ledger row S4) |

## Contexts of use

None approved. A build is used only through a route in `models/routing.yaml` after G5 (§8.16).

## Evaluation

No evaluation report is recorded. Per-language results (en, zh-TW, ja, mixed) come from the suites (§8.9).
