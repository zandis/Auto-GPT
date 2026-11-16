# D-783 SCREEN ranks note sentences with the box's embed service when it serves a real model; that score never rescues on the placeholder

- **Task:** NEW-LLM-2, embedder step (deep review 2026-11-12, LLM-002)
- **PR:** #589
- **Date:** 2026-11-14
- **Status:** proposed; needs `orchestrator` among the callers of `embed-service` in `tb_common.service_auth.CALLERS`
  (lane C2, or the owner's yes in lane A2's session)
- **Builds on:** D-781 (not evaluated without retrieval), D-449 (stored vectors never decide a rescue before the
  refit), D-127 / D-128 (service auth)

## Decision

1. Each SCREEN job asks the box's embed service once (`screen_cascade.job_embedder`). If it serves a real model, the
   job ranks note sentences with it. If there is no service URL, it serves the hash stub, or it does not answer, the
   job keeps the local hash embedder, and the log says why.
2. If the service stops answering or changes its model after the probe, the job stops with a sentence. It never mixes
   two embedders in one run.
3. The S2b threshold is a public-prior placeholder set for the hash stub (CAS-14), and a real model's similarities clear
   it almost always. So in the index-condition sweep (CAS-11), a real model's above-threshold on-the-fly score never
   rescues an index condition until the refit. A rescue held back is never an absence either: a person looks. A score
   below the threshold keeps its earlier path.

## Test

`tests/unit/test_screen_embed_service.py`.
