# trec_ct: TrialBox judge on the TREC Clinical Trials 2021 / 2022 cohorts

`tools/trec_ct_eval.py`. 125 NIST patient topics, 1,700 sampled patient x trial pairs (1,200 NIST-eligible, 500
NIST-excluded), 20,096 criteria judged one at a time with the `tools/mlbench` prompt; pair-level scoring with
patient-cluster bootstrap intervals; deterministic age/sex filter from ClinicalTrials.gov structured fields.

- `results/raw/<model>.jsonl.gz`: every model answer (2026-11-05, OpenRouter; `~negation` = prompt variant)
- `results/scores.json`: single models and both-must-block pairs, LLM only / filter / filter then LLM
- `AUDIT.md`: hand check of 30 dropped eligible pairs (10 model errors, 12 label noise, 5 other-arm criteria)

NIST topics and qrels, the NCBI corpus and the CT.gov fields are fetched into `.cache/trec_ct` and not committed.
Results and reading: `docs/reviews/2026-11-05-public-data-validation.md`.
