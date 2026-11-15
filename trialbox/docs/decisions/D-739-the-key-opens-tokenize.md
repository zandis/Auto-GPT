# D-739 model-guard lets `POST /tokenize` through, with the key only

- **Task:** GUARD-TOKENIZE, lane G's blocker 8 for R4 (G-1 on the shipped server)
- **PR:** this branch (`agent/GUARD-TOKENIZE-the-key-opens-tokenize`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Changes:** D-177 (model-guard: only `/v1/models`, `/v1/chat/completions`, `/v1/completions` with the key)

## Context

vLLM checks its API key only under `/v1`; `/tokenize` and other routes answer without it, so model-guard (D-177)
answered 404 to everything else, with or without the key. Lane G's G-1 counts tokens with the server's own
tokenizer and chat template (`tools/g_probes.py`, `tools/chat_template_check.py`): on the shipped server only its
identity half could run.

## Decision

1. `POST /tokenize` joins the keyed paths: without the key or with another it is 401 and never forwarded; with it,
   it is forwarded as is. Any other method, a query, a trailing slash or another spelling stays 404.
2. Why it is safe: the key already opens `/v1/chat/completions`, which takes the same text and does more than count
   its tokens. The gateway holds the key; nothing new is reachable without it.
3. Everything else D-177 refused stays refused: `/invocations`, `/detokenize`, `/score`, `/pooling`, `/classify`,
   `/metrics`, `/collective_rpc` and the rest, with or without the key.
4. The box rehearsal's `guard` part checks that `/tokenize` without the key is 401 (the stand-in counts any
   `/tokenize` as an open call, so the keyed pass is the unit test's).

## Test

`tests/unit/test_model_guard.py::test_tokenize_passes_with_the_key_only`: before, failed (404 with the key); after,
passed. `/tokenize` leaves the list of `test_vllm_routes_that_skip_the_key_never_reach_it`; every other path stays.
