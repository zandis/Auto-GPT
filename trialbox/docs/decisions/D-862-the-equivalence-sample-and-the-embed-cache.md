# D-862 The stored equivalence report names no patient; what D-513 still leaves owed is said (T-206b, part 2b)

- **Task:** T-206b, the code-complete sprint, item 4, part 2b, under the owner's ruling D-513 (a tombstone list, not a rebuild; the embed cache the one true rebuild) · **Date:** 2026-11-16
- **The equivalence report:** the criteria compiler's stored report (the draft's `tests/equivalence.json`, kept in the criteria library's history) names each disagreeing patient by a case label (`case-001`), never the pseudonym. It keeps no evidence, because the lake resource ids and dates in it lead back to the patient. The run keeps both in memory; nothing reads a stored disagreement's patient or evidence back (`enforce` reads the failing criteria and the percentages). Reports stored before this change keep theirs in the history, which is not rewritten, and an imported ruleset's zip may bring an older report in. While the kept lake exists, a case label can be re-derived by running the gate again (the sample is seeded by the ruleset and its version).
- **What the adversarial review found still owed, now said in the registry instead of filed as withheld:**
  - the mail outbox: a queued or re-sent message reads its outputs with no register check, so a list mailed after an opt-out can name the patient;
  - the compiler's equivalence sample, which reads every patient, and a direct call of the lake's `/query`;
  - a CASE chart, which is parsed before the subject's opt-out is checked;
  - the embed cache's prune.
- **The embed cache:** a prune by the current snapshot alone was built and withdrawn. It missed the vectors of older kept snapshots and deleted vectors other patients still needed there, nothing embeds a pruned vector again, and the nightly build puts the patient's vectors back. A prune must consider every kept snapshot, with the build not embedding an opted-out patient. It stays owed.
- **Held by:** `tests/unit/test_readers_drop_the_opted_out.py::test_the_stored_equivalence_report_names_no_patient`. The owed list stays at 49; the kept snapshots, outputs and attachments stay owed with their gaps named.
