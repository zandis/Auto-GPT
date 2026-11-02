# Vendored upstream code

`ncbi_trialgpt/` is an unmodified copy of [ncbi-nlp/TrialGPT](https://github.com/ncbi-nlp/TrialGPT) at the commit in
`ncbi_trialgpt/COMMIT` (public domain, US Government work; see its `LICENSE`). It is kept for traceability only: the
code that runs is `trialgpt_local/`, which reuses its prompts verbatim (checked by `tests/test_core.py` and `tools/sync_prompts.py --check`) and
replaces the Azure OpenAI client with a local Ollama / OpenAI-compatible endpoint. The datasets are not vendored;
`make data` downloads them.
