# D-796 A negated exclusion is rewritten, and a list with no code never answers

- **Task:** red of lane G's accuracy run on the real pair (#639, 2026-11-15, jmed); **Date:** 2026-11-15; **Status:** reserved
- **Decision:** (1) the compiler's post-process rewrites an exclusion whose whole logic is negated (an atom with quantifier `none`, or `not(x)`) to the positive form and flags it `negated_logic_rewritten` and `needs_review`; the review page shows the negated form beside it. A negation inside the logic and every inclusion are left alone. (2) A value set with no code and no code family (a concept the terminology could not map) cannot answer: the runtime reads the answer it would give as unknown, reason `code_system_not_carried` (D-795), on the cascade and the SQL engine.
- **Why:** jmed's "history of diabetes" compiled as "none of diabetes" over an empty list: TRUE for every patient, so every patient was excluded.
- **Test:** `tests/unit/test_negated_exclusion_and_empty_lists.py`.
