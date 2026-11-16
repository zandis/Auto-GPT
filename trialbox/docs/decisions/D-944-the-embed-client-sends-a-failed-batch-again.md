# D-944 The embed client sends a failed batch again

- **Task:** T-701 (F-15 of `docs/reviews/2026-11-11-scale-timeouts.md`; wave 6 of plan v7, built now by the owner's ruling D-1027): one failed batch in 1,000 does not stop the rebuild, and the rebuild shows its progress. Lane A2's backlog (#639, 2026-11-16). **Date:** 2026-11-16. **Status:** reserved.
- **Decision:**
  - **A failed batch is sent again.** `HttpEmbedder` sends a batch again when the service did not answer it for a reason of its own: no connection, a timeout, a 5xx, or a 429. It waits 2, 5 and 15 s (`RETRY_WAITS`) and logs each retry; `retried` counts them.
  - **What still raises.** A refusal of the request itself (a 4xx other than 429) raises at once, and so does the fourth failure. A service that is gone stays an error the caller sees.
  - **Progress.** The lake rebuild's embedding loop logs "embedding chunks: n of m" about every tenth of the work. That is one line in `services/lake/store.py`, lane B2's file.
- **Not in this card:** the GPU half of T-701 (the rtxpro6000 profile reports `cuda`; `deploy/` is lane D's). It waits for a measured run on the card.
- **Test:** `tests/unit/test_embed_retry.py`.
