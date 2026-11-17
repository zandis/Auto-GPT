# D-908 The judged-pair store

- **Task:** the owner's D-519 (2026-11-16, by way of the integrator on #639), CAS-5; lane G's review of note processing, item 4; **Date:** 2026-11-16; **Status:** reserved
- **Decision:** SCREEN keeps each model's answer to a note question in `orch.judged_pairs` (`orchestrator.judged_store`), so the same question asked again of the same build is read, not asked.
  - **The key:** the pseudonym; the criterion's canonical hash, exact wording and note question; the sha256 of the exact excerpt set (D-479); the role; the prompt id and file sha; the schema; the build answering the role (that of its latest live answer in the job); the window and the index date; `NOTE_MASK_VERSION`; the cascade's role (S3 or S4). The cascade gives the pseudonym, hash, window, role and a digest of the question (`matching.cascade.judge.ASKING`); a call whose variables are not that question (a wake check's canary case) is never keyed. The two-phase verifier answers in the question's context.
  - **What is stored:** only a parsed answer (verdict pass, fail or unknown, with a confidence) from that build. Never a refusal, a fault, an answer naming no build, or an unanswered call.
  - **Read:** the judge's and verifier's rows are stored apart and recombined by the pair rule and `decision.answer_of` (D-478) as a live answer would be. A read spends no tokens.
  - **Not read, not stored:** an audit sample (CAS-8); a pseudonym on the opt-out register, read before every write and every read that finds a row; anything when the register cannot be read (D-127). A fault of the store asks the model live.
  - **Erasure and retention:** an opt-out deletes the patient's rows (`OWED_TABLES`). At each SCREEN job's end, however it ends, the rows it wrote for patients who opted out while it ran go too. A row stays with the snapshot whose notes it read; at each SCREEN job's end (store on or off) the rows of a snapshot the site's retention (`settings.retention`, D-452) no longer keeps are deleted, by the lake's rule over every night up to the job's snapshot.
  - **Data class:** D3. Never exported, not in a support bundle, in the encrypted backup (runbook 05; the opt-out worker clears it again after a restore). Listed in the erasure registry and the record inventory.
  - **Setting and report:** `TB_JUDGED_STORE=off` turns it off. The job's summary says `judged_store: {on, read, live}` (model calls of note questions read and asked).
  - **Adversarial review (2026-11-16):** eight findings, all fixed: the store off for new jobs (snapshot read lazily), canary calls keyed under a patient (question digest), the build frozen at the first answer, opt-outs during a job, retention over the store's own snapshots, S4 sharing S3's row (role in the key), a store fault failing the job, and the report when off.
- **Test:** `tests/unit/test_judged_pair_store.py`.

## Each judge call's record names its stage and its question (H-16, 2026-11-17)

Lane H's offline review of a stored run (#970, for H-18) could not tell S3's calls from S4's: SCREEN's note calls
are all labelled with one context of use on the gateway (the v1 path's role table names the prompt, not the stage),
and the cascade's question was not recorded beside a call. Now the cascade sets `tb_common.llm.CALL_CONTEXT` around
each judge question (beside `ASKING`), and `llm.call` writes it as `asking`, with the answer schema the call used:

- `stage` (S3 for the judge, S4 for the second opinion) and the `context_of_use` the cascade's gateway client labels
  it with, and the cascade's `role`;
- the patient's pseudonym, the criterion's canonical hash, the window and the question digest (`question_digest`,
  what the models are shown), and whether it was an audit sample.

Ids and hashes only, never the question's text. With the call's prompt id, prompt sha, schema and build beside it,
the store's key can be computed from the records. The gateway labels of the v1 path are unchanged: they route the
call, and changing them is the gateway's card.
