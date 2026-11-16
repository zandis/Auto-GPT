# D-907 The judge key holds the criterion's text; S2b compares in numpy; the embedder loads at start

- **Task:** lane A2's review of lane G's #772 (#639, 2026-11-16); **Date:** 2026-11-16; **Status:** reserved
- **Decision:** three parts of #772 that master lacked.
  - The in-run judge cache key adds the sha256 of the criterion's text. The canonical hash drops free text, so two criteria with one note question and structure shared a cached answer whenever their sentence sets met; on D-904's whole-window path that was always.
  - S2b computes its similarities with numpy (`cosines`), giving the same numbers as `cosine`.
  - The embed service loads its model at start in every environment (before this, only in PRODUCTION).
  - Not taken: #772's average of windows at the service (D-905's best window at S2b is right for recall), its per-run vector memo (D-900's bounded cache already covers the two-phase rounds), and its 4096 batch default (the cap is 6 GB, D-890; it needs a measurement).
- **Test:** `tests/unit/test_judge_key_and_s2b_numpy.py`.
