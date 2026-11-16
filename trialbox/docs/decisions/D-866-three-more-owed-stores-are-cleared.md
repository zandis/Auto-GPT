# D-866 Three more owed stores are cleared at an opt-out (ERASE-A1)

- **Task:** ERASE-A1, lane C2's backlog after the PoC freeze (the integrator's re-plan of 2026-11-16): owed erasure entries that wait for nothing, closed by the opt-out worker's `owed_tables` clear (D-798). · **Date:** 2026-11-16
- **Decision:**
  - `edc.draft`: a never-consented patient's EDC drafts go. A subject the candidate registry shows as consented or enrolled keeps them (OD-8), and so does any draft already signed or sent, which is the record of what was done. With no candidate registry to tell a subject from a never-consented patient, the clear fails and is retried; it is never called done.
  - `recall.recall_observation` and `recall.recall_known_positive`: the recall ledger keeps each draw, because the recall estimate counts it. Its `pid_hash` (an unsalted hash of the pseudonym, linkable) becomes a random `erased:` token, so the patient can no longer be found in it.
  - `sitesetup.fact`: a fact read from an uploaded file, by pseudonym, goes.
- **Why:** each was owed with a clear that needs nothing from another lane. The owed list goes from 49 to 45; `KNOWN_OWED` and the generated page move.
- **Left:** `sitesetup.input`, `check_item` and `fix` stay owed. A per-patient upload's file sits on disk, and a sheet's rows are not keyed by patient. They are the next card. The screening log's tables (`site.pi_marks`, `site.screening_no`, `orch.candidate_events`, `study.rc_record`, `study.rc_write`) wait for LIFE-005, which is frozen.
- **Held by:** `tests/unit/test_the_worker_clears_more_owed_tables.py`, synthetic data only (failing output kept: `erasea-fail.txt`).
