# match_registry: registry-matching benchmark (FR-M5-14)

Vendored from the TrialGPT port (branch `claude/trialgpt-local-lcvm9p`, `trialgpt/trialgpt_local/benchmark.py`,
`datasets.py`, `metrics.py`, `benchmarks/paper_reference.json`) by S1-17. The matching code it exercises is
`services/matching/registry_match/`.

| file | content |
| --- | --- |
| `benchmark.py` | `rank` (criterion matching + aggregation + ranking on the labelled trials), `retrieval` (hybrid recall@N), `report` |
| `datasets.py` | loaders for the NCBI cohorts; `fetch` downloads them at run time (never committed) |
| `metrics.py` | NDCG@10 (linear gain), graded P@10, AUROC eligible vs excluded, recall@N, as in Jin et al. 2024 |
| `paper_reference.json` | the published values and their caveats |

Data: the NCBI TrialGPT cohorts are synthetic patients with public relevance labels (D0). They are fetched into
`.cache/match_registry/ncbi/` and are not part of the repository.

Running needs an injected model client (the tb-gateway client, S1-06), or `TB_MATCH_LLM_MODE=cassette` with recorded
responses. Only runs whose `run.json` reports `"tokenizer": "nltk"` are comparable with the paper (NLTK and its
`punkt` data reproduce NCBI's sentence numbering and BM25 tokens).

```bash
python -m eval.match_registry.datasets fetch [--zip TrialGPT-main.zip] [--corpora]
python -m eval.match_registry.benchmark report --model <label>
```

The cohorts and the NCBI code are US Government works in the public domain (see
`services/matching/registry_match/ncbi_upstream/LICENSE`). Please cite: Jin Q, et al. *Matching patients to clinical
trials with large language models.* Nat Commun 15, 9074 (2024).
