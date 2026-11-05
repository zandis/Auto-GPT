# trialgpt_compare: TrialBox S3 judge vs TrialGPT-Matching on TrialGPT's own data

Same models, same physician-labelled pairs, same scorer (`tools.mlbench.score`).

| side | prompt | calls |
| --- | --- | --- |
| TrialBox | `judge_ml` from `tools/mlbench.py` (one criterion, label + evidence ids, "absence is not a negative finding") | 1 per criterion |
| TrialGPT | NCBI matching prompt, verbatim from `services/matching/registry_match/prompts.py` | 1 per patient × trial × inclusion/exclusion |

Data: `eval/criterion_ml` (NCBI TrialGPT-Criterion-Annotations, 53 SIGIR patients, 105 patient × trial pairs) plus
NCBI's `trial_info.json` for each trial's full criteria list (fetched into `.cache/trialgpt_compare/`, not committed).
15 of the 1,015 annotated criteria are not in `trial_info.json` word for word; both sides are scored on the other 1,000.

```bash
python -m tools.trialgpt_compare fetch
OPENROUTER_API_KEY=... python -m tools.trialgpt_compare run --models openai/gpt-oss-120b google/gemma-4-26b-a4b-it --langs en ja zh-TW
python -m tools.trialgpt_compare score   # writes results/scores.json
```

`results/raw/*.jsonl.gz` holds every model answer of the 2026-10-25 run (OpenRouter, temperature 0, thinking off where
the model allows it, low effort otherwise; same settings on both sides; $4.39 billed). `trialbox_s4|a+b` rows are
scored from the recorded single-model answers with the rule "a criterion blocks only when both models block it".

Results of that run (English notes, 1,000 criteria, 79 eligible patient × trial pairs):

| model | pipeline | false-block | eligible pairs lost | accuracy | $ / 1k criteria |
| --- | --- | --- | --- | --- | --- |
| GPT-4 (published labels) | TrialGPT | 1.3 % | 8 / 79 | 87.3 % | — |
| gpt-oss-120b + Gemma 4 (both must block) | TrialBox | 1.0 % | 8 / 79 | 50.1 % | 0.083 |
| gpt-oss-120b | TrialBox / TrialGPT | 2.3 % / 6.0 % | 15 / 27 | 50.0 % / 69.2 % | 0.041 / 0.029 |
| Gemma-4-26B-A4B | TrialBox / TrialGPT | 2.6 % / 4.6 % | 15 / 16 | 65.2 % / 72.3 % | 0.042 / 0.027 |
| Qwen3.6-35B-A3B | TrialBox / TrialGPT | 3.2 % / 6.3 % | 22 / 24 | 51.3 % / 74.9 % | 0.101 / 0.179 |
| Nemotron 3 Nano 30B | TrialBox / TrialGPT | 12.7 % / 8.3 % | 33 / 35 | 61.6 % / 55.2 % | 0.038 / 0.038 |
| Hermes 4 405B | TrialBox / TrialGPT | 4.0 % / 7.0 % | 22 / 33 | 67.2 % / 67.1 % | 0.564 / 0.386 |
| GPT-4.1 | TrialBox / TrialGPT | 1.8 % / 12.9 % | 13 / 54 | 50.7 % / 71.1 % | 1.183 / 0.903 |

TrialBox's prompt abstains ("not enough information") where the physicians, following TrialGPT's guideline, assumed an
unmentioned fact absent; that costs exact-label accuracy and keeps patients. 79 eligible pairs is a small denominator:
one pair is 1.3 points. Translations of the notes (ja, zh-TW) are machine-made and not clinician-checked.

Cite: Jin Q, et al. *Matching patients to clinical trials with large language models.* Nat Commun 15, 9074 (2024).
