# TB-DR-03a Verifier and embedder candidates: desk comparison

| Field | Value |
| --- | --- |
| Date | 2026-11-10 |
| Asked by | The owner, 2026-11-10: own quantised build of the verifier, disclosure to both hospitals, and a comparison that includes non-PRC options ("Mistral? or no-PRC options"). |
| Code read | Deep-review branch (= `origin/master` at `ca8f287`). PR #64 `tools/judge_bakeoff.py` read from its remote branch, not checked out. |
| Method | Desk study only. One reviewer. Facts were read on 2026-11-10 from the Hugging Face model API (`huggingface.co/api/models/<repo>`, with `?blobs=true` for file sizes) and from the raw model cards (`<repo>/raw/main/README.md`). The vLLM release list was read from `github.com/vllm-project/vllm/releases`. Earlier measurements come from `docs/reviews/2026-11-07-open-llm-survey.md`. |
| What was run | Read-only web lookups. A count of the gated judge set by language (`tests/fixtures/llm/judge_set.jsonl`). Nothing else. |
| What was not run | No GPU. No model was downloaded, quantised or served. No bake-off. No cloud spending. Every VRAM and GPU-hour number below is an estimate. |
| What was not verified online | (1) Licence **texts** behind a gate or a script page: the two TAIDE licence agreements (Google Drive links), the PLaMo Community License page (renders by script), the Llama 3.1 / 3.2 community licences and acceptable-use policy (gated repo; the Meta page redirected twice), the Health AI Developer Foundations terms for MedGemma. For these the licence **name** was verified; the clauses are from training knowledge and are marked. (2) NTT tsuzumi: no open weights were found on Hugging Face; nothing else was checked. (3) Country of origin is from general knowledge of each organisation, not from the model card. (4) Whether each candidate obeys vLLM v0.32.0 structured output on the product's judge schema: no card states it; only a run can show it. (5) MIG profile names and sizes on the B200. |
| Related findings | LLM-005, LLM-007, LLM-008, LLM-009, LLM-011, LLM-012, LLM-020, LLM-027, LLM-031 (`03-llm-serving-stack.md`); DEP-007, DEP-008, DEP-010, DEP-011 (`08-dependency-currency.md`); CR-097. |

## 1. Summary

1. **The incumbent can be fixed without changing the model.** Official `Qwen/Qwen3.5-9B` weights are Apache-2.0 and
   pinned at revision `c20223623576`. The owner's own 4-bit build is about one GPU-hour. There is also an
   organisation-published 4-bit build now (`RedHatAI/Qwen3.5-9B-quantized.w4a16`, 2026-04-24, and
   `RedHatAI/Qwen3.5-9B-NVFP4`, 2026-11-06), which DEP-008 did not list. This removes the personal-account problem.
   It does not remove the PRC-origin question.
2. **There is a credible non-PRC verifier to test: Mistral Ministral 3 14B Instruct (France, Apache-2.0).** It
   declares Japanese and Chinese, is built for vLLM, and has an organisation-published NVFP4 build of 12.5 GiB.
   The team already measured it on 2026-11-07: as the second model beside Gemma 4 it was close to Qwen but a little
   less careful (MedTxt: 9.9 % of absent findings wrongly blocked, against 6.3 %). So it is a real candidate, not a
   sure win.
3. **No Japan-origin or Taiwan-origin model covers all three languages with a clean licence.** The best one is
   `llm-jp/llm-jp-4.1-8b-thinking` (National Institute of Informatics, Japan; Apache-2.0; trained from scratch;
   Japanese and English only). It can be a Japan-site candidate. The Taiwan models (TAIDE, Breeze 2) sit on Gemma 3
   or Llama bases with extra licence agreements, are Traditional Chinese only, and have no vendor quantised build.
4. **A smaller Gemma 4 is the easiest to serve and the weakest second check.** Same developer, same training
   lineage and same tokenizer family as the judge: the two models tend to make the same mistakes.
5. **Mistral licences differ by model.** Ministral 3 (3B, 8B, 14B, December 2025) is Apache-2.0. The older
   `Ministral-8B-Instruct-2410` is under the Mistral Research Licence (no commercial use). Codestral 22B and
   Mistral Small 2409 are also `license: other`. Use only the `2512` Ministral 3 files.
6. **Embedder:** two non-PRC multilingual options are worth one run in the existing `tools/bench_embed.py`:
   `ibm-granite/granite-embedding-311m-multilingual-r2` and `google/embeddinggemma-2`. Both are Apache-2.0,
   ship safetensors, and output 768 dimensions (bge-m3 has 1024, so the index must be rebuilt).
7. **Bake-off cost:** about 8 GPU-hours on one RTX PRO 6000 spot VM for three verifier candidates plus the
   embedder comparison (estimate, section 6).

This file has no new findings in the `ID | Severity` format. It supports the fix of DEP-008 and CR-097 and adds
task-card text (section 8).

## 2. The job, and what "fits" means

The verifier is the second, independent reader. It gets the same criterion and note excerpt as the judge, in
Japanese, Traditional Chinese (Taiwan usage) or English. It answers in the product's JSON schema with a verdict and
an exact quote. A note criterion excludes a patient only when both models agree.

| Limit | Value | Source |
| --- | --- | --- |
| Class | about 7B to 14B (a 21B mixture-of-experts model with 4-bit official weights is listed as a border case) | owner's request |
| Memory beside the judge | about 19 GiB today on the RTX PRO 6000 (0.20 of the card; weights 7.5 GiB, the rest KV cache) | `deploy/docker-compose.rtxpro6000.yml:13` |
| MIG slice on the B200 | about 23 GB for the verifier, about 45 GB for the judge | LLM-027 |
| Context | 32k on RTX PRO 6000, 16k on DGX Spark, 8k on RTX 5090 | `models/registry.yaml` |
| Server | vLLM, pinned `vllm/vllm-openai:v0.32.0` (release of 2026-10-18; v0.33.0 is at release candidate on 2026-11-02) | compose files; vLLM release page read 2026-11-10 |
| Use | commercial, on-premises, hospitals in Japan and Taiwan | owner |

Rule of thumb used for the VRAM column (estimate): weight files + about 2 GiB for the runtime + KV cache. On a
23 GB slice a 4-bit model of 6 to 13 GiB leaves 8 to 15 GiB for KV cache. The measured Qwen build uses about
45 KiB of KV per token; other architectures differ, so only a run gives the real number.

## 3. Verifier candidates

All facts in this section were read on 2026-11-10 from the Hugging Face API and the model card of the named
repository, unless a cell says otherwise. "Lost EN / JA" is the number of eligible pairs lost of 79 on the SIGIR
set, model alone, from the 2026-11-07 survey (lower is better; Qwen3.5-9B lost 3 / 2).

### 3.1 Main table

| # | Model (repo, revision) | Developer, origin | Licence; hospital commercial on-prem use | Size; context | ja / zh-TW / en as documented | JSON and structured output | Quantised weights; vLLM | VRAM estimate (4-bit) | Independence from the judge | Provenance | Known risks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **Qwen3.5-9B** (incumbent). `Qwen/Qwen3.5-9B` rev `c20223623576`, last change 2026-03-02 | Alibaba Qwen team, PRC | Apache-2.0 (LICENSE file in repo). Allowed. | 9.65 B params; 18.0 GiB BF16; 262,144 tokens native | "201 languages and dialects"; no separate Traditional Chinese statement. Measured here: lost 3 / 2 alone; pair 1 / 2 (zh-TW 1) | Works today with thinking off. Copies Japanese quotes with stray spaces (handled by the quote fix of 2026-11-08). 53 of 54 on the canary | No quantised build from Qwen. Organisation builds: `RedHatAI/Qwen3.5-9B-quantized.w4a16` (INT4, 10.7 GiB, rev `a398088c4228`, 2026-04-24, recipe in repo), `RedHatAI/Qwen3.5-9B-NVFP4` (8.7 GiB, rev `a4df85a20fb7`, 2026-11-06), `RedHatAI/Qwen3.5-9B-FP8-dynamic` (13.0 GiB). Today's build: `cyankiwi/Qwen3.5-9B-AWQ-4bit` (8.4 GiB, personal account). Card says vLLM is supported; the box already serves it on v0.32.0 | 19 GiB measured at 32k (weights 7.5 GiB loaded) | Different developer, architecture and training data from Gemma. Good. | Official org account; revision known; own build gives own hashes | PRC origin: must be disclosed, may be refused by a hospital or a sponsor. Card recommends 128k context "to preserve thinking"; the box runs thinking off |
| 2 | **Ministral 3 14B Instruct 2512**. `mistralai/Ministral-3-14B-Instruct-2512` rev `29439f81c2be`, last change 2026-07-15 | Mistral AI, France | Apache-2.0 (card: "commercial and non-commercial"). Allowed. | 13.9 B params; official weights are FP8; 256k context | Card lists Chinese and Japanese among 11 named languages. No Traditional Chinese statement. Measured here: alone lost 12 / 12 and 44 % on TREC; **as second model beside Gemma: 2 / 2, TREC 21.8 % lost, 56 % caught, MedTxt 76 % caught / 9.9 % wrongly blocked** (Qwen pair: 1 / 2, 19.3 %, 54 %, 69 % / 6.3 %) | Card: "native function calling and JSON outputting"; recommends temperature below 0.1. Uses the `mistral-common` tokenizer (`tekken.json`); guided JSON under that tokenizer must be checked on v0.32.0 | Official FP8 (card: fits 24 GB VRAM; too tight for a 23 GB slice). Organisation 4-bit: `RedHatAI/Ministral-3-14B-Instruct-2512-NVFP4` (12.5 GiB, rev `ae31e2b3d5ac`, recipe in repo). `library_name: vllm`; card asks for vLLM 0.12.0 or later | 12.5 GiB weights + KV: about 20 to 22 GiB at 32k; fits the slice with a smaller KV budget than Qwen | Different developer, country, architecture and tokenizer. Good. | Official org account; revision known. The RedHatAI card's release date field reads "05/21/2025", before the model existed: treat that card as careless and make an own build | Less careful than Qwen as second reader in the one measurement that exists. 14B is slower than 9B. NVFP4 under MIG on the B200 is unproven (RSK-43); an INT4 build avoids that |
| 3 | Ministral 3 8B Instruct 2512. `mistralai/Ministral-3-8B-Instruct-2512` rev `5b26027e7b19` | Mistral AI, France | Apache-2.0. Allowed. | 8.9 B params; FP8 official; 256k | Same language list as the 14B | As row 2 | Official FP8 only; own 4-bit needed | about 6 GiB weights (est.) | As row 2 | Official org | Not measured here. Smaller than a model that already lost more than Qwen; test only if the 14B is too slow |
| 4 | **Gemma 4 12B-it**. `google/gemma-4-12B-it` rev `43c9d014b231`, last change 2026-10-30 | Google DeepMind, US | Apache-2.0 on the card (link to the Gemma 4 licence page). Allowed. | 11.95 B params; 256k context | Card: "support for 35+ languages, pre-trained on 140+". Judge sibling scored well on ja and zh-TW here | Native system role and function calling; thinking can be switched off | **Official** 4-bit QAT build for vLLM: `google/gemma-4-12B-it-qat-w4a16-ct` (9.6 GiB, rev `1d2c2d7f2466`, compressed-tensors, recipe in repo) | about 17 to 19 GiB at 32k | **Weak.** Same developer, same data and training recipe, same tokenizer family as the judge. Errors are likely to be correlated: both may misread the same negation or the same abbreviation. Agreement then says less than it seems. A prompt injection or a template fault (DEP-007) hits both | Official org; official quantisation; best provenance of all rows | A second check that shares the judge's blind spots. Use as a fallback only, or as a third reader |
| 5 | Phi-4 (14B). `microsoft/phi-4` rev `2db69c1c3e91` | Microsoft, US | MIT. Allowed. Card warns about "high-risk scenarios" such as health advice | 14.7 B params; **16k context** | Card: "trained primarily on English … not intended to support multilingual use"; multilingual data about 8 % | No statement | `RedHatAI/phi-4-quantized.w4a16` (8.5 GiB) | about 16 GiB | Different developer and data | Official org | English only by the vendor's own words. 16k context is the Spark limit and below the 32k profile. **Not suitable.** No newer Phi of this size was found on 2026-11-10 (Phi-4-mini 3.8B lists ja and zh; too small) |
| 6 | Granite 4.2 8B. `ibm-granite/granite-4.2-8b` rev `a7042144125c`, last change 2026-10-20 | IBM, US | Apache-2.0. Allowed. | 8.8 B params; 128k native | Tested languages include Japanese and Chinese; no Traditional Chinese statement. Measured here: alone lost **19 / 16** | Training included "structured output" environments; thinking can be switched off | **Official** `granite-4.2-8b-nvfp4` (5.7 GiB), `-fp8` (9.0 GiB), `-mxfp4`. Card has a vLLM section | about 12 to 14 GiB | Different developer and data | Official org; repo carries `model.sig` (signed weights). Best supply-chain story after Google | Lost six times more eligible pairs than Qwen when alone. Low priority unless the pair result differs |
| 7 | Llama 3.1 8B Instruct. `meta-llama/Llama-3.1-8B-Instruct` rev `0e9e39f249a1` (2024) | Meta, US | Llama 3.1 Community License; gated, manual approval. Commercial use allowed with an acceptable-use policy, attribution and naming rules (clauses not verified online) | 8.0 B params; 128k | Card languages: en, de, fr, it, pt, hi, es, th. **No Japanese, no Chinese** | Old model; no statement | Community only | about 12 GiB | Different developer | Official org, gated | Not suitable: languages. Meta's newer open models are too large for the slot (Llama 4 Scout 109 B; `meta-models/Muse-Glimmer-30B`, Apache-2.0, 30 B, lost 10 / 11 alone here) |
| 8 | **gpt-oss-20b** (border case). `openai/gpt-oss-20b` rev `6cee5e81ee83` (2025-08) | OpenAI, US | Apache-2.0 plus a usage policy file. Allowed. | 20.9 B params, mixture of experts; official weights are 4-bit (MXFP4), 12.8 GiB; card: runs "within 16GB" | No language list on the card. Measured here on the sibling `gpt-oss-safeguard-20b`: alone lost 8 / 7, catches 0.76 | Card lists "Structured Outputs". Works only with the harmony format; always reasons (effort low, medium, high), so more tokens and time per answer | Official weights are already quantised by the developer. Card names vLLM | about 20 to 22 GiB at 32k | Different developer and architecture. Good | Official org; developer's own quantisation | Outside the 7 to 14B class by total size. Reasoning cannot be turned off, so latency and the token cap need care. The pair gpt-oss-120b + Gemma lost more than the Qwen pair |
| 9 | **llm-jp-4.1-8b-thinking**. `llm-jp/llm-jp-4.1-8b-thinking` rev `7c19bc90e49b`, 2026-09-15 | National Institute of Informatics (LLM research centre), Japan | Apache-2.0. Allowed. | 8.59 B params; 16.0 GiB BF16; **65,536** context | Languages on the card: Japanese and English. **No Chinese.** Trained from scratch on 11.7 T tokens; corpora are public | Chat template is "compatible with the OpenAI Harmony response format" but with its own tokenizer; the card says the `openai-harmony` library does not work. A thinking model | No official quantised build; community builds only. The card has no vLLM section. A model built on the same base (`elyza/ELYZA-Thinking-1.0-llm-jp-4-32b-a3b`) ships vLLM plugin files, which suggests a plugin is needed | about 6 GiB weights after own 4-bit (est.); about 14 GiB | **Strongest.** Own data, own tokenizer, public institute, no US or PRC base model | Official org account; no hashes published beyond the repo | Japan site only (no zh-TW). vLLM and structured output are unproven. Not measured here (the survey could not reach it by API) |
| 10 | GPT-OSS-Swallow-20B. `tokyotech-llm/GPT-OSS-Swallow-20B-RL-v0.1-MXFP4` rev `41133b64e441`, 2026-05 | Institute of Science Tokyo (Okazaki lab) with AIST, Japan; base model OpenAI, US | Apache-2.0. Allowed. | 20.9 B params; 12.8 GiB MXFP4 | Japanese and English | As row 8 (harmony) | Official MXFP4 build from the lab; card: "primarily developed and evaluated using vLLM" | about 20 to 22 GiB | Different from Gemma; same base as row 8 | University org account | Japan site only. Border size. Not measured here |
| 11 | Medical-Qwen3-Swallow-8B. `tokyotech-llm/Medical-Qwen3-Swallow-8B` rev `f9a3d4dc3827`, 2026-06 | Institute of Science Tokyo, Japan; base model Qwen3-8B, PRC | Apache-2.0. Card: "intended for research and development … not validated as a medical device" | 8.19 B params; card advises 32,768 context or less | Japanese and English; Japanese medical benchmarks on the card | No statement; reasoning parser `qwen3` | No quantised build for the 8B medical model; card shows a vLLM command | about 12 to 14 GiB | Different from Gemma, but **same lineage as the incumbent** | University org | Does not answer the PRC-origin question (base is Qwen3). The licence allows hospital use; the card's intended use does not cover it |
| 12 | Gemma-3-TAIDE-12b-Chat-2602. `taide/Gemma-3-TAIDE-12b-Chat-2602` rev `4de0b93b99f8`, 2026-02-13 | TAIDE project (National Science and Technology Council programme), Taiwan; base `google/gemma-3-12b-pt` | "Gemma-version TAIDE models license agreement"; gated (accept terms and a privacy notice). Commercial terms **not verified online** | 12.4 B params; 25.4 GiB BF16; 128k | Traditional Chinese first (22 B tokens of Taiwan text); TMMLU+ 58.0 against 53.8 for Gemma-3-12b-it. Japanese not mentioned | No statement. Card: add safety safeguards before use | No official quantised build | about 16 to 18 GiB after own 4-bit | **Weak**: Gemma 3 base, the generation before the judge | Official project account; gated | Licence unclear for a commercial product. Same family as the judge. zh-TW only |
| 13 | Llama-3.1-TAIDE-LX-8B-Chat. `taide/Llama-3.1-TAIDE-LX-8B-Chat` rev `673892378666`, 2025-02 | TAIDE, Taiwan; base Meta Llama 3.1 8B | "TAIDE L models community license agreement" on top of the Llama licence; gated. Commercial terms **not verified online** | 8.5 B params; 131k | Traditional Chinese; English in pretraining | No statement | No official quantised build of this version | about 12 GiB | Different from Gemma | Official project account | Two stacked licences. Base from 2024. zh-TW only |
| 14 | Llama-Breeze2-8B-Instruct. `MediaTek-Research/Llama-Breeze2-8B-Instruct` rev `724cdce8e4d4`, 2025-01 | MediaTek Research, Taiwan; base Meta Llama 3.2 | Llama 3.2 Community License (clauses not verified online) | 8.4 B params | Traditional Chinese and English | Function calling claimed in the paper title | None. The repo has custom model code (`modeling_internvl_chat.py`); vLLM support unknown | about 12 GiB | Different from Gemma | Official org | Custom code is a supply-chain and serving risk. The vision part follows the InternVL design (a PRC lab). Base from 2024. No newer Breeze text model was found |

### 3.2 Looked at and left out

| Model | Why it is out | Source, date |
| --- | --- | --- |
| `mistralai/Ministral-8B-Instruct-2410` | `license: other`, name `mrl` (Mistral Research Licence): no commercial use | HF API, 2026-11-10 |
| `mistralai/Codestral-22B-v0.1`, `Mistral-Small-Instruct-2409`, `Mistral-Medium-3.5-128B`, `Mistral-Large-4-1T-A52B` | `license: other`; and the last two are far too large | HF API, 2026-11-10 |
| `mistralai/Mistral-Small-4-119B-2603` | Apache-2.0 but 119 B; lost 17 / 15 alone here | HF API; survey 2026-11-07 |
| Mistral Small 3.2 24B, Mistral Nemo 12B (2407) | Apache-2.0. Small 3.2 (24 B, 2025-06) needs a 4-bit build of about 14 GiB and is a reserve if the 14B fails; Nemo is from 2024 and superseded by Ministral 3 | HF API, 2026-11-10 |
| `google/medgemma-1.5-4b-it`, `medgemma-27b-text-it` | Health AI Developer Foundations terms, gated; 4 B is too small, 27 B too large; and Gemma family, so weak independence. Terms not verified online | HF API, 2026-11-10 |
| `pfnet/Preferred-MedRECT-32B`, `tokyotech-llm/Medical-Qwen3-Swallow-30B-A3B`, `Medical-GPT-OSS-Swallow-120B` | Too large for the verifier slot | HF API, 2026-11-10 |
| `pfnet/plamo-3-nict-8b-base`, `plamo-3-8b-fin-instruct` | PLaMo Community License; the card says to contact the company for commercial use; base model or finance tuning only. Licence text not verified online | model card, 2026-11-10 |
| `cyberagent/CAT-Thinking-8B`, `CAT-Paws-8B`; `tokyotech-llm/Qwen3-Swallow-8B-RL-v0.2` | Apache-2.0, Japan-tuned, but the base is Qwen3-8B: PRC lineage stays | HF API, 2026-11-10 |
| `Rakuten/RakutenAI-3.0.1` (684 B), `stockmark/Stockmark-2-100B-Instruct`, `elyza/ELYZA-Thinking-1.0-llm-jp-4-32b-a3b` (32 B) | Too large | HF API, 2026-11-10 |
| Sakana AI | No general instruct model of this size on its account (research models only) | HF listing, 2026-11-10 |
| NTT tsuzumi | No open weights found on Hugging Face. Not verified further | HF search, 2026-11-10 |
| `LiquidAI/LFM2.5-8B-A1B`, `LFM2.5-24B-A2B` | `license: other`; the survey found the licence excludes organisations above US$10 M revenue | HF API; survey 2026-11-07 |
| `nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16` | NVIDIA open model licence; English only on the card; 4 B | HF API, 2026-11-10 |
| Cohere tiny-aya, North-Small-Translate | CC BY-NC 4.0: no commercial use | HF API, 2026-11-10 |
| `yentinglin/Llama-3-Taiwan-8B-Instruct`, `FoxconnAI/Llama_3.1-FoxBrain-70B` | Personal account and 2024 base; or 70 B | HF search, 2026-11-10 |

### 3.3 Why same-family is a weakness for the second check

The pair rule is safe only if the two models fail in different places. The 2026-11-07 survey shows the value: Gemma 4
alone lost 11 / 12 eligible pairs on the card; with Qwen as second reader it lost 4 / 3. That gain comes from
disagreement. A smaller Gemma 4 has the same developer, the same pre-training data mix, the same tokenizer and chat
template, and the same safety tuning. It will more often repeat the judge's reading, right or wrong. It also shares
single points of failure: a chat-template fault (DEP-007) or an instruction planted in a note (LLM-034) reaches both.
LLM-005 already says the two readings are less independent than they look; a same-family verifier makes that worse.
If Gemma 4 12B is ever used, the bake-off must report its error overlap with the judge, not only its own error rate.

## 4. Ranked shortlist for the bake-off

| Rank | Candidate | Role in the test | Build to test | Why |
| --- | --- | --- | --- | --- |
| 1 | **Ministral 3 14B Instruct 2512** (Mistral AI, France) | Primary non-PRC candidate, all three languages | Own INT4 (W4A16) build from `mistralai/Ministral-3-14B-Instruct-2512-BF16` rev `3cea74c1ebaf` with the public llm-compressor recipe; also `RedHatAI/…-NVFP4` rev `ae31e2b3d5ac` as a cross-check | Apache-2.0, EU developer, official vLLM support, ja and zh declared, and the only non-PRC model with an existing pair measurement that is close to the incumbent |
| 2 | **llm-jp-4.1-8b-thinking** (NII, Japan) | Japan-origin candidate, **ja and en only**, for the Japan site | Own INT4 build from rev `7c19bc90e49b` | Cleanest lineage and licence of any Japan or Taiwan model. Stop early if vLLM v0.32.0 cannot serve it with the product's JSON schema. Reserve: `tokyotech-llm/GPT-OSS-Swallow-20B-RL-v0.1-MXFP4` |
| 3 | **Qwen3.5-9B, own build** (incumbent) | Baseline and fallback | Own AWQ INT4 from `Qwen/Qwen3.5-9B` rev `c20223623576` with the recipe now in the community repo (llm-compressor AWQ, int4, group 32); compare with today's `cyankiwi` rev `e4d2d39cede8` and with `RedHatAI/Qwen3.5-9B-quantized.w4a16` | Shows that the own build answers like the build measured on 2026-11-08, and gives every other candidate its reference |

If time is left on the VM, run `google/gemma-4-12B-it-qat-w4a16-ct` (to measure the error overlap of section 3.3)
and `openai/gpt-oss-20b` (the best non-PRC model alone in the survey, by its safeguard sibling).

No credible Taiwan-origin candidate exists today for this job. TAIDE's Gemma 3 model is the nearest; ask TAIDE
for the commercial terms before spending GPU time on it.

## 5. Exact measurements

Harness: PR #64 `tools/judge_bakeoff.py` with the product's `judge` prompt, `chat_json` and `postprocess`. It tests
one model alone today. The pair measurements need the `--pair` mode proposed in LLM-031; until it exists, compute
them offline from two `rows.jsonl` files joined on the item id.

The gated set by language today (counted 2026-11-10): the synthetic set has 300 items, 261 with a note, **all in
Traditional Chinese**; MedTxt gives Japanese and English. There is no English or Japanese synthetic item and no real
zh-TW text. With 62 judge exclusions in the synthetic set, the upper 95 % bound of "0 wrong" is 5.8 % (LLM-031).
Grow each language to about 190 judge exclusions before reading a 2 % claim from it.

| # | Measurement | Definition | Per | Pass line (proposal) |
| --- | --- | --- | --- | --- |
| M1 | **Wrong-confirmation rate** | Of the items where the judge excluded and the gold does not exclude, the share the verifier also excluded. This is the error the pair lets through | ja, zh-TW, en; and pooled | Not above the Qwen own build on any language; pooled pair wrong exclusions ≤ 2 % with Wilson and patient-cluster intervals |
| M2 | Right-confirmation rate | Of the judge's correct exclusions, the share the verifier confirmed (what the pair keeps) | language | Not more than 5 points below Qwen |
| M3 | Agreement | Raw agreement and Cohen's kappa between judge and verifier on all asked items; plus the count of items where both are wrong the same way (error overlap) | language | Reported; overlap is the independence number |
| M4 | Verifier alone | The existing gate: wrong exclusions, unanswered share, abstention on gold-unknown, citation validity (quote found in an excerpt, date correct) | source and language | Unanswered ≤ 10 %; citation validity not below Qwen |
| M5 | JSON validity | Share of calls with a schema-valid answer on the first attempt and after the one retry; share cut off by the token cap; each registered schema sent once with an adversarial prompt (LLM-020) | language | 100 % after retry; ≥ 99 % first attempt |
| M6 | Quote fidelity | Share of quotes that match the excerpt exactly, and after the CJK-space rule | ja, zh-TW | Reported (Qwen needed the space rule) |
| M7 | Latency | p50 and p95 per item and per HTTP call, at 1 and at 16 concurrent requests; checks per second; tokens in and out (reasoning tokens apart) | profile | p95 not above 2 × Qwen at 16 concurrent |
| M8 | VRAM on the slice | Server started with a 23 GB cap (`--gpu-memory-utilization` set so that the process may take 23 GB of the 96 GB card), at 32k and at 16k context, 16 sequences: `nvidia-smi` memory after load and at peak; longest prompt of the set accepted (LLM-015) | 23 GB, and the Spark's 16k | Starts, serves the longest prompt, no out-of-memory in the run |
| M9 | Repeat run | The same frozen set twice; share of identical verdicts (LLM-021) | candidate | ≥ 99 % |
| M10 | Identity | `--revision`, `--model-dir` manifest sha256, `/v1/models` root before and after; the llm-compressor version and recipe file hash for own builds | build | Recorded in `metrics.json` and in the registry row |

For the Qwen own build add one check: verdict agreement with today's `cyankiwi` build on the full set. A
quantised build made from the same recipe will not be bit-identical; ≥ 98 % identical verdicts and no change in M1
is the proposed line.

The capped RTX PRO 6000 is a stand-in for the B200 slice. It does not prove MIG behaviour or NVFP4 kernels on the
B200 (LLM-027, RSK-43). That needs the owner's B200.

## 6. GPU-hours on one RTX PRO 6000 spot VM (estimate)

| Step | Hours |
| --- | --- |
| Start, pull the pinned vLLM image, download weights (about 90 GiB in all) | 0.75 |
| Judge pass on the frozen set (once; its rows are reused for every pair) | 0.5 |
| Own INT4 builds: Qwen3.5-9B, Ministral 3 14B, llm-jp-4.1-8b (calibration, save, hash) | 2.0 |
| Three candidates × (alone, pair join, 23 GB sizing at two contexts, latency at two loads, repeat run) | 3.0 |
| Qwen comparison builds (`cyankiwi`, RedHatAI INT4) | 0.5 |
| Embedder comparison of section 7 (`tools/bench_embed.py`, four models) | 0.5 |
| Spot preemption and one failed start | 0.75 |
| **Total** | **about 8** |

The survey's own rate ("about 2 h, about US$6 Spot") puts this near US$25. It is one working day on the one
allowed GPU, after the G1 run that is using it now. The optional Gemma 4 12B and gpt-oss-20b runs add about 1.5 hours.

## 7. Embedder candidates

Read on 2026-11-10 from the Hugging Face API and model cards. The embedder is not in `models/registry.yaml`
(LLM-012) and `tools/bench_embed.py` compares bge-m3 with Qwen3-Embedding-0.6B only; both are PRC-origin.

| Model (repo, revision) | Developer, origin | Licence | Size; dimensions; max tokens | ja / zh-TW / en | Weights format | Notes and risks |
| --- | --- | --- | --- | --- | --- | --- |
| **bge-m3** (incumbent). `BAAI/bge-m3` rev `5617a9f61b02`, 2024-07-03 | Beijing Academy of Artificial Intelligence, PRC | MIT | XLM-RoBERTa-large base; 1024; 8192 | "more than 100 working languages"; no Traditional Chinese statement | Pickle (`pytorch_model.bin`) and ONNX only; `pin_model` refuses pickle (DEP-010) | PRC origin. Not changed since 2024 |
| Qwen3-Embedding-0.6B. `Qwen/Qwen3-Embedding-0.6B` rev `97b0c614be4d` | Alibaba Qwen, PRC | Apache-2.0 | 0.6 B; 1024; long context | multilingual | safetensors | PRC origin; already in `bench_embed` |
| **granite-embedding-311m-multilingual-r2**. `ibm-granite/granite-embedding-311m-multilingual-r2` rev `443995599303`, 2026-04-20 | IBM, US | Apache-2.0 | 311 M (ModernBERT); **768**; 32,768 | Japanese and Chinese are in the 52 "enhanced support" languages; card shows Japanese cross-lingual examples. No Traditional Chinese statement | safetensors, ONNX, `model.sig` | Non-PRC, signed, long context. 768 dimensions: the pgvector column and index must be rebuilt. Card: 65.2 on multilingual MTEB retrieval (vendor number) |
| **embeddinggemma-2**. `google/embeddinggemma-2` rev `f9972ac22e69`, 2026-09-14 | Google DeepMind, US | Apache-2.0 | 740 M total, 270 M text part (other encoders can be left unloaded); **768** (128 to 768 Matryoshka); 8192 | "100+ languages"; no per-language table read | safetensors | Non-PRC. Needs task prefixes in the query and document text. Same vendor as the judge, which matters less for retrieval than for the second check |
| snowflake-arctic-embed-l-v2.0. `Snowflake/snowflake-arctic-embed-l-v2.0` rev `ac6544c8a46e`, 2024-11 | Snowflake, US | Apache-2.0 | 568 M; 1024; 8192 | ja and zh in the language list | safetensors | Drop-in size for bge-m3 (1024, same architecture). But the card says it "builds on BAAI/bge-m3-retromae": the encoder base is PRC-origin, so it is only a partial answer |
| multilingual-e5-large. `intfloat/multilingual-e5-large` rev `3d7cfbdacd47` | Microsoft researchers (personal account `intfloat`) | MIT | XLM-RoBERTa-large; 1024; **512** tokens | 100 languages incl. ja, zh | safetensors | Named in spec v4 as the fallback. 512 tokens is short for note chunks; personal account |
| bitnet-embedding-0.6b. `microsoft/bitnet-embedding-0.6b` rev `16176d108561`, 2026-07 | Microsoft, US | MIT | 0.6 B, 1.58-bit weights; 1024; 32,768 | multilingual list incl. ja, zh | custom format | Backbone is Qwen3-0.6B (card): PRC lineage. Needs the BitNet runtime |
| plamo-embedding-1b. `pfnet/plamo-embedding-1b` rev `51507f82e588` | Preferred Networks, Japan | Apache-2.0 | 1.05 B; 2048; 4096 | **Japanese only** | safetensors, custom model code | Japan site only; custom code |
| embeddinggemma-GTAIDE-300m-2605. `taide/embeddinggemma-GTAIDE-300m-2605` rev `451ef76c7ef1`, 2026-06 | TAIDE, Taiwan; base `google/embeddinggemma-300m` | Gemma-version TAIDE licence, gated; terms not verified online | 303 M; dimensions not read | Traditional Chinese focus (card not readable: gated) | safetensors | Licence unclear; 625 downloads |
| jina-embeddings-v3, v5-text-small | Jina AI, Germany | **CC BY-NC 4.0** | – | – | – | Not allowed for commercial use; v5 is also based on Qwen3-0.6B |

Proposal: add `ibm-granite/granite-embedding-311m-multilingual-r2` and `google/embeddinggemma-2` to
`tools/bench_embed.py` and run the four models on the existing ja and zh-TW set (needle MRR@10 and recall@10,
finding nDCG@10 and precision@10, the negation traps, docs per second, GPU memory). Switch only if a non-PRC model
is within the noise of bge-m3 on both languages. The embedder never decides alone (only a calibrated threshold in
code acts on a score), so a small loss in recall costs review time, not safety; the S2b threshold must be refitted
after any switch.

## 8. What to tell the two hospitals now

Send the same short note to both sites, in their language, before hospital IT is engaged. Proposed content:

1. **What runs on the box.** Three open-weight models, all on the hospital's own server. No patient text leaves it.
   The judge is Gemma 4 26B-A4B (Google, US, Apache-2.0). The verifier is Qwen3.5-9B (Alibaba, PRC, Apache-2.0).
   The planned embedder is bge-m3 (BAAI, PRC, MIT).
2. **What "PRC-origin" means here.** Only the weight files come from the developer. They are numbers, loaded by
   server software from the vLLM project. The model has no network path out (the box's egress rules). The origin
   matters for policy and procurement, and the hospital decides whether it accepts it.
3. **What is being corrected.** Until now the verifier's 4-bit file came from a personal Hugging Face account. The
   vendor will build the file itself from the developer's official release, record the source revision and the
   file hashes, and the box will refuse other files (DEP-008, LLM-007).
4. **What is being tested.** A non-PRC verifier (Mistral, France) and a Japan-origin one (NII), and two non-PRC
   embedders, on the same safety test as the current model. Result expected after one GPU day. The model is
   changed only if the replacement is at least as safe on wrong exclusions in that site's language.
5. **What the hospital is asked.** Does your policy, or a sponsor's, restrict models by country of origin? If
   yes, the non-PRC result becomes a go-live condition for your site. The two sites may run different verifiers.
6. **What does not change.** Unknown never excludes. A note criterion excludes only when two different models agree
   and quote the note. A person reviews every exclusion list.

Do not say that any replacement is chosen. Do not say that the models are certified or validated as medical devices.

## 9. Proposed task-card text for TB-PLAN-06

| Id suggestion | Goal | Files it touches | Acceptance tests | Depends on | Size | PoC prerequisite |
| --- | --- | --- | --- | --- | --- | --- |
| T-012 (existing), add | Own-build step: quantise from the official revision with a committed recipe; write source repo, revision, recipe sha256, manifest sha256 and licence file into the registry row (DEP-008, LLM-007) | `tools/` (a small quantise script), `models/registry.yaml`, `models/cards/` | No `null` revision or sha256 for any deployed build; the registry row of the verifier names an official source repository | GPU VM | S | no |
| new: verifier bake-off | Run section 4 on section 5's measurements; write the result as a decision record; choose per site | PR #64 `tools/judge_bakeoff.py` (`--pair`, per-language report, M1 to M10), `eval/` results outside the repo | `metrics.json` has M1 to M10 per language for three candidates; decision record signed by the owner | PR #64, LLM-031, G1 run finished | M | no |
| new: gated set per language | Grow the gated set to about 190 judge exclusions each in ja, zh-TW and en (synthetic; plus MedTxt for ja and en) | `tools/make_judge_set.py`, `tests/fixtures/llm/` | The per-language upper Wilson bound can show ≤ 2 % | none | M | no |
| T-009 (existing), add | Embedder decision with two non-PRC candidates in `bench_embed`; registry row for the embedder | `tools/bench_embed.py`, `models/registry.yaml`, `services/embed_service/embedder.py` | Four-model result table; chosen embedder pinned by `pin_model`; S2b threshold refitted | DEP-010, DEP-012 | S | no |
| new: model disclosure note | Section 8 as a one-page document in ja, zh-TW and en, with the model list generated from the registry | `docs/plan/sites/`, a small generator | The note's model table equals the registry; owner sends it | LLM-012 | S | no |

## 10. Questions for the owner

| # | Question | Recommended answer |
| --- | --- | --- |
| 1 | May the two sites run different verifiers (for example llm-jp in Japan, Ministral or Qwen in Taiwan)? | Yes, if each passes the gate in that site's language. The registry already pins builds per profile. It doubles the qualification work, so prefer one model if Ministral passes in all three languages. |
| 2 | Is "non-PRC" a hard rule or a preference? | Preference until a hospital or sponsor says otherwise. A less careful verifier is a patient-safety cost; origin is a policy cost. Decide after the bake-off, with the hospitals' answers to point 5 of section 8. |
| 3 | Own build or the RedHatAI build for the interim? | Own build. It is one GPU-hour and gives hashes the vendor controls. Use the RedHatAI INT4 build only as a cross-check. |
| 4 | Should a snowflake-arctic or BitNet embedder count as non-PRC? | No. Their base encoders are PRC-origin by their own cards. Say so if asked. |

## 11. Assumptions

- The slice for the verifier on the B200 is about 23 GB (LLM-027). If CGMH gives one slice only, the sleep swap
  applies and the VRAM column matters less.
- The pinned server stays vLLM v0.32.0 for the test, so results match the measured profile.
- Thinking stays off for the verifier where the model allows it. For models that always reason (gpt-oss, llm-jp
  thinking), the lowest effort is used and the token cap is raised; latency is then judged on M7.
- "Country of origin" means the developer's home country. A model fine-tuned in Japan or Taiwan on a PRC base is
  counted as PRC lineage; on a US base as US lineage.
- Download counts and "last change" dates are as shown by Hugging Face on 2026-11-10 and will move.
