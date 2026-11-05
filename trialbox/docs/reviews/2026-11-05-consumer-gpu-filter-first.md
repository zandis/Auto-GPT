# TrialBox on a consumer GPU, filter first (2026-11-05)

Question (Changfu): have smaller models been assessed, can TrialBox run on a consumer card, and does that change if deterministic filters run first and the LLM only reads notes? Japanese is required.

## Short answer

Yes. With filter first, one RTX 4090 or 5090 is enough for screening, provided the LLM is not allowed to exclude a patient on its own on a single-card box. Two cards (or one 5090 that swaps models) can run the two-model "both must block" rule. Gemma 4 26B and Qwen3.6 35B are the consumer pair; on Japanese notes it loses 6 of 79 eligible pairs, against 4 for today's Spark pair. Not yet measured: 4-bit builds and models under 25B. Those runs are waiting for a fresh OpenRouter key.

## How the filter-first replay works

All 1,003 criteria in the TrialGPT SIGIR benchmark were labelled by route (Fable, file `eval/trialgpt_compare/criteria_routes.jsonl`). The labels assume the coded data a Japanese or Taiwanese hospital EHR holds: age, sex, ICD diagnoses, prescriptions, labs and vitals, procedures.

| route | share | who decides |
| --- | --- | --- |
| filter | 36 % | CQL/SQL on coded data, no LLM |
| mixed | 27 % | filter pre-checks the coded part, the LLM reads notes for the rest |
| notes | 16 % | LLM on notes or reports |
| human | 21 % | coordinator (consent, willingness, investigator judgement); never sent to the LLM |

So the LLM reads **42 %** of criteria. `python -m tools.trialgpt_compare filterfirst --lang en|ja|zh-TW` replays the recorded 25 Oct model answers on top of that routing. It assumes the filter is perfect, which is the optimistic case: real coding errors and missing codes would add losses on the filter side.

## Results (79 eligible patient × trial pairs; "lost" = wrongly excluded)

| setup | hardware | lost en: all-LLM → filter first | ja | zh-TW | block recall en, filter first |
| --- | --- | --- | --- | --- | --- |
| filters only, LLM may not exclude | CPU, or any card | 0 | 0 | 0 | 0.39 |
| gpt-oss-120b + Gemma 4 (today) | Spark / RTX PRO 6000 | 8 → **5** | 4 | 6 | 0.64 |
| Gemma 4 + Qwen3.6 (both must block) | 2× 4090, 2× 5090, or one 5090 swapping | 10 → **7** | 6 | 8 | 0.67 |
| Gemma 4 26B alone | one 4090 / 5090 | 15 → **11** | 9 | 10 | 0.70 |
| Qwen3.6 35B alone | one 5090 | 22 → 12 | 11 | 14 | 0.70 |
| Nemotron Nano 30B alone | one 4090 | 33 → 22 | – | – | 0.58 |

Block recall is the share of true exclusions that get caught. With perfect coded data, the filters alone catch 39 % of true exclusions and lose nobody. That matches the recall today's model pair reaches without filters (0.39).

The Japanese and Traditional Chinese notes are machine translations and were not checked by a clinician. Do not quote these numbers to a site.

## Design (Fable's recommendation, condensed)

1. **No LLM:** parse the protocol; run every structured criterion as CQL/SQL; send `human` criteria straight to review. If retrieval finds no note text for a criterion, record "unknown" and skip the call; that cuts LLM calls by about half again.
2. **Small local LLM (patient data stays on the box):** judges note and mixed criteria, only for patients who passed the filters. A nightly run is about 300 patients × 5 note criteria ≈ 1,500 checks, under an hour on a 4090. Speed is not the constraint; memory and quality are.
3. **Bigger model, only for protocol reading** (`ir_extract`: once per trial, no patient data). Use the cloud model behind the PHI guard, or gpt-oss-120b when the hospital forbids cloud. A misread criterion affects every patient, and a human approves the result anyway.
4. **Blocking policy per site, set by hardware:** `never` on one card (the LLM can move a patient up or to review, never out). `both_agree` with two models (two different models must block, citing the same evidence).

| tier | models | block policy |
| --- | --- | --- |
| CPU only | none | filters only; note criteria go to review |
| 1× RTX 4090 24 GB | Gemma 4 26B-A4B Q4, 8k | never |
| 1× RTX 5090 32 GB | Gemma Q4, then Qwen3.6 Q4 in a second pass (model swap) | both_agree |
| 2× 4090 / 2× 5090 | pair loaded together | both_agree, more candidates per night |
| Spark / RTX PRO 6000 | gpt-oss-120b + Gemma FP8, 32k | both_agree, long-context fallback, local protocol reading |

**Japanese.** What matters in a model: tokenizer efficiency on kanji (Gemma and Qwen are built for CJK), valid JSON in Japanese, and exact quotes. Normalise text to NFKC before the quote check. Test on real de-identified notes, about 300 items stratified by:
- negation and status: 否定, なし, 認めず, (-)/(+), 疑い, 既往, 家族歴
- 和暦 dates: 令和6年3月, R6.3.15
- mixed terms: CKD stage 3, DM(-), Ope歴
- jRCT protocols, for protocol reading

**What proves "small is enough".** Run the exact Q4 files on the exact engine on the card. Bars on note criteria:
- false-block ≤ 1.0 % (upper 95 % ≤ 2 %)
- eligible pairs lost within 1 pair of the full-precision pair
- valid JSON ≥ 99.5 %
- quote-not-found ≤ 5 %
- block recall ≥ 0.35

79 pairs is thin, so add TREC-CT pairs and at least 100 site-adjudicated pairs before any site runs `both_agree`.

**Risks.**
1. Quantisation is unmeasured; every number above is full precision.
2. 24 GB rules out the long-context fallback, so more criteria go to review.
3. Hospital IT may reject GeForce cards: no ECC, datacenter licence terms for the driver, no vendor support. If buying, buy the 5090 over the 4090, so the pair stays possible.

## Sizing (`python -m tools.gpu_sizing`, estimates only)

| card | plan | memory used | headroom |
| --- | --- | --- | --- |
| RTX 3090 / 4090 (24 GB) | Gemma 4 26B Q4, 8k, 2 sequences | 19.8 GB | 4.2 GB |
| RTX 5090 (32 GB) | Gemma 4 26B Q4, 16k, 4 sequences | 24 GB | 8 GB |
| 2× 4090 | Gemma Q4 + Qwen3.6 Q4, 8k, 1 sequence | – | 5.1 GB and 0.2 GB (tight) |
| 2× 5090 | Gemma Q4 + Qwen3.6 Q4, 16k, 4 sequences | – | 8 GB and 3 GB |

- The pair does not fit loaded together on one 5090; it has to swap models between passes.
- Dense 27–31B models (Gemma 4 31B, Qwen3.8 27B) fit a 5090 but run at about 1/7 the speed of the MoE models.
- A 16 GB card is about 0.4 GB short for gpt-oss-20b once the engine allowance is counted.

## Still to run (needs `OPENROUTER_API_KEY`)

```
python -m tools.trialgpt_compare run --pipelines trialbox --langs en ja \
  --models google/gemma-4-26b-a4b-it@fp4 qwen/qwen3.6-35b-a3b@fp4 openai/gpt-oss-20b \
           google/gemma-4-31b-it qwen/qwen3.8-27b qwen/qwen3.5-9b
python -m tools.trialgpt_compare filterfirst --lang ja
```
