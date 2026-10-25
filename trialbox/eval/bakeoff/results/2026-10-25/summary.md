# Bake-off results 2026-10-25

First real-model run of TrialBox (S1-14): open D0 data only (NCBI TrialGPT-Criterion-Annotations, SIGIR, 1,015 physician-labelled criterion pairs, with TrialBox zh-TW / ja / mixed renderings of the notes), hosted models via OpenRouter, every call through tb-gateway (DEV, topology A, bakeoff route for judge_ml; dev-public route for the cascade). Each hosted build is provider-pinned (tools/pin_provider.py; dated canonical slug + provider endpoint, sha256 over the descriptor); the gateway asked for that provider only (no fallback, require_parameters, data_collection deny) and refused any response reporting another model or provider. Sampling is forced by the gateway: temperature 0, top_p 1, seed 20261025; one seed per item (the weights file's three seeds were not run). Request: tools/mlbench.messages (prompt mlbench_judge@1), json_schema response with evidence capped at 12 ids (tools/bakeoff_live.bounded_schema), max_tokens 2048, OpenRouter reasoning effort low for the reasoning models (Qwen3.6, gpt-oss, Nemotron). Costs are OpenRouter's reported usage.cost per call. GPT-4.1 is a closed GPT-4-class reference only; the 'recorded GPT-4' column is the label NCBI stored from the TrialGPT paper run (GPT-4, TrialGPT's own prompt). Rows '__trialgpt' use TrialGPT-Matching's criterion wording (tools/bakeoff_live.trialgpt_messages) on a seeded 100-pair subset, to show that the 4-way gap to the recorded GPT-4 labels is the 'absent is not negative' convention of the TrialBox prompt. Rows 'agree:' apply the two-model rule (gpt-oss-120b judge, Gemma 4 verifier; block only if both block) to the recorded answers. GPT-4.1 non-English rows are a seeded 200-item subset (all 33 physician blocks included, so screening accuracy there is not comparable with the full sets). Cascade rows ran with --no-repro.

## judge_ml through the gateway `bakeoff` route

Accuracy is exact 4-way agreement with the physician label (NCBI TrialGPT-Criterion-Annotations, SIGIR). False block: the model blocks a patient (`not included` / `excluded`) where the physician does not; in brackets the one-sided 95% upper bound. An invalid answer counts as `not enough information`. Screen: agreement on block vs open (the decision the cascade acts on). Refused: gateway refusals / model refusals.

| Build | Lang | n | Accuracy | Screen | Agree GPT-4 | False block (UB95) | Block recall | Invalid | Refused | p50 / p95 s | Cost | Per 1k |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| or-gemma-4-26b-a4b | en | 1015 | 0.635 | 0.960 | 0.583 | 0.024 (0.034) | 0.485 | 0.009 | 0/0 | 0.7 / 1.5 | $0.048 | $0.05 |
| or-gemma-4-26b-a4b | ja | 1015 | 0.602 | 0.958 | 0.553 | 0.026 (0.036) | 0.485 | 0.007 | 40/0 | 0.7 / 1.6 | $0.048 | $0.05 |
| or-gemma-4-26b-a4b | mixed | 1015 | 0.631 | 0.961 | 0.585 | 0.022 (0.032) | 0.455 | 0.008 | 11/0 | 0.6 / 1.3 | $0.047 | $0.05 |
| or-gemma-4-26b-a4b | zh-TW | 1015 | 0.622 | 0.957 | 0.570 | 0.024 (0.034) | 0.394 | 0.009 | 52/0 | 0.7 / 1.6 | $0.048 | $0.05 |
| or-gemma-4-26b-a4b__trialgpt | en | 100 | 0.690 | 0.860 | 0.580 | 0.030 (0.091) | 0.636 | 0.000 | 0/0 | 2.0 / 3.2 | $0.008 | $0.08 |
| or-gpt-4.1-reference | en | 1015 | 0.499 | 0.967 | 0.466 | 0.017 (0.026) | 0.485 | 0.008 | 0/0 | 1.1 / 1.5 | $1.284 | $1.26 |
| or-gpt-4.1-reference | ja | 200 | 0.495 | 0.895 | 0.440 | 0.024 (0.054) | 0.485 | 0.025 | 6/0 | 1.1 / 1.6 | $0.325 | $1.63 |
| or-gpt-4.1-reference | mixed | 200 | 0.490 | 0.895 | 0.460 | 0.018 (0.046) | 0.455 | 0.020 | 1/0 | 1.1 / 1.9 | $0.292 | $1.46 |
| or-gpt-4.1-reference | zh-TW | 200 | 0.490 | 0.885 | 0.445 | 0.012 (0.037) | 0.364 | 0.020 | 11/0 | 1.1 / 1.6 | $0.295 | $1.47 |
| or-gpt-4.1-reference__trialgpt | en | 100 | 0.690 | 0.830 | 0.660 | 0.119 (0.205) | 0.727 | 0.000 | 0/0 | 1.4 / 1.9 | $0.197 | $1.97 |
| or-gpt-oss-120b | en | 1015 | 0.509 | 0.969 | 0.475 | 0.017 (0.026) | 0.545 | 0.006 | 0/0 | 1.6 / 3.4 | $0.036 | $0.04 |
| or-gpt-oss-120b | ja | 1015 | 0.469 | 0.966 | 0.429 | 0.019 (0.028) | 0.515 | 0.010 | 40/0 | 1.8 / 4.1 | $0.039 | $0.04 |
| or-gpt-oss-120b | mixed | 1015 | 0.494 | 0.960 | 0.461 | 0.025 (0.035) | 0.515 | 0.004 | 11/0 | 2.0 / 3.8 | $0.036 | $0.04 |
| or-gpt-oss-120b | zh-TW | 1015 | 0.492 | 0.958 | 0.447 | 0.024 (0.034) | 0.424 | 0.002 | 52/0 | 1.5 / 3.2 | $0.035 | $0.03 |
| or-gpt-oss-120b__trialgpt | en | 100 | 0.670 | 0.890 | 0.710 | 0.000 (0.044) | 0.667 | 0.000 | 0/0 | 6.6 / 11.9 | $0.005 | $0.05 |
| or-nemotron-3-nano-30b-a3b | en | 1015 | 0.489 | 0.967 | 0.456 | 0.018 (0.027) | 0.515 | 0.014 | 0/0 | 3.8 / 12.4 | $0.121 | $0.12 |
| or-nemotron-3-nano-30b-a3b | ja | 1015 | 0.471 | 0.964 | 0.434 | 0.020 (0.029) | 0.485 | 0.009 | 40/0 | 3.8 / 10.0 | $0.143 | $0.14 |
| or-nemotron-3-nano-30b-a3b | mixed | 1015 | 0.490 | 0.966 | 0.462 | 0.019 (0.028) | 0.515 | 0.004 | 11/0 | 4.5 / 12.4 | $0.123 | $0.12 |
| or-nemotron-3-nano-30b-a3b | zh-TW | 1015 | 0.469 | 0.961 | 0.431 | 0.021 (0.031) | 0.424 | 0.009 | 52/0 | 3.7 / 9.7 | $0.130 | $0.13 |
| or-nemotron-3-nano-30b-a3b__trialgpt | en | 100 | 0.710 | 0.850 | 0.680 | 0.119 (0.205) | 0.788 | 0.000 | 0/0 | 5.5 / 10.7 | $0.020 | $0.20 |
| or-qwen3.6-35b-a3b | en | 1015 | 0.537 | 0.955 | 0.494 | 0.035 (0.046) | 0.636 | 0.002 | 0/0 | 5.8 / 9.2 | $1.001 | $0.99 |
| or-qwen3.6-35b-a3b | ja | 1015 | 0.523 | 0.955 | 0.475 | 0.035 (0.046) | 0.636 | 0.003 | 40/0 | 7.5 / 15.1 | $1.102 | $1.09 |
| or-qwen3.6-35b-a3b | mixed | 1015 | 0.548 | 0.953 | 0.505 | 0.036 (0.047) | 0.606 | 0.002 | 11/0 | 7.0 / 9.5 | $1.072 | $1.06 |
| or-qwen3.6-35b-a3b | zh-TW | 1015 | 0.533 | 0.957 | 0.481 | 0.030 (0.041) | 0.576 | 0.003 | 52/0 | 9.0 / 11.9 | $1.064 | $1.05 |
| or-qwen3.6-35b-a3b__trialgpt | en | 100 | 0.780 | 0.900 | 0.680 | 0.090 (0.169) | 0.879 | 0.010 | 0/0 | 7.2 / 8.8 | $0.131 | $1.31 |
| agree:or-gpt-oss-120b+or-gemma-4-26b-a4b | en | 1015 | 0.511 | 0.974 | 0.477 | 0.009 (0.016) | 0.485 | 0.006 | 0/0 | 1.6 / 3.4 | $0.038 | $0.04 |
| agree:or-gpt-oss-120b+or-gemma-4-26b-a4b | ja | 1015 | 0.471 | 0.971 | 0.430 | 0.011 (0.018) | 0.455 | 0.010 | 40/0 | 1.8 / 4.2 | $0.041 | $0.04 |
| agree:or-gpt-oss-120b+or-gemma-4-26b-a4b | mixed | 1015 | 0.499 | 0.969 | 0.465 | 0.013 (0.021) | 0.424 | 0.004 | 11/0 | 2.0 / 3.9 | $0.038 | $0.04 |
| agree:or-gpt-oss-120b+or-gemma-4-26b-a4b | zh-TW | 1015 | 0.494 | 0.970 | 0.450 | 0.010 (0.017) | 0.364 | 0.002 | 52/0 | 1.5 / 3.4 | $0.038 | $0.04 |

Recorded GPT-4 labels (TrialGPT paper run) on the same items:

| Items | Accuracy | Screen | False block (UB95) | Block recall |
| --- | --- | --- | --- | --- |
| en, n=100 | 0.810 | 0.940 | 0.015 (0.069) | 0.849 |
| en, n=1015 | 0.873 | 0.981 | 0.014 (0.022) | 0.849 |
| ja, n=200 | 0.825 | 0.965 | 0.012 (0.037) | 0.849 |
| ja, n=1015 | 0.873 | 0.981 | 0.014 (0.022) | 0.849 |
| mixed, n=200 | 0.825 | 0.965 | 0.012 (0.037) | 0.849 |
| mixed, n=1015 | 0.873 | 0.981 | 0.014 (0.022) | 0.849 |
| zh-TW, n=200 | 0.825 | 0.965 | 0.012 (0.037) | 0.849 |
| zh-TW, n=1015 | 0.873 | 0.981 | 0.014 (0.022) | 0.849 |

## Pins (provider descriptors, sha256)

| Build | Model | Dated version | Provider | sha256 |
| --- | --- | --- | --- | --- |
| or-gemma-4-26b-a4b | google/gemma-4-26b-a4b-it | google/gemma-4-26b-a4b-it-20260403 (created 1775227989) | deepinfra/fp8 | `6679993249ff3bcb…` |
| or-gemma-4-26b-a4b | google/gemma-4-26b-a4b-it | google/gemma-4-26b-a4b-it-20260403 (created 1775227989) | deepinfra/fp8 | `6679993249ff3bcb…` |
| or-gpt-4.1-reference | openai/gpt-4.1 | openai/gpt-4.1-2025-04-14 (created 1744651385) | openai | `a93701804c70c635…` |
| or-gpt-4.1-reference | openai/gpt-4.1 | openai/gpt-4.1-2025-04-14 (created 1744651385) | openai | `a93701804c70c635…` |
| or-gpt-oss-120b | openai/gpt-oss-120b | openai/gpt-oss-120b (created 1754414231) | deepinfra/bf16 | `9ced587a77f01469…` |
| or-gpt-oss-120b | openai/gpt-oss-120b | openai/gpt-oss-120b (created 1754414231) | deepinfra/bf16 | `9ced587a77f01469…` |
| or-nemotron-3-nano-30b-a3b | nvidia/nemotron-3-nano-30b-a3b | nvidia/nemotron-3-nano-30b-a3b (created 1765731275) | nebius/fp8 | `07c58a06e047d8b5…` |
| or-nemotron-3-nano-30b-a3b | nvidia/nemotron-3-nano-30b-a3b | nvidia/nemotron-3-nano-30b-a3b (created 1765731275) | nebius/fp8 | `07c58a06e047d8b5…` |
| or-qwen3.6-35b-a3b | qwen/qwen3.6-35b-a3b | qwen/qwen3.6-35b-a3b-20260415 (created 1777260255) | deepinfra/fp8 | `bfea44f0a17edb72…` |
| or-qwen3.6-35b-a3b | qwen/qwen3.6-35b-a3b | qwen/qwen3.6-35b-a3b-20260415 (created 1777260255) | deepinfra/fp8 | `bfea44f0a17edb72…` |
| agree:or-gpt-oss-120b+or-gemma-4-26b-a4b |  |  (created ) |  | `…` |

## Cascade end to end (synthetic site A, GZQO, D0)

| Build | Passed | S0→S5 funnel | Final list | Certificate | Model calls | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| agree:or-gpt-oss-120b+or-gemma-4-26b-a4b | True | 600 → 18 → 18 → 17 → 12 → 12 → 2 | 2 | issued | 31 | $0.003 |
| or-gemma-4-26b-a4b | True | 600 → 18 → 18 → 17 → 12 → 12 → 2 | 2 | issued | 17 | $0.001 |
| or-gpt-4.1-reference | False | 600 → 18 → 18 → 17 → 17 → 17 → 2 | 2 | issued | 0 | $0.000 |
| or-gpt-oss-120b | True | 600 → 18 → 18 → 17 → 12 → 12 → 2 | 2 | issued | 17 | $0.002 |
| or-nemotron-3-nano-30b-a3b | True | 600 → 18 → 18 → 17 → 12 → 12 → 2 | 2 | issued | 18 | $0.005 |
| or-qwen3.6-35b-a3b | True | 600 → 18 → 18 → 17 → 11 → 11 → 2 | 2 | issued | 17 | $0.012 |

Total recorded cost: $7.6752
