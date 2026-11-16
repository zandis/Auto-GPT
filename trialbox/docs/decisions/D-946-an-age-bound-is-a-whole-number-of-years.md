# D-946 An age bound is a whole number of years

- **Task:** F2 of the integrator's root-cause review of the P1b run (#639, 2026-11-16). NCT01260883 INC-02, "Aged 0.17 years or older", compiled as `age.min 0.17`, and INC-03 as 1.5. The age is counted in complete years (D-442: `AGE_SQL`, CQL `AgeInYearsAt`), so a two-month-old is 0 and never meets 0.17. Every infant failed an inclusion they meet. **Date:** 2026-11-16. **Status:** reserved.
- **Decision.** A non-integer age bound is a `CompileError` in `semantics.kind`, next to D-914's negative and reversed bounds:
  - in `postprocess` it is flagged `logic_invalid` and a person reads it (D-910);
  - an approved one is moved to a person by `demote_uncompilable` (flag `compile_error`);
  - the SQL and CQL generators refuse it.
- **Not chosen:** comparing in months. The SQL and CQL ages would both have to change together, at the risk of drifting the shipped rulesets, which today have whole-year bounds only (`build_rulesets --check` is unchanged). It can follow if the owner wants pediatric bounds automated.
- **Not in this card:** F3, ages written in months, weeks or days ("2-18 months" read as 2 to 18 years), which is D-947.
- **Test:** `tests/unit/test_fractional_age_bound.py`.
