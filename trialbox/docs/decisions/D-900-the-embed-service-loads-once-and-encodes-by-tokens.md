# D-900 The embed service loads once, encodes by tokens, and SCREEN embeds a sentence once

- **Task:** red of lane G's accuracy run (#639, 2026-11-15, tcga: the embed service died mid-SCREEN); **Date:** 2026-11-15; **Status:** reserved
- **Decision:** (1) the service loads its model once, under a lock, however many requests arrive together; (2) it encodes `TB_EMBED_CONCURRENCY` requests at a time (1), each input cut at `TB_EMBED_MAX_TOKENS` (512) tokens, in batches of at most `TB_EMBED_BATCH_TOKENS` (8192) padded tokens instead of 64 texts; (3) SCREEN keeps the vectors the service gave by model and text hash (`TB_EMBED_CACHE_VECTORS`, 20,000, about 4 kB each, in the orchestrator's memory only), so a patient's window sentences are embedded once, not once per zero-hit criterion and again per protocol.
- **Memory:** weights about 2.3 GB (fp32), runtime about 0.6 GB, one batch at the token cap under 0.6 GB: about 3.5 GB for one load; three loads at once (the run) need about 7 GB, above the 4 GB limit. The compose default (lane D's) should be 6 GB.
- **Test:** `tests/unit/test_embed_service_under_load.py`.
