# Model card: gemma-4-26b-a4b-it-spark

Generated from `models/registry.yaml` by `python -m registry.cards --write`. Do not edit by hand.

| Field | Value |
| --- | --- |
| Alias | `j-workhorse` |
| Model | Gemma 4 26B-A4B-it (NVFP4, Spark judge) |
| Status | candidate |
| Serving | vllm |
| Weights SHA-256 | not yet pinned (null) |
| Revision | not yet pinned |
| Quantisation | NVFP4 (NVIDIA release; measured 2026-11-08) |
| Context length | 16384 |
| Licence | Apache-2.0 (Gemma 4) (SPDX: Apache-2.0; verified: yes) |
| Origin | Google (US); non-PRC: yes |
| Source | `nvidia/Gemma-4-26B-A4B-NVFP4` at a19cfe00be84568a6867111c9a68c9c44fdcffe6 (publisher-quantisation) |
| Base model | `google/gemma-4-26B-A4B-it` at 4d7ae4984b7d |
| Licence file | none in the source repository (the licence register row holds the text) |
| Chat template | `google/gemma-4-26B-A4B-it` at 4d7ae4984b7d, `chat-templates/gemma-4-26b-a4b-it/chat_template.jinja` (recorded in the site pin) |

## Contexts of use

None approved. A build is used only through a route in `models/routing.yaml` after G5 (§8.16).

## Evaluation

No evaluation report is recorded. Per-language results (en, zh-TW, ja, mixed) come from the suites (§8.9).
