# D-948 An atom keeps only the fields its domain uses

- **Task:** F4 of the integrator's root-cause review of the P1b run (#639, 2026-11-16), and the first part of G10 of the second review. **Date:** 2026-11-16. **Status:** reserved.
  - **What the run's 1,032 extracted sigir criteria carried** (`raw-traces.json`):
    - On demographic atoms: 111 quantifiers, 134 values and 8 `derived`.
      - Every demographic `quantifier: none` is on a plain age or sex line ("Aged 40 years or older", "Female participants only").
      - 64 of the "Aged N years or older" lines put the number in `value` instead of `age`, so they went to a person.
      - NCT00606840 EXC-02 is one of the 8 `derived`: quantifier all, derived egfr.
    - On other atoms: 35 ages and 29 `derived` names. 28 of the ages are numbers not written in the line, such as the prompt's 0-150; the names include the prompt's "asdas".
  - **What the compile did with them:**
    - It ignored the demographic fields and an age on a non-demographic atom.
    - It refused a `derived` name off an observation atom, so the whole line went to a person.
- **Decision** (`postprocess.strip_stray`, on the raw logic before `_convert_logic`). A field an atom cannot use is dropped and flagged. Only a line whose own words may give the field a meaning goes to a person. Holding every case for a person would have demoted more lines, which is G9's loss.
  - **Demographic atoms**
    - `derived`, `quantifier`, `value`, `count`, `window` and `duration` are dropped (`stray_field`). An explicit `quantifier: any` is the default and is not flagged.
    - An age written in `value` becomes `age` (`value_read_as_age`), but only when it is unambiguous: all of the conditions below must hold.
      - The concept is age or none.
      - The unit is years or none.
      - The op is `>=`, `<=` or `between`.
      - The line's numbers are exactly the value's numbers.

      So "Age 50 to 89 years" written as `value >= 50` is not repaired, because its 89 would be lost. `>` is not repaired either, because "over 18" may mean 18 or 19.
    - A `quantifier: none` on a line with a negation word goes to a person (`demographic_negated`). The age compare never read the "not".
  - **Other atoms**
    - A `derived` name off an observation atom is dropped (`stray_field`), and the line now compiles.
    - An age is dropped (`stray_field`) unless the line writes its numbers next to an age word. In that case it may be an age at onset ("diabetes before age 30"), so it goes to a person (`age_on_non_demographic`). Dropping it would widen the exclusion to every diabetic.
- **Effect on answers:**
  - Dropping an ignored field changes no answer.
  - A line that kept a placeholder `derived` name, or that put its age in `value`, now compiles where it went to a person before.
- **Not in this card:**
  - The second part of G10: the prompt's example derived names, which the model copied into 24 criteria. That fix is a new prompt version with its canary.
  - The ValueSet keyed "NONE" the review saw.
- **Test:** `tests/unit/test_stray_atom_fields.py`, using the run's own lines.
