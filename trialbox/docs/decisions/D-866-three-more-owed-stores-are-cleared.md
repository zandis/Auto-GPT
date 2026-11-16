# D-866 The site set-up's facts are cleared at an opt-out, and never written again (ERASE-A1)

- **Task:** ERASE-A1, lane C2's backlog after the PoC freeze (the integrator's re-plan of 2026-11-16): owed erasure entries that wait for nothing, closed by the opt-out worker's `owed_tables` clear (D-798). · **Date:** 2026-11-16
- **Decision:**
  - The worker deletes `sitesetup.fact` rows of an opted-out patient.
  - The site set-up no longer writes one again. A re-read of a sheet, from its file on disk, leaves the opted-out patients' facts out (any case). A chart of an opted-out patient is refused (`SETUP-OPTED-OUT`) before it is read or anything of it is kept. A register that does not answer stops both (`SETUP-OPTOUT`, fail closed). The register is read through the decision context's door for code outside a job (`orchestrator.decision_context.register_now`).
  - The owed list goes from 49 to 48.
- **The adversarial review (NOT SOUND on the first build), and what was withdrawn:**
  - `recall.recall_known_positive`: the same hash also sits in `draw_id`, and the certificate would add the patient again once the hash was gone.
  - `edc.draft`: "consented or enrolled in the candidate registry now" is not the test of a trial subject. A withdrawn subject, a registry that lags the lifecycle, an ODM import and a merged chart would each lose a subject's drafts.

  Both stay owed, with the gap named in the registry. `recall.recall_observation` stays owed with them.
- **Left:** `sitesetup.input`, `check_item` and `fix` stay owed: a per-patient upload's file sits on disk, and a sheet's rows are not keyed by patient. The screening log's tables (`site.pi_marks`, `site.screening_no`, `orch.candidate_events`, `study.rc_record`, `study.rc_write`) wait for LIFE-005, which is frozen.
- **Held by:** `tests/unit/test_the_worker_clears_more_owed_tables.py`, synthetic data only (failing output on master kept: `erasea-fail.txt`).
