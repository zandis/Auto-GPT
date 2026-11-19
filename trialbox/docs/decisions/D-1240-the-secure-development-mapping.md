# D-1240 The secure-development mapping: SSDF and IEC 81001-5-1, one row per task or clause, checked by a test (10G-19)

- **Task:** lane J, plan 10 row 10G-19 (review 16, item 16-12; `docs/plan/47-plan-10-2026-11-18.md`): the NIST SP
  800-218 (SSDF v1.1) and IEC 81001-5-1:2021 mapping. Exit: every practice cites a file. · **Date:** 2026-11-19
- **Decision:**
  - **One register.** `docs/validation/ssdf-iec81001.csv`, beside the ISO 27001 statement of applicability
    (`docs/validation/soa.csv`, T-649c) and in its form: one row per SSDF practice (19) and task (42), and one row per
    IEC 81001-5-1 clause or subclause of clauses 4 to 9 that public summaries name. Evidence is a `;` list of
    repository paths, from `trialbox/` or the repository root, as in `soa.csv`; `path::name` also names a Python
    `def`, a Makefile target or a workflow job inside the file.
  - **Four statuses**, plus one for the standard we cannot read: `met`, `partly`, `not met`, `not applicable` (with
    the reason), and `unverified against the standard's text` for an IEC clause whose number public summaries imply
    but whose content they do not give. A row is `met` only when the cited file does the thing on `master` today; a
    plan or design document supports at most `partly`. A `partly` or `not met` row carries the gap in one sentence,
    its weight (high, medium, low), the rough size to close it (S, M, L) and the plan-10 card that would close it, or
    `no card`.
  - **A practice row is derived** from its task rows: the tasks' common status when they agree (ignoring
    `not applicable`), else `partly`. The test holds this, so a practice row cannot claim more than its tasks.
  - **The SSDF identifiers are data in the test**, copied from NIST's own table of SP 800-218 v1.1
    (`nist.sp.800-218.ssdf-table.xlsx`, February 2022): 42 task ids, each present exactly once. SSDF is a US
    government work and its titles may be quoted.
  - **IEC 81001-5-1 is copyrighted and was not read.** Its rows give the clause number and a short title in our own
    words, from public summaries named in the document; nothing of the standard's text is copied, and every IEC row
    says `unverified against the standard's text` in its `source` column. A person holding the purchased standard
    (and its interpretation sheet 1 of 2025) checks the clause list before any claim to a customer or auditor.
  - **The page for people** is `docs/security/11-secure-development-mapping.md`: a summary table by group and the
    gaps by weight with their size. The test holds the page to the register (its counts and its list of gaps), so
    the two cannot drift.
  - **No claim.** This is a self-assessment. Neither the register nor the page claims conformity to either document,
    or any certification.
- **Held by:** `tests/unit/test_ssdf_iec81001.py`.
