# NCBI TrialGPT upstream sources (reference copy)

Byte-for-byte copies of four files of [ncbi-nlp/TrialGPT](https://github.com/ncbi-nlp/TrialGPT) at the commit in
`COMMIT`. The code is a United States Government Work in the public domain; its notice is kept unchanged in
`LICENSE`. Please cite: Jin Q, et al. *Matching patients to clinical trials with large language models.*
Nat Commun 15, 9074 (2024).

The files carry a `.txt` suffix so that no tool imports, lints or type-checks them: the originals build a cloud LLM
client at import time, which TrialBox never does. They are read as text only:

* `registry_match/sync_prompts.py` extracts the prompt builders and scoring functions verbatim into
  `registry_match/prompts.py` and fails the NCBI prompt drift check when the two differ;
* `tests/unit/test_registry_match_core.py` executes the upstream functions from this text and compares their output
  with the vendored module.

| file | upstream path |
| --- | --- |
| `trialgpt_retrieval/keyword_generation.py.txt` | `trialgpt_retrieval/keyword_generation.py` |
| `trialgpt_matching/TrialGPT.py.txt` | `trialgpt_matching/TrialGPT.py` |
| `trialgpt_ranking/TrialGPT.py.txt` | `trialgpt_ranking/TrialGPT.py` |
| `trialgpt_ranking/rank_results.py.txt` | `trialgpt_ranking/rank_results.py` |
