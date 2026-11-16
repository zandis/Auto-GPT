# D-948 An atom keeps only the fields its domain uses

- **Task:** F4 of the integrator's root-cause review of the P1b run (#639, 2026-11-16). sigir's 772 compiled criteria carried fields their atoms cannot use: 25 quantifiers, 6 values and 5 `derived` on demographic atoms, and 9 ages on other atoms. NCT00606840 EXC-02 was `{"domain":"demographic","quantifier":"all","age":{"min":18,"max":35},"derived":"egfr"}`. `_convert_logic` kept every key. The demographic compile ignores them, but `derived` still built an eGFR ValueSet for the ruleset. **Date:** 2026-11-16. **Status:** reserved.
- **Decision** (`postprocess.strip_stray`, on the raw logic before `_convert_logic`):
  - **A demographic atom's stray fields are dropped.** These are `derived`, `quantifier`, `value`, `count`, `window` and `duration`. The criterion is flagged `stray_field`; an explicit `quantifier: any` is the default and is not flagged.
  - **A demographic `quantifier: none` goes to a person** (`demographic_quantifier_none`). It may mean "not", and the age compare never read it.
  - **An age on any other atom goes to a person** (`age_on_non_demographic`). It may be an age at onset ("diabetes before 30"), so dropping it would widen the criterion: an exclusion would then exclude every diabetic.
- **Not in this card:** the ValueSet keyed "NONE" that the review saw. It needs the run's criterion to trace (asked for on #639).
- **Test:** `tests/unit/test_stray_atom_fields.py`, including the stored EXC-02 output, which no longer builds an eGFR ValueSet.
