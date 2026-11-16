# D-956 A derived value is the score its line names, compared as a number

- **Task:** G5 of the integrator's second review of the P1b run (#639, 2026-11-16). On NCT01187901 the model wrote a derived value with `value.op "in"`. `semantics.kind` returned DERIVED without `check_value`, the CQL held `(None in { })`, and the translator failed the protocol.
  - The run's traces show more: the model copies the prompt's example names onto atoms that are not those scores. Examples are "sdai" on a brain injury, "das28" on sore-throat pain, and "egfr" on an FEV1/FVC ratio or a serum creatinine.
  - With a numeric value, those would compile as eGFR < 0.7 or eGFR > 3.0.

  **Date:** 2026-11-16. **Status:** reserved.
- **Decision**
  - **In `kind`, a derived value is a score this box computes, and a comparison of it is numeric.** That means `check_value`, and `in` is refused. A derived value with no comparison is "computable" (D-149), as before. The contract's enum already refuses an unknown name; `kind` refuses it again for IR built without validation.
  - **In `postprocess`, a derived value runs only when its line names that score.** The test (`derived_said`) is by family: BMI or body mass index; eGFR, GFR or glomerular filtration (Japanese and Chinese spellings too); DAS28; BASDAI; ASDAS; CDAI; SDAI. Matching uses ASCII edges, so "eGFRが" counts. Capitals "EGFR" is the growth factor receptor ("EGFR mutation"), and names eGFR only beside a kidney word or a comparison with a number, never when an oncology word follows it (D-986, the integrator's one disambiguation card with `terms.py`). Otherwise the coded part cannot run: a person reads it, or the notes do for a mixed line once D-954 is in.
  - All 13 derived atoms in the shipped rulesets name their score, and `build_rulesets --check` is unchanged.
- **Test:** `tests/unit/test_derived_values_are_checked.py`, including the run's own misplaced names.
