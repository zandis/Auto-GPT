# D-1360 The answer store: one answer per patient, criterion and ruleset version (10A-4)

- **Task:** lane A2, plan 10 row 10A-4 (review 15, card B16-11; commitment C-5: "patient × criterion × rule-set
  version → status, reason, rung, quote, date, flip date; every finding service reads it and none re-implements
  matching; it is erased with the patient"). · **Date:** 2026-11-19
- **Decision:**
  - A new table `orch.answers` (orch schema version 7), primary key (pseudonym, ruleset, version, criterion):
    status, reason code, rung, basis, `final`, quote, quote date, flip date, index date, snapshot, job id, time
    written.
    `orchestrator.answer_store` writes and reads it; `orchestrator.db.JobDB.answer_store_*` are the statements, all
    static SQL.
  - **What is stored is the answer as the run gave it**, the same row the candidate list carries: the status, the
    reason code (never the engine's or a model's words, D-118), the basis (D-478: records, a pair, a single model, a
    person), `final` (D-476) and the verified quote and its date. No new decision is made. Every reader shows a
    stored answer through `answer_store.shown` (`tb_common.verdict_word.shown_of`): a single model's "not met", or one
    given while notes could not exclude, is an open point, never "not met" (the adversarial review, H2).
  - **The rung** is the cascade's stage that gave the answer (`S0` to `S5`), carried from the trace on
    `PatientVerdicts.rungs`; the v1 path (MICROBATCH's re-check) has no stages and stores none, so a re-check's answer
    on the same day as a screen's replaces the screen's rung with none. **The flip date** is none until criterion
    model v3 computes it (10A-5).
  - **Who writes:** SCREEN, every answer of the run after the opt-outs, listed or not (an excluded patient's too);
    MICROBATCH, the re-check's fresh answers (a stored answer that stood because nobody was asked, D-642, is not
    written again), the full screens of another criteria version, and the screens of new and excluded patients.
  - **The latest answer stands:** a run of a later or the same index date replaces a stored answer; an older one (a
    re-run of a past day) never does. An answer nobody gave (not evaluated, the model down: D-642) never replaces a
    "met" or "not met" stored before; it is stored only where none is (the review, M2).
  - **Who reads:** MICROBATCH tells a patient listed again (an excluded patient screened again) which criteria
    changed against the answers last stored for them, in the same "changes" table the re-check fills for a pool row.
    The excluded pool rows' answers are read before the re-check writes any, so a row re-checked and then screened
    again is told against the answers stored before this job (the review, M1). Not a change: a criterion with no
    stored answer, an answer nobody gave on either side, a criterion the re-check already named, and two answers
    that show alike (a stored single-model "not met" and a fresh "unknown" both read as open). CASE shows, beside each criterion's answer on the sheet, the answer the last
    screening of the same ruleset version stored (status and index date on the sheet; status, rung, basis and index
    date in the JSON record), for a patient in the hospital data only (a pseudonym the screening knows), never for a
    chart alone. Display only: the sheet's own answer is not changed by it.
  - **Opt-out (D-513):** the register is read before every write and every read; a patient on it is neither written
    nor read; a register that does not answer means no write and no read (D-127). After a write the register is read
    again and the rows of a patient who opted out meanwhile are deleted at once; when that second read does not
    answer, the opt-out worker's next tick deletes them (every tick clears every patient on the register). The opt-out worker's clear deletes
    the rest (`datacore.optout_worker.OWED_TABLES`, `orch.answers`); the erasure registry lists it under
    `owed_tables`; a restore is followed by the same clear (the restore drill names it).
  - **Retention (D-452):** a row stays with the snapshot whose notes its quote came from; at each write the rows of a
    snapshot the site's retention no longer keeps are deleted, by the judged-pair store's rule (`kept_snapshots`), and
    the nightly RETENTION job sweeps the same against the lake's current snapshot, so a study that stopped screening
    does not keep its rows (the review, L3; the report says `answer_rows_deleted`).
  - **A fault of the store is never the run's:** the whole write, its clock and its sweep are inside the guard; the
    list is sent, the fault is logged, nothing is stored (the review, H1: 50 MICROBATCH tests whose stand-in job has
    no clock had failed). `record` returns the answers sent to the store; an older run's are sent and not taken.
  - Class D3: in the trial database, never exported, never in a support bundle; the record inventory maps the table
    to R-18 with the orchestrator's others; the backup runbook names it.
- **Not in this card:** the patient view (10A-13), alerts (10A-12) and the watch-list (10A-11) read the store when
  they are built; the flip date is 10A-5's.
- **Held by:** `tests/unit/test_answer_store.py`; `tests/unit/test_migrations.py` (orch version 7);
  `tests/unit/test_optout_clears_the_owed_tables.py` (`orch.answers`).
