# D-908 The judged-pair store

- **Task:** the owner's D-519 (2026-11-16, by way of the integrator on #639), CAS-5; lane G's review of note processing, item 4; **Date:** 2026-11-16; **Status:** reserved
- **Decision:** SCREEN keeps each model's answer to a note question in `orch.judged_pairs` (`orchestrator.judged_store`), so the same question asked again of the same build is read, not asked.
  - **The key:** the pseudonym; the criterion's canonical hash, exact wording and note question; the sha256 of the exact excerpt set (D-479); the role; the prompt id and file sha; the schema; the build answering the role (from its first live answer in the job); the window and the index date; `NOTE_MASK_VERSION`. The cascade gives the pseudonym, hash and window (`matching.cascade.judge.ASKING`); the two-phase verifier answers in the question's context.
  - **What is stored:** only a parsed answer (verdict pass, fail or unknown, with a confidence) from that build. Never a refusal, a fault, an answer naming no build, or an unanswered call.
  - **Read:** the judge's and verifier's rows are stored apart and recombined by the pair rule and `decision.answer_of` (D-478) as a live answer would be. A read spends no tokens.
  - **Not read, not stored:** an audit sample (CAS-8); a pseudonym on the opt-out register read at the job's start; anything when the register cannot be read (D-127).
  - **Erasure and retention:** an opt-out deletes the patient's rows (`OWED_TABLES`). At the job's end, the rows of patients who opted out while it ran go too. A row goes with the snapshot of the last run that used it; D-452's retention (`tb_common.retention`) is applied when a SCREEN job starts.
  - **Data class:** D3. Never exported, not in a support bundle, in the encrypted backup (runbook 05; the opt-out worker clears it again after a restore). Listed in the erasure registry and the record inventory.
  - **Setting and report:** `TB_JUDGED_STORE=off` turns it off. The job's summary says `judged_store: {on, read, live}`.
- **Test:** `tests/unit/test_judged_pair_store.py`.
