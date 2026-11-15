# D-804 The kept files are withheld on read (T-206b, part 2a; the owner's ruling D-513)

- **Task:** T-206b, the code-complete sprint, item 4, part 2a. D-513 (the owner, 2026-11-15) chose a tombstone list over a rebuild: a file that names an opted-out patient stays until retention rewrites it, and every reader drops the patient on read. · **Date:** 2026-11-15
- **The lake:** every job's per-patient read of the lake is already scoped without an opted-out pseudonym, at receipt (`ctx.decision.drop`) and again at publish (`drop_now`), and audited by count (D-441): SCREEN, MICROBATCH, NAV, CASE, FEAS and COHORT (`uncounted`), and the cascade through its given population. The derive batch skips the register (D-798). The adversarial review rejected a second filter at the lake (`PinnedLake`): it hid the audited counts, changed the scope read at receipt, and still missed pid-keyed queries and note searches. It is not built.
- **Outputs and records:**
  - The console's two raw downloads of a patient-level output refuse a file that names a patient opted out since it was made, as the workbook download already did. A per-patient file (its name carries the pseudonym's prefix: a TWPAS bundle, a draft) is judged by its own patient. A list in text is judged by its content, in any case. A compressed list is judged by the job's text lists.
  - A FEEDBACK row naming such a patient is refused. A SUBMIT of a TWPAS bundle for one is refused.
  - `orch.submissions`: a dry run goes, and a live submission stays (D-513). The owed list goes from 50 to 49.
- **Still owed (part 2b):**
  - the criteria compiler's equivalence sample, whose role cannot read the register;
  - a direct call of the lake's `/query`;
  - the embed cache's rebuild, the one true rebuild D-513 asks for;
  - the mail of a job's outputs, which reads them at publish.

  The registry's lake and output entries say this.
- **Held by:** `tests/unit/test_readers_drop_the_opted_out.py` (failing output kept: `t206b2-fail.txt`). The SUBMIT guard has no test of its own: it sits behind the NAV job's routing checks. The registry's pinned lists move as a clear-adding card moves them.
