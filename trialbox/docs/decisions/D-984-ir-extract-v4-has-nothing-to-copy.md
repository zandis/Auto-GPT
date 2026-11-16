# D-984 ir_extract v4: no example score names to copy, an age in `age`, no placeholders

- **Task:** the second half of G10 of the integrator's second review of the P1b run (#639, 2026-11-16).
  - ir_extract v3's own line, "Use `derived` = bmi | egfr | das28 | basdai | asdas", was copied into 29 criteria, on atoms that are not those scores.
  - 64 "Aged N years or older" lines put the number in `value`.
  - The model added placeholder ages (0-150) and quantifiers to other atoms.
  - D-948 (#863) repairs or refuses what reaches `postprocess`. This card removes the cause.

  **Date:** 2026-11-16. **Status:** reserved.
- **Decision.** ir_extract v4 changes three rules of the system text and nothing else; the schema and the user block are those of v3.
  - **No placeholders:** an atom gets only the fields its line states, with no placeholder age, window, quantifier or derived.
  - **Ages:** an age is `age` {min, max} in whole years on a `demographic` atom, never a `value`. An age given in months, weeks or days makes the criterion `human`, consistent with D-946 and D-947.
  - **Scores:** `derived` is used only on an `observation` atom whose line names the score (BMI, eGFR, DAS28, BASDAI, ASDAS, CDAI, SDAI), consistent with D-956.
- **Registered unqualified** (`qualification: null`): PRODUCTION keeps serving the newest qualified version (D-359), and a VALIDATION box serves v4.
  - **Its canary** is `eval/qualification/ir_extract_v4_canary.jsonl`: 110 of the run's own lines, each with what a correct answer must show (`no_derived`, `age_in_age`, `no_placeholder_age`). v3's stored answer fails every one.
  - `tools/ir_extract_canary.py` scores a version's answers on it.
  - The qualification run needs the GPU, which the owner has stopped until a review. Whether v4 passes is what only the GPU can show.
- **Tests updated for the new active version:** `test_prompt_registry` (the active ir_extract is v4) and `test_injection_hardening`. The latter still checks T-606's own versions against the ones before them, and now also requires every active version to keep the data rule and the JSON block.
- **Test:** `tests/unit/test_ir_extract_v4.py`.
