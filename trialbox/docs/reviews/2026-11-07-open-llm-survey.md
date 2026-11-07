# Which open LLMs for TrialBox? Survey and bake-off (2026-11-07)

Question (Changfu): there are many LLMs out there, including new work on Hugging Face. Have we compared them deeply,
and what is the best single model and the best pair for TrialBox?

## Short answer

**Keep the pair we have: Gemma 4 26B-A4B (4-bit) + Qwen3.5-9B, both must agree before anyone is excluded.**
We tested 15 newer open models against it. None beat it on both things that matter at once: losing few eligible
patients *and* still catching real exclusions, in English and Japanese, on three data sets.

| tier | recommendation | why |
| --- | --- | --- |
| one RTX 5090 (32 GB) | Gemma 4 26B-A4B 4-bit + Qwen3.5-9B 4-bit, `both_agree` | best balance; both Apache 2.0. Does **not** fit 32 GB yet as configured (35 GiB measured); needs a 4k context or a smaller Gemma build (next step 1) |
| one RTX 4090, or the 5090 until the pair fits | Gemma 4 26B-A4B 4-bit alone, `never` (LLM may send to review, never exclude) | best single model for finding exclusions and for PHI |
| 2× RTX 5090 | same pair, one model per card, 8-16k context | fits today with room |
| RTX PRO 6000 (96 GB) / DGX Spark | same pair for patient notes, plus gpt-oss-120b for protocol reading | the bigger models we tried were *less* careful on notes, not more |

The one real alternative found: **LFM2.5-24B-A2B** (Liquid AI, Oct 2026). Paired with Gemma 4 it loses half as many
eligible patients on TREC (9.8 % vs 19.3 %), but it also catches half as many true exclusions (26 % vs 54 %), so the
coordinator reviews about twice as many patients. It is weaker on real Japanese text, it always "thinks" (slower,
more tokens), and its licence does not cover commercial use by organisations with revenue over US$10 M, which
includes most hospitals. We do not recommend it as the default.

Medical and Japanese fine-tunes (Medical-Qwen3-Swallow-30B-A3B, MedGemma 27B, HuatuoGPT-3-27B, Fastino Nemotron
Healthcare, llm-jp-4.1, ELYZA-Thinking) are not served by any API we can reach, so they are **not tested**. Their base
models all did badly here (below), so expectations are low, but Medical-Qwen3-Swallow is worth one GPU run for
Japanese (next step 2).

## What was compared

All runs: OpenRouter, the TrialBox judge prompt, temperature 0, US$28.6 in total this round. Three data sets:

1. **TrialGPT SIGIR** (1,015 physician-labelled criteria, 79 eligible patient-trial pairs), English and machine-
   translated Japanese, scored "filter first": the LLM reads only the 42 % of criteria that need notes.
2. **TREC Clinical Trials 2021/22** (1,200 eligible + 500 excluded pairs, 20,096 criteria), every criterion read by
   the LLM. Raw rates include NIST label noise; a hand audit put true loss at about a third of the raw rate.
3. **MedTxt** (215 real Japanese case and radiology reports with English translations).

SIGIR is small: one pair is 1.3 points, and picking the best of ~600 pairs overfits. That is why every finalist was
re-checked on TREC and MedTxt, and why two models that looked best on SIGIR (Ministral 14B, Nemotron 3.5 Lightning)
were dropped.

### Single models (SIGIR, filter first; eligible pairs lost of 79, EN / JA; lower is better)

| model | size, fits | lost EN / JA | catches (EN) | verdict |
| --- | --- | --- | --- | --- |
| Qwen3.5-9B (current verifier) | 9B, any card | 3 / 2 | 0.64 | careful; keep |
| LFM2.5-24B-A2B (new) | 24B MoE, 2B active, ~14 GB | 5 / 3 | 0.58 | careful, low recall on TREC; licence limit |
| Gemma 4 26B-A4B 4-bit (current judge) | 26B MoE, ~17 GB | 5 / 5 | 0.67 | best recall of the careful ones; keep |
| Ternary Bonsai 2 9B (new, 1.6-bit) | ~3 GB | 2 / – | 0.48 | abstains on 87 % of criteria |
| Qwen3.5-27B | dense 27B | 4 / 8 | 0.55 | worse in Japanese |
| gpt-oss-safeguard-20b | 21B MoE | 8 / 7 | 0.76 | no gain over gpt-oss-20b |
| Qwen3.6-27B | dense 27B | 8 / 10 | 0.76 | |
| Muse Glimmer 30B (Meta, new) | dense 30B | 10 / 11 | 0.70 | |
| gpt-oss-120b (Spark judge) | 117B MoE | 10 / 10 | 0.67 | |
| Ministral 3 14B | dense 14B | 12 / 12 | 0.73 | TREC: loses 44 % |
| Nemotron 3 Super 120B | 120B MoE | 15 / 15 | 0.67 | |
| Nex-N2.5-mini | 35B | 16 / 12 | 0.67 | |
| Mistral Small 4 (119B) | 119B MoE | 17 / 15 | 0.82 | blocks too readily |
| Qwen3.5-122B-A10B | 122B MoE | 17 / 20 | 0.79 | blocks too readily |
| Granite 4.2 8B | 8B | 19 / 16 | 0.70 | |
| Nemotron 3.5 Lightning 30B-A3B | 30B MoE | 37 / 44 | 0.73 | erratic: 85 % lost on TREC |
| Xing4.0-29B-A4B | 29B MoE | 39 / – | 0.58 | unusable |
| Flint 40B | 40B MoE | 5 / – | 0.64 | Japanese answers all empty |

Bigger is not safer here: the three ~120B models lost 3-6 times more eligible pairs than the 9B Qwen.

### Pairs, both must block (the decision that matters)

| pair | SIGIR lost EN / JA | TREC lost (raw) | TREC exclusions caught | MedTxt JA: present findings caught / absent wrongly blocked | memory |
| --- | --- | --- | --- | --- | --- |
| **Gemma 4 4-bit + Qwen3.5-9B (current)** | 1 / 2 (OpenRouter); **4 / 3 on a real Blackwell card** | 19.3 % | **54 %** | **69 % / 6.3 %** | 35 GiB measured; 2× 5090 or PRO 6000 today |
| Gemma 4 4-bit + LFM2.5-24B | 1 / 1 | **9.8 %** | 26 % | 61 % / 4.7 % | ~31 GB weights, est., not measured |
| LFM2.5-24B + Qwen3.5-9B | 0 / 1 | 8.7 % | 24 % | 57 % / 3.2 % | ~21 GB weights, est. |
| gpt-oss-120b + Gemma 4 (Spark) | 5 / 4 | 24.9 % | 64 % | 88 % / 8.7 % | Spark / PRO 6000 |
| Gemma 4 4-bit + Ministral 14B | 2 / 2 | 21.8 % | 56 % | 76 % / 9.9 % | |

TrialGPT reference on SIGIR: the published GPT-4 matcher lost 8 of 79 eligible pairs reading every criterion; GPT-4.1
with the TrialGPT prompt lost 54. Every TrialBox pair above is at or below that. (TrialGPT 2.0, Sept 2026,
arXiv 2609.01202, ranks trials per patient with GPT-4.1; it does not report criterion-level loss, so there is no
like-for-like number.)

## PHI detection (new test)

120 fictional notes written by Claude Sonnet 5.5 (40 each in Japanese, Traditional Chinese, English), 1,131 planted
identifiers and 510 look-alikes (Parkinson, 橋本病, drug names, 主治医). Share of identifiers found / share of look-alikes
wrongly flagged:

| detector | JA | zh-TW | EN | look-alikes flagged |
| --- | --- | --- | --- | --- |
| TrialBox regex guard (today) | 64 % | 51 % | 52 % | 0-3 % |
| OpenMed Japanese PII 600M (CPU) | 81 % | – | – | 20 % |
| OpenMed privacy-filter-multilingual-v2 (CPU) | 79 % | 65 % | 83 % | 1-14 % |
| Qwen3.5-9B | 63 % | 68 % | 95 % | 0-2 % |
| **Gemma 4 26B-A4B** | **100 %** | **93 %** | **95 %** | **0 %** |

The regex guard misses facility names, ages over 89, most free-text dates and half the Chinese names. Gemma 4, which
is already on the card, found nearly everything. Recommendation: keep regex as the fast tripwire and add a Gemma 4 pass
before anything leaves the box. Caveat: the notes were written by an LLM, which flatters LLM detectors; check on real
de-identified notes before relying on it.

## Not measured

- Protocol-to-criteria drafting, REDCap field extraction and chat were not benchmarked this round. Use Gemma 4 on one
  card (it is the best general model that fits) and gpt-oss-120b on PRO 6000 / Spark for protocol reading, where a
  person approves the result anyway.
- No new run on a real GPU; the GCP VM is stopped and this session has no GCP credentials.
- Medical and Japanese fine-tunes listed above (not on any API).

## Next steps

1. Make the pair fit one 5090: run Google's QAT 4-bit Gemma build (`cyankiwi/gemma-4-26B-A4B-it-qat-AWQ-INT4` or
   `google/gemma-4-26B-A4B-it-qat-q4_0-gguf`) with a 4k context on the GPU VM, and re-score. The NVFP4 build we
   measured was worse than the 4-bit API build (11 vs 5 lost alone).
2. In the same GPU session (about 2 h, about US$6 Spot): Medical-Qwen3-Swallow-30B-A3B and MedGemma 27B on SIGIR,
   TREC and MedTxt.
3. Re-test PHI on real de-identified Japanese notes when a site provides them.

## Re-run

```
python -m tools.trialgpt_compare run --pipelines trialbox --langs en ja --models liquid/lfm-2.5-24b-a2b ...
python -m tools.trialgpt_compare filterfirst --lang ja
python -m tools.trec_ct_eval run --models liquid/lfm-2.5-24b-a2b && python -m tools.trec_ct_eval score
python -m tools.medtxt_eval run --models liquid/lfm-2.5-24b-a2b && python -m tools.medtxt_eval score
python tools/phi_synth_eval.py eval/phi_synth/notes.jsonl google/gemma-4-26b-a4b-it
```

Raw answers are under `eval/trialgpt_compare/results/raw`, `eval/trec_ct/results/raw`, `eval/medtxt/results/raw`,
`eval/phi_synth/`.

Sources: Hugging Face model cards (LiquidAI/LFM2.5-24B-A2B and its LICENSE, tokyotech-llm/Medical-Qwen3-Swallow-30B-A3B,
FreedomIntelligence/HuatuoGPT-3-27B, fastino/Fastino-Nemotron-3.5-Lightning-Healthcare, OpenMed PII models,
google/medgemma-27b-text-it, llm-jp/llm-jp-4.1-32b-a3b-thinking, elyza/ELYZA-Thinking-1.0-llm-jp-4-32b-a3b);
TrialGPT 2.0, https://arxiv.org/abs/2609.01202.
