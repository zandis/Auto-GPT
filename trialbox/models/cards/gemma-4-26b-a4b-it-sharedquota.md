# Model card: gemma-4-26b-a4b-it-sharedquota

Generated from `models/registry.yaml` by `python -m registry.cards --write`. Do not edit by hand.

| Field | Value |
| --- | --- |
| Alias | `j-workhorse` |
| Model | Gemma 4 26B-A4B-it (NVFP4, shared-quota judge on its MIG instance) |
| Status | candidate |
| Serving | vllm |
| Weights SHA-256 | not yet pinned (null) |
| Revision | not yet pinned |
| Quantisation | NVFP4 (NVIDIA release; the same weights as the measured pair; NVFP4 under MIG unproven, RSK-43) |
| Context length | to record at qualification |
| Licence | Apache-2.0 (Gemma 4) (SPDX: Apache-2.0; verified: yes) |
| Origin | Google (US); non-PRC: yes |
| Source | `nvidia/Gemma-4-26B-A4B-NVFP4` at a19cfe00be84568a6867111c9a68c9c44fdcffe6 (publisher-quantisation) |
| Base model | `google/gemma-4-26B-A4B-it` at 4d7ae4984b7db7de8f8457170b3f1a419ee76d52 |
| Licence file | none in the source repository (the licence register row holds the text) |
| Chat template | `google/gemma-4-26B-A4B-it` at 4d7ae4984b7db7de8f8457170b3f1a419ee76d52, `chat-templates/gemma-4-26b-a4b-it/chat_template.jinja` (ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4) |

## Contexts of use

None approved. A build is used only through a route in `models/routing.yaml` after G5 (§8.16).

## Evaluation

No evaluation report is recorded. Per-language results (en, zh-TW, ja, mixed) come from the suites (§8.9).
