# D-796 A negated exclusion is rewritten, and a list with no code never answers

- **Task:** red of lane G's accuracy run on the real pair (#639, 2026-11-15, jmed); **Date:** 2026-11-15; **Status:** reserved
- **Decision:** (1) the compiler's post-process rewrites an exclusion whose whole logic is negated (an atom with quantifier `none`, or `not(x)`) to the positive form and flags it `negated_logic_rewritten` and `needs_review`; the review page shows the negated form beside it. A negation inside the logic and every inclusion are left alone. (2) A value set with no code and no code family (a concept the terminology could not map) cannot answer: the runtime reads the answer it would give as unknown, reason `code_system_not_carried` (D-795), on the cascade and the SQL engine.
- **Why:** jmed's "history of diabetes" compiled as "none of diabetes" over an empty list: TRUE for every patient, so every patient was excluded.
- **Test:** `tests/unit/test_negated_exclusion_and_empty_lists.py`.

## A negated inclusion with presence logic goes to a person (card 10A-1, 2026-11-18)

Review 15 (finding 2.3.1): "PRIOR CONCURRENT THERAPY: No prior chemotherapy or radiotherapy", an inclusion, compiled
to "any of chemotherapy", which the patients it should exclude meet; item (1) leaves inclusions alone and nothing else
compared a coded inclusion with its line. An inclusion (structured or mixed) whose logic asks the presence of a
concept that a negation in its line governs is flagged `negated_inclusion_presence` and `needs_review` and goes to a
person; it is not rewritten (a rewrite could be wrong too). "Governs" is read as ConText reads a sentence: a cue
before the concept's name or a synonym (or after it, for "not allowed", "なし", "未曾…"), in the same clause and within a
few words; a bound ("no more than 2", "超えない", "無…大於") is not a negation; an atom that compares a value,
counts or takes the latest result asks a measure, not a presence. A line that never names its concept goes to a
person when it holds any cue. An approved inclusion an incremental compile reuses gets the same check and the same
flag, with a warning, so its reviewer sees why it came back. Cue lists:
`services/criteria_compiler/ir_extract/negation_scope.py` (English adapted from medspaCy's ConText rules, MIT).
Test: `tests/unit/test_negated_inclusion_never_compiles_as_presence.py` over
`tests/fixtures/negated_inclusion/lines.json`.
